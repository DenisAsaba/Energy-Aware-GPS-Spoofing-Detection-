"""M8 Stage 2A normal-driving expansion and validation (never final test)."""
from __future__ import annotations
import argparse, csv, hashlib, json, logging, shutil
from pathlib import Path
from typing import Any
import numpy as np
import yaml
from src.attacks.gps_attacks import generate_attack
from src.detection.m8_detector import extract_m8_features, calibrate_m8_thresholds, apply_m8_thresholds
from src.experiments.m8_evaluation import (_metrics, _read_labels, _stable_seed, _write_csv, _write_json,
                                            _prediction_pair, _validate_splits, compare_runs, protected_manifest,
                                            ATTACK_TYPES, METRIC_FIELDS, _sha256)
from src.experiments.m8_stage2a_scenarios import build_scenario_inputs, scenario_manifest
from src.simulation.run_sumo import run as run_sumo
from src.sensors.gps_normal import generate_observations

LOGGER=logging.getLogger("m8_stage2a")

def _trip(root: Path, cfg: dict[str,Any], run_dir: Path, split: str, index: int, seed: int, scenario: str):
    trip_id=f"{split}_{scenario}_seed{seed}"; out=run_dir/"trips"/trip_id
    out.mkdir(parents=True,exist_ok=False)
    inputs=build_scenario_inputs(out/"inputs",scenario,seed)
    sim={"seed":seed,"step_length_s":cfg["simulation"]["step_length_s"],"begin_s":0,"end_s":600,
         "vehicle_id":"ev_001","network_file":str(inputs["network"]),"route_file":str(inputs["routes"]),
         "telemetry_output_dir":str(out),"depart_s":0}
    simpath=out/"simulation.yaml"; simpath.write_text(yaml.safe_dump({"simulation":sim},sort_keys=True),encoding="utf-8")
    truth=out/"truth.csv"; run_sumo(simpath,output_path=truth)
    gps=out/"normal_gps.csv"; gps_seed=_stable_seed(cfg["gps"]["seed_offset"],seed,scenario)
    generate_observations(truth,gps,noise_std_m=cfg["gps"]["noise_std_m_per_axis"],seed=gps_seed)
    return {"trip_id":trip_id,"split":split,"seed":seed,"scenario":scenario,"truth":truth,"gps":gps,"gps_seed":gps_seed,
            "hashes":{name:_sha256(path) for name,path in inputs.items()},"traffic_vehicles":scenario_manifest()[scenario]["traffic"]}

