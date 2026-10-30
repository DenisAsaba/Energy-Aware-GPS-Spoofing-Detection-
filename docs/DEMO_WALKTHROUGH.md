# Project walkthrough and live demo

## One-minute summary

We have a reproducible SUMO simulation of one battery-equipped electric vehicle, a separate seeded normal-GPS observation stream, and four controlled attack scenarios. We keep simulator truth, GPS observations, and attack labels in separate files. The current system generates scenarios and offline comparisons; it does not yet detect spoofing or let spoofed GPS change a navigation decision.

## Live demo order

Open PowerShell in the project directory (`Energy-Aware-GPS-Spoofing-Detection-`) and run:

```powershell
python src/simulation/run_sumo.py
python src/sensors/gps_normal.py
python src/attacks/gps_spoofing.py --attack all
python src/attacks/route_deviation.py
```

The first command runs SUMO through TraCI and writes `data/raw/truth.csv`. It samples position, speed, acceleration, heading, route and available battery/energy fields after each simulation step. The baseline trip takes 84 simulation steps and records 83 active-vehicle samples (seconds 1–83); SUMO removes the EV at arrival.

The second command reads truth and writes 83 normal GPS observations to `data/processed/gps_normal.csv`, plus two plots and an offline JSON error summary. The next command transforms that GPS baseline into offset, jump and drift scenarios, each with a separate observation CSV, label CSV, summary, trajectory plot and error plot. The final command runs a different SUMO route, verifies its route ID and traversed road edges, then saves its truth, GPS observations, labels, summary and figures separately.

To verify the generated outputs during the presentation, show `results/figures/ev_trajectory_gps_normal.png`, `results/figures/gps_offset_trajectory.png`, `results/figures/gps_jump_trajectory.png`, `results/figures/gps_drift_trajectory.png`, and `results/figures/route_deviation_trajectory.png`. JSON summaries are in `results/tables/`.

## Algorithm explanation

### Simulation and telemetry (M0–M1)

SUMO advances the EV in 1-second steps with configured seed 42. TraCI reads a post-step state only while the vehicle is on the network. The runner validates CSV columns, finite numeric values and increasing timestamps. Coordinates are SUMO's local Cartesian network coordinates in meters, not latitude/longitude. Battery state of charge is computed as charge divided by capacity; other battery values are read from SUMO's battery device when available.

### Normal GPS baseline (M2)

For each truth sample, the generator independently draws `dx` and `dy` from a zero-mean Gaussian distribution with configured standard deviation 3 m, using GPS seed 123. It writes `(x + dx, y + dy)` with identifiers and model metadata, but no truth coordinates or errors. Because the two axis errors are independent Gaussian variables with equal variance, radial error follows a Rayleigh distribution under this model. Truth is joined back only in the plotting and summary step for offline evaluation.

### Coordinate attacks (M3)

Attacks add a configured displacement to the normal GPS coordinates during a half-open time window: `onset <= time < onset + duration`. They are deterministic transforms; the baseline noise is preserved outside the attack interval, and observations return to normal afterward.

- **Offset:** a fixed displacement vector. Defaults: 50 m toward +y for 20 seconds starting at t=20 s.
- **Jump:** a fixed 100 m displacement at 45 degrees for 5 seconds starting at t=30 s. It appears and disappears abruptly.
- **Drift:** displacement grows linearly from zero at 2 m/s toward +x for 30 seconds starting at t=20 s; it reaches 58 m on the final active sample at t=49 s.

Direction is measured counterclockwise from SUMO +x. A vector of magnitude `m` and direction `θ` is `(m cos θ, m sin θ)`. Drift uses magnitude `rate × (time − onset)` over its active interval. Labels and displacement values are stored beside the observations in a separate file, never in the GPS observation input.

### Route-deviation scenario (M3)

This is a second genuine SUMO trip on the valid alternative edges `A0B0 → B0B1`, with a distinct route ID. It changes the simulated vehicle path; it does not forge coordinates or show that a spoofed fix caused a route planner to change course. That causal loop remains future work.

## Demonstrated results

The live run used SUMO seed 42 and GPS seed 123. Baseline truth and normal GPS each contain 83 samples. With per-axis sigma 3 m, offline radial GPS error was mean 3.370 m, median 3.024 m, standard deviation 1.927 m, 95th percentile 6.601 m, and maximum 8.719 m. These describe this synthetic run, not real receiver accuracy.

| Scenario | Active records | Mean offline position error | 95th percentile | Maximum |
| --- | ---: | ---: | ---: | ---: |
| Normal GPS | 0 | 3.370 m | 6.601 m | 8.719 m |
| 50 m offset | 20 / 83 | 14.377 m | 50.583 m | 52.577 m |
| 100 m jump | 5 / 83 | 9.190 m | 96.024 m | 101.187 m |
| 2 m/s drift | 30 / 83 | 12.841 m | 51.053 m | 60.170 m |
| Alternative route | Separate SUMO trip, 81 records | 3.340 m | 6.601 m | 8.719 m |

The alternative route used ID `ev_route_alternative` and the configured edges were observed. It completed in 82 simulation steps. Its GPS errors remain similar to baseline because it uses the same noise model and seed; its distinct result is the changed path.

The EV telemetry includes energy-related values, but these experiments have not established energy consequences from spoofing. No comparison claims an energy increase or saving.

## What we are building next

**M4: motion consistency, sensor fusion and map matching.** First add a dead-reckoning baseline and compare GPS motion against speed/heading residuals. Then add a documented Kalman-filter baseline with explicit state, covariance and update equations. Add road-distance, heading, topology, transition and route-disagreement features. The key design rule is that detector features can use only streams available at inference time; truth, attack labels, attack parameters and post-hoc errors remain evaluation-only.

After M4, the plan is to train and evaluate threshold, Isolation Forest and Random Forest baselines using trip/route-grouped train/validation/test splits (M5). Eco-routing and energy causality come later (M6): spoofed location must first change an estimated location and selected route, then an actual executed path, before energy differences can be attributed to it. Reporting and reproducibility follow in M7.

## Suggested closing

“So far, we have built the reproducible simulation and controlled data needed to study the problem, and demonstrated how normal GPS noise and three coordinate manipulations affect measured positions. Next we will build the detector from motion and road-consistency signals, while preserving the boundary between live inputs and simulator-only evaluation truth. We have not yet demonstrated detection performance or an energy impact.”
