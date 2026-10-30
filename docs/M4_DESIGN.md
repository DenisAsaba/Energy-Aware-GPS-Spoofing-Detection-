# M4 sensor and estimator design

## Available signals and separation

The M1 telemetry contains SUMO network position (`x_m`,`y_m`, meters), speed (`m/s`), acceleration (`m/s^2`), SUMO heading (`degrees`, 0 north and clockwise), road/route IDs, and battery signals. The network XML supplies directed drivable edges, lane centerline geometry, edge lengths, endpoints, and legal edge connections. Coordinates are local SUMO Cartesian meters, not longitude/latitude.

M4 emits a new motion stream under `data/m4/sensors/`. It adds independent seeded Gaussian error to speed (default sigma 0.25 m/s), heading (2 degrees, wrapped to [0,360)), and longitudinal acceleration (0.15 m/s^2); noisy speed is clipped at zero. Defaults and the independent seed are in `config/experiment_config.yaml`. These are simulated sensor observations derived from SUMO outputs, not measurements from physical devices or a validated vehicle sensor model. Acceleration is retained for future use; the M4 estimators currently use speed and heading.

Motion records contain `time_s,trip_id,vehicle_id,motion_seed,speed_mps,heading_deg,acceleration_mps2`. GPS, motion, map-match and fusion outputs are separate files. M4 estimators do not load truth or labels. Truth and M3 labels are read only by the evaluation stage after estimates exist.

## Map-matching baseline

`src/mapping/map_matching.py` reads SUMO's network XML and considers each directed non-internal edge's lane shape. It projects each GPS point onto every edge's polyline and keeps candidates within a configured radius. Candidate emission cost is squared perpendicular distance plus a weighted squared heading disagreement. SUMO heading is converted to mathematical angle from +x for comparison with directed edge geometry. A transition cost checks whether edges are the same or connected by a directed path, compares implied along-network travel distance with noisy speed times elapsed time, and strongly penalizes disconnected or implausible transitions. The lowest local candidate plus transition cost is selected.

This is a greedy, explainable scoring baseline; it is **not** an HMM, Viterbi decoder, or globally optimal route inference. A record with no candidate is retained and marked unmatched with empty road/position fields. Network distance uses shortest directed edge lengths; junction shape/internal-lane detail and lane choice are simplified.

## Sensor fusion baseline

`src/fusion/sensor_fusion.py` maintains state `[x, y, vx, vy]` with covariance. It initializes x/y from the first GPS observation and velocity from the simultaneous noisy speed and heading when available (otherwise zero). For each step it propagates position with the previous velocity estimate, grows covariance under a white-acceleration process-noise model, performs scalar velocity Kalman updates from speed/heading converted to x/y velocity (using an approximate per-axis variance from speed and heading noise), then performs scalar x/y GPS Kalman updates using configured GPS sigma. Missing motion means constant-velocity propagation; missing GPS means prediction without position correction. Speed and heading alone cannot provide absolute position; the first GPS measurement supplies the arbitrary, potentially spoofed origin. Errors accumulate during prediction, and GPS attacks can pull the estimate off course. The method is an intentionally small constant-velocity Kalman baseline, not a full vehicle-dynamics or multi-sensor model.

## Evaluation and outputs

Run all five inputs (normal, offset, jump, drift, and alternate-route observations). Evaluation joins records on `(trip_id, vehicle_id, time_s)` and compares raw GPS, map matching, and fusion on the same common set of records with a valid map match. It reports mean, median, nearest-rank p95, RMSE, maximum error, common comparison count, total input count, match success rate, and unmatched percentage. This prevents unmatched map records from making method-level error comparisons use different samples; coverage is reported alongside errors. Ground truth is used only in this post-estimation stage. Metrics over one short synthetic trip are descriptive for these configured runs, not estimates of real-world performance. A genuine route-deviation trip has its own route truth and is evaluated against that truth.

Outputs are under `data/m4/sensors/`, `data/m4/estimates/`, `results/tables/m4_metrics.json`, and `results/figures/m4_*.png`. M0-M3 source datasets are input-only and are not intentionally rewritten.