def run_workflow(config_path:Path,run_id:str):
    if not run_id or not all(c.isalnum() or c in "-_" for c in run_id): raise ValueError("invalid run_id")
    config_path=config_path.resolve(); cfg=yaml.safe_load(config_path.read_text(encoding="utf-8")); root=config_path.parent.parent
    outroot=(config_path.parent/cfg["outputs"]["root"]).resolve(); run_dir=outroot/run_id
    if run_dir.exists(): raise FileExistsError(run_dir)
    seeds={k:v for k,v in cfg["splits"].items() if k in ("calibration","validation")}
    if set(seeds["calibration"])&set(seeds["validation"]): raise ValueError("calibration/validation seed overlap")
    reserved=yaml.safe_load((root/"config/m8_detector.yaml").read_text(encoding="utf-8"))["splits"]["final_test"]["trips"]
    reserved_seeds={int(t["seed"]) for t in reserved}
    if (set(seeds["calibration"])|set(seeds["validation"]))&reserved_seeds: raise ValueError("Stage 2A reuses reserved final seed")
    before=protected_manifest(root); run_dir.mkdir(parents=True,exist_ok=False); shutil.copy2(config_path,run_dir/"m8_stage2a.yaml")
    calibration=[]; validation=[]; manifest=[]
    scenarios=cfg["scenarios"]
    for split,target in (("calibration",calibration),("validation",validation)):
        for i,seed in enumerate(cfg["splits"][split]):
            scenario=scenarios[i%len(scenarios)]
            trip=_trip(root,cfg,run_dir,split,i,int(seed),scenario); target.append(trip)
            manifest.append({k:v for k,v in trip.items() if k not in ("truth","gps")})
    det=cfg["detector"]; feature_sets=[extract_m8_features(t["gps"],rolling_speed_window=det["rolling_speed_window"]) for t in calibration]
    thresholds,cal_details=calibrate_m8_thresholds(feature_sets,quantile=det["normal_quantile"],calibration_fraction_per_trip=det["calibration_fraction_per_trip"])
    _write_json(run_dir/"calibration.json",{"calibration_trips":len(calibration),"thresholds":thresholds,"details":cal_details,"training_only_normal_data":True})
    m5_thresholds={k:thresholds[k] for k in ("max_speed_mps","max_speed_change_mps","max_heading_change_deg")}
    candidates=[]; all_rows=[]; attack_observations=[]
    # Predictions for all candidate policies are completed before labels are read.
    for trip in validation:
        feats=extract_m8_features(trip["gps"],rolling_speed_window=det["rolling_speed_window"])
        labels_normal={(float(r["time_s"]),str(r["vehicle_id"])):{"attack_active":0} for r in feats if r.get("time_s") is not None}
        datasets={"normal":(trip["gps"],labels_normal,None)}
        attack_paths={}
        for kind in ATTACK_TYPES:
            ap=run_dir/"attacks"/trip["trip_id"]/f"{kind}.csv"; ap.parent.mkdir(parents=True,exist_ok=True)
            settings=dict(cfg["attacks"][kind]); settings["attack_id"]=trip["trip_id"]+"_"+kind
            _,lp=generate_attack(trip["truth"],ap,attack_type=kind,settings=settings,noise_std_m=cfg["gps"]["noise_std_m_per_axis"],seed=trip["gps_seed"])
            attack_paths[kind]=(ap,lp,settings); datasets[kind]=(ap,None,settings)
        for scenario,(path,labels,settings) in datasets.items():
            features=extract_m8_features(path,rolling_speed_window=det["rolling_speed_window"])
            for ci,policy in enumerate(det["persistence_candidates"]):
                preds=apply_m8_thresholds(features,thresholds,policy)
                lab=labels if labels is not None else _read_labels(attack_paths[scenario][1])
                row=_metrics(preds,lab,split="validation",trip={"trip_id":trip["trip_id"],"seed":trip["seed"],"route_group":trip["scenario"]},scenario=scenario,detector=f"M8_candidate_{ci}",settings=settings)
                row["scenario_type"]=trip["scenario"]; candidates.append(row)
                if ci==0:
                    m5pred,m8pred=_prediction_pair(path,window=det["rolling_speed_window"],m5_thresholds=m5_thresholds,m8_thresholds=thresholds,persistence=det["persistence_candidates"][0])
                    lab0=labels if labels is not None else _read_labels(attack_paths[scenario][1])
                    for detector,pred in (("M5",m5pred),("M8_candidate_0",m8pred)):
                        metr=_metrics(pred,lab0,split="validation",trip={"trip_id":trip["trip_id"],"seed":trip["seed"],"route_group":trip["scenario"]},scenario=scenario,detector=detector,settings=settings)
                        metr["scenario_type"]=trip["scenario"]; all_rows.append(metr)
    fields=list(METRIC_FIELDS)+["scenario_type"]
    _write_csv(run_dir/"validation_candidate_metrics.csv",fields,candidates)
    summaries=[]
    for i,policy in enumerate(det["persistence_candidates"]):
        rows=[r for r in candidates if r["detector"]==f"M8_candidate_{i}"]; normals=[r for r in rows if r["scenario"]=="normal"]
        fpr=sum(r["fp"] for r in normals)/max(1,sum(r["fp"]+r["tn"] for r in normals))
        summaries.append({"candidate_index":i,"policy":policy,"normal_fpr":fpr,"meets_5pct":fpr<=det["maximum_normal_false_positive_rate"],"mean_attack_event_detection":float(np.mean([r["active_attack_detection_rate"] for r in rows if r["scenario"] in ATTACK_TYPES]))})
    qualified=[r for r in summaries if r["meets_5pct"]]
    selected=min(qualified or summaries,key=lambda r:(-r["mean_attack_event_detection"] if qualified else r["normal_fpr"],r["candidate_index"]))
    selected_index=int(selected["candidate_index"])
    # Main validation comparison uses the selected M8 candidate and matched M5 rows.
    all_rows=[row for row in all_rows if row["detector"]=="M5"]
    all_rows.extend({**row,"detector":"M8"} for row in candidates if row["detector"]==f"M8_candidate_{selected_index}")
    selected_policy=det["persistence_candidates"][selected_index]
    for trip in validation:
        for scenario,path in [("normal",trip["gps"]),*((kind,run_dir/"attacks"/trip["trip_id"]/f"{kind}.csv") for kind in ATTACK_TYPES)]:
            m5pred,m8pred=_prediction_pair(path,window=det["rolling_speed_window"],m5_thresholds=m5_thresholds,m8_thresholds=thresholds,persistence=selected_policy)
            _write_csv(run_dir/"predictions"/trip["trip_id"]/f"{scenario}.csv",list(m8pred[0].keys()),[{**r,"m5_predicted_attack":m.get("predicted_attack","")} for r,m in zip(m8pred,m5pred)])
    _write_csv(run_dir/"validation_metrics.csv",fields,all_rows)
    _write_json(run_dir/"validation_selection.json",{"criterion":"predeclared normal FPR <=5%; tie-break by event detection","candidate_summaries":summaries,"selected":selected,"candidate_meeting_target":bool(qualified)})
    after=protected_manifest(root); changed=sorted(p for p in set(before)|set(after) if before.get(p)!=after.get(p))
    metadata={"milestone":"M8 Stage 2A","run_id":run_id,"final_test_executed":False,"reserved_final_test_seeds_unchanged":sorted(reserved_seeds),"m7_test_seeds_used":False,"split_seeds":seeds,"scenario_assignments":manifest,"scenario_definitions":scenario_manifest(),"input_file_sha256":{"stage2a_config":_sha256(config_path),"scenario_builder":_sha256(Path(__file__).with_name("m8_stage2a_scenarios.py"))},"vehicle_settings":{"ev":{"accel_mps2":1.7,"decel_mps2":4.0,"max_speed_mps":13.89,"capacity_wh":50000,"initial_charge_wh":25000},"background":{"accel_mps2":2.0,"decel_mps2":4.5,"max_speed_mps":13.89}},"simulation_settings":{"step_length_s":cfg["simulation"]["step_length_s"],"gps_noise_std_m_per_axis":cfg["gps"]["noise_std_m_per_axis"],"gps_seed_offset":cfg["gps"]["seed_offset"]},"protected_manifest_before_sha256":hashlib.sha256(json.dumps(before,sort_keys=True).encode()).hexdigest(),"protected_manifest_after_sha256":hashlib.sha256(json.dumps(after,sort_keys=True).encode()).hexdigest(),"protected_count_before":len(before),"protected_count_after":len(after),"protected_changes":changed}
    _write_json(run_dir/"metadata.json",metadata)
    if changed: raise RuntimeError(f"protected M0-M7 files changed: {changed}")
    _write_json(run_dir/"summary.json",{"thresholds":thresholds,"selected":selected,"candidate_summaries":summaries,"validation_metrics":all_rows,"calibration_trip_count":len(calibration),"validation_trip_count":len(validation),"final_test_run":False})
    return {"run_dir":run_dir,"selected":selected,"candidates":summaries,"metrics":all_rows}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--config",type=Path,default=Path("config/m8_stage2a.yaml"));p.add_argument("--run-id",required=True);a=p.parse_args();logging.basicConfig(level=logging.INFO)
    r=run_workflow(a.config,a.run_id);print(r["run_dir"])
if __name__=="__main__":main()
