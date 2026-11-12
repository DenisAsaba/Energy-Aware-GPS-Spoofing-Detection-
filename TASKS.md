# Live milestone tracker

**Current milestone:** M9 Stage 2 final held-out evaluation complete; stop before M10 or detector tuning.

### M9 Stage 1: detector error analysis and hybrid fusion
- [x] Audit proposed calibration/validation/final seed ranges against existing configs and reports; preserve a pre-implementation hash manifest.
- [x] Read existing M5/M8 prediction records by keyed observation and report joint overlap, normal false positives, attack misses/delay, post-attack alerts, and M8 persistence transitions.
- [x] Implement isolated OR, AND, and staged fusion; retain immediate M5 suspect alerts and separately expose M8 corroboration/corroborated state.
- [x] Add tests for keyed alignment, fusion truth tables, event association/expiry, missing and ineligible fixes, multiple vehicles, clearing, short events, causal prefix behavior, ignored truth/label fields, deterministic outputs, and no-overwrite behavior.
- [x] Run three-seed-per-split calibration/validation smoke across all three driving profiles; join labels only after prediction files are written.
- [x] Select staged as the validation-smoke candidate under the predeclared 5% fast-suspect FPR limit; report corroborated-state errors separately.
- [x] Repeat Stage 1 smoke under a distinct run ID; compare deterministic input, prediction, label, metric, and selection CSV files.
- [x] Run all six calibration and six validation seeds (two trips per profile) without opening final-test data; select staged fast-suspect with separate corroboration reporting.
- [x] Repeat the full calibration/validation split; verify 98/98 comparable CSV outputs match byte-for-byte.
- [x] Run the complete repository unittest suite and verify the pre-existing protected-file hashes.
- [x] After explicit approval of the historical M8 Stage 2B matrix, run the frozen M9 final evaluation on seeds 2501–2506; preserve Stage 1 settings and keep validation separate.
- [x] Repeat the final evaluation independently, verify deterministic outputs, run the complete test suite, and check M0–M8 and prior M9 hashes.
- [x] Report pooled/per-profile false alarms, attack-event detection/delay, 1 s versus 5 s jumps, overlap, staged corroboration, coverage, limitations, hashes, and exact reproduction commands; stop after Stage 2.

### M8 Stage 1, Stage 2A, and Stage 2B progress
- [x] Implement the causal GPS-only M8 detector and preserve the M5 baseline.
- [x] Complete Stage 1 calibration, validation, and paired smoke testing; retain the 8.74% validation FPR (above the 5% target) and mixed M5/M8 findings as historical results.
- [x] Add isolated M8 normal-driving scenarios for turns, stop/restarts, varied speed, braking/acceleration, and seeded traffic; assign disjoint calibration/validation seeds and record input hashes.
- [x] Recalibrate from normal calibration trips only; select validation operating configuration against the predeclared 5% FPR target and evaluate M5/M8 on identical observations.
- [x] Run Stage 2A twice under distinct run IDs; compare deterministic outputs and verify protected M0–M7 files.
- [x] Add Stage 2A scenario tests; run M8-specific tests and the complete repository suite; update README and M8 methods documentation.
- [x] Freeze Stage 2A M8 thresholds/persistence and M5 thresholds; confirm reserved final seeds and configs remain unchanged.
- [x] Run the full final matrix on seeds 1301/1302 across normal profiles and multiple offset, jump, and drift magnitudes/durations; keep complete trips paired.
- [x] Report observation-level and event-level metrics, post-attack alerts, trip-paired comparisons, seed breakdowns, and confidence-interval limitations.
- [x] Repeat the full matrix under a distinct run ID; compare deterministic outputs and verify M0-M7, previous M8 reports, and frozen files remain unchanged.
- [x] Run all M8 tests and the complete repository suite; document final results and exact reproduction commands.
- [x] Stop after Stage 2B; do not start M9 or tune the detector against final-test results.

### M7 Stage 1 progress
- [x] Reconfirm nested M6 workspace, M5 online API, battery telemetry, and protected-file boundary.
- [x] Add isolated connected network, paired GPS-responsive controller, unchanged M5 calls, oracle-gated fallback, and telemetry runner.
- [x] Add M7 routing/controller tests and run the paired four-scenario smoke experiment twice.
- [x] Inspect outputs, run M7 tests and full suite, document the Stage 1 result and limitations.
- [x] Obtain approval before expanding beyond the Stage 1 smoke experiment.

