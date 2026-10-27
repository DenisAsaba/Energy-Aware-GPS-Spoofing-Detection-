# EV GPS spoofing detection and energy-aware routing

A staged, reproducible, simulation-only research project using Python, SUMO and TraCI. M0/M1 run one SUMO EV and save per-step telemetry. M2 generates seeded normal GPS observations. M3 now adds configurable offset, jump, drift, and a genuine alternate-route scenario, with separate observation/label files and offline evaluation outputs. Sensor fusion, machine learning, and eco-routing are not implemented.

## Environment and setup

SUMO (including `sumo` on `PATH`), Python, TraCI, sumolib, PyYAML and Matplotlib are required. Install Python dependencies from this directory:

```powershell
python -m pip install -r requirements.txt
```

SUMO is a separate system dependency; add its `bin` directory to `PATH` or set `SUMO_HOME`. The project's configured network, route and simulation files are under `sumo/`; experiment defaults are in `config/experiment_config.yaml`.

## Reproduce M0–M2

Run the EV simulation and export ground truth, then generate normal GPS data, plots and error summary:

```powershell
python src/simulation/run_sumo.py
python src/sensors/gps_normal.py
```

The simulation writes `data/raw/truth.csv`. M2 reads it without modifying it and writes `data/processed/gps_normal.csv`, `results/figures/ev_trajectory_gps_normal.png`, `results/figures/gps_normal_error_distribution.png` and `results/tables/gps_normal_error_summary.json`. Reproduce the tests with:

```powershell
python -m unittest discover -s tests -v
```

The active checkout's full suite passed all 9 tests after M2, including the M0/M1 trip and telemetry tests plus the new GPS reproducibility, noise, schema, and truth-preservation tests.

GPS seed, noise model, per-axis standard deviation, input/output and figure paths are configured under `gps` in the YAML. Override key parameters from the command line, for example:

```powershell
python src/sensors/gps_normal.py --seed 456 --sigma-m 5
```

`--input`, `--output` and `--config` are also supported. GPS noise uses its own seed, independently of SUMO's seed. The generator refuses to write GPS output over the truth input.

## Data and noise model

Ground-truth and GPS coordinates use SUMO's local Cartesian road-network x/y frame in meters; they are not geographic longitude/latitude. The existing truth CSV contains time (simulation seconds), trip and vehicle IDs, simulation seed, x/y (meters), speed (m/s), acceleration (m/s²), heading (degrees), road and route IDs, and available SUMO battery/energy measurements. `soc` is derived as battery charge divided by capacity (fraction 0–1); energy fields retain the names and sign conventions in the telemetry CSV.

For each time step, the GPS model independently samples x and y errors from zero-mean normal distributions with standard deviation 3 m (`gps.position_std_m`). Thus radial position error is Rayleigh distributed under this model. The default GPS seed is 123, separate from the SUMO seed (42). This stationary independent-axis model is a reproducible baseline, not a validated receiver model or a claim of realistic GPS accuracy. It omits temporal correlation, multipath, urban blockage, changing signal quality, and device-specific behavior.

The GPS CSV includes time/trip/vehicle identifiers, GPS seed, model name, configured standard deviation, and measured `gps_x_m`/`gps_y_m`; it excludes ground-truth coordinates, error values, and attack labels. The simulator reads truth to create synthetic GPS observations; evaluation also compares observations to truth. Neither truth nor post-hoc error is an operational detector input.

In the checked 83-observation run with GPS seed 123 and sigma 3 m, radial-error mean was 3.370 m, median 3.024 m, standard deviation 1.927 m, nearest-rank 95th percentile 6.601 m, and maximum 8.719 m. These are results from this synthetic model and run, not empirical receiver performance claims.

## M0/M1 commands and output

The simulation can be rerun with a chosen SUMO seed or alternate truth output:

```powershell
python src/simulation/run_sumo.py --seed 123 --output data/raw/truth_seed_123.csv
```

The original M1 trajectory-only figure can be regenerated with:

```powershell
python src/simulation/plot_trajectory.py
```

Telemetry samples are recorded after each simulation step while the EV is present. The default run completes in 84 SUMO steps and records 83 positions at 1–83 seconds because the vehicle leaves the active network on its arrival step. Battery values may be blank if unavailable from another SUMO configuration.

