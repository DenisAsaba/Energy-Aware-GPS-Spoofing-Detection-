"""Reproducible, simulation-only M3 GPS attack data and evaluation workflow.

Coordinates use SUMO's local metric X/Y frame (meters). GPS CSVs contain only
observable measurements; per-sample attack labels and run metadata are stored
in separate files for offline evaluation.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
from pathlib import Path
import shutil
import subprocess
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import yaml

from src.sensors.gps_normal import _read_csv, _validated_rows, evaluate_observations, generate_observations
from src.simulation.run_sumo import run as run_sumo

LOGGER = logging.getLogger("m3")
GPS_FIELDS = ("time_s", "vehicle_id", "gps_x_m", "gps_y_m")
LABEL_FIELDS = ("time_s", "vehicle_id", "attack_type", "attack_id", "attack_active", "attack_intensity")
ATTACK_TYPES = ("offset", "jump", "drift")


def _vector(magnitude: float, direction_deg: float) -> tuple[float, float]:
    """Convert a compass bearing (0 north, clockwise) to SUMO-frame X/Y."""
    angle = math.radians(direction_deg)
    x, y = magnitude * math.sin(angle), magnitude * math.cos(angle)
    return (0.0 if abs(x) < 1e-12 else x, 0.0 if abs(y) < 1e-12 else y)


def _atomic_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {path}")
    with path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def generate_attack(
    truth_path: Path, output_path: Path, *, attack_type: str, settings: dict[str, Any],
    noise_std_m: float, seed: int,
) -> tuple[Path, Path]:
    """Generate one noisy observable GPS dataset plus separate offline labels."""
    if attack_type not in ATTACK_TYPES:
        raise ValueError(f"attack_type must be one of {ATTACK_TYPES}")
    onset = float(settings["onset_s"])
    duration = float(settings["duration_s"])
    if not math.isfinite(onset) or not math.isfinite(duration) or duration <= 0:
        raise ValueError("onset_s must be finite and duration_s must be finite and positive")
    clean_path = output_path.with_name(f".{output_path.stem}.normal.tmp.csv")
    if output_path.resolve() == truth_path.resolve() or clean_path.exists():
        raise ValueError("GPS output must be separate from truth and temporary output must be absent")
    try:
        observations = generate_observations(truth_path, clean_path, noise_std_m=noise_std_m, seed=seed)
        labels: list[dict[str, Any]] = []
        attacked: list[dict[str, Any]] = []
        attack_id = str(settings["attack_id"])
        for sample in observations:
            time_s = float(sample["time_s"])
            elapsed = time_s - onset
            active = 0.0 <= elapsed < duration
            dx = dy = intensity = 0.0
            if active and attack_type == "offset":
                intensity = float(settings["magnitude_m"])
                dx, dy = _vector(intensity, float(settings["direction_deg"]))
            elif active and attack_type == "jump":
                intensity = float(settings["magnitude_m"])
                dx, dy = _vector(intensity, float(settings["direction_deg"]))
            elif active and attack_type == "drift":
                intensity = min(float(settings["rate_mps"]) * (elapsed + 1.0), float(settings["max_displacement_m"]))
                dx, dy = _vector(intensity, float(settings["direction_deg"]))
            attacked.append({**sample,
                "gps_x_m": format(float(sample["gps_x_m"]) + dx, ".15g"),
                "gps_y_m": format(float(sample["gps_y_m"]) + dy, ".15g")})
            labels.append({"time_s": sample["time_s"], "vehicle_id": sample["vehicle_id"],
                "attack_type": attack_type, "attack_id": attack_id,
                "attack_active": int(active), "attack_intensity": format(intensity, ".15g")})
        label_path = output_path.with_name(f"{output_path.stem}_labels.csv")
        _atomic_csv(output_path, GPS_FIELDS, attacked)
        _atomic_csv(label_path, LABEL_FIELDS, labels)
        meta = {"attack_type": attack_type, "attack_id": attack_id, "seed": seed,
                "noise_std_m_per_axis": noise_std_m, "coordinates": "SUMO road-network X/Y meters",
                "onset_s": onset, "duration_s": duration, "truth_file": str(truth_path.resolve()),
                "gps_file": output_path.name, "labels_file": label_path.name,
                "attack_parameters": {key: value for key, value in settings.items() if key != "attack_id"},
                "labels_are_not_detector_inputs": True}
        meta_path = output_path.with_name(f"{output_path.stem}_metadata.yaml")
        if meta_path.exists():
            raise FileExistsError(f"Refusing to overwrite existing output: {meta_path}")
        meta_path.write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")
        return output_path, label_path
    finally:
        clean_path.unlink(missing_ok=True)


def build_alternative_network(project_root: Path) -> Path:
    """Compile only M3's node/edge sources into its separate SUMO network."""
    root = project_root.resolve()
    nodes, edges = root / "sumo/network/m3.nod.xml", root / "sumo/network/m3.edg.xml"
    network = root / "sumo/network/m3.net.xml"
    if not nodes.is_file() or not edges.is_file():
        raise FileNotFoundError(f"M3 network source missing: {nodes} or {edges}")
    if network.exists():
        raise FileExistsError(f"Refusing to overwrite existing M3 network: {network}")
    executable = shutil.which("netconvert")
    if not executable:
        raise RuntimeError("netconvert is unavailable; install SUMO and add its bin directory to PATH")
    subprocess.run([executable, "--node-files", str(nodes), "--edge-files", str(edges),
                    "--output-file", str(network)], check=True, capture_output=True, text=True)
    return network


