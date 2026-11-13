# EV GPS Spoofing Detection and Energy-Aware Routing

A completed M0-M9 simulation-only research project using Python, SUMO and TraCI. Committed results are inspectable, but the checkpoint is not a self-contained reproduction package.

## Reproducibility status

The documentation audit of commit `3f6439c004dc144dd7b1580cae76d2cf5a40220e` distinguishes committed evidence from historical reproduction. Source code, configurations, methods, and substantial result tables, predictions, and figures are tracked. Additional M4/M5 input CSVs, historical preservation prerequisites, and unique external M3 verification evidence are not included in a clean clone. The M9 frozen baseline has 509 unresolved M8 raw-byte checksum discrepancies; these are not demonstrated changes to numerical findings. Windows newline conversion also affects raw-byte hashes.

Read [Reproducibility limitations and evidence inspection](docs/REPRODUCIBILITY_LIMITATIONS.md) before using any execution commands below. They are workflow examples, not a guarantee of clean-clone reproduction; tests can also generate artifacts. M9 final evaluation currently fails its preservation prerequisite. Do not bypass the checks or reuse historical output IDs.

Canonical corrected M9 results are `reports/m9/m9_stage2_final_03/` and `reports/m9/m9_stage2_final_04/`, as documented in [M9 methods](docs/M9_DETECTOR_ERROR_ANALYSIS.md). Earlier `_01/_02` runs remain audit history. Inspect [the final evidence inventory](reports/final_project/final_evidence_inventory.md) for milestone-specific evidence and limitations. No numerical result is revised by this documentation correction.

## M7 Stage 1: GPS-responsive route smoke experiment

M7 Stage 1 adds an isolated connected two-route network, an online GPS-driven routing controller, unchanged M5 temporal detector calls, and an explicitly oracle-assisted fallback after an M5 alert. Its paired smoke command and trust-boundary, method, result, and limitation notes are in [docs/M7_GPS_AWARE_ENERGY_ROUTING.md](docs/M7_GPS_AWARE_ENERGY_ROUTING.md). Run `python -m src.experiments.m7_energy_routing --config config/m7_energy_routing.yaml --run-id stage1_smoke_01` from the project root. Each run ID writes only to a new folder below `reports/m7/stage1_smoke/`.

M7 Stage 2 runs the configured paired seed/intensity/duration matrix with frozen M5 thresholds. The historical independent runs are `reports/m7/full_matrix/m7_full_02/` and `reports/m7/full_matrix/m7_full_03/`. A future execution must satisfy the documented prerequisites and use a new, unused run ID with `python -m src.experiments.m7_matrix --config config/m7_energy_routing.yaml --run-id <new-unused-id>`. Outputs are isolated under `reports/m7/full_matrix/`; the full protocol, measured results, and limits are documented in the M7 report.

## M0: run the first EV simulation

M0 established a local 1,000 m, one-edge SUMO road and one passenger EV. SUMO road coordinates are metric x/y; there is no conversion to geographic longitude/latitude. The simulation step is 1 second, the random seed is 42, and the configured simulation end is 600 seconds. M1 records vehicle ground truth and available battery values as described below; M2/M3 GPS data and M4 offline evaluation are documented in their milestone sections and docs.

Install Eclipse SUMO (including `sumo`, `sumo-gui`, `netgenerate`, and `netconvert`) and Python. The runner uses TraCI and PyYAML. With the SUMO installer as used on Windows, set and verify the paths in PowerShell:

```powershell
$env:SUMO_HOME = '<SUMO installation directory>' # Replace with your installation location.
$env:Path = "$env:SUMO_HOME\bin;$env:Path"
sumo --version
netgenerate --version
python --version
python -c "import traci, yaml; print('TraCI', traci.__version__, 'PyYAML', yaml.__version__)"
```

