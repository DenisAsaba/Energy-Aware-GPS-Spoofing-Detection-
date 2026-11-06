# M5: GPS-only temporal spoofing baseline

## Purpose and separation from M4

M5 evaluates whether temporal consistency in GPS observations alone can flag
simulated offset, jump, and drift attacks. It does not read ground-truth
coordinates, attack labels, M4 residuals, or future GPS observations while
producing predictions. M4 is an oracle-assisted offline reference because it
compares GPS against ground truth. Its results are not an operational
detector's expected performance. Route deviation is excluded from M5.

## Inputs, features, and rules

The input CSV contains `time_s`, `vehicle_id`, `gps_x_m`, and `gps_y_m` in
SUMO's local metric road coordinates. For each vehicle, and using only its
previous valid fix, M5 computes elapsed time `dt` (s), displacement
`sqrt(dx^2 + dy^2)` (m), estimated speed `displacement / dt` (m/s), and
compass bearing `atan2(dx, dy)` in degrees clockwise from north. It then
computes absolute change in estimated speed (m/s) and the smallest circular
change in bearing (degrees). A fix is flagged if any calculated feature is
strictly greater than its corresponding threshold. The output records each
individual rule and the combined OR prediction.

The first valid fix for each vehicle initializes state and cannot be scored.
Missing or non-finite timestamps/coordinates, missing vehicle IDs, duplicate
`(time_s, vehicle_id)` keys, and non-increasing per-vehicle timestamps are
retained in output with an exclusion reason and do not update state. A zero
displacement has speed zero and undefined heading; its heading-change rule is
not evaluated for that transition. Input order must be chronological per
vehicle; out-of-order records are excluded rather than sorted using future
observations.

## Calibration and evaluation

The configured `normal_quantile: 0.99` is independently applied to GPS speed,
absolute speed change, and heading change from the first 50% chronological
valid normal M2 fixes. The thresholds are fixed before attack predictions.
The held-out normal suffix evaluates false alarms. The observed thresholds
were 23.4725198451 m/s speed, 14.7583719656 m/s absolute speed change, and
69.8848509793 degrees heading change. The normal training prefix and first
per-vehicle initialization fix are excluded from scored predictions.

For attacks, predictions are generated before the corresponding label CSV is
read. Labels are joined offline by `(time_s, vehicle_id)`. The first eligible
true positive time minus the first active-label time is detection delay; it is
null if no eligible attack record is detected. Confusion counts and rates use
only eligible matched evaluation records. Excluded and unmatched records are
reported. M5 uses the same basic confusion-metric formulas as M4, but normal
M5 scores only the held-out suffix and attack M5 scores exclude the first
fix, so M4/M5 denominators differ slightly.

## Verified results

Run `m5_final_01` evaluated the existing 79-row M2 normal file and each
79-row M3 attack file. Each attack had 78 eligible matched records; one
initialization fix was excluded. The normal suffix had 40 eligible records;
39 calibration/initialization records were excluded.

| Scenario | TP | FP | TN | FN | Precision | Recall | F1 | FPR | Accuracy | Delay (s) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Normal holdout | 0 | 2 | 38 | 0 | 0.000 | 0.000 | 0.000 | 0.050 | 0.950 | — |
| Offset | 6 | 3 | 45 | 24 | 0.667 | 0.200 | 0.308 | 0.063 | 0.654 | 0.0 |
| Jump | 4 | 5 | 68 | 1 | 0.444 | 0.800 | 0.571 | 0.068 | 0.923 | 0.0 |
| Drift | 4 | 3 | 45 | 26 | 0.571 | 0.133 | 0.216 | 0.063 | 0.628 | 6.0 |

| Scenario | M5 F1 | M4 oracle-assisted F1 |
|---|---:|---:|
| Normal holdout | 0.000 | 0.000 |
| Offset | 0.308 | 0.952 |
| Jump | 0.571 | 0.714 |
| Drift | 0.216 | 0.900 |

M5 has lower F1 than M4 for all three attacks in this run. This is expected to
be possible because M4 uses privileged position residuals. These are results
from a single simulated trip and one attack intensity, not estimates of
generalization to other trips, routes, seeds, or severity levels.

## Outputs and reproduction

Configuration is in `config/experiment_config.yaml`. Run from the project
root with a new run ID (the workflow refuses an existing directory):

```powershell
python -m src.detection.gps_only --config config/experiment_config.yaml --run-id m5_run_01
python -m unittest discover -s tests -v
```

Each run writes prediction CSVs, four metric JSON files, `summary.csv`, M4
comparison CSV/JSON, run metadata with input SHA-256 hashes, a copied config,
confusion matrices, an M5/M4 precision-recall-F1 comparison, and
GPS-feature/threshold/prediction time series under `reports/m5/<run-id>/`.
Labels appear only in evaluation plots/metrics and are not prediction fields.

## Limitations

This deterministic GPS-only baseline uses simple independent upper quantiles
and OR rules. Position offset can be temporally smooth and therefore evade
motion-only checks; gradual drift may remain below thresholds; natural turns
or noisy fixes can cause false alarms. The thresholds are fit on one short
normal trip, with only 39 chronological calibration fixes and 40 held-out
fixes. There are no held-out trips/routes, attack intensity transfer,
validation-selected thresholds, uncertainty intervals, latency measurements,
or online stream integration. Excluded observations reduce the evaluation
sample. The system is a GPS-only research baseline, not a certified production
safety detector. No route-selection controller or causal energy effect is
implemented or claimed.
