"""Forecast a launch day's Twitch audience, hour by hour, from its first hour.

Written for make.fun's gta6-twitch-ccu-forecast-01. The program reads one case
file per run (schema makefun/twitch-ccu-case/v1): the case game's release day,
its hour-1 viewer print, and a library of past launches ("comparables"), each
with an hourly viewer curve spanning its own release day.

Method, in one paragraph: a launch day's *shape* is far more alike across big
games than its *scale* is, so the forecast is built from shapes. Every
comparable contributes, for each hour h of its release day, the log ratio
ln(viewers_h / viewers_1). The forecast for this case is the case's own hour-1
print multiplied by exp() of the cross-comparable quantiles of those ratios,
one set of five quantiles per hour. Two corrections are applied, both tuned by
leave-one-out validation over the comparables themselves (each comparable
forecast from all the others, scored with the contest's log pinball loss):

  * comparables whose hour 1 is under 2% of their own day peak are dropped:
    they unlocked late in the UTC day (a single global unlock in the
    afternoon, say), so their hour 1 is a pre-launch trickle and their ratios
    are hundreds-fold explosions that say nothing about a rolling-midnight
    launch like this one;
  * the median log ratio is shrunk 10% toward zero (toward persistence) and
    the spread around it is scaled by 0.95, because the raw cross-launch
    quantiles are a touch overconfident on held-out launches; every log
    quantile is also capped at 1.8 (about 6x hour 1), the largest same-day
    ratio any rolling launch in the library actually reaches, which trims
    tail noise from the few remaining late unlockers.

The quantile curves are smoothed with a three-hour moving average in log
space, since neighbouring hours of a real audience curve move together and
the per-hour empirical quantiles are noisy with only ~35 curves in the pool.

Validity is treated as a hard constraint, not a hope: whatever the input
looks like, the program always writes exactly 23 rows for hours 2..24, five
finite, positive, non-decreasing quantiles each, clamped to at most 1e9. If
the comparables are unusable it falls back to a widening band around hour 1,
and if even hour 1 is missing it falls back to the last history value, then
to a plain constant. The program is deterministic: every collection it
iterates is sorted first, and it uses no randomness, clock or network.

Run locally with:
    mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
The grader instead leaves both variables unset and uses /input and /output.
"""

import json
import math
import os
import sys
from pathlib import Path

# The grader invokes python3 -P, which keeps this file's folder off sys.path;
# restore it so sibling modules (none today, but harmless) would import.
sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

DEFAULT_LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
# Standard-normal quantiles at DEFAULT_LEVELS, for the fallback band only.
FALLBACK_Z = [-1.645, -0.674, 0.0, 0.674, 1.645]
FALLBACK_SIGMA = 0.18

# Tuning constants, chosen by leave-one-out over the comparables (see the
# module docstring): minimum hour-1 share of a comparable's day peak for the
# comparable to enter the pool, the median shrink toward persistence, the
# spread scale around the median, and the cap on any log quantile.
MIN_HOUR1_SHARE = 0.02
MEDIAN_SHRINK = 0.90
SPREAD_SCALE = 0.95
LOG_CAP = 1.8

MAX_VIEWERS = 1_000_000_000.0


