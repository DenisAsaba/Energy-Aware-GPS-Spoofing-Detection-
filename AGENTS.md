# Agent instructions: EV GPS spoofing and energy-aware routing

## Mission
Build a reproducible, simulation-only research system for GPS spoofing detection and energy-aware electric vehicle routing, following `docs/PROJECT_SPEC.md`, `docs/IMPLEMENTATION_PLAN.md`, and `TASKS.md`.

## Session startup
1. Inspect the repository, `TASKS.md`, and relevant documentation before editing.
2. State the current milestone, acceptance criteria, and a short implementation plan.
3. Work on only the next incomplete milestone unless explicitly directed otherwise.
4. Do not overwrite functioning code or existing experiments without inspecting it.
5. Identify missing system dependencies and give exact installation/verification commands. Never claim an installation or test succeeded without evidence.

## Non-negotiable engineering rules
- Python-first implementation using SUMO and TraCI. Run local simulations only. Do not operate physical GPS transmitters or interfere with real navigation systems.
- Maintain separation among simulation ground truth, noisy GPS observations, spoofed GPS, derived features, and labels.
- Never expose ground-truth position, ground-truth error, attack labels, future samples, or post-hoc information to an operational detector unless explicitly constructing an oracle upper-bound baseline marked non-deployable.
- Distinguish road-network x/y coordinates in meters from geographic longitude/latitude in degrees. Use explicit coordinate conversions.
- Define units, coordinate system, simulation timestep, random seed, noise distributions, and assumptions for every experiment.
- Do not assume energy effects from GPS manipulation. Implement and verify a causal route-change mechanism before claiming energy consequences.
- Do not invent experimental results, citations, accuracy, energy savings, or p-values.
- Prefer small testable functions, type hints, docstrings, logging, and meaningful errors.
- Keep configuration in `config/experiment_config.yaml`; record configuration and seeds for each run.
- Treat requirements as a starting point; check installed SUMO version and available TraCI battery outputs before choosing APIs.
- Hold out entire trips/routes and evaluate attack-intensity transfer; never randomly split adjacent timesteps across train and test.
- Fit preprocessing and model parameters only on training data. Use validation data for thresholds; keep the test set untouched.
- Separate realistic observable motion/vehicle signals from privileged simulator values, and document availability at inference time.
- Add tests for every feature and regression. Run the applicable tests after changes; state any not run and why.
- Store generated data and figures outside Git when large; do not commit secrets or credentials.

## Definition of done for each milestone
- Working code and at least one repeatable command or script.
- Tests and verification results or explicit blockers.
- Updated README/documentation and `TASKS.md` with completed checkboxes.
- Brief report: files changed, commands run, evidence of success, outstanding limitations, next milestone.

## Instruction priority
Follow explicit current user instructions, then this file, then the project specification and roadmap. Flag conflicts rather than silently altering research goals.
