"""M6 multi-seed, multi-route, multi-intensity detector evaluation.

M4 is evaluated as its existing oracle-assisted residual rule. M5 predictions
use only GPS observations and the existing GPS-only temporal rule. All M6
inputs and reports are isolated under a fresh reports/m6/<run-id> directory.
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
from typing import Any, Iterable
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import yaml

from src.attacks.gps_attacks import generate_attack
from src.detection.gps_only import (
    FEATURE_THRESHOLDS, PREDICTION_FIELDS as M5_FIELDS, _read_labels as m5_read_labels,
    apply_temporal_thresholds,
    extract_gps_features, score_scenario,
)
from src.detection.gps_spoofing import (
    PREDICTION_FIELDS as M4_FIELDS, _read_labels as m4_read_labels,
    classification_metrics, predict_position_residuals,
)
from src.sensors.gps_normal import evaluate_observations, generate_observations
from src.simulation.run_sumo import run as run_sumo

LOGGER = logging.getLogger("m6")
METRICS = ("precision", "recall", "f1", "false_positive_rate", "accuracy", "detection_delay_s")
COUNT_FIELDS = ("true_positive", "false_positive", "true_negative", "false_negative")
SCORE_FIELDS = (
    "experiment_id", "detector", "split", "scenario", "attack_type", "attack_intensity",
    "attack_intensity_value", "attack_intensity_unit", "attack_duration_s", "seed", "route",
    "threshold_value", *COUNT_FIELDS, "precision", "recall", "f1", "false_positive_rate",
    "accuracy", "detection_delay_s", "matched_observations", "unmatched_prediction_records",
    "unmatched_label_records", "unmatched_gps_without_truth", "unmatched_truth_without_gps",
    "excluded_observations", "excluded_labeled_observations",
)


def _safe_id(value: str) -> str:
    if not value or not all(char.isalnum() or char in "-_" for char in value):
        raise ValueError("run_id may contain only letters, numbers, hyphens, and underscores")
    return value


def build_experiment_matrix(config: dict[str, Any], *, smoke: bool = False) -> list[dict[str, Any]]:
    """Return deterministic experiment records; split membership is trip-level."""
    routes = config["routes"]
    seeds = config["seeds"]
    if smoke:
        routes = {"m0_route": routes["m0_route"]}
        seeds = {"calibration": [901], "validation": [902], "test": [903]}
    seen: set[str] = set()
    matrix: list[dict[str, Any]] = []
    for split in ("calibration", "validation", "test"):
        for route_name in routes:
            for seed in seeds[split]:
                trip_id = f"{route_name}_seed{int(seed)}"
                experiment_id = f"normal_{split}_{trip_id}"
                if experiment_id in seen:
                    raise ValueError(f"duplicate experiment identifier: {experiment_id}")
                seen.add(experiment_id)
                matrix.append({"experiment_id": experiment_id, "trip_id": trip_id, "split": split,
                               "scenario": "normal", "attack_type": "none", "attack_intensity": "none",
                               "attack_intensity_value": 0.0, "attack_intensity_unit": "none",
                               "attack_duration_s": 0.0, "seed": int(seed), "route": route_name,
                               "gps_seed": _stable_seed(int(config["gps_seed_offset"]), int(seed), route_name)})
    attacks = config["attack_matrix"]
    if smoke:
        attacks = {}
        for kind in ("offset", "jump", "drift"):
            values = config["attack_matrix"][kind]
            intensity_key = "rates_mps" if kind == "drift" else "magnitudes_m"
            attacks[kind] = {"onset_s": values["onset_s"], intensity_key: [values[intensity_key][0]],
                             "durations_s": [values["durations_s"][0]]}
    for route_name in routes:
        for seed in seeds["test"]:
            trip_id = f"{route_name}_seed{int(seed)}"
            for attack_type in ("offset", "jump", "drift"):
                settings = attacks[attack_type]
                onset = float(settings["onset_s"])
                if attack_type == "offset":
                    intensities = [(float(v), "m") for v in settings["magnitudes_m"]]
                elif attack_type == "jump":
                    intensities = [(float(v), "m") for v in settings["magnitudes_m"]]
                else:
                    intensities = [(float(v), "mps") for v in settings["rates_mps"]]
                for intensity, unit in intensities:
                    for duration in map(float, settings["durations_s"]):
                        token = f"{intensity:g}{unit}_{duration:g}s"
                        experiment_id = f"{attack_type}_{token}_{trip_id}"
                        if experiment_id in seen:
                            raise ValueError(f"duplicate experiment identifier: {experiment_id}")
                        seen.add(experiment_id)
                        matrix.append({"experiment_id": experiment_id, "trip_id": trip_id, "split": "test",
                                       "scenario": attack_type, "attack_type": attack_type,
                                       "attack_intensity": f"{intensity:g} {unit}",
                                       "attack_intensity_value": intensity, "attack_intensity_unit": unit,
                                       "attack_duration_s": duration, "attack_onset_s": onset,
                                       "seed": int(seed), "route": route_name,
                                       "gps_seed": _stable_seed(int(config["gps_seed_offset"]), int(seed), route_name)})
    return matrix


def validate_routes(project_root: Path, config: dict[str, Any]) -> dict[str, Any]:
    """Ask the installed SUMO binary to load every configured network/route pair."""
    executable = shutil.which("sumo")
    if not executable:
        raise RuntimeError("sumo is unavailable; install SUMO and add its bin directory to PATH")
    verified = {}
    for route_name, route in config["routes"].items():
        net = (project_root / route["network_file"]).resolve()
        rou = (project_root / route["route_file"]).resolve()
        if not net.is_file() or not rou.is_file():
            raise FileNotFoundError(f"missing SUMO route inputs for {route_name}: {net}, {rou}")
        result = subprocess.run([executable, "--net-file", str(net), "--route-files", str(rou),
                                 "--route-steps", "0", "--no-step-log", "true",
                                 "--duration-log.disable", "true"], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(f"SUMO rejected route {route_name}: {result.stderr.strip()}")
        root = ET.parse(rou).getroot()
        element = root.find(f"route[@id='{route['route_id']}']")
        if element is None or element.get("edges", "").split() != list(route["edges"]):
            raise ValueError(f"route {route_name} does not match configured ID/edge sequence")
        verified[route_name] = {"network_file": str(net), "route_file": str(rou),
                                "route_id": route["route_id"], "edges": list(route["edges"]),
                                "sumo_route_check": "passed"}
    return verified


def _write_csv(path: Path, fields: Iterable[str], rows: Iterable[dict[str, Any]]) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite M6 output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite M6 output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def _stable_seed(base: int, seed: int, route: str) -> int:
    digest = hashlib.sha256(f"{base}:{seed}:{route}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big")


def _protected_snapshot(project_root: Path) -> dict[str, Any]:
    """Hash prior milestone inputs/results that the M6 writer must leave intact."""
    protected_dirs = ("data/raw", "data/processed", "data/attacks", "reports/m2", "reports/m3",
                      "reports/m4", "reports/m5", "results")
    protected_files = (
        "config/experiment_config.yaml", "config/m3_route_deviation.yaml",
        "sumo/network/m0.nod.xml", "sumo/network/m0.edg.xml", "sumo/network/m0.net.xml",
        "sumo/network/m3.nod.xml", "sumo/network/m3.edg.xml", "sumo/network/m3.net.xml",
        "sumo/routes/m0.rou.xml", "sumo/routes/m3_route_deviation.rou.xml",
        "src/simulation/run_sumo.py", "src/simulation/demo_m0_m1.py",
        "src/sensors/gps_normal.py", "src/attacks/gps_attacks.py",
        "src/detection/gps_spoofing.py", "src/detection/gps_only.py",
        "docs/M2_NORMAL_GPS.md", "docs/M3_GPS_ATTACKS.md",
        "docs/M4_GPS_DETECTION.md", "docs/M5_GPS_ONLY_DETECTION.md",
    )
    paths = {path for relative in protected_files if (path := project_root / relative).is_file()}
    for relative in protected_dirs:
        directory = project_root / relative
        if directory.is_dir():
            paths.update(path for path in directory.rglob("*") if path.is_file())
    manifest = {str(path.relative_to(project_root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(paths)}
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"file_count": len(manifest), "manifest_sha256": hashlib.sha256(canonical).hexdigest(),
            "manifest": manifest}


def _attack_settings(record: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    kind, intensity, duration = record["attack_type"], record["attack_intensity_value"], record["attack_duration_s"]
    common = {"attack_id": record["experiment_id"], "onset_s": record["attack_onset_s"],
              "duration_s": duration, "direction_deg": float(config["attack_direction_deg"])}
    if kind in ("offset", "jump"):
        common["magnitude_m"] = intensity
    else:
        common["rate_mps"] = intensity
        common["max_displacement_m"] = intensity * duration
    return common


def _delay(predictions: Iterable[dict[str, Any]], labels: dict[tuple[float, str], int]) -> float | None:
    active = [key for key, value in labels.items() if value == 1]
    if not active:
        return None
    first = min(key[0] for key in active)
    predicted = {(float(row["time_s"]), str(row["vehicle_id"])): row.get("predicted_attack")
                 for row in predictions if row.get("predicted_attack") not in (None, "")}
    hits = [key[0] for key in active if predicted.get(key) in (1, "1")]
    return min(hits) - first if hits else None


def _calibrate_thresholds(trips: list[dict[str, Any]], settings: dict[str, Any]) -> tuple[float, dict[str, float], dict[str, Any]]:
    """Pool only normal training-trip values, preserving the M4/M5 rule forms."""
    m4_values: list[float] = []
    m5_values: dict[str, list[float]] = {feature: [] for feature in FEATURE_THRESHOLDS}
    counts: dict[str, int] = {feature: 0 for feature in FEATURE_THRESHOLDS}
    for trip in trips:
        _, residual_rows = evaluate_observations(trip["truth"], trip["gps"])
        m4_values.extend(float(row["position_error_m"]) for row in residual_rows)
        for row in extract_gps_features(trip["gps"]):
            if row["eligible"]:
                for feature in FEATURE_THRESHOLDS:
                    if row[feature] is not None:
                        m5_values[feature].append(float(row[feature]))
                        counts[feature] += 1
    if len(m4_values) < 2 or any(len(values) < 2 for values in m5_values.values()):
        raise ValueError("insufficient normal calibration data to fit M4/M5 thresholds")
    m4_threshold = float(np.quantile(m4_values, float(settings["m4_normal_quantile"])))
    m5_thresholds = {FEATURE_THRESHOLDS[feature]: float(np.quantile(values, float(settings["m5_normal_quantile"])))
                     for feature, values in m5_values.items()}
    return m4_threshold, m5_thresholds, {
        "training_trip_ids": [trip["trip_id"] for trip in trips],
        "m4_normal_residual_observations": len(m4_values), "m4_quantile": settings["m4_normal_quantile"],
        "m4_threshold_m": m4_threshold,
        "m5_normal_feature_observations": counts,
        "m5_quantile": settings["m5_normal_quantile"], "m5_thresholds": m5_thresholds,
        "method": "NumPy linear quantile over pooled normal calibration trips; attack/validation/test data excluded",
    }


def _record_metrics(record: dict[str, Any], detector: str, metrics: dict[str, Any], *,
                    threshold: float | None, unmatched_truth: int = 0, unmatched_gps: int = 0,
                    excluded: int = 0, excluded_labels: int = 0, delay: float | None = None) -> dict[str, Any]:
    result = {key: record.get(key, "") for key in ("experiment_id", "split", "scenario", "attack_type",
              "attack_intensity", "attack_intensity_value", "attack_intensity_unit", "attack_duration_s", "seed", "route")}
    result.update({"detector": detector, "threshold_value": threshold,
                   **{field: metrics.get(field, 0) for field in COUNT_FIELDS},
                   **{field: metrics.get(field, 0.0) for field in ("precision", "recall", "f1", "false_positive_rate", "accuracy")},
                   "detection_delay_s": delay,
                   "matched_observations": metrics.get("matched_observations", 0),
                   "unmatched_prediction_records": metrics.get("unmatched_prediction_records", 0),
                   "unmatched_label_records": metrics.get("unmatched_label_records", 0),
                   "unmatched_gps_without_truth": unmatched_gps,
                   "unmatched_truth_without_gps": unmatched_truth,
                   "excluded_observations": excluded, "excluded_labeled_observations": excluded_labels})
    return result


def _evaluate(record: dict[str, Any], truth: Path, gps: Path, labels_path: Path | None,
              m4_threshold: float, m5_thresholds: dict[str, float], output: Path) -> list[dict[str, Any]]:
    m4_predictions, match = predict_position_residuals(truth, gps, m4_threshold)
    features = extract_gps_features(gps)
    m5_predictions = apply_temporal_thresholds(features, m5_thresholds)
    _write_csv(output / f"{record['experiment_id']}_m4_predictions.csv", M4_FIELDS, m4_predictions)
    _write_csv(output / f"{record['experiment_id']}_m5_predictions.csv", M5_FIELDS, m5_predictions)
    # Both detectors finish prediction before attack labels are opened for scoring.
    labels = ({key: 0 for key in ((float(row["time_s"]), row["vehicle_id"]) for row in m4_predictions)}
              if labels_path is None else m4_read_labels(labels_path))
    m4_metrics = classification_metrics(m4_predictions, labels)
    m4_metrics["unmatched_gps_without_truth"] = match["unmatched_observations"]
    m4_metrics["unmatched_truth_without_gps"] = match["unmatched_truth_records"]
    m4_result = _record_metrics(record, "M4_oracle", m4_metrics, threshold=m4_threshold,
                                unmatched_truth=match["unmatched_truth_records"],
                                unmatched_gps=match["unmatched_observations"],
                                delay=_delay(m4_predictions, labels))
    # M5 labels are evaluation-only and never passed to either M5 prediction function.
    m5_labels = labels if labels_path is None else m5_read_labels(labels_path)
    input_keys = {(float(row["time_s"]), row["vehicle_id"]) for row in features
                  if row.get("time_s") is not None and row.get("vehicle_id")}
    m5_metrics = score_scenario(m5_predictions, m5_labels, scenario=record["scenario"], input_keys=input_keys)
    m5_result = _record_metrics(record, "M5_gps_only", m5_metrics, threshold=None,
                                excluded=m5_metrics["excluded_observations"],
                                excluded_labels=m5_metrics["excluded_labeled_observations"],
                                delay=m5_metrics["detection_delay_s"])
    return [m4_result, m5_result]


def _aggregate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groupings = (
        ("detector",), ("detector", "scenario"), ("detector", "scenario", "attack_type"),
        ("detector", "scenario", "attack_intensity"),
        ("detector", "scenario", "attack_duration_s"),
        ("detector", "scenario", "attack_intensity", "attack_duration_s"),
        ("detector", "seed"), ("detector", "route"),
        ("detector", "scenario", "seed"), ("detector", "scenario", "route"),
    )
    summary = []
    for keys in groupings:
        groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
        for row in rows:
            groups.setdefault(tuple(row.get(key, "") for key in keys), []).append(row)
        for group, values in sorted(groups.items(), key=lambda item: tuple(str(part) for part in item[0])):
            entry = {"group_by": ";".join(keys), **dict(zip(keys, group))}
            entry["n_experiments"] = len(values)
            for metric in METRICS:
                numbers = [float(row[metric]) for row in values if row.get(metric) is not None]
                entry[f"{metric}_n"] = len(numbers)
                entry[f"{metric}_mean"] = float(np.mean(numbers)) if numbers else None
                entry[f"{metric}_std"] = float(np.std(numbers, ddof=1)) if len(numbers) > 1 else (0.0 if numbers else None)
                entry[f"{metric}_min"] = min(numbers) if numbers else None
                entry[f"{metric}_max"] = max(numbers) if numbers else None
            for field in COUNT_FIELDS:
                entry[field] = sum(int(row[field]) for row in values)
            summary.append(entry)
    return summary


def _plot_outputs(rows: list[dict[str, Any]], output: Path, route_names: list[str]) -> list[str]:
    attacks = [row for row in rows if row["split"] == "test" and row["scenario"] != "normal"]
    normals = [row for row in rows if row["split"] == "test" and row["scenario"] == "normal"]
    created: list[str] = []

    # Detector comparison: per-run F1 points grouped by attack class.
    fig, ax = plt.subplots(figsize=(9, 5))
    labels = ["offset", "jump", "drift"]
    x = np.arange(len(labels)); width = 0.35
    for offset, detector, color in ((-width/2, "M4_oracle", "tab:blue"), (width/2, "M5_gps_only", "tab:orange")):
        values = [[float(r["f1"]) for r in attacks if r["detector"] == detector and r["scenario"] == name] for name in labels]
        means = [float(np.mean(v)) if v else 0 for v in values]
        ax.bar(x + offset, means, width, color=color, label=detector)
        for i, group in enumerate(values):
            if group: ax.scatter(np.full(len(group), x[i] + offset), group, s=13, color="black", alpha=.45, zorder=3)
    ax.set(xticks=x, xticklabels=[s.title() for s in labels], ylim=(0, 1.05), ylabel="Trip-level F1",
           title="M4 vs M5 on held-out attack experiments")
    ax.legend(); fig.tight_layout(); fig.savefig(output / "m4_vs_m5_f1.png", dpi=160); plt.close(fig)
    created.append("m4_vs_m5_f1.png")

    # Intensity and duration summaries, one panel per attack type.
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6), squeeze=False)
    for ax, attack_type in zip(axes[0], ("offset", "jump", "drift")):
        selected = [r for r in attacks if r["scenario"] == attack_type]
        groups = sorted({(r["attack_intensity"], float(r["attack_duration_s"])) for r in selected}, key=lambda v: (float(v[1]), v[0]))
        xx = np.arange(len(groups)); width = .12
        for detector_i, detector in enumerate(("M4_oracle", "M5_gps_only")):
            for metric_i, metric in enumerate(("precision", "recall", "f1")):
                means = []
                for intensity, duration in groups:
                    vals = [float(r[metric]) for r in selected if r["detector"] == detector and r["attack_intensity"] == intensity and float(r["attack_duration_s"]) == duration]
                    means.append(float(np.mean(vals)) if vals else 0)
                shift = (detector_i * 3 + metric_i - 2.5) * width
                ax.bar(xx + shift, means, width, label=f"{detector} {metric}" if attack_type == "offset" else None)
        ax.set(xticks=xx, xticklabels=[f"{i}\n{d:g}s" for i, d in groups], ylim=(0, 1.05), title=attack_type.title(), xlabel="Intensity / duration", ylabel="Trip-level score")
    axes[0][0].legend(fontsize="x-small", ncol=2)
    fig.suptitle("Precision, recall and F1 by configured attack intensity and duration")
    fig.tight_layout(); fig.savefig(output / "prf_by_attack_intensity.png", dpi=160); plt.close(fig)
    created.append("prf_by_attack_intensity.png")

    fig, ax = plt.subplots(figsize=(9, 4.5))
    labels = [f"{r['route']} / seed {r['seed']}" for r in normals if r["detector"] == "M4_oracle"]
    for detector, marker in (("M4_oracle", "o"), ("M5_gps_only", "s")):
        values = [float(r["false_positive_rate"]) for r in normals if r["detector"] == detector]
        ax.plot(range(len(values)), values, marker=marker, label=detector)
    ax.set(xticks=range(len(labels)), xticklabels=labels, ylim=(0, 1.05), ylabel="False-positive rate", title="False-positive rate on held-out normal trips")
    ax.tick_params(axis="x", rotation=35); ax.legend(); fig.tight_layout(); fig.savefig(output / "normal_test_fpr.png", dpi=160); plt.close(fig)
    created.append("normal_test_fpr.png")

    fig, ax = plt.subplots(figsize=(10, 4.5))
    delay_rows = [r for r in attacks if r["detection_delay_s"] is not None]
    group_names = sorted({(r["scenario"], r["attack_intensity"]) for r in delay_rows})
    xx = np.arange(len(group_names)); width = .35
    for j, detector in enumerate(("M4_oracle", "M5_gps_only")):
        vals = [float(np.mean([r["detection_delay_s"] for r in delay_rows if r["detector"] == detector and (r["scenario"], r["attack_intensity"]) == name])) if any(r["detector"] == detector and (r["scenario"], r["attack_intensity"]) == name for r in delay_rows) else np.nan for name in group_names]
        ax.bar(xx + (j-.5)*width, vals, width, label=detector)
    ax.set(xticks=xx, xticklabels=[f"{a}\n{i}" for a, i in group_names], ylabel="Detection delay (s)", title="Mean detected-trip delay; missed trips omitted")
    ax.legend(); fig.tight_layout(); fig.savefig(output / "detection_delay.png", dpi=160); plt.close(fig)
    created.append("detection_delay.png")

    fig, axes = plt.subplots(1, 2, figsize=(10, 4.5), sharey=True)
    for ax, detector in zip(axes, ("M4_oracle", "M5_gps_only")):
        data = [[float(r["f1"]) for r in attacks if r["detector"] == detector and r["seed"] == seed] for seed in sorted({r["seed"] for r in attacks})]
        ax.boxplot(data, tick_labels=[str(seed) for seed in sorted({r["seed"] for r in attacks})], showmeans=True)
        ax.set(title=detector, xlabel="Held-out SUMO seed", ylabel="Trip-level F1", ylim=(0, 1.05))
    fig.suptitle("Trip-level performance variability across test seeds")
    fig.tight_layout(); fig.savefig(output / "seed_variability.png", dpi=160); plt.close(fig)
    created.append("seed_variability.png")

    if len(route_names) > 1:
        fig, axes = plt.subplots(1, 2, figsize=(10, 4.5), sharey=True)
        for ax, detector in zip(axes, ("M4_oracle", "M5_gps_only")):
            vals = [[float(r["f1"]) for r in attacks if r["detector"] == detector and r["route"] == route] for route in route_names]
            ax.boxplot(vals, tick_labels=route_names, showmeans=True)
            ax.set(title=detector, xlabel="Held-out route", ylabel="Trip-level F1", ylim=(0, 1.05))
            ax.tick_params(axis="x", rotation=20)
        fig.suptitle("Trip-level performance variability across routes")
        fig.tight_layout(); fig.savefig(output / "route_variability.png", dpi=160); plt.close(fig)
        created.append("route_variability.png")

    fig, axes = plt.subplots(1, 2, figsize=(8, 4))
    for ax, detector in zip(axes, ("M4_oracle", "M5_gps_only")):
        selected = [r for r in rows if r["split"] == "test" and r["detector"] == detector]
        matrix = np.array([[sum(int(r["true_negative"]) for r in selected), sum(int(r["false_positive"]) for r in selected)],
                           [sum(int(r["false_negative"]) for r in selected), sum(int(r["true_positive"]) for r in selected)]])
        ax.imshow(matrix, cmap="Greens", vmin=0)
        for (i, j), value in np.ndenumerate(matrix): ax.text(j, i, str(value), ha="center", va="center")
        ax.set(xticks=[0, 1], yticks=[0, 1], xticklabels=["Normal", "Attack"], yticklabels=["Normal", "Attack"], xlabel="Predicted", ylabel="Observed", title=detector)
    fig.suptitle("Aggregate held-out confusion counts (GPS fixes pooled within trips)")
    fig.tight_layout(); fig.savefig(output / "aggregate_confusion.png", dpi=160); plt.close(fig)
    created.append("aggregate_confusion.png")
    return created


def run_campaign(config_path: Path, run_id: str, *, smoke: bool = False) -> dict[str, Any]:
    """Run M6 under a new report ID; never reads or writes M0-M5 output paths."""
    _safe_id(run_id)
    config_path = config_path.resolve()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    project_root = config_path.parent.parent.resolve()
    if smoke:
        attack_matrix = {}
        for kind in ("offset", "jump", "drift"):
            values = config["attack_matrix"][kind]
            intensity_key = "rates_mps" if kind == "drift" else "magnitudes_m"
            attack_matrix[kind] = {"onset_s": values["onset_s"], intensity_key: [values[intensity_key][0]],
                                   "durations_s": [values["durations_s"][0]]}
        config = {**config, "seeds": {"calibration": [901], "validation": [902], "test": [903]},
                  "attack_matrix": attack_matrix}
    verified_routes = validate_routes(project_root, config)
    matrix = build_experiment_matrix(config, smoke=smoke)
    protected_before = _protected_snapshot(project_root)
    output_root = (config_path.parent / config["output_root"]).resolve()
    output = output_root / run_id
    output.mkdir(parents=True, exist_ok=False)
    shutil.copy2(config_path, output / "m6_robustness.yaml")
    data_root = output / "datasets"
    normal_trip_records = [row for row in matrix if row["scenario"] == "normal"]
    trip_assets: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(normal_trip_records):
        route = config["routes"][record["route"]]
        trip_dir = data_root / "trips" / record["trip_id"]
        trip_dir.mkdir(parents=True, exist_ok=False)
        sim_config = {"simulation": {"seed": record["seed"], "step_length_s": float(config["sumo_step_length_s"]),
            "begin_s": 0, "end_s": 600, "vehicle_id": "ev_001",
            "network_file": str((project_root / route["network_file"]).resolve()),
            "route_file": str((project_root / route["route_file"]).resolve()),
            "telemetry_output_dir": "unused", "depart_s": 0}}
        config_copy = trip_dir / "simulation.yaml"
        config_copy.write_text(yaml.safe_dump(sim_config, sort_keys=False), encoding="utf-8")
        truth_path = trip_dir / "truth.csv"
        run_sumo(config_copy, output_path=truth_path)
        gps_path = trip_dir / "gps_normal.csv"
        gps_seed = record["gps_seed"]
        generate_observations(truth_path, gps_path, noise_std_m=float(config["gps_noise_std_m"]), seed=gps_seed)
        _write_json(trip_dir / "normal_gps_metadata.json", {
            "trip_id": record["trip_id"], "split": record["split"], "route": record["route"],
            "route_id": route["route_id"], "sumo_seed": record["seed"], "gps_seed": gps_seed,
            "gps_noise_std_m_per_axis": float(config["gps_noise_std_m"]),
            "noise_distribution": "independent zero-mean Gaussian on SUMO X/Y coordinates",
            "step_length_s": float(config["sumo_step_length_s"]),
            "truth_file": str(truth_path), "gps_file": str(gps_path),
        })
        trip_assets[record["trip_id"]] = {**record, "truth": truth_path, "gps": gps_path, "gps_seed": gps_seed}
        LOGGER.info("Prepared %s (%d/%d)", record["trip_id"], index + 1, len(normal_trip_records))

    train_trips = [trip_assets[row["trip_id"]] for row in normal_trip_records if row["split"] == "calibration"]
    validation_trips = [trip_assets[row["trip_id"]] for row in normal_trip_records if row["split"] == "validation"]
    if not train_trips or not validation_trips:
        raise ValueError("M6 requires separate normal calibration and validation trips")
    m4_threshold, m5_thresholds, calibration = _calibrate_thresholds(train_trips, config["thresholds"])
    # Validation trips are scored and recorded separately; they do not retune thresholds.
    predictions_root = output / "predictions"
    predictions_root.mkdir()
    validation_rows: list[dict[str, Any]] = []
    for trip in validation_trips:
        rec = {**trip, "experiment_id": f"normal_validation_{trip['trip_id']}", "scenario": "normal",
               "attack_type": "none", "attack_intensity": "none", "attack_intensity_value": 0.0,
               "attack_intensity_unit": "none", "attack_duration_s": 0.0}
        validation_rows.extend(_evaluate(rec, trip["truth"], trip["gps"], None,
                                         m4_threshold, m5_thresholds, predictions_root / "validation"))

    scores: list[dict[str, Any]] = []
    for record in matrix:
        if record["scenario"] == "normal" and record["split"] != "test":
            continue
        trip = trip_assets[record["trip_id"]]
        labels_path: Path | None = None
        gps_path = trip["gps"]
        if record["scenario"] != "normal":
            attack_dir = data_root / "attacks" / record["experiment_id"]
            attack_dir.mkdir(parents=True, exist_ok=False)
            gps_path = attack_dir / "gps.csv"
            _, labels_path = generate_attack(trip["truth"], gps_path, attack_type=record["attack_type"],
                settings=_attack_settings(record, config), noise_std_m=float(config["gps_noise_std_m"]), seed=trip["gps_seed"])
        pred_dir = predictions_root / "test" / record["experiment_id"]
        pred_dir.mkdir(parents=True, exist_ok=False)
        row_results = _evaluate(record, trip["truth"], gps_path, labels_path,
                                m4_threshold, m5_thresholds, pred_dir)
        scores.extend(row_results)
        LOGGER.info("Evaluated %s", record["experiment_id"])

    matrix_fields = list(dict.fromkeys(key for row in matrix for key in row))
    _write_csv(output / "experiment_matrix.csv", matrix_fields, matrix)
    _write_csv(output / "per_experiment_metrics.csv", SCORE_FIELDS, scores)
    aggregate = _aggregate(scores)
    aggregate_fields = list(dict.fromkeys(key for row in aggregate for key in row)) if aggregate else ["detector", "n_experiments"]
    _write_csv(output / "aggregate_metrics.csv", aggregate_fields, aggregate)
    _write_json(output / "threshold_calibration.json", calibration)
    _write_csv(output / "validation_metrics.csv", SCORE_FIELDS, validation_rows)
    plot_names = _plot_outputs(scores, output, sorted({row["route"] for row in matrix}))
    protected_after = _protected_snapshot(project_root)
    if protected_after != protected_before:
        raise RuntimeError("M6 run modified a protected M0-M5 input or output; compare snapshot manifests")
    metadata = {
        "milestone": "M6", "run_id": run_id, "smoke": smoke,
        "coordinate_frame": "SUMO local road-network X/Y meters; time in seconds; step length 1 s",
        "gps_noise": {"distribution": "independent zero-mean Gaussian per X/Y axis", "std_m_per_axis": config["gps_noise_std_m"]},
        "routes_validated": verified_routes, "seed_groups": config["seeds"],
        "threshold_calibration": calibration,
        "m4_status": "oracle-assisted; uses truth coordinates for residual calculation",
        "m5_prediction_inputs": ["time_s", "vehicle_id", "gps_x_m", "gps_y_m", "previous GPS fix"],
        "m5_prediction_excludes": ["ground truth", "attack labels", "future GPS fixes"],
        "m5_labels_loaded_after_prediction_for_scoring": True,
        "matrix_rows": len(matrix), "test_experiments": sum(r["split"] == "test" and r["scenario"] != "normal" for r in matrix) + sum(r["split"] == "test" and r["scenario"] == "normal" for r in matrix),
        "detector_evaluations": len(scores), "validation_detector_evaluations": len(validation_rows),
        "aggregate_unit": "one simulation trip/scenario configuration; GPS fixes are not treated as independent experiments",
        "protected_m0_m5_snapshot": {key: value for key, value in protected_after.items() if key != "manifest"},
        "protected_m0_m5_unchanged": True,
        "statistical_method": "mean, sample standard deviation (ddof=1; 0 for n=1), min/max over per-trip metrics; delay excludes missed attacks",
        "plots": plot_names,
    }
    _write_json(output / "run_metadata.json", metadata)
    return {"output_dir": str(output), "experiment_matrix_rows": len(matrix),
            "test_experiments": metadata["test_experiments"], "detector_evaluations": len(scores),
            "validation_detector_evaluations": len(validation_rows), "plots": plot_names}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/m6_robustness.yaml"))
    parser.add_argument("--run-id", required=True, help="new reports/m6 run folder; existing IDs are never overwritten")
    parser.add_argument("--smoke", action="store_true", help="run a reduced one-route, one-seed/level matrix")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        print(json.dumps(run_campaign(args.config, args.run_id, smoke=args.smoke), indent=2))
    except Exception as exc:
        LOGGER.error("M6 campaign failed: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