def validate_alternative_route(network: Path, route_file: Path, route_id: str, expected_edges: list[str]) -> None:
    """Ask SUMO's route checker to verify the M3 route against its own network."""
    sumo = shutil.which("sumo")
    if not sumo:
        raise RuntimeError("sumo executable is unavailable; install SUMO and add its bin directory to PATH")
    result = subprocess.run([sumo, "--net-file", str(network), "--route-files", str(route_file),
                             "--route-steps", "0", "--no-step-log", "true", "--duration-log.disable", "true"],
                            capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"SUMO rejected M3 route: {result.stderr.strip()}")
    root = __import__("xml.etree.ElementTree", fromlist=["ElementTree"]).parse(route_file).getroot()
    route = root.find(f"route[@id='{route_id}']")
    if route is None or route.get("edges", "").split() != expected_edges:
        raise ValueError(f"Route {route_id!r} does not match configured ordered edge list {expected_edges}")


def evaluate_m3(truth_path: Path, gps_path: Path, labels_path: Path, output_dir: Path, name: str) -> dict[str, Any]:
    """Evaluate against matching scenario truth and write M2-style error metrics/plots."""
    metrics, errors = evaluate_observations(truth_path, gps_path)
    gps_rows = _read_csv(gps_path)
    truth = _validated_rows(_read_csv(truth_path), truth_path)
    truth_xy = {(t, v): (x, y) for t, v, x, y in truth}
    gps_xy = {(float(r["time_s"]), r["vehicle_id"]): (float(r["gps_x_m"]), float(r["gps_y_m"])) for r in gps_rows}
    keys = sorted(truth_xy.keys() & gps_xy.keys())
    out = output_dir.resolve(); out.mkdir(parents=True, exist_ok=True)
    metrics["scenario"] = name
    metrics["truth_file"] = str(truth_path.resolve())
    metrics["gps_file"] = str(gps_path.resolve())
    metrics["labels_file"] = str(labels_path.resolve())
    metrics["active_attack_observations"] = sum(row["attack_active"] == "1" for row in _read_csv(labels_path))
    metrics_path = out / f"{name}_metrics.json"
    if metrics_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing evaluation: {metrics_path}")
    metrics_path.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    if keys:
        tx, ty = zip(*(truth_xy[key] for key in keys)); gx, gy = zip(*(gps_xy[key] for key in keys))
        fig, ax = plt.subplots()
        ax.plot(tx, ty, label="Scenario ground truth", marker=".", markersize=3)
        ax.plot(gx, gy, label="Attacked GPS", marker=".", markersize=3)
        ax.set_aspect("equal", adjustable="datalim")
        ax.set(xlabel="SUMO X (m)", ylabel="SUMO Y (m)", title=f"{name}: trajectory comparison")
        ax.legend(); fig.tight_layout(); fig.savefig(out / f"{name}_trajectory.png", dpi=160); plt.close(fig)
        fig, ax = plt.subplots()
        ax.plot([row["time_s"] for row in errors], [row["position_error_m"] for row in errors])
        ax.set(xlabel="Time (s)", ylabel="Horizontal error (m)", title=f"{name}: GPS position error")
        fig.tight_layout(); fig.savefig(out / f"{name}_error_time.png", dpi=160); plt.close(fig)
    return metrics


