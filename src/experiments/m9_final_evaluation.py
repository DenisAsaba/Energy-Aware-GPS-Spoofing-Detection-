"""Frozen M9 Stage 2 final held-out evaluation.

All detector predictions are materialized from GPS-only inputs before attack
labels are read for scoring. Outputs are isolated under reports/m9/<run-id>/.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from src.attacks.gps_attacks import generate_attack
from src.detection.gps_only import apply_temporal_thresholds
from src.detection.m8_detector import apply_m8_thresholds, extract_m8_features
from src.detection.m9_hybrid import align_and_fuse
from src.experiments.m8_stage2a_scenarios import build_scenario_inputs, scenario_manifest
from src.experiments.m9_error_analysis import (
    _flag, _key, _read_csv, _read_labels, _sha, _stable_seed,
)
from src.sensors.gps_normal import generate_observations
from src.simulation.run_sumo import run as run_sumo

ATTACK_TYPES = ("offset", "jump", "drift")
DETECTOR_FIELDS = {
    "M5": "m5_prediction",
    "M8": "m8_prediction",
    "OR": "or_prediction",
    "AND": "and_prediction",
    "staged_fast_suspect": "m5_fast_suspect",
    "staged_corroborated": "corroborated_suspicion",
}
FROZEN_PATHS = (
    "config/m9_analysis.yaml", "config/m8_stage2b.yaml",
    "reports/m8/stage2b/m8_stage2b_final_02/m8_stage2b.yaml",
    "reports/m8/stage2b/m8_stage2b_final_02/metadata.json",
    "reports/m9/m9_stage1_validation_07/validation_selection.json",
    "src/detection/gps_only.py", "src/detection/m8_detector.py",
    "src/detection/m9_hybrid.py", "src/attacks/gps_attacks.py",
    "src/sensors/gps_normal.py", "src/simulation/run_sumo.py",
    "src/experiments/m8_stage2a_scenarios.py",
    "src/experiments/m9_error_analysis.py", "src/experiments/m9_final_evaluation.py",
)
METRIC_DEFINITIONS = {
    "eligible_observation": "Detector's eligible prediction joined to a label by (time_s, vehicle_id); fusion and staged states require joint eligibility.",
    "normal_fpr": "False-positive eligible observations divided by all eligible normal-label observations; pooled rates sum counts before division.",
    "event_detected": "At least one detector alert on an eligible observation with attack_active=1 for that case; each seed/case is one event.",
    "detection_delay_s": "First eligible active-label alert timestamp minus the first active-label timestamp; only detected events contribute to delay summaries.",
    "alarm_episode": "A rising edge in a detector alert stream over eligible observations, grouped per vehicle and dataset; clearing is the next eligible inactive observation.",
    "post_attack_alert": "Alert at an eligible observation at or after onset_s + duration_s, after the attack label is inactive.",
    "staged_outputs": "staged_fast_suspect is immediate M5 output; staged_corroborated is separately measured corroborated suspicion; no confirmed-spoofing interpretation.",
}


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        with path.open("x", encoding="utf-8", newline=""):
            pass
        return
    fields: list[str] = []
    for row in rows:
        for name in row:
            if name not in fields:
                fields.append(name)
    with path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8", newline="") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def _manifest(paths: list[Path], root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): _sha(p) for p in sorted(paths) if p.is_file()}


def _tree_manifest(directory: Path) -> dict[str, str]:
    if not directory.exists():
        return {}
    return {p.relative_to(directory).as_posix(): _sha(p) for p in sorted(directory.rglob("*")) if p.is_file()}


def _matrix(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    section = cfg["final_test"]
    onset = float(section["attack_onset_s"])
    matrix = section["matrix"]
    cases: list[dict[str, Any]] = []
    for kind in ATTACK_TYPES:
        settings = matrix[kind]
        if kind == "drift":
            intensities = [("rate_mps", float(x)) for x in settings["rates_mps"]]
        else:
            intensities = [("magnitude_m", float(x)) for x in settings["magnitudes_m"]]
        for intensity_key, intensity in intensities:
            for duration in settings["durations_s"]:
                d = float(duration)
                case: dict[str, Any] = {
                    "attack_type": kind, "onset_s": onset, "duration_s": d,
                    intensity_key: intensity, "direction_deg": float(settings["direction_deg"]),
                }
                if kind == "drift":
                    case["max_displacement_m"] = float(settings["max_displacement_m"])
                case["case_id"] = f"{kind}_{intensity_key}_{intensity:g}_duration_{d:g}s"
                cases.append(case)
    if len(cases) != 12 or len({c["case_id"] for c in cases}) != 12:
        raise ValueError("approved M9 final-test matrix must contain 12 unique cases")
    return cases


def _validate_preflight(cfg: dict[str, Any], root: Path) -> dict[str, Any]:
    ft = cfg["final_test"]
    seeds = [int(x) for x in ft["seeds"]]
    expected_seeds = [2501, 2502, 2503, 2504, 2505, 2506]
    expected_profiles = {
        "urban_turns_light": [2501, 2504],
        "urban_stop_restart": [2502, 2505],
        "urban_brake_accel": [2503, 2506],
    }
    if seeds != expected_seeds or ft["profile_assignment"] != expected_profiles:
        raise ValueError("final-test seed allocation differs from the approved six-seed assignment")
    splits = cfg["splits"]
    all_seed_sets = [set(map(int, splits[k])) for k in ("calibration", "validation", "final_test")]
    if any(all_seed_sets[i] & all_seed_sets[j] for i in range(3) for j in range(i + 1, 3)):
        raise ValueError("M9 calibration, validation, and final-test seeds collide")
    if set(seeds) != all_seed_sets[2]:
        raise ValueError("final_test seeds must match the reserved M9 split exactly")
    cases = _matrix(cfg)
    expected_ids = {
        "offset_magnitude_m_30_duration_10s", "offset_magnitude_m_30_duration_25s",
        "offset_magnitude_m_60_duration_10s", "offset_magnitude_m_60_duration_25s",
        "jump_magnitude_m_30_duration_1s", "jump_magnitude_m_30_duration_5s",
        "jump_magnitude_m_60_duration_1s", "jump_magnitude_m_60_duration_5s",
        "drift_rate_mps_0.5_duration_10s", "drift_rate_mps_0.5_duration_25s",
        "drift_rate_mps_1_duration_10s", "drift_rate_mps_1_duration_25s",
    }
    if {c["case_id"] for c in cases} != expected_ids:
        raise ValueError("case identifiers do not match approved M8 Stage 2B historical matrix")
    if not all({c["duration_s"] for c in cases if c["attack_type"] == "jump" and c["magnitude_m"] == mag} == {1.0, 5.0} for mag in (30.0, 60.0)):
        raise ValueError("jump attacks must include 1-second and 5-second durations at both magnitudes")
    if float(cfg["attacks"]["jump"]["duration_s"]) == 8.0:
        # Preserve this Stage 1 setting; ensure it is not silently in the final matrix.
        if any(c["attack_type"] == "jump" and c["duration_s"] == 8.0 for c in cases):
            raise ValueError("M9-only 60 m / 8-second Stage 1 jump must not replace historical cases")
    if len(expected_profiles) != 3 or any(len(v) != 2 for v in expected_profiles.values()):
        raise ValueError("each profile must retain exactly two approved seeds")
    existing_seed_dirs = []
    for p in (root / "reports").rglob("*"):
        if p.is_dir() and re.search(r"seed(?:2501|2502|2503|2504|2505|2506)(?:$|\D)", p.name):
            if not p.relative_to(root).as_posix().startswith("reports/m9/"):
                existing_seed_dirs.append(p.relative_to(root).as_posix())
    if existing_seed_dirs:
        raise ValueError(f"final seed collision with existing trip directories: {existing_seed_dirs[:20]}")
    counts = {
        "sumo_trips": len(seeds), "normal_control_datasets": len(seeds),
        "attack_case_count": len(cases), "attack_events": len(seeds) * len(cases),
        "attack_events_per_seed": len(cases),
        "attack_events_per_type_per_seed": {kind: sum(c["attack_type"] == kind for c in cases) for kind in ATTACK_TYPES},
        "attack_events_per_type_per_profile": {profile: {kind: len(seed_list) * sum(c["attack_type"] == kind for c in cases)
                                                        for kind in ATTACK_TYPES}
                                               for profile, seed_list in expected_profiles.items()},
        "instances_per_case_overall": len(seeds),
        "instances_per_case_per_profile": 2,
        "normal_plus_attack_prediction_datasets": len(seeds) * (1 + len(cases)),
    }
    if counts["sumo_trips"] != 6 or counts["normal_control_datasets"] != 6 or counts["attack_events"] != 72:
        raise ValueError(f"approved matrix allocation count mismatch: {counts}")
    return {"seeds": seeds, "profile_assignment": expected_profiles,
            "attack_onset_s": float(ft["attack_onset_s"]), "attack_matrix": cases,
            "counts": counts, "stage1_attack_settings_preserved": dict(cfg["attacks"]),
            "metrics": METRIC_DEFINITIONS}


def _trip(root: Path, cfg: dict[str, Any], out: Path, seed: int, profile: str) -> dict[str, Any]:
    trip_id = f"final_{profile}_seed{seed}"
    trip_dir = out / "trips" / trip_id
    trip_dir.mkdir(parents=True, exist_ok=False)
    input_files = build_scenario_inputs(trip_dir / "inputs", profile, seed)
    sim = {"seed": seed, "step_length_s": float(cfg["simulation"]["step_length_s"]),
           "begin_s": int(cfg["simulation"]["begin_s"]), "end_s": int(cfg["simulation"]["end_s"]),
           "vehicle_id": "ev_001", "network_file": str(input_files["network"]),
           "route_file": str(input_files["routes"]), "telemetry_output_dir": str(trip_dir), "depart_s": 0}
    sim_config = trip_dir / "simulation_config.yaml"
    sim_config.write_text(yaml.safe_dump({"simulation": sim}, sort_keys=True), encoding="utf-8")
    truth, gps = trip_dir / "truth.csv", trip_dir / "normal_gps.csv"
    run_sumo(sim_config, output_path=truth)
    gps_seed = _stable_seed(int(cfg["gps"]["seed_offset"]), seed, profile)
    generate_observations(truth, gps, noise_std_m=float(cfg["gps"]["noise_std_m_per_axis"]), seed=gps_seed)
    return {"trip_id": trip_id, "seed": seed, "profile": profile, "gps_seed": gps_seed,
            "truth_path": truth, "normal_gps_path": gps, "input_files": input_files,
            "input_hashes": {k: _sha(v) for k, v in input_files.items()},
            "truth_sha256": _sha(truth), "normal_gps_sha256": _sha(gps),
            "traffic_vehicles": scenario_manifest()[profile]["traffic"]}


def _predict(gps_path: Path, cfg: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    # The feature extractor receives a GPS-only CSV; no truth/labels are opened.
    features = extract_m8_features(gps_path, rolling_speed_window=int(cfg["detector"]["rolling_speed_window"]))
    m5 = apply_temporal_thresholds(features, cfg["detector"]["m5_thresholds"])
    m8 = apply_m8_thresholds(features, cfg["detector"]["m8_thresholds"], cfg["detector"]["m8_persistence"])
    hybrid = align_and_fuse(m5, m8,
        association_window=int(cfg["detector"]["staged_association_window_eligible_observations"]),
        clear_after_joint_clean=int(cfg["detector"]["staged_clear_after_joint_clean_observations"]))
    return m5, m8, hybrid


def _prediction_rows(m5: list[dict[str, Any]], m8: list[dict[str, Any]], hybrid: list[dict[str, Any]]) -> list[dict[str, Any]]:
    m5map, m8map, hmap = ({_key(r): r for r in rows} for rows in (m5, m8, hybrid))
    all_keys = sorted(m5map.keys() | m8map.keys() | hmap.keys())
    result = []
    for time_s, vehicle in all_keys:
        a, b, h = m5map.get((time_s, vehicle), {}), m8map.get((time_s, vehicle), {}), hmap.get((time_s, vehicle), {})
        result.append({"time_s": time_s, "vehicle_id": vehicle,
            "m5_eligible": a.get("eligible", 0), "m8_eligible": b.get("eligible", 0),
            "joint_eligible": h.get("joint_eligible", 0),
            "m5_prediction": a.get("predicted_attack", ""), "m8_prediction": b.get("predicted_attack", ""),
            "both_prediction": int(bool(_flag(h.get("m5_prediction")) and _flag(h.get("m8_prediction")))) if _flag(h.get("joint_eligible")) else "",
            "m5_only_prediction": int(bool(_flag(h.get("m5_prediction")) and not _flag(h.get("m8_prediction")))) if _flag(h.get("joint_eligible")) else "",
            "m8_only_prediction": int(bool(_flag(h.get("m8_prediction")) and not _flag(h.get("m5_prediction")))) if _flag(h.get("joint_eligible")) else "",
            "neither_prediction": int(not _flag(h.get("m5_prediction")) and not _flag(h.get("m8_prediction"))) if _flag(h.get("joint_eligible")) else "",
            "or_prediction": h.get("or_prediction", ""), "and_prediction": h.get("and_prediction", ""),
            "m5_fast_suspect": h.get("m5_fast_suspect", ""),
            "m8_corroboration_state": h.get("m8_corroboration", ""),
            "corroborated_suspicion": h.get("corroborated_suspicion", ""),
            "staged_event_id": h.get("staged_event_id", "")})
    return result


def _episode_rows(rows: list[dict[str, Any]], labels: dict[tuple[float, str], int],
                  trip: dict[str, Any], dataset: str, case: dict[str, Any] | None) -> list[dict[str, Any]]:
    output = []
    by_vehicle: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_vehicle[str(r["vehicle_id"])].append(r)
    for detector, field in DETECTOR_FIELDS.items():
        for vehicle, seq in by_vehicle.items():
            seq.sort(key=lambda r: float(r["time_s"]))
            active = False
            start: float | None = None
            start_attack = 0
            count = 0
            for r in seq:
                eligible = _flag(r.get("joint_eligible")) if detector.startswith("staged") or detector in ("OR", "AND") else _flag(r.get("m5_eligible" if detector == "M5" else "m8_eligible"))
                if not eligible:
                    continue
                value = _flag(r.get(field))
                t = float(r["time_s"])
                label = labels.get((t, vehicle), 0)
                if value and not active:
                    active, start, count, start_attack = True, t, 1, label
                elif value and active:
                    count += 1
                elif not value and active:
                    output.append({"trip_id": trip["trip_id"], "seed": trip["seed"], "profile": trip["profile"],
                        "dataset": dataset, "case_id": case["case_id"] if case else "normal", "detector": detector,
                        "vehicle_id": vehicle, "transition": "alarm_episode", "activation_time_s": start,
                        "clearing_time_s": t, "eligible_alert_observations": count,
                        "attack_active_at_activation": start_attack,
                        "active_attack_overlap": int(any(labels.get((float(x["time_s"]), vehicle), 0) for x in seq if start <= float(x["time_s"]) < t))})
                    active, start, count, start_attack = False, None, 0, 0
            if active:
                output.append({"trip_id": trip["trip_id"], "seed": trip["seed"], "profile": trip["profile"],
                    "dataset": dataset, "case_id": case["case_id"] if case else "normal", "detector": detector,
                    "vehicle_id": vehicle, "transition": "alarm_episode_open_at_end", "activation_time_s": start,
                    "clearing_time_s": "", "eligible_alert_observations": count,
                    "attack_active_at_activation": start_attack,
                    "active_attack_overlap": int(any(labels.get((float(x["time_s"]), vehicle), 0) for x in seq if start <= float(x["time_s"])))})
    return output


def _score(rows: list[dict[str, Any]], labels: dict[tuple[float, str], int], trip: dict[str, Any],
           dataset: str, case: dict[str, Any] | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    per_system = []
    overlap = []
    episodes = _episode_rows(rows, labels, trip, dataset, case)
    systems = {
        "M5": ("m5_prediction", "m5_eligible"), "M8": ("m8_prediction", "m8_eligible"),
        "OR": ("or_prediction", "joint_eligible"), "AND": ("and_prediction", "joint_eligible"),
        "staged_fast_suspect": ("m5_fast_suspect", "joint_eligible"),
        "staged_corroborated": ("corroborated_suspicion", "joint_eligible"),
    }
    matched_by_sys: dict[str, dict[tuple[float, str], int]] = {}
    for system, (pred_field, eligible_field) in systems.items():
        predictions = {(float(r["time_s"]), str(r["vehicle_id"])): _flag(r.get(pred_field))
                       for r in rows if _flag(r.get(eligible_field))}
        keys = predictions.keys() & labels.keys()
        tp = sum(predictions[k] == 1 and labels[k] == 1 for k in keys)
        fp = sum(predictions[k] == 1 and labels[k] == 0 for k in keys)
        tn = sum(predictions[k] == 0 and labels[k] == 0 for k in keys)
        fn = sum(predictions[k] == 0 and labels[k] == 1 for k in keys)
        active_times = sorted(k[0] for k in keys if labels[k] == 1)
        hit_times = sorted(k[0] for k in keys if labels[k] == 1 and predictions[k] == 1)
        delay = hit_times[0] - active_times[0] if active_times and hit_times else ""
        per_system.append({"trip_id": trip["trip_id"], "seed": trip["seed"], "profile": trip["profile"],
            "dataset": dataset, "case_id": case["case_id"] if case else "normal",
            "attack_type": case["attack_type"] if case else "none",
            "magnitude_or_rate": (case.get("magnitude_m", case.get("rate_mps", "")) if case else ""),
            "duration_s": case["duration_s"] if case else "", "detector": system,
            "tp": tp, "fp": fp, "tn": tn, "fn": fn, "eligible_observations": len(keys),
            "input_observations": len(rows), "label_observations": len(labels),
            "ineligible_or_missing_prediction_observations": max(0, len(rows) - len(predictions)),
            "inactive_observation_fpr": fp / (fp + tn) if fp + tn else "",
            "active_event": int(bool(active_times)) if active_times else "",
            "event_detected": int(bool(hit_times)) if active_times else "",
            "detection_delay_s": delay,
            "post_attack_alerts": sum(predictions[k] for k in keys if k[0] >= (case["onset_s"] + case["duration_s"]) and labels[k] == 0) if case else 0,
            "unmatched_predictions": len(predictions.keys() - labels.keys()),
            "unmatched_labels": len(labels.keys() - predictions.keys())})
        matched_by_sys[system] = predictions
    for r in rows:
        key = (float(r["time_s"]), str(r["vehicle_id"]))
        if not _flag(r.get("joint_eligible")) or key not in labels:
            continue
        m5, m8 = _flag(r.get("m5_prediction")), _flag(r.get("m8_prediction"))
        overlap.append({"trip_id": trip["trip_id"], "seed": trip["seed"], "profile": trip["profile"],
            "dataset": dataset, "case_id": case["case_id"] if case else "normal",
            "attack_type": case["attack_type"] if case else "none", "time_s": key[0], "vehicle_id": key[1],
            "attack_active": labels[key], "m5_alert": m5, "m8_alert": m8,
            "overlap_category": "both" if m5 and m8 else "m5_only" if m5 else "m8_only" if m8 else "neither",
            "or_alert": _flag(r.get("or_prediction")), "and_alert": _flag(r.get("and_prediction")),
            "staged_fast_suspect": _flag(r.get("m5_fast_suspect")),
            "staged_corroborated": _flag(r.get("corroborated_suspicion"))})
    return per_system, overlap, episodes


def _aggregate(rows: list[dict[str, Any]], group_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    buckets: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[tuple(row.get(field, "") for field in group_fields)].append(row)
    result = []
    for key, values in sorted(buckets.items(), key=lambda kv: tuple(str(v) for v in kv[0])):
        tp, fp, tn, fn = (sum(int(r[k]) for r in values) for k in ("tp", "fp", "tn", "fn"))
        event_rows = [r for r in values if r["active_event"] != ""]
        delays = [float(r["detection_delay_s"]) for r in event_rows if r["detection_delay_s"] != ""]
        result.append(dict(zip(group_fields, key)) | {
            "dataset_count": len(values), "eligible_observations": sum(int(r["eligible_observations"]) for r in values),
            "tp": tp, "fp": fp, "tn": tn, "fn": fn,
            "inactive_observation_fpr": fp / (fp + tn) if fp + tn else "",
            "active_events": len(event_rows), "events_detected": sum(int(r["event_detected"]) for r in event_rows),
            "event_recall": sum(int(r["event_detected"]) for r in event_rows) / len(event_rows) if event_rows else "",
            "mean_detection_delay_s": sum(delays) / len(delays) if delays else "",
            "detection_delay_min_s": min(delays) if delays else "",
            "detection_delay_max_s": max(delays) if delays else "",
            "detection_delay_median_s": sorted(delays)[len(delays) // 2] if delays else "",
            "detection_delay_p90_s": sorted(delays)[min(len(delays) - 1, math.ceil(0.9 * len(delays)) - 1)] if delays else "",
            "post_attack_alerts": sum(int(r["post_attack_alerts"]) for r in values),
        })
    return result


def _summary_counts(rows: list[dict[str, Any]], profile: str | None, detector: str) -> dict[str, Any]:
    selected = [r for r in rows if r["detector"] == detector and (profile is None or r["profile"] == profile)]
    normals = [r for r in selected if r["attack_type"] == "none"]
    attacks = [r for r in selected if r["attack_type"] != "none"]
    fp = sum(int(r["fp"]) for r in normals)
    n = sum(int(r["fp"]) + int(r["tn"]) for r in normals)
    return {"profile": profile or "pooled", "detector": detector,
        "normal_fp_observations": fp, "normal_eligible_observations": n,
        "normal_fpr": fp / n if n else "",
        "normal_alarm_episodes": sum(int(r.get("dataset_alarm_episodes", 0)) for r in normals),
        "attack_events": len(attacks), "attack_events_detected": sum(int(r["event_detected"]) for r in attacks),
        "attack_event_recall": sum(int(r["event_detected"]) for r in attacks) / len(attacks) if attacks else "",
        "mean_detection_delay_s": (sum(float(r["detection_delay_s"]) for r in attacks if r["detection_delay_s"] != "") /
                                   max(1, sum(r["detection_delay_s"] != "" for r in attacks))) if any(r["detection_delay_s"] != "" for r in attacks) else "",
        "post_attack_alert_observations": sum(int(r["post_attack_alerts"]) for r in attacks)}


def _run(root: Path, cfg: dict[str, Any], out: Path, preflight: dict[str, Any]) -> dict[str, Any]:
    detector_manifest = _manifest([root / p for p in FROZEN_PATHS], root)
    stage1_reports_before = _tree_manifest(root / "reports/m9")
    baseline_path = root / "reports/m9/m9_stage1_validation_01/protected_before.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8-sig"))
    baseline_manifest = {k: v for k, v in baseline.items() if k != "TASKS.md"}
    actual_baseline = {k: _sha(root / k) for k in baseline_manifest if (root / k).is_file()}
    changed_baseline = sorted(k for k, v in baseline_manifest.items() if actual_baseline.get(k) != v)
    missing_baseline = sorted(k for k in baseline_manifest if k not in actual_baseline)
    if changed_baseline or missing_baseline:
        raise RuntimeError(f"protected M0-M8 baseline mismatch before evaluation: changed={changed_baseline[:20]}, missing={missing_baseline[:20]}")
    freeze = {"milestone": "M9 Stage 2 final held-out evaluation", "run_id": out.name,
        "final_test_opened": False, "preflight": preflight,
        "configuration_sha256": _sha(root / "config/m9_analysis.yaml"),
        "frozen_code_and_input_hashes": detector_manifest,
        "m0_m8_protected_baseline_file_count": len(baseline),
        "m0_m8_protected_baseline_excluding_tracker_sha256": hashlib.sha256(json.dumps(baseline_manifest, sort_keys=True).encode()).hexdigest(),
        "m9_artifacts_before": stage1_reports_before,
        "thresholds": {k: cfg["detector"][k] for k in ("m5_thresholds", "m8_thresholds", "m8_persistence", "staged_association_window_eligible_observations", "staged_clear_after_joint_clean_observations")},
        "prediction_protocol": "For each normal/attack GPS file, all M5, M8, OR, AND and staged predictions are written before that file's labels are opened. Detector code receives GPS observations only.",
        "metric_definitions": METRIC_DEFINITIONS}
    out.mkdir(parents=True, exist_ok=False)
    _write_json(out / "preflight_freeze.json", freeze)
    (out / "m9_analysis.yaml").write_text((root / "config/m9_analysis.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    metric_rows: list[dict[str, Any]] = []
    overlap_rows: list[dict[str, Any]] = []
    episode_rows: list[dict[str, Any]] = []
    trip_manifest: list[dict[str, Any]] = []
    case_manifest: list[dict[str, Any]] = []
    cases = preflight["attack_matrix"]
    # Build all normal GPS and attack GPS/label pairs first; labels are retained unopened.
    trip_data: list[dict[str, Any]] = []
    for profile, profile_seeds in preflight["profile_assignment"].items():
        for seed in profile_seeds:
            trip = _trip(root, cfg, out, int(seed), profile)
            trip_manifest.append({k: v for k, v in trip.items() if k not in ("truth_path", "normal_gps_path", "input_files")})
            datasets: list[dict[str, Any]] = [{"dataset": "normal", "gps": trip["normal_gps_path"], "labels": None, "case": None}]
            for case in cases:
                case_copy = dict(case)
                kind = case_copy.pop("attack_type")
                case_id = case_copy.pop("case_id")
                gps_path = out / "attacks" / trip["trip_id"] / f"{case_id}.csv"
                gps_path.parent.mkdir(parents=True, exist_ok=True)
                settings = dict(case_copy)
                settings["attack_id"] = f"{trip['trip_id']}_{case_id}"
                _, label_path = generate_attack(trip["truth_path"], gps_path, attack_type=kind,
                    settings=settings, noise_std_m=float(cfg["gps"]["noise_std_m_per_axis"]), seed=int(trip["gps_seed"]))
                datasets.append({"dataset": case_id, "gps": gps_path, "labels": label_path,
                    "case": {**case, "attack_type": kind, "case_id": case_id}})
                case_manifest.append({"trip_id": trip["trip_id"], "seed": seed, "profile": profile,
                    "case_id": case_id, "attack_type": kind, "magnitude_m": case.get("magnitude_m", ""),
                    "rate_mps": case.get("rate_mps", ""), "duration_s": case["duration_s"],
                    "onset_s": case["onset_s"], "gps_sha256": _sha(gps_path), "labels_sha256": _sha(label_path)})
            trip_data.append({"trip": trip, "datasets": datasets})
    # Generate and persist predictions for every dataset before reading any labels.
    for item in trip_data:
        trip = item["trip"]
        for dataset in item["datasets"]:
            m5, m8, hybrid = _predict(dataset["gps"], cfg)
            rows = _prediction_rows(m5, m8, hybrid)
            path = out / "predictions" / trip["trip_id"] / f"{dataset['dataset']}.csv"
            path.parent.mkdir(parents=True, exist_ok=True)
            _write_csv(path, rows)
            dataset["prediction_rows"] = rows
            dataset["prediction_sha256"] = _sha(path)
    # Labels are opened only after all prediction CSVs exist for the complete matrix.
    for item in trip_data:
        trip = item["trip"]
        for dataset in item["datasets"]:
            rows = dataset["prediction_rows"]
            if dataset["labels"] is None:
                labels = {(float(r["time_s"]), str(r["vehicle_id"])): 0 for r in rows}
            else:
                labels = _read_labels(dataset["labels"])
            scored, overlap, episodes = _score(rows, labels, trip, dataset["dataset"], dataset["case"])
            metric_rows.extend(scored); overlap_rows.extend(overlap); episode_rows.extend(episodes)
    # Episode counts are attached to each dataset/system for compact FPR summaries.
    episode_counts: dict[tuple[str, str, str], int] = defaultdict(int)
    for ep in episode_rows:
        if ep["transition"].startswith("alarm_episode"):
            episode_counts[(ep["trip_id"], ep["dataset"], ep["detector"])] += 1
    for row in metric_rows:
        row["dataset_alarm_episodes"] = episode_counts[(row["trip_id"], row["dataset"], row["detector"])]
    _write_csv(out / "trip_metrics.csv", metric_rows)
    _write_csv(out / "prediction_coverage.csv", [{k: r[k] for k in (
        "trip_id", "seed", "profile", "dataset", "case_id", "detector", "input_observations",
        "label_observations", "eligible_observations", "ineligible_or_missing_prediction_observations",
        "unmatched_predictions", "unmatched_labels")} for r in metric_rows])
    _write_csv(out / "joint_prediction_overlap.csv", overlap_rows)
    _write_csv(out / "alarm_episodes.csv", episode_rows)
    _write_csv(out / "trip_manifest.csv", trip_manifest)
    _write_csv(out / "attack_case_manifest.csv", case_manifest)
    pooled = [_summary_counts(metric_rows, None, name) for name in DETECTOR_FIELDS]
    per_profile = [_summary_counts(metric_rows, profile, name) for profile in preflight["profile_assignment"] for name in DETECTOR_FIELDS]
    _write_csv(out / "normal_fpr_summary.csv", pooled + per_profile)
    attack_groups = _aggregate([r for r in metric_rows if r["attack_type"] != "none"],
        ("profile", "attack_type", "magnitude_or_rate", "duration_s", "detector"))
    pooled_attack_groups = _aggregate([r for r in metric_rows if r["attack_type"] != "none"],
        ("attack_type", "magnitude_or_rate", "duration_s", "detector"))
    for group in pooled_attack_groups:
        group["profile"] = "pooled"
    # Join episode counts to the exact attack case, rather than all cases in a profile.
    for group in pooled_attack_groups + attack_groups:
        case = next(c for c in cases if c["attack_type"] == group["attack_type"]
            and c.get("magnitude_m", c.get("rate_mps")) == float(group["magnitude_or_rate"])
            and c["duration_s"] == float(group["duration_s"]))
        group["case_id"] = case["case_id"]
        group["alarm_episodes"] = sum(1 for e in episode_rows
            if (group["profile"] == "pooled" or e["profile"] == group["profile"])
            and e["case_id"] == case["case_id"] and e["detector"] == group["detector"]
            and e["transition"].startswith("alarm_episode"))
    _write_csv(out / "attack_event_summary.csv", pooled_attack_groups + attack_groups)
    overlap_summary: dict[tuple[str, str], int] = defaultdict(int)
    for r in overlap_rows:
        cls = "attack_active" if int(r["attack_active"]) else "normal_or_inactive"
        overlap_summary[(cls, str(r["overlap_category"]))] += 1
    _write_csv(out / "overlap_summary.csv", [{"label_state": state, "overlap_category": category, "observations": n}
        for (state, category), n in sorted(overlap_summary.items())])
    counts = preflight["counts"]
    if len(trip_manifest) != counts["sumo_trips"] or len(case_manifest) != counts["attack_events"]:
        raise RuntimeError("generated trip/event counts differ from frozen preflight allocation")
    # Recheck protected files and previous M9 reports after evaluation.
    after_baseline = {k: _sha(root / k) for k in baseline_manifest if (root / k).is_file()}
    changed_baseline_after = sorted(k for k, v in baseline_manifest.items() if after_baseline.get(k) != v)
    missing_baseline_after = sorted(k for k in baseline_manifest if k not in after_baseline)
    m9_after = _tree_manifest(root / "reports/m9")
    prior_m9 = {k: v for k, v in stage1_reports_before.items()}
    changed_m9 = sorted(k for k, v in prior_m9.items() if m9_after.get(k) != v)
    if changed_baseline_after or missing_baseline_after or changed_m9:
        raise RuntimeError(f"preservation failure baseline={changed_baseline_after[:20]}/{missing_baseline_after[:20]}, M9 prior={changed_m9[:20]}")
    result = {"milestone": "M9 Stage 2 final held-out evaluation", "run_id": out.name,
        "final_test_completed": True, "final_test_opened_after_freeze": True,
        "allocation": counts, "seed_profile_assignment": preflight["profile_assignment"],
        "systems": list(DETECTOR_FIELDS), "normal_fpr": pooled + per_profile,
        "attack_event_summary": attack_groups,
        "short_jump_summary": [r for r in attack_groups if r["attack_type"] == "jump"],
        "m5_m8_overlap_summary": [{"label_state": s, "overlap_category": c, "observations": n} for (s, c), n in sorted(overlap_summary.items())],
        "alarm_episode_count": len(episode_rows),
        "limits": ["Six SUMO trips provide two trips per profile; results are descriptive and do not establish broad generalization.",
            "A GPS motion anomaly is not proof of spoofing; smooth constant translation and plausible slow drift may be unobservable from GPS motion alone.",
            "Corroboration is a detector state, not confirmed spoofing; this simulation evaluation does not establish production readiness."],
        "preservation": {"protected_baseline_file_count": len(baseline_manifest), "protected_baseline_changed": [],
            "prior_m9_files_unchanged": True, "prior_m9_file_count": len(stage1_reports_before)},
        "reproduction": [
            f"python -m src.experiments.m9_final_evaluation --config config/m9_analysis.yaml --run-id {out.name}",
            "python -m unittest discover -s tests -v",
        ]}
    _write_json(out / "summary.json", result)
    return result


def run_workflow(config_path: Path, run_id: str) -> dict[str, Any]:
    if not run_id or not all(c.isalnum() or c in "-_" for c in run_id):
        raise ValueError("run_id may contain only letters, digits, hyphens, and underscores")
    config_path = config_path.resolve()
    root = config_path.parent.parent.resolve()
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    out_root = (config_path.parent / cfg["outputs"]["root"]).resolve()
    out = out_root / run_id
    if out.exists():
        raise FileExistsError(f"refusing to overwrite M9 final-test run: {out}")
    preflight = _validate_preflight(cfg, root)
    return _run(root, cfg, out, preflight)


def compare_runs(first: Path, second: Path) -> dict[str, Any]:
    """Compare deterministic CSV outputs byte-for-byte, excluding path manifests."""
    first, second = first.resolve(), second.resolve()
    if not first.is_dir() or not second.is_dir():
        raise FileNotFoundError("both M9 Stage 2 run directories must exist")
    ignored = {"trip_manifest.csv"}
    def hashes(directory: Path) -> dict[str, str]:
        return {p.relative_to(directory).as_posix(): _sha(p) for p in directory.rglob("*.csv") if p.name not in ignored}
    a, b = hashes(first), hashes(second)
    changed = sorted(k for k in a.keys() | b.keys() if a.get(k) != b.get(k))
    return {"first_run": str(first), "second_run": str(second),
        "compared_csv_count": len(a.keys() | b.keys()) - len(changed),
        "changed_or_missing": changed, "byte_identical": not changed}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/m9_analysis.yaml"))
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    result = run_workflow(args.config, args.run_id)
    print(json.dumps({"run_id": result["run_id"], "trip_count": result["allocation"]["sumo_trips"],
        "attack_events": result["allocation"]["attack_events"], "completed": result["final_test_completed"]}, indent=2))


if __name__ == "__main__":
    main()
