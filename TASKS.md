# Live milestone tracker

**Current milestone:** M3 complete; M4 is next.

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

M0, M1, M2 and M3 acceptance criteria pass in the checked environment. Ground-truth error, labels and attack parameters must not become operational detector inputs.