## M3: controlled attack scenarios

Generate the configured coordinate attacks from the existing M2 normal GPS baseline:

```powershell
python src/attacks/gps_spoofing.py --attack all
```

Use `--attack offset`, `--attack jump`, or `--attack drift` to generate one scenario. Parameters live under `attacks.scenarios` in `config/experiment_config.yaml`. Angles are measured counterclockwise from SUMO +x: 0° is +x/east and 90° is +y/north. All intervals are half-open: an attack is active when `onset_time_s <= time_s < onset_time_s + duration_s`. The onset sample is included. Offset and jump apply a constant vector for the interval and return directly to normal GPS at its end. Drift displacement is `drift_rate_mps * (time_s - onset_time_s)` along its configured direction, starts at zero on the onset sample, and returns directly to normal at interval end. Finite onset times are allowed before or after the recorded trip; if drift starts before the first recorded sample, its displacement is already `drift_rate_mps * (first_time_s - onset_time_s)`. If no sample overlaps the interval, the output is unchanged with zero active labels. Duration and magnitude/rate must be positive, direction must be in `[0, 360)`, and non-finite values are rejected. Intervals extending beyond the recorded trip are clipped by available rows.

The defaults are: 50 m northward offset on `[20,40)` seconds; 100 m jump at 45° on `[30,35)`; and eastward drift at 2 m/s on `[20,50)`. Attack transforms use no additional randomness; they preserve each input record's GPS noise and seed. Therefore, a fixed normal GPS file and configuration yield byte-reproducible attack CSVs. Labels and realized displacement are saved separately from observations.

Each coordinate scenario writes `data/attacks/gps_<type>.csv` using the same observation schema as M2, `data/attacks/labels_<type>.csv`, `results/tables/gps_<type>_summary.json`, and trajectory/error plots under `results/figures/`. Observation files contain measured GPS fields only. Label files contain `time_s,trip_id,vehicle_id,attack_type,attack_active,displacement_x_m,displacement_y_m,displacement_m`. JSON and plots use ground truth only for offline position-error evaluation.

The route-deviation scenario is a separate genuine SUMO trip, not a coordinate manipulation. Reproduce it with:

```powershell
python src/attacks/route_deviation.py
```

This runs `src/simulation/run_sumo.py` with `config/route_deviation.yaml` and the separate `sumo/routes/ev_alternative.rou.xml`. The original route is `A0A1 → A1B1`; the alternative is `A0B0 → B0B1`. The runner verifies the observed route ID and both road edges before saving noisy GPS observations. It writes alternative-route truth separately to `data/attacks/route_deviation_truth.csv`; observations and labels go to `data/attacks/`, with separate summary and figures. The label marks the scenario for evaluation; it is not included in GPS observations. Route deviation represents an actual alternate SUMO path, not a forged location presented to a navigation controller.

M3 limits: these deterministic coordinate changes and the alternate-route trip are controlled simulation scenarios, not claims about real adversaries, GNSS receivers, or deployed navigation systems. The route scenario changes the actual simulated path; this implementation does not model an attacker changing route selection from a false location. There is no detector yet. Any future detector must consume only inference-time observation streams and must not read truth, labels, attack parameters, or post-hoc errors.

Run only the M3 tests or the complete suite with:

```powershell
python -m unittest discover -s tests -p "test_m3_*.py" -v
python -m unittest discover -s tests -v
```

Verified in this checkout: the M3-specific command passed 8 tests and the full suite passed all 17 tests. The configured coordinate outputs each contain 83 records (20 offset, 5 jump, 30 drift-active labels); the verified alternative route completed in 82 SUMO steps with 81 telemetry/GPS/label rows. Generation left the original truth and normal-GPS baseline hashes unchanged.

Open the generated figures in Windows PowerShell:

```powershell
Get-ChildItem .\results\figures\gps_*_trajectory.png, .\results\figures\gps_*_error_distribution.png, .\results\figures\route_deviation_*.png | ForEach-Object { Start-Process $_.FullName }
```

M4 is next. No sensor fusion, machine-learning detector, or energy-aware routing has been added.
