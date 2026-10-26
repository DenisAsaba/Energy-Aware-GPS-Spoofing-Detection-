"""Run the reproducible M0 SUMO electric-vehicle trip via TraCI."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import shutil
import sys

import traci
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOGGER = logging.getLogger("ev_sumo")


def load_config(config_path: Path) -> dict:
    """Load the experiment YAML and return its simulation settings."""
    with config_path.open(encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    if not isinstance(config, dict) or not isinstance(config.get("simulation"), dict):
        raise ValueError(f"Missing simulation settings in {config_path}")
    return config["simulation"]


def resolve_path(value: str) -> Path:
    """Resolve a configured path relative to the project root."""
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def sumo_binary() -> str:
    """Find the SUMO executable, including the standard Windows install."""
    binary = shutil.which("sumo")
    if binary:
        return binary
    if os.name == "nt":
        candidate = Path(os.environ.get("SUMO_HOME", r"C:\Program Files (x86)\SUMO")) / "bin" / "sumo.exe"
        if candidate.is_file():
            return str(candidate)
    raise FileNotFoundError("SUMO executable not found; install SUMO and add its bin directory to PATH")


def run(config_path: Path, seed: int | None = None, max_steps: int | None = None) -> int:
    """Run until the configured EV completes or the step limit is reached."""
    settings = load_config(config_path)
    vehicle_id = str(settings["vehicle_id"])
    seed = int(settings["seed"] if seed is None else seed)
    max_steps = int(settings["max_steps"] if max_steps is None else max_steps)
    sumocfg = resolve_path(settings["config_file"])
    if not sumocfg.is_file():
        raise FileNotFoundError(f"SUMO configuration not found: {sumocfg}")

    command = [sumo_binary(), "-c", str(sumocfg), "--seed", str(seed), "--no-step-log", "true"]
    steps = 0
    completed = False
    LOGGER.info("Starting SUMO with seed=%d vehicle_id=%s", seed, vehicle_id)
    try:
        traci.start(command)
        while traci.simulation.getMinExpectedNumber() > 0 and steps < max_steps:
            traci.simulationStep()
            steps += 1
            if vehicle_id in traci.vehicle.getIDList():
                continue
            if traci.simulation.getMinExpectedNumber() == 0:
                completed = True
        if not completed:
            raise RuntimeError(
                f"Vehicle {vehicle_id} did not complete within {max_steps} steps "
                f"(simulation reports {traci.simulation.getMinExpectedNumber()} expected vehicles)"
            )
    finally:
        if traci.isLoaded():
            traci.close()

    LOGGER.info("Trip completed: vehicle_id=%s timesteps=%d seed=%d", vehicle_id, steps, seed)
    return steps


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config/experiment_config.yaml")
    parser.add_argument("--seed", type=int, help="override the configured SUMO seed")
    parser.add_argument("--max-steps", type=int, help="override the configured trip step limit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        run(args.config.resolve(), args.seed, args.max_steps)
    except (FileNotFoundError, RuntimeError, ValueError, KeyError) as error:
        LOGGER.error("Simulation failed: %s", error)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
