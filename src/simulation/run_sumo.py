"""Run the reproducible M0 SUMO electric-vehicle trip."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import shutil
import sys
from typing import Any

import yaml

LOGGER = logging.getLogger("m0")


def _load_traci() -> Any:
    """Load TraCI, adding SUMO's tools directory when SUMO_HOME is set."""
    try:
        import traci
        return traci
    except ImportError:
        sumo_home = os.environ.get("SUMO_HOME")
        if sumo_home:
            tools_dir = Path(sumo_home) / "tools"
            if tools_dir.is_dir():
                sys.path.insert(0, str(tools_dir))
                import traci
                return traci
        raise RuntimeError("TraCI is unavailable. Install SUMO and set SUMO_HOME, or install its Python tools.") from None


def run(config_path: Path, gui: bool = False) -> int:
    """Run SUMO until its configured EV trip completes; return steps executed."""
    config_path = config_path.resolve()
    with config_path.open(encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    settings = config["simulation"]
    root = config_path.parent
    network = (root / settings["network_file"]).resolve()
    routes = (root / settings["route_file"]).resolve()
    output_dir = (root / settings["output_dir"]).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if not network.is_file() or not routes.is_file():
        raise FileNotFoundError(f"SUMO inputs missing: network={network}, routes={routes}")

    sumo_home = os.environ.get("SUMO_HOME")
    executable = "sumo-gui" if gui else "sumo"
    binary = Path(sumo_home) / "bin" / f"{executable}.exe" if sumo_home else None
    command = str(binary) if binary and binary.is_file() else executable
    traci = _load_traci()
    args = [command, "--net-file", str(network), "--route-files", str(routes),
            "--seed", str(settings["seed"]), "--step-length", str(settings["step_length_s"]),
            "--begin", str(settings["begin_s"]), "--end", str(settings["end_s"]),
            "--no-step-log", "true", "--duration-log.disable", "true"]
    vehicle_id = settings["vehicle_id"]
    steps = 0
    arrived = False
    LOGGER.info("Starting SUMO EV run: seed=%s vehicle=%s", settings["seed"], vehicle_id)
    traci.start(args)
    try:
        while traci.simulation.getMinExpectedNumber() > 0:
            traci.simulationStep()
            steps += 1
            arrived = arrived or vehicle_id in traci.simulation.getArrivedIDList()
    finally:
        traci.close()
    if not arrived:
        raise RuntimeError(f"Vehicle {vehicle_id!r} did not complete its trip within the configured simulation end")
    shutil.copy2(config_path, output_dir / "experiment_config.yaml")
    with (output_dir / "run_metadata.yaml").open("w", encoding="utf-8") as stream:
        yaml.safe_dump({"seed": settings["seed"], "vehicle_id": vehicle_id,
                        "timesteps": steps, "trip_completed": arrived,
                        "sumo_step_length_s": settings["step_length_s"]}, stream, sort_keys=False)
    LOGGER.info("Completed EV run: vehicle=%s timesteps=%d seed=%s", vehicle_id, steps, settings["seed"])
    return steps


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/experiment_config.yaml"))
    parser.add_argument("--gui", action="store_true", help="launch sumo-gui instead of headless SUMO")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        run(args.config, gui=args.gui)
    except Exception as exc:
        LOGGER.error("SUMO run failed: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
