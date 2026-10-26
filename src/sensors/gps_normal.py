"""Generate seeded normal GPS observations from SUMO truth for offline experiments."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
import random
import statistics
import tempfile
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TRUTH_COLUMNS = ("time_s", "trip_id", "vehicle_id", "seed", "x_m", "y_m")
GPS_FIELDS = ("time_s", "trip_id", "vehicle_id", "gps_seed", "noise_model", "position_std_m", "gps_x_m", "gps_y_m")


def _read_truth(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        missing = set(TRUTH_COLUMNS) - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"Truth CSV is missing columns: {', '.join(sorted(missing))}")
        for line, row in enumerate(reader, start=2):
            try:
                x, y, time_s = float(row["x_m"]), float(row["y_m"]), float(row["time_s"])
            except (TypeError, ValueError) as error:
                raise ValueError(f"Invalid truth position/time on CSV line {line}") from error
            if not all(math.isfinite(value) for value in (x, y, time_s)):
                raise ValueError(f"Non-finite truth position/time on CSV line {line}")
            if not row["trip_id"] or not row["vehicle_id"]:
                raise ValueError(f"Missing trip or vehicle ID on CSV line {line}")
            rows.append({**row, "x_m": x, "y_m": y, "time_s": time_s})
    if not rows:
        raise ValueError(f"Truth CSV contains no observations: {path}")
    return rows


def error_summary(errors_m: list[float], seed: int, sigma_m: float) -> dict[str, Any]:
    """Summarize radial position error for offline evaluation only."""
    ordered = sorted(errors_m)
    p95 = ordered[math.ceil(0.95 * len(ordered)) - 1]
    return {
        "evaluation_only": True,
        "ground_truth_used_only_for_offline_evaluation": True,
        "count": len(errors_m), "gps_seed": seed,
        "noise_model": "independent_gaussian_xy", "per_axis_standard_deviation_m": sigma_m,
        "radial_error_m": {
            "mean": statistics.fmean(errors_m), "median": statistics.median(errors_m),
            "standard_deviation": statistics.pstdev(errors_m), "p95_nearest_rank": p95,
            "maximum": max(errors_m),
        },
    }


def generate(truth_path: Path, output_path: Path, seed: int, sigma_m: float) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Create observations with independent N(0, sigma²) x/y errors; truth is read-only."""
    if not math.isfinite(sigma_m) or sigma_m < 0:
        raise ValueError("position_std_m must be finite and nonnegative")
    if truth_path.resolve() == output_path.resolve():
        raise ValueError("GPS output must be a separate file; refusing to overwrite ground truth")
    truth = _read_truth(truth_path)
    rng = random.Random(seed)
    observations: list[dict[str, Any]] = []
    errors: list[float] = []
    for row in truth:
        dx, dy = rng.gauss(0.0, sigma_m), rng.gauss(0.0, sigma_m)
        observations.append({
            "time_s": row["time_s"], "trip_id": row["trip_id"], "vehicle_id": row["vehicle_id"],
            "gps_seed": seed, "noise_model": "independent_gaussian_xy", "position_std_m": sigma_m,
            "gps_x_m": row["x_m"] + dx, "gps_y_m": row["y_m"] + dy,
        })
        errors.append(math.hypot(dx, dy))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=GPS_FIELDS)
        writer.writeheader()
        writer.writerows(observations)
    return observations, error_summary(errors, seed, sigma_m)


def _setup_matplotlib() -> None:
    cache_path = Path(tempfile.gettempdir()) / "ev-gps-agent-matplotlib"
    cache_path.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache_path))
    import matplotlib
    matplotlib.use("Agg")


def plot_comparison(truth_path: Path, observations: list[dict[str, Any]], output_path: Path) -> None:
    """Plot truth and measured GPS tracks in the common SUMO meter frame."""
    truth = _read_truth(truth_path)
    _setup_matplotlib()
    import matplotlib.pyplot as plt
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 6), layout="constrained")
    ax.plot([r["x_m"] for r in truth], [r["y_m"] for r in truth], "-o", ms=2.5, label="Ground truth")
    ax.plot([r["gps_x_m"] for r in observations], [r["gps_y_m"] for r in observations], "--.", ms=3, alpha=.8, label="Normal GPS observations")
    ax.set(title="EV trajectory: ground truth and simulated normal GPS", xlabel="SUMO network X (m)", ylabel="SUMO network Y (m)")
    ax.set_aspect("equal", adjustable="datalim")
    ax.grid(True, alpha=.3)
    ax.legend()
    fig.savefig(output_path, dpi=160)
    plt.close(fig)


def plot_error_distribution(truth_path: Path, observations: list[dict[str, Any]], output_path: Path, summary: dict[str, Any]) -> None:
    """Plot radial errors by comparing measurements to truth offline."""
    truth = _read_truth(truth_path)
    errors = [math.hypot(g["gps_x_m"] - t["x_m"], g["gps_y_m"] - t["y_m"]) for t, g in zip(truth, observations, strict=True)]
    _setup_matplotlib()
    import matplotlib.pyplot as plt
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 5), layout="constrained")
    ax.hist(errors, bins=min(20, max(5, round(math.sqrt(len(errors))))), edgecolor="white")
    stats = summary["radial_error_m"]
    ax.set(title="Simulated GPS radial position error (offline evaluation)", xlabel="Position error from ground truth (m)", ylabel="Observation count")
    ax.text(.98, .97, f"n = {summary['count']}\nmean = {stats['mean']:.2f} m\nmedian = {stats['median']:.2f} m\n95th percentile = {stats['p95_nearest_rank']:.2f} m", transform=ax.transAxes, ha="right", va="top", bbox={"facecolor": "white", "alpha": .85})
    ax.grid(True, axis="y", alpha=.3)
    fig.savefig(output_path, dpi=160)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config/experiment_config.yaml")
    parser.add_argument("--input", type=Path, help="ground-truth CSV (read-only)")
    parser.add_argument("--output", type=Path, help="GPS observation CSV")
    parser.add_argument("--seed", type=int, help="independent GPS random seed")
    parser.add_argument("--sigma-m", type=float, help="per-axis Gaussian standard deviation in meters")
    args = parser.parse_args()
    try:
        with args.config.open(encoding="utf-8") as stream:
            config = yaml.safe_load(stream)
        gps = config["gps"]
        resolve = lambda value: (Path(value) if Path(value).is_absolute() else PROJECT_ROOT / value).resolve()
        truth_path, output_path = resolve(args.input or gps["input_file"]), resolve(args.output or gps["output_file"])
        plot_path, error_plot, summary_path = resolve(gps["trajectory_plot"]), resolve(gps["error_plot"]), resolve(gps["error_summary"])
        seed = int(gps["seed"] if args.seed is None else args.seed)
        sigma = float(gps["position_std_m"] if args.sigma_m is None else args.sigma_m)
        observations, summary = generate(truth_path, output_path, seed, sigma)
        plot_comparison(truth_path, observations, plot_path)
        plot_error_distribution(truth_path, observations, error_plot, summary)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    except (FileNotFoundError, OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as error:
        parser.error(str(error))
    print(f"Saved {len(observations)} GPS observations to {output_path}")
    print(f"GPS seed={seed} per-axis sigma={sigma:g} m; radial error summary: {json.dumps(summary['radial_error_m'], sort_keys=True)}")
    print(f"Saved comparison plot to {plot_path}; offline error distribution to {error_plot}; summary to {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
