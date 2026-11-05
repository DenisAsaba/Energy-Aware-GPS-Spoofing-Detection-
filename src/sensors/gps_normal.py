"""Generate normal GPS observations and evaluate them offline against SUMO truth.

All positions are SUMO road-network X/Y coordinates in meters. The generator
does not write truth coordinates or error values to the operational GPS CSV.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import yaml

LOGGER = logging.getLogger("m2")
GPS_FIELDS = ("time_s", "vehicle_id", "gps_x_m", "gps_y_m")
KEY_FIELDS = ("time_s", "vehicle_id")


def _read_csv(path: Path) -> list[dict[str, str]]:
    """Read a nonempty CSV and reject malformed rows and duplicate headers."""
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
                raise ValueError(f"{path}: missing or duplicate CSV headers")
            rows = list(reader)
    except OSError as exc:
        raise ValueError(f"Could not read CSV {path}: {exc}") from exc
    if not rows:
        raise ValueError(f"CSV has no data rows: {path}")
    if any(None in row for row in rows):
        raise ValueError(f"CSV contains rows with extra fields: {path}")
    return rows


def _validated_rows(rows: list[dict[str, str]], path: Path) -> list[tuple[float, str, float, float]]:
    required = set(KEY_FIELDS) | {"x_m", "y_m"}
    if not required.issubset(rows[0]):
        raise ValueError(f"{path} is missing required columns: {sorted(required - set(rows[0]))}")
    parsed = []
    keys = set()
    for line, row in enumerate(rows, start=2):
        try:
            time_s, x, y = (float(row[column]) for column in ("time_s", "x_m", "y_m"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{path}:{line}: invalid/missing time_s, x_m, or y_m") from exc
        if not all(math.isfinite(value) for value in (time_s, x, y)) or not row["vehicle_id"]:
            raise ValueError(f"{path}:{line}: nonfinite coordinate/time or empty vehicle_id")
        key = (time_s, row["vehicle_id"])
        if key in keys:
            raise ValueError(f"{path}:{line}: duplicate timestamp/vehicle key {key}")
        keys.add(key)
        parsed.append((time_s, row["vehicle_id"], x, y))
    return parsed


def generate_observations(
    input_path: Path, output_path: Path, *, noise_std_m: float, seed: int,
) -> list[dict[str, str]]:
    """Write independently perturbed GPS coordinates using a local seeded RNG."""
    if not math.isfinite(noise_std_m) or noise_std_m < 0:
        raise ValueError("noise_std_m must be a finite nonnegative value")
    if input_path.resolve() == output_path.resolve():
        raise ValueError("GPS output must be separate from ground-truth input")
    source = _validated_rows(_read_csv(input_path), input_path)
    rng = np.random.default_rng(seed)
    errors = rng.normal(loc=0.0, scale=noise_std_m, size=(len(source), 2))
    observations = [
        {"time_s": format(time_s, ".15g"), "vehicle_id": vehicle_id,
         "gps_x_m": format(x + float(error[0]), ".15g"),
         "gps_y_m": format(y + float(error[1]), ".15g")}
        for (time_s, vehicle_id, x, y), error in zip(source, errors)
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=GPS_FIELDS)
        writer.writeheader()
        writer.writerows(observations)
    return observations


def evaluate_observations(truth_path: Path, gps_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Join on (time_s, vehicle_id) and compute horizontal Euclidean errors."""
    truth = _validated_rows(_read_csv(truth_path), truth_path)
    gps_rows = _read_csv(gps_path)
    required = set(KEY_FIELDS) | {"gps_x_m", "gps_y_m"}
    if not required.issubset(gps_rows[0]):
        raise ValueError(f"{gps_path} is missing required columns: {sorted(required - set(gps_rows[0]))}")
    truth_by_key = {(t, vehicle): (x, y) for t, vehicle, x, y in truth}
    gps_by_key: dict[tuple[float, str], tuple[float, float]] = {}
    for line, row in enumerate(gps_rows, start=2):
        try:
            key = (float(row["time_s"]), row["vehicle_id"])
            coords = (float(row["gps_x_m"]), float(row["gps_y_m"]))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{gps_path}:{line}: invalid/missing key or GPS coordinate") from exc
        if not all(map(math.isfinite, (*key[:1], *coords))) or not key[1]:
            raise ValueError(f"{gps_path}:{line}: nonfinite key/coordinate or empty vehicle_id")
        if key in gps_by_key:
            raise ValueError(f"{gps_path}:{line}: duplicate timestamp/vehicle key {key}")
        gps_by_key[key] = coords
    errors = []
    for time_s, vehicle, x, y in truth:
        key = (time_s, vehicle)
        if key in gps_by_key:
            gx, gy = gps_by_key[key]
            errors.append({"time_s": time_s, "vehicle_id": vehicle,
                           "position_error_m": math.hypot(gx - x, gy - y)})
    values = np.asarray([row["position_error_m"] for row in errors], dtype=float)
    metrics: dict[str, Any] = {
        "mean_error_m": float(np.mean(values)) if len(values) else None,
        "mae_m": float(np.mean(np.abs(values))) if len(values) else None,
        "rmse_m": float(np.sqrt(np.mean(np.square(values)))) if len(values) else None,
        "p95_error_m": float(np.percentile(values, 95)) if len(values) else None,
        "matched_observations": len(errors),
        "unmatched_observations": len(set(gps_by_key) - set(truth_by_key)),
        "unmatched_truth_records": len(set(truth_by_key) - set(gps_by_key)),
        "units": "meters",
    }
    return metrics, errors


