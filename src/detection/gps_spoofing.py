"""Oracle-assisted position-residual baseline for M4 GPS attack evaluation.

Ground truth is used to compute residuals and calibrate a normal-only threshold.
This is an offline research baseline and is not deployable as a GPS-only detector.
Attack labels are read only after predictions are produced, for scoring/plots.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
from pathlib import Path
import shutil
from typing import Any, Iterable

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import yaml

from src.sensors.gps_normal import _read_csv, evaluate_observations

LOGGER = logging.getLogger("m4")
PREDICTION_FIELDS = ("time_s", "vehicle_id", "residual_m", "threshold_m", "predicted_attack", "evaluation_split")
CONFUSION_FIELDS = ("true_negative", "false_positive", "false_negative", "true_positive")
SCORE_FIELDS = ("scenario", "threshold_m", "true_positive", "false_positive", "true_negative",
                "false_negative", "precision", "recall", "f1", "false_positive_rate", "accuracy",
                "matched_observations", "unmatched_prediction_records", "unmatched_label_records",
                "detection_delay_s")


def predict_position_residuals(
    truth_path: Path, gps_path: Path, threshold_m: float,
    *, evaluation_keys: set[tuple[float, str]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Predict anomalies from M2-style truth/GPS residuals; labels are not accepted."""
    if not math.isfinite(threshold_m) or threshold_m < 0:
        raise ValueError("threshold_m must be finite and nonnegative")
    match_stats, residuals = evaluate_observations(truth_path, gps_path)
    output = []
    for row in sorted(residuals, key=lambda r: (r["time_s"], r["vehicle_id"])):
        key = (row["time_s"], row["vehicle_id"])
        role = "evaluation" if evaluation_keys is None or key in evaluation_keys else "calibration"
        output.append({"time_s": row["time_s"], "vehicle_id": row["vehicle_id"],
                       "residual_m": row["position_error_m"], "threshold_m": threshold_m,
                       "predicted_attack": int(row["position_error_m"] > threshold_m),
                       "evaluation_split": role})
    return output, match_stats


def calibrate_threshold(
    truth_path: Path, normal_gps_path: Path, *, quantile: float, calibration_fraction: float,
) -> tuple[float, set[tuple[float, str]], set[tuple[float, str]], dict[str, Any]]:
    """Calibrate a fixed threshold on an early normal-only prefix; hold out its suffix."""
    if not math.isfinite(quantile) or not 0.0 <= quantile <= 1.0:
        raise ValueError("threshold quantile must be between 0 and 1")
    if not math.isfinite(calibration_fraction) or not 0.0 < calibration_fraction < 1.0:
        raise ValueError("calibration_fraction must be between 0 and 1")
    match_stats, errors = evaluate_observations(truth_path, normal_gps_path)
    ordered = sorted(errors, key=lambda r: (r["time_s"], r["vehicle_id"]))
    count = int(math.floor(len(ordered) * calibration_fraction))
    if count < 1 or count >= len(ordered):
        raise ValueError("normal baseline needs at least two matched observations and nonempty calibration/evaluation splits")
    calibration = ordered[:count]
    evaluation = ordered[count:]
    threshold = float(np.quantile([r["position_error_m"] for r in calibration], quantile))
    calibration_keys = {(r["time_s"], r["vehicle_id"]) for r in calibration}
    evaluation_keys = {(r["time_s"], r["vehicle_id"]) for r in evaluation}
    details = {**match_stats, "calibration_observations": len(calibration),
               "normal_evaluation_observations": len(evaluation),
               "calibration_fraction": calibration_fraction, "threshold_quantile": quantile,
               "threshold_method": "numpy.quantile linear interpolation", "threshold_m": threshold}
    return threshold, calibration_keys, evaluation_keys, details


