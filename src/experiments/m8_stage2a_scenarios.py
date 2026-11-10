"""M8 Stage 2A isolated SUMO scenario input generator."""
from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Any


SCENARIOS = {
    "urban_turns_light": {"route": ["west", "east", "north", "south"], "stop": None, "traffic": 0, "speed_factor": 0.78},
    "urban_stop_restart": {"route": ["west", "east", "north", "south"], "stop": ("east", 65, 5), "traffic": 5, "speed_factor": 0.88},
    "urban_brake_accel": {"route": ["south_r", "north_r", "east_r", "west_r"], "stop": ("east_r", 75, 3), "traffic": 12, "speed_factor": 1.0},
}


def build_scenario_inputs(directory: Path, scenario: str, seed: int) -> dict[str, Path]:
    """Write an M8-only 2x2 block network and varied EV/background routes.

    Stops are curbside dwell events (5s/3s), not a claim to model signal control.
    Background traffic traverses shared edges and is seeded via deterministic
    departure times; speed variation comes from SUMO's vehicle speedFactor.
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown M8 Stage 2A scenario: {scenario}")
    directory.mkdir(parents=True, exist_ok=True)
    nodes, edges, net, routes = (directory / name for name in ("grid.nod.xml", "grid.edg.xml", "grid.net.xml", "scenario.rou.xml"))
    node_root = ET.Element("nodes")
    for node, x, y in (("sw", 0, 0), ("se", 180, 0), ("ne", 180, 180), ("nw", 0, 180)):
        ET.SubElement(node_root, "node", id=node, x=str(x), y=str(y), type="priority")
    ET.ElementTree(node_root).write(nodes, encoding="utf-8", xml_declaration=True)
    edge_root = ET.Element("edges")
    for edge, frm, to in (("west", "sw", "se"), ("west_r", "se", "sw"), ("east", "se", "ne"), ("east_r", "ne", "se"), ("north", "ne", "nw"), ("north_r", "nw", "ne"), ("south", "nw", "sw"), ("south_r", "sw", "nw")):
        ET.SubElement(edge_root, "edge", id=edge, **{"from": frm, "to": to, "numLanes": "1", "speed": "13.89", "length": "180"})
    ET.ElementTree(edge_root).write(edges, encoding="utf-8", xml_declaration=True)
    import shutil, subprocess
    netconvert = shutil.which("netconvert")
    if not netconvert:
        raise RuntimeError("netconvert is required for M8 Stage 2A; install SUMO and add its bin directory to PATH")
    result = subprocess.run([netconvert, "--node-files", str(nodes), "--edge-files", str(edges), "--output-file", str(net), "--no-turnarounds", "true"], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"netconvert failed: {result.stderr.strip()}")
    root = ET.Element("routes")
    ev_type = ET.SubElement(root, "vType", id="ev", vClass="passenger", accel="1.7", decel="4.0", maxSpeed="13.89", speedFactor=str(SCENARIOS[scenario]["speed_factor"]), emissionClass="Energy/unknown")
    for key, value in (("has.battery.device", "true"), ("device.battery.capacity", "50000"),
                       ("device.battery.maximumChargeRate", "100000"), ("device.battery.maximumDischargeRate", "100000"),
                       ("device.battery.mass", "1500"), ("device.battery.frontSurfaceArea", "2.2"),
                       ("device.battery.airDragCoefficient", "0.29"), ("device.battery.constantPowerIntake", "100")):
        ET.SubElement(ev_type, "param", key=key, value=value)
    ET.SubElement(root, "vType", id="traffic", vClass="passenger", accel="2.0", decel="4.5", maxSpeed="13.89")
    route_edges = " ".join(SCENARIOS[scenario]["route"])
    ET.SubElement(root, "route", id="evroute", edges=route_edges)
    ev = ET.SubElement(root, "vehicle", id="ev_001", type="ev", route="evroute", depart="0", departSpeed="0")
    ET.SubElement(ev, "param", key="device.battery.chargeLevel", value="25000")
    stop = SCENARIOS[scenario]["stop"]
    if stop:
        edge, pos, duration = stop
        ET.SubElement(ev, "stop", lane=f"{edge}_0", endPos=str(pos), duration=str(duration))
    for idx in range(SCENARIOS[scenario]["traffic"]):
        depart = 8 + idx * 11 + ((seed * 17 + idx * 7) % 5)
        ET.SubElement(root, "vehicle", id=f"traffic_{idx:02d}", type="traffic", route="evroute", depart=str(depart), departSpeed="max")
    ET.ElementTree(root).write(routes, encoding="utf-8", xml_declaration=True)
    return {"nodes": nodes, "edges": edges, "network": net, "routes": routes}


def scenario_manifest() -> dict[str, Any]:
    return {key: dict(value) for key, value in SCENARIOS.items()}
