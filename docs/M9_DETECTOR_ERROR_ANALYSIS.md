# M9 Stage 1 — Detector Error Analysis and Hybrid Fusion

## Scope and frozen baselines

M9 Stage 1 adds a read-only analysis of the existing M8 Stage 2B prediction
records and evaluates fusion on a new disjoint calibration/validation split.
A three-seed smoke preceded the full six-seed validation repeat. It does not
open M9 final-test seeds 2501–2506 and does not modify M5 or
M8 source, thresholds, configuration, or reports. M5/M8 predictions use the
same observed GPS CSV and are aligned by `(time_s, vehicle_id)`.

The frozen M5 thresholds are 21.143275 m/s speed, 17.433802 m/s speed change,
and 170.598147 degrees heading change. M8 adds 17.433802 m/s² absolute
acceleration and 6.833180 m/s rolling-speed consistency, with 2-of-5 persistence
and clearing after three clean eligible fixes. The thresholds and M8 persistence
are copied from the approved M8 Stage 2B configuration.

SUMO X/Y coordinates are local road-network meters; time is seconds; the
simulation step is 1 second. GPS uses independent, zero-mean Gaussian noise of
3 m standard deviation per axis, with deterministic seeds. Each M9 prediction
input contains only `time_s`, `vehicle_id`, `gps_x_m`, and `gps_y_m`. Truth,
labels, route progress, future fixes, and M4 residuals are excluded. Attack
labels are loaded only after M5, M8, and all fusion predictions have been
written.

## Split audit and Stage 1 smoke protocol

The proposed seed ranges 2301–2306 (calibration), 2401–2406 (validation), and
2501–2506 (final test) did not occur as assignments in existing configs or
reports. M8 reserved test seeds 1301 and 1302 remain retired. Two seeds per
profile are assigned in each six-seed split by cycling through turns/light,
stop/restart, and brake/accel profiles.

Stage 1 used the first three calibration seeds (2301–2303) and first three
validation seeds (2401–2403), one trip per profile, as a small workflow smoke.
The other seeds remain assigned but unused. Calibration trips produce normal
reference metrics only. They do not recalibrate M5/M8 thresholds or tune
fusion: those baselines are frozen, and the association/clearing windows are
specified in advance. The validation attack smoke uses the M8 Stage 2A attack
settings: 30 m eastward offset for 25 s, 60 m jump for 8 s, and 1 m/s northward
drift for 25 s capped at 20 m, all beginning at 35 s. This creates 3 normal
validation trips and 9 paired attack datasets. It is not the final evaluation.

The existing-data analysis reads `reports/m8/stage2b/m8_stage2b_final_02`, which
contains the already-opened M8 test seeds 1301/1302. Those are used only for
retrospective error analysis, not as fresh M9 held-out evidence.

## Fusion definitions

- **OR:** alert on a joint-eligible observation when M5 or M8 predicts an
  alert.
- **AND:** alert only when both predict an alert on the same keyed observation.
- **Staged:** emit the M5 fast-suspect flag immediately; expose the unchanged
  M8 latched prediction as corroboration; separately latch corroborated
  suspicion when M8 is active during an M5 event window. No suspect is delayed
  or suppressed.

An M5 event window includes its initiating jointly eligible observation and
the next two jointly eligible observations. A further M5 hit while the current
window remains open refreshes that same event window. M8 corroborates when its
unchanged prediction is active on any jointly eligible fix in that window.
Corroborated suspicion remains active until three consecutive jointly eligible
observations have both M5 and M8 inactive. Missing or ineligible rows do not
advance event age or clean-fix clearing. An eligible M5 row still emits its
immediate fast-suspect flag if its M8 counterpart is missing; OR/AND and event
association are undefined on that unmatched key. State and event IDs are
separate per vehicle. The two-observation window uses only current/past
predictions; it does not read future fixes.

The staged system reports the fast-suspect and corroborated-suspicion streams
separately. For candidate selection, its binary alert is the unsuppressed fast
suspect; corroborated-event detection is a separate diagnostic. This preserves
short-event sensitivity and makes the false-alarm cost of the stronger state
visible instead of hiding it in one binary column.

## Existing M5/M8 error analysis

The historical M8 final matrix has 520 matched normal observations across six
normal trips. In the normal controls, the joint overlap was:

| Outcome | Observations |
|---|---:|
| Both alert | 2 |
| M5 only | 11 |
| M8 only | 23 |
| Neither alerts | 484 |

