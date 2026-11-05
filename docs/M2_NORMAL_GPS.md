# M2: Normal GPS measurement simulation

The M2 generator reads an existing M1 ground-truth CSV and writes a separate operational GPS CSV. Coordinates remain in SUMO's local road-network X/Y frame, in meters; they are not longitude/latitude. At each row it adds independent zero-mean Gaussian noise to X and Y:

`gps_x_m = x_m + Normal(0, sigma_m)` and `gps_y_m = y_m + Normal(0, sigma_m)`.

The default `sigma_m` is 3.0 m per axis, the standard deviation of each coordinate error (not a radial accuracy guarantee). The configured seed is 2026 and NumPy's `default_rng` provides a local reproducible generator. A zero standard deviation is supported. The model assumes independent, stationary, isotropic coordinate noise and is a simulation approximation; real GPS errors can be correlated, biased, heavy-tailed, environment-dependent, and non-Gaussian. This milestone adds no offsets, jumps, drift, spoofing, or route changes.

Operational `gps_normal_*.csv` contains exactly `time_s,vehicle_id,gps_x_m,gps_y_m`. The generator validates required coordinates and unique `(time_s, vehicle_id)` keys, rejects missing/nonfinite values, never fills or invents records, and refuses to write over its input. It does not carry SUMO road/route state, ground-truth coordinates, or error labels. The evaluator alone joins truth to GPS by `(time_s, vehicle_id)`. It reports mean horizontal error (arithmetic mean Euclidean distance), MAE (mean absolute horizontal error; equal to mean error for nonnegative distances), RMSE (square root of mean squared horizontal error), 95th percentile horizontal error, matched count, unmatched GPS count, and unmatched truth count, all errors in meters. Evaluation errors are not added to operational observations.

## Configuration and commands (PowerShell)

`config/experiment_config.yaml` contains `gps_normal.noise_std_m`, `seed`, `input_dir`, optional `input_file`, `output_dir`, and `evaluation_dir`. If `input_file` is null, generation selects the most recently modified `truth_*.csv` in `input_dir`; pass `--input` to choose explicitly.

```powershell
# Generate observations from latest raw truth (or pass --input data/raw/truth_....csv)
python src/sensors/gps_normal.py generate --config config/experiment_config.yaml

# Evaluate and generate trajectory, error/time, and error-distribution plots
python src/sensors/gps_normal.py evaluate --truth data/raw/truth_ev_001_20261104T073118.622118Z.csv --gps data/processed/gps_normal_ev_001_20261104T073118.622118Z.csv --output-dir reports/m2

# Run the complete repository suite
python -m unittest discover -s tests -v
```

Generation logs its selected output, noise standard deviation, and seed. Evaluation writes JSON metrics and three PNGs under the selected report directory. Use `--output` during generation and `--output-dir` during evaluation to choose alternate paths. The generated artifacts are ignored by Git.

## Limitations

This is a simple coordinate-noise baseline on SUMO's artificial metric map, not a receiver-level GNSS simulator. No temporal correlation, multipath, satellite geometry, projection conversion, or receiver metadata is modeled. Time-key matching uses exact CSV numeric timestamps and vehicle IDs.
