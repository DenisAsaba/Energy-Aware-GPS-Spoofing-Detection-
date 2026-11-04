# Research system specification

## Working title
Detection of GPS Spoofing and Assessment of Energy Consequences in Electric Vehicle Eco-Routing through Multi-Sensor Fusion.

## Research objective
Use SUMO-based EV trip simulations to (1) build ground-truth trajectories and reproducible noisy GPS measurements; (2) inject four simulated GPS manipulation patterns; (3) compare motion, road-network, and energy-based consistency signals for attack detection; (4) determine whether a GPS-dependent eco-routing controller actually changes its route under an attack and whether that causes measurable energy differences.

## Core causal chain
Manipulated GPS observation -> altered estimated location -> different route or route decision -> actual executed driving behavior -> measured EV energy consumption. A spoofed coordinate alone is not evidence of increased energy use.

## Components
1. SUMO network with alternate valid routes, vehicle and EV/battery configuration, traffic scenarios.
2. Python TraCI simulation runner and per-timestep CSV telemetry logger.
3. Separate measured GPS noise generator with configurable, physically plausible errors.
4. Simulation-only position offset, sudden jump, gradual drift, and map-valid route-deviation attacks.
5. Dead-reckoning motion baseline, followed by Kalman-filter sensor fusion.
6. Map matching, road topology and heading/transition consistency checks.
7. Feature calculation from observations available to the deployed detector.
8. Threshold, Isolation Forest, and Random Forest detectors; optional XGBoost.
9. GPS-dependent eco-routing, detection response, EV energy accounting.
10. Evaluation, ablations, plots, and reproducibility report.

## Ground truth schema
`time_s,trip_id,vehicle_id,x_m,y_m,speed_mps,acceleration_mps2,heading_deg,road_id,route_id,energy_wh,soc`.
These are proposed canonical names, not claims that SUMO provides each value natively. Verify available battery telemetry and define computation/derivation for missing fields. Document whether energy means consumption per timestep or cumulative consumption, and whether SOC is simulated or directly reported. Keep energy sign conventions explicit.

## GPS schema
`time_s,trip_id,vehicle_id,gps_x_m,gps_y_m,attack_type,attack_intensity,attack_active` plus seed/config metadata. Keep attack labels separate from model input feature matrices.

## Candidate detector inputs
- GPS displacement speed vs observable vehicle speed; acceleration and heading consistency
- GPS-to-motion prediction residual, Kalman innovation (computed without ground-truth leakage)
- road proximity, topology-valid transitions, heading-vs-road direction, planned-route disagreement
- energy rate / SOC change only if independently observed and actually relevant to the detector's task

**Forbidden operational features:** `gps_position_error` computed from simulation truth, true route location, attack labels, future trajectory, and other hidden simulation-only state. Those may be used for offline evaluation, never as inputs to the deployed classifier. Record this distinction in the feature dictionary.

## Evaluation
- Attack classes: none, offset, jump, gradual drift, route deviation.
- Severity: low, medium, high with documented values and rationale.
- Trips, roads, traffic conditions, and random seeds vary. Split by trip or held-out route.
- Compare precision, recall, F1, false-positive rate, detection delay and inference latency (with precise definitions).
- Ablations: GPS only; GPS+motion; GPS+map; GPS+motion+map; full system including energy if valid.
- Energy conditions: normal GPS; spoofed with no detection; spoofed with detector/safe response. Compare matched scenarios, same initial state, network, traffic controls and random seeds where feasible.
- Record distance, duration, energy (Wh), SOC, and estimated range only when the underlying model supports them. Never prefill results.

## Key scientific safeguards
- Ordinary GPS errors must not be confused with spoofing by construction.
- A map-valid spoofed road does not guarantee a physically plausible route transition.
- Demonstrate intermediate causal variables (estimated location, selected route, executed route) before attributing energy differences to spoofing.
- Model false alarms, delayed detections, and incomplete recovery in mitigation scenarios, not an unrealistically perfect detector.
- State the threat model, sensor trust assumptions, limitations, and ethical scope before interpreting results.

## Scope
Start with a simple SUMO map and one EV; expand to multiple routes and traffic conditions. No deep learning, large public dataset or physical spoofing hardware required for the baseline.

## Origin and limitations
Adapted from the user-provided planning document, which starts at numbered Phase 2. Earlier phases and the formal original thesis proposal were not supplied; initial setup tasks are reconstructed from the provided weekly plan. Specific SUMO API and battery implementation choices remain to be verified in the actual environment.
