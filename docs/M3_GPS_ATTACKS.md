# M3: simulated GPS attacks

M3 creates independent attack observations for the existing M1 trip and a
separate physical SUMO trip on a valid alternative route. SUMO X/Y and GPS X/Y
are local road-network coordinates in meters. The simulation step is one
second; configured seed is 42 for SUMO and 2026 for GPS noise. GPS noise is the
same independent per-axis Gaussian model as M2 (`sigma=3 m`). M3 is simulation
only; no hardware or real navigation system is involved.

## Attack definitions

For offset, jump, and drift, the attack interval is half-open:
`[onset_s, onset_s + duration_s)`. The underlying truth file is read-only.
Noisy GPS is generated from it with NumPy's seeded generator, then the attack
is applied to the observable coordinates. Each GPS CSV contains exactly
`time_s, vehicle_id, gps_x_m, gps_y_m`. Per-sample labels, run configuration,
seed, and provenance are kept in adjacent `_labels.csv` and `_metadata.yaml`
files. Do not pass those label or metadata files to an operational detector.

- **Offset:** add a constant configured vector during the active interval.
- **Jump:** apply an abrupt constant vector for the configured interval, then
  restore the noisy baseline when the interval ends. It is a finite pulse.
- **Drift:** add a vector whose magnitude grows at `rate_mps` per sample from
  the first active sample and caps at `max_displacement_m`.
- Directions use compass bearings (0 degrees north, clockwise); positive X is
  east and positive Y is north. Magnitudes are meters and drift rate is m/s.

Default M1-based scenarios use offset onset/duration/magnitude 20 s/30 s/30 m
at 90 degrees; jump 35 s/5 s/60 m at 45 degrees; drift 20 s/30 s/1 m/s at 0
degrees, capped at 25 m. Attack magnitude is also recorded per sample in the
separate labels file.

## Alternative route

`sumo/network/m3.nod.xml` and `m3.edg.xml` are separate M3 inputs. `netconvert`
generates `m3.net.xml`; the M3 route uses the connected ordered edges
`road_alt_0 road_alt_1` from west through north to east. SUMO validates the
route before its trip is simulated. M0's network, route, and M0/M1 telemetry
are not edited. M3 route deviation uses its own simulation truth CSV and GPS
observations; its labels say `route_deviation` and its metadata records the
selected route.

This is a physical alternative-route scenario, not a GPS-driven route-choice
experiment. The longer path and different energy telemetry do not establish
that GPS spoofing caused a route change or energy increase. That causal
controller experiment is outside M3 and remains unimplemented.

## Reproduce

From the project root, use a new run ID for each complete data generation;
outputs refuse overwrite. SUMO (`sumo`, `netconvert`), TraCI and Python
dependencies from the M0/M1 setup must be available. The first command
generates the separate network and executes route validation; the second
creates four GPS datasets, labels, metadata, metrics, and trajectory/error
plots. Omit `--truth` to select the most recently modified `data/raw/truth_*.csv`.

```powershell
python -m src.attacks.gps_attacks --config config/experiment_config.yaml --run-id m3_reproduction_01
python -m unittest discover -s tests -v
```

Outputs go under `data/attacks/m3_reproduction_01/` and
`reports/m3/m3_reproduction_01/`. To select an explicit M1 truth file, add
`--truth data/raw/truth_<run>.csv`. A direct command to produce the isolated
network is:

```powershell
netconvert --node-files sumo/network/m3.nod.xml --edge-files sumo/network/m3.edg.xml --output-file sumo/network/m3.net.xml
```

That direct command is for a fresh checkout where `m3.net.xml` does not exist;
the Python workflow leaves an existing network untouched and validates it.

## Verified example results

The checked example uses M1 truth
`truth_ev_001_20261104T073118.622118Z.csv`, seed 2026, and the defaults above.
Metrics are offline joins by `(time_s, vehicle_id)` using the M2 evaluator's
horizontal Euclidean error convention. They describe this deterministic
synthetic run, not real-world performance.

| Scenario | Matches | Active label samples | MAE (m) | RMSE (m) | 95th percentile (m) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Offset | 79 | 30 | 14.004687 | 19.252981 | 34.678888 |
| Jump | 79 | 5 | 7.492904 | 15.645186 | 55.167881 |
| Drift | 79 | 30 | 8.379058 | 11.220782 | 24.406715 |
| Route deviation | 109 | 109 | 3.571623 | 4.009786 | 6.667635 |

Offset/jump/drift retain the same M1 truth and include the same normal GPS
noise outside their active interval, so overall metrics include unattacked
samples. Route deviation is evaluated against its own separate route truth;
its lower error reflects normal GPS noise, not a failure to execute the
alternative path. The baseline sampled X/Y path was 992.036 m with 131.17 Wh
cumulative consumed energy; the alternative-route sample was 1329.129 m with
198.40 Wh. These are descriptive, non-matched route runs and are not an energy
causality result.

Each scenario writes a metrics JSON plus trajectory and error-over-time PNG.
All four M3 tests exercise timing, vector/intensity behavior, reproducibility,
no label leakage, route validity, evaluation artifacts, and preservation of
M0 source files and input truth. The complete repository suite is run with the
command above.
