# Phased implementation and acceptance criteria

Each phase is gated. Do not move ahead without evidence.

## M0: Toolchain and first SUMO EV run (proposal weeks 1-2)
- [ ] Verify Python, VS Code, SUMO, `sumo-gui`, `netgenerate`, TraCI, Git.
- [ ] Set up venv, dependencies, config, basic network/route and one EV.
- [ ] A Python runner starts SUMO with a fixed seed and completes a trip.
**Acceptance:** documented command exits successfully; logs trip identifier and timesteps.

## M1: Ground truth and EV telemetry (weeks 3-4)
- [ ] Record timestamp, position, speed, acceleration, heading, road and route.
- [ ] Verify battery/energy signals; document units and data source; compute SOC only if justified.
- [ ] Write `truth.csv` and test field types, monotonic time, deterministic reproducibility.
**Acceptance:** normal EV trip replay produces validated CSV; no attacks implemented yet.

## M2: Normal GPS observations (weeks 5-6, first half)
- [ ] Add independently seeded configurable GPS noise using SUMO metric coordinates.
- [ ] Preserve clean truth separately; generate `gps_normal.csv`.
- [ ] Plot ground truth vs measured GPS and summarize observed error distribution.
**Acceptance:** nonzero configurable noise; repeatable seed; detector never reads ground truth.

## M3: Four simulated attacks (weeks 5-6, second half)
- [ ] Offset, jump, drift and network-valid route deviation with configurable intensity and onset.
- [ ] Labels stored outside detector inputs; plots and attack-unit tests.
**Acceptance:** all four alter only observable GPS measurements while truth remains unchanged.

## M4: Motion, fusion and map matching (weeks 7-9)
- [ ] Dead reckoning; speed/heading residuals; a Kalman baseline with documented state, covariance and update rules.
- [ ] Verify innovation calculations do not use true position.
- [ ] Road distance, topology, heading alignment, transitions and route disagreement.
**Acceptance:** trajectory comparison and feature dictionary, with leakage audits.

## M5: Detection and ablation evaluation (weeks 10-11)
- [ ] Threshold baseline; Isolation Forest trained on normal training trips; Random Forest supervised baseline.
- [ ] Grouped train/validation/test by trip; held-out routes and severity transfer.
- [ ] Five input ablations, metrics, confusion matrices, detection-delay definitions.
**Acceptance:** reproducible scripts write real metrics with seeds; no claims from synthetic placeholder tables.

## M6: Eco-routing and energy causality (week 12)
- [ ] At least two plausible routes with distinct energy characteristics.
- [ ] Route selection explicitly uses estimated GPS and can be affected by spoofing.
- [ ] Verify attack can change route choice; then compare executed paths and energy.
- [ ] Add detector-aware safe response with realistic errors/delay.
**Acceptance:** matched scenario logs show localization, route choice, driven path, energy and detector state.

## M7: Research reporting (weeks 13-14)
- [ ] Attack intensity matrix, per-attack metrics, ablations, energy results, uncertainty and limitations.
- [ ] Plots, manuscript methods, reproducible runbook, README and clean tests.
**Acceptance:** new user can recreate main figures from code and configuration.

## Initial five milestones
1. SUMO runs an EV.
2. Python/TraCI retrieves vehicle position, motion and available energy data.
3. Save trace to CSV.
4. Generate realistic seeded GPS observations.
5. Plot true vs noisy GPS trajectories.
No attack work until the fifth milestone passes.
