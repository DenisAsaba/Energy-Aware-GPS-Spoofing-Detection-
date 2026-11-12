# M9 Stage 2 — Final Held-Out Evaluation

Canonical corrected run: `m9_stage2_final_03`, independently repeated as
`m9_stage2_final_04`. Both runs evaluated seeds 2501–2506 with two seeds per
profile, six SUMO trips, six normal-control datasets, and 72 attack events from
the 12 approved historical M8 Stage 2B cases. Each exact case ID occurs six
times. Jumps include 30 m and 60 m cases at both 1 s and 5 s. The Stage 1
60 m / 8 s jump remained Stage 1-only.

## Pooled results

| System | Normal FPR | Normal false positives / eligible | Normal alarm episodes | Active events detected | Mean delay among detected |
|---|---:|---:|---:|---:|---:|
| M5 | 2.98% | 16 / 537 | 15 | 58 / 72 | 1.33 s |
| M8 | 7.26% | 39 / 537 | 7 | 60 / 72 | 0.40 s |
| OR | 9.12% | 49 / 537 | 16 | 66 / 72 | 0.65 s |
| AND | 1.12% | 6 / 537 | 5 | 50 / 72 | 1.12 s |
| Staged fast suspect | 2.98% | 16 / 537 | 15 | 58 / 72 | 1.33 s |
| Staged corroborated | 5.77% | 31 / 537 | 4 | 52 / 72 | 0.46 s |

Staged fast suspect equals the frozen M5 stream. Corroboration is reported
separately and does not mean confirmed spoofing. OR detected the most events
and also had the highest normal FPR. AND had the lowest FPR and detected fewer
events.

| Profile | M5 FPR | M8 FPR | OR FPR | AND FPR | Staged fast FPR | Staged corroborated FPR |
|---|---:|---:|---:|---:|---:|---:|
| Turns/light | 3.54% | 9.60% | 11.62% | 1.52% | 3.54% | 8.59% |
| Stop/restart | 3.49% | 9.88% | 12.21% | 1.16% | 3.49% | 5.23% |
| Brake/accel | 1.80% | 1.80% | 2.99% | 0.60% | 1.80% | 2.99% |

Profile event detection (mean delay among detections):

| Profile | M5 | M8 | OR | AND | Staged fast | Staged corroborated |
|---|---:|---:|---:|---:|---:|---:|
| Turns/light | 18/24 (1.67 s) | 24/24 (0 s) | 24/24 (0 s) | 18/24 (1.78 s) | 18/24 (1.67 s) | 20/24 (0 s) |
| Stop/restart | 22/24 (0.55 s) | 24/24 (0.50 s) | 24/24 (0.33 s) | 20/24 (0.60 s) | 22/24 (0.55 s) | 20/24 (0.60 s) |
| Brake/accel | 18/24 (1.94 s) | 12/24 (1.00 s) | 18/24 (1.94 s) | 12/24 (1.00 s) | 18/24 (1.94 s) | 12/24 (1.00 s) |

## Jump results

Each duration has 12 attack events across both magnitudes, three profiles, and
two seeds per profile.

| System | 1 s | 5 s |
|---|---:|---:|
| M5 | 12/12, 0 s mean delay | 12/12, 0 s |
| M8 | 8/12, 0 s | 12/12, 0.33 s |
| OR | 12/12, 0 s | 12/12, 0 s |
| AND | 8/12, 0 s | 12/12, 0.33 s |
| Staged fast suspect | 12/12, 0 s | 12/12, 0 s |
| Staged corroborated | 8/12, 0 s | 12/12, 0.33 s |

The full attack-type, magnitude/rate, duration, and profile results are in
`attack_event_summary.csv`; per-event outcomes and delays are in
`trip_metrics.csv`. Matched M5/M8 overlap, all alarm activations/clears, and
prediction coverage are in `joint_prediction_overlap.csv`, `alarm_episodes.csv`,
and `prediction_coverage.csv`.

## Reproducibility and preservation

Runs `_03` and `_04` matched byte-for-byte across 242 CSV files. Runs `_01`
and `_02` were also deterministic; review found case-wide episode aggregation,
normal episode counts that counted datasets instead of episodes, and an
inactive-observation rate mislabeled as normal FPR in those initial summary
tables. They are retained as audit history and `_03`/`_04` are canonical. The
222 attack/GPS/prediction CSVs compared between
`_01` and `_03` are byte-identical; the correction did not change detector
outputs, labels, thresholds, or fusion behavior.

All 105 repository tests passed. The protected M0–M8 hash baseline had no
changes, and 1,658 prior M9 report files remained unchanged at the canonical
run’s start. Frozen input and code hashes are recorded in `preflight_freeze.json`.

Validation results remain separate from these held-out results. The six trips
support descriptive comparisons only. A GPS motion anomaly is not proof of
spoofing; smooth translation and plausible slow drift may be unobservable from
GPS motion alone. The detector is not established as production-ready.

Exact commands, all profile metrics, error rates, limitations, and hash values
are recorded in [the M9 Stage 2 analysis](../../../docs/M9_DETECTOR_ERROR_ANALYSIS.md).
