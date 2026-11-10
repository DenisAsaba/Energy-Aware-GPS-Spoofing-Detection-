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

## Stage 2A: expanded normal driving and validation

Stage 2A adds a separate 2x2 M8-only SUMO grid (four 180 m blocks, with
directed links in both directions) and three normal scenario profiles. Each EV
completes a 720 m loop with a stop at simulation time zero, turns, and SUMO
acceleration/deceleration. The `urban_turns_light` profile uses speedFactor
0.78 and no background traffic. `urban_stop_restart` uses speedFactor 0.88,
five shared-route passenger vehicles, and a 5 s curbside dwell. The
`urban_brake_accel` profile uses the reverse loop, speedFactor 1.0, twelve
shared-route passenger vehicles, and a 3 s curbside dwell. EV parameters are
accel 1.7 m/s², decel 4.0 m/s², maxSpeed 13.89 m/s; background traffic uses
accel 2.0 m/s², decel 4.5 m/s² and maxSpeed 13.89 m/s. SUMO step length is
1 s. Traffic departures use the run seed; observed behavior is from SUMO's
car-following model. This small network has no traffic lights or lane changes,
so the dwell events and traffic profiles are controlled simulation cases,
not a validated model of a specific city.

Each run has six complete calibration trips and six complete validation trips,
two per scenario. Calibration seeds are 2101–2106 and validation seeds are
2201–2206, with scenario order turns/light, stop/restart, brake/accel repeated
twice. Calibration and validation are disjoint from each other and from the
reserved final-test seeds 1301/1302. M7 final-test seeds 803/804 are not used.
The reserved final configuration in `config/m8_detector.yaml` was not changed
or run. `config/m8_stage2a.yaml` sets 3 m per-axis Gaussian GPS noise, GPS seed
offset 68000, 99th percentile calibration, and a 50% chronological prefix per
normal calibration trip. Per-trip network, node, edge, and route SHA-256 values
are recorded in each run's `metadata.json`; the config snapshot is also kept in
the run directory.

Thresholds use only the six normal calibration trips. M5's detector
implementation is unchanged and was recalibrated using the same expanded
normal calibration data. M5 and M8 were scored on identical normal and attack
GPS observations. Validation operating selection uses the predeclared 5% FPR
target and then active event detection. The selected policy was 2-of-5 fixes,
clearing after 3 clean fixes. It had a 4.23% pooled normal FPR. The 2-of-3
policy had 3.02% FPR and 66.7% mean event detection; 2-of-5 had 4.23% FPR and
72.2% mean event detection. The more sensitive 1-of-1 policy had 10.69% FPR
and did not meet the target. The selected policy therefore meets the target on
this validation sample; this is not final-test evidence.

The fitted Stage 2A 99th-percentile normal thresholds were 21.1433 m/s GPS
speed, 17.4338 m/s absolute speed change, 170.5981° heading change, 17.4338
m/s² absolute acceleration, and 6.8332 m/s speed-consistency difference. The
pooled calibration included 245 speed, 239 speed-change, 239 heading-change,
239 acceleration, and 221 speed-consistency feature values from the
chronological calibration prefixes.

Pooled normal results for selected M8 versus unchanged M5 were: M8 21/496
false-positive observations (4.23%) and 0.50 alarm episodes per trip; M5
17/496 (3.43%) and 2.50 episodes per trip. M8 had fewer alarm episodes but a
higher false-positive observation rate. M8's scenario FPRs were 3.90% on
turns/light, 4.02% on stop/restart, and 4.76% on brake/accel. M5's were 3.25%,
5.17%, and 1.79%, respectively. Selected M8 alert observations overlapped
truth-based turn, braking, acceleration, stop, restart, and nonzero-traffic
conditions as follows: 0 turns, 0 braking, 9 accelerating, 6 stopped, 2
restarting, and 15 in traffic scenarios. M5 had 2 turns, 3 braking, 7
accelerating, 5 stopped, 1 restarting, and 12 in traffic scenarios. These
categories overlap and are descriptive associations, not causal explanations.

Selected M8 attack validation results (six observations per attack type):

| Attack | Active events detected | Precision | Recall | F1 | Mean delay among detected | Post-attack alert observations |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Offset | 5/6 | 0.543 | 0.253 | 0.346 | 1.2 s | 26 |
| Jump | 6/6 | 0.412 | 0.875 | 0.560 | 0.8 s | 54 |
| Drift | 2/6 | 0.405 | 0.100 | 0.160 | 8.0 s | 16 |

Active-event detection by normal-driving scenario (two validation trips per
scenario) was:

| Detector | Attack | Turns/light | Stop/restart | Brake/accel |
| --- | --- | ---: | ---: | ---: |
| M5 | Offset | 2/2 | 2/2 | 2/2 |
| M8 | Offset | 2/2 | 2/2 | 1/2 |
| M5 | Jump | 2/2 | 2/2 | 2/2 |
| M8 | Jump | 2/2 | 2/2 | 2/2 |
| M5 | Drift | 0/2 | 2/2 | 1/2 |
| M8 | Drift | 0/2 | 1/2 | 1/2 |

For comparison, M5 detected offset 6/6, jump 6/6, and drift 3/6; its pooled
F1 was 0.174, 0.345, and 0.036 respectively. Attack results are mixed, and
offset detection regressed for M8. No overall detector improvement has been
established. Stage 1's historical 2-of-3 selection and 8.74% validation FPR
(above the 5% target) remain recorded unchanged above; Stage 2A does not
replace that result.

Two completed Stage 2A workflows (`m8_stage2a_repro_04` and `_05`) matched
across all 89 CSV, JSON, and PNG outputs. `metadata.json` is excluded because
run IDs and protected-manifest timing differ; configuration snapshots and
per-trip hashes remain documented. The protected M0–M7 manifest had 2,546
files, the same SHA-256 before and after, and no changed paths. All existing
Stage 1 output directories were preserved. The full test suite generated one
new timestamped M1 truth CSV and its config/metadata sidecars under
`data/raw/`; these three test outputs were kept. Excluding just those new test
paths from the post-suite manifest reproduces the 2,546-file Stage 2A protected
manifest exactly. The M8-specific tests passed 19 tests; the full repository
suite passed 81 tests. The full M8 final-test matrix has **not** been run.

Reproduction commands from the nested project root (use new run IDs):

```powershell
python -m src.experiments.m8_stage2a --config config/m8_stage2a.yaml --run-id m8_stage2a_repro_04
python -m src.experiments.m8_stage2a --config config/m8_stage2a.yaml --run-id m8_stage2a_repro_05
python -c "from pathlib import Path; from src.experiments.m8_evaluation import compare_runs; print(compare_runs(Path('reports/m8/stage2a/m8_stage2a_repro_04'), Path('reports/m8/stage2a/m8_stage2a_repro_05')))"
python -m unittest tests.test_m8_detector tests.test_m8_evaluation tests.test_m8_stage2a -v
python -m unittest discover -s tests -v
```

No final-test execution is authorized by this stage. Stop here pending approval.
