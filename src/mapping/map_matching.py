"""Explainable geometric road matcher with heading and network-aware continuity."""
from __future__ import annotations

import argparse
import csv
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
OUT_FIELDS = ("time_s", "trip_id", "vehicle_id", "matched", "matched_road_id", "matched_x_m", "matched_y_m", "distance_to_road_m", "candidate_count", "match_score")


@dataclass(frozen=True)
class Edge:
    edge_id: str
    start: str
    end: str
    shape: tuple[tuple[float, float], ...]
    length: float


@dataclass(frozen=True)
class Candidate:
    edge: Edge
    x: float
    y: float
    distance: float
    fraction: float
    heading: float
    emission: float


def load_network(path: Path) -> dict[str, Edge]:
    root = ET.parse(path).getroot()
    result = {}
    for node in root.findall("edge"):
        if node.get("function") == "internal" or not node.get("from") or not node.get("to"):
            continue
        lane = node.find("lane")
        if lane is None:
            continue
        shape_text = lane.get("shape", "")
        points = tuple(tuple(map(float, token.split(","))) for token in shape_text.split())
        if len(points) < 2:
            continue
        length = float(lane.get("length", "0"))
        result[node.attrib["id"]] = Edge(node.attrib["id"], node.attrib["from"], node.attrib["to"], points, length)
    if not result:
        raise ValueError(f"No drivable edge geometries in {path}")
    return result


def _project(x: float, y: float, edge: Edge) -> tuple[float, float, float, float]:
    best = (math.inf, 0.0, 0.0, 0.0)
    lengths = [math.hypot(b[0]-a[0], b[1]-a[1]) for a,b in zip(edge.shape, edge.shape[1:])]
    total = sum(lengths) or 1.0
    traversed = 0.0
    for (ax, ay), (bx, by), segment_length in zip(edge.shape, edge.shape[1:], lengths):
        dx, dy = bx-ax, by-ay
        denom = dx*dx + dy*dy
        t = min(1.0, max(0.0, ((x-ax)*dx+(y-ay)*dy)/denom)) if denom else 0.0
        px, py = ax+t*dx, ay+t*dy
        dist = math.hypot(x-px, y-py)
        if dist < best[0]:
            best = (dist, px, py, (traversed+t*segment_length)/total)
            heading = math.degrees(math.atan2(dy, dx)) % 360.0
        traversed += segment_length
    return best[0], best[1], best[2], best[3], heading


def _angle_diff(a: float, b: float) -> float:
    return abs((a-b+180.0) % 360.0 - 180.0)


def candidates(x: float, y: float, edges: dict[str, Edge], heading_deg: float | None,
               max_distance_m: float, heading_weight: float, max_count: int = 6) -> list[Candidate]:
    found = []
    for edge in edges.values():
        d, px, py, fraction, direction = _project(x, y, edge)
        if d <= max_distance_m:
            # SUMO heading convention 0=north, clockwise; convert to math angle from +x.
            observed = (90.0 - heading_deg) % 360.0 if heading_deg is not None else direction
            heading_error = _angle_diff(direction, observed)
            emission = d*d + heading_weight * (heading_error/45.0)**2
            found.append(Candidate(edge, px, py, d, fraction, direction, emission))
    return sorted(found, key=lambda c:c.emission)[:max_count]


def _network_distance(a: Candidate, b: Candidate, edges: dict[str, Edge]) -> float:
    if a.edge.edge_id == b.edge.edge_id:
        if b.fraction >= a.fraction:
            return (b.fraction-a.fraction)*a.edge.length
        return math.inf
    start_cost = (1.0-a.fraction)*a.edge.length
    target_cost = b.fraction*b.edge.length
    graph: dict[str, list[tuple[str,float]]] = {}
    for edge in edges.values():
        graph.setdefault(edge.start, []).append((edge.end, edge.length))
    dist = {a.edge.end: 0.0}
    queue = [(0.0, a.edge.end)]
    import heapq
    while queue:
        cost, node = heapq.heappop(queue)
        if cost != dist[node]:
            continue
        if node == b.edge.start:
            return start_cost + cost + target_cost
        for nxt, length in graph.get(node, []):
            candidate_cost = cost + length
            if candidate_cost < dist.get(nxt, math.inf):
                dist[nxt] = candidate_cost
                heapq.heappush(queue, (candidate_cost, nxt))
    return math.inf