def positive_number(value):
    """Return value as a float when it is a finite number above zero, else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def release_day_curve(comparable):
    """Map hour-of-day (1..24) to mean viewers for one comparable's release day.

    Points are the comparable's hourly entries whose timestamp falls on its
    day_start date. Duplicate hours are averaged. Hours with no usable point
    are simply absent from the returned dict.
    """
    day_start = comparable.get("day_start")
    if not isinstance(day_start, str) or len(day_start) < 10:
        return {}
    date = day_start[:10]
    totals = {}
    counts = {}
    hourly = comparable.get("hourly")
    if not isinstance(hourly, list):
        return {}
    for point in sorted(
        (p for p in hourly if isinstance(p, dict)),
        key=lambda p: str(p.get("from", "")),
    ):
        stamp = point.get("from")
        if not isinstance(stamp, str) or stamp[:10] != date or len(stamp) < 13:
            continue
        try:
            hour = int(stamp[11:13]) + 1
        except ValueError:
            continue
        viewers = positive_number(point.get("viewers"))
        if viewers is None or not 1 <= hour <= 24:
            continue
        totals[hour] = totals.get(hour, 0.0) + viewers
        counts[hour] = counts.get(hour, 0) + 1
    return {hour: totals[hour] / counts[hour] for hour in sorted(totals)}


def build_ratio_pool(comparables):
    """Collect, per forecast hour, the sorted log ratios of the usable pool.

    A comparable is usable when its release day is (nearly) fully observed,
    it has an hour-1 value, and that hour 1 is at least MIN_HOUR1_SHARE of
    its day peak. The last rule quietly removes both late-global-unlock
    launches and non-launch curves (a category's premiere-day spike, say,
    whose "release day" holds only a handful of points never passes the
    full-day test either).
    """
    pool = {hour: [] for hour in range(2, 25)}
    if not isinstance(comparables, list):
        return pool
    for comparable in sorted(
        (c for c in comparables if isinstance(c, dict)),
        key=lambda c: str(c.get("name", "")),
    ):
        curve = release_day_curve(comparable)
        if len(curve) < 20 or 1 not in curve:
            continue
        first = curve[1]
        peak = max(curve.values())
        if peak <= 0 or first / peak < MIN_HOUR1_SHARE:
            continue
        for hour in range(2, 25):
            if hour in curve:
                pool[hour].append(math.log(curve[hour] / first))
    for hour in pool:
        pool[hour].sort()
    return pool


def sorted_quantile(sorted_values, tau):
    """The tau quantile of an ascending list, inverse-CDF style.

    Returns the smallest value whose rank reaches tau of the way through the
    list. With a few dozen curves this step quantile is deliberately plain:
    interpolation between two neighbouring launches would invent shapes no
    real launch had.
    """
    if not sorted_values:
        return 0.0
    if tau <= 0:
        return sorted_values[0]
    if tau >= 1:
        return sorted_values[-1]
    rank = math.ceil(tau * len(sorted_values))
    return sorted_values[min(max(rank, 1), len(sorted_values)) - 1]


def log_quantile_curves(pool, levels):
    """Turn the ratio pool into one list of log quantiles per hour.

    Applies the median shrink, the spread scale and the log cap, then the
    three-hour moving-average smoothing across neighbouring hours.
    """
    raw = {}
    for hour in range(2, 25):
        values = pool.get(hour) or []
        if not values:
            raw[hour] = None
            continue
        median = sorted_quantile(values, 0.5) * MEDIAN_SHRINK
        row = []
        for tau in levels:
            q = sorted_quantile(values, tau)
            row.append(median + (q - median) * SPREAD_SCALE)
        raw[hour] = row
    smoothed = {}
    for hour in range(2, 25):
        if raw[hour] is None:
            smoothed[hour] = None
            continue
        neighbours = [raw[k] for k in (hour - 1, hour, hour + 1) if raw.get(k) is not None]
        row = []
        for slot in range(len(levels)):
            averaged = sum(n[slot] for n in neighbours) / len(neighbours)
            row.append(min(averaged, LOG_CAP))
        smoothed[hour] = row
    return smoothed


def fallback_log_row(hour, levels):
    """A widening lognormal band around zero (persistence) for missing data."""
    width = FALLBACK_SIGMA * math.sqrt(hour - 1)
    row = []
    for tau in levels:
        # Map an arbitrary level to a z-score by its distance from the
        # median of the standard five levels; exact for the contest levels.
        if tau in DEFAULT_LEVELS:
            z = FALLBACK_Z[DEFAULT_LEVELS.index(tau)]
        elif tau < 0.5:
            z = -1.645 * (0.5 - tau) / 0.45
        elif tau > 0.5:
            z = 1.645 * (tau - 0.5) / 0.45
        else:
            z = 0.0
        row.append(z * width)
    return row


def round2(value):
    """Round to two decimals, half up, returning an int when whole."""
    scaled = math.floor(value * 100 + 0.5)
    result = scaled / 100
    return int(result) if float(result).is_integer() else result


def hour_one_print(case):
    """The case's hour-1 viewers: from `known`, else history, else a constant."""
    known = case.get("known")
    if isinstance(known, list):
        for row in sorted(
            (r for r in known if isinstance(r, dict)),
            key=lambda r: str(r.get("hour", "")),
        ):
            if row.get("hour") == 1:
                viewers = positive_number(row.get("viewers"))
                if viewers is not None:
                    return viewers
    history = case.get("history_hourly") or case.get("history")
    if isinstance(history, list):
        best = None
        for point in history:
            if isinstance(point, dict):
                viewers = positive_number(point.get("viewers"))
                if viewers is not None:
                    best = viewers
        if best is not None:
            return best
    return 1000.0


def forecast_case(case):
    """Build the {"hours": [...]} document for one parsed case."""
    levels = case.get("levels")
    if (
        not isinstance(levels, list)
        or len(levels) != 5
        or any(positive_number(t) is None or float(t) >= 1 for t in levels)
    ):
        levels = DEFAULT_LEVELS
    levels = [float(t) for t in levels]
    p1 = hour_one_print(case)
    pool = build_ratio_pool(case.get("comparables"))
    curves = log_quantile_curves(pool, levels)
    rows = []
    for hour in range(2, 25):
        log_row = curves.get(hour)
        if log_row is None:
            log_row = fallback_log_row(hour, levels)
        quantiles = []
        for log_q in log_row:
            value = p1 * math.exp(log_q)
            value = min(max(value, 0.01), MAX_VIEWERS)
            quantiles.append(value)
        quantiles.sort()
        rows.append({"hour": hour, "q": [round2(v) for v in quantiles]})
    return {"hours": rows}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if not INPUT_DIR.is_dir():
        return
    for path in sorted(INPUT_DIR.glob("*.in")):
        try:
            case = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(case, dict):
                case = {}
        except (OSError, ValueError):
            case = {}
        document = forecast_case(case)
        text = json.dumps(document, separators=(",", ":")) + "\n"
        (OUTPUT_DIR / (path.stem + ".out")).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