def _read_labels(path: Path) -> dict[tuple[float, str], int]:
    """Read offline binary labels with unique timestamp/vehicle keys."""
    rows = _read_csv(path)
    required = {"time_s", "vehicle_id", "attack_active"}
    if not required.issubset(rows[0]):
        raise ValueError(f"{path} is missing label columns: {sorted(required - set(rows[0]))}")
    labels: dict[tuple[float, str], int] = {}
    for line, row in enumerate(rows, start=2):
        try:
            time_s = float(row["time_s"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{path}:{line}: invalid time_s") from exc
        if not math.isfinite(time_s) or not row["vehicle_id"]:
            raise ValueError(f"{path}:{line}: nonfinite time or empty vehicle_id")
        if row["attack_active"] not in ("0", "1"):
            raise ValueError(f"{path}:{line}: attack_active must be binary 0 or 1")
        key = (time_s, row["vehicle_id"])
        if key in labels:
            raise ValueError(f"{path}:{line}: duplicate timestamp/vehicle key {key}")
        labels[key] = int(row["attack_active"])
    return labels


def classification_metrics(
    predictions: Iterable[dict[str, Any]], labels: dict[tuple[float, str], int],
    *, evaluation_keys: set[tuple[float, str]] | None = None,
) -> dict[str, Any]:
    """Score matched binary predictions; undefined ratios use the documented zero convention."""
    prediction_map = {}
    for row in predictions:
        key = (float(row["time_s"]), row["vehicle_id"])
        if evaluation_keys is not None and key not in evaluation_keys:
            continue
        value = int(row["predicted_attack"])
        if value not in (0, 1) or key in prediction_map:
            raise ValueError("predictions must have unique keys and binary predicted_attack values")
        prediction_map[key] = value
    selected_labels = {k: v for k, v in labels.items() if evaluation_keys is None or k in evaluation_keys}
    keys = prediction_map.keys() & selected_labels.keys()
    tp = sum(prediction_map[k] == 1 and selected_labels[k] == 1 for k in keys)
    fp = sum(prediction_map[k] == 1 and selected_labels[k] == 0 for k in keys)
    tn = sum(prediction_map[k] == 0 and selected_labels[k] == 0 for k in keys)
    fn = sum(prediction_map[k] == 0 and selected_labels[k] == 1 for k in keys)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    fpr = fp / (fp + tn) if fp + tn else 0.0
    accuracy = (tp + tn) / len(keys) if keys else 0.0
    return {"true_positive": tp, "false_positive": fp, "true_negative": tn,
            "false_negative": fn, "precision": precision, "recall": recall, "f1": f1,
            "false_positive_rate": fpr, "accuracy": accuracy,
            "matched_observations": len(keys),
            "unmatched_prediction_records": len(prediction_map.keys() - selected_labels.keys()),
            "unmatched_label_records": len(selected_labels.keys() - prediction_map.keys())}


def _score_scenario(
    predictions: list[dict[str, Any]], labels: dict[tuple[float, str], int], *,
    scenario: str, threshold_m: float, match_stats: dict[str, Any],
    evaluation_keys: set[tuple[float, str]] | None = None,
) -> dict[str, Any]:
    metrics = classification_metrics(predictions, labels, evaluation_keys=evaluation_keys)
    active_keys = [k for k, value in labels.items() if value == 1 and
                   (evaluation_keys is None or k in evaluation_keys)]
    delay = None
    if active_keys:
        start = min(k[0] for k in active_keys)
        prediction_map = {(float(r["time_s"]), r["vehicle_id"]): int(r["predicted_attack"])
                          for r in predictions}
        detected = [k[0] for k in active_keys if prediction_map.get(k) == 1]
        if detected:
            delay = min(detected) - start
    return {"scenario": scenario, "threshold_m": threshold_m, **metrics,
            "unmatched_gps_without_truth": match_stats["unmatched_observations"],
            "unmatched_truth_without_gps": match_stats["unmatched_truth_records"],
            "detection_delay_s": delay,
            "detection_delay_definition": "first active-sample true positive time minus first active-label time; null if undetected"}


def _write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite M4 output: {path}")
    with path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)


def _plot_confusions(results: list[dict[str, Any]], output: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(8, 7))
    for ax, result in zip(axes.flat, results):
        matrix = np.array([[result["true_negative"], result["false_positive"]],
                           [result["false_negative"], result["true_positive"]]])
        ax.imshow(matrix, cmap="Blues", vmin=0)
        for (i, j), count in np.ndenumerate(matrix): ax.text(j, i, str(count), ha="center", va="center")
        ax.set(xticks=[0, 1], yticks=[0, 1], xticklabels=["Normal", "Attack"],
               yticklabels=["Normal", "Attack"], xlabel="Predicted class", ylabel="True class",
               title=result["scenario"].replace("_", " ").title())
    fig.suptitle("M4 oracle-assisted residual detector confusion matrices")
    fig.tight_layout(); fig.savefig(output, dpi=160); plt.close(fig)


def _plot_scores(results: list[dict[str, Any]], output: Path) -> None:
    scenarios = [r for r in results if r["scenario"] in {"offset", "jump", "drift"}]
    x = np.arange(len(scenarios)); width = 0.24
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for i, metric in enumerate(("precision", "recall", "f1")):
        ax.bar(x + (i - 1) * width, [r[metric] for r in scenarios], width, label=metric.upper())
    ax.set(xticks=x, xticklabels=[r["scenario"].title() for r in scenarios], ylim=(0, 1.05),
           ylabel="Score (unitless)", title="M4 attack-scenario precision, recall and F1")
    ax.legend(); fig.tight_layout(); fig.savefig(output, dpi=160); plt.close(fig)


def _plot_timeseries(
    scenarios: list[tuple[str, list[dict[str, Any]], dict[tuple[float, str], int]]],
    threshold_m: float, output: Path,
) -> None:
    fig, axes = plt.subplots(len(scenarios), 1, figsize=(10, 9), sharex=False)
    for ax, (name, predictions, labels) in zip(axes, scenarios):
        rows = sorted(predictions, key=lambda r: (r["time_s"], r["vehicle_id"]))
        times = [r["time_s"] for r in rows]
        residuals = [r["residual_m"] for r in rows]
        predicted = [r["predicted_attack"] for r in rows]
        actual = [labels.get((r["time_s"], r["vehicle_id"]), 0) for r in rows]
        ax.plot(times, residuals, color="tab:blue", label="Position residual (m)")
        ax.axhline(threshold_m, color="tab:orange", linestyle="--", label=f"Threshold ({threshold_m:.3f} m)")
        ax.set_ylabel("Residual (m)"); ax.set_title(name.replace("_", " ").title())
        right = ax.twinx()
        right.step(times, actual, where="mid", color="tab:red", alpha=0.75, label="Attack label")
        right.step(times, predicted, where="mid", color="tab:green", linestyle=":", label="Prediction")
        right.set_ylim(-0.05, 1.15); right.set_yticks([0, 1]); right.set_ylabel("Class (0/1)")
        lines, names_ = ax.get_legend_handles_labels(); lines2, names2 = right.get_legend_handles_labels()
        ax.legend(lines + lines2, names_ + names2, loc="upper left", ncol=2, fontsize="small")
    axes[-1].set_xlabel("Simulation time (s)")
    fig.suptitle("M4 position residual, fixed threshold, offline labels and predictions")
    fig.tight_layout(); fig.savefig(output, dpi=160); plt.close(fig)


def run_workflow(config_path: Path, run_id: str, *, output_root: Path | None = None) -> list[dict[str, Any]]:
    """Calibrate on M2 normal data, evaluate M2 holdout and M3 offset/jump/drift."""
    if not run_id or not all(c.isalnum() or c in "-_" for c in run_id):
        raise ValueError("run_id must contain only letters, numbers, hyphens and underscores")
    config_path = config_path.resolve()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    root = config_path.parent.parent
    settings = config["m4"]
    paths = settings["datasets"]
    resolve = lambda value: (config_path.parent / value).resolve()
    normal_truth = resolve(paths["normal"]["truth_file"])
    normal_gps = resolve(paths["normal"]["gps_file"])
    threshold, calibration_keys, normal_eval_keys, calibration = calibrate_threshold(
        normal_truth, normal_gps,
        quantile=float(settings["threshold"]["normal_quantile"]),
        calibration_fraction=float(settings["threshold"]["calibration_fraction"]))
    base_output = output_root.resolve() if output_root else resolve(settings["output_dir"])
    output = base_output / run_id
    output.mkdir(parents=True, exist_ok=False)
    shutil.copy2(config_path, output / "experiment_config.yaml")
    metadata = {"milestone": "M4", "detector": "position_residual_threshold",
                "detector_type": "oracle-assisted offline research baseline; not GPS-only/deployable",
                "inputs_to_prediction": ["SUMO ground truth x_m/y_m", "GPS gps_x_m/gps_y_m"],
                "attack_labels_used_for_prediction": False, "coordinate_units": "SUMO local X/Y meters",
                "threshold_calibration": calibration, "threshold_fixed_m": threshold,
                "configuration_file": str(config_path), "run_id": run_id}
    (output / "run_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    normal_predictions, normal_match = predict_position_residuals(
        normal_truth, normal_gps, threshold, evaluation_keys=normal_eval_keys)
    _write_csv(output / "normal_predictions.csv", PREDICTION_FIELDS, normal_predictions)
    normal_labels = {key: 0 for key in calibration_keys | normal_eval_keys}
    results = [_score_scenario(normal_predictions, normal_labels, scenario="normal",
                               threshold_m=threshold, match_stats=normal_match,
                               evaluation_keys=normal_eval_keys)]
    normal_eval_predictions = [row for row in normal_predictions
                               if (row["time_s"], row["vehicle_id"]) in normal_eval_keys]
    normal_eval_labels = {key: value for key, value in normal_labels.items() if key in normal_eval_keys}
    plot_data = [("normal", normal_eval_predictions, normal_eval_labels)]
    for scenario in ("offset", "jump", "drift"):
        dataset = paths["attacks"][scenario]
        truth_path, gps_path, labels_path = map(resolve, (dataset["truth_file"], dataset["gps_file"], dataset["labels_file"]))
        predictions, match_stats = predict_position_residuals(truth_path, gps_path, threshold)
        labels = _read_labels(labels_path)
        _write_csv(output / f"{scenario}_predictions.csv", PREDICTION_FIELDS, predictions)
        result = _score_scenario(predictions, labels, scenario=scenario,
                                 threshold_m=threshold, match_stats=match_stats)
        results.append(result); plot_data.append((scenario, predictions, labels))
        (output / f"{scenario}_metrics.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    normal_result = results[0]
    normal_result["calibration_observations"] = calibration["calibration_observations"]
    normal_result["normal_evaluation_observations"] = calibration["normal_evaluation_observations"]
    normal_result["threshold_quantile"] = calibration["threshold_quantile"]
    (output / "normal_metrics.json").write_text(json.dumps(normal_result, indent=2) + "\n", encoding="utf-8")
    _write_csv(output / "summary.csv", SCORE_FIELDS,
               [{key: result.get(key) for key in SCORE_FIELDS} for result in results])
    _plot_confusions(results, output / "confusion_matrices.png")
    _plot_scores(results, output / "attack_scores.png")
    _plot_timeseries(plot_data, threshold, output / "residuals_labels_predictions.png")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/experiment_config.yaml"))
    parser.add_argument("--run-id", required=True, help="new output folder name; existing folders are never overwritten")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        for result in run_workflow(args.config, args.run_id):
            LOGGER.info("M4 metrics: %s", json.dumps(result, sort_keys=True))
    except Exception as exc:
        LOGGER.error("M4 workflow failed: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
