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

At the close of Stage 2A, the final matrix was still unrun. Stage 2B was
subsequently approved and its results are reported below.

## Stage 2B: frozen final held-out evaluation

Stage 2B ran only after approval, using reserved seeds 1301 and 1302. The
Stage 1 final seed assignments and `config/m8_detector.yaml` were not changed.
The Stage 2B config is a new file with the same reserved seeds and an explicit
attack matrix. M8 used the frozen Stage 2A thresholds and policy: 2-of-5
eligible fixes, clearing after 3 clean fixes. M5 used the unchanged M5
algorithm with its first three frozen thresholds from the same approved Stage
2A normal calibration trips. No final observations entered calibration or
validation; the Stage 2B workflow rejects overlap and checks its configured
thresholds against the approved Stage 2A report before simulation.

Each final seed ran one complete normal trip in each of the three expanded
profiles. For each of the six seed/profile trips, the same normal GPS file was
used to derive all attack datasets: two offset magnitudes (30/60 m) by two
durations (10/25 s), two jump magnitudes (30/60 m) by two durations (1/5 s),
and two drift rates (0.5/1.0 m/s) by two durations (10/25 s), with a 20 m drift
cap. Attack onset was 35 s. The final matrix contains 6 normal trips and 72
attack datasets; both detectors were evaluated on identical observations.
Outputs include per-trip metrics, separate observation and event summaries,
paired trip comparisons, predictions, truth/GPS/attack inputs, and plots.

### Normal false alarms

Across 520 eligible normal observations, M8 had 25 false positives and 495
true negatives (FPR **4.81%**, TNR 95.19%); M5 had 13 false positives and 507
true negatives (FPR **2.50%**, TNR 97.50%). M8 meets the pooled 5% target, but
its FPR exceeded 5% in the turns/light and brake/accel profiles:

| Normal scenario | M5 FP / negatives | M5 FPR | M8 FP / negatives | M8 FPR | Alarm episodes per trip, M5 / M8 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Turns/light | 3/172 | 1.74% | 12/172 | 6.98% | 1.00 / 1.00 |
| Stop/restart | 5/181 | 2.76% | 0/181 | 0.00% | 2.50 / 0.00 |
| Brake/accel | 5/167 | 2.99% | 13/167 | 7.78% | 2.00 / 1.00 |

Overall, M8 had fewer normal alarm episodes per trip (0.67 vs 1.83), despite
nearly doubling the count of false-positive observations. The 25 M8 false
alarm observations were associated with acceleration (11), braking (5),
turns (3), stops (2), restarts (1), and traffic profiles (13); these categories
overlap. M5's 13 false alarms overlapped acceleration (3), braking (3), turns
(2), stops (1), and traffic profiles (10). These associations use truth only
for post-hoc analysis and do not explain causality.

### Attack results

The following observation-level metrics pool the 24 trips per attack type
(three profiles × two seeds × four intensity/duration combinations). Event
detection and delay are reported separately; alerts after the active window
are not counted as successful detections.

| Attack | Detector | TP | FP | TN | FN | Precision | Recall | F1 | FPR | TNR | Active events | Miss rate | Mean delay, detected events | Post-attack alert rate | Alerts/trip |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Offset | M5 | 58 | 74 | 1586 | 362 | .439 | .138 | .210 | 4.46% | 95.54% | 24/24 | 0.0% | 0.0 s | 7.14% | 3.33 |
| Offset | M8 | 160 | 226 | 1434 | 260 | .415 | .381 | .397 | 13.61% | 86.39% | 22/24 | 8.3% | 1.0 s | 23.27% | 2.21 |
| Jump | M5 | 36 | 82 | 1926 | 36 | .305 | .500 | .379 | 4.08% | 95.92% | 24/24 | 0.0% | 0.0 s | 5.76% | 2.96 |
| Jump | M8 | 48 | 274 | 1734 | 24 | .149 | .667 | .244 | 13.65% | 86.35% | 12/24 | 50.0% | 1.0 s | 20.56% | 1.50 |
| Drift | M5 | 22 | 37 | 1623 | 398 | .373 | .052 | .092 | 2.23% | 97.77% | 15/24 | 37.5% | 4.7 s | 2.88% | 2.04 |
| Drift | M8 | 40 | 79 | 1581 | 380 | .336 | .095 | .148 | 4.76% | 95.24% | 7/24 | 70.8% | 8.1 s | 6.34% | 0.79 |

M8 did **not** improve active event detection for any attack type: offset was
22/24 vs M5's 24/24, jump 12/24 vs 24/24, and drift 7/24 vs 15/24. Its
observation F1 improved for offset and drift but dropped for jump; all three
attack types had greater M8 false-positive rates in attack datasets, and M8
had longer delay for detected events. Jump detection was especially sensitive
to duration: M8 detected 0/6 one-second jumps at either magnitude, versus 6/6
for each five-second jump condition. The complete condition breakdown is in
`condition_summary.csv` and `event_summary.csv`.

Post-attack alert rate is the number of predicted-alert observations at or
after the configured attack end divided by eligible observations from attack
end through trip completion. These alerts are reported separately and never
count toward active event detection.

