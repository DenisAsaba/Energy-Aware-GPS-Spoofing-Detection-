# First Codex / VS Code agent prompt

You are the implementation engineer for this research repository. Read `AGENTS.md`, `docs/PROJECT_SPEC.md`, `docs/IMPLEMENTATION_PLAN.md`, and `TASKS.md` fully, then inspect the current repository and tools available in the terminal.

Work only on M0. First report your understanding of the experiment, the current environment, acceptance criteria, and planned file changes. Then implement the smallest runnable SUMO + Python TraCI EV scenario. Check that dependencies are available; if they cannot be installed from your environment, produce exact user-executable install and validation commands instead of pretending they work.

Write modular, readable Python with tests, CLI options for seed and output paths, and a single documented run command. If SUMO is available, execute the first simulation and show evidence from its output. If it is not, explain the blocker and still create a minimal, plausible configuration and tests for pieces that can be validated locally.

Do NOT build spoofing, detectors, fusion or routing yet. Do NOT invent performance results. Update `TASKS.md` and README when complete. Summarize changed files, verification commands and results, outstanding issues, and the precise next step.