### M7 Stage 2 progress
- [x] Preserve Stage 1 outputs and confirm M5/M0-M6 source/config/report boundaries before running.
- [x] Add a fixed calibration/validation/test seed plan and multiple attack magnitudes/durations without changing M5 thresholds.
- [x] Run the complete 52-trip matrix and an independent repeat under distinct new run IDs.
- [x] Validate pair completeness, route connectivity, arrivals, energy telemetry, active-attack detection, post-attack alerts, false positives, paired metrics, and reproducibility.
- [x] Run the complete repository test suite and document results and limitations.

## Local M0/M1 research dashboard
- [x] Add isolated read-only CSV discovery/loading, summary metrics, optional-field handling, interactive chart entry point, and refresh control.
- [x] Add tests for loading, file discovery, empty/malformed files, optional missing columns, metric correctness, and source CSV immutability.
- [x] Document separate dashboard dependencies, units, and the local launch command.
- [x] Verify Streamlit server startup and local URL with the installed dashboard dependencies.

## M0/M1 demonstration workflow
- [x] Add one documented command to run the existing simulation, summarize its new CSV, and save trajectory, speed, and available battery/SOC plots.
- [x] Add opt-in `--keep-open` for SUMO-GUI while preserving the default close-on-completion behavior.
- [x] Test summary calculations against a fresh simulation CSV, plot outputs, missing-battery behavior, no-overwrite protections, and GUI argument defaults.
- [ ] Visually verify the interactive GUI in a desktop session; this execution environment starts SUMO-GUI without a visible window handle.

## M0 acceptance
- [x] Inspect local OS, Python version, SUMO installation and available executables.
- [x] Create minimal reproducible SUMO network, EV type, route and configuration.
- [x] Create a Python TraCI runner with CLI arguments, deterministic seed and logging.
- [x] Add smoke test or clear manual verification command.
- [x] Document exact setup and run steps in README.

## M1 acceptance
- [x] Record time, position, speed, acceleration, heading, road, and route per active vehicle timestep.
- [x] Verify battery/energy values and document source, units, and SOC derivation.
- [x] Save the ground-truth trace to CSV and test types, monotonic timestamps, and deterministic reproducibility.
- [x] Keep the ground-truth trace separate from any future GPS observations.

## M2 acceptance
- [x] Generate seeded Gaussian GPS observations separately from ground truth.
- [x] Evaluate by `(time_s, vehicle_id)`, report horizontal errors and unmatched records, and plot results.
- [x] Test reproducibility, zero-noise behavior, schema separation, validation and preservation.

## M3 acceptance
- [x] Generate offset, jump and drift observations with separate attack-label sidecars.
- [x] Simulate and validate a separate physical alternative SUMO route with its own truth.
- [x] Evaluate scenarios separately and generate metrics/plots; preserve M0-M2 inputs.
- [x] Document that route deviation is not GPS-driven route choice or evidence of causal energy effects.

## M4 acceptance
- [x] Implement deterministic oracle-assisted position-residual threshold detector; no attack labels enter prediction.
- [x] Calibrate the fixed threshold from normal-only M2 data and evaluate on a held-out normal suffix plus each M3 attack.
- [x] Report confusion counts, precision, recall, F1, FPR, accuracy, unmatched records and attack detection delay.
- [x] Write per-observation predictions, per-scenario metrics, combined summary and requested visualizations to a new M4 run directory.
- [x] Add M4 tests, document oracle status/results/limitations, and run the complete test suite.

## M5 acceptance
- [x] Implement causal GPS-only temporal features and deterministic configurable thresholds calibrated on a chronological normal M2 prefix.
- [x] Evaluate held-out normal and M3 offset, jump, and drift separately; keep route deviation excluded and labels evaluation-only.
- [x] Write per-fix predictions, scenario metrics, comparison with M4, run metadata, confusion matrices, and time-series/PRF plots to a fresh run directory.
- [x] Add GPS-only feature, exclusion, threshold, reproducibility, metric, and no-leakage tests; run the full test suite.
- [x] Document M5 method, actual metrics, comparison, commands, and limitations.