| Attack condition | M5 active events | M8 active events | M5 F1 | M8 F1 | M5 FPR | M8 FPR | M8 mean delay when detected |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Offset 30 m, 10 s | 6/6 | 5/6 | .283 | .417 | 4.1% | 11.7% | 1.0 s |
| Offset 30 m, 25 s | 6/6 | 5/6 | .165 | .300 | 4.6% | 13.0% | 1.0 s |
| Offset 60 m, 10 s | 6/6 | 6/6 | .298 | .523 | 4.3% | 14.6% | 1.0 s |
| Offset 60 m, 25 s | 6/6 | 6/6 | .174 | .389 | 4.9% | 15.4% | 1.0 s |
| Jump 30 m, 1 s | 6/6 | 0/6 | .387 | .000 | 3.7% | 14.2% | — |
| Jump 30 m, 5 s | 6/6 | 6/6 | .393 | .421 | 3.9% | 12.2% | 1.0 s |
| Jump 60 m, 1 s | 6/6 | 0/6 | .353 | .000 | 4.3% | 14.4% | — |
| Jump 60 m, 5 s | 6/6 | 6/6 | .375 | .397 | 4.5% | 13.7% | 1.0 s |
| Drift 0.5 m/s, 10 s | 4/6 | 1/6 | .135 | .141 | 2.0% | 4.1% | 1.0 s |
| Drift 0.5 m/s, 25 s | 5/6 | 2/6 | .097 | .125 | 1.9% | 4.1% | 10.5 s |
| Drift 1.0 m/s, 10 s | 2/6 | 1/6 | .083 | .135 | 2.0% | 5.0% | 1.0 s |
| Drift 1.0 m/s, 25 s | 4/6 | 3/6 | .071 | .180 | 3.2% | 5.9% | 11.3 s |

Active-event detection pooled over all four attack settings, by driving
profile, was:

| Attack | Turns/light M5 / M8 | Stop/restart M5 / M8 | Brake/accel M5 / M8 |
| --- | ---: | ---: | ---: |
| Offset | 8/8 / 6/8 | 8/8 / 8/8 | 8/8 / 8/8 |
| Jump | 8/8 / 4/8 | 8/8 / 4/8 | 8/8 / 4/8 |
| Drift | 4/8 / 4/8 | 7/8 / 1/8 | 4/8 / 2/8 |

### Paired seed-level comparison and limitations

Trip-level paired outputs are grouped by scenario and attack condition in
`paired_trip_comparisons.csv`. For an additional seed-cluster summary, trip
results were pooled within each reserved seed before calculating M8-minus-M5
paired differences. Each mean and sample standard deviation below is based on
**two seed clusters** (1301 and 1302), not individual fixes or repeated
intensity cases. No confidence interval is reported: two independent seeds do
not support a useful inferential interval.

| Outcome | Mean paired difference (M8 − M5) | Sample SD across seeds |
| --- | ---: | ---: |
| Normal FPR | +2.17 percentage points | 3.06 pp |
| Offset active event detection | −8.33 pp | 11.79 pp |
| Offset F1 | +0.190 | 0.047 |
| Jump active event detection | −50.00 pp | 0.00 pp |
| Jump F1 | −0.127 | 0.056 |
| Drift active event detection | −33.33 pp | 0.00 pp |
| Drift F1 | +0.063 | 0.063 |

Event detection by seed, pooling each seed's three driving profiles and four
matrix settings per attack type, was: seed 1301, M5/M8 offset 12/12 vs 10/12,
jump 12/12 vs 6/12, drift 6/12 vs 2/12; seed 1302, offset 12/12 vs 12/12,
jump 12/12 vs 6/12, drift 9/12 vs 5/12. Per-trip seed rows are retained in
`trip_metrics.csv`.

M8 meets the pooled 5% normal FPR target but exceeds it in two scenario
profiles, has higher pooled normal FPR than M5, and detects fewer active attack
events for all three types. M8 therefore does **not** improve overall
performance relative to M5 on this held-out matrix. Results are limited to two
reserved seeds and this simulated network/scenario set. They do not establish
universal spoofing detection or production readiness.

### Reproducibility and verification

`m8_stage2b_final_01` and `_02` used the same frozen configuration and seeds.
All **242 of 242** deterministic CSV, JSON, and PNG files matched byte-for-byte.
Only `metadata.json` is excluded from comparison because it records the run ID
and preservation-manifest timing. Both runs report unchanged M0–M7 protected
hashes, unchanged prior M8 report hashes, and unchanged frozen detector/config
hashes. The Stage 1 final seed config remained unchanged. M8-specific tests
passed 23 cases and the complete repository suite passed 85 tests. The full
suite created one new timestamped M1 truth CSV and its config/metadata sidecars;
they were preserved. Excluding those three test artifacts, the M0-M7 protected
manifest returned to its exact pre-run 2,552-file hash. The prior M8 Stage 1
and Stage 2A manifest remained 1,218 files with SHA-256
`8ff08907edda5ae3aa987523b32c6232038b5d9471a8d2f43bdba0f59cc8c37f`.
The full M8 final matrix is complete; no later milestone or detector changes
were made.

Reproduction commands from the nested repository root:

```powershell
python -m src.experiments.m8_stage2b --config config/m8_stage2b.yaml --run-id m8_stage2b_final_01
python -m src.experiments.m8_stage2b --config config/m8_stage2b.yaml --run-id m8_stage2b_final_02
python -c "from pathlib import Path; from src.experiments.m8_evaluation import compare_runs; print(compare_runs(Path('reports/m8/stage2b/m8_stage2b_final_01'), Path('reports/m8/stage2b/m8_stage2b_final_02')))"
python -m unittest tests.test_m8_detector tests.test_m8_evaluation tests.test_m8_stage2a tests.test_m8_stage2b -v
python -m unittest discover -s tests -v
```
