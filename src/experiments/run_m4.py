"""Run M4 sensor generation, map matching, fusion and offline evaluation."""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
import sys
import tempfile
from pathlib import Path

import yaml

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src/sensors"));sys.path.insert(0,str(ROOT/"src/mapping"));sys.path.insert(0,str(ROOT/"src/fusion"))
import motion, map_matching, sensor_fusion

SCENARIOS=("normal","offset","jump","drift","route_deviation")

def read(path:Path)->list[dict[str,str]]:
    with path.open(newline="",encoding="utf-8") as f:return list(csv.DictReader(f))
def write(path:Path,fields:tuple[str,...],rows:list[dict])->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",newline="",encoding="utf-8") as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
def key(r:dict[str,str])->tuple[str,str,float]:return r["trip_id"],r["vehicle_id"],float(r["time_s"])

def metrics(truth:list[dict[str,str]],est:list[dict[str,str]],xcol:str,ycol:str,allowed:set|None=None)->dict:
    t={key(r):r for r in truth};e={key(r):r for r in est};errors=[]
    for k,r in e.items():
        if allowed is not None and k not in allowed:continue
        if k in t and r.get(xcol) not in (None,"") and r.get(ycol) not in (None,""):
            errors.append(math.hypot(float(r[xcol])-float(t[k]["x_m"]),float(r[ycol])-float(t[k]["y_m"])))
    if not errors:return {"valid_records":0,"mean_error_m":None,"median_error_m":None,"p95_error_m":None,"rmse_m":None,"maximum_error_m":None}
    ordered=sorted(errors)
    return {"valid_records":len(errors),"mean_error_m":statistics.fmean(errors),"median_error_m":statistics.median(errors),
        "p95_error_m":ordered[math.ceil(.95*len(ordered))-1],"rmse_m":math.sqrt(statistics.fmean(e*e for e in errors)),"maximum_error_m":max(errors)}

def scenario_paths(cfg:dict,name:str)->tuple[Path,Path,Path]:
    gps=cfg["gps"]["output_file"] if name=="normal" else cfg["attacks"]["route_deviation"]["gps_output"] if name=="route_deviation" else f"data/attacks/gps_{name}.csv"
    truth=cfg["gps"]["input_file"] if name!="route_deviation" else cfg["attacks"]["route_deviation"]["truth_output"]
    return tuple((Path(v) if Path(v).is_absolute() else ROOT/v) for v in (gps,truth))

