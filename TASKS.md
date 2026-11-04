# Live milestone tracker

**Current milestone:** M0 complete; M1 is next and remains gated pending explicit direction.

## M0 acceptance
- [x] Inspect local OS, Python version, SUMO installation and available executables.
- [x] Create minimal reproducible SUMO network, EV type, route and configuration.
- [x] Create a Python TraCI runner with CLI arguments, deterministic seed and logging.
- [x] Add smoke test or clear manual verification command.
- [x] Document exact setup and run steps in README.

## Work log
| Date | Milestone | Changes | Validation | Blockers |
| --- | --- | --- | --- | --- |
| 2026-11-03 | M0 | Added one-edge 1,000 m SUMO road, battery-equipped EV, fixed-seed config, Python/TraCI runner, metadata and smoke test | SUMO 1.28.0 run completed ev_001 in 80 steps; smoke test command recorded below | pytest absent (unittest used); Git metadata absent; battery telemetry not yet checked |

## M0 verification (2026-11-03)
- Environment: Windows; Python 3.14.6; SUMO, `sumo-gui`, `netgenerate`, and `netconvert` 1.28.0; TraCI 1.28.0; PyYAML 6.0.3. `SUMO_HOME` resolves to `C:\Program Files (x86)\SUMO`.
- `python src/simulation/run_sumo.py --config config/experiment_config.yaml` — passed; logged `Completed EV run: vehicle=ev_001 timesteps=80 seed=42`.
- `python -m unittest discover -s tests -v` — passed; 1 integration smoke test ran and the EV trip completed.
- `pytest` is not installed; test uses built-in `unittest`. This workspace copy has no `.git` repository, so Git status/diff evidence is unavailable.
- Limits: M0 only establishes EV trip completion. Battery model parameters are present but energy values are not read or verified. No M1 telemetry or GPS work is included.

## Rules
Move to M1 only after the M0 acceptance criterion passes. Keep this file current after every agent session. Mark anything not tested as unverified.