def match_rows(gps_rows: list[dict[str, str]], motion_rows: list[dict[str, str]], edges: dict[str, Edge],
               radius_m: float = 30.0, heading_weight: float = 16.0) -> list[dict[str, Any]]:
    motion = {(r["trip_id"],r["vehicle_id"],float(r["time_s"])):r for r in motion_rows}
    rows = sorted(gps_rows, key=lambda r:(r["trip_id"],r["vehicle_id"],float(r["time_s"])))
    out: list[dict[str, Any]] = []
    groups: dict[tuple[str,str],list[dict[str,str]]] = {}
    for row in rows: groups.setdefault((row["trip_id"],row["vehicle_id"]),[]).append(row)
    for (_, _), seq in groups.items():
        previous: Candidate | None = None
        prev_time = 0.0
        for row in seq:
            key=(row["trip_id"],row["vehicle_id"],float(row["time_s"]))
            mr=motion.get(key)
            hdg=float(mr["heading_deg"]) if mr else None
            pool=candidates(float(row["gps_x_m"]),float(row["gps_y_m"]),edges,hdg,radius_m,heading_weight)
            speed=float(mr["speed_mps"]) if mr else None
            if pool and previous:
                dt=max(0.0,float(row["time_s"])-prev_time)
                selected=min(pool,key=lambda c: c.emission + _transition_cost(previous,c,edges,speed,dt))
            else:
                selected=pool[0] if pool else None
            score=selected.emission if selected else None
            out.append({"time_s":row["time_s"],"trip_id":row["trip_id"],"vehicle_id":row["vehicle_id"],
                "matched":str(selected is not None).lower(),"matched_road_id":selected.edge.edge_id if selected else "",
                "matched_x_m":selected.x if selected else "","matched_y_m":selected.y if selected else "",
                "distance_to_road_m":selected.distance if selected else "","candidate_count":len(pool),"match_score":score if score is not None else ""})
            if selected is None: previous=None
            else: previous=selected; prev_time=float(row["time_s"])
    return out


def _transition_cost(a: Candidate,b: Candidate,edges: dict[str,Edge],speed: float|None,dt:float)->float:
    distance=_network_distance(a,b,edges)
    if not math.isfinite(distance): return 1e6
    expected=max(0.0,speed or 0.0)*dt
    # Mild continuity penalty; impossible network jumps are heavily discouraged.
    if distance > expected + max(35.0, 3.0*dt): return 1e5 + (distance-expected)**2
    return ((distance-expected)/max(8.0,expected*.5+5.0))**2


def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config",type=Path,default=ROOT/"config/experiment_config.yaml")
    parser.add_argument("--scenario",choices=("normal","offset","jump","drift","route_deviation"),default="normal")
    args=parser.parse_args(); cfg=yaml.safe_load(args.config.read_text(encoding="utf-8")); base=cfg["m4"]
    gps_path=cfg["gps"]["output_file"] if args.scenario=="normal" else cfg["attacks"]["route_deviation"]["gps_output"] if args.scenario=="route_deviation" else f"data/attacks/gps_{args.scenario}.csv"
    motion_path=f"{base['motion_dir']}/motion_{args.scenario}.csv"
    path=lambda p: Path(p) if Path(p).is_absolute() else ROOT/p
    with path(gps_path).open(newline="",encoding="utf-8") as f:gps=list(csv.DictReader(f))
    with path(motion_path).open(newline="",encoding="utf-8") as f:motion=list(csv.DictReader(f))
    result=match_rows(gps,motion,load_network(path(cfg["simulation"]["network_file"])),float(base["candidate_radius_m"]),float(base["heading_weight"]))
    output=path(base["output_dir"])/f"map_matched_{args.scenario}.csv"; output.parent.mkdir(parents=True,exist_ok=True)
    with output.open("w",newline="",encoding="utf-8") as f:w=csv.DictWriter(f,fieldnames=OUT_FIELDS);w.writeheader();w.writerows(result)
    print(f"Matched {sum(r['matched']=='true' for r in result)}/{len(result)} records -> {output}")
    return 0

if __name__=="__main__": raise SystemExit(main())