## M6 acceptance
- [x] Inspect M0-M5 implementations, historical artifacts, configuration, and both existing route definitions before changing files.
- [x] Define a reproducible multi-seed, multi-route, multi-intensity/duration experiment matrix with trip-level calibration, validation, and final-test groups.
- [x] Validate both existing routes with SUMO; generate M6 simulations/GPS/attacks only under new M6 report paths.
- [x] Calibrate unchanged M4/M5 rules from normal calibration trips only; keep M4 oracle-assisted and M5 GPS-only at prediction time.
- [x] Record per-trip confusion counts, metrics, delays, unmatched/excluded records, metadata, aggregate means/standard deviations, and plots.
- [x] Add tests for matrix/splits/IDs, routes, intensity semantics, aggregation, reproducibility, no leakage, run-ID protection, and historical-output preservation.
- [x] Run smoke and full matrices twice for reproducibility; verify M0-M5 artifacts remain unchanged.
- [x] Document M6 protocol, actual results, commands, plots, and limitations; update README and this tracker.

## Work log
| Date | Milestone | Changes | Validation | Limitations |
| --- | --- | --- | --- | --- |
| 2026-11-12 | M9 Stage 2 | Added a separate approved 12-case historical M8 final matrix and isolated final evaluator; evaluated seeds 2501–2506 and documented pooled/per-profile results, overlap, jump durations, episodes, coverage, hashes, and limitations | Canonical `_03`/`_04` runs matched 242/242 CSVs; first `_01`/`_02` pair also matched; 222 attack/GPS/prediction CSVs matched across reporting correction; all 105 repository tests passed; protected M0–M8 baseline and all pre-existing M9 report hashes unchanged | Six trips/two per profile are descriptive only; M8/OR/corroborated staged pooled normal FPR exceeded 5%; corroboration is not confirmation; no M10/tuning started |
| 2026-11-11 | M9 Stage 1 | Added isolated keyed M5/M8 error analysis and OR/AND/staged fusion; added new disjoint seed config, validation metrics, overlap/persistence reports, tests, and methods documentation | 14 M9 tests and 99 repository tests passed; full 6+6 calibration/validation split repeated with 98/98 CSV outputs matching; all pre-existing project hashes unchanged except intentional M9 TASKS update | Validation uses six trips and a synthetic SUMO map; staged fast alerts equal M5 and corroboration does not establish spoofing; final seeds 2501–2506 remain unopened |
| 2026-11-09 | M8 Stage 2B | Ran the frozen M5/M8 paired final matrix across 2 reserved seeds, 3 normal-driving profiles, and 12 attack intensity/duration cases; added event/observation summaries and paired seed statistics | `_final_01` and `_final_02` matched 242/242 CSV/JSON/PNG files; 23 M8 tests and all 85 repository tests passed; protected M0-M7, prior M8 reports, and frozen code/config hashes verified | Pooled M8 normal FPR met 5% at 4.81% but exceeded it for two profiles and was above M5's 2.50%; M8 active event detection was lower for offset, jump, and drift; only 2 independent seeds |
| 2026-11-09 | M8 Stage 2A | Added an isolated SUMO loop network with three normal-driving profiles, six calibration and six validation trips, normal-only threshold fitting, validation persistence selection, and paired M5/M8 evaluation; updated M8 docs and README | `m8_stage2a_repro_04` and `_05` matched 89/89 CSV/JSON/PNG outputs; 19 M8 tests and all 81 repository tests passed; Stage 2A protected manifest stayed identical with zero changed paths | Selected M8 normal FPR 4.23% met the 5% target, but exceeded M5's 3.43%; M8 reduced alarm episodes but attack results were mixed. Full final-test matrix not run; await approval |
| 2026-11-07 | M7 Stage 2 | Added fixed split seed matrix, offset/jump/drift intensity-duration grid, paired summaries, active versus post-attack detection accounting, and isolated M7 report outputs | Two 52-trip runs completed; 24 pairs and 219 deterministic artifacts matched; 1,848 protected pre-existing files retained identical hashes; `python -m unittest discover -s tests -v` passed all 62 tests | Only two final-test seeds and one simple network; M5 alerts were all post-attack, fallback did not improve paired outcomes |
| 2026-11-03 | M0 | Added one-edge 1,000 m SUMO road, fixed-seed config, Python/TraCI runner and EV route | SUMO 1.28.0 completed ev_001 in 80 steps; integration smoke test passed | pytest absent (unittest used); Git metadata absent |
| 2026-11-04 | M1 | Enabled battery device and explicit 25,000 Wh initial charge; added per-step truth CSV, per-run metadata/config snapshots, and schema/type/spacing/reproducibility integration test; made GUI mode auto-start | Simulation completed 80 steps and wrote 79 active-state rows; unittest passed; timestamped CSV inspected | SUMO removes vehicle at arrival before TraCI can read its arrival-step state; automated session has no visible GUI window |
| 2026-11-04 | M0/M1 demo | Added one-command demo runner, CSV-backed summary, three CSV-stem-named plots, opt-in GUI keep-open flag, and overwrite protection | Headless demo produced summary and 3 PNGs; 5 unittest cases passed, including independent recomputation from CSV rows | Visible GUI cannot be inspected in this automation desktop; `--gui --keep-open` command is documented for interactive PowerShell |
| 2026-11-04 | M0/M1 dashboard | Added separate Streamlit/Plotly read-only dashboard and optional dashboard requirements | Dashboard tests passed; Streamlit AppTest rendered with no exceptions; local HTTP startup returned 200; full suite passed | None observed; dashboard dependency install is separate from simulation requirements |

