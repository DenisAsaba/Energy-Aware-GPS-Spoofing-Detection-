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

M9 Stage 1 validation remains a separate result set. Stage 2 final held-out
results, run only after explicit approval, are recorded below; validation and
final-test results are not pooled.

## M9 Stage 2 — Final held-out evaluation

### Frozen setup and allocation

Stage 2 used the approved final seeds 2501–2506, two seeds per profile:

| Profile | Seeds | SUMO trips | Normal controls | Attack events |
|---|---|---:|---:|---:|
| `urban_turns_light` | 2501, 2504 | 2 | 2 | 24 |
| `urban_stop_restart` | 2502, 2505 | 2 | 2 | 24 |
| `urban_brake_accel` | 2503, 2506 | 2 | 2 | 24 |
| **Total** | **2501–2506** | **6** | **6** | **72** |

Each of the six route trips supplies one normal GPS control and all 12 approved
attack variants. Thus the experiment has six simulated trips, six normal
control datasets, 72 attack datasets/events, and 78 prediction datasets. Each
seed has four events per attack type; each profile has eight events per type;
each exact case ID occurs six times overall and twice per profile.

The matrix matches M8 Stage 2B: four offsets (30/60 m by 10/25 s), four jumps
(30/60 m by **1/5 s**), and four drifts (0.5/1.0 m/s by 10/25 s, capped at
20 m). Every case begins at 35 s. Directions are 90° for offsets, 45° for
jumps, and 0° for drift. The M9 Stage 1 60 m / 8 s jump remains unchanged in
the Stage 1 `attacks` section and was not included in the final matrix because
it is absent from historical M8 Stage 2B.

M5 thresholds, M8 thresholds and 2-of-5 persistence, and all staged fusion
windows were frozen. M5 and M8 predictions, followed by keyed OR/AND/staged
outputs, were written from GPS-only files before labels were read for scoring.
All systems used matched `(time_s, vehicle_id)` observations. The staged
fast-suspect result is the unchanged immediate M5 stream; corroboration is
reported as a separate state.

### Normal-driving false alarms

Normal FPR is computed only on the six normal controls. Pooled rates sum false
positive and eligible observation counts before division. “Alarm episodes”
counts rising edges in the normal alert stream; false-positive observations
and episodes are distinct measures.

| System | Pooled normal FPR (FP / eligible) | Normal alarm episodes | Turns/light FPR | Stop/restart FPR | Brake/accel FPR |
|---|---:|---:|---:|---:|---:|
| M5 | 2.98% (16/537) | 15 | 3.54% | 3.49% | 1.80% |
| M8 | 7.26% (39/537) | 7 | 9.60% | 9.88% | 1.80% |
| OR | 9.12% (49/537) | 16 | 11.62% | 12.21% | 2.99% |
| AND | 1.12% (6/537) | 5 | 1.52% | 1.16% | 0.60% |
| Staged fast suspect | 2.98% (16/537) | 15 | 3.54% | 3.49% | 1.80% |
| Staged corroborated | 5.77% (31/537) | 4 | 8.59% | 5.23% | 2.99% |

Per-profile eligible denominators were 198 turns/light, 172 stop/restart, and
167 brake/accel observations for each system. M8, OR, and staged corroborated
exceeded 5% pooled normal FPR; OR had the highest pooled false-positive count.
The 5% target is descriptive here and was not used to retune or select a final
policy.

### Active attack events and delay

| System | Events detected | Mean delay among detected events |
|---|---:|---:|
| M5 | 58/72 (80.6%) | 1.33 s |
| M8 | 60/72 (83.3%) | 0.40 s |
| OR | 66/72 (91.7%) | 0.65 s |
| AND | 50/72 (69.4%) | 1.12 s |
| Staged fast suspect | 58/72 (80.6%) | 1.33 s |
| Staged corroborated | 52/72 (72.2%) | 0.46 s |

Fast-suspect results exactly equal M5, as defined. They do not show a change in
M5 recall or delay. By type, M5 detected all 24 offsets, all systems detected
all offsets, and offset mean delay ranged from 0 s (M5, OR, staged fast) to
0.33 s (M8, AND, staged corroborated). Detection was weaker for drift: M5
10/24, M8 16/24, OR 18/24, AND 6/24, staged fast 10/24, and staged
corroborated 8/24. Exact results by profile, magnitude/rate, duration, and
system are in `attack_event_summary.csv`; per-event delays are in
`trip_metrics.csv`.

Per-profile event detection is shown with mean delay among detected events:

| Profile | M5 | M8 | OR | AND | Staged fast | Staged corroborated |
|---|---:|---:|---:|---:|---:|---:|
| Turns/light | 18/24 (1.67 s) | 24/24 (0 s) | 24/24 (0 s) | 18/24 (1.78 s) | 18/24 (1.67 s) | 20/24 (0 s) |
| Stop/restart | 22/24 (0.55 s) | 24/24 (0.50 s) | 24/24 (0.33 s) | 20/24 (0.60 s) | 22/24 (0.55 s) | 20/24 (0.60 s) |
| Brake/accel | 18/24 (1.94 s) | 12/24 (1.00 s) | 18/24 (1.94 s) | 12/24 (1.00 s) | 18/24 (1.94 s) | 12/24 (1.00 s) |

#### Short and longer jump comparison

