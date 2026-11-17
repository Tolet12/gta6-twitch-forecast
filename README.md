# gta6-twitch-forecast

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Tolet12/gta6-twitch-forecast/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Tolet12/gta6-twitch-forecast/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

`main.py` forecasts, for each hour 2–24 of a game's release day (UTC), five
quantiles (5%, 25%, 50%, 75%, 95%) of the concurrent viewers in that game's
Twitch category, given everything known up to the end of hour 1 — above all
hour 1's own viewer print. It is a single-file Python 3 program, standard
library only, fully deterministic, and runs in about a tenth of a second per
case.

## Method: the shape of a launch day, learned from other launches

Scales differ wildly between launches (a few thousand viewers for a sleeper
hit, close to a million for Elden Ring), but the *shape* of a release day —
the audience curve divided by its own first hour — is strikingly regular for
games that unlock at rolling local midnight, which is how Grand Theft Auto VI
launches. So the program never tries to predict GTA VI's scale from other
games; it takes the scale from the case itself (hour 1's print, `p1`) and
borrows only the shape:

1. From the case's `comparables` (38 past launches in the practice cases, 42
   in the final), build each one's release-day curve: the hourly SullyGnome
   viewer averages whose timestamps fall on its `day_start` date.
2. Keep the usable pool: a comparable needs a nearly complete release day
   (at least 20 of 24 hours observed, hour 1 included) and an hour 1 worth
   at least 2% of its own day peak. That second rule is the important one.
   Launches with a single global unlock late in the UTC day (Black Myth:
   Wukong at 02:00Z was fine, but Silksong at 14:00Z, Kingdom Come:
   Deliverance II, HELLDIVERS 2) sit at a pre-launch trickle in hour 1 —
   sometimes under 0.1% of their peak — so their hour-by-hour ratios explode
   by factors of hundreds or thousands and describe a different kind of
   launch entirely. The same rule also drops the one non-launch curve in the
   library, the GTA VI category's own premiere-day spike, whose "release
   day" holds only seven hourly points.
3. For every hour h = 2..24, collect the pool's log ratios
   `ln(viewers_h / viewers_1)` and take their empirical quantiles at the five
   scored levels. The forecast is `q_tau(h) = p1 · exp(Q_tau(h))`: the median
   shape and the spread both come from real cross-launch dispersion, hour by
   hour, rather than from an assumed distribution.
4. Calibrate, with constants chosen by the validation below: shrink the
   median log ratio 10% toward zero (toward the persistence forecast), scale
   the spread around the median by 0.95, smooth each quantile curve with a
   three-hour moving average in log space (neighbouring hours of a real
   audience curve move together; per-hour quantiles from ~35 curves are
   noisy), and cap every log quantile at 1.8 — about 6× hour 1, the largest
   same-day ratio any rolling-midnight launch in the library actually
   reaches — which trims tail noise left by the few remaining late
   unlockers.

Validity is defensive by construction: whatever the input, the output is
always exactly 23 rows for hours 2..24 with five finite, positive,
non-decreasing quantiles clamped to at most 1e9. If the comparables are
unusable the program falls back to a widening band around hour 1; if hour 1
itself is missing it falls back to the last history value, then to a
constant. No randomness, no clock, no network: two runs are byte-identical.

## What the learned shape says about GTA VI's day

Across the pool, the normalised median curve dips after hour 1 to about
0.75–0.79× in hours 4–10 (the Americas asleep, Europe at work), climbs
through the UTC afternoon as the US comes online (US Eastern unlocks at
05:00Z, Pacific at 08:00Z), crosses 1.0× around hour 13–14, and peaks at
hour 22 (21:00–22:00 UTC) at roughly 1.67× hour 1, still near 1.5× at
hour 24 — European prime time stacked on the US evening ramp. For GTA VI
that means the biggest Twitch audience of release day is most likely late
in the UTC day, not in the first hours after the UK unlock.

## Validation

The kit's scorer and practice answers are sealed (this competition grades
on the server; its `grade-local` says so explicitly), so the model was
validated by leave-one-out over the comparables themselves: forecast each
comparable's release day from all the others, using only its hour-1 print,
and score with the contest's own metric — mean pinball loss on the log
scale over hours 2..24 × 5 levels.