If TraCI or PyYAML is unavailable to the selected Python, install them with `python -m pip install traci PyYAML`. The installed SUMO distribution also supplies TraCI under `$env:SUMO_HOME\tools`.

From the repository root, run headless or with the graphical SUMO frontend:

```powershell
python src/simulation/run_sumo.py --config config/experiment_config.yaml
python src/simulation/run_sumo.py --config config/experiment_config.yaml --gui
```

GUI mode starts SUMO automatically and uses a 150 ms display delay per step so the run is visible. See the SUMO [TraCI startup guidance](https://sumo.dlr.de/docs/TraCI/) for the GUI `--start` requirement.

The runner logs the seed, vehicle ID, completed simulation steps, telemetry rows, and CSV path. It writes a timestamped ground-truth CSV under `data/raw/` plus per-run `<csv-stem>_config.yaml` and `<csv-stem>_metadata.yaml` files. Rebuild the checked-in network from its node and edge sources with:

```powershell
netconvert --node-files sumo/network/m0.nod.xml --edge-files sumo/network/m0.edg.xml --output-file sumo/network/m0.net.xml
```

Run the integration smoke test with Python's standard library (no test package install is needed):

```powershell
python -m unittest discover -s tests -v
```

`python -m pytest` is also supported after `python -m pip install pytest`.

## M1: vehicle telemetry

The M1 runner records `time_s`, `vehicle_id`, metric `x_m`/`y_m`, `speed_mps`, `acceleration_mps2`, SUMO navigational `heading_deg` (0 degrees north, clockwise), `road_id`, `route_id`, `electricity_wh`, `energy_consumed_wh`, `energy_total_consumed_wh`, `energy_total_regenerated_wh`, `battery_charge_wh`, `battery_capacity_wh`, and `soc`. `electricity_wh` integrates TraCI's Wh/s rate over the configured one-second step; regenerative values can be negative. SOC is calculated from SUMO-reported battery charge divided by capacity. The exact configuration and seed are copied beside each run's CSV.

The CSV contains rows for each timestep while the EV is active and queryable through TraCI. In the current 80-step trip, SUMO removes the vehicle on arrival at step 80 before vehicle getters can retrieve its final state; the verified CSV therefore contains 79 active-state rows at times 1 to 79 seconds. The runner does not synthesize an arrival row. M1 stores simulation ground truth only; no GPS observation or attack fields are mixed into it.

SUMO's official [electric-vehicle model documentation](https://sumo.dlr.de/docs/Models/Electric.html) documents battery-output energy fields and Wh units, and its [TraCI vehicle retrieval reference](https://sumo.dlr.de/docs/TraCI/Vehicle_Value_Retrieval.html) documents electricity consumption in Wh/s and supported battery parameters. Installed SUMO 1.28.0 was probed directly: battery charge, capacity, per-step consumption, cumulative consumption/regeneration, electricity, position, acceleration, heading, edge, and route getters returned values after enabling `has.battery.device`.

Latest M1 verification (2026-11-04): `python src/simulation/run_sumo.py --config config/experiment_config.yaml` completed 80 simulation steps and wrote [the timestamped truth CSV](data/raw/truth_ev_001_20261104T073118.622118Z.csv) with 79 active-state samples, plus its config and metadata snapshots. The inspected CSV spans 1–79 s at 1-second intervals; speed min/mean/max is 12.180/12.724/13.172 m/s, sampled X/Y distance is 992.036 m, battery charge is 25,000.00–24,920.76 Wh (50,000 Wh capacity), cumulative consumed/regenerated energy is 131.17/51.93 Wh, and SOC is 50.000%–49.842%. `python -m unittest discover -s tests -v` passed all 5 tests. SUMO removes the EV before TraCI exposes an arrival-step sample, so the final active-state timestep is not synthesized.

## Demonstrate M0 and M1

From the repository root, run this single command to watch the EV, leave SUMO-GUI open at the completed route, and then print the telemetry summary and write plots after you close the GUI:

```powershell
python src/simulation/demo_m0_m1.py --gui --keep-open
```

`--keep-open` is opt-in and requires `--gui`; ordinary `run_sumo.py` runs retain their existing close-on-completion behavior. The demo writes a new timestamped CSV and per-run YAML snapshots under `data/raw/`, and uniquely named PNGs under `results/figures/m0_m1/`. It does not overwrite historical CSVs or earlier plots. The summary reports row count, sampled duration, speed min/mean/max, sampled X/Y path distance, and battery charge, SUMO cumulative energy, and SOC only when those fields are present in the CSV. Distance and duration cover the sampled active-vehicle rows; SUMO removes the vehicle at arrival before TraCI can provide a final arrival-step row.

The plots use the installed Matplotlib dependency (verified version 3.11.2); no dashboard or data-frame package is needed. The workflow produces an X/Y trajectory, speed/time plot, and battery charge/SOC plot when those values are available.

## Local M0/M1 research dashboard

An optional, separate Streamlit dashboard inspects existing files under `data/raw/`. It is read-only: it does not call SUMO or change telemetry CSVs. Install its dependencies separately from the simulation environment requirements:

```powershell
python -m pip install -r requirements-dashboard.txt
```

Start it from the repository root:

```powershell
python -m streamlit run src/dashboard/app.py
```

Streamlit prints its local URL (normally `http://localhost:8501`). Use **Refresh file list** in the sidebar after a new simulation run, then choose a CSV. The dashboard displays record count, sampled duration, speed range/mean, initial/final battery charge and SOC, separate cumulative consumed and regenerated energy, and interactive trajectory, speed, acceleration, SOC, charge, and energy charts where their source columns are present. The raw table is shown below. Missing optional fields remain unavailable; malformed and empty files produce an error message. Time is seconds, X/Y positions meters in SUMO road coordinates, speed m/s, acceleration m/s², heading degrees, energy/charge Wh, and SOC a fraction. The reported duration is the observed time span, not the total SUMO run duration; no road distance is inferred from coordinate displacement.

Dashboard tests (which do not require Streamlit) run with the existing test command `python -m unittest discover -s tests -v`.
In the verified Python 3.14.6 environment, dashboard versions were Streamlit 1.66.1, Plotly 6.9.0, and pandas 3.0.6; Streamlit AppTest rendered the page without app exceptions and the local server smoke check returned HTTP 200.

## Research stages

Read `AGENTS.md`, `docs/PROJECT_SPEC.md`, `docs/IMPLEMENTATION_PLAN.md`, and `TASKS.md` before extending the staged system. M0-M9 are complete for their documented research scope, through M9 Stage 2 final held-out evaluation. The original implementation plan is a proposal roadmap; `TASKS.md` and milestone methods record actual completed work. Stop before M10 or further detector tuning.

## Planned repository directories
`config/`, `sumo/network/`, `sumo/routes/`, `sumo/vehicles/`, `sumo/simulation/`, `src/simulation/`, `src/sensors/`, `src/attacks/`, `src/fusion/`, `src/mapping/`, `src/features/`, `src/detection/`, `src/routing/`, `src/energy/`, `tests/`, `data/raw/`, `data/processed/`, `data/attacks/`, `experiments/`, `results/figures/`, `results/tables/`, `results/metrics/`, `paper/`.

## Dependencies
The demo was run with Python 3.14.6, SUMO 1.28.0, TraCI 1.28.0, PyYAML 6.0.3, and Matplotlib 3.11.2 on Windows. Tests use `unittest`; `pytest` is optional and was not installed in the verified environment. Pandas and scikit-learn are not needed. Battery energy comes from the SUMO `Energy/unknown` EV model and battery device, not a physical vehicle.

## Status
M0-M9 are complete for the documented simulation research scope. M4 is oracle-assisted because it uses ground truth to calculate GPS residuals. M5 and M8 are GPS-only motion anomaly detectors; M9 combines detector outputs, not independent sensors. M7 implements GPS-responsive routing and an oracle-assisted SUMO-state fallback, with executed-route and battery telemetry. Its final paired matrix found zero successful mitigations and zero protected-versus-unprotected outcome improvements; it does not establish real-world energy savings. See `TASKS.md`, the milestone method documents, and the reproducibility limitations above.

## M4: GPS spoofing detection

M4 applies an explainable position-residual threshold to the M2 normal baseline
and the M3 offset, jump, and drift scenarios. It calibrates a fixed threshold
from the configured quantile of normal-only M2 residuals, reserves the
chronological M2 suffix for false-alarm evaluation, and evaluates each attack
separately. Predictions are generated before labels are loaded for offline
scoring; prediction CSVs do not include labels. Route deviation remains a
separate physical-route scenario and is excluded. This baseline uses
ground-truth coordinates, so document it as oracle-assisted and not deployable.
See [M4 methods, definitions, results and limitations](docs/M4_GPS_DETECTION.md).

Run M4 using a new output folder name; existing experiment outputs are never
overwritten:

```powershell
python -m src.detection.gps_spoofing --config config/experiment_config.yaml --run-id m4_run_01
python -m unittest discover -s tests -v
```

The workflow writes prediction CSVs, per-scenario metrics, a combined summary,
confusion matrices, attack-score comparison, and residual/label/prediction
time series under `reports/m4/m4_run_01/`.

## M5: GPS-only temporal detection

M5 estimates speed, heading, speed changes, and heading changes from each
vehicle's current and previous GPS positions. Independent upper quantiles are
calibrated from the chronological first half of normal M2 GPS; a held-out
normal suffix and each M3 offset, jump, and drift dataset are evaluated
separately. Labels are read only after predictions for offline evaluation.
Route deviation is excluded. See
[M5 method, results and limitations](docs/M5_GPS_ONLY_DETECTION.md).

Run with a fresh output ID:

```powershell
python -m src.detection.gps_only --config config/experiment_config.yaml --run-id m5_run_01
python -m unittest discover -s tests -v
```

The verified `m5_final_01` run uses 99th-percentile thresholds of 23.4725 m/s
GPS speed, 14.7584 m/s speed change, and 69.8849 degrees heading change.
Offset, jump, and drift F1 were 0.308, 0.571, and 0.216 respectively. M5 is a
single-trip research baseline, not a certified production safety detector.

## M6: robustness and generalization evaluation

M6 runs the original M4 oracle-assisted residual rule and M5 GPS-only temporal
rule across multiple SUMO seeds, both existing route definitions, and
configurable offset, jump, and drift intensities/durations. Thresholds are
calibrated from distinct normal training trips only. The campaign writes a
per-trip experiment matrix and metrics, aggregate summaries, predictions,
configuration/seed metadata, and comparison plots to a new
`reports/m6/<run-id>/` directory. Existing run IDs are protected. Generated M6
outputs are ignored by default, but selected historical M6 runs, including
`m6_full_02` and `m6_full_03`, are already tracked. Ignored local artifacts
also form part of the historical preservation prerequisites.

Run a reduced smoke campaign first, then use a different fresh ID for the full
matrix:

```powershell
python -m src.experiments.m6_robustness --config config/m6_robustness.yaml --run-id m6_smoke_repro_01 --smoke
python -m src.experiments.m6_robustness --config config/m6_robustness.yaml --run-id m6_full_repro_01
python -m unittest discover -s tests -v
```

The verified `m6_full_02` run contains 52 held-out test configurations and
104 detector evaluations. Both SUMO routes passed validation. Across the
16-trip attack-class groups, M4 F1 was 0.894 for offset, 0.592 for jump, and
0.533 for drift; M5 F1 was 0.080, 0.355, and 0.000. M5's weak offset/drift
transfer remains visible in the intensity analysis. A second full run
reproduced all compared CSV, JSON, and PNG outputs exactly. See
[M6 design, results, plots, and limitations](docs/M6_ROBUSTNESS_EVALUATION.md).

## M8: improved GPS-only spoofing detection

M8 adds causal GPS motion features and alarm persistence while keeping M5's
detector implementation unchanged. Stage 1 is complete: its historical
validation FPR was **8.74%**, above the predeclared 5% target. The mixed smoke
results showed fewer M8 normal alarms and better offset/jump F1, but M8 missed
drift detected by M5. No overall detector improvement has been established.

Stage 2A added an isolated M8-only SUMO grid with turn, stop/restart,
brake/acceleration, speed, and traffic variation. Six complete normal trips
were used for calibration and six disjoint trips for validation. The selected
2-of-5 policy met the validation normal FPR target at 4.23%; M8 had a higher
normal observation FPR than M5 (4.23% vs 3.43%) but fewer alarm episodes per
normal trip (0.50 vs 2.50). Attack results were mixed: offset event detection
fell from 6/6 for M5 to 5/6 for M8, jump detection tied at 6/6, and drift
detection fell from 3/6 to 2/6. M8's validation F1 was higher for all three
attack types, but this does not establish overall improvement or
production readiness.

Stage 2B completed the frozen held-out matrix using reserved seeds 1301 and
1302 across all three normal profiles and 72 attack datasets. M8's pooled
normal FPR was 4.81%, meeting 5%, but it exceeded 5% on turns/light (6.98%)
and brake/accel (7.78%) and was higher than M5 overall (2.50%). M8 detected
fewer active events than M5 for offset (22/24 vs 24/24), jump (12/24 vs
24/24), and drift (7/24 vs 15/24). It did not improve overall performance.
Full results, paired seed statistics, limitations, and reproduction details
are in [M8 methods and results](docs/M8_IMPROVED_GPS_DETECTION.md).

Reproduce Stage 2A twice with fresh IDs, compare deterministic outputs, and
then run the M8-specific and full test suites:

```powershell
python -m src.experiments.m8_stage2a --config config/m8_stage2a.yaml --run-id m8_stage2a_repro_04
python -m src.experiments.m8_stage2a --config config/m8_stage2a.yaml --run-id m8_stage2a_repro_05
python -c "from pathlib import Path; from src.experiments.m8_evaluation import compare_runs; print(compare_runs(Path('reports/m8/stage2a/m8_stage2a_repro_04'), Path('reports/m8/stage2a/m8_stage2a_repro_05')))"
python -m unittest tests.test_m8_detector tests.test_m8_evaluation tests.test_m8_stage2a -v
python -m unittest discover -s tests -v
```

Both Stage 2A repeat runs matched across 89 CSV, JSON, and PNG files. Stage 2B
repeat runs also matched across 242 CSV, JSON, and PNG files. The M8 tests
passed 23 cases and the complete repository suite passed 85 tests. Reproduce
the final held-out evaluation with fresh run IDs:

```powershell
python -m src.experiments.m8_stage2b --config config/m8_stage2b.yaml --run-id m8_stage2b_final_01
python -m src.experiments.m8_stage2b --config config/m8_stage2b.yaml --run-id m8_stage2b_final_02
python -c "from pathlib import Path; from src.experiments.m8_evaluation import compare_runs; print(compare_runs(Path('reports/m8/stage2b/m8_stage2b_final_01'), Path('reports/m8/stage2b/m8_stage2b_final_02')))"
python -m unittest tests.test_m8_detector tests.test_m8_evaluation tests.test_m8_stage2a tests.test_m8_stage2b -v
python -m unittest discover -s tests -v
```

Final outputs are under `reports/m8/stage2b/m8_stage2b_final_01/` and
`reports/m8/stage2b/m8_stage2b_final_02/`. No detector changes or later
milestone work were started.
