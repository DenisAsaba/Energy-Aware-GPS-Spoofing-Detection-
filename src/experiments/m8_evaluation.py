"""M8 Stage 1 calibration, validation, and isolated smoke comparison.

The workflow creates only reports/m8/<run-id>/ outputs. It does not execute
the reserved final-test group or alter M0-M7 source/configuration/artifacts.
"""

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
from typing import Any
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import yaml

from src.attacks.gps_attacks import generate_attack
from src.detection.gps_only import apply_temporal_thresholds, score_scenario
from src.detection.m8_detector import (
    M8_THRESHOLDS,
    apply_m8_thresholds,
    calibrate_m8_thresholds,
    extract_m8_features,
    prediction_input_contract,
)
from src.sensors.gps_normal import GPS_FIELDS, generate_observations
from src.simulation.run_sumo import run as run_sumo

LOGGER = logging.getLogger("m8")
ATTACK_TYPES = ("offset", "jump", "drift")
DETECTOR_FIELDS = (
    "time_s", "vehicle_id", "gps_x_m", "gps_y_m", "elapsed_s", "displacement_m",
    "estimated_speed_mps", "estimated_heading_deg", "speed_change_mps", "heading_change_deg",
    "signed_acceleration_mps2", "abs_acceleration_mps2", "rolling_displacement_speed_mps",
    "recent_median_speed_mps", "speed_consistency_mps", "eligible", "exclusion_reason",
    "m5_predicted_attack", "m8_raw_anomaly", "m8_raw_rules", "persistence_hits_in_window",
    "predicted_attack",
)
METRIC_FIELDS = (
    "split", "trip_id", "route_group", "sumo_seed", "scenario", "attack_type",
    "attack_magnitude", "attack_duration_s", "attack_onset_s", "attack_end_s", "detector",
    "tp", "fp", "tn", "fn", "precision", "recall", "f1", "false_positive_rate",
    "true_negative_rate", "active_attack_detected", "active_attack_detection_rate",
    "missed_attack_rate", "detection_delay_s", "post_attack_alerts", "alerts_per_trip",
    "eligible_observations", "excluded_observations",
)
PROTECTED_DIRS = (
    "data/raw", "data/processed", "data/attacks", "reports/m2", "reports/m3", "reports/m4",
    "reports/m5", "reports/m6", "reports/m7", "results",
)
PROTECTED_FILES = (
    "config/experiment_config.yaml", "config/m3_route_deviation.yaml", "config/m6_robustness.yaml",
    "config/m7_energy_routing.yaml", "sumo/network/m0.nod.xml", "sumo/network/m0.edg.xml",
    "sumo/network/m0.net.xml", "sumo/network/m3.nod.xml", "sumo/network/m3.edg.xml",
    "sumo/network/m3.net.xml", "sumo/network/m7.nod.xml", "sumo/network/m7.edg.xml",
    "sumo/network/m7.net.xml", "sumo/routes/m0.rou.xml", "sumo/routes/m3_route_deviation.rou.xml",
    "sumo/routes/m7.rou.xml", "src/simulation/run_sumo.py", "src/sensors/gps_normal.py",
    "src/attacks/gps_attacks.py", "src/detection/gps_only.py", "src/detection/gps_spoofing.py",
    "src/experiments/m6_robustness.py", "src/experiments/m7_energy_routing.py",
    "src/experiments/m7_matrix.py", "src/experiments/m7_routing_controller.py",
    "config/m6_robustness.yaml", "config/m7_energy_routing.yaml", "docs/M2_NORMAL_GPS.md",
    "docs/M3_GPS_ATTACKS.md", "docs/M4_GPS_DETECTION.md", "docs/M5_GPS_ONLY_DETECTION.md",
    "docs/M6_ROBUSTNESS_EVALUATION.md", "docs/M7_GPS_AWARE_ENERGY_ROUTING.md",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def protected_manifest(project_root: Path) -> dict[str, str]:
    """Hash the pre-existing M0-M7 inputs and artifacts, excluding M8 outputs."""
    paths = {project_root / item for item in PROTECTED_FILES if (project_root / item).is_file()}
    for relative in PROTECTED_DIRS:
        directory = project_root / relative
        if directory.is_dir():
            paths.update(path for path in directory.rglob("*") if path.is_file())
    return {str(path.relative_to(project_root)): _sha256(path) for path in sorted(paths)}


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite M8 output: {path}")
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, fields: tuple[str, ...] | list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite M8 output: {path}")
    with path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _route_path(project_root: Path, route: dict[str, Any], output: Path) -> Path:
    source = (project_root / "config" / route["route_file"]).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Configured SUMO route file is missing: {source}")
    network = (project_root / "config" / route["network_file"]).resolve()
    if not network.is_file():
        raise FileNotFoundError(f"Configured SUMO network is missing: {network}")
    if not source.name.startswith("m7"):
        return source
    # M7's checked-in route file contains both branches but its vehicle is bound
    # to the direct branch. Select the configured branch in an M8-only copy.
    root = ET.parse(source).getroot()
    vehicle = root.find("vehicle")
    if vehicle is None or root.find(f"route[@id='{route['route_id']}']") is None:
        raise ValueError(f"M7 route file does not contain configured vehicle/route {route['route_id']}")
    vehicle.set("route", str(route["route_id"]))
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite M8 route copy: {output}")
    ET.ElementTree(root).write(output, encoding="utf-8", xml_declaration=True)
    return output


def _simulate_trip(
    project_root: Path, config: dict[str, Any], group: str, trip: dict[str, Any],
    run_dir: Path,
) -> tuple[Path, Path, dict[str, Any]]:
    route = config["routes"][group]
    trip_dir = run_dir / "trips" / str(trip["trip_id"])
    truth = trip_dir / "truth.csv"
    if truth.exists():
        raise FileExistsError(f"Refusing to overwrite M8 trip: {truth}")
    route_file = _route_path(project_root, route, trip_dir / "m8_selected_route.rou.xml")
    settings = {
        "seed": int(trip["seed"]), "step_length_s": float(config["simulation"]["step_length_s"]),
        "begin_s": int(config["simulation"]["begin_s"]), "end_s": int(config["simulation"]["end_s"]),
        "vehicle_id": str(route["vehicle_id"]),
        "network_file": str((project_root / "config" / route["network_file"]).resolve()),
        "route_file": str(route_file.resolve()), "telemetry_output_dir": str((trip_dir / "unused").resolve()),
        "depart_s": 0,
    }
    sim_config_path = trip_dir / "simulation_config.yaml"
    sim_config_path.parent.mkdir(parents=True, exist_ok=True)
    if sim_config_path.exists():
        raise FileExistsError(f"Refusing to overwrite M8 simulation config: {sim_config_path}")
    sim_config_path.write_text(yaml.safe_dump({"simulation": settings}, sort_keys=False), encoding="utf-8")
    run_sumo(sim_config_path, output_path=truth)
    sumo = shutil.which("sumo")
    route_check = "not_run"
    if sumo:
        checked = subprocess.run([sumo, "--net-file", settings["network_file"], "--route-files", str(route_file),
                                  "--route-steps", "0", "--no-step-log", "true",
                                  "--duration-log.disable", "true"], capture_output=True, text=True)
        if checked.returncode:
            raise RuntimeError(f"SUMO route check failed for {trip['trip_id']}: {checked.stderr.strip()}")
        route_check = "passed"
    gps_seed = _stable_seed(int(config["gps"]["seed_offset"]), int(trip["seed"]), str(trip["route_group"]))
    normal_gps = trip_dir / "normal_gps.csv"
    if normal_gps.exists():
        raise FileExistsError(f"Refusing to overwrite M8 GPS data: {normal_gps}")
    generate_observations(truth, normal_gps,
                          noise_std_m=float(config["gps"]["noise_std_m_per_axis"]), seed=gps_seed)
    return truth, normal_gps, {
        "trip_id": trip["trip_id"], "split": group, "route_group": trip["route_group"],
        "sumo_seed": int(trip["seed"]), "gps_seed": gps_seed, "network_file": str(route["network_file"]),
        "route_file": str(route["route_file"]), "route_id": str(route["route_id"]),
        "ordered_edges": list(route["edges"]), "sumo_route_validation": route_check,
        "truth_file_sha256": _sha256(truth), "normal_gps_sha256": _sha256(normal_gps),
        "trip_data_dir": str(trip_dir.relative_to(run_dir)),
    }


def _stable_seed(base: int, seed: int, route_group: str) -> int:
    payload = f"{base}:{seed}:{route_group}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:4], "big")


def _attack_data(
    truth: Path, trip: dict[str, Any], split: str, config: dict[str, Any], run_dir: Path,
    gps_seed: int,
) -> dict[str, dict[str, Any]]:
    results = {}
    for kind in ATTACK_TYPES:
        settings = dict(config["attacks"][kind])
        settings["attack_id"] = f"{trip['trip_id']}_{kind}"
        gps_path = run_dir / "datasets" / str(trip["trip_id"]) / f"gps_{kind}.csv"
        gps_path.parent.mkdir(parents=True, exist_ok=True)
        _, labels_path = generate_attack(
            truth, gps_path, attack_type=kind, settings=settings,
            noise_std_m=float(config["gps"]["noise_std_m_per_axis"]), seed=gps_seed)
        results[kind] = {"gps": gps_path, "labels": labels_path, "settings": settings,
                         "split": split, "trip": trip}
    return results


def _read_labels(path: Path) -> dict[tuple[float, str], dict[str, Any]]:
    labels: dict[tuple[float, str], dict[str, Any]] = {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"time_s", "vehicle_id", "attack_type", "attack_id", "attack_active"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(f"M8 evaluation label file lacks required fields: {path}")
        for row in reader:
            key = (float(row["time_s"]), row["vehicle_id"])
            if key in labels:
                raise ValueError(f"duplicate M8 label key {key} in {path}")
            labels[key] = {**row, "attack_active": int(row["attack_active"])}
    return labels


def _metrics(
    predictions: list[dict[str, Any]], labels: dict[tuple[float, str], dict[str, Any]], *,
    split: str, trip: dict[str, Any], scenario: str, detector: str,
    settings: dict[str, Any] | None,
) -> dict[str, Any]:
    matched = []
    for row in predictions:
        if row.get("predicted_attack") in (None, "") or not row.get("eligible"):
            continue
        key = (float(row["time_s"]), str(row["vehicle_id"]))
        if key in labels:
            matched.append((row, labels[key]))
    tp = sum(int(bool(pred["predicted_attack"])) and int(lab["attack_active"]) == 1 for pred, lab in matched)
    fp = sum(int(bool(pred["predicted_attack"])) and int(lab["attack_active"]) == 0 for pred, lab in matched)
    tn = sum(not bool(pred["predicted_attack"]) and int(lab["attack_active"]) == 0 for pred, lab in matched)
    fn = sum(not bool(pred["predicted_attack"]) and int(lab["attack_active"]) == 1 for pred, lab in matched)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    fpr = fp / (fp + tn) if fp + tn else 0.0
    tnr = tn / (tn + fp) if tn + fp else 0.0
    eligible_prediction = [row for row in predictions if row.get("eligible") and row.get("predicted_attack") not in (None, "")]
    alerts = sum(bool(row["predicted_attack"]) and (i == 0 or not bool(eligible_prediction[i - 1]["predicted_attack"]))
                 for i, row in enumerate(eligible_prediction))
    attack_rows = [(pred, lab) for pred, lab in matched if int(lab["attack_active"]) == 1]
    event_detected = any(bool(pred["predicted_attack"]) for pred, _ in attack_rows)
    delay = None
    post_alerts = 0
    onset = float(settings["onset_s"]) if settings else None
    end = onset + float(settings["duration_s"]) if settings else None
    if onset is not None and end is not None:
        active_hits = [float(pred["time_s"]) for pred, lab in attack_rows if bool(pred["predicted_attack"])]
        delay = min(active_hits) - onset if active_hits else None
        post_alerts = sum(bool(pred["predicted_attack"]) and float(pred["time_s"]) >= end for pred, _ in matched)
    excluded = sum(not bool(row.get("eligible")) for row in predictions)
    return {
        "split": split, "trip_id": trip["trip_id"], "route_group": trip["route_group"],
        "sumo_seed": trip["seed"], "scenario": scenario,
        "attack_type": scenario if scenario in ATTACK_TYPES else "none",
        "attack_magnitude": (settings.get("magnitude_m", settings.get("rate_mps", "")) if settings else ""),
        "attack_duration_s": settings.get("duration_s", "") if settings else "",
        "attack_onset_s": onset if onset is not None else "",
        "attack_end_s": end if end is not None else "", "detector": detector,
        "tp": tp, "fp": fp, "tn": tn, "fn": fn, "precision": precision,
        "recall": recall, "f1": f1, "false_positive_rate": fpr,
        "true_negative_rate": tnr,
        "active_attack_detected": int(event_detected) if scenario != "normal" else "",
        "active_attack_detection_rate": float(event_detected) if scenario != "normal" else "",
        "missed_attack_rate": float(not event_detected) if scenario != "normal" else "",
        "detection_delay_s": delay if delay is not None else "",
        "post_attack_alerts": post_alerts, "alerts_per_trip": alerts,
        "eligible_observations": len(matched), "excluded_observations": excluded,
    }


def _prediction_pair(
    gps: Path, *, window: int, m5_thresholds: dict[str, float],
    m8_thresholds: dict[str, float], persistence: dict[str, int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    features = extract_m8_features(gps, rolling_speed_window=window)
    m5 = apply_temporal_thresholds(features, m5_thresholds)
    m8 = apply_m8_thresholds(features, m8_thresholds, persistence)
    for left, right in zip(m5, m8):
        right["m5_predicted_attack"] = left.get("predicted_attack", "")
    return m5, m8


def _save_predictions(path: Path, predictions: list[dict[str, Any]]) -> None:
    _write_csv(path, DETECTOR_FIELDS, predictions)


def _plot_scenario(
    path: Path, rows: list[dict[str, Any]], labels: dict[tuple[float, str], dict[str, Any]],
    thresholds: dict[str, float], title: str,
) -> None:
    valid = sorted((row for row in rows if row.get("eligible")), key=lambda row: float(row["time_s"]))
    if not valid:
        return
    times = [float(row["time_s"]) for row in valid]
    fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
    panels = (
        ("estimated_speed_mps", "GPS speed (m/s)", thresholds["max_speed_mps"]),
        ("abs_acceleration_mps2", "|GPS acceleration| (m/s²)", thresholds["max_abs_acceleration_mps2"]),
        ("speed_consistency_mps", "Rolling speed consistency (m/s)", thresholds["max_speed_consistency_mps"]),
    )
    for ax, (field, label, threshold) in zip(axes, panels):
        values = [float(row[field]) if row.get(field) is not None else math.nan for row in valid]
        ax.plot(times, values, color="tab:blue", linewidth=1, label=label)
        ax.axhline(threshold, color="tab:orange", linestyle="--", label=f"Calibration threshold {threshold:.3g}")
        active_times = [time for time, row in zip(times, valid)
                        if labels.get((time, str(row["vehicle_id"])), {}).get("attack_active", 0)]
        if active_times:
            ax.axvspan(min(active_times), max(active_times), color="tab:red", alpha=.12, label="Active attack")
        ax.grid(alpha=.2); ax.set_ylabel(label); ax.legend(loc="upper right", fontsize="small")
    axes[-1].step(times, [int(bool(row.get("m5_predicted_attack"))) for row in valid],
                  where="post", label="M5 prediction", color="tab:green", alpha=.8)
    axes[-1].step(times, [int(bool(row.get("predicted_attack"))) for row in valid],
                  where="post", label="M8 prediction", color="tab:purple", alpha=.8)
    axes[-1].set(xlabel="Time (s)", ylabel="Alarm (0/1)", ylim=(-.1, 1.1))
    axes[-1].legend(loc="upper right", fontsize="small")
    fig.suptitle(title)
    fig.tight_layout()
    if path.exists():
        plt.close(fig)
        raise FileExistsError(f"Refusing to overwrite M8 plot: {path}")
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _fit_thresholds(
    calibration_gps: list[Path], config: dict[str, Any], run_dir: Path,
) -> tuple[dict[str, float], dict[str, Any], list[dict[str, Any]]]:
    detector = config["detector"]
    window = int(detector["rolling_speed_window"])
    feature_trips = [extract_m8_features(path, rolling_speed_window=window) for path in calibration_gps]
    thresholds, details = calibrate_m8_thresholds(
        feature_trips, quantile=float(detector["normal_quantile"]),
        calibration_fraction_per_trip=float(detector["calibration_fraction_per_trip"]))
    _write_json(run_dir / "calibration.json", {
        "split": "calibration", "training_sources": [path.stem for path in calibration_gps],
        "thresholds": thresholds, "details": details,
        "m5_thresholds_primary": {name: thresholds[name] for name in (
            "max_speed_mps", "max_speed_change_mps", "max_heading_change_deg")},
        "historical_m6_thresholds_reference_only": {
            "max_speed_mps": 24.06041913028352,
            "max_speed_change_mps": 18.029596454554305,
            "max_heading_change_deg": 108.45527698501837,
        },
    })
    return thresholds, details, feature_trips


def _prepare_trip(
    root: Path, config: dict[str, Any], split: str, trip: dict[str, Any], run_dir: Path,
) -> tuple[Path, Path, dict[str, Any]]:
    truth, gps, meta = _simulate_trip(root, config, split, trip, run_dir)
    record = {**trip, **meta}
    record["gps_seed"] = _stable_seed(int(config["gps"]["seed_offset"]), int(trip["seed"]), str(trip["route_group"]))
    return truth, gps, record


def _validation_candidates(
    config: dict[str, Any], run_dir: Path, trip: dict[str, Any], normal_gps: Path,
    attack_data: dict[str, dict[str, Any]], thresholds: dict[str, float],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, list[dict[str, Any]]], dict[str, dict[tuple[float, str], dict[str, Any]]]]:
    window = int(config["detector"]["rolling_speed_window"])
    m5_thresholds = {key: thresholds[key] for key in (
        "max_speed_mps", "max_speed_change_mps", "max_heading_change_deg")}
    datasets = {"normal": {"gps": normal_gps, "labels": None, "settings": None}}
    datasets.update(attack_data)
    predictions: dict[str, list[dict[str, Any]]] = {}
    m5_predictions: dict[str, list[dict[str, Any]]] = {}
    labels_by_scenario: dict[str, dict[tuple[float, str], dict[str, Any]]] = {}
    # Complete prediction generation for every scenario and policy before labels are opened.
    for scenario, item in datasets.items():
        features = extract_m8_features(item["gps"], rolling_speed_window=window)
        m5_predictions[scenario] = apply_temporal_thresholds(features, m5_thresholds)
        for candidate_index, policy in enumerate(config["detector"]["persistence_candidates"]):
            candidate_key = f"{scenario}__candidate_{candidate_index}"
            predictions[candidate_key] = apply_m8_thresholds(features, thresholds, policy)
    labels_by_scenario["normal"] = {
        (float(row["time_s"]), str(row["vehicle_id"])): {"attack_active": 0}
        for row in m5_predictions["normal"] if row.get("time_s") not in (None, "") and row.get("vehicle_id")
    }
    for scenario, item in attack_data.items():
        labels_by_scenario[scenario] = _read_labels(item["labels"])
    score_rows: list[dict[str, Any]] = []
    for candidate_index, policy in enumerate(config["detector"]["persistence_candidates"]):
        for scenario, item in datasets.items():
            key = f"{scenario}__candidate_{candidate_index}"
            labs = labels_by_scenario[scenario]
            score_rows.append(_metrics(predictions[key], labs, split="validation", trip=trip,
                                       scenario=scenario, detector=f"M8_candidate_{candidate_index}",
                                       settings=item.get("settings")))
    _write_csv(run_dir / "validation_candidate_metrics.csv", list(METRIC_FIELDS), score_rows)
    criterion = config["detector"]["validation_operating_criterion"]
    max_fpr = float(criterion["maximum_normal_false_positive_rate"])
    candidate_summaries = []
    for candidate_index, policy in enumerate(config["detector"]["persistence_candidates"]):
        rows = [row for row in score_rows if row["detector"] == f"M8_candidate_{candidate_index}"]
        normal = next(row for row in rows if row["scenario"] == "normal")
        attacks = [row for row in rows if row["scenario"] in ATTACK_TYPES]
        candidate_summaries.append({
            "candidate_index": candidate_index, "policy": policy,
            "normal_false_positive_rate": float(normal["false_positive_rate"]),
            "active_event_detection_rate": float(np.mean([float(row["active_attack_detection_rate"]) for row in attacks])),
            "alerts_per_trip": float(np.mean([float(row["alerts_per_trip"]) for row in rows])),
            "meets_normal_fpr_criterion": float(normal["false_positive_rate"]) <= max_fpr,
        })
    eligible = [row for row in candidate_summaries if row["meets_normal_fpr_criterion"]]
    if not eligible:
        eligible = candidate_summaries
        selected = min(eligible, key=lambda row: (row["normal_false_positive_rate"],
                                                    -row["active_event_detection_rate"],
                                                    row["alerts_per_trip"], row["candidate_index"]))
        selection_reason = "No candidate met validation normal-FPR criterion; selected lowest validation FPR, then highest event detection."
    else:
        selected = min(eligible, key=lambda row: (-row["active_event_detection_rate"],
                                                   row["alerts_per_trip"], row["candidate_index"]))
        selection_reason = "Among candidates meeting validation normal-FPR criterion, selected highest active event detection, then fewest alerts."
    selected_index = int(selected["candidate_index"])
    selected_policy = dict(config["detector"]["persistence_candidates"][selected_index])
    candidate_manifest = {
        "criterion": criterion, "candidate_summaries": candidate_summaries,
        "selected_candidate_index": selected_index, "selected_persistence": selected_policy,
        "selection_reason": selection_reason,
    }
    _write_json(run_dir / "validation_selection.json", candidate_manifest)
    chosen_predictions = {scenario: predictions[f"{scenario}__candidate_{selected_index}"]
                         for scenario in datasets}
    return candidate_manifest, score_rows, chosen_predictions, labels_by_scenario


def _evaluate_split(
    *, split: str, trip: dict[str, Any], datasets: dict[str, dict[str, Any]],
    thresholds: dict[str, float], persistence: dict[str, int], config: dict[str, Any],
    output_dir: Path, validation_chosen: dict[str, list[dict[str, Any]]] | None = None,
    validation_labels: dict[str, dict[tuple[float, str], dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    rows_out = []
    window = int(config["detector"]["rolling_speed_window"])
    m5_thresholds = {key: thresholds[key] for key in (
        "max_speed_mps", "max_speed_change_mps", "max_heading_change_deg")}
    for scenario, item in datasets.items():
        if split == "validation" and validation_chosen is not None:
            m8_predictions = validation_chosen[scenario]
            features = extract_m8_features(item["gps"], rolling_speed_window=window)
            m5_predictions = apply_temporal_thresholds(features, m5_thresholds)
            labels = validation_labels[scenario]  # type: ignore[index]
            combined = [{**m8row, "m5_predicted_attack": m5row.get("predicted_attack", "")}
                        for m5row, m8row in zip(m5_predictions, m8_predictions)]
            _save_predictions(output_dir / f"{scenario}_predictions.csv", combined)
        else:
            m5_predictions, m8_predictions = _prediction_pair(
                item["gps"], window=window, m5_thresholds=m5_thresholds,
                m8_thresholds=thresholds, persistence=persistence)
            # Persist both prediction streams before opening any attack labels.
            labels = None
            pred_path = output_dir / f"{scenario}_predictions.csv"
            combined = []
            for m5row, m8row in zip(m5_predictions, m8_predictions):
                combined.append({**m8row, "m5_predicted_attack": m5row.get("predicted_attack", "")})
            _save_predictions(pred_path, combined)
            if item.get("labels") is not None:
                labels = _read_labels(item["labels"])
            else:
                labels = {(float(row["time_s"]), str(row["vehicle_id"])): {"attack_active": 0}
                          for row in m5_predictions if row.get("time_s") not in (None, "") and row.get("vehicle_id")}
        # The validation candidate path has already generated and saved all detector outputs
        # before _validation_candidates reads labels for criterion selection.
        metrics = []
        for detector_name, pred in (("M5", m5_predictions), ("M8", m8_predictions)):
            metrics.append(_metrics(pred, labels, split=split, trip=trip, scenario=scenario,
                                    detector=detector_name, settings=item.get("settings")))
        rows_out.extend(metrics)
        merged = [{**m8row, "m5_predicted_attack": m5row.get("predicted_attack", "")}
                  for m5row, m8row in zip(m5_predictions, m8_predictions)]
        _plot_scenario(output_dir / f"{scenario}_timeseries.png", merged, labels,
                       thresholds, f"M8 Stage 1 {split}: {scenario} — {trip['trip_id']}")
    _write_csv(output_dir / "scenario_metrics.csv", list(METRIC_FIELDS), rows_out)
    return rows_out


def _validate_splits(config: dict[str, Any]) -> dict[str, Any]:
    groups: dict[str, set[int]] = {}
    route_groups: dict[str, set[str]] = {}
    seen_trip_ids: set[str] = set()
    route_keys = {str(route["key"]) for route in config["routes"].values()}
    for split in ("calibration", "validation", "smoke", "final_test"):
        trips = config["splits"][split]["trips"]
        if not trips:
            raise ValueError(f"M8 split {split} has no assigned trips")
        groups[split] = {int(row["seed"]) for row in trips}
        route_groups[split] = {str(row["route_group"]) for row in trips}
        for row in trips:
            if row["trip_id"] in seen_trip_ids:
                raise ValueError(f"M8 trip ID reused across splits: {row['trip_id']}")
            seen_trip_ids.add(str(row["trip_id"]))
            if row["route_group"] not in route_keys:
                raise ValueError(f"unknown M8 route group: {row['route_group']}")
    split_names = list(groups)
    for i, left in enumerate(split_names):
        for right in split_names[i + 1:]:
            if groups[left] & groups[right]:
                raise ValueError(f"M8 SUMO seeds overlap between {left} and {right}")
            if route_groups[left] & route_groups[right]:
                raise ValueError(f"M8 route groups overlap between {left} and {right}")
    m7_test_seeds = {803, 804}
    if groups["smoke"] & m7_test_seeds or groups["final_test"] & m7_test_seeds:
        raise ValueError("M8 smoke/final-test seed assignment reuses M7 final-test seeds")
    return {split: {"sumo_seeds": sorted(groups[split]), "route_groups": sorted(route_groups[split]),
                    "trip_ids": [row["trip_id"] for row in config["splits"][split]["trips"]]}
            for split in split_names}


def run_workflow(config_path: Path, run_id: str) -> dict[str, Any]:
    """Run M8 calibration, validation-based persistence selection, and smoke only."""
    if not run_id or not all(char.isalnum() or char in "-_" for char in run_id):
        raise ValueError("run_id may contain only letters, numbers, hyphens, and underscores")
    config_path = config_path.resolve()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    root = config_path.parent.parent.resolve()
    output_root = (config_path.parent / config["outputs"]["root"]).resolve()
    run_dir = output_root / run_id
    if run_dir.exists():
        raise FileExistsError(f"M8 run ID already exists: {run_dir}")
    split_manifest = _validate_splits(config)
    pre_manifest = protected_manifest(root)
    run_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(config_path, run_dir / "m8_detector.yaml")
    run_metadata: dict[str, Any] = {
        "milestone": "M8 Stage 1", "run_id": run_id,
        "prediction_contract": prediction_input_contract(),
        "split_manifest": split_manifest,
        "reserved_final_test_executed": False,
        "m7_final_test_seed_reuse": False,
        "protected_m0_m7_before": {"file_count": len(pre_manifest),
                                    "manifest_sha256": hashlib.sha256(json.dumps(pre_manifest, sort_keys=True).encode()).hexdigest()},
        "normal_traffic_variation_limitation": (
            "Available routes provide a straight M0 calibration route, a bent two-edge M3 validation route, "
            "and an M7 alternate-branch smoke route. There is no varied traffic demand or broad stop/turn library; "
            "the Stage 1 smoke is a pipeline check, not representative normal-driving validation."
        ),
    }
    (run_dir / "metadata.json").write_text(json.dumps(run_metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    calibration_gps = []
    calibration_records = []
    for trip in config["splits"]["calibration"]["trips"]:
        _, gps, meta = _prepare_trip(root, config, "calibration", trip, run_dir)
        calibration_gps.append(gps)
        calibration_records.append(meta)
    thresholds, calibration_details, _ = _fit_thresholds(calibration_gps, config, run_dir)

    validation_trip = config["splits"]["validation"]["trips"][0]
    validation_truth, validation_gps, validation_meta = _prepare_trip(root, config, "validation", validation_trip, run_dir)
    validation_attacks = _attack_data(
        validation_truth, validation_trip, "validation", config, run_dir, int(validation_meta["gps_seed"]))
    validation_datasets = {"normal": {"gps": validation_gps, "labels": None, "settings": None},
                           **validation_attacks}
    selection, validation_candidate_rows, chosen, validation_labels = _validation_candidates(
        config, run_dir, validation_trip, validation_gps, validation_attacks, thresholds)
    validation_rows = _evaluate_split(
        split="validation", trip=validation_trip, datasets=validation_datasets,
        thresholds=thresholds, persistence=selection["selected_persistence"], config=config,
        output_dir=run_dir / "validation", validation_chosen=chosen, validation_labels=validation_labels)

    smoke_trip = config["splits"]["smoke"]["trips"][0]
    smoke_truth, smoke_gps, smoke_meta = _prepare_trip(root, config, "smoke", smoke_trip, run_dir)
    smoke_attacks = _attack_data(smoke_truth, smoke_trip, "smoke", config, run_dir, int(smoke_meta["gps_seed"]))
    smoke_datasets = {"normal": {"gps": smoke_gps, "labels": None, "settings": None}, **smoke_attacks}
    smoke_rows = _evaluate_split(
        split="smoke", trip=smoke_trip, datasets=smoke_datasets, thresholds=thresholds,
        persistence=selection["selected_persistence"], config=config, output_dir=run_dir / "smoke")

    # Combined run table includes validation selection diagnostics and smoke comparison.
    _write_csv(run_dir / "validation_metrics.csv", list(METRIC_FIELDS), validation_rows)
    _write_csv(run_dir / "smoke_metrics.csv", list(METRIC_FIELDS), smoke_rows)
    _write_json(run_dir / "run_summary.json", {
        "selected_persistence": selection["selected_persistence"],
        "validation_selection": selection,
        "validation_metrics": validation_rows,
        "smoke_metrics": smoke_rows,
        "thresholds": thresholds,
        "m5_calibration_method": "M5 calibrate_temporal_thresholds called per normal calibration trip; pooled quantiles use only each trip's chronological calibration prefix.",
        "m5_historical_m6_thresholds_are_reference_only": True,
        "post_attack_alerts_count_as_active_detection": False,
        "smoke_is_final_test": False,
        "attack_intervals": "[onset_s, onset_s + duration_s)",
        "calibration_trip_manifests": calibration_records,
        "validation_trip_manifest": validation_meta,
        "smoke_trip_manifest": smoke_meta,
        "limitations": [
            "One validation trip and one smoke trip do not support generalization claims.",
            "M8 Stage 1 smoke does not run the reserved final-test split.",
            "Current networks do not provide broad traffic, stop, route-change, and turn variation.",
            "GPS-only motion features cannot identify a kinematically smooth constant translation without an external reference.",
        ],
    })
    post_manifest = protected_manifest(root)
    changed = sorted(path for path in set(pre_manifest) | set(post_manifest)
                     if pre_manifest.get(path) != post_manifest.get(path))
    preservation = {
        "protected_file_count_before": len(pre_manifest), "protected_file_count_after": len(post_manifest),
        "protected_manifest_sha256_before": hashlib.sha256(json.dumps(pre_manifest, sort_keys=True).encode()).hexdigest(),
        "protected_manifest_sha256_after": hashlib.sha256(json.dumps(post_manifest, sort_keys=True).encode()).hexdigest(),
        "changed_protected_paths": changed,
        "m0_m7_preserved": not changed,
    }
    run_metadata.update({"thresholds": thresholds, "selected_persistence": selection["selected_persistence"],
                         "m5_calibration": calibration_details, "validation_trip": validation_meta,
                         "smoke_trip": smoke_meta, "preservation": preservation})
    # Metadata is deliberately excluded from deterministic output comparisons because run_id differs.
    (run_dir / "metadata.json").write_text(json.dumps(run_metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if changed:
        raise RuntimeError(f"Protected M0-M7 files changed during M8: {changed}")
    LOGGER.info("M8 Stage 1 complete: run_id=%s selected_persistence=%s smoke_rows=%d",
                run_id, selection["selected_persistence"], len(smoke_rows))
    return {"run_dir": run_dir, "summary": run_dir / "run_summary.json",
            "selected_persistence": selection["selected_persistence"],
            "validation_metrics": validation_rows, "smoke_metrics": smoke_rows,
            "preservation": preservation}


def compare_runs(first: Path, second: Path) -> dict[str, Any]:
    """Compare deterministic CSV/JSON/PNG content, excluding run metadata."""
    excluded = {"metadata.json"}
    files_a = {p.relative_to(first).as_posix(): p for p in first.rglob("*")
               if p.is_file() and p.suffix.lower() in {".csv", ".json", ".png"} and p.name not in excluded}
    files_b = {p.relative_to(second).as_posix(): p for p in second.rglob("*")
               if p.is_file() and p.suffix.lower() in {".csv", ".json", ".png"} and p.name not in excluded}
    missing = sorted(set(files_a) ^ set(files_b))
    different = sorted(path for path in set(files_a) & set(files_b)
                       if _sha256(files_a[path]) != _sha256(files_b[path]))
    return {"file_count_first": len(files_a), "file_count_second": len(files_b),
            "matched_identical_files": len(set(files_a) & set(files_b)) - len(different),
            "missing_paths": missing, "different_paths": different,
            "identical": not missing and not different}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/m8_detector.yaml"))
    parser.add_argument("--run-id", required=True, help="new isolated reports/m8 run ID")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        result = run_workflow(args.config, args.run_id)
        LOGGER.info("M8 outputs: %s", result["run_dir"])
    except Exception as exc:
        LOGGER.error("M8 workflow failed: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
