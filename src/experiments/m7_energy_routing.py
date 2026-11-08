"""Paired, simulation-only M7 GPS-responsive EV routing smoke experiment."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import math
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

import numpy as np
import yaml

from src.detection.gps_only import apply_temporal_thresholds, extract_gps_features
from src.experiments.m7_routing_controller import RoutingController, energy_metrics

LOGGER = logging.getLogger("m7")
GPS_FIELDS = ("time_s", "vehicle_id", "gps_x_m", "gps_y_m")
CONDITIONS = ("normal_navigation", "unprotected_spoofed", "protected_spoofed")
ATTACKS = ("none", "offset", "jump", "drift")


def compile_network(root: Path) -> Path:
    """Compile the isolated M7 diamond network without touching earlier nets."""
    network = root / "sumo/network/m7.net.xml"
    if network.exists():
        return network
    executable = shutil.which("netconvert")
    if not executable:
        raise RuntimeError("netconvert unavailable; install SUMO and add its bin directory to PATH")
    subprocess.run([executable, "--node-files", str(root / "sumo/network/m7.nod.xml"),
                    "--edge-files", str(root / "sumo/network/m7.edg.xml"),
                    "--output-file", str(network)], check=True, capture_output=True, text=True)
    return network


def validate_network(net_path: Path) -> dict[str, Any]:
    """Check route endpoint and edge connectivity from the compiled SUMO net."""
    import xml.etree.ElementTree as ET
    net = ET.parse(net_path).getroot()
    edge = {node.get("id"): (node.get("from"), node.get("to"))
            for node in net.findall("edge") if node.get("function") != "internal"}
    routes = {"direct": ["approach", "direct_a", "direct_b"],
              "alternate": ["approach", "alternate_a", "alternate_b"]}
    endpoints = {}
    for name, edges in routes.items():
        if any(item not in edge for item in edges):
            raise ValueError(f"{name} route references an edge absent from the M7 network")
        if any(edge[a][1] != edge[b][0] for a, b in zip(edges, edges[1:])):
            raise ValueError(f"{name} route is disconnected")
        endpoints[name] = [edge[edges[0]][0], edge[edges[-1]][1]]
    if endpoints["direct"] != endpoints["alternate"]:
        raise ValueError("M7 route alternatives do not share origin and destination")
    return {"routes": routes, "endpoints": endpoints}


def _attack_fix(x: float, y: float, time_s: float, kind: str,
                attack: dict[str, float], rng: np.random.Generator,
                noise_std_m: float) -> tuple[float, float, int]:
    gx, gy = x + float(rng.normal(0, noise_std_m)), y + float(rng.normal(0, noise_std_m))
    elapsed = time_s - float(attack["onset_s"])
    active = 0 <= elapsed < float(attack["duration_s"])
    if active:
        displacement = (min(float(attack["drift_rate_mps"]) * (elapsed + 1), float(attack["magnitude_m"]))
                        if kind == "drift" else float(attack["magnitude_m"]))
        gy += displacement
    return gx, gy, int(active)


def _battery(traci: Any, vehicle_id: str, parameter: str) -> float | None:
    try:
        raw = traci.vehicle.getParameter(vehicle_id, f"device.battery.{parameter}")
        value = float(raw)
        return value if math.isfinite(value) else None
    except (traci.exceptions.TraCIException, TypeError, ValueError):
        return None


def run_one(root: Path, config: dict[str, Any], *, attack_type: str,
            condition: str, output_dir: Path, seed_override: int | None = None,
            gps_seed_override: int | None = None,
            attack_parameters: dict[str, float] | None = None,
            pair_id: str = "", split: str = "smoke") -> dict[str, Any]:
    """Run one scenario/condition. GPS prefix alone enters the M5 API."""
    import traci
    sim, gps, detector, nav = (config[k] for k in ("simulation", "gps", "detector", "navigation"))
    vehicle_id = sim["vehicle_id"]
    protected = condition == "protected_spoofed"
    attack_kind = attack_type if condition != "normal_navigation" else "none"
    attack = dict(gps["attacks"][attack_kind])
    if attack_parameters:
        attack.update(attack_parameters)
    sim_seed = int(seed_override if seed_override is not None else sim["seed"])
    gps_seed = int(gps_seed_override if gps_seed_override is not None else gps["seed"])
    rng = np.random.default_rng(gps_seed)
    root_output = output_dir / attack_type / condition
    root_output.mkdir(parents=True, exist_ok=False)
    net = compile_network(root)
    command = shutil.which("sumo")
    if not command:
        raise RuntimeError("sumo unavailable; install SUMO and add its bin directory to PATH")
    traci.start([command, "--net-file", str(net), "--route-files", str(root / "sumo/routes/m7.rou.xml"),
                 "--seed", str(sim_seed), "--step-length", str(sim["step_length_s"]),
                 "--end", str(sim["end_s"]), "--no-step-log", "true", "--duration-log.disable", "true"])
    controller = RoutingController(
        {"direct": tuple(nav["direct_reference_xy_m"]),
         "alternate": tuple(nav["alternate_reference_xy_m"])},
        protected, sim["destination_edge"])
    gps_rows: list[dict[str, Any]] = []
    step_rows: list[dict[str, Any]] = []
    label_rows: list[dict[str, Any]] = []
    alerts: list[float] = []
    traveled_edges: list[str] = []
    arrived_at: float | None = None
    attack_observations = 0
    try:
        while traci.simulation.getMinExpectedNumber() > 0:
            traci.simulationStep()
            now = float(traci.simulation.getTime())
            if vehicle_id not in traci.vehicle.getIDList():
                if vehicle_id in traci.simulation.getArrivedIDList():
                    arrived_at = now
                continue
            x, y = traci.vehicle.getPosition(vehicle_id)
            gx, gy, active = _attack_fix(x, y, now, attack_kind, attack, rng,
                                         float(gps["noise_std_m"]))
            attack_observations += active
            gps_rows.append({"time_s": now, "vehicle_id": vehicle_id,
                             "gps_x_m": gx, "gps_y_m": gy})
            label_rows.append({"time_s": now, "vehicle_id": vehicle_id,
                               "attack_type": attack_kind, "attack_active": active})
            # This is M5's existing API. The prefix contains GPS columns only.
            m5_features = extract_gps_features_from_rows(gps_rows)
            prediction = apply_temporal_thresholds(m5_features, detector["thresholds"])[-1]
            alert = bool(prediction["predicted_attack"]) if prediction["eligible"] else False
            if alert:
                alerts.append(now)
            edge = traci.vehicle.getRoadID(vehicle_id)
            proposed, reason = controller.decide(time_s=now, gps_x_m=gx, gps_y_m=gy,
                detector_alert=alert, current_edge=edge, traci=traci, vehicle_id=vehicle_id)
            if edge and edge not in traveled_edges:
                traveled_edges.append(edge)
            charge = _battery(traci, vehicle_id, "chargeLevel")
            capacity = _battery(traci, vehicle_id, "capacity")
            consumed = _battery(traci, vehicle_id, "totalEnergyConsumed")
            regenerated = _battery(traci, vehicle_id, "totalEnergyRegenerated")
            electricity_rate = float(traci.vehicle.getElectricityConsumption(vehicle_id))
            step_rows.append({"time_s": now, "vehicle_id": vehicle_id,
                "m5_alert": int(alert),
                "route_id": traci.vehicle.getRouteID(vehicle_id), "road_id": edge,
                "route_change_reason": reason or "", "speed_mps": traci.vehicle.getSpeed(vehicle_id),
                "m5_eligible": int(bool(prediction["eligible"])),
                "distance_travelled_m": float(traci.vehicle.getDistance(vehicle_id)),
                "battery_charge_wh": charge, "battery_capacity_wh": capacity,
                "energy_total_consumed_wh": consumed, "energy_total_regenerated_wh": regenerated,
                "electricity_wh": electricity_rate * float(sim["step_length_s"]),
                "soc": charge / capacity if charge is not None and capacity else None})
    finally:
        traci.close()
    if not step_rows:
        raise RuntimeError(f"{attack_type}/{condition}: no active-vehicle telemetry was collected")
    _write_csv(root_output / "telemetry.csv", list(step_rows[0]), step_rows)
    _write_csv(root_output / "gps_observations.csv", list(gps_rows[0]), gps_rows)
    _write_csv(root_output / "attack_labels.csv", list(label_rows[0]), label_rows)
    energy = energy_metrics(step_rows)
    if energy["final_battery_charge_wh"] is not None:
        energy["initial_battery_charge_wh"] = float(sim["initial_charge_wh"])
        capacity = next((row["battery_capacity_wh"] for row in step_rows
                         if row["battery_capacity_wh"] is not None), None)
        if capacity:
            energy["initial_soc"] = float(sim["initial_charge_wh"]) / float(capacity)
            energy["soc_change"] = (energy["final_soc"] - energy["initial_soc"]
                                     if energy["final_soc"] is not None else None)
    odometer = [row["distance_travelled_m"] for row in step_rows
                if row["distance_travelled_m"] is not None]
    distance = float(odometer[-1]) if odometer else None
    final_route = step_rows[-1]["route_id"] if step_rows else ""
    summary = {"attack_type": attack_type, "condition": condition,
        "navigation_attack_input": attack_kind, "seed": sim_seed,
        "gps_seed": gps_seed, "pair_id": pair_id, "split": split,
        "attack_parameters": attack, "destination_arrived": arrived_at is not None,
        "travel_time_s": arrived_at, "route_distance_m": distance,
        "executed_edges": traveled_edges, "final_route_id": final_route,
        "reroute_count": len(controller.route_changes), "route_changes": controller.route_changes,
        "detector_alert_count": len(alerts), "detector_alert_times_s": alerts,
        "attack_observations": attack_observations, "protected_fallback_activated": controller.fallback_active,
        "fallback_events": controller.fallback_events,
        "mitigation_success": bool(controller.fallback_active and arrived_at is not None), **energy}
    (root_output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def extract_gps_features_from_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Call unchanged M5 functions through an isolated, truth-free CSV adapter."""
    import tempfile
    with tempfile.TemporaryDirectory(prefix="m7_m5_gps_") as temp:
        path = Path(temp) / "gps.csv"
        _write_csv(path, GPS_FIELDS, rows)
        return extract_gps_features(path)


