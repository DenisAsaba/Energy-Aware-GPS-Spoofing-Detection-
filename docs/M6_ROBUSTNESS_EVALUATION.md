# M6: robustness, generalization, and multi-scenario evaluation

## Research question and scope

M6 measures whether the existing M4 oracle-assisted residual threshold and M5
GPS-only temporal threshold rules retain performance across independently
seeded SUMO trips, two existing route definitions, and multiple attack
intensities/durations. M4 remains a non-deployable oracle benchmark. M5 uses
only GPS coordinates and previous GPS fixes at prediction time. Neither
detector's prediction rule is changed. This is simulation-only work; it does
not evaluate GPS hardware, routing decisions, or energy causality.

## Inputs and route validation

M6 configuration is isolated in `config/m6_robustness.yaml`; M0-M5
configuration and historical datasets are read-only. The campaign uses SUMO
road-network X/Y coordinates in meters, a 1.0-second simulation step, and
independent zero-mean Gaussian X/Y noise with 3.0 m per-axis standard deviation.
GPS random seeds are derived deterministically from the configured base seed,
SUMO seed, and route name.

The configured route matrix uses only routes already defined in the project:

| Route key | Network | Route ID | Ordered edges |
| --- | --- | --- | --- |
| `m0_route` | `sumo/network/m0.net.xml` | `route_0` | `road_0` |
| `m3_alternative` | `sumo/network/m3.net.xml` | `route_alternative` | `road_alt_0`, `road_alt_1` |

Each network/route pair is checked by SUMO and its route ID/edge list is checked
against the configuration before a campaign starts. The alternative is a
separate network from M0; cross-route results therefore indicate sensitivity
to these two defined network/route conditions, not broad road-network
generalization.

## Experimental design

The experimental unit is one SUMO trip and its corresponding GPS/attack
scenario. Seeds are split before generating data; adjacent samples from one
trip are never divided among calibration, validation, and test groups.

| Group | SUMO seeds | Routes | Purpose |
| --- | --- | --- | --- |
| Normal calibration | 601, 602 | both | Fit M4/M5 thresholds using normal GPS only |
| Normal validation | 603 | both | Report a separate normal-only diagnostic; never tune thresholds |
| Normal final test | 604, 605 | both | Estimate false alarms on held-out normal trips |
| Attack final test | 604, 605 | both | Evaluate all attack type/intensity/duration combinations |

The full matrix contains 10 normal trip inputs (4 calibration, 2 validation,
4 final-test) and 48 attack trip/scenario datasets (2 test seeds × 2 routes × 3
attack types × 2 intensities × 2 durations). The scored final test has 52
experiment configurations: four normal trips plus 48 attack configurations.
M4 and M5 each score all 52, yielding 104 per-detector experiment metric rows.
The route/seed-matched attacks reuse each test trip's normal GPS noise seed so
the attack manipulation is the only GPS-coordinate change between paired
normal and attack data.

The smoke matrix uses route `m0_route`, seeds 901/902/903 for calibration,
validation, and test, respectively, and the first configured intensity and
duration for each attack. It contains three normal trip inputs and four scored
test configurations (one normal and three attacks), or eight detector scores.

## Attack matrix and semantics

All attack windows use the existing M3 half-open interval
`[onset_s, onset_s + duration_s)`. Offset and drift begin at 20 s; the jump
begins at 35 s, preserving the M3 onset convention. Directions use the
existing compass-bearing convention (0° north, clockwise), and coordinates
remain SUMO X/Y meters.

| Type | Intensities | Durations | Existing M3 parameter meaning |
| --- | --- | --- | --- |
| Offset | 10 m, 30 m | 10 s, 30 s | Constant vector magnitude during active interval |
| Jump | 20 m, 60 m | 1 s, 5 s | Finite sudden vector displacement, restored after interval |
| Drift | 0.5 m/s, 1.0 m/s | 10 s, 30 s | Linear displacement growth, capped at rate × duration |

The attack generator writes GPS observations separately from labels and
metadata. M4/M5 prediction functions finish before the M6 evaluator opens
attack labels. M5 prediction receives GPS only and never receives truth,
residuals, labels, or future GPS fixes.

## Threshold calibration and evaluation

M6 calibrates thresholds separately from the M0-M5 runs, using only the
normal calibration trips (seeds 601 and 602, both configured routes):

- M4 pools truth-to-normal-GPS Euclidean residuals and applies the configured
  95th percentile, preserving M4's strict `residual > threshold` decision.
- M5 extracts its existing causal GPS-derived speed, speed-change, and
  heading-change features from each calibration trip, pools eligible feature
  values across those trips, and applies the configured 99th percentile to
  each feature. The original OR rule and strict greater-than comparisons are
  retained.
