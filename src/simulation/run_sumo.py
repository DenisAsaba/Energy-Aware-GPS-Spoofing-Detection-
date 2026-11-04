"""Run the reproducible SUMO electric-vehicle trip and collect ground truth."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import shutil
import sys
from typing import Any

import yaml

LOGGER = logging.getLogger("m0")
TELEMETRY_FIELDS = (
    "time_s", "vehicle_id", "x_m", "y_m", "speed_mps", "acceleration_mps2",
    "heading_deg", "road_id", "route_id", "electricity_wh",
    "energy_consumed_wh", "energy_total_consumed_wh", "energy_total_regenerated_wh",
    "battery_charge_wh", "battery_capacity_wh", "soc",
)


def build_sumo_args(
    command: str,
    network: Path,
    routes: Path,
    settings: dict[str, Any],
    *,
    gui: bool = False,
    keep_open: bool = False,
) -> list[str]:
    """Build SUMO args while preserving the normal close-on-completion default."""
    if keep_open and not gui:
        raise ValueError("--keep-open requires --gui")
    args = [command, "--net-file", str(network), "--route-files", str(routes),
            "--seed", str(settings["seed"]), "--step-length", str(settings["step_length_s"]),
            "--begin", str(settings["begin_s"]), "--end", str(settings["end_s"]),
            "--no-step-log", "true", "--duration-log.disable", "true"]
    if gui:
        # SUMO-GUI otherwise waits for a manual click before TraCI can advance it.
        args.extend(["--start", "--delay", "150"])
        if keep_open:
            # Keep the completed window alive; TraCI close waits until the user exits it.
            args.extend(["--quit-on-end", "false"])
    return args


def _ensure_new_output_paths(csv_path: Path) -> None:
    """Refuse to replace a CSV or its per-run sidecars."""
    candidates = (
        csv_path,
        csv_path.with_name(f"{csv_path.stem}_config.yaml"),
        csv_path.with_name(f"{csv_path.stem}_metadata.yaml"),
    )
    existing = [path for path in candidates if path.exists()]
    if existing:
        raise FileExistsError(f"Refusing to overwrite existing run outputs: {', '.join(map(str, existing))}")


def _battery_value(traci: Any, vehicle_id: str, parameter: str) -> float | None:
    """Return one configured battery-device value, or None if unavailable."""
    try:
        value = traci.vehicle.getParameter(vehicle_id, f"device.battery.{parameter}")
        return float(value) if value not in (None, "") else None
    except traci.exceptions.TraCIException:
        return None


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


def run(
    config_path: Path,
    gui: bool = False,
    output_path: Path | None = None,
    keep_open: bool = False,
) -> Path:
    """Run SUMO and write active-vehicle ground truth to a timestamped CSV."""
    config_path = config_path.resolve()
    with config_path.open(encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    settings = config["simulation"]
    root = config_path.parent
    network = (root / settings["network_file"]).resolve()
    routes = (root / settings["route_file"]).resolve()
    output_dir = (root / settings.get("telemetry_output_dir", "../data/raw")).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if output_path is not None:
        output_path = output_path.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        _ensure_new_output_paths(output_path)
    if not network.is_file() or not routes.is_file():
        raise FileNotFoundError(f"SUMO inputs missing: network={network}, routes={routes}")

    sumo_home = os.environ.get("SUMO_HOME")
    executable = "sumo-gui" if gui else "sumo"
    binary = Path(sumo_home) / "bin" / f"{executable}.exe" if sumo_home else None
    command = str(binary) if binary and binary.is_file() else executable
    traci = _load_traci()
    args = build_sumo_args(command, network, routes, settings, gui=gui, keep_open=keep_open)
    vehicle_id = settings["vehicle_id"]
    steps = 0
    arrived = False
    rows: list[dict[str, object]] = []
    LOGGER.info("Starting SUMO EV run: seed=%s vehicle=%s", settings["seed"], vehicle_id)
    traci.start(args)
    try:
        while traci.simulation.getMinExpectedNumber() > 0:
            traci.simulationStep()
            steps += 1
            now = traci.simulation.getTime()
            arrived = arrived or vehicle_id in traci.simulation.getArrivedIDList()
            if vehicle_id not in traci.vehicle.getIDList():
                continue
            x_m, y_m = traci.vehicle.getPosition(vehicle_id)
            charge = _battery_value(traci, vehicle_id, "chargeLevel")
            capacity = _battery_value(traci, vehicle_id, "capacity")
            rows.append({
                "time_s": now,
                "vehicle_id": vehicle_id,
                "x_m": x_m,
                "y_m": y_m,
                "speed_mps": traci.vehicle.getSpeed(vehicle_id),
                "acceleration_mps2": traci.vehicle.getAcceleration(vehicle_id),
                # SUMO navigational degrees: 0 is north and increases clockwise.
                "heading_deg": traci.vehicle.getAngle(vehicle_id),
                "road_id": traci.vehicle.getRoadID(vehicle_id),
                "route_id": traci.vehicle.getRouteID(vehicle_id),
                # TraCI electricity consumption is Wh/s for this step; integrate over dt.
                "electricity_wh": traci.vehicle.getElectricityConsumption(vehicle_id) * settings["step_length_s"],
                "energy_consumed_wh": _battery_value(traci, vehicle_id, "energyConsumed"),
                "energy_total_consumed_wh": _battery_value(traci, vehicle_id, "totalEnergyConsumed"),
                "energy_total_regenerated_wh": _battery_value(traci, vehicle_id, "totalEnergyRegenerated"),
                "battery_charge_wh": charge,
                "battery_capacity_wh": capacity,
                "soc": charge / capacity if charge is not None and capacity else None,
            })
    finally:
        traci.close()
    if not arrived:
        raise RuntimeError(f"Vehicle {vehicle_id!r} did not complete its trip within the configured simulation end")
    if not rows:
        raise RuntimeError(f"No active-vehicle telemetry was collected for {vehicle_id!r}")
    if output_path is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        output_path = output_dir / f"truth_{vehicle_id}_{stamp}.csv"
        _ensure_new_output_paths(output_path)
    with output_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=TELEMETRY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    shutil.copy2(config_path, output_path.with_name(f"{output_path.stem}_config.yaml"))
    with output_path.with_name(f"{output_path.stem}_metadata.yaml").open("w", encoding="utf-8") as stream:
        yaml.safe_dump({"seed": settings["seed"], "vehicle_id": vehicle_id,
                        "simulation_steps": steps, "telemetry_rows": len(rows),
                        "trip_completed": arrived, "sumo_step_length_s": settings["step_length_s"],
                        "telemetry_file": output_path.name}, stream, sort_keys=False)
    LOGGER.info("Completed EV run: vehicle=%s timesteps=%d telemetry_rows=%d seed=%s csv=%s",
                vehicle_id, steps, len(rows), settings["seed"], output_path)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/experiment_config.yaml"))
    parser.add_argument("--gui", action="store_true", help="launch sumo-gui instead of headless SUMO")
    parser.add_argument("--keep-open", action="store_true", help="keep the completed SUMO-GUI window open until you close it (requires --gui)")
    parser.add_argument("--output", type=Path, help="optional telemetry CSV path (default: timestamped CSV in data/raw)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        run(args.config, gui=args.gui, output_path=args.output, keep_open=args.keep_open)
    except Exception as exc:
        LOGGER.error("SUMO run failed: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
