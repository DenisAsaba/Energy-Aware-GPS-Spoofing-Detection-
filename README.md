# EV GPS Spoofing Detection and Energy-Aware Routing

A staged, reproducible, simulation-only research project using Python, SUMO and TraCI.

## M0: run the first EV simulation

M0 established a local 1,000 m, one-edge SUMO road and one passenger EV. SUMO road coordinates are metric x/y; there is no conversion to geographic longitude/latitude. The simulation step is 1 second, the random seed is 42, and the configured simulation end is 600 seconds. M1 now records vehicle ground truth and available battery values as described below. No GPS measurements or spoofing are implemented.

Install Eclipse SUMO (including `sumo`, `sumo-gui`, `netgenerate`, and `netconvert`) and Python. The runner uses TraCI and PyYAML. With the SUMO installer as used on Windows, set and verify the paths in PowerShell:

```powershell
$env:SUMO_HOME = 'C:\Program Files (x86)\SUMO'
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

## Research stages

Read `AGENTS.md`, `docs/PROJECT_SPEC.md`, `docs/IMPLEMENTATION_PLAN.md`, and `TASKS.md` before extending the staged system. The first objective is a runnable EV in SUMO; GPS noise and attacks are later milestones.

## Planned repository directories
`config/`, `sumo/network/`, `sumo/routes/`, `sumo/vehicles/`, `sumo/simulation/`, `src/simulation/`, `src/sensors/`, `src/attacks/`, `src/fusion/`, `src/mapping/`, `src/features/`, `src/detection/`, `src/routing/`, `src/energy/`, `tests/`, `data/raw/`, `data/processed/`, `data/attacks/`, `experiments/`, `results/figures/`, `results/tables/`, `results/metrics/`, `paper/`.

## Dependencies
The demo was run with Python 3.14.6, SUMO 1.28.0, TraCI 1.28.0, PyYAML 6.0.3, and Matplotlib 3.11.2 on Windows. Tests use `unittest`; `pytest` is optional and was not installed in the verified environment. Pandas and scikit-learn are not needed. Battery energy comes from the SUMO `Energy/unknown` EV model and battery device, not a physical vehicle.

## Status
M0 and M1 complete: Python/TraCI runs the EV and writes reproducible per-step ground-truth telemetry to CSV. See `TASKS.md` for evidence. No GPS sensing, spoofing, sensor fusion, or machine learning has been implemented.