def run_workflow(config_path: Path, truth_path: Path | None = None, run_id: str | None = None) -> list[dict[str, Any]]:
    """Build route network, simulate route deviation, generate four datasets and evaluate."""
    config_path = config_path.resolve(); config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    root = config_path.parent.parent.resolve(); settings = config["m3"]
    simulation_config = config_path.parent / settings["route_deviation"]["config_file"]
    route_config = yaml.safe_load(simulation_config.read_text(encoding="utf-8"))
    network = (simulation_config.parent / route_config["simulation"]["network_file"]).resolve()
    route_file = (simulation_config.parent / route_config["simulation"]["route_file"]).resolve()
    if not network.exists(): build_alternative_network(root)
    validate_alternative_route(network, route_file, settings["route_deviation"]["route_id"], settings["route_deviation"]["edges"])
    normal_truth = truth_path.resolve() if truth_path else None
    if normal_truth is None:
        files = sorted((root / "data/raw").glob("truth_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files: raise FileNotFoundError("No M1 truth CSV found under data/raw; run M0/M1 first")
        normal_truth = files[0]
    output_dir = (config_path.parent / settings["attacks_output_dir"]).resolve()
    evaluation_dir = (config_path.parent / settings["evaluation_dir"]).resolve()
    if run_id:
        if not all(c.isalnum() or c in "-_" for c in run_id):
            raise ValueError("run_id may contain only letters, numbers, hyphens and underscores")
        output_dir = output_dir / run_id
        evaluation_dir = evaluation_dir / run_id
    seed = int(config["gps_normal"]["seed"]); sigma = float(config["gps_normal"]["noise_std_m"])
    metrics = []
    for kind in ATTACK_TYPES:
        attack_settings = settings["attacks"][kind]
        gps = output_dir / f"gps_{kind}_{normal_truth.stem.removeprefix('truth_')}.csv"
        _, labels = generate_attack(normal_truth, gps, attack_type=kind, settings=attack_settings,
                                    noise_std_m=sigma, seed=seed)
        metrics.append(evaluate_m3(normal_truth, gps, labels, evaluation_dir, kind))

    # Route deviation is a separate physical trip on the valid M3 route. Its own
    # truth is retained separately and its GPS carries offline class labels.
    route_truth = output_dir / "truth_route_deviation.csv"
    if not route_truth.exists():
        run_sumo(simulation_config, output_path=route_truth)
    route_gps = output_dir / "gps_route_deviation.csv"
    route_labels = output_dir / "gps_route_deviation_labels.csv"
    normal = generate_observations(route_truth, route_gps, noise_std_m=sigma,
                                   seed=seed + int(settings["route_deviation"]["gps_seed_offset"]))
    label_rows = [{"time_s": r["time_s"], "vehicle_id": r["vehicle_id"], "attack_type": "route_deviation",
                   "attack_id": "valid_alternative_route", "attack_active": 1, "attack_intensity": "route_alternative"} for r in normal]
    _atomic_csv(route_labels, LABEL_FIELDS, label_rows)
    metadata = {"attack_type": "route_deviation", "route_id": settings["route_deviation"]["route_id"],
                "edges": settings["route_deviation"]["edges"], "network": str(network),
                "truth_file": str(route_truth), "gps_file": route_gps.name, "labels_file": route_labels.name,
                "seed": seed + int(settings["route_deviation"]["gps_seed_offset"]),
                "sumo_seed": route_config["simulation"]["seed"],
                "step_length_s": route_config["simulation"]["step_length_s"],
                "config_file": str(config_path), "route_config_file": str(simulation_config),
                "route_simulation_settings": route_config["simulation"],
                "interpretation": "physical alternative-route trip; not a GPS-driven route-choice causal experiment"}
    metadata_path = output_dir / "gps_route_deviation_metadata.yaml"
    if metadata_path.exists(): raise FileExistsError(f"Refusing to overwrite existing output: {metadata_path}")
    metadata_path.write_text(yaml.safe_dump(metadata, sort_keys=False), encoding="utf-8")
    metrics.append(evaluate_m3(route_truth, route_gps, route_labels, evaluation_dir, "route_deviation"))
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/experiment_config.yaml"))
    parser.add_argument("--truth", type=Path, help="M1 truth CSV for offset/jump/drift; defaults to latest data/raw truth")
    parser.add_argument("--run-id", help="optional isolated output subdirectory; must be new and unique")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    for result in run_workflow(args.config, args.truth, args.run_id): LOGGER.info("M3 result: %s", json.dumps(result, sort_keys=True))


if __name__ == "__main__": main()
