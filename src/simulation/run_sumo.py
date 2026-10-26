"""Run the reproducible SUMO EV trip and export per-step ground-truth telemetry."""

from __future__ import annotations

import argparse
import csv
import logging
import math
import os
from pathlib import Path
import shutil
import sys
from typing import Any

import traci
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOGGER = logging.getLogger("ev_sumo")
CSV_FIELDS = [
    "time_s",
    "trip_id",
    "vehicle_id",
    "seed",
    "x_m",
    "y_m",
    "speed_mps",
    "acceleration_mps2",
    "heading_deg",
    "road_id",
    "route_id",
    "battery_charge_wh",
    "battery_capacity_wh",
    "soc",
    "energy_consumed_wh",
    "total_energy_consumed_wh",
    "total_energy_regenerated_wh",
    "electricity_consumption_wh_per_s",
]
NUMERIC_FIELDS = (
    "time_s",
    "seed",
    "x_m",
    "y_m",
    "speed_mps",
    "acceleration_mps2",
    "heading_deg",
    "battery_charge_wh",
    "battery_capacity_wh",
    "soc",
    "energy_consumed_wh",
    "total_energy_consumed_wh",
    "total_energy_regenerated_wh",
    "electricity_consumption_wh_per_s",
)
REQUIRED_NUMERIC_FIELDS = (
    "time_s",
    "seed",
    "x_m",
    "y_m",
    "speed_mps",
    "acceleration_mps2",
    "heading_deg",
)
BATTERY_PARAMETERS = {
    "battery_charge_wh": "device.battery.chargeLevel",
    "battery_capacity_wh": "device.battery.capacity",
    "energy_consumed_wh": "device.battery.energyConsumed",
    "total_energy_consumed_wh": "device.battery.totalEnergyConsumed",
    "total_energy_regenerated_wh": "device.battery.totalEnergyRegenerated",
}


