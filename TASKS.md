# Live milestone tracker

**Current milestone:** M4 complete; M5 is next.

## M2 acceptance checklist

- [x] Add independently seeded, configurable normal GPS noise in SUMO metric coordinates.
- [x] Preserve ground truth separately and export `data/processed/gps_normal.csv`.
- [x] Plot ground truth against observations and show the offline radial-error distribution.
- [x] Test reproducibility, nonzero configurable noise, GPS schema, and ground-truth preservation.
- [x] Run the full test suite and generate M2 artifacts; record measured results.

## Work log

| Date | Milestone | Changes | Validation | Limitations |
| --- | --- | --- | --- | --- |
| 2026-10-26 | M0 | Built SUMO EV scenario and Python/TraCI runner. | Existing smoke test verifies the seeded trip completes. | One vehicle and one route. |
| 2026-10-26 | M1 | Added per-step truth telemetry, battery/energy fields, CSV validation and ground-truth trajectory plot. | Existing tests cover telemetry values, schema, time ordering, and simulation repeatability. | Optional battery values depend on SUMO configuration. |
| 2026-10-26 | M2 | Added separate seeded GPS observations, configured independent per-axis Gaussian noise (sigma 3 m), comparison and radial-error plots, and offline JSON summary. | `python -m unittest discover -s tests -v`: all 9 tests passed. `python src/sensors/gps_normal.py` generated 83 observations and both plots from existing truth. Verified the truth CSV SHA-256 was unchanged. Seed 123 radial error: mean 3.370 m, median 3.024 m, SD 1.927 m, p95 6.601 m, max 8.719 m. | Independent Gaussian axes are a simple simulation assumption, not a validated receiver or urban-canyon model. |

## M3 acceptance checklist

- [x] Add configurable offset, jump, and linear-drift transforms over the normal GPS baseline.
- [x] Keep attack observations, per-record labels/displacements, and truth in separate files.
- [x] Add an actual alternate-route SUMO run and verify its route ID and traversed edges.
- [x] Define interval boundaries, coordinate direction, invalid parameters, and out-of-trip behavior.
- [x] Add synthetic attack tests and a SUMO route integration test.
- [x] Run targeted and full test suites; verify generated outputs and baseline preservation.

## M3 work log

| Date | Milestone | Changes | Validation | Limitations |
| --- | --- | --- | --- | --- |
| 2026-10-26 | M3 | Added deterministic offset/jump/drift scenarios with separate labels, JSON evaluation summaries and plots. Added valid alternative route `A0B0 B0B1`, separate SUMO config/truth, and route-deviation GPS output. | `python -m unittest discover -s tests -p 'test_m3_*.py' -v`: 8 passed. `python -m unittest discover -s tests -v`: all 17 passed. Generated all four scenarios. Coordinate outputs have 83 rows and 20/5/30 active labels; route run completed in 82 SUMO steps with 81 rows. Independently verified schemas, key alignment, finite coordinates, inactive equality to normal GPS, and unchanged truth/M2 GPS SHA-256 values. | Route deviation changes the actual SUMO trajectory; it does not model false GPS causing a navigation controller to choose that route. |

## Rules

M0-M4 acceptance criteria pass in the checked environment. Ground-truth error, labels and attack parameters must not become operational estimator or detector inputs.

## M4 implementation checklist

- [x] Inspect M3 data, SUMO telemetry, road geometry/connectivity, configs, and tests. `docs/PROJECT_SPEC.md` was absent from this checkout; added `docs/IMPLEMENTATION_PLAN.md` and `docs/M4_DESIGN.md` for current roadmap and methods.
- [x] Generate separate seeded noisy speed, heading, and acceleration observations.
- [x] Add explainable geometric map matching with heading, speed/time continuity, connectivity, and unmatched records.
- [x] Add separate GPS/motion constant-velocity Kalman fusion with documented initialization and missing-data behavior.
- [x] Add offline aligned evaluation and trajectory/error/RMSE figures for all five M3 GPS scenarios.
- [x] Add synthetic tests for noise reproducibility/schema, map candidates/continuity/connectivity/no match, fusion initialization/missing inputs, and metrics.
- [x] Run M4 pipeline and full test suite; record measured outcomes and any limitations.

## M4 work log

| Date | Milestone | Changes | Validation | Limitations |
| --- | --- | --- | --- | --- |
| 2026-10-29 | M4 | Added seeded synthetic speed/heading/acceleration observations, directed road-geometry matching, GPS/motion Kalman fusion, five-scenario offline evaluation, and 11 figures. Added M4 design documentation and reproduction commands. | `python src/experiments/run_m4.py --stage all --scenario all` generated 5 motion files, 5 map estimates, 5 fused estimates, metrics JSON and 11 PNGs. `python -m unittest discover -s tests -v`: 25 tests passed. Integration test hashed every M0-M3 CSV before/after the full pipeline; all were unchanged. Metrics compare methods on common valid map-match records: normal RMSE raw/map/fusion 3.882/2.779/2.223 m; jump 16.008/17.191/13.441 m. Leakage tests confirmed that added truth/label columns do not affect estimates. | Single short trip per scenario; synthetic noise model. Greedy map matcher can select a wrong road (jump maximum error 111.911 m, exceeding raw GPS maximum on the same records, 100.336 m), and fusion inherits initial GPS error. These runs are not evidence of real-world performance. |