| 2026-11-06 | M2-M4 | Confirmed existing M2/M3 inputs, added an oracle-assisted residual-threshold evaluator calibrated only on the M2 normal prefix, and wrote separate M4 prediction/metric/plot outputs | Final M4 runs produced byte-identical predictions, metrics, summaries and plots; 123 protected M0-M3 input/output files retained identical hashes; existing run ID was refused without changes; full suite passed all 36 tests | Single-trip data only; residual uses privileged truth and is not deployable. M5 not started |
| 2026-11-06 | M5 | Added a GPS-only temporal speed/heading threshold detector; calibrates on normal M2 prefix and evaluates held-out normal plus M3 offset/jump/drift; added separate M5 predictions, metrics, M4 comparison, plots and method docs | `m5_final_01` and `m5_final_02` matched byte-for-byte across 15 non-metadata outputs; `python -m unittest discover -s tests -v` passed all 40 tests | Single 79-row trip, one attack intensity, short calibration/holdout; modest drift and offset recall; thresholds require broader trip/route validation |
| 2026-11-06 | M6 | Added an isolated multi-seed/multi-route M4/M5 evaluation campaign, pooled normal-only thresholds, 2×2 intensity/duration grids for offset/jump/drift, trip-level summaries, and seven plots | Smoke run completed 4 test scenarios; full run completed 52 test scenarios/104 detector evaluations; `m6_full_02` and `_03` matched across 236 CSV/JSON/PNG files; 278 protected M0-M5 files retained hash `807fd0db79814e8d327f0325023226626000b46c9782ca3071c14061682a28c2`; full suite passed all 48 tests | Two test seeds and two separate network/route definitions; routes are not held out from calibration, so route result is comparative variability rather than leave-one-route-out generalization; M4 is oracle-assisted, M5 remains weak on offset/drift |

## M0 verification (2026-11-03)
- Environment: Windows; Python 3.14.6; SUMO, sumo-gui, netgenerate, and netconvert 1.28.0; TraCI 1.28.0; PyYAML 6.0.3. SUMO_HOME resolves to `C:\Program Files (x86)\SUMO`.
- `python src/simulation/run_sumo.py --config config/experiment_config.yaml` passed; logged `Completed EV run: vehicle=ev_001 timesteps=80 seed=42`.
- `python -m unittest discover -s tests -v` passed; 1 integration smoke test ran and the EV trip completed.
- pytest is not installed; tests use built-in unittest. This workspace copy has no .git repository, so Git status/diff evidence is unavailable.