def _write_csv(path: Path, fields: list[str] | tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    with path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run_smoke(config_path: Path, run_id: str) -> Path:
    """Run the 12 paired Stage 1 scenarios into a new smoke directory."""
    if not run_id or not all(c.isalnum() or c in "-_" for c in run_id):
        raise ValueError("run_id may contain only letters, numbers, hyphens and underscores")
    config_path = config_path.resolve()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    root = config_path.parent.parent.resolve()
    network = compile_network(root)
    net_info = validate_network(network)
    output = (config_path.parent / config["output"]["root"] / config["output"]["smoke_directory"] / run_id).resolve()
    output.mkdir(parents=True, exist_ok=False)
    shutil.copy2(config_path, output / "experiment_config.yaml")
    rows = []
    for attack in ATTACKS:
        for condition in CONDITIONS:
            summary = run_one(root, config, attack_type=attack, condition=condition, output_dir=output / "runs")
            rows.append(summary)
    _write_csv(output / "paired_results.csv", list(rows[0]), rows)
    metadata = {"milestone": "M7 Stage 1 smoke", "run_id": run_id,
        "coordinate_frame": "SUMO local X/Y meters", "time_unit": "seconds",
        "sumo_seed": config["simulation"]["seed"], "paired_conditions": CONDITIONS,
        "attack_types": ATTACKS, "network_validation": net_info,
        "m5_interface": "extract_gps_features(prefix_csv); apply_temporal_thresholds(features, frozen M6 thresholds)",
        "m5_inputs": list(GPS_FIELDS), "m5_excludes": ["SUMO truth", "attack_labels.csv", "future GPS fixes"],
        "protected_fallback": "oracle-assisted: after M5 alert, query SUMO shortest connected route from current edge to destination",
        "battery_model": "SUMO battery device matching M0 configuration; absent values remain null",
        "paired_control": "same network, vehicle/type, departure, initial charge, SUMO/GPS seed and attack parameters per scenario",
        "outputs_are_deterministic_except": ["SUMO ephemeral port/log metadata not included in result files"]}
    (output / "run_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/m7_energy_routing.yaml"))
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print(run_smoke(args.config, args.run_id))


if __name__ == "__main__":
    main()
