# M8 Stage 1: improved GPS-only detector

## Status and scope

Stage 1 implements a separate interpretable GPS-only detector and a paired M5
baseline comparison. It runs normal calibration trips, a validation-only
persistence selection, and a small held-out smoke scenario. It does **not** run
the reserved final-test split or the full intensity/duration matrix. The smoke
is a pipeline and behavior check; it does not establish generalization or prove
that M8 is better overall.

M5 remains unchanged. M8 prediction reads only the exact GPS schema
`time_s,vehicle_id,gps_x_m,gps_y_m`; any extra column is rejected. The detector
does not receive truth, attack labels or metadata, SUMO route/vehicle state, M4
residuals, or future fixes. Predictions are written before attack labels are
opened for scoring. Ground truth is used only by the experiment driver to
simulate trips and generate observations.

## Features and units

Coordinates are local SUMO road-network X/Y meters; timestamps are seconds.
M8 reuses M5's causal per-fix GPS speed, compass bearing, absolute speed change,
and circular heading change. It adds:

1. **Signed time-normalized acceleration**

   ```text
   a_t = (v_t - v_(t-1)) / (t_t - t_(t-1))
   ```

   Units are m/s². The signed value is retained in predictions; the threshold
   rule uses `abs(a_t)` so both abrupt acceleration and deceleration can fire.

2. **Rolling displacement/speed consistency**

   For window size `W`, calculate the straight-line rolling speed

   ```text
   v_roll_t = hypot(x_t - x_(t-W), y_t - y_(t-W)) / (t_t - t_(t-W))
   ```

   and compare it to the median of the previous `W` eligible per-fix GPS speed
   estimates:

   ```text
   c_t = abs(v_roll_t - median(v_(t-W), ..., v_(t-1)))
   ```

   `v_roll_t` and `c_t` are in m/s. With `W=4`, the feature is unavailable
   until four prior eligible speed estimates exist. Warm-up values are null and
   do not trigger a rule. Invalid, duplicate, or out-of-order observations
   follow M5 behavior: they are excluded and do not update state. State is
   maintained independently for each vehicle.

Thresholds are normal-only upper 99th percentiles. M8's raw anomaly is the OR
of M5's three feature threshold rules, absolute acceleration, and rolling
consistency. Strict `>` comparisons match M5. M5's primary baseline thresholds
are recalibrated from the same M8 calibration trips; M6's historical thresholds
are recorded as a reference only.

## Persistence and calibration

For each calibration trip, M8 calls M5's existing
`calibrate_temporal_thresholds()` to identify that trip's chronological normal
prefix. The pooled M5 and M8 feature thresholds are then NumPy linear quantiles
over those per-trip prefixes. No attack, validation, smoke, or final-test data
fit the thresholds.

Persistence counts raw anomalies in the last `N` eligible fixes and activates
when at least `K` are anomalous. Once active, an alarm remains latched until
`clear_after_clean_fixes` consecutive eligible fixes have no raw anomaly.
Excluded records do not enter the trigger window or clear an alarm. This can
reduce single-fix alerts, but delays alarm onset and can miss short events.

Validation compares the configured persistence candidates against one normal
trip and its offset, jump, and drift variants. The operating criterion is
normal observation-level FPR at most 5%; among candidates meeting it, choose
the highest active event detection and then fewer alarm episodes. If none meet
the criterion, choose the lowest normal FPR, then highest event detection. The
criterion and fallback are recorded in the run output. Candidate selection is
performed only on validation data.

## Split assignment and limitations

The split assignment is frozen in `config/m8_detector.yaml` before generation:

| Split | SUMO seeds | Route group | Use |
| --- | --- | --- | --- |
| Calibration | 1001, 1002 | M0 straight road | Normal-only threshold fitting |
| Validation | 1101 | M3 two-segment alternative | Normal FPR and persistence selection; attack variants share the trip and split |
| Stage 1 smoke | 1201 | M7 alternate branch | Paired M5/M8 normal, offset, jump, and drift check |
| Reserved final test | 1301, 1302 | M7 direct branch | Not generated or evaluated in Stage 1 |

Seeds and route-group keys are disjoint across groups; attack variants remain
with their source trip. M7 final-test seeds 803 and 804 are not reused. Smoke
results are not used to calibrate thresholds or choose persistence. The
final-test group is reserved and untouched.

The available networks do not provide a defensible sample of ordinary driving
variation. M3 supplies a bent two-edge route, and M7 supplies an alternate
branch, but there are few trips, no variable traffic demand, and no broad set
of stopping, restarting, and route-change behaviors. The one-trip validation
does not establish an operating point. A later full evaluation should add
normal routes/trips with controlled turns, stops, acceleration profiles, and
traffic variation, then hold out complete network/route groups as well as
seeds. Smooth constant GPS translation may be unobservable from GPS motion
alone after its onset without an independent reference.

## Metrics