def load_config(config_path: Path) -> dict[str, Any]:
    """Load the experiment YAML and return its simulation settings."""
    with config_path.open(encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    if not isinstance(config, dict) or not isinstance(config.get("simulation"), dict):
        raise ValueError(f"Missing simulation settings in {config_path}")
    return config["simulation"]


def resolve_path(value: str | Path) -> Path:
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


def _optional_battery_parameter(vehicle_id: str, parameter: str) -> float | None:
    """Return a documented battery-device parameter, or None if unavailable."""
    try:
        raw_value = traci.vehicle.getParameter(vehicle_id, parameter)
        return float(raw_value)
    except (traci.TraCIException, ValueError):
        return None


def collect_vehicle_record(vehicle_id: str, trip_id: str, seed: int) -> dict[str, Any]:
    """Read one post-step record from TraCI for a vehicle currently in the network."""
    x_m, y_m = traci.vehicle.getPosition(vehicle_id)
    record: dict[str, Any] = {
        "time_s": traci.simulation.getTime(),
        "trip_id": trip_id,
        "vehicle_id": vehicle_id,
        "seed": seed,
        "x_m": x_m,
        "y_m": y_m,
        "speed_mps": traci.vehicle.getSpeed(vehicle_id),
        "acceleration_mps2": traci.vehicle.getAcceleration(vehicle_id),
        "heading_deg": traci.vehicle.getAngle(vehicle_id),
        "road_id": traci.vehicle.getRoadID(vehicle_id),
        "route_id": traci.vehicle.getRouteID(vehicle_id),
    }
    for column, parameter in BATTERY_PARAMETERS.items():
        record[column] = _optional_battery_parameter(vehicle_id, parameter)
    try:
        # SUMO TraCI reports this rate in Wh/s for the current simulation step.
        record["electricity_consumption_wh_per_s"] = traci.vehicle.getElectricityConsumption(vehicle_id)
    except traci.TraCIException:
        record["electricity_consumption_wh_per_s"] = None

    charge = record["battery_charge_wh"]
    capacity = record["battery_capacity_wh"]
    record["soc"] = charge / capacity if charge is not None and capacity is not None and capacity > 0 else None
    return record


def validate_telemetry_csv(csv_path: Path) -> tuple[int, float]:
    """Validate schema, finite numeric values, and strictly increasing per-vehicle time."""
    row_count = 0
    last_time_by_vehicle: dict[str, float] = {}
    with csv_path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != CSV_FIELDS:
            raise ValueError(f"Unexpected telemetry CSV columns: {reader.fieldnames}")
        for line_number, row in enumerate(reader, start=2):
            row_count += 1
            for name in ("trip_id", "vehicle_id", "road_id", "route_id"):
                if not row[name]:
                    raise ValueError(f"Missing {name} on CSV line {line_number}")
            for name in REQUIRED_NUMERIC_FIELDS:
                if not row[name]:
                    raise ValueError(f"Missing required numeric field {name} on CSV line {line_number}")
            for name in NUMERIC_FIELDS:
                if row[name] and not math.isfinite(float(row[name])):
                    raise ValueError(f"Non-finite numeric field {name} on CSV line {line_number}")
            time_s = float(row["time_s"])
            vehicle_id = row["vehicle_id"]
            if time_s <= last_time_by_vehicle.get(vehicle_id, -math.inf):
                raise ValueError(f"Timestamps are not strictly increasing for {vehicle_id} at CSV line {line_number}")
            last_time_by_vehicle[vehicle_id] = time_s
    if row_count == 0:
        raise ValueError(f"Telemetry CSV contains no vehicle rows: {csv_path}")
    return row_count, max(last_time_by_vehicle.values())


def run(
    config_path: Path,
    seed: int | None = None,
    max_steps: int | None = None,
    output_path: Path | None = None,
) -> int:
    """Run until the configured EV completes and write per-step telemetry."""
    settings = load_config(config_path)
    vehicle_id = str(settings["vehicle_id"])
    seed = int(settings["seed"] if seed is None else seed)
    max_steps = int(settings["max_steps"] if max_steps is None else max_steps)
    sumocfg = resolve_path(settings["config_file"])
    output_path = resolve_path(output_path or settings.get("output_file", "data/raw/truth.csv"))
    if not sumocfg.is_file():
        raise FileNotFoundError(f"SUMO configuration not found: {sumocfg}")
    if max_steps < 1:
        raise ValueError("max_steps must be positive")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    trip_id = f"{vehicle_id}_seed_{seed}"
    command = [sumo_binary(), "-c", str(sumocfg), "--seed", str(seed), "--no-step-log", "true"]
    steps = 0
    completed = False
    LOGGER.info("Starting SUMO with seed=%d vehicle_id=%s", seed, vehicle_id)
    try:
        traci.start(command)
        with output_path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
            writer.writeheader()
            while traci.simulation.getMinExpectedNumber() > 0 and steps < max_steps:
                traci.simulationStep()
                steps += 1
                if vehicle_id in traci.vehicle.getIDList():
                    writer.writerow(collect_vehicle_record(vehicle_id, trip_id, seed))
                elif traci.simulation.getMinExpectedNumber() == 0:
                    completed = True
        if not completed:
            raise RuntimeError(
                f"Vehicle {vehicle_id} did not complete within {max_steps} steps "
                f"(simulation reports {traci.simulation.getMinExpectedNumber()} expected vehicles)"
            )
    finally:
        if traci.isLoaded():
            traci.close()

    row_count, final_time_s = validate_telemetry_csv(output_path)
    LOGGER.info(
        "Trip completed: vehicle_id=%s timesteps=%d seed=%d telemetry_rows=%d final_time_s=%.3f output=%s",
        vehicle_id,
        steps,
        seed,
        row_count,
        final_time_s,
        output_path,
    )
    return steps


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config/experiment_config.yaml")
    parser.add_argument("--seed", type=int, help="override the configured SUMO seed")
    parser.add_argument("--max-steps", type=int, help="override the configured trip step limit")
    parser.add_argument("--output", type=Path, help="telemetry CSV path (default: data/raw/truth.csv)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        run(args.config.resolve(), args.seed, args.max_steps, args.output)
    except (FileNotFoundError, RuntimeError, ValueError, KeyError, OSError) as error:
        LOGGER.error("Simulation failed: %s", error)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
