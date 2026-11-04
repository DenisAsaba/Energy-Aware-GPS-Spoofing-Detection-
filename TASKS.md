# Live milestone tracker

**Current milestone:** M1 complete; M2 is next and remains unstarted.

## Local M0/M1 research dashboard
- [x] Add isolated read-only CSV discovery/loading, summary metrics, optional-field handling, interactive chart entry point, and refresh control.
- [x] Add tests for loading, file discovery, empty/malformed files, optional missing columns, metric correctness, and source CSV immutability.
- [x] Document separate dashboard dependencies, units, and the local launch command.
- [x] Verify Streamlit server startup and local URL with the installed dashboard dependencies.

## M0/M1 demonstration workflow
- [x] Add one documented command to run the existing simulation, summarize its new CSV, and save trajectory, speed, and available battery/SOC plots.
- [x] Add opt-in `--keep-open` for SUMO-GUI while preserving the default close-on-completion behavior.
- [x] Test summary calculations against a fresh simulation CSV, plot outputs, missing-battery behavior, no-overwrite protections, and GUI argument defaults.
- [ ] Visually verify the interactive GUI in a desktop session; this execution environment starts SUMO-GUI without a visible window handle.

## M0 acceptance
- [x] Inspect local OS, Python version, SUMO installation and available executables.
- [x] Create minimal reproducible SUMO network, EV type, route and configuration.
- [x] Create a Python TraCI runner with CLI arguments, deterministic seed and logging.
- [x] Add smoke test or clear manual verification command.
- [x] Document exact setup and run steps in README.

## M1 acceptance
- [x] Record time, position, speed, acceleration, heading, road, and route per active vehicle timestep.
- [x] Verify battery/energy values and document source, units, and SOC derivation.
- [x] Save the ground-truth trace to CSV and test types, monotonic timestamps, and deterministic reproducibility.
- [x] Keep the ground-truth trace separate from any future GPS observations.

## Work log
| Date | Milestone | Changes | Validation | Limitations |
| --- | --- | --- | --- | --- |
| 2026-11-03 | M0 | Added one-edge 1,000 m SUMO road, fixed-seed config, Python/TraCI runner and EV route | SUMO 1.28.0 completed ev_001 in 80 steps; integration smoke test passed | pytest absent (unittest used); Git metadata absent |
| 2026-11-04 | M1 | Enabled battery device and explicit 25,000 Wh initial charge; added per-step truth CSV, per-run metadata/config snapshots, and schema/type/spacing/reproducibility integration test; made GUI mode auto-start | Simulation completed 80 steps and wrote 79 active-state rows; unittest passed; timestamped CSV inspected | SUMO removes vehicle at arrival before TraCI can read its arrival-step state; automated session has no visible GUI window |
| 2026-11-04 | M0/M1 demo | Added one-command demo runner, CSV-backed summary, three CSV-stem-named plots, opt-in GUI keep-open flag, and overwrite protection | Headless demo produced summary and 3 PNGs; 5 unittest cases passed, including independent recomputation from CSV rows | Visible GUI cannot be inspected in this automation desktop; `--gui --keep-open` command is documented for interactive PowerShell |
| 2026-11-04 | M0/M1 dashboard | Added separate Streamlit/Plotly read-only dashboard and optional dashboard requirements | Dashboard tests passed; Streamlit AppTest rendered with no exceptions; local HTTP startup returned 200; full suite passed | None observed; dashboard dependency install is separate from simulation requirements |

## M0 verification (2026-11-03)
- Environment: Windows; Python 3.14.6; SUMO, sumo-gui, netgenerate, and netconvert 1.28.0; TraCI 1.28.0; PyYAML 6.0.3. SUMO_HOME resolves to `C:\Program Files (x86)\SUMO`.
- `python src/simulation/run_sumo.py --config config/experiment_config.yaml` passed; logged `Completed EV run: vehicle=ev_001 timesteps=80 seed=42`.
- `python -m unittest discover -s tests -v` passed; 1 integration smoke test ran and the EV trip completed.
- pytest is not installed; tests use built-in unittest. This workspace copy has no .git repository, so Git status/diff evidence is unavailable.