Observation-level metrics are calculated only on eligible GPS fixes matched to
labels by `(time_s, vehicle_id)`: TP, FP, TN, FN, precision, recall, F1, FPR,
and TNR. Event-level active detection is the fraction of configured attack
events with at least one predicted alarm during the half-open active interval
`[onset_s, onset_s + duration_s)`. Missed-attack rate is one minus this rate.
Detection delay is the first active alarm time minus configured attack onset;
missed events have no delay. Post-attack alert counts include alerts at or after
attack end and never count as active detection. Alert episodes count transitions
from no alarm to alarm. Results include eligible and excluded observations.

## Stage 1 smoke result

Configuration: 3 m independent Gaussian GPS noise per axis; fixed SUMO/GPS
seeds; offset 30 m for 20 s, jump 60 m for 5 s, and drift 1 m/s capped at 20 m
for 20 s; all attacks start at 15 s. Attack direction and interval semantics
are in the config and per-run metadata. All metrics below are from the single
M7 alternate-branch smoke trip and must be read as a small demonstration, not
as inferential evidence.

The selected persistence was **2 of 3 fixes**, with alarm clearing after three
consecutive clean fixes. No candidate met the validation FPR ceiling of 5%:
the selected candidate's validation normal FPR was 8.74%, versus 26.21% for
1-of-1 and 17.48% for 2-of-5. Its validation active event detection was 2/3.
The rule therefore records a validation operating-criterion failure rather
than implying the target was met.

Pooled calibration thresholds were:

| Feature rule | Threshold |
| --- | ---: |
| GPS speed | 21.5466 m/s |
| Absolute GPS speed change | 15.6149 m/s |
| GPS heading change | 113.5403° |
| Absolute signed acceleration | 15.6149 m/s² |
| Rolling displacement/speed consistency | 5.9673 m/s |

The first fix was excluded for each dataset; 111 eligible observations remained
in each smoke scenario. Results:

| Scenario | Detector | F1 | FPR | Active event detected | Delay | Post-attack alerts | Alarm episodes |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Normal | M5 | 0.000 | 5.41% | — | — | 0 | 6 |
| Normal | M8 | 0.000 | 0.00% | — | — | 0 | 0 |
| Offset | M5 | 0.222 | 4.40% | 1/1 | 0 s | 4 | 6 |
| Offset | M8 | 0.276 | 5.49% | 1/1 | 1 s | 5 | 2 |
| Jump | M5 | 0.286 | 6.60% | 1/1 | 0 s | 7 | 7 |
| Jump | M8 | 0.533 | 5.66% | 1/1 | 1 s | 6 | 1 |
| Drift | M5 | 0.160 | 3.30% | 1/1 | 1 s | 3 | 5 |
| Drift | M8 | 0.000 | 0.00% | 0/1 | missed | 0 | 0 |

On this smoke only, M8 had fewer alarms on the normal trip and higher F1 for
offset and jump. It missed drift, which M5 detected. The results do **not**
support a claim that M8 improves detection overall. The changed calibration,
attack settings, and route also mean this smoke is not a direct replication of
M7's final-test conditions.

## Reproduction and preservation

From the nested project root, run the two identical-seed workflows with new run
IDs:

```powershell
python -m src.experiments.m8_evaluation --config config/m8_detector.yaml --run-id m8_stage1_smoke_02
python -m src.experiments.m8_evaluation --config config/m8_detector.yaml --run-id m8_stage1_smoke_03
python -c "from pathlib import Path; from src.experiments.m8_evaluation import compare_runs; print(compare_runs(Path('reports/m8/m8_stage1_smoke_02'), Path('reports/m8/m8_stage1_smoke_03')))"
python -m unittest tests.test_m8_detector tests.test_m8_evaluation -v
python -m unittest discover -s tests -v
```

Deterministic CSV, JSON, and PNG outputs are compared byte-for-byte; `metadata.json`
is excluded because the run ID differs. In the recorded repeat, **44 of 44**
compared files matched. The protected M0–M7 manifest contained 2,540 files
before and after with identical SHA-256 manifest hash
`bd52c2963f60ce780e395be119677214fbdd5e1f5f2092b3eb14abf03d4e33f5` and no
changed paths.

The initial attempt `m8_stage1_smoke_01` completed its two calibration trips
and validation trip, then stopped before the smoke trip because its route path
was resolved against the wrong directory. It is an incomplete preserved output
directory and was not overwritten. Runs `m8_stage1_smoke_02` and `_03` use the
corrected config-relative route resolution.

Verification: the M8-specific unittest command passed all 16 tests, and
`python -m unittest discover -s tests -v` passed all 78 repository tests.
The full-suite M0/M1 integration test wrote a fresh timestamped truth CSV and
its config/metadata sidecars under `data/raw/`; these three new untracked
artifacts were preserved. Removing those three test-generated paths from the
post-suite manifest reproduces the pre-suite 2,540-file M0-M7 manifest exactly.

Stage 1 implementation files are isolated to `config/m8_detector.yaml`,
`src/detection/m8_detector.py`, `src/experiments/m8_evaluation.py`,
`tests/test_m8_detector.py`, `tests/test_m8_evaluation.py`, and this document.
README.md and TASKS.md were not changed. Any M8 index/status edits to those
shared files are proposed separately for approval.