- Validation seeds 603 and final-test seeds 604/605 do not set or adjust either
  threshold. Validation metrics are reported separately from final-test
  aggregates.

The M4 residual is explicitly oracle-assisted because it uses simulation
ground truth. M5 prediction uses only the current and previous GPS records for
the same vehicle. The evaluator reads labels only after both prediction sets
are generated. No attack data is used for threshold calibration.

Per-trip metrics include TP, FP, TN, FN, precision, recall, F1, false-positive
rate, accuracy, detection delay when detected, matched/unmatched records, and
M5 exclusions. Undefined ratios use the existing zero-denominator convention
(0.0). Detection delay is the first active-label true positive time minus the
first active-label time; missed attacks have null delay.

Aggregate tables report mean, sample standard deviation (`ddof=1`, or 0 for a
single trip), minimum, maximum, and experiment count for detector/scenario,
attack intensity, duration, seed, and route groupings. Delay summaries omit
missed attacks and report the number of observed delays. The per-trip record is
the unit for variability; confidence intervals are not calculated because the
small seed counts do not support a stable interval estimate. Confusion counts
are also shown pooled over fixes for reference only; those fixes are not
treated as independent experimental units.

## Reproduction

From this project directory, first run the reduced smoke matrix and inspect its
manifest, metrics, and plots. Then use a different run ID for the full matrix.
Outputs are new, isolated directories and existing run IDs are rejected.

```powershell
python -m src.experiments.m6_robustness --config config/m6_robustness.yaml --run-id m6_smoke_01 --smoke
python -m src.experiments.m6_robustness --config config/m6_robustness.yaml --run-id m6_full_01
python -m unittest discover -s tests -v
```

Each run writes its configuration snapshot, experiment matrix, input datasets
and their seed metadata, M4/M5 per-fix predictions, per-trip and aggregate
metrics, threshold record, run metadata, and plots under
`reports/m6/<run-id>/`. Generated M6 data and figures are excluded from Git;
the code, tests, configuration, and methods document remain reproducible.

## Outputs

The full campaign produces `per_experiment_metrics.csv`,
`validation_metrics.csv`, `aggregate_metrics.csv`, and `experiment_matrix.csv`.
Plots include M4/M5 F1, precision/recall/F1 by intensity and duration, normal
test false-positive rates, detection delay, variability across test seeds,
variability across routes, and aggregate confusion counts. Route variability
is plotted only when multiple routes are configured. The plotted samples and
group sizes come from trip-level metrics recorded for the same run.

## Results and limitations

The final verified run is `reports/m6/m6_full_02/`. It produced 58 unique
matrix rows (10 normal trip datasets and 48 attack datasets), 52 held-out test
configurations, 104 test metric rows, and four validation metric rows. The
second full run, `m6_full_03/`, reproduced 236 CSV, JSON, and PNG outputs
byte-for-byte when comparing all run-relative artifacts; path-bearing metadata
was excluded from that comparison. The M6 runner also hashed 278 protected
M0-M5 files before and after each run; their combined manifest hash was
`807fd0db79814e8d327f0325023226626000b46c9782ca3071c14061682a28c2`, and the
files were unchanged. Both configured routes passed SUMO route validation.
Earlier isolated M6 run IDs are retained rather than overwritten. In
particular, `m6_full_01/` predates a fix to the aggregate CSV column union and
is not a final result; use `m6_full_02/` or its exact repeat `m6_full_03/`.
`m6_smoke_03/` is the inspected smoke run; earlier smoke IDs are superseded.

Calibration used only four normal trips. The M4 residual threshold was
**7.379797 m** at the configured 95th percentile. M5's 99th-percentile
thresholds were **24.060419 m/s** estimated speed, **18.029596 m/s** speed
change, and **108.455277 degrees** heading change. Validation and final-test
trips did not affect these thresholds.

The table reports macro means and sample standard deviations over per-trip
scenario metrics. The experimental unit is a trip/scenario configuration;
each attack class has 16 test trips (2 seeds × 2 routes × 2 intensities × 2
durations). Normal F1 is zero by the detector metric convention because those
trips contain no positive attack labels; normal false-positive rate is the
useful normal-only measure.

