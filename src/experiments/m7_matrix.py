"""Full paired M7 test matrix using frozen M5 detector thresholds."""
from __future__ import annotations

import argparse
import csv
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

from src.experiments.m7_energy_routing import (
    _write_csv, compile_network, run_one, validate_network,
)

LOGGER = logging.getLogger("m7_matrix")
ATTACKS = ("offset", "jump", "drift")
ARMS = ("unprotected_spoofed", "protected_spoofed")
METRICS = ("route_distance_m", "travel_time_s", "energy_consumed_wh",
           "energy_regenerated_wh", "soc_change")


def build_matrix(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Build calibration/validation normal controls and paired final-test rows."""
    matrix = []
    offset = int(config["matrix"]["gps_seed_offset"])
    for split in ("calibration", "validation"):
        for seed in config["matrix"]["seeds"][split]:
            matrix.append({"split": split, "attack_type": "none", "condition": "normal_navigation",
                "seed": int(seed), "gps_seed": offset + int(seed), "pair_id": f"normal_{split}_{seed}",
                "attack_parameters": dict(config["gps"]["attacks"]["none"])})
    for seed in config["matrix"]["seeds"]["test"]:
        seed = int(seed)
        matrix.append({"split": "test", "attack_type": "none", "condition": "normal_navigation",
            "seed": seed, "gps_seed": offset + seed,
            "pair_id": f"normal_test_seed{seed}",
            "attack_parameters": dict(config["gps"]["attacks"]["none"])})
        for attack in ATTACKS:
            settings = config["matrix"]["attacks"][attack]
            for magnitude in settings["magnitudes_m"]:
                for duration in settings["durations_s"]:
                    params = {"onset_s": float(settings["onset_s"]),
                        "duration_s": float(duration), "magnitude_m": float(magnitude),
                        "drift_rate_mps": float(settings.get("drift_rate_mps", 0.0))}
                    if "direction_deg" in settings:
                        params["direction_deg"] = float(settings["direction_deg"])
                    pair = f"{attack}_m{magnitude:g}_d{duration:g}_seed{seed}"
                    for arm in ARMS:
                        matrix.append({"split": "test", "attack_type": attack,
                            "condition": arm, "seed": seed, "gps_seed": offset + seed,
                            "pair_id": pair, "attack_parameters": params})
    return matrix


def _rate(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [row.get(key) for row in rows if row.get(key) is not None]
    return float(np.mean([float(value) for value in values])) if values else None


def aggregate_runs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate by split, attack, and condition; std is sample std."""
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((row["split"], row["attack_type"], row["condition"]), []).append(row)
    output = []
    for (split, attack, condition), group in sorted(groups.items()):
        item: dict[str, Any] = {"split": split, "attack_type": attack,
            "condition": condition, "n_runs": len(group)}
        for metric in METRICS:
            vals = [float(row[metric]) for row in group if row.get(metric) is not None]
            item[f"{metric}_n"] = len(vals)
            item[f"{metric}_mean"] = float(np.mean(vals)) if vals else None
            item[f"{metric}_std"] = float(np.std(vals, ddof=1)) if len(vals) > 1 else (0.0 if vals else None)
            item[f"{metric}_median"] = float(np.median(vals)) if vals else None
        item["arrival_rate"] = _rate(group, "destination_arrived")
        item["detection_rate"] = _rate(group, "attack_detected") if attack != "none" else None
        item["post_attack_alert_rate"] = _rate(group, "post_attack_alert") if attack != "none" else None
        item["false_positive_rate_per_fix"] = (
            sum(int(row["detector_alert_count"]) for row in group)
            / sum(int(row["eligible_fix_count"]) for row in group)
            if attack == "none" and sum(int(row["eligible_fix_count"]) for row in group) else None)
        item["fallback_activation_rate"] = _rate(group, "protected_fallback_activated")
        item["mitigation_success_rate"] = _rate(group, "mitigation_success")
        item["reroutes_mean"] = float(np.mean([row["reroute_count"] for row in group]))
        item["battery_telemetry_completeness"] = _rate(group, "battery_telemetry_available")
        output.append(item)
    return output


def paired_comparisons(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compute protected-minus-unprotected deltas and conservative mitigation."""
    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        if row["split"] == "test" and row["attack_type"] in ATTACKS:
            grouped.setdefault(row["pair_id"], {})[row["condition"]] = row
    result = []
    for pair_id, pair in sorted(grouped.items()):
        if set(pair) != set(ARMS):
            raise ValueError(f"incomplete paired run {pair_id}: {sorted(pair)}")
        unprotected, protected = pair[ARMS[0]], pair[ARMS[1]]
        better = False
        if protected["destination_arrived"] and not unprotected["destination_arrived"]:
            better = True
        elif protected["destination_arrived"] and unprotected["destination_arrived"]:
            pd, ud = protected.get("route_distance_m"), unprotected.get("route_distance_m")
            better = pd is not None and ud is not None and float(pd) + 1.0 < float(ud)
        success = bool(protected["protected_fallback_activated"] and better)
        row: dict[str, Any] = {"pair_id": pair_id, "attack_type": protected["attack_type"],
            "seed": protected["seed"], "attack_parameters": protected["attack_parameters"],
            "unprotected_arrived": unprotected["destination_arrived"],
            "protected_arrived": protected["destination_arrived"],
            "unprotected_fallback_activated": unprotected["protected_fallback_activated"],
            "protected_fallback_activated": protected["protected_fallback_activated"],
            "mitigation_success": success,
            "unprotected_attack_detected": unprotected.get("attack_detected"),
            "protected_attack_detected": protected.get("attack_detected"),
            "unprotected_post_attack_alert": unprotected.get("post_attack_alert"),
            "protected_post_attack_alert": protected.get("post_attack_alert"),
            "unprotected_detection_delay_s": unprotected.get("detection_delay_s"),
            "protected_detection_delay_s": protected.get("detection_delay_s"),
            "protected_post_attack_alert_delay_s": protected.get("post_attack_alert_delay_s"),
            "unprotected_executed_edges": unprotected["executed_edges"],
            "protected_executed_edges": protected["executed_edges"],
            "unprotected_route_changes": unprotected["reroute_count"],
            "protected_route_changes": protected["reroute_count"]}
        for metric in METRICS:
            u, p = unprotected.get(metric), protected.get(metric)
            row[f"unprotected_{metric}"] = u
            row[f"protected_{metric}"] = p
            row[f"protected_minus_unprotected_{metric}"] = (
                float(p) - float(u) if p is not None and u is not None else None)
        result.append(row)
    return result


def aggregate_pairs(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Summarize paired deltas by attack and configured magnitude/duration."""
    groups: dict[tuple[str, float, float], list[dict[str, Any]]] = {}
    for row in pairs:
        params = row["attack_parameters"]
        groups.setdefault((row["attack_type"], float(params["magnitude_m"]),
                           float(params["duration_s"])), []).append(row)
    output = []
    for (attack, magnitude, duration), group in sorted(groups.items()):
        item: dict[str, Any] = {"attack_type": attack, "magnitude_m": magnitude,
            "duration_s": duration, "n_pairs": len(group),
            "mitigation_success_rate": _rate(group, "mitigation_success"),
            "protected_arrival_rate": _rate(group, "protected_arrived"),
            "unprotected_arrival_rate": _rate(group, "unprotected_arrived"),
            "fallback_activation_rate": _rate(group, "protected_fallback_activated")}
        item["protected_detection_rate"] = _rate(group, "protected_attack_detected")
        item["unprotected_detection_rate"] = _rate(group, "unprotected_attack_detected")
        item["protected_post_attack_alert_rate"] = _rate(group, "protected_post_attack_alert")
        item["unprotected_post_attack_alert_rate"] = _rate(group, "unprotected_post_attack_alert")
        for label, source in (("protected_detection_delay_s", "protected_detection_delay_s"),
                              ("unprotected_detection_delay_s", "unprotected_detection_delay_s"),
                              ("protected_post_attack_alert_delay_s", "protected_post_attack_alert_delay_s")):
            vals = [float(row[source]) for row in group if row.get(source) is not None]
            item[f"{label}_mean"] = float(np.mean(vals)) if vals else None
            item[f"{label}_std"] = float(np.std(vals, ddof=1)) if len(vals) > 1 else (0.0 if vals else None)
        for metric in METRICS:
            vals = [float(row[f"protected_minus_unprotected_{metric}"]) for row in group
                    if row.get(f"protected_minus_unprotected_{metric}") is not None]
            item[f"delta_{metric}_n"] = len(vals)
            item[f"delta_{metric}_mean"] = float(np.mean(vals)) if vals else None
            item[f"delta_{metric}_std"] = float(np.std(vals, ddof=1)) if len(vals) > 1 else (0.0 if vals else None)
            item[f"delta_{metric}_median"] = float(np.median(vals)) if vals else None
        output.append(item)
    return output


def _annotate_detection(row: dict[str, Any], attack: dict[str, float]) -> None:
    onset = float(attack["onset_s"])
    end = onset + float(attack["duration_s"])
    alerts = [float(value) for value in row["detector_alert_times_s"]]
    # Attack generation uses a half-open interval: the first fix at `end` is
    # already clean, so an alert then is post-attack and cannot mitigate it.
    hits = [value for value in alerts if onset <= value < end]
    late_hits = [value for value in alerts if end <= value <= end + 10.0]
    row["attack_detected"] = bool(hits)
    row["detection_delay_s"] = min(hits) - onset if hits else None
    row["post_attack_alert"] = bool(late_hits)
    row["post_attack_alert_delay_s"] = min(late_hits) - onset if late_hits else None


def rebuild_summaries(output: Path) -> None:
    """Recalculate machine-readable aggregates from immutable per-run summaries."""
    rows = json.loads((output / "per_run_results.json").read_text(encoding="utf-8"))
    for row in rows:
        telemetry_path = (output / "runs" / row["pair_id"] / row["attack_type"] /
                          row["condition"] / "telemetry.csv")
        telemetry = _read_csv(telemetry_path)
        consumed = [float(t["energy_total_consumed_wh"]) for t in telemetry
                    if t.get("energy_total_consumed_wh") not in (None, "")]
        regenerated = [float(t["energy_total_regenerated_wh"]) for t in telemetry
                       if t.get("energy_total_regenerated_wh") not in (None, "")]
        charge = [float(t["battery_charge_wh"]) for t in telemetry
                  if t.get("battery_charge_wh") not in (None, "")]
        capacities = [float(t["battery_capacity_wh"]) for t in telemetry
                      if t.get("battery_capacity_wh") not in (None, "")]
        soc_values = [float(t["soc"]) for t in telemetry if t.get("soc") not in (None, "")]
        row["energy_consumed_wh"] = consumed[-1] if consumed else None
        row["energy_regenerated_wh"] = regenerated[-1] if regenerated else None
        row["initial_battery_charge_wh"] = 25000.0 if charge else None
        row["final_battery_charge_wh"] = charge[-1] if charge else None
        row["initial_soc"] = 25000.0 / capacities[-1] if capacities else None
        row["final_soc"] = soc_values[-1] if soc_values else None
        row["soc_change"] = (row["final_soc"] - row["initial_soc"]
                             if row["final_soc"] is not None and row["initial_soc"] is not None else None)
        if row["attack_type"] in ATTACKS:
            params = row["attack_parameters"]
            _annotate_detection(row, params)
        else:
            row.update({"attack_detected": None, "detection_delay_s": None,
                        "post_attack_alert": None, "post_attack_alert_delay_s": None})
    pairs = paired_comparisons(rows)
    pair_lookup = {row["pair_id"]: row for row in pairs}
    for row in rows:
        if row["attack_type"] in ATTACKS:
            row["mitigation_success"] = (pair_lookup[row["pair_id"]]["mitigation_success"]
                if row["condition"] == "protected_spoofed" else False)
        else:
            row["mitigation_success"] = None
    aggregates, pair_aggregates = aggregate_runs(rows), aggregate_pairs(pairs)
    _write_json_csv(output, "per_run_results", rows)
    _write_json_csv(output, "paired_comparisons", pairs)
    _write_json_csv(output, "aggregate_results", aggregates)
    _write_json_csv(output, "paired_aggregate_results", pair_aggregates)
    _plot_rates(aggregates, output / "detection_fallback_mitigation_rates.png")
    _plot_paired(pairs, output / "paired_differences.png")


def _write_json_csv(output: Path, stem: str, rows: list[dict[str, Any]]) -> None:
    (output / f"{stem}.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    fields = list(dict.fromkeys(key for row in rows for key in row)) if rows else []
    with (output / f"{stem}.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)


def _plot_rates(aggregates: list[dict[str, Any]], path: Path) -> None:
    test = [row for row in aggregates if row["split"] == "test" and row["attack_type"] != "none"]
    attacks = list(ATTACKS)
    x = np.arange(len(attacks)); width = 0.18
    fig, ax = plt.subplots(figsize=(9, 5))
    for idx, (metric, label, color) in enumerate((
        ("detection_rate", "M5 alert during attack", "tab:blue"),
        ("post_attack_alert_rate", "M5 alert after attack", "tab:red"),
        ("fallback_activation_rate", "Oracle fallback", "tab:orange"),
        ("mitigation_success_rate", "Mitigation success", "tab:green"),
    )):
        values = []
        for attack in attacks:
            subset = [row[metric] for row in test if row["attack_type"] == attack
                      and row["condition"] == "protected_spoofed" and row[metric] is not None]
            values.append(float(np.mean(subset)) if subset else 0.0)
        ax.bar(x + (idx - 1.5) * width, values, width, label=label, color=color)
    ax.set(xticks=x, xticklabels=[name.title() for name in attacks], ylim=(0, 1.05),
           ylabel="Rate", title="Test attack detection, fallback, and mitigation rates")
    ax.legend(); fig.tight_layout(); fig.savefig(path, dpi=160); plt.close(fig)


def _plot_paired(pairs: list[dict[str, Any]], path: Path) -> None:
    attacks = list(ATTACKS)
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.5))
    for ax, (metric, title) in zip(axes, (("route_distance_m", "Distance (m)"),
                                          ("travel_time_s", "Travel time (s)"),
                                          ("energy_consumed_wh", "Energy (Wh)"))):
        data = [[float(row[f"protected_minus_unprotected_{metric}"])
                 for row in pairs if row["attack_type"] == attack
                 and row.get(f"protected_minus_unprotected_{metric}") is not None]
                for attack in attacks]
        ax.axhline(0, color="black", linewidth=.8)
        ax.boxplot(data, tick_labels=[x.title() for x in attacks], showmeans=True)
        ax.set(title=title, ylabel="Protected − unprotected")
    fig.suptitle("Paired protected-minus-unprotected test differences")
    fig.tight_layout(); fig.savefig(path, dpi=160); plt.close(fig)


def run_full_matrix(config_path: Path, run_id: str) -> Path:
    """Run every configured calibration, validation, and test trip in a new dir."""
    if not run_id or not all(c.isalnum() or c in "-_" for c in run_id):
        raise ValueError("run_id may contain only letters, numbers, hyphens and underscores")
    config_path = config_path.resolve()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    root = config_path.parent.parent.resolve()
    net = compile_network(root)
    network_validation = validate_network(net)
    matrix = build_matrix(config)
    expected = (len(config["matrix"]["seeds"]["calibration"])
        + len(config["matrix"]["seeds"]["validation"])
        + len(config["matrix"]["seeds"]["test"]) * (1 + 2 * sum(
            len(v["magnitudes_m"]) * len(v["durations_s"])
            for v in config["matrix"]["attacks"].values())))
    if len(matrix) != expected or len({(r["pair_id"], r["condition"]) for r in matrix}) != len(matrix):
        raise RuntimeError("matrix contains missing or duplicate pair-condition rows")
    output = (config_path.parent / config["output"]["root"] /
              config["output"]["matrix_directory"] / run_id).resolve()
    output.mkdir(parents=True, exist_ok=False)
    shutil.copy2(config_path, output / "experiment_config.yaml")
    rows = []
    for index, record in enumerate(matrix, 1):
        attack = record["attack_type"]
        params = (record["attack_parameters"] if attack != "none" else None)
        row = run_one(root, config, attack_type=attack, condition=record["condition"],
            output_dir=output / "runs" / record["pair_id"], seed_override=record["seed"],
            gps_seed_override=record["gps_seed"], attack_parameters=params,
            pair_id=record["pair_id"], split=record["split"])
        row["expected_attack_onset_s"] = params.get("onset_s") if params else None
        row["expected_attack_duration_s"] = params.get("duration_s") if params else None
        row["eligible_fix_count"] = sum(int(r["m5_eligible"]) for r in _read_csv(
            output / "runs" / record["pair_id"] / attack / record["condition"] / "telemetry.csv"))
        if attack != "none":
            _annotate_detection(row, params)
        else:
            row["attack_detected"] = None
            row["detection_delay_s"] = None
            row["post_attack_alert"] = None
            row["post_attack_alert_delay_s"] = None
        rows.append(row)
        LOGGER.info("M7 matrix %d/%d %s %s", index, len(matrix), record["pair_id"], record["condition"])
    pairs = paired_comparisons(rows)
    pair_lookup = {row["pair_id"]: row for row in pairs}
    for row in rows:
        if row["attack_type"] in ATTACKS:
            row["mitigation_success"] = pair_lookup[row["pair_id"]]["mitigation_success"] if row["condition"] == "protected_spoofed" else False
        else:
            row["mitigation_success"] = None
    aggregates = aggregate_runs(rows)
    pair_aggregates = aggregate_pairs(pairs)
    if len(rows) != expected or len(pairs) != sum(1 for r in matrix if r["split"] == "test" and r["attack_type"] != "none") // 2:
        raise RuntimeError("completed run or paired comparison count does not match matrix")
    fields = list(dict.fromkeys(k for r in rows for k in r))
    _write_csv(output / "per_run_results.csv", fields, rows)
    _write_csv(output / "paired_comparisons.csv", list(dict.fromkeys(k for r in pairs for k in r)), pairs)
    _write_csv(output / "aggregate_results.csv", list(dict.fromkeys(k for r in aggregates for k in r)), aggregates)
    _write_csv(output / "paired_aggregate_results.csv",
               list(dict.fromkeys(k for r in pair_aggregates for k in r)), pair_aggregates)
    (output / "per_run_results.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    (output / "paired_comparisons.json").write_text(json.dumps(pairs, indent=2) + "\n", encoding="utf-8")
    (output / "aggregate_results.json").write_text(json.dumps(aggregates, indent=2) + "\n", encoding="utf-8")
    (output / "paired_aggregate_results.json").write_text(json.dumps(pair_aggregates, indent=2) + "\n", encoding="utf-8")
    _plot_rates(aggregates, output / "detection_fallback_mitigation_rates.png")
    _plot_paired(pairs, output / "paired_differences.png")
    metadata = {"milestone": "M7 Stage 2 full paired matrix", "run_id": run_id,
        "run_count": len(rows), "paired_attack_comparisons": len(pairs),
        "network_validation": network_validation,
        "seed_splits": config["matrix"]["seeds"],
        "final_test_attacks_only": True,
        "threshold_provenance": "Frozen M5 thresholds from M6 normal calibration trips; M7 calibration/validation/test outputs do not tune thresholds",
        "attack_detection_definition": "M5 alert during the half-open active attack interval [onset, end); post-attack alerts through end+10s are reported separately and do not count as detection",
        "false_positive_definition": "M5 alerts divided by eligible GPS fixes in test split normal-GPS runs",
        "mitigation_definition": "Protected fallback activated and protected run arrives with lower odometer distance by >1 m, or protected arrives while unprotected does not",
        "protected_fallback": "Oracle-assisted SUMO shortest route from current edge, called only after M5 alert",
        "attack_labels_outside_m5": True,
        "outputs_excluded_from_reproducibility_comparison": {"run_metadata.json": "contains intentionally different run_id"}}
    (output / "run_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return output


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/m7_energy_routing.yaml"))
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print(run_full_matrix(args.config, args.run_id))


if __name__ == "__main__":
    main()