def save_evaluation(truth_path: Path, gps_path: Path, output_dir: Path) -> dict[str, Any]:
    """Write metrics JSON and the three requested M2 figures."""
    truth = _validated_rows(_read_csv(truth_path), truth_path)
    gps_rows = _read_csv(gps_path)
    metrics, errors = evaluate_observations(truth_path, gps_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = output_dir / f"{gps_path.stem}_metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    truth_by_key = {(t, vehicle): (x, y) for t, vehicle, x, y in truth}
    gps_by_key = {(float(row["time_s"]), row["vehicle_id"]):
                  (float(row["gps_x_m"]), float(row["gps_y_m"])) for row in gps_rows}
    matched = [(time_s, vehicle, truth_by_key[(time_s, vehicle)], gps_by_key[(time_s, vehicle)])
               for time_s, vehicle in truth_by_key.keys() & gps_by_key.keys()]
    matched.sort(key=lambda item: (item[0], item[1]))
    if matched:
        tx = [item[2][0] for item in matched]; ty = [item[2][1] for item in matched]
        gx = [item[3][0] for item in matched]; gy = [item[3][1] for item in matched]
        fig, ax = plt.subplots()
        ax.plot(tx, ty, label="Ground truth", marker=".", markersize=3)
        ax.plot(gx, gy, label="GPS observation", marker=".", markersize=3)
        ax.set_aspect("equal", adjustable="datalim")
        ax.set(xlabel="SUMO X (m)", ylabel="SUMO Y (m)", title="Ground-truth and normal GPS trajectories")
        ax.legend(); fig.tight_layout(); fig.savefig(output_dir / f"{gps_path.stem}_trajectory.png", dpi=160); plt.close(fig)
        fig, ax = plt.subplots()
        ax.plot([item["time_s"] for item in errors], [item["position_error_m"] for item in errors])
        ax.set(xlabel="Time (s)", ylabel="Horizontal position error (m)", title="Normal GPS position error over time")
        fig.tight_layout(); fig.savefig(output_dir / f"{gps_path.stem}_error_time.png", dpi=160); plt.close(fig)
        fig, ax = plt.subplots()
        ax.hist([item["position_error_m"] for item in errors], bins="auto", edgecolor="black")
        ax.set(xlabel="Horizontal position error (m)", ylabel="Observations (count)", title="Normal GPS position error distribution")
        fig.tight_layout(); fig.savefig(output_dir / f"{gps_path.stem}_error_distribution.png", dpi=160); plt.close(fig)
    return metrics


def _load_settings(config_path: Path) -> tuple[Path, dict[str, Any]]:
    config_path = config_path.resolve()
    with config_path.open(encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    if not isinstance(config, dict) or not isinstance(config.get("gps_normal"), dict):
        raise ValueError(f"{config_path} must define gps_normal settings")
    return config_path.parent, config["gps_normal"]


def _select_input(root: Path, settings: dict[str, Any], requested: Path | None) -> Path:
    if requested:
        return requested.resolve()
    if settings.get("input_file"):
        return (root / settings["input_file"]).resolve()
    directory = (root / settings["input_dir"]).resolve()
    files = sorted(directory.glob("truth_*.csv"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(f"No truth_*.csv files found under {directory}")
    return files[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate", help="generate a separate normal-GPS CSV")
    gen.add_argument("--config", type=Path, default=Path("config/experiment_config.yaml"))
    gen.add_argument("--input", type=Path, help="ground-truth CSV; defaults to configured/latest raw truth")
    gen.add_argument("--output", type=Path, help="GPS CSV path; defaults under configured output_dir")
    ev = sub.add_parser("evaluate", help="evaluate GPS against truth and write metrics and plots")
    ev.add_argument("--config", type=Path, default=Path("config/experiment_config.yaml"))
    ev.add_argument("--truth", type=Path, required=True)
    ev.add_argument("--gps", type=Path, required=True)
    ev.add_argument("--output-dir", type=Path, help="defaults to reports/m2")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.command == "generate":
        root, settings = _load_settings(args.config)
        input_path = _select_input(root, settings, args.input)
        output = args.output.resolve() if args.output else (root / settings["output_dir"] / f"gps_normal_{input_path.stem.removeprefix('truth_')}.csv").resolve()
        records = generate_observations(input_path, output, noise_std_m=float(settings["noise_std_m"]), seed=int(settings["seed"]))
        LOGGER.info("Wrote %d operational GPS observations to %s (sigma=%.3f m, seed=%d)", len(records), output, settings["noise_std_m"], settings["seed"])
    else:
        root, settings = _load_settings(args.config)
        default_output = (root / settings.get("evaluation_dir", "../reports/m2")).resolve()
        metrics = save_evaluation(args.truth.resolve(), args.gps.resolve(), args.output_dir.resolve() if args.output_dir else default_output)
        LOGGER.info("Evaluation metrics: %s", json.dumps(metrics, sort_keys=True))


if __name__ == "__main__":
    main()
