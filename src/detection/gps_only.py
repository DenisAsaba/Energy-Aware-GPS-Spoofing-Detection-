"""Causal GPS-only temporal consistency baseline for M5.

Prediction uses only timestamped GPS X/Y observations and previous observations
for the same vehicle. Labels and M4 metrics are loaded only by the evaluation
workflow after predictions have been produced.
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
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import yaml

LOGGER = logging.getLogger("m5")
FEATURE_THRESHOLDS = {
    "estimated_speed_mps": "max_speed_mps",
    "speed_change_mps": "max_speed_change_mps",
    "heading_change_deg": "max_heading_change_deg",
}
PREDICTION_FIELDS = (
    "time_s", "vehicle_id", "gps_x_m", "gps_y_m", "elapsed_s", "displacement_m",
    "estimated_speed_mps", "estimated_heading_deg", "speed_change_mps",
    "heading_change_deg", "speed_rule", "speed_change_rule", "heading_change_rule",
    "rule_triggered", "predicted_attack", "eligible", "exclusion_reason", "evaluation_split",
)
SCENARIO_FIELDS = (
    "scenario", "true_positive", "false_positive", "true_negative", "false_negative",
    "precision", "recall", "f1", "false_positive_rate", "accuracy", "detection_delay_s",
    "input_observations", "eligible_observations", "excluded_observations",
    "excluded_labeled_observations", "unmatched_observations", "unmatched_label_records",
    "calibration_observations",
)
METRICS = ("precision", "recall", "f1")


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _key(row: dict[str, Any]) -> tuple[float, str] | None:
    time_s = _number(row.get("time_s"))
    vehicle = str(row.get("vehicle_id", "")).strip()
    return (time_s, vehicle) if time_s is not None and vehicle else None


def _angle_delta(current: float, previous: float) -> float:
    """Smallest unsigned angle between SUMO compass headings, in degrees."""
    return abs((current - previous + 180.0) % 360.0 - 180.0)


def extract_gps_features(gps_path: Path) -> list[dict[str, Any]]:
    """Derive causal per-fix features, retaining excluded rows with reasons.

    Input rows must be chronological per vehicle. Duplicate, missing, invalid,
    and out-of-order fixes are excluded and never update the vehicle state.
    The first valid fix per vehicle initializes state but is not scoreable.
    """
    try:
        with gps_path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
                raise ValueError(f"{gps_path}: missing or duplicate CSV headers")
            required = {"time_s", "vehicle_id", "gps_x_m", "gps_y_m"}
            missing = required - set(reader.fieldnames)
            if missing:
                raise ValueError(f"{gps_path} is missing GPS columns: {sorted(missing)}")
            source_rows = list(reader)
    except OSError as exc:
        raise ValueError(f"Could not read GPS observations {gps_path}: {exc}") from exc
    if not source_rows:
        raise ValueError(f"GPS CSV has no data rows: {gps_path}")

    states: dict[str, dict[str, Any]] = {}
    seen: set[tuple[float, str]] = set()
    features: list[dict[str, Any]] = []
    for index, raw in enumerate(source_rows):
        t_raw, vehicle = raw.get("time_s"), str(raw.get("vehicle_id") or "").strip()
        t, x, y = _number(t_raw), _number(raw.get("gps_x_m")), _number(raw.get("gps_y_m"))
        row: dict[str, Any] = {
            "time_s": t if t is not None else (t_raw or ""), "vehicle_id": vehicle,
            "gps_x_m": x if x is not None else (raw.get("gps_x_m") or ""),
            "gps_y_m": y if y is not None else (raw.get("gps_y_m") or ""),
            "elapsed_s": None, "displacement_m": None, "estimated_speed_mps": None,
            "estimated_heading_deg": None, "speed_change_mps": None,
            "heading_change_deg": None, "speed_rule": 0, "speed_change_rule": 0,
            "heading_change_rule": 0, "rule_triggered": "", "predicted_attack": "",
            "eligible": 0, "exclusion_reason": "", "evaluation_split": "evaluation",
            "_source_index": index, "_valid_observation": False,
        }
        if None in raw:
            row["exclusion_reason"] = "extra_csv_fields"
        elif t is None:
            row["exclusion_reason"] = "missing_or_invalid_timestamp"
        elif not vehicle:
            row["exclusion_reason"] = "missing_vehicle_id"
        elif (x is None) or (y is None):
            row["exclusion_reason"] = "missing_or_invalid_coordinate"
        elif (t, vehicle) in seen:
            row["exclusion_reason"] = "duplicate_timestamp_vehicle"
        elif vehicle in states and t <= states[vehicle]["time_s"]:
            row["exclusion_reason"] = "out_of_order_timestamp"
        else:
            seen.add((t, vehicle))
            row["_valid_observation"] = True
            previous = states.get(vehicle)
            if previous is None:
                row["exclusion_reason"] = "first_observation"
                states[vehicle] = {"time_s": t, "x": x, "y": y, "speed": None, "heading": None}
            else:
                dt = t - previous["time_s"]
                dx, dy = x - previous["x"], y - previous["y"]
                displacement = math.hypot(dx, dy)
                speed = displacement / dt
                heading = math.degrees(math.atan2(dx, dy)) % 360.0 if displacement > 1e-9 else None
                speed_change = abs(speed - previous["speed"]) if previous["speed"] is not None else None
                heading_change = (
                    _angle_delta(heading, previous["heading"])
                    if heading is not None and previous["heading"] is not None else None
                )
                row.update({"elapsed_s": dt, "displacement_m": displacement,
                            "estimated_speed_mps": speed, "estimated_heading_deg": heading,
                            "speed_change_mps": speed_change, "heading_change_deg": heading_change,
                            "eligible": 1})
                states[vehicle] = {"time_s": t, "x": x, "y": y, "speed": speed, "heading": heading}
        features.append(row)
    return features


def calibrate_temporal_thresholds(
    normal_features: list[dict[str, Any]], *, quantile: float, calibration_fraction: float,
) -> tuple[dict[str, float], set[int], set[int], dict[str, Any]]:
    """Fit upper feature quantiles on a chronological normal-only prefix."""
    if not math.isfinite(quantile) or not 0 <= quantile <= 1:
        raise ValueError("normal_quantile must be between 0 and 1")
    if not math.isfinite(calibration_fraction) or not 0 < calibration_fraction < 1:
        raise ValueError("calibration_fraction must be between 0 and 1")
    valid = [row["_source_index"] for row in normal_features if row["_valid_observation"]]
    n_calibration = math.floor(len(valid) * calibration_fraction)
    if n_calibration < 3 or n_calibration >= len(valid):
        raise ValueError("normal GPS baseline needs at least 4 valid fixes and nonempty calibration/evaluation splits")
    calibration_indices = set(valid[:n_calibration])
    evaluation_indices = set(valid[n_calibration:])
    thresholds: dict[str, float] = {}
    counts: dict[str, int] = {}
    for feature, threshold_name in FEATURE_THRESHOLDS.items():
        values = [float(row[feature]) for row in normal_features
                  if row["_source_index"] in calibration_indices and row["eligible"]
                  and row[feature] is not None]
        if len(values) < 2:
            raise ValueError(f"not enough normal calibration samples for {feature}")
        thresholds[threshold_name] = float(np.quantile(values, quantile))
        counts[feature] = len(values)
    return thresholds, calibration_indices, evaluation_indices, {
        "normal_valid_observations": len(valid), "calibration_observations": n_calibration,
        "calibration_eligible_features": counts, "evaluation_observations": len(evaluation_indices),
        "normal_quantile": quantile, "calibration_fraction": calibration_fraction,
        "threshold_method": "independent configured NumPy quantile per temporal feature",
    }


def apply_temporal_thresholds(
    features: list[dict[str, Any]], thresholds: dict[str, float], *,
    calibration_indices: set[int] | None = None, evaluation_indices: set[int] | None = None,
) -> list[dict[str, Any]]:
    """Apply fixed OR rules using only current/past GPS-derived features."""
    required = set(FEATURE_THRESHOLDS.values())
    if set(thresholds) != required or any(not math.isfinite(v) or v < 0 for v in thresholds.values()):
        raise ValueError(f"thresholds must contain finite nonnegative values for {sorted(required)}")
    output = []
    for feature_row in features:
        row = dict(feature_row)
        i = row["_source_index"]
        if calibration_indices is not None and i in calibration_indices:
            row["evaluation_split"] = "calibration"
        elif evaluation_indices is not None and i not in evaluation_indices:
            row["evaluation_split"] = "excluded"
        else:
            row["evaluation_split"] = "evaluation"
        if not row["eligible"]:
            row["rule_triggered"] = ""
            row["predicted_attack"] = ""
            output.append(row)
            continue
        fired = []
        for feature, threshold_name in FEATURE_THRESHOLDS.items():
            value = row[feature]
            hit = value is not None and float(value) > thresholds[threshold_name]
            rule_field = {"estimated_speed_mps": "speed_rule",
                           "speed_change_mps": "speed_change_rule",
                           "heading_change_deg": "heading_change_rule"}[feature]
            row[rule_field] = int(hit)
            if hit:
                fired.append(threshold_name.removeprefix("max_").removesuffix("_mps").replace("_deg", ""))
        row["rule_triggered"] = ";".join(fired) if fired else "none"
        row["predicted_attack"] = int(bool(fired))
        output.append(row)
    return output


def _read_labels(path: Path) -> dict[tuple[float, str], int]:
    """Load labels only for evaluation, validating binary values and unique keys."""
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
                raise ValueError(f"{path}: missing or duplicate label headers")
            required = {"time_s", "vehicle_id", "attack_active"}
            missing = required - set(reader.fieldnames)
            if missing:
                raise ValueError(f"{path} is missing label columns: {sorted(missing)}")
            rows = list(reader)
    except OSError as exc:
        raise ValueError(f"Could not read attack labels {path}: {exc}") from exc
    labels: dict[tuple[float, str], int] = {}
    for line, row in enumerate(rows, 2):
        t = _number(row.get("time_s")); vehicle = (row.get("vehicle_id") or "").strip()
        if t is None or not vehicle or row.get("attack_active") not in ("0", "1"):
            raise ValueError(f"{path}:{line}: invalid time, vehicle ID or binary attack_active")
        key = (t, vehicle)
        if key in labels:
            raise ValueError(f"{path}:{line}: duplicate label key {key}")
        labels[key] = int(row["attack_active"])
    return labels


def _confusion(predicted: dict[tuple[float, str], int], labels: dict[tuple[float, str], int]) -> dict[str, Any]:
    matched = predicted.keys() & labels.keys()
    tp = sum(predicted[k] == 1 and labels[k] == 1 for k in matched)
    fp = sum(predicted[k] == 1 and labels[k] == 0 for k in matched)
    tn = sum(predicted[k] == 0 and labels[k] == 0 for k in matched)
    fn = sum(predicted[k] == 0 and labels[k] == 1 for k in matched)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {"true_positive": tp, "false_positive": fp, "true_negative": tn,
            "false_negative": fn, "precision": precision, "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
            "false_positive_rate": fp / (fp + tn) if fp + tn else 0.0,
            "accuracy": (tp + tn) / len(matched) if matched else 0.0,
            "matched_observations": len(matched),
            "unmatched_prediction_records": len(predicted.keys() - labels.keys()),
            "unmatched_label_records": len(labels.keys() - predicted.keys())}


def score_scenario(
    predictions: list[dict[str, Any]], labels: dict[tuple[float, str], int], *,
    scenario: str, input_keys: set[tuple[float, str]], calibration_count: int = 0,
) -> dict[str, Any]:
    """Score eligible evaluation records and expose exclusions/unmatched inputs."""
    eligible_rows = [row for row in predictions if row["eligible"] and row["evaluation_split"] == "evaluation"]
    predicted = {_key(row): int(row["predicted_attack"]) for row in eligible_rows}
    predicted.pop(None, None)
    selected_labels = {key: value for key, value in labels.items() if key in input_keys}
    metrics = _confusion(predicted, selected_labels)
    matched_keys = predicted.keys() & selected_labels.keys()
    active = [key for key in matched_keys if selected_labels[key] == 1]
    delay = None
    if active:
        onset = min(key[0] for key, value in labels.items() if value == 1)
        hits = [key[0] for key in active if predicted[key] == 1]
        if hits:
            delay = min(hits) - onset
    eligible_keys = set(predicted)
    return {
        "scenario": scenario, **metrics,
        "detection_delay_s": delay,
        "detection_delay_definition": "first eligible active-label true positive time minus first active-label time; null if undetected",
        "input_observations": len(predictions),
        "eligible_observations": len(eligible_rows),
        "excluded_observations": len(predictions) - len(eligible_rows),
        "excluded_labeled_observations": len((selected_labels.keys() & input_keys) - eligible_keys),
        "unmatched_observations": len(input_keys - labels.keys()),
        "unmatched_label_records": len(labels.keys() - input_keys),
        "calibration_observations": calibration_count,
    }


def _prediction_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite M5 output: {path}")
    with path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=PREDICTION_FIELDS)
        writer.writeheader()
        writer.writerows([{field: row.get(field, "") for field in PREDICTION_FIELDS} for row in rows])


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _plot_confusion(results: list[dict[str, Any]], path: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(8, 7))
    for ax, result in zip(axes.flat, results):
        matrix = np.array([[result["true_negative"], result["false_positive"]],
                           [result["false_negative"], result["true_positive"]]])
        ax.imshow(matrix, cmap="Greens", vmin=0)
        for (i, j), value in np.ndenumerate(matrix): ax.text(j, i, str(value), ha="center", va="center")
        ax.set(xticks=[0, 1], yticks=[0, 1], xticklabels=["Normal", "Attack"],
               yticklabels=["Normal", "Attack"], xlabel="Predicted class", ylabel="True class",
               title=result["scenario"].title())
    fig.suptitle("M5 GPS-only temporal-rule confusion matrices")
    fig.tight_layout(); fig.savefig(path, dpi=160); plt.close(fig)


def _plot_comparison(m5: list[dict[str, Any]], m4: list[dict[str, Any]], path: Path) -> None:
    m4_by_name = {row["scenario"]: row for row in m4}
    scenarios = [row["scenario"] for row in m5]
    x = np.arange(len(scenarios)); width = 0.18
    fig, axes = plt.subplots(1, 3, figsize=(12, 4), sharey=True)
    for ax, metric in zip(axes, METRICS):
        ax.bar(x - width / 2, [row[metric] for row in m5], width, label="M5 GPS-only")
        ax.bar(x + width / 2, [m4_by_name[name][metric] for name in scenarios], width,
               label="M4 oracle-assisted")
        ax.set(xticks=x, xticklabels=[name.title() for name in scenarios], ylim=(0, 1.05),
               title=metric.upper(), ylabel="Score (unitless)")
    axes[0].legend(fontsize="small")
    fig.suptitle("M5 GPS-only vs M4 oracle-assisted; inputs and eligible records differ")
    fig.tight_layout(); fig.savefig(path, dpi=160); plt.close(fig)


def _plot_features(
    scenarios: list[tuple[str, list[dict[str, Any]], dict[tuple[float, str], int]]],
    thresholds: dict[str, float], path: Path,
) -> None:
    columns = (("estimated_speed_mps", "Estimated GPS speed (m/s)", "max_speed_mps"),
               ("speed_change_mps", "GPS speed change (m/s)", "max_speed_change_mps"),
               ("heading_change_deg", "GPS heading change (degrees)", "max_heading_change_deg"))
    fig, axes = plt.subplots(len(scenarios), len(columns), figsize=(13, 10), squeeze=False)
    for row_i, (scenario, records, labels) in enumerate(scenarios):
        rows = sorted((r for r in records if r["eligible"] and r["evaluation_split"] == "evaluation"),
                      key=lambda r: (float(r["time_s"]), r["vehicle_id"]))
        times = [float(r["time_s"]) for r in rows]
        predictions = [int(r["predicted_attack"]) for r in rows]
        actual = [labels.get((float(r["time_s"]), r["vehicle_id"]), 0) for r in rows]
        for col_i, (field, label, threshold_name) in enumerate(columns):
            ax = axes[row_i, col_i]
            values = [float(r[field]) if r[field] is not None else math.nan for r in rows]
            ax.plot(times, values, color="tab:blue", label=label)
            ax.axhline(thresholds[threshold_name], color="tab:orange", linestyle="--",
                       label=f"Threshold {thresholds[threshold_name]:.2f}")
            ax.set_ylabel(label); ax.grid(alpha=0.2)
            if row_i == 0: ax.set_title(label)
            right = ax.twinx()
            right.step(times, actual, where="mid", color="tab:red", alpha=0.7, label="Attack label")
            right.step(times, predictions, where="mid", color="tab:green", linestyle=":", label="Prediction")
            right.set_ylim(-0.05, 1.1); right.set_yticks([0, 1])
            if col_i == len(columns) - 1: right.set_ylabel("Class (0/1)")
            if row_i == len(scenarios) - 1: ax.set_xlabel("Time (s)")
            if col_i == 0:
                ax.text(-0.24, 0.5, scenario.title(), transform=ax.transAxes,
                        rotation=90, va="center", ha="center")
            if row_i == 0 and col_i == 0:
                lines, labels_ = ax.get_legend_handles_labels(); lines2, labels2 = right.get_legend_handles_labels()
                ax.legend(lines + lines2, labels_ + labels2, fontsize="x-small", loc="upper left")
    fig.suptitle("Causal GPS-derived temporal features, normal-only thresholds and offline labels/predictions")
    fig.tight_layout(); fig.savefig(path, dpi=160); plt.close(fig)


def run_workflow(config_path: Path, run_id: str) -> list[dict[str, Any]]:
    """Calibrate M5 rules on normal M2 GPS and evaluate M2 holdout/M3 attacks."""
    if not run_id or not all(char.isalnum() or char in "-_" for char in run_id):
        raise ValueError("run_id may contain only letters, numbers, hyphens and underscores")
    config_path = config_path.resolve()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    root = config_path.parent.parent
    settings = config["m5"]
    datasets = settings["datasets"]
    resolve = lambda value: (config_path.parent / value).resolve()

    normal_gps = resolve(datasets["normal"]["gps_file"])
    normal_features = extract_gps_features(normal_gps)
    thresholds, calibration_indices, evaluation_indices, calibration = calibrate_temporal_thresholds(
        normal_features,
        quantile=float(settings["calibration"]["normal_quantile"]),
        calibration_fraction=float(settings["calibration"]["fraction"]))

    output = resolve(settings["output_dir"]) / run_id
    output.mkdir(parents=True, exist_ok=False)
    shutil.copy2(config_path, output / "experiment_config.yaml")
    input_manifest: dict[str, Any] = {"normal_gps": str(normal_gps),
                                      "normal_gps_sha256": _sha256(normal_gps), "attacks": {}}
    metadata = {"milestone": "M5", "detector": "gps_only_temporal_threshold_rules",
                "detector_status": "GPS-only research baseline; not certified for production safety",
                "prediction_inputs": ["time_s", "vehicle_id", "gps_x_m", "gps_y_m",
                                      "previous valid GPS fix for the same vehicle"],
                "prediction_excludes": ["ground-truth coordinates or motion", "attack labels", "M4 residuals", "future GPS fixes"],
                "feature_units": {"elapsed_s": "s", "displacement_m": "m",
                                  "estimated_speed_mps": "m/s", "speed_change_mps": "m/s",
                                  "estimated_heading_deg": "degrees clockwise from north",
                                  "heading_change_deg": "degrees"},
                "coordinate_frame": "SUMO local road-network X/Y meters; only GPS coordinate differences are used",
                "threshold_calibration": {**calibration, "thresholds": thresholds},
                "configuration_file": str(config_path), "run_id": run_id}

    normal_predictions = apply_temporal_thresholds(
        normal_features, thresholds, calibration_indices=calibration_indices,
        evaluation_indices=evaluation_indices)
    _prediction_csv(output / "normal_predictions.csv", normal_predictions)
    normal_input_keys = {key for row in normal_features if (key := _key(row)) is not None}
    normal_labels = {key: 0 for key in normal_input_keys}
    normal_metrics = score_scenario(normal_predictions, normal_labels, scenario="normal",
                                    input_keys=normal_input_keys,
                                    calibration_count=len(calibration_indices))
    normal_metrics["thresholds"] = thresholds
    (output / "normal_metrics.json").write_text(json.dumps(normal_metrics, indent=2) + "\n", encoding="utf-8")
    m5_results = [normal_metrics]
    plot_data = [("normal", normal_predictions, normal_labels)]

    for scenario in ("offset", "jump", "drift"):
        dataset = datasets["attacks"][scenario]
        gps_path = resolve(dataset["gps_file"])
        features = extract_gps_features(gps_path)
        predictions = apply_temporal_thresholds(features, thresholds)
        _prediction_csv(output / f"{scenario}_predictions.csv", predictions)
        # Labels are loaded after GPS-only features and predictions are complete.
        labels_path = resolve(dataset["labels_file"])
        labels = _read_labels(labels_path)
        input_keys = {key for row in features if (key := _key(row)) is not None}
        result = score_scenario(predictions, labels, scenario=scenario, input_keys=input_keys)
        result["thresholds"] = thresholds
        (output / f"{scenario}_metrics.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        m5_results.append(result); plot_data.append((scenario, predictions, labels))
        input_manifest["attacks"][scenario] = {
            "gps_file": str(gps_path), "gps_sha256": _sha256(gps_path),
            "labels_file": str(labels_path), "labels_sha256": _sha256(labels_path)}

    # The M4 files are read only for a post-prediction benchmark comparison.
    m4_dir = resolve(settings["m4_reference_dir"])
    m4_results = [json.loads((m4_dir / f"{scenario}_metrics.json").read_text(encoding="utf-8"))
                  for scenario in ("normal", "offset", "jump", "drift")]
    m4_by_scenario = {result["scenario"]: result for result in m4_results}
    comparison = []
    for result in m5_results:
        oracle = m4_by_scenario[result["scenario"]]
        comparison.append({"scenario": result["scenario"],
                           **{f"m5_{metric}": result[metric] for metric in METRICS},
                           **{f"m4_{metric}": oracle[metric] for metric in METRICS},
                           "m5_eligible_observations": result["eligible_observations"],
                           "m4_matched_observations": oracle["matched_observations"],
                           "m5_detector": "GPS-only temporal rules",
                           "m4_detector": "oracle-assisted position residual"})
    with (output / "summary.csv").open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=SCENARIO_FIELDS)
        writer.writeheader(); writer.writerows([{field: row.get(field, "") for field in SCENARIO_FIELDS} for row in m5_results])
    with (output / "m4_comparison.csv").open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(comparison[0]))
        writer.writeheader(); writer.writerows(comparison)
    (output / "m4_comparison.json").write_text(json.dumps(comparison, indent=2) + "\n", encoding="utf-8")
    metadata["input_manifest"] = input_manifest
    metadata["m4_reference_metrics_dir"] = str(m4_dir)
    (output / "run_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    _plot_confusion(m5_results, output / "confusion_matrices.png")
    _plot_comparison(m5_results, m4_results, output / "m4_comparison_prf.png")
    _plot_features(plot_data, thresholds, output / "gps_temporal_features_predictions.png")
    return m5_results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/experiment_config.yaml"))
    parser.add_argument("--run-id", required=True, help="new M5 output folder; existing IDs are never overwritten")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        for result in run_workflow(args.config, args.run_id):
            LOGGER.info("M5 metrics: %s", json.dumps(result, sort_keys=True))
    except Exception as exc:
        LOGGER.error("M5 workflow failed: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