| Detector | Test scenario | Precision | Recall | F1 | FPR | Accuracy | Delay (s), detected trips | n |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| M4 oracle | Offset | 0.861 ± 0.129 | 0.944 ± 0.076 | 0.894 ± 0.080 | 0.028 ± 0.021 | 0.966 ± 0.021 | 0.125 (16) | 16 |
| M4 oracle | Jump | 0.456 ± 0.234 | 1.000 ± 0.000 | 0.592 ± 0.228 | 0.033 ± 0.016 | 0.968 ± 0.016 | 0.000 (16) | 16 |
| M4 oracle | Drift | 0.704 ± 0.330 | 0.465 ± 0.284 | 0.533 ± 0.292 | 0.028 ± 0.021 | 0.890 ± 0.029 | 4.867 (15) | 16 |
| M5 GPS-only | Offset | 0.163 ± 0.193 | 0.058 ± 0.077 | 0.080 ± 0.100 | 0.040 ± 0.022 | 0.769 ± 0.113 | 0.000 (8) | 16 |
| M5 GPS-only | Jump | 0.290 ± 0.123 | 0.675 ± 0.342 | 0.355 ± 0.106 | 0.038 ± 0.014 | 0.946 ± 0.021 | 0.000 (16) | 16 |
| M5 GPS-only | Drift | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.035 ± 0.024 | 0.765 ± 0.119 | — (0) | 16 |

On the four normal final-test trips, mean FPR was **0.032 ± 0.017** for M4
and **0.019 ± 0.020** for M5. M5 excluded 52 observations in total: the first
GPS fix of each of the 52 test configurations, because the existing temporal
feature rule requires a previous fix. Those records are also counted as
excluded labeled observations, not as unmatched labels. M4 had zero unmatched
GPS/truth rows. Both detectors had zero unmatched prediction/label records.

### F1 by attack intensity

Values average over both configured durations, both test seeds, and both
routes (eight trip runs per cell); the ± value is sample standard deviation.

| Attack | Intensity | M4 F1 | M5 F1 |
| --- | --- | ---: | ---: |
| Offset | 10 m | 0.864 ± 0.075 | 0.000 ± 0.000 |
| Offset | 30 m | 0.924 ± 0.079 | 0.159 ± 0.082 |
| Jump | 20 m | 0.592 ± 0.236 | 0.346 ± 0.122 |
| Jump | 60 m | 0.592 ± 0.236 | 0.364 ± 0.096 |
| Drift | 0.5 m/s | 0.406 ± 0.321 | 0.000 ± 0.000 |
| Drift | 1.0 m/s | 0.660 ± 0.207 | 0.000 ± 0.000 |

### Variability by route and seed

Route-stratified attack F1 summaries (eight trip runs per cell, across attack
intensity and duration) were:

| Detector | Attack | M0 route F1 | M3 alternative F1 |
| --- | --- | ---: | ---: |
| M4 | Offset | 0.942 ± 0.053 | 0.846 ± 0.076 |
| M4 | Jump | 0.727 ± 0.169 | 0.457 ± 0.203 |
| M4 | Drift | 0.524 ± 0.319 | 0.541 ± 0.285 |
| M5 | Offset | 0.098 ± 0.121 | 0.061 ± 0.077 |
| M5 | Jump | 0.412 ± 0.079 | 0.298 ± 0.103 |
| M5 | Drift | 0.000 ± 0.000 | 0.000 ± 0.000 |

The `seed_variability.png` and `route_variability.png` plots show each
trip-level result. There are only two final-test seeds and two distinct route
definitions, so the standard deviations describe this experiment matrix and
should not be interpreted as stable population uncertainty. No confidence
intervals or significance tests are claimed.

### Verification and generated artifacts

`reports/m6/m6_smoke_03/` contains the inspected smoke run: four test
configurations, eight detector scores, two validation detector scores, and six
smoke plots (route variability is correctly omitted from a one-route subset).
The full run has all seven plots listed below and in its `run_metadata.json`:

- `m4_vs_m5_f1.png`
- `prf_by_attack_intensity.png`
- `normal_test_fpr.png`
- `detection_delay.png`
- `seed_variability.png`
- `route_variability.png`
- `aggregate_confusion.png`

The final command `python -m unittest discover -s tests -v` passed all **48
tests**. The test suite covers matrix uniqueness/splits, intensity semantics,
SUMO route validation, aggregation and standard deviations, M5 prediction
independence from truth/labels, smoke reproducibility, output-ID protection,
and preservation of historical artifacts.

The two routes use separate networks, one EV, one traffic-free road
configuration per network, and a small number of seeded trips. Seeds 604/605
are held out from calibration, but both routes appear in calibration; this
campaign therefore measures seed transfer and route variability, not
leave-one-route-out generalization. The results cannot establish performance
across realistic traffic, a broad road network, multiple vehicles, real GNSS
effects, or operational deployments. M4 is an oracle benchmark. M5 remains a
research baseline and is not safety-certified. No route controller or
spoofing-related energy claim is part of M6.