## M1 verification (2026-11-04)
- Reviewed [SUMO Electric model](https://sumo.dlr.de/docs/Models/Electric.html) for battery output fields/units and [TraCI Vehicle Value Retrieval](https://sumo.dlr.de/docs/TraCI/Vehicle_Value_Retrieval.html) for the Wh/s electricity getter and device parameters.
- Runtime probe with SUMO/TraCI 1.28.0 showed M0 battery parameters did not instantiate a battery device. Added `has.battery.device=true` and explicit `device.battery.chargeLevel=25000` Wh. Re-probe returned 50,000 Wh capacity, charge level, per-step energy, cumulative consumed/regenerated energy, and electricity consumption. SOC is charge divided by capacity.
- `python src/simulation/run_sumo.py --config config/experiment_config.yaml` passed: 80 simulation steps, 79 queryable active-state CSV rows. Final inspected file: `data/raw/truth_ev_001_20261104T063621.926817Z.csv`; values inspected, times 1 to 79 seconds at 1-second spacing. Per-run config and metadata snapshots were created beside it.
- `python -m unittest discover -s tests -v` passed: 1 integration test checks exact columns, finite numeric values, battery values, SOC bounds, 1-second monotonic timestamps, and identical rows across repeated fixed-seed runs.
- Limitation: SUMO removes arrived vehicles before TraCI vehicle getters return the arrival-step state. The CSV intentionally contains active states only and does not invent an arrival-step sample. CSVs are under ignored `data/raw/`.
- GUI mode was updated to pass SUMO-GUI's `--start` flag and 150 ms display delay. A GUI run was attempted, but the automated environment supplied no visible window and the TraCI process did not finish; it was stopped. Run the documented `--gui` command from the user's interactive PowerShell session to view the simulation. Headless simulation and smoke test both pass.

### M1 verification refresh (2026-11-04)
- Rechecked the official SUMO 1.28.0 Electric model and TraCI vehicle retrieval documentation before running; battery/energy fields are read from the configured battery device, and SOC is derived only from reported charge/capacity.
- `python src/simulation/run_sumo.py --config config/experiment_config.yaml` passed with seed 42: 80 simulation steps and 79 active, queryable samples. New output: `data/raw/truth_ev_001_20261104T073118.622118Z.csv` with adjacent config and metadata snapshots. Historical CSVs were not modified.
- Inspected the generated CSV: 79 records at 1-second intervals from 1 to 79 s; speed min/mean/max 12.180/12.724/13.172 m/s; sampled X/Y distance 992.036 m; charge 25,000.00 to 24,920.76 Wh; capacity 50,000 Wh; cumulative consumed/regenerated energy 131.17/51.93 Wh; SOC 50.000% to 49.842%.
- `python -m unittest discover -s tests -v` passed all 5 tests, including exact CSV schema/types, timestep spacing, fixed-seed reproducibility, and demo summary/plot checks.
- The arrival-step state is unavailable because SUMO removes the vehicle before TraCI getters can query it; telemetry therefore covers each active/queryable simulation step and contains no fabricated arrival sample. GPS observations/spoofing, sensor fusion, and ML remain unimplemented.

## M0/M1 demo verification (2026-11-04)
- `python src/simulation/demo_m0_m1.py --help` passed and shows the GUI, keep-open, CSV output, and figures-directory options.
- `python -m unittest discover -s tests -v` passed: 5 tests, covering M1 reproducibility/schema and demo summaries, PNG outputs, missing optional battery fields, no-overwrite behavior, and keep-open argument behavior.
- `python src/simulation/demo_m0_m1.py` passed headlessly. CSV: `data/raw/truth_ev_001_20261104T071429.981247Z.csv`; 79 rows, sampled 1.0 to 79.0 s. Summary from the CSV: sampled duration 78.0 s; speed min/mean/max 12.180/12.724/13.172 m/s; sampled X/Y distance 992.036 m; battery charge 25,000.00 to 24,920.76 Wh (50,000 Wh capacity); SUMO cumulative consumed/regenerated 131.17/51.93 Wh; SOC 50.00% to 49.84%. Tests independently recomputed these summary calculations from the CSV.
- Generated three non-overwriting plots under `results/figures/m0_m1/`: trajectory X/Y, speed/time, and battery charge/SOC/time. Existing CSV, metadata, config snapshots, and plot paths are protected against overwrite.
- Matplotlib 3.11.2 was already installed; no new dependency was installed. A visible GUI launch was attempted, but this environment returned zero main-window handles for both Python and SUMO-GUI. The processes were stopped. M0/M1 GUI use is documented for an interactive desktop; no new research milestone was started.

## Local dashboard verification (2026-11-04)
- Dashboard dependencies are isolated in `requirements-dashboard.txt`; environment verified Streamlit 1.66.1, Plotly 6.9.0, and pandas 3.0.6. SUMO/simulation requirements were not changed.
- `python -m unittest tests.test_dashboard -v` passed dashboard CSV discovery/loading, empty/malformed inputs, missing optional values, correct metric calculations, chronological initial/final calculations, and source-file immutability checks.
- `python -m streamlit run src/dashboard/app.py --server.headless true --server.port 8765` was launched as a local startup smoke check and returned HTTP 200 at `http://127.0.0.1:8765`; Streamlit AppTest rendered the full page and reported no app exceptions. The smoke-test server was then stopped.
- `python -m unittest discover -s tests -v` passed all 10 existing and dashboard tests. The dashboard only reads `data/raw/*.csv`; existing simulation and telemetry generation code was not changed, and M2 remains unstarted.

## Rules
Move only to the next incomplete milestone. Keep this file current after every agent session and mark anything not tested as unverified.
