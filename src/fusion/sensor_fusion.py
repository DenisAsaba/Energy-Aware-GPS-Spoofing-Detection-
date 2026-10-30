"""GPS-corrected dead-reckoning Kalman filter (operational inputs only)."""
from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
from typing import Any

import yaml

ROOT=Path(__file__).resolve().parents[2]
FIELDS=("time_s","trip_id","vehicle_id","fused_x_m","fused_y_m","fused_vx_mps","fused_vy_mps","gps_used","motion_used","position_sigma_m")


def fuse(gps_rows:list[dict[str,str]],motion_rows:list[dict[str,str]],gps_sigma_m:float,process_accel_sigma_mps2:float,
         speed_sigma_mps:float=0.25,heading_sigma_deg:float=2.0)->list[dict[str,Any]]:
    """Constant-velocity Kalman state [x,y,vx,vy]; first GPS fixes the arbitrary origin."""
    motion={(r["trip_id"],r["vehicle_id"],float(r["time_s"])):r for r in motion_rows}
    groups:dict[tuple[str,str],list[dict[str,str]]]={}
    for r in gps_rows:groups.setdefault((r["trip_id"],r["vehicle_id"]),[]).append(r)
    out=[]
    for seq in groups.values():
        seq.sort(key=lambda r:float(r["time_s"]))
        state: list[float]|None=None
        P: list[list[float]]|None=None
        last_t:float|None=None
        for row in seq:
            t=float(row["time_s"]); key=(row["trip_id"],row["vehicle_id"],t); m=motion.get(key)
            gps_ok=bool(row.get("gps_x_m")) and bool(row.get("gps_y_m"))
            motion_ok=m is not None and bool(m.get("speed_mps")) and bool(m.get("heading_deg"))
            if state is None:
                if not gps_ok: continue
                x,y=float(row["gps_x_m"]),float(row["gps_y_m"])
                vx=vy=0.0
                velocity_variance=25.0
                if motion_ok:
                    speed=float(m["speed_mps"]); theta=math.radians(90.0-float(m["heading_deg"]))
                    vx,vy=speed*math.cos(theta),speed*math.sin(theta)
                    velocity_variance=speed_sigma_mps**2+(speed*math.radians(heading_sigma_deg))**2
                state=[x,y,vx,vy]; P=[[gps_sigma_m**2,0,0,0],[0,gps_sigma_m**2,0,0],[0,0,velocity_variance,0],[0,0,0,velocity_variance]]
                last_t=t
            else:
                dt=max(0.0,t-(last_t if last_t is not None else t)); last_t=t
                # Predict with the previous velocity estimate, then update velocity from noisy speed/heading.
                state[0]+=state[2]*dt; state[1]+=state[3]*dt
                F=[[1,0,dt,0],[0,1,0,dt],[0,0,1,0],[0,0,0,1]]
                # P <- F P F' + white-acceleration process covariance (per axis).
                FP=[[sum(F[i][k]*P[k][j] for k in range(4)) for j in range(4)] for i in range(4)]
                P=[[sum(FP[i][k]*F[j][k] for k in range(4)) for j in range(4)] for i in range(4)]
                q=process_accel_sigma_mps2**2
                qpp=q*dt**4/4; qpv=q*dt**3/2; qvv=q*dt**2
                P[0][0]+=qpp;P[1][1]+=qpp;P[0][2]+=qpv;P[2][0]+=qpv;P[1][3]+=qpv;P[3][1]+=qpv;P[2][2]+=qvv;P[3][3]+=qvv
                if motion_ok:
                    speed=float(m["speed_mps"]); theta=math.radians(90.0-float(m["heading_deg"]))
                    velocity_observations=(speed*math.cos(theta),speed*math.sin(theta))
                    velocity_variance=speed_sigma_mps**2+(speed*math.radians(heading_sigma_deg))**2
                    for axis,measurement in zip((2,3),velocity_observations):
                        denom=P[axis][axis]+velocity_variance
                        gain=[P[i][axis]/denom for i in range(4)]
                        residual=measurement-state[axis]
                        state=[state[i]+gain[i]*residual for i in range(4)]
                        old_col=[P[i][axis] for i in range(4)]
                        P=[[P[i][j]-gain[i]*old_col[j] for j in range(4)] for i in range(4)]
                if gps_ok:
                    variance=gps_sigma_m**2
                    for axis in (0,1):
                        denom=P[axis][axis]+variance
                        gain=[P[i][axis]/denom for i in range(4)]
                        residual=float(row["gps_x_m"] if axis==0 else row["gps_y_m"])-state[axis]
                        state=[state[i]+gain[i]*residual for i in range(4)]
                        old_col=[P[i][axis] for i in range(4)]
                        P=[[P[i][j]-gain[i]*old_col[j] for j in range(4)] for i in range(4)]
            out.append({"time_s":row["time_s"],"trip_id":row["trip_id"],"vehicle_id":row["vehicle_id"],
                "fused_x_m":state[0],"fused_y_m":state[1],"fused_vx_mps":state[2],"fused_vy_mps":state[3],
                "gps_used":str(gps_ok).lower(),"motion_used":str(motion_ok).lower(),"position_sigma_m":math.sqrt(max(0.0,(P[0][0]+P[1][1])/2))})
    return out


def main()->int:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--config",type=Path,default=ROOT/"config/experiment_config.yaml");p.add_argument("--scenario",choices=("normal","offset","jump","drift","route_deviation"),default="normal");a=p.parse_args()
    cfg=yaml.safe_load(a.config.read_text(encoding="utf-8"));m4=cfg["m4"]
    gps=cfg["gps"]["output_file"] if a.scenario=="normal" else cfg["attacks"]["route_deviation"]["gps_output"] if a.scenario=="route_deviation" else f"data/attacks/gps_{a.scenario}.csv"
    path=lambda v:Path(v) if Path(v).is_absolute() else ROOT/v
    read=lambda v:list(csv.DictReader(path(v).open(newline="",encoding="utf-8")))
    rows=fuse(read(gps),read(f"{m4['motion_dir']}/motion_{a.scenario}.csv"),float(cfg["gps"]["position_std_m"]),float(m4["process_acceleration_std_mps2"]))
    dest=path(m4["output_dir"])/f"fused_{a.scenario}.csv";dest.parent.mkdir(parents=True,exist_ok=True)
    with dest.open("w",newline="",encoding="utf-8") as stream:w=csv.DictWriter(stream,fieldnames=FIELDS);w.writeheader();w.writerows(rows)
    print(f"Fused {len(rows)} observations -> {dest}");return 0

if __name__=="__main__":raise SystemExit(main())