def run(config_path:Path,stage:str,scenario:str)->dict:
    cfg=yaml.safe_load(config_path.read_text(encoding="utf-8"));m4=cfg["m4"]
    root=lambda v:Path(v) if Path(v).is_absolute() else ROOT/v
    names=SCENARIOS if scenario=="all" else (scenario,)
    network=map_matching.load_network(root(cfg["simulation"]["network_file"]))
    motion_dir=root(m4["motion_dir"]);outdir=root(m4["output_dir"]);figdir=root(m4["figure_dir"]);table_dir=root(m4["table_dir"])
    if stage in ("all","motion"):
        for i,name in enumerate(names):
            _,truth=scenario_paths(cfg,name)
            target=motion_dir/f"motion_{name}.csv"
            ms=cfg["motion"]
            n=motion.generate(truth,target,int(m4["motion_seed"])+i,float(ms["speed_std_mps"]),float(ms["heading_std_deg"]),float(ms["acceleration_std_mps2"]))
            print(f"Motion {name}: {n} rows -> {target}")
    if stage in ("all","map-match","fusion","evaluate"):
        for name in names:
            gps_path,truth_path=scenario_paths(cfg,name);gps=read(gps_path);motion_rows=read(motion_dir/f"motion_{name}.csv")
            if stage in ("all","map-match"):
                matched=map_matching.match_rows(gps,motion_rows,network,float(m4["candidate_radius_m"]),float(m4["heading_weight"]))
                write(outdir/f"map_matched_{name}.csv",map_matching.OUT_FIELDS,matched)
                print(f"Map match {name}: {sum(r['matched']=='true' for r in matched)}/{len(matched)}")
            if stage in ("all","fusion"):
                ms=cfg["motion"]
                fused=sensor_fusion.fuse(gps,motion_rows,float(cfg["gps"]["position_std_m"]),float(m4["process_acceleration_std_mps2"]),float(ms["speed_std_mps"]),float(ms["heading_std_deg"]))
                write(outdir/f"fused_{name}.csv",sensor_fusion.FIELDS,fused)
                print(f"Fusion {name}: {len(fused)} rows")
    if stage in ("all","evaluate"):
        cache=Path(tempfile.gettempdir())/"ev-gps-agent-matplotlib"
        cache.mkdir(parents=True,exist_ok=True)
        os.environ.setdefault("MPLCONFIGDIR",str(cache))
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        report={"evaluation_only":True,"ground_truth_used_only_for_evaluation":True,"scenarios":{}}
        comparison={"raw_gps":[],"map_matched":[],"sensor_fused":[]}
        for name in names:
            gps_path,truth_path=scenario_paths(cfg,name);gps=read(gps_path);truth=read(truth_path)
            matched=read(outdir/f"map_matched_{name}.csv");fused=read(outdir/f"fused_{name}.csv")
            matched_keys={key(r) for r in matched if r["matched"]=="true"}
            common=matched_keys & {key(r) for r in truth} & {key(r) for r in gps} & {key(r) for r in fused}
            raw_m=metrics(truth,gps,"gps_x_m","gps_y_m",common);map_m=metrics(truth,matched,"matched_x_m","matched_y_m",common);fuse_m=metrics(truth,fused,"fused_x_m","fused_y_m",common)
            successes=sum(r["matched"]=="true" for r in matched);n=len(matched)
            map_m["map_match_success_rate"]=(successes/n if n else None);map_m["unmatched_percentage"]=(100*(n-successes)/n if n else None)
            report["scenarios"][name]={"comparison_record_count":len(common),"input_record_count":n,
                "unmatched_record_count":n-successes,"raw_gps":raw_m,"map_matched":map_m,"sensor_fused":fuse_m}
            for method,m in (("raw_gps",raw_m),("map_matched",map_m),("sensor_fused",fuse_m)):comparison[method].append(m["rmse_m"])
            truth_by={key(r):r for r in truth}
            figure,ax=plt.subplots(figsize=(9,6),layout="constrained")
            ax.plot([float(r["x_m"]) for r in truth],[float(r["y_m"]) for r in truth],label="Ground truth (evaluation only)",lw=2)
            ax.plot([float(r["gps_x_m"]) for r in gps],[float(r["gps_y_m"]) for r in gps],".",ms=3,label="Raw GPS")
            valid=[r for r in matched if r["matched"]=="true"]
            ax.plot([float(r["matched_x_m"]) for r in valid],[float(r["matched_y_m"]) for r in valid],"--",lw=1.2,label="Map matched")
            ax.plot([float(r["fused_x_m"]) for r in fused],[float(r["fused_y_m"]) for r in fused],"-",lw=1.1,label="GPS + motion Kalman")
            ax.set(title=f"M4 position estimates — {name}",xlabel="SUMO network X (m)",ylabel="SUMO network Y (m)");ax.set_aspect("equal",adjustable="datalim");ax.grid(alpha=.3);ax.legend(fontsize="small")
            figdir.mkdir(parents=True,exist_ok=True);figure.savefig(figdir/f"m4_{name}_trajectories.png",dpi=180);plt.close(figure)
            # Error distributions use aligned keys and are explicitly post-hoc.
            fig,ax=plt.subplots(figsize=(8,5),layout="constrained")
            for label,rows,x,y in (("Raw GPS",gps,"gps_x_m","gps_y_m"),("Map matched",matched,"matched_x_m","matched_y_m"),("Sensor fused",fused,"fused_x_m","fused_y_m")):
                e=[]
                for row in rows:
                    k=key(row)
                    if k not in common:continue
                    if k in truth_by and row.get(x) not in (None,"") and row.get(y) not in (None,""):
                        e.append(math.hypot(float(row[x])-float(truth_by[k]["x_m"]),float(row[y])-float(truth_by[k]["y_m"])))
                if e:ax.hist(e,bins=16,alpha=.45,label=label)
            ax.set(title=f"M4 position error (offline) — {name}",xlabel="Position error (m)",ylabel="Record count");ax.grid(axis="y",alpha=.3);ax.legend()
            fig.savefig(figdir/f"m4_{name}_error_distributions.png",dpi=180);plt.close(fig)
        # RMSE summary across methods/scenarios.
        fig,ax=plt.subplots(figsize=(10,5),layout="constrained");width=.24;x=list(range(len(names)))
        for j,(method,vals) in enumerate(comparison.items()):ax.bar([i+(j-1)*width for i in x],[v or 0 for v in vals],width,label=method.replace("_"," "))
        ax.set_xticks(x,names,rotation=15);ax.set_ylabel("RMSE (m)");ax.set_title("Position RMSE by scenario and estimator (offline)");ax.grid(axis="y",alpha=.3);ax.legend()
        figdir.mkdir(parents=True,exist_ok=True);fig.savefig(figdir/"m4_rmse_comparison.png",dpi=180);plt.close(fig)
        table_dir.mkdir(parents=True,exist_ok=True);target=table_dir/"m4_metrics.json";target.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n",encoding="utf-8")
        print(f"Evaluation summary -> {target}; figures -> {figdir}")
        return report
    return {}

def main()->int:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--config",type=Path,default=ROOT/"config/experiment_config.yaml");p.add_argument("--stage",choices=("all","motion","map-match","fusion","evaluate"),default="all");p.add_argument("--scenario",choices=("all",*SCENARIOS),default="all");a=p.parse_args()
    run(a.config.resolve(),a.stage,a.scenario);return 0
if __name__=="__main__":raise SystemExit(main())
