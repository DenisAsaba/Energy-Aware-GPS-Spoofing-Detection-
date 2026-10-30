# Implementation plan

## Completed milestones

- **M0 — SUMO EV simulation:** reproducible one-EV route and TraCI runner.
- **M1 — Telemetry:** separate ground-truth position, motion, route, and available battery streams in CSV.
- **M2 — Normal GPS:** independently seeded noisy observations and offline error products.
- **M3 — Scenarios:** offset, jump, drift, and a separate genuine alternate-route trip; observations, labels, and truth remain separate.
- **M4 — Estimation:** synthetic noisy motion sensors, geometry/heading/network continuity map-matching baseline, constant-velocity GPS/motion Kalman filter, and evaluation/figures. See [M4_DESIGN.md](M4_DESIGN.md) for equations, assumptions, limitations, data layout, and reproduction.

## Next milestones

- **M5 — Spoofing detection and evaluation:** build inference-time features without ground-truth or label leakage; compare documented thresholds, an Isolation Forest trained on normal training trips, and a Random Forest baseline. Split by trip/route and evaluate held-out routes and attack intensities. Report precision, recall, F1, false-positive rate, detection delay, latency, ablations, and confusion matrices. Do not use adjacent time samples from one trip as independent train/test records.
- **M6 — GPS-dependent eco-routing and energy causality:** implement at least two plausible routes and make route choice consume the estimated GPS/fused position. Verify the chain from attack to localization estimate to route selection to executed route before comparing EV energy. Use matched seeds and scenarios; include imperfect detector response and report route, distance, duration, energy, and SOC only when supported by simulation outputs.
- **M7 — Research reporting:** broaden route, traffic, intensity, and seed experiments; quantify uncertainty; produce methods, plots, limitations, and reproducible final report. Make no real-world claims from simulation alone.

## Research integrity gates

Keep truth, attack labels, attack parameters, and post-hoc errors out of operational estimator/detector inputs. Preserve data provenance and seeds. Never infer energy effects from coordinate error alone. Keep simulation outputs and synthetic sensor assumptions clearly identified. Advance each milestone only when code, tests, reproducible commands, and limitations are documented.