Across the active portions of all 72 attack datasets, overlap was 39 both, 77
M5-only, 209 M8-only, and 587 neither. These are repeated observations across
attack variants, not independent trip counts. `joint_prediction_overlap.csv`
retains each keyed observation, its profile, dataset, active/normal label, and
overlap category.

M5 had 13/520 normal false positives (2.50% FPR); M8 had 25/520 (4.81%). M8
normal FPR was 6.98% in turns/light and 7.78% in brake/accel, versus 0% in
stop/restart. OR produces 36/520 false positives (6.92%) and AND 2/520 (0.38%).
OR therefore preserves M5's event coverage but adds M8-only false alarms; AND
reduces false alarms but loses events not shared by the detectors.

| Normal profile FPR | M5 | M8 | OR | AND | Staged fast suspect | Staged corroborated |
|---|---:|---:|---:|---:|---:|---:|
| Turns/light | 1.74% | 6.98% | 8.14% | 0.58% | 1.74% | 9.30% |
| Stop/restart | 2.76% | 0.00% | 2.76% | 0.00% | 2.76% | 0.00% |
| Brake/accel | 2.99% | 7.78% | 10.18% | 0.60% | 2.99% | 10.18% |

| Historical active event detection | M5 | M8 | OR | AND | Staged fast suspect | Staged corroborated |
|---|---:|---:|---:|---:|---:|---:|
| Offset | 24/24 | 22/24 | 24/24 | 22/24 | 24/24 | 24/24 |
| Jump | 24/24 | 12/24 | 24/24 | 12/24 | 24/24 | 14/24 |
| Drift | 15/24 | 7/24 | 15/24 | 5/24 | 15/24 | 7/24 |

Staged corroboration mean delay was 0.83 s for offset, 0.71 s for jump events
it corroborated, and 8.14 s for drift. OR's event coverage matches M5 on this
matrix. AND inherits M8's one-second-jump misses. The staged fast path retains
M5's event detections; the corroborated state is not proof of spoofing.

### Magnitude, duration, and representative errors

The historical Stage 2B report shows M8 detected 0/6 one-second jump events at
both 30 m and 60 m, versus 6/6 for M5 at each magnitude. For five-second jumps,
both detectors detected 6/6 at either magnitude, with M8's mean delay 1 s.
Across the 24 jump trips, staged corroboration detected 2/12 one-second events
and 12/12 five-second events. On a 30 m, one-second jump at 35 s, the M5
prediction flags the active fix immediately; M8 has a single raw anomaly and
does not satisfy 2-of-5. M8 first alarms at 37 s, after the `[35, 36)` attack
window. This is consistent with persistence suppressing a one-fix event and
then responding to recovery dynamics.

For offset, M8 detected 5/6 events at 30 m for both 10 s and 25 s, and 6/6 at
60 m for both durations; M5 detected all six events in each of those four
conditions. This shows a magnitude effect in the M8 results, while longer
duration alone did not resolve its misses in these two-seed condition groups.

Drift remained difficult: historical active-event detection was 15/24 for M5
and 7/24 for M8. By M8 drift settings, M8 detected 4/6 for 0.5 m/s over 10 s,
2/6 for 0.5 m/s over 25 s, 1/6 for 1.0 m/s over 10 s, and 3/6 for 1.0 m/s over
25 s. The capped drift can remain within ordinary GPS-derived motion limits;
these data do not distinguish detector feature limits from fundamental
GPS-only ambiguity.

A normal turns/light trip at time 27 s triggered M8 speed consistency at
6.8621 m/s, just above its 6.8332 m/s threshold; M5 stayed inactive. M8 remained
latched through subsequent clean fixes. Across the historical prediction
records, the extracted M8 alarm stream had 112 activation and 112 clear
transitions; observed active spans lasted 4–18 eligible fixes (mean 7.61).
The configured clearing rule requires three consecutive clean eligible fixes,
so spans can be longer when raw anomalies recur. Across normal M8 false-positive
records, post-hoc annotations associated alarms with acceleration (11),
braking (5), turns (3), stops (2), restarts (1), and traffic profiles (13),
with overlapping categories. These are associations based on simulator truth,
not detector inputs or causal explanations. The isolated M9 false-positive
records and M8 activation/clear transitions are in
`historical_normal_false_positives.csv` and
`historical_m8_persistence_transitions.csv`.

Mean per-trip post-attack alert rates across the 24 historical trips per attack
type were:

| Attack | M5 | M8 | OR | AND | Staged fast suspect | Staged corroborated |
|---|---:|---:|---:|---:|---:|---:|
| Offset | 7.5% | 24.4% | 27.5% | 4.4% | 7.5% | 31.6% |
| Jump | 5.8% | 20.9% | 22.1% | 4.5% | 5.8% | 26.6% |
| Drift | 3.0% | 6.8% | 9.0% | 0.8% | 3.0% | 8.8% |

These are unweighted means of trip-level rates; denominators vary with trip
length and attack end time. Per-trip counts and eligible denominators are in
`historical_error_metrics.csv`.

## New validation results

The initial three-seed smoke verified the workflow. The final Stage 1 selection
uses the complete six-seed calibration and six-seed validation splits: two
trips per profile in each split. All five systems used identical GPS files.
Validation contains 514 eligible normal observations and 18 attack events (six
each for offset, jump, and drift). The 5% limit applies to pooled validation
normal observations.

| System / candidate | Normal FP / fixes | Normal FPR | Active events detected | Mean delay when detected |
|---|---:|---:|---:|---:|
| M5 reference | 10 / 514 | 1.95% | 15/18 | 0.27 s |
| M8 reference | 14 / 514 | 2.72% | 12/18 | 1.0 s |
| OR | 20 / 514 | 3.89% | 15/18 | 0.27 s |
| AND | 4 / 514 | 0.78% | 12/18 | 1.0 s |
| Staged fast-suspect alert | 10 / 514 | 1.95% | 15/18 | 0.27 s |

Staged corroboration confirmed 12/18 attack events, with 1.0 s mean delay for
confirmed events. Its latched corroborated-suspicion state produced 18/514
normal false-positive observations (3.50%); profile FPR was 0% in turns/light,
5.08% in stop/restart, and 5.45% in brake/accel. By attack type, staged fast
suspect detected offset 6/6 and jump 6/6 at 0 s mean delay, and drift 3/6 at
1.33 s. Corroborated suspicion detected offset 6/6 and jump 6/6 at 1 s, and
drift 0/6. The final M9 validation selection records **staged**: it retains
M5's immediate suspect output and adds separate corroboration. It does not
improve event recall over M5; it adds a distinct confidence state. OR matched
staged's fast-suspect event coverage but had twice as many normal false
positives. AND reduced false alarms further but detected only 12/18 events.

Post-attack alert-observation counts across the six validation attack datasets
per type, in M5/M8/OR/AND/staged-fast/staged-corroborated order, were offset
**12/39/44/7/12/51**, jump **16/51/53/14/16/65**, and drift **9/26/30/5/9/34**.
The validation CSV reports each count's eligible denominator and rate.

The selected fast-suspect pooled FPR meets the 5% target, but profile-level
rates for the separate corroborated state exceed 5% in two profiles. Results
are descriptive across six validation trips and do not support broad
generalization.
No final-test data were generated or opened. GPS-only anomalies remain
statistical signals, not confirmed attack attribution: a smooth position
translation or sufficiently slow drift can remain plausible, while real
maneuvers can resemble spoofing.

## Outputs, reproducibility, and commands

Each run is isolated under `reports/m9/<run-id>/`; an existing ID is refused.
It contains per-observation joint overlap, historical metrics and false
positive/persistence records, new-trip manifests, prediction CSVs, validation
metrics, candidate selection, and a summary. The workflow verifies all 4,553
pre-existing file hashes, reporting the intentional M9 progress edit in
`TASKS.md` separately. A final post-cleanup check found no missing or changed
pre-existing files other than that tracker edit.
New data and outputs are simulation-only.

The full validation execution and independent repeat produced 98 comparable
CSV outputs each; 98/98 matched byte-for-byte. The comparison excludes only
`trip_manifest.csv`, which stores hashes of generated network/config artifacts
whose serialization and absolute paths vary between runs. The reproduced set
includes truth/GPS/attack/label data, detector predictions, keyed overlap,
metrics, and validation selection.

From the nested repository root:

```powershell
python -m unittest tests.test_m9_hybrid -v
python -m src.experiments.m9_error_analysis --config config/m9_analysis.yaml --run-id m9_stage1_validation_06
python -m src.experiments.m9_error_analysis --config config/m9_analysis.yaml --run-id m9_stage1_validation_07
python -c "from pathlib import Path; from src.experiments.m9_error_analysis import compare_runs; r=compare_runs(Path('reports/m9/m9_stage1_validation_06'), Path('reports/m9/m9_stage1_validation_07')); print(r); assert r['byte_identical']"
python -m unittest discover -s tests -v
```

M9 Stage 1 stops here. Do not evaluate seeds 2501–2506 until approval.