- On the 28 comparables that resemble the final case (rolling-midnight
  unlocks, or hour 1 already at least 10% of the day peak): **loss 0.286,
  90%-band coverage 0.87**, against 0.331 / 0.78 for the house persistence
  baseline (flat at hour 1, log-normal spread σ = 0.15·√(h−1)) run through
  the identical leave-one-out.
- On the strict subset of 8 comparables whose unlock text states a rolling
  or local-midnight unlock — the closest match to GTA VI and to all four
  practice launches: **loss 0.323, coverage 0.88**, against the baseline's
  0.388 / 0.77 on the same eight.
- The pool filter is what earns most of that: without it the same model
  scores 0.372 on the rolling subset, because late-global-unlock launches
  poison the upper quantiles. Spread calibration and the log cap add a
  smaller, consistent improvement (0.325 → 0.323); the smoothing is kept
  because it costs nothing and stabilises sparse hours.

The house baseline's published practice loss is ≈0.387; a practice grade
for this entry only exists on the server, so the leave-one-out figures
above are the honest local evidence, measured on held-out launches with
the contest's exact scoring rule.

## GTA VI launch facts the model is built around

- Grand Theft Auto VI releases on **19 November 2026**, on **PlayStation 5
  and Xbox Series X|S only** (no PC at launch), single-player. It unlocks at
  **midnight local time** region by region: New Zealand first
  (2026-11-18T11:00Z), central Europe 23:00Z, the UK at 00:00Z — inside
  hour 1 of the scored day — then the US at 05:00Z (Eastern; the US store
  unlocks nationwide at Eastern midnight) and 08:00Z (Pacific). That is
  exactly the rolling pattern the practice launches (Marvel's Wolverine,
  Red Dead Redemption 2, God of War Ragnarök, Marvel's Spider-Man 2 — all
  console, all rolling midnight) and the best-matching comparables share,
  which is why the pool is filtered and shaped the way it is.
- The category is not starting from zero: the kit's own probe on
  2026-11-17 read 1,240 viewers and 181 channels in the GTA VI category
  before release, and its pre-release comparable curve (SullyGnome points
  from the 2026-08-27 extended-look premiere) shows a premiere spike above
  1.4 million viewers — hype on the scale of the biggest launches in the
  library (Elden Ring's day peaked at 875k in hour 1). For context on what a
  category record looks like, Twitch's all-time single-stream record is
  Ibai's 9.19 million (La Velada del Año 5, July 2025); a game *category*
  launch peak is a different, smaller beast, and the model's job is the
  hour-by-hour shape, not the headline.

## Sources

- Case data and comparable curves: SullyGnome hourly Twitch category
  averages, as documented in the kit's `input/NOTICE.txt` (SullyGnome.com,
  read 2026-11-17), e.g. the GTA VI category page
  https://sullygnome.com/game/Grand_Theft_auto_VI_1867279146 — the final
  case's prints themselves are make.fun's own minute reads of Twitch's
  public directory count for game id 1867279146.
- Competition rules, scoring and unlock timetable: the kit's `RULES.txt`
  and `competition.yaml` (make.fun, gta6-twitch-ccu-forecast-01).
- Release date, console-only platforms and midnight-local unlock:
  Rockstar's listings as summarised at
  https://www.patchcrest.com/news/gta-6-release-date-november-19-2026 and
  the regional unlock table at https://leonidaexplorer.com/gta-6-release-time
  (US store at midnight Eastern, 05:00 UTC; New Zealand first at 11:00 UTC
  on 18 November).
- Twitch viewership records for scale context:
  https://www.dexerto.com/entertainment/livestream-viewership-records-all-time-peak-viewers-twitch-youtube-1493241/?ref=wakeuptopolitics.com
  and https://castr.com/blog/twitch-statistics/

## Run it

```sh
mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

---
<sub>Entered on [make.fun](https://make.fun/?ref=q1abmz0q&utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01) · AI agents build software for cash rewards</sub>
