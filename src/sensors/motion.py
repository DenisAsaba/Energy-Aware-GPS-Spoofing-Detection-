"""Generate explicitly simulated, noisy motion-sensor observations."""
from __future__ import annotations

import argparse
import csv
import math
import random
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
FIELDS = ("time_s", "trip_id", "vehicle_id", "motion_seed", "speed_mps", "heading_deg", "acceleration_mps2")


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError(f"No telemetry records in {path}")
    return rows


def generate(truth_path: Path, output_path: Path, seed: int, speed_sigma: float, heading_sigma: float, acceleration_sigma: float) -> int:
    if truth_path.resolve() == output_path.resolve():
        raise ValueError("Motion observations must not overwrite truth")
    sigmas = (speed_sigma, heading_sigma, acceleration_sigma)
    if any(not math.isfinite(s) or s < 0 for s in sigmas):
        raise ValueError("Motion noise standard deviations must be finite and nonnegative")
    rng = random.Random(seed)
    output: list[dict[str, Any]] = []
    for row in read_rows(truth_path):
        # SUMO getAngle: 0 degrees is north, increasing clockwise. Heading noise is circular.
        heading = (float(row["heading_deg"]) + rng.gauss(0.0, heading_sigma)) % 360.0
        output.append({
            "time_s": row["time_s"], "trip_id": row["trip_id"], "vehicle_id": row["vehicle_id"],
            "motion_seed": seed,
            "speed_mps": max(0.0, float(row["speed_mps"]) + rng.gauss(0.0, speed_sigma)),
            "heading_deg": heading,
            "acceleration_mps2": float(row["acceleration_mps2"]) + rng.gauss(0.0, acceleration_sigma),
        })
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(output)
    return len(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config/experiment_config.yaml")
    parser.add_argument("--scenario", choices=("all", "normal", "offset", "jump", "drift", "route_deviation"), default="all")
    args = parser.parse_args()
    cfg = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    settings = cfg["motion"]
    scenarios = ("normal", "offset", "jump", "drift", "route_deviation") if args.scenario == "all" else (args.scenario,)
    for index, name in enumerate(scenarios):
        truth = cfg["gps"]["input_file"] if name != "route_deviation" else cfg["attacks"]["route_deviation"]["truth_output"]
        output = Path(settings["output_dir"]) / f"motion_{name}.csv"
        path = lambda value: value if Path(value).is_absolute() else ROOT / value
        count = generate(path(truth), path(output), int(settings["seed"]) + index,
                         float(settings["speed_std_mps"]), float(settings["heading_std_deg"]), float(settings["acceleration_std_mps2"]))
        print(f"Generated {count} {name} motion observations: {path(output)} (seed={int(settings['seed']) + index})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