## M1 verification (2026-11-04)
- Reviewed [SUMO Electric model](https://sumo.dlr.de/docs/Models/Electric.html) for battery output fields/units and [TraCI Vehicle Value Retrieval](https://sumo.dlr.de/docs/TraCI/Vehicle_Value_Retrieval.html) for the Wh/s electricity getter and device parameters.
- Runtime probe with SUMO/TraCI 1.28.0 showed M0 battery parameters did not instantiate a battery device. Added `has.battery.device=true` and explicit `device.battery.chargeLevel=25000` Wh. Re-probe returned 50,000 Wh capacity, charge level, per-step energy, cumulative consumed/regenerated energy, and electricity consumption. SOC is charge divided by capacity.
- `python src/simulation/run_sumo.py --config config/experiment_config.yaml` passed: 80 simulation steps, 79 queryable active-state CSV rows. Final inspected file: `data/raw/truth_ev_001_20261104T063621.926817Z.csv`; values inspected, times 1 to 79 seconds at 1-second spacing. Per-run config and metadata snapshots were created beside it.
- `python -m unittest discover -s tests -v` passed: 1 integration test checks exact columns, finite numeric values, battery values, SOC bounds, 1-second monotonic timestamps, and identical rows across repeated fixed-seed runs.
- Limitation: SUMO removes arrived vehicles before TraCI vehicle getters return the arrival-step state. The CSV intentionally contains active states only and does not invent an arrival-step sample. CSVs are under ignored `data/raw/`.
- GUI mode was updated to pass SUMO-GUI's `--start` flag and 150 ms display delay. A GUI run was attempted, but the automated environment supplied no visible window and the TraCI process did not finish; it was stopped. Run the documented `--gui` command from the user's interactive PowerShell session to view the simulation. Headless simulation and smoke test both pass.

### M1 verification refresh (2026-11-04)
- Rechecked the official SUMO 1.28.0 Electric model and TraCI vehicle retrieval documentation before running; battery/energy fields are read from the configured battery device, and SOC is derived only from reported charge/capacity.
- `python src/simulation/run_sumo.py --config config/experiment_config.yaml` passed with seed 42: 80 simulation steps and 79 active, queryable samples. New output: `data/raw/truth_ev_001_20261104T073118.622118Z.csv` with adjacent config and metadata snapshots. Historical CSVs were not modified.
- Inspected the generated CSV: 79 records at 1-second intervals from 1 to 79 s; speed min/mean/max 12.180/12.724/13.172 m/s; sampled X/Y distance 992.036 m; charge 25,000.00 to 24,920.76 Wh; capacity 50,000 Wh; cumulative consumed/regenerated energy 131.17/51.93 Wh; SOC 50.000% to 49.842%.
- `python -m unittest discover -s tests -v` passed all 5 tests, including exact CSV schema/types, timestep spacing, fixed-seed reproducibility, and demo summary/plot checks.
- The arrival-step state is unavailable because SUMO removes the vehicle before TraCI getters can query it; telemetry therefore covers each active/queryable simulation step and contains no fabricated arrival sample. GPS observations/spoofing, sensor fusion, and ML remain unimplemented.

## M0/M1 demo verification (2026-11-04)
- `python src/simulation/demo_m0_m1.py --help` passed and shows the GUI, keep-open, CSV output, and figures-directory options.
- `python -m unittest discover -s tests -v` passed: 5 tests, covering M1 reproducibility/schema and demo summaries, PNG outputs, missing optional battery fields, no-overwrite behavior, and keep-open argument behavior.
- `python src/simulation/demo_m0_m1.py` passed headlessly. CSV: `data/raw/truth_ev_001_20261104T071429.981247Z.csv`; 79 rows, sampled 1.0 to 79.0 s. Summary from the CSV: sampled duration 78.0 s; speed min/mean/max 12.180/12.724/13.172 m/s; sampled X/Y distance 992.036 m; battery charge 25,000.00 to 24,920.76 Wh (50,000 Wh capacity); SUMO cumulative consumed/regenerated 131.17/51.93 Wh; SOC 50.00% to 49.84%. Tests independently recomputed these summary calculations from the CSV.
- Generated three non-overwriting plots under `results/figures/m0_m1/`: trajectory X/Y, speed/time, and battery charge/SOC/time. Existing CSV, metadata, config snapshots, and plot paths are protected against overwrite.
- Matplotlib 3.11.2 was already installed; no new dependency was installed. A visible GUI launch was attempted, but this environment returned zero main-window handles for both Python and SUMO-GUI. The processes were stopped. M0/M1 GUI use is documented for an interactive desktop; no new research milestone was started.

## Local dashboard verification (2026-11-04)
- Dashboard dependencies are isolated in `requirements-dashboard.txt`; environment verified Streamlit 1.66.1, Plotly 6.9.0, and pandas 3.0.6. SUMO/simulation requirements were not changed.
- `python -m unittest tests.test_dashboard -v` passed dashboard CSV discovery/loading, empty/malformed inputs, missing optional values, correct metric calculations, chronological initial/final calculations, and source-file immutability checks.
- `python -m streamlit run src/dashboard/app.py --server.headless true --server.port 8765` was launched as a local startup smoke check and returned HTTP 200 at `http://127.0.0.1:8765`; Streamlit AppTest rendered the full page and reported no app exceptions. The smoke-test server was then stopped.
- `python -m unittest discover -s tests -v` passed all 10 existing and dashboard tests. The dashboard only reads `data/raw/*.csv`; existing simulation and telemetry generation code was not changed, and M2 remains unstarted.

## Rules
Move only to the next incomplete milestone. Keep this file current after every agent session and mark anything not tested as unverified.