Each duration row contains 12 events: two magnitudes across three profiles and
two seeds per profile.

| System | 1 s jumps detected | Mean delay | 5 s jumps detected | Mean delay |
|---|---:|---:|---:|---:|
| M5 | 12/12 | 0 s | 12/12 | 0 s |
| M8 | 8/12 | 0 s | 12/12 | 0.33 s |
| OR | 12/12 | 0 s | 12/12 | 0 s |
| AND | 8/12 | 0 s | 12/12 | 0.33 s |
| Staged fast suspect | 12/12 | 0 s | 12/12 | 0 s |
| Staged corroborated | 8/12 | 0 s | 12/12 | 0.33 s |

For both 30 m and 60 m jumps, the 1 s versus 5 s event counts follow the same
pattern: M5/OR/staged fast detected 6/6 at each duration; M8/AND/staged
corroborated detected 4/6 at 1 s and 6/6 at 5 s. These are event-level
descriptive results, not evidence of generalization.

### Prediction overlap, persistence, and coverage

Across matched jointly eligible observations, M5/M8 overlap was:

| Label state | Both alert | M5 only | M8 only | Neither |
|---|---:|---:|---:|---:|
| Attack active | 106 | 34 | 235 | 537 |
| Normal or attack inactive | 123 | 114 | 534 | 5,298 |

The alarm ledger records each activation, clearing observation, and episode
length separately for all six output streams. In normal controls, the system
episode counts are listed above. Across attack datasets the episode totals
were M5 234, M8 113, OR 201, AND 143, staged fast 234, and staged corroborated
96. Post-attack alert observations across the 72 attack datasets were 161,
414, 482, 93, 161, and 544 respectively; these are counts, not event recall.

Each prediction dataset had one initial ineligible/warm-up observation;
eligible denominators exclude it. Across each detector stream this accounts
for 78 ineligible observations over 78 datasets. There were no unmatched
predictions on eligible keys. Labels include the ineligible first observation,
so it appears as one unmatched label per dataset and is excluded from scoring.
The detailed per-dataset counts are in `prediction_coverage.csv`.

### Reproducibility, preservation, and limits

The first two runs (`m9_stage2_final_01` and `_02`) compared byte-for-byte on
242 CSV files. During review, the attack summary’s episode grouping was found
to pool cases incorrectly, the normal alarm episode count counted datasets
with an alarm instead of alarm episodes, and an inactive-observation rate was
labeled as normal FPR. No predictions, labels, thresholds, or detector
policies changed. The reporting aggregation was corrected; the complete
evaluation was repeated as `_03` and `_04`, which also matched byte-for-byte on
242 CSV files. The 222
attack/GPS/prediction CSV files in `_01` and `_03` are byte-identical. Use
`_03` and `_04` as the canonical corrected report runs; the earlier runs remain
preserved as audit history.

All 105 repository tests passed, including 20 M9-specific tests. The M0–M8
protected baseline had no hash changes (4,552 baseline files excluding the
M9 tracker edit). All 1,658 pre-existing M9 report files were unchanged at the
start of the canonical run, and all frozen code/input hashes matched after
evaluation. The protected baseline manifest digest, excluding the tracker,
was `052b8ec5689a6e70c40d738cd9b3852880dc809a1af6c6ad2ed24b0ad53f6620`.

Frozen hashes for the canonical run include:

| Artifact | SHA-256 |
|---|---|
| `config/m9_analysis.yaml` | `4916eb391982592e1c01afb177f893475991e53f6096fe3562056ff26cdf8a77` |
| `config/m8_stage2b.yaml` | `24a21860864b60c96a9a73b1a029c9a457cb052506468e35fd2fa94ec53faaaa` |
| `src/detection/m8_detector.py` | `65c4323e40328f0f1f0493a5a0c9afebc420b1cfdede067cb424f8a38d36ba7d` |
| `src/detection/m9_hybrid.py` | `b8d72f1f61f7373c64ca51f1b77918a6f96a80723ccd6665a373c28158371cdd` |
| `src/experiments/m9_final_evaluation.py` | `51411049e11692351b916d89080220b9a46d73422534a227c1ebadea5136106e` |
| Historical M8 Stage 2B `metadata.json` | `816a70833c1d8e1ad2e4a0f028afb43aee00ccd5ef5bb162dad8a214fc60b2ab` |

Reproduction commands (use a new run ID because existing outputs are protected):

```powershell
python -m src.experiments.m9_final_evaluation --config config/m9_analysis.yaml --run-id m9_stage2_reproduction_01
python -m src.experiments.m9_final_evaluation --config config/m9_analysis.yaml --run-id m9_stage2_reproduction_02
python -c "from pathlib import Path; from src.experiments.m9_final_evaluation import compare_runs; r=compare_runs(Path('reports/m9/m9_stage2_reproduction_01'), Path('reports/m9/m9_stage2_reproduction_02')); print(r); assert r['byte_identical']"
python -m unittest discover -s tests -v
```

The six trips support descriptive comparisons only; no confidence intervals
or claims of broad generalization are made. A GPS motion anomaly does not
prove spoofing. Smooth constant translation and plausible slow drift can be
unobservable from GPS motion alone. Corroboration is not confirmed spoofing,
and these results do not establish production readiness. M9 Stage 2 ends here.
