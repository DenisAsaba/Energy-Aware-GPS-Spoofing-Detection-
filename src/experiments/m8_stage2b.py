"""Frozen M8 Stage 2B held-out paired evaluation; no calibration or tuning."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import shutil
import statistics
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import yaml

from src.attacks.gps_attacks import generate_attack
from src.detection.gps_only import apply_temporal_thresholds
from src.detection.m8_detector import apply_m8_thresholds, extract_m8_features
from src.experiments.m8_evaluation import (
    ATTACK_TYPES, METRIC_FIELDS, _metrics, _read_labels, _stable_seed,
    _write_csv, _write_json, compare_runs, protected_manifest,
)
from src.experiments.m8_stage2a_scenarios import build_scenario_inputs, scenario_manifest
from src.sensors.gps_normal import generate_observations
from src.simulation.run_sumo import run as run_sumo

PAIR_METRICS = (
    "precision", "recall", "f1", "false_positive_rate", "true_negative_rate",
    "active_attack_detection_rate", "missed_attack_rate", "detection_delay_s",
    "post_attack_alert_rate", "alerts_per_trip",
)
METRIC_EXTRA = ("scenario_type", "attack_intensity_value", "attack_duration_s",
                "attack_event_detected", "post_attack_eligible_observations")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _frozen_manifest(root: Path) -> dict[str, str]:
    names = (
        "config/m8_detector.yaml", "config/m8_stage2a.yaml", "config/m8_stage2b.yaml",
        "src/detection/m8_detector.py", "src/detection/gps_only.py",
        "src/experiments/m8_evaluation.py", "src/experiments/m8_stage2a.py",
        "src/experiments/m8_stage2a_scenarios.py", "src/experiments/m8_stage2b.py",
        "tests/test_m8_detector.py", "tests/test_m8_evaluation.py", "tests/test_m8_stage2a.py",
    )
    return {name: _sha(root / name) for name in names if (root / name).is_file()}


def _prior_m8_manifest(root: Path, current_run_id: str) -> dict[str, str]:
    directory = root / "reports/m8"
    if not directory.exists():
        return {}
    excluded = Path("stage2b") / current_run_id
    return {str(path.relative_to(root)): _sha(path) for path in sorted(directory.rglob("*"))
            if path.is_file() and not path.relative_to(directory).is_relative_to(excluded)}


def _matrix(config: dict[str, Any]) -> list[dict[str, Any]]:
    onset = float(config["final_test"]["attack_onset_s"])
    cases = []
    for kind in ATTACK_TYPES:
        settings = config["final_test"]["matrix"][kind]
        if kind == "drift":
            intensities = [("rate_mps", float(v)) for v in settings["rates_mps"]]
        else:
            intensities = [("magnitude_m", float(v)) for v in settings["magnitudes_m"]]
        for intensity_key, intensity in intensities:
            for duration in settings["durations_s"]:
                case = {"attack_type": kind, "onset_s": onset, "duration_s": float(duration),
                        intensity_key: intensity, "direction_deg": float(settings["direction_deg"])}
                if kind == "drift":
                    case["max_displacement_m"] = float(settings["max_displacement_m"])
                case["case_id"] = f"{kind}_{intensity_key}_{intensity:g}_duration_{duration:g}s"
                cases.append(case)
    if len({case["case_id"] for case in cases}) != len(cases):
        raise ValueError("attack matrix case IDs must be unique")
    return cases


def _verify_frozen(root: Path, config: dict[str, Any]) -> dict[str, Any]:
    stage1 = yaml.safe_load((root / "config/m8_detector.yaml").read_text(encoding="utf-8"))
    reserved = [int(row["seed"]) for row in stage1["splits"]["final_test"]["trips"]]
    configured = [int(seed) for seed in config["final_test"]["seeds"]]
    if configured != reserved or reserved != [1301, 1302]:
        raise ValueError("Stage 2B must use the unchanged reserved final seeds 1301 and 1302")
    calibration = [int(seed) for seed in config["detector"]["calibration_trip_seeds"]]
    if set(calibration) & set(configured) or set(configured) & {803, 804}:
        raise ValueError("final seeds overlap calibration or M7 held-out seeds")
    policy = config["detector"]["m8_persistence"]
    if policy != {"trigger_count": 2, "trigger_window": 5, "clear_after_clean_fixes": 3}:
        raise ValueError("Stage 2B persistence must remain frozen at 2-of-5, clear after 3")
    source = root / "reports/m8/stage2a" / config["detector"]["frozen_source_run"] / "calibration.json"
    if not source.is_file():
        raise FileNotFoundError(f"frozen Stage 2A calibration report missing: {source}")
    approved = json.loads(source.read_text(encoding="utf-8"))["thresholds"]
    if config["detector"]["m8_thresholds"] != approved:
        raise ValueError("Stage 2B M8 thresholds differ from frozen Stage 2A calibration values")
    m5 = {k: approved[k] for k in ("max_speed_mps", "max_speed_change_mps", "max_heading_change_deg")}
    if config["detector"]["m5_thresholds"] != m5:
        raise ValueError("Stage 2B M5 thresholds must be the frozen M5 subset from approved calibration")
    stage2a = yaml.safe_load((root / "config/m8_stage2a.yaml").read_text(encoding="utf-8"))
    if calibration != [int(seed) for seed in stage2a["splits"]["calibration"]]:
        raise ValueError("Stage 2B must use the already approved Stage 2A calibration trips")
    cal_val = set(stage2a["splits"]["calibration"]) | set(stage2a["splits"]["validation"])
    if set(configured) & cal_val:
        raise ValueError("final-test observations/seeds overlap Stage 2A calibration or validation")
    return {"reserved_final_seeds": reserved, "calibration_trip_seeds": calibration,
            "calibration_validation_overlap": False, "m7_final_seed_reuse": False,
            "frozen_source_run": config["detector"]["frozen_source_run"],
            "m8_thresholds": dict(config["detector"]["m8_thresholds"]),
            "m5_thresholds": dict(config["detector"]["m5_thresholds"]),
            "m8_persistence": dict(policy), "stage1_final_seed_config_sha256": _sha(root / "config/m8_detector.yaml")}


def _simulate_trip(root: Path, config: dict[str, Any], run_dir: Path, seed: int, scenario: str) -> dict[str, Any]:
    trip_id = f"final_{scenario}_seed{seed}"
    trip_dir = run_dir / "trips" / trip_id
    trip_dir.mkdir(parents=True, exist_ok=False)
    inputs = build_scenario_inputs(trip_dir / "inputs", scenario, seed)
    sim = {"seed": seed, "step_length_s": float(config["simulation"]["step_length_s"]),
           "begin_s": int(config["simulation"]["begin_s"]), "end_s": int(config["simulation"]["end_s"]),
           "vehicle_id": "ev_001", "network_file": str(inputs["network"]),
           "route_file": str(inputs["routes"]), "telemetry_output_dir": str(trip_dir), "depart_s": 0}
    sim_config = trip_dir / "simulation_config.yaml"
    sim_config.write_text(yaml.safe_dump({"simulation": sim}, sort_keys=True), encoding="utf-8")
    truth = trip_dir / "truth.csv"
    run_sumo(sim_config, output_path=truth)
    gps = trip_dir / "normal_gps.csv"
    gps_seed = _stable_seed(int(config["gps"]["seed_offset"]), seed, scenario)
    generate_observations(truth, gps, noise_std_m=float(config["gps"]["noise_std_m_per_axis"]), seed=gps_seed)
    return {"trip_id": trip_id, "seed": seed, "scenario_type": scenario, "route_group": scenario,
            "truth": truth, "gps": gps, "gps_seed": gps_seed,
            "traffic_vehicles": scenario_manifest()[scenario]["traffic"],
            "input_hashes": {key: _sha(path) for key, path in inputs.items()},
            "truth_sha256": _sha(truth), "normal_gps_sha256": _sha(gps)}


def _score(predictions: list[dict[str, Any]], labels: dict[tuple[float, str], dict[str, Any]], *,
           trip: dict[str, Any], scenario: str, settings: dict[str, Any] | None,
           detector: str, end_time_s: float) -> dict[str, Any]:
    row = _metrics(predictions, labels, split="final_test", trip=trip,
                   scenario=scenario, detector=detector, settings=settings)
    eligible_after_end = sum(bool(p.get("eligible")) and float(p["time_s"]) >= end_time_s
                             for p in predictions if p.get("time_s") not in (None, ""))
    post_alert_rate = (float(row["post_attack_alerts"]) / eligible_after_end
                       if settings is not None and eligible_after_end else (0.0 if settings is not None else ""))
    row.update({"scenario_type": trip["scenario_type"],
                "attack_intensity_value": (settings.get("magnitude_m", settings.get("rate_mps", "")) if settings else ""),
                "attack_duration_s": (settings.get("duration_s", "") if settings else ""),
                "attack_event_detected": int(bool(row["active_attack_detected"])) if settings else "",
                "post_attack_eligible_observations": eligible_after_end if settings else "",
                "post_attack_alert_rate": post_alert_rate})
    return row


def _condition_summaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = ("scenario_type", "attack_type", "attack_magnitude", "attack_duration_s", "detector")
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(tuple(row.get(k, "") for k in keys), []).append(row)
    output = []
    for group_key, values in sorted(groups.items(), key=lambda item: tuple(str(v) for v in item[0])):
        tp, fp, tn, fn = (sum(int(r[k]) for r in values) for k in ("tp", "fp", "tn", "fn"))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        fpr = fp / (fp + tn) if fp + tn else 0.0
        tnr = tn / (tn + fp) if tn + fp else 0.0
        events = [r for r in values if r["attack_event_detected"] != ""]
        delays = [float(r["detection_delay_s"]) for r in events if r["detection_delay_s"] not in ("", None)]
        post_n = sum(int(r["post_attack_eligible_observations"] or 0) for r in events)
        post_alerts = sum(int(r["post_attack_alerts"] or 0) for r in events)
        output.append(dict(zip(keys, group_key)) | {
            "trip_count": len(values), "observation_count": tp + fp + tn + fn,
            "tp": tp, "fp": fp, "tn": tn, "fn": fn, "precision": precision,
            "recall": recall, "f1": f1, "false_positive_rate": fpr,
            "true_negative_rate": tnr,
            "attack_event_count": len(events),
            "active_event_detection_rate": (sum(int(r["attack_event_detected"]) for r in events) / len(events) if events else ""),
            "missed_attack_rate": (1.0 - sum(int(r["attack_event_detected"]) for r in events) / len(events) if events else ""),
            "mean_detection_delay_s": float(np.mean(delays)) if delays else "",
            "post_attack_alerts": post_alerts,
            "post_attack_alert_rate": post_alerts / post_n if post_n else (0.0 if events else ""),
            "mean_alerts_per_trip": float(np.mean([float(r["alerts_per_trip"]) for r in values])),
        })
    return output


def _paired_comparisons(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = ("scenario_type", "attack_type", "attack_magnitude", "attack_duration_s")
    groups: dict[tuple[Any, ...], dict[str, dict[str, dict[str, Any]]]] = {}
    for row in rows:
        key = tuple(row.get(k, "") for k in keys)
        groups.setdefault(key, {}).setdefault(str(row["trip_id"]), {})[str(row["detector"])] = row
    out = []
    for group_key, trip_rows in sorted(groups.items(), key=lambda item: tuple(str(v) for v in item[0])):
        paired = [(pair["M5"], pair["M8"]) for pair in trip_rows.values() if {"M5", "M8"} <= set(pair)]
        for metric in PAIR_METRICS:
            diffs = []
            vals5, vals8 = [], []
            for left, right in paired:
                a, b = left.get(metric), right.get(metric)
                if a in (None, "") or b in (None, ""):
                    continue
                a, b = float(a), float(b)
                if not math.isfinite(a) or not math.isfinite(b):
                    continue
                vals5.append(a); vals8.append(b); diffs.append(b - a)
            out.append(dict(zip(keys, group_key)) | {
                "metric": metric, "n_paired_trips": len(diffs),
                "n_distinct_seeds": len({int(trip_rows[t]["M5"]["sumo_seed"]) for t in trip_rows if "M5" in trip_rows[t]}),
                "m5_mean": float(np.mean(vals5)) if vals5 else "",
                "m5_sample_sd": statistics.stdev(vals5) if len(vals5) > 1 else "",
                "m8_mean": float(np.mean(vals8)) if vals8 else "",
                "m8_sample_sd": statistics.stdev(vals8) if len(vals8) > 1 else "",
                "paired_difference_m8_minus_m5_mean": float(np.mean(diffs)) if diffs else "",
                "paired_difference_sample_sd": statistics.stdev(diffs) if len(diffs) > 1 else "",
                "ci95_low": "", "ci95_high": "",
            })
    return out


def _plots(out: Path, summaries: list[dict[str, Any]]) -> None:
    normal = [r for r in summaries if r["attack_type"] == "none"]
    scenarios = sorted({r["scenario_type"] for r in normal})
    fig, ax = plt.subplots(figsize=(9, 5))
    for detector in ("M5", "M8"):
        subset = [next((r for r in normal if r["scenario_type"] == scenario and r["detector"] == detector), None) for scenario in scenarios]
        ax.plot(scenarios, [float(r["false_positive_rate"]) * 100 if r else 0 for r in subset], marker="o", label=detector)
    ax.axhline(5, color="tab:red", linestyle="--", label="5% target")
    ax.set(ylabel="Normal false-positive rate (%)", xlabel="Normal-driving scenario")
    ax.grid(alpha=.25); ax.legend(); fig.tight_layout(); fig.savefig(out / "normal_fpr_by_scenario.png", dpi=140); plt.close(fig)
    attack = [r for r in summaries if r["attack_type"] in ATTACK_TYPES]
    types = list(ATTACK_TYPES)
    fig, ax = plt.subplots(figsize=(8, 5)); width=.36; x=np.arange(len(types))
    for idx, detector in enumerate(("M5", "M8")):
        rates=[]
        for kind in types:
            subset=[r for r in attack if r["attack_type"]==kind and r["detector"]==detector]
            events=sum(int(r["attack_event_count"]) for r in subset)
            detected=sum(float(r["active_event_detection_rate"])*int(r["attack_event_count"]) for r in subset)
            rates.append(detected/events if events else 0)
        ax.bar(x+(idx-.5)*width,rates,width,label=detector)
    ax.set(xticks=x,xticklabels=types,ylabel="Active-attack event detection rate",ylim=(0,1.05)); ax.grid(axis="y",alpha=.25); ax.legend(); fig.tight_layout(); fig.savefig(out/"attack_detection_by_type.png",dpi=140); plt.close(fig)


def run_workflow(config_path: Path, run_id: str) -> dict[str, Any]:
    if not run_id or not all(c.isalnum() or c in "-_" for c in run_id):
        raise ValueError("run_id may contain only letters, numbers, hyphens, and underscores")
    config_path = config_path.resolve(); config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    root = config_path.parent.parent.resolve()
    out_root = (config_path.parent / config["outputs"]["root"]).resolve(); out = out_root / run_id
    if out.exists():
        raise FileExistsError(f"refusing to overwrite Stage 2B run: {out}")
    frozen = _verify_frozen(root, config); cases = _matrix(config)
    before_m07 = protected_manifest(root); before_old_m8 = _prior_m8_manifest(root, run_id); before_frozen = _frozen_manifest(root)
    out.mkdir(parents=True, exist_ok=False); shutil.copy2(config_path, out / "m8_stage2b.yaml")
    (out / "metadata.json").write_text(json.dumps({"milestone":"M8 Stage 2B", "run_id":run_id,
        "final_test_executed":True,"frozen":frozen,"attack_matrix":cases,"scenario_definitions":scenario_manifest(),
        "input_config_sha256":_sha(config_path),"protected_m0_m7_before_sha256":hashlib.sha256(json.dumps(before_m07,sort_keys=True).encode()).hexdigest(),
        "protected_m0_m7_before_count":len(before_m07),"prior_m8_manifest_sha256":hashlib.sha256(json.dumps(before_old_m8,sort_keys=True).encode()).hexdigest(),
        "prior_m8_file_count":len(before_old_m8),"frozen_code_config_manifest_before":before_frozen},indent=2,sort_keys=True)+"\n",encoding="utf-8")

    metric_rows = []; trip_manifest = []
    m8_thresholds = config["detector"]["m8_thresholds"]
    m5_thresholds = config["detector"]["m5_thresholds"]
    persistence = config["detector"]["m8_persistence"]
    window = int(config["detector"]["rolling_speed_window"])
    for seed in config["final_test"]["seeds"]:
        for scenario in config["final_test"]["scenarios"]:
            trip = _simulate_trip(root, config, out, int(seed), scenario)
            trip_manifest.append({k:v for k,v in trip.items() if k not in ("truth","gps")})
            datasets = [("none", trip["gps"], None, None)]
            label_paths = {}
            for case in cases:
                settings = dict(case); kind = settings.pop("attack_type"); case_id = settings.pop("case_id")
                gps_path = out / "attacks" / trip["trip_id"] / f"{case_id}.csv"
                gps_path.parent.mkdir(parents=True, exist_ok=True)
                settings["attack_id"] = f"{trip['trip_id']}_{case_id}"
                _, labels_path = generate_attack(trip["truth"], gps_path, attack_type=kind,
                    settings=settings, noise_std_m=float(config["gps"]["noise_std_m_per_axis"]), seed=trip["gps_seed"])
                datasets.append((case_id, gps_path, kind, settings)); label_paths[case_id] = labels_path
            for dataset_id, gps_path, kind, settings in datasets:
                features = extract_m8_features(gps_path, rolling_speed_window=window)
                # Generate both detector streams before opening attack labels.
                m5 = apply_temporal_thresholds(features, m5_thresholds)
                m8 = apply_m8_thresholds(features, m8_thresholds, persistence)
                m5_by_key = {(float(r["time_s"]),str(r["vehicle_id"])):r for r in m5 if r.get("time_s") not in (None,"")}
                prediction_rows=[]
                for row in m8:
                    prior=m5_by_key.get((float(row["time_s"]),str(row["vehicle_id"])),{})
                    prediction_rows.append({**row,"m5_predicted_attack":prior.get("predicted_attack","")})
                pred_path=out/"predictions"/trip["trip_id"]/f"{dataset_id}.csv"
                _write_csv(pred_path,list(prediction_rows[0].keys()),prediction_rows)
                if settings is None:
                    labels={(float(r["time_s"]),str(r["vehicle_id"])):{"attack_active":0} for r in features if r.get("time_s") not in (None,"")}
                    scenario="normal"
                    end_time=float(features[-1]["time_s"]) if features else 0.0
                else:
                    labels=_read_labels(label_paths[dataset_id]); scenario=str(kind)
                    end_time=float(settings["onset_s"])+float(settings["duration_s"])
                trip_fields={"trip_id":trip["trip_id"],"seed":int(seed),"route_group":trip["scenario_type"]}
                # Keep scenario IDs independently available for the requested breakdown.
                for detector, predictions in (("M5",m5),("M8",m8)):
                    item=_score(predictions,labels,trip=trip_fields | {"scenario_type":scenario},
                                scenario=scenario,settings=settings,detector=detector,end_time_s=end_time)
                    item["scenario_type"]=trip["scenario_type"]
                    metric_rows.append(item)

    metric_fields=list(METRIC_FIELDS)+[x for x in METRIC_EXTRA if x not in METRIC_FIELDS]+["post_attack_alert_rate"]
    _write_csv(out/"trip_metrics.csv",metric_fields,metric_rows)
    summaries=_condition_summaries(metric_rows)
    summary_fields=list(summaries[0].keys()) if summaries else []
    _write_csv(out/"condition_summary.csv",summary_fields,summaries)
    observation_fields=("scenario_type","attack_type","attack_magnitude","attack_duration_s","detector",
        "trip_count","observation_count","tp","fp","tn","fn","precision","recall","f1",
        "false_positive_rate","true_negative_rate","mean_alerts_per_trip")
    event_fields=("scenario_type","attack_type","attack_magnitude","attack_duration_s","detector",
        "attack_event_count","active_event_detection_rate","missed_attack_rate","mean_detection_delay_s",
        "post_attack_alerts","post_attack_alert_rate")
    _write_csv(out/"observation_summary.csv",observation_fields,[{k:r.get(k,"") for k in observation_fields} for r in summaries])
    _write_csv(out/"event_summary.csv",event_fields,[{k:r.get(k,"") for k in event_fields} for r in summaries])
    paired=_paired_comparisons(metric_rows)
    _write_csv(out/"paired_trip_comparisons.csv",list(paired[0].keys()) if paired else [],paired)
    _plots(out,summaries)
    after_m07=protected_manifest(root); after_old_m8=_prior_m8_manifest(root, run_id); after_frozen=_frozen_manifest(root)
    changed_m07=sorted(path for path in set(before_m07)|set(after_m07) if before_m07.get(path)!=after_m07.get(path))
    changed_old_m8=sorted(path for path in set(before_old_m8)|set(after_old_m8) if before_old_m8.get(path)!=after_old_m8.get(path))
    changed_frozen=sorted(path for path in set(before_frozen)|set(after_frozen) if before_frozen.get(path)!=after_frozen.get(path))
    if changed_m07 or changed_old_m8 or changed_frozen:
        raise RuntimeError(f"preservation failure M0-M7={changed_m07}, previous M8={changed_old_m8}, frozen={changed_frozen}")
    meta=json.loads((out/"metadata.json").read_text(encoding="utf-8"))
    meta.update({"trip_manifest":trip_manifest,"protected_m0_m7_after_sha256":hashlib.sha256(json.dumps(after_m07,sort_keys=True).encode()).hexdigest(),
        "protected_m0_m7_after_count":len(after_m07),"protected_m0_m7_changed_paths":changed_m07,
        "prior_m8_manifest_after_sha256":hashlib.sha256(json.dumps(after_old_m8,sort_keys=True).encode()).hexdigest(),
        "prior_m8_file_count_after":len(after_old_m8),"prior_m8_changed_paths":changed_old_m8,
        "frozen_code_config_manifest_after":after_frozen,"frozen_code_config_changed_paths":changed_frozen,
        "deterministic_comparison_excludes":["metadata.json"],"confidence_intervals":"Not reported: only two independent reserved seeds; descriptive paired trip summaries only."})
    (out/"metadata.json").write_text(json.dumps(meta,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    summary={"selected_m8_policy":persistence,"frozen_thresholds":m8_thresholds,"m5_thresholds":m5_thresholds,
        "trip_count":len(trip_manifest),"final_seeds":config["final_test"]["seeds"],"scenario_count":len(config["final_test"]["scenarios"]),
        "attack_case_count":len(cases),"attack_trip_count":len(trip_manifest)*len(cases),"trip_metric_rows":len(metric_rows),
        "normal_fpr_target":0.05,"normal_fpr_by_detector_scenario":[r for r in summaries if r["attack_type"]=="none"],
        "attack_event_results":[r for r in summaries if r["attack_type"] in ATTACK_TYPES],
        "paired_trip_comparison_rows":len(paired),"statistical_limit":"Two independent final-test seeds limit precision and generalization; no inferential CI is reported.",
        "no_final_data_tuning":True,"final_test_completed":True,"m8_overall_improvement_claimed":False,
        "outputs":{"trip_metrics":"trip_metrics.csv","observation_level":"observation_summary.csv","event_level":"event_summary.csv","condition_summary":"condition_summary.csv","paired_comparison":"paired_trip_comparisons.csv"}}
    _write_json(out/"summary.json",summary)
    return {"run_dir":out,"trip_count":len(trip_manifest),"case_count":len(cases),"metric_rows":len(metric_rows),"preserved":not(changed_m07 or changed_old_m8 or changed_frozen)}


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--config",type=Path,default=Path("config/m8_stage2b.yaml")); parser.add_argument("--run-id",required=True)
    args=parser.parse_args(); result=run_workflow(args.config,args.run_id); print(json.dumps({k:str(v) for k,v in result.items()},indent=2))


if __name__=="__main__":
    main()
