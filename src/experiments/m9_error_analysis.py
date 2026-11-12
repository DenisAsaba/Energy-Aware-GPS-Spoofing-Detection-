"""M9 Stage 1: historical M5/M8 error analysis and validation-only fusion.

The command never opens the configured final-test seeds. It writes only beneath
reports/m9/<run-id>/ and refuses to reuse an output ID.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import math
import re
import shutil
from pathlib import Path
from typing import Any

import yaml

from src.attacks.gps_attacks import generate_attack
from src.detection.gps_only import apply_temporal_thresholds
from src.detection.m8_detector import apply_m8_thresholds, extract_m8_features
from src.detection.m9_hybrid import align_and_fuse
from src.experiments.m8_stage2a_scenarios import build_scenario_inputs, scenario_manifest
from src.sensors.gps_normal import generate_observations
from src.simulation.run_sumo import run as run_sumo

LOG = logging.getLogger("m9_stage1")
ATTACKS = ("offset", "jump", "drift")
SYSTEMS = ("M5", "M8", "OR", "AND", "staged_suspect", "staged_corroborated")


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError(f"missing or duplicate CSV headers: {path}")
        return list(reader)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("x", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8", newline="") as f:
        json.dump(value, f, indent=2, sort_keys=True)
        f.write("\n")


def _read_labels(path: Path) -> dict[tuple[float, str], int]:
    labels: dict[tuple[float, str], int] = {}
    for row in _read_csv(path):
        key = (float(row["time_s"]), row["vehicle_id"])
        if key in labels:
            raise ValueError(f"duplicate label key in {path}: {key}")
        value = row.get("attack_active")
        if value not in ("0", "1"):
            raise ValueError(f"invalid attack_active label in {path}: {value}")
        labels[key] = int(value)
    return labels


def _flag(value: Any) -> int:
    return int(value in (1, True, "1", "True", "true"))


def _key(row: dict[str, Any]) -> tuple[float, str]:
    return float(row["time_s"]), str(row["vehicle_id"])


def _metrics(rows: list[dict[str, Any]], labels: dict[tuple[float, str], int], pred_field: str) -> dict[str, Any]:
    pred_by_key = {_key(r): _flag(r.get(pred_field)) for r in rows if _flag(r.get("eligible"))}
    matched = pred_by_key.keys() & labels.keys()
    tp = sum(pred_by_key[k] == 1 and labels[k] == 1 for k in matched)
    fp = sum(pred_by_key[k] == 1 and labels[k] == 0 for k in matched)
    tn = sum(pred_by_key[k] == 0 and labels[k] == 0 for k in matched)
    fn = sum(pred_by_key[k] == 0 and labels[k] == 1 for k in matched)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    delay = ""
    active_times = [k[0] for k in matched if labels[k] == 1]
    hit_times = [k[0] for k in matched if labels[k] == 1 and pred_by_key[k] == 1]
    if active_times and hit_times:
        delay = min(hit_times) - min(active_times)
    return {
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "precision": precision, "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "fpr": fp / (fp + tn) if fp + tn else 0.0,
        "tnr": tn / (tn + fp) if tn + fp else 0.0,
        "eligible_observations": len(matched),
        "unmatched_prediction_count": len(pred_by_key.keys() - labels.keys()),
        "unmatched_label_count": len(labels.keys() - pred_by_key.keys()),
        "attack_event_detected": int(bool(hit_times)) if active_times else "",
        "missed_attack_event": int(bool(active_times) and not hit_times) if active_times else "",
        "detection_delay_s": delay,
    }


def _joined_predictions(rows: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    m5 = [{"time_s": r["time_s"], "vehicle_id": r["vehicle_id"], "eligible": r.get("eligible"),
           "predicted_attack": r.get("m5_predicted_attack", "")} for r in rows]
    m8 = [{"time_s": r["time_s"], "vehicle_id": r["vehicle_id"], "eligible": r.get("eligible"),
           "predicted_attack": r.get("predicted_attack", "")} for r in rows]
    det = config["detector"]
    return align_and_fuse(m5, m8,
                          association_window=int(det["staged_association_window_eligible_observations"]),
                          clear_after_joint_clean=int(det["staged_clear_after_joint_clean_observations"]))


def _history_analysis(root: Path, config: dict[str, Any], out: Path) -> dict[str, int]:
    base = root / config["historical_analysis"]["source_run"]
    predroot = base / "predictions"
    overlap_rows: list[dict[str, Any]] = []
    metric_rows: list[dict[str, Any]] = []
    fp_rows: list[dict[str, Any]] = []
    persistence_rows: list[dict[str, Any]] = []
    files = sorted(predroot.glob("final_*/**/*.csv"))
    if not files:
        raise FileNotFoundError(f"historical M8 predictions not found: {predroot}")
    for pred_path in files:
        dataset = pred_path.stem
        trip = pred_path.parent.name
        scenario = trip.removeprefix("final_").rsplit("_seed", 1)[0]
        seed_text = trip.rsplit("_seed", 1)[-1]
        rows = _read_csv(pred_path)
        fused = _joined_predictions(rows, config)
        fused_by_key = {_key(r): r for r in fused}
        is_normal = dataset == "none"
        labels_path = base / "attacks" / trip / f"{dataset}_labels.csv"
        labels = ({(_float(r.get("time_s")), str(r.get("vehicle_id"))): 0 for r in rows
                   if _float(r.get("time_s")) is not None} if is_normal else _read_labels(labels_path))
        active_times = [key[0] for key, active in labels.items() if active]
        attack_end = max(active_times) + 1.0 if active_times else math.inf
        # Labels are joined only after historical predictions and fusion outputs are read.
        types: dict[tuple[str, str], dict[str, int]] = {}
        for r in fused:
            k = _key(r)
            if not _flag(r.get("joint_eligible")):
                continue
            cls = "attack" if labels.get(k, 0) else "normal"
            bucket = types.setdefault((cls, cls), {"both": 0, "m5_only": 0, "m8_only": 0, "neither": 0})
            m5f, m8f = _flag(r.get("m5_prediction")), _flag(r.get("m8_prediction"))
            category = "both" if m5f and m8f else "m5_only" if m5f else "m8_only" if m8f else "neither"
            bucket[category] += 1
            overlap_rows.append({"trip_id": trip, "seed": seed_text, "profile": scenario,
                                 "dataset": dataset, "observation_time_s": k[0],
                                 "vehicle_id": k[1], "class": cls, **r,
                                 "overlap_category": category})
        pred_by_name = {
            "M5": ({_key(r): {**r, "pred": r.get("m5_predicted_attack", "")} for r in rows}),
            "M8": ({_key(r): {**r, "pred": r.get("predicted_attack", "")} for r in rows}),
            "OR": ({_key(r): {**fused_by_key[_key(r)], "eligible": fused_by_key[_key(r)].get("joint_eligible"), "pred": fused_by_key[_key(r)].get("or_prediction", "")} for r in fused}),
            "AND": ({_key(r): {**fused_by_key[_key(r)], "eligible": fused_by_key[_key(r)].get("joint_eligible"), "pred": fused_by_key[_key(r)].get("and_prediction", "")} for r in fused}),
            "staged_suspect": ({_key(r): {**fused_by_key[_key(r)], "eligible": fused_by_key[_key(r)].get("joint_eligible"), "pred": fused_by_key[_key(r)].get("m5_fast_suspect", "")} for r in fused}),
            "staged_corroborated": ({_key(r): {**fused_by_key[_key(r)], "eligible": fused_by_key[_key(r)].get("joint_eligible"), "pred": fused_by_key[_key(r)].get("corroborated_suspicion", "")} for r in fused}),
        }
        for system, predmap in pred_by_name.items():
            score = _metrics(list(predmap.values()), labels, "pred")
            post_den = sum(1 for k in predmap if k in labels and k[0] >= attack_end)
            post_alerts = sum(_flag(r.get("pred")) for k, r in predmap.items()
                              if k in labels and k[0] >= attack_end) if not is_normal else 0
            intensity, duration = _attack_parameters(dataset)
            metric_rows.append({"trip_id": trip, "seed": seed_text, "profile": scenario,
                                "dataset": dataset, "attack_type": "none" if is_normal else _attack_type(dataset),
                                "attack_intensity": intensity, "attack_duration_s": duration,
                                "attack_end_s": "" if is_normal else attack_end,
                                "detector": system, "post_attack_alerts": post_alerts,
                                "post_attack_alert_rate": post_alerts / post_den if post_den else 0.0,
                                **score})
        for row in rows:
            k = _key(row)
            if is_normal and labels.get(k, 0) == 0 and (
                _flag(row.get("m5_predicted_attack")) or _flag(row.get("predicted_attack"))
            ):
                fp_rows.append({"trip_id": trip, "seed": seed_text, "profile": scenario,
                                "time_s": k[0], "m5_alert": _flag(row.get("m5_predicted_attack")),
                                "m8_alert": _flag(row.get("predicted_attack")),
                                "m8_raw_anomaly": row.get("m8_raw_anomaly"),
                                "m8_raw_rules": row.get("m8_raw_rules"),
                                "estimated_speed_mps": row.get("estimated_speed_mps"),
                                "speed_change_mps": row.get("speed_change_mps"),
                                "heading_change_deg": row.get("heading_change_deg"),
                                "abs_acceleration_mps2": row.get("abs_acceleration_mps2"),
                                "speed_consistency_mps": row.get("speed_consistency_mps")})
        by_vehicle: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            by_vehicle.setdefault(row["vehicle_id"], []).append(row)
        for vehicle, seq in by_vehicle.items():
            prior = 0
            start = None
            for row in seq:
                if not _flag(row.get("eligible")):
                    continue
                active = _flag(row.get("predicted_attack"))
                t = float(row["time_s"])
                if active and not prior:
                    start = t
                    persistence_rows.append({"trip_id": trip, "dataset": dataset, "vehicle_id": vehicle,
                                             "transition": "activated", "time_s": t, "duration_eligible_fixes": ""})
                if prior and not active:
                    persistence_rows.append({"trip_id": trip, "dataset": dataset, "vehicle_id": vehicle,
                                             "transition": "cleared", "time_s": t,
                                             "duration_eligible_fixes": _elapsed_fixes(seq, start, t)})
                    start = None
                prior = active
    _write_csv(out / "joint_prediction_overlap.csv", overlap_rows)
    _write_csv(out / "historical_error_metrics.csv", metric_rows)
    _write_csv(out / "historical_normal_false_positives.csv", fp_rows)
    _write_csv(out / "historical_m8_persistence_transitions.csv", persistence_rows)
    return {"prediction_datasets": len(files), "overlap_observations": len(overlap_rows),
            "normal_false_positive_records": len(fp_rows), "persistence_transitions": len(persistence_rows)}


def _float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _attack_type(dataset: str) -> str:
    return next((kind for kind in ATTACKS if dataset.startswith(kind + "_")), "unknown")


def _elapsed_fixes(rows: list[dict[str, str]], start: float | None, end: float) -> int | str:
    if start is None:
        return ""
    return sum(start <= float(r["time_s"]) < end and _flag(r.get("eligible")) for r in rows)


def _stable_seed(offset: int, seed: int, scenario: str) -> int:
    token = f"{offset}:{seed}:{scenario}".encode()
    return int.from_bytes(hashlib.sha256(token).digest()[:4], "big")


def _attack_parameters(dataset: str) -> tuple[float | str, float | str]:
    match = re.search(r"(?:magnitude_m|rate_mps)_([0-9.]+)_duration_([0-9.]+)s$", dataset)
    return (float(match.group(1)), float(match.group(2))) if match else ("", "")


def _trip(root: Path, cfg: dict[str, Any], out: Path, split: str, seed: int, scenario: str) -> dict[str, Any]:
    trip_id = f"{split}_{scenario}_seed{seed}"
    trip_dir = out / "trips" / trip_id
    trip_dir.mkdir(parents=True, exist_ok=False)
    inputs = build_scenario_inputs(trip_dir / "inputs", scenario, seed)
    sim = {"seed": int(seed), "step_length_s": float(cfg["simulation"]["step_length_s"]),
           "begin_s": int(cfg["simulation"]["begin_s"]), "end_s": int(cfg["simulation"]["end_s"]),
           "vehicle_id": "ev_001", "network_file": str(inputs["network"]),
           "route_file": str(inputs["routes"]), "telemetry_output_dir": str(trip_dir), "depart_s": 0}
    sim_config = trip_dir / "simulation_config.yaml"
    sim_config.write_text(yaml.safe_dump({"simulation": sim}, sort_keys=True), encoding="utf-8")
    truth, gps = trip_dir / "truth.csv", trip_dir / "normal_gps.csv"
    run_sumo(sim_config, output_path=truth)
    gps_seed = _stable_seed(int(cfg["gps"]["seed_offset"]), seed, scenario)
    generate_observations(truth, gps, noise_std_m=float(cfg["gps"]["noise_std_m_per_axis"]), seed=gps_seed)
    return {"trip_id": trip_id, "split": split, "seed": seed, "scenario": scenario,
            "gps_seed": gps_seed, "truth": truth, "gps": gps,
            "input_hashes": {k: _sha(v) for k, v in inputs.items()},
            "truth_sha256": _sha(truth), "gps_sha256": _sha(gps),
            "traffic_vehicles": scenario_manifest()[scenario]["traffic"]}


def _predict(gps_path: Path, cfg: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    # The feature extractor receives GPS columns only; labels are not loaded here.
    features = extract_m8_features(gps_path, rolling_speed_window=int(cfg["detector"]["rolling_speed_window"]))
    m5 = apply_temporal_thresholds(features, cfg["detector"]["m5_thresholds"])
    m8 = apply_m8_thresholds(features, cfg["detector"]["m8_thresholds"], cfg["detector"]["m8_persistence"])
    hybrid = align_and_fuse(m5, m8,
                            association_window=int(cfg["detector"]["staged_association_window_eligible_observations"]),
                            clear_after_joint_clean=int(cfg["detector"]["staged_clear_after_joint_clean_observations"]))
    return m5, m8, hybrid


def _record_predictions(out: Path, trip_id: str, dataset_id: str,
                        m5: list[dict[str, Any]], m8: list[dict[str, Any]], hybrid: list[dict[str, Any]]) -> Path:
    directory = out / "predictions" / trip_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{dataset_id}.csv"
    hmap = {_key(r): r for r in hybrid}
    m8map = {_key(r): r for r in m8}
    rows = []
    for r in m5:
        k = _key(r)
        rows.append({"time_s": k[0], "vehicle_id": k[1], "eligible": r.get("eligible"),
                     "m5_predicted_attack": r.get("predicted_attack", ""),
                     "m8_predicted_attack": m8map.get(k, {}).get("predicted_attack", ""),
                     **hmap[k]})
    _write_csv(path, rows)
    return path


def _validation_workflow(root: Path, cfg: dict[str, Any], out: Path, smoke: bool) -> dict[str, Any]:
    count = int(cfg.get("smoke_seed_count", 3)) if smoke else 6
    seed_splits = cfg["splits"]
    cal_seeds = [int(s) for s in seed_splits["calibration"][:count]]
    val_seeds = [int(s) for s in seed_splits["validation"][:count]]
    scenarios = list(cfg["scenarios"])
    if count not in (3, 6) or len(scenarios) != 3:
        raise ValueError("M9 supports 3-seed smoke or 6-seed full validation across three profiles")
    if set(cal_seeds) & set(val_seeds) or set(val_seeds) & set(seed_splits["final_test"]):
        raise ValueError("M9 split seed overlap")
    manifest: list[dict[str, Any]] = []
    normal_rows: list[dict[str, Any]] = []
    result_rows: list[dict[str, Any]] = []
    trip_summaries: list[dict[str, Any]] = []
    for split, seeds in (("calibration", cal_seeds), ("validation", val_seeds)):
        for index, seed in enumerate(seeds):
            scenario = scenarios[index % len(scenarios)]
            trip = _trip(root, cfg, out, split, seed, scenario)
            manifest.append({k: v for k, v in trip.items() if k not in ("truth", "gps")})
            datasets: list[tuple[str, Path, Path | None, dict[str, Any] | None]] = [("none", trip["gps"], None, None)]
            if split == "validation":
                for kind in ATTACKS:
                    settings = dict(cfg["attacks"][kind])
                    settings["attack_id"] = f"{trip['trip_id']}_{kind}"
                    attack_path = out / "attacks" / trip["trip_id"] / f"{kind}.csv"
                    attack_path.parent.mkdir(parents=True, exist_ok=True)
                    _, labels_path = generate_attack(trip["truth"], attack_path, attack_type=kind,
                        settings=settings, noise_std_m=float(cfg["gps"]["noise_std_m_per_axis"]), seed=trip["gps_seed"])
                    datasets.append((kind, attack_path, labels_path, settings))
            for dataset_id, gps_path, labels_path, settings in datasets:
                m5, m8, hybrid = _predict(gps_path, cfg)
                pred_path = _record_predictions(out, trip["trip_id"], dataset_id, m5, m8, hybrid)
                # Read/join labels only after all five-system predictions are materialized.
                keys = [_key(r) for r in m5 if _flag(r.get("eligible"))]
                labels = ({k: 0 for k in keys} if labels_path is None else _read_labels(labels_path))
                pred_maps = {
                    "M5": ({_key(r): {**r, "pred": r.get("predicted_attack")} for r in m5}),
                    "M8": ({_key(r): {**r, "pred": r.get("predicted_attack")} for r in m8}),
                    "OR": ({_key(r): {**r, "eligible": r.get("joint_eligible"), "pred": r.get("or_prediction")} for r in hybrid}),
                    "AND": ({_key(r): {**r, "eligible": r.get("joint_eligible"), "pred": r.get("and_prediction")} for r in hybrid}),
                    "staged_suspect": ({_key(r): {**r, "eligible": r.get("joint_eligible"), "pred": r.get("m5_fast_suspect")} for r in hybrid}),
                    "staged_corroborated": ({_key(r): {**r, "eligible": r.get("joint_eligible"), "pred": r.get("corroborated_suspicion")} for r in hybrid}),
                }
                end_s = float(settings["onset_s"]) + float(settings["duration_s"]) if settings else math.inf
                for system, predmap in pred_maps.items():
                    score = _metrics(list(predmap.values()), labels, "pred")
                    post = sum(_flag(r.get("pred")) for k, r in predmap.items()
                               if k in labels and labels[k] == 0 and k[0] >= end_s) if settings else 0
                    post_den = sum(1 for k in predmap if k in labels and k[0] >= end_s) if settings else 0
                    result_rows.append({"split": split, "trip_id": trip["trip_id"], "seed": seed,
                        "profile": scenario, "dataset": dataset_id, "attack_type": "none" if not settings else dataset_id,
                        "attack_intensity": "" if not settings else settings.get("magnitude_m", settings.get("rate_mps")),
                        "attack_duration_s": "" if not settings else settings["duration_s"],
                        "detector": system, "post_attack_alerts": post,
                        "post_attack_alert_rate": post / post_den if post_den else 0.0, **score})
                if split == "calibration":
                    for system, predmap in pred_maps.items():
                        score = _metrics(list(predmap.values()), labels, "pred")
                        normal_rows.append({"trip_id": trip["trip_id"], "seed": seed,
                                            "profile": scenario, "detector": system, **score})
                trip_summaries.append({"split": split, "trip_id": trip["trip_id"], "seed": seed,
                    "profile": scenario, "dataset": dataset_id, "gps_input_sha256": _sha(gps_path),
                    "prediction_sha256": _sha(pred_path), "labels_joined_after_predictions": True})
    _write_csv(out / "calibration_normal_metrics.csv", normal_rows)
    _write_csv(out / "validation_metrics.csv", result_rows)
    _write_csv(out / "trip_manifest.csv", manifest)
    _write_csv(out / "prediction_manifest.csv", trip_summaries)
    # Policy eligibility is assessed on validation normal trips; the staged
    # system's scored alert is its unsuppressed fast-suspect output.
    normal = [r for r in result_rows if r["split"] == "validation" and r["dataset"] == "none"]
    attack = [r for r in result_rows if r["split"] == "validation" and r["dataset"] != "none"]
    candidates = []
    baseline_summaries = []
    for name, system in (("M5", "M5"), ("M8", "M8")):
        normal_sys = [r for r in normal if r["detector"] == system]
        attack_sys = [r for r in attack if r["detector"] == system]
        baseline_summaries.append({"candidate": name,
            "normal_fp": sum(r["fp"] for r in normal_sys),
            "normal_eligible": sum(r["fp"] + r["tn"] for r in normal_sys),
            "normal_fpr": sum(r["fp"] for r in normal_sys) / max(1, sum(r["fp"] + r["tn"] for r in normal_sys)),
            "active_events_detected": sum(_flag(r["attack_event_detected"]) for r in attack_sys),
            "active_events": len(attack_sys)})
    for name, system in (("OR", "OR"), ("AND", "AND"), ("staged", "staged_suspect")):
        normal_sys = [r for r in normal if r["detector"] == system]
        attack_sys = [r for r in attack if r["detector"] == system]
        fpr = sum(r["fp"] for r in normal_sys) / max(1, sum(r["fp"] + r["tn"] for r in normal_sys))
        events = sum(_flag(r["attack_event_detected"]) for r in attack_sys)
        candidates.append({"candidate": name, "normal_fp": sum(r["fp"] for r in normal_sys),
            "normal_eligible": sum(r["fp"] + r["tn"] for r in normal_sys), "normal_fpr": fpr,
            "active_events_detected": events, "active_events": len(attack_sys),
            "mean_detection_delay_s_detected": _mean([float(r["detection_delay_s"]) for r in attack_sys
                                                        if r["detection_delay_s"] != ""]),
            "meets_5pct_target": fpr <= float(cfg["detector"]["normal_fpr_target"]),
            "selected": False})
    eligible = [r for r in candidates if r["meets_5pct_target"]]
    # Predeclared selection: among fusion candidates under the FPR ceiling,
    # maximize fast-suspect event detection, then minimize FPR, then delay.
    # Staged suspect is the unsuppressed M5 fast path; corroboration is reported
    # separately and never replaces/suppresses it.
    if eligible:
        winner = max(eligible, key=lambda r: (r["active_events_detected"],
                          -r["normal_fpr"],
                          -(r["mean_detection_delay_s_detected"] if r["mean_detection_delay_s_detected"] != "" else math.inf)))
        winner["selected"] = True
        selected = winner["candidate"]
    else:
        selected = "none_meets_target"
    # Staged candidate diagnostics remain separate from its fast-suspect score.
    corroborated = [r for r in attack if r["detector"] == "staged_corroborated"]
    staged_summary = {"suspect_normal_fpr": next((r["normal_fpr"] for r in candidates if r["candidate"] == "staged"), 0.0),
        "suspect_events_detected": next((r["active_events_detected"] for r in candidates if r["candidate"] == "staged"), 0),
        "corroborated_events_detected": sum(_flag(r["attack_event_detected"]) for r in corroborated),
        "corroborated_event_count": len(corroborated),
        "corroborated_mean_delay_s": _mean([float(r["detection_delay_s"]) for r in corroborated if r["detection_delay_s"] != ""])}
    _write_csv(out / "validation_candidate_summary.csv", candidates)
    _write_json(out / "validation_selection.json", {"target_normal_fpr": cfg["detector"]["normal_fpr_target"],
        "selection_rule": "among OR, AND and staged candidates with validation normal FPR <= 5%, maximize active alert-event detections, then minimize FPR, then mean delay; staged uses its unsuppressed fast-suspect state as its alert while reporting corroboration separately; never select by F1 alone",
        "selected_candidate": selected, "staged_diagnostics": staged_summary,
        "baseline_reference_metrics": baseline_summaries,
        "candidates": candidates, "final_test_opened": False})
    return {"calibration_trip_count": len(cal_seeds), "validation_trip_count": len(val_seeds),
            "validation_datasets": len(result_rows), "selected_candidate": selected,
            "candidates": candidates, "staged_diagnostics": staged_summary,
            "trip_manifest": manifest, "prediction_manifest": trip_summaries}


def _mean(values: list[float]) -> float | str:
    return sum(values) / len(values) if values else ""


def run_workflow(config_path: Path, run_id: str, *, smoke: bool = False) -> dict[str, Any]:
    if not run_id or not all(c.isalnum() or c in "-_" for c in run_id):
        raise ValueError("run_id may contain only letters, digits, hyphens and underscores")
    config_path = config_path.resolve()
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    root = config_path.parent.parent
    out_root = (config_path.parent / cfg["outputs"]["root"]).resolve()
    out = out_root / run_id
    if out.exists():
        raise FileExistsError(f"refusing to overwrite M9 run directory: {out}")
    all_splits = [set(map(int, cfg["splits"][name])) for name in ("calibration", "validation", "final_test")]
    if any(all_splits[i] & all_splits[j] for i in range(3) for j in range(i + 1, 3)):
        raise ValueError("M9 calibration, validation and final-test seeds must be disjoint")
    before_manifest_path = root / "reports/m9/m9_stage1_validation_01/protected_before.json"
    if not before_manifest_path.is_file():
        raise FileNotFoundError(f"protected-file baseline missing: {before_manifest_path}")
    before_manifest = json.loads(before_manifest_path.read_text(encoding="utf-8-sig"))
    out.mkdir(parents=True, exist_ok=False)
    shutil.copy2(config_path, out / "m9_analysis.yaml")
    history = _history_analysis(root, cfg, out)
    validation = _validation_workflow(root, cfg, out, smoke)
    after_manifest = _protected_manifest(root)
    changed = sorted(path for path, digest in before_manifest.items()
                     if after_manifest.get(path) != digest and path != "TASKS.md")
    allowed_tracker_change = "TASKS.md" in before_manifest and after_manifest.get("TASKS.md") != before_manifest["TASKS.md"]
    missing = sorted(path for path in before_manifest if path not in after_manifest)
    if changed or missing:
        raise RuntimeError(f"protected-file verification failed; changed={changed[:20]}, missing={missing[:20]}")
    result = {"stage": "M9 Stage 1 validation only", "final_test_opened": False,
              "historical_analysis": history, "validation": validation,
              "preservation": {"before_file_count": len(before_manifest),
                               "after_file_count": len(after_manifest),
                               "all_preexisting_project_hashes_unchanged_except_m9_tracker": True,
                               "expected_m9_tracker_edit": allowed_tracker_change,
                               "baseline_manifest": str(before_manifest_path.relative_to(root))}}
    _write_json(out / "summary.json", result)
    return {"run_dir": out, "summary": result}


def _protected_manifest(root: Path) -> dict[str, str]:
    import os
    result: dict[str, str] = {}
    for base, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in {".git", ".pytest_cache", "__pycache__"}
                   and not Path(base, d).relative_to(root).as_posix().startswith("reports/m9/")]
        for name in names:
            path = Path(base, name)
            rel = path.relative_to(root).as_posix()
            if rel.startswith("reports/m9/"):
                continue
            result[rel] = _sha(path)
    return result


def compare_runs(first: Path, second: Path) -> dict[str, Any]:
    """Compare deterministic CSV results while excluding path/hash manifests.

    Truth, GPS observations, attack CSV/label pairs, detector predictions,
    metrics and selection outputs are compared byte-for-byte. ``trip_manifest``
    is excluded because generated network/config provenance contains paths and
    converter serialization details unrelated to detector output reproducibility.
    """
    first, second = first.resolve(), second.resolve()
    if not first.is_dir() or not second.is_dir():
        raise FileNotFoundError("both M9 run directories must exist")
    ignored = {"trip_manifest.csv"}
    def files(directory: Path) -> dict[str, str]:
        return {p.relative_to(directory).as_posix(): _sha(p)
                for p in directory.rglob("*.csv") if p.name not in ignored}
    a, b = files(first), files(second)
    keys = a.keys() | b.keys()
    changed = sorted(k for k in keys if a.get(k) != b.get(k))
    return {"first_run": str(first), "second_run": str(second),
            "compared_csv_count": len(keys) - len(changed),
            "changed_or_missing": changed, "byte_identical": not changed}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/m9_analysis.yaml"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--smoke", action="store_true", help="use three calibration and three validation seeds")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    result = run_workflow(args.config, args.run_id, smoke=args.smoke)
    print(result["run_dir"])


if __name__ == "__main__":
    main()

