"""Run a genuine alternative SUMO route and export its GPS observation scenario."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src/sensors"))
sys.path.insert(0, str(PROJECT_ROOT / "src/attacks"))
import gps_normal  # noqa: E402
from gps_spoofing import GPS_FIELDS, _error_metrics, _key, _read_csv, _write_csv  # noqa: E402


ROUTE_LABEL_FIELDS = ("time_s", "trip_id", "vehicle_id", "attack_type", "attack_active", "route_id")


def _resolve(value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def make_route_labels(alt_truth: list[dict[str, str]]) -> list[dict[str, str]]:
    """Label the genuine alternate-route scenario separately from its GPS stream."""
    return [{
        "time_s": row["time_s"], "trip_id": row["trip_id"], "vehicle_id": row["vehicle_id"],
        "attack_type": "route_deviation", "attack_active": "true", "route_id": row["route_id"],
    } for row in alt_truth]


def _plot_route_comparison(
    baseline_truth: list[dict[str, str]], baseline_gps: list[dict[str, str]],
    alt_truth: list[dict[str, str]], alt_gps: list[dict[str, Any]], trajectory_path: Path, error_path: Path,
) -> None:
    cache_path = Path(tempfile.gettempdir()) / "ev-gps-agent-matplotlib"
    cache_path.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache_path))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    trajectory_path.parent.mkdir(parents=True, exist_ok=True)
    sumo_seeds = sorted({int(row["seed"]) for row in alt_truth if row.get("seed")})
    gps_seeds = sorted({int(row["gps_seed"]) for row in alt_gps})
    sigma_values = sorted({float(row["position_std_m"]) for row in alt_gps})
    provenance = f"SUMO seed={sumo_seeds}; GPS seed={gps_seeds}; per-axis sigma={sigma_values} m"
    original_route_ids = sorted({row["route_id"] for row in baseline_truth})
    alternative_route_ids = sorted({row["route_id"] for row in alt_truth})
    fig, ax = plt.subplots(figsize=(9, 6), layout="constrained")
    ax.plot([float(r["x_m"]) for r in baseline_truth], [float(r["y_m"]) for r in baseline_truth], label=f"Original route truth ({original_route_ids})", linewidth=2)
    ax.plot([float(r["gps_x_m"]) for r in baseline_gps], [float(r["gps_y_m"]) for r in baseline_gps], ".--", ms=3, label="Original route normal GPS")
    ax.plot([float(r["x_m"]) for r in alt_truth], [float(r["y_m"]) for r in alt_truth], label=f"Alternative route truth ({alternative_route_ids})", linewidth=2)
    ax.plot([float(r["gps_x_m"]) for r in alt_gps], [float(r["gps_y_m"]) for r in alt_gps], ".--", ms=3, label="Alternative route GPS")
    ax.set(title=f"Genuine SUMO route-deviation scenario\n{provenance}", xlabel="SUMO network X (m)", ylabel="SUMO network Y (m)")
    ax.set_aspect("equal", adjustable="datalim")
    ax.grid(True, alpha=.3)
    ax.legend(fontsize="small")
    fig.savefig(trajectory_path, dpi=160)
    plt.close(fig)

    base_errors = [math.hypot(float(g["gps_x_m"]) - float(t["x_m"]), float(g["gps_y_m"]) - float(t["y_m"])) for t, g in zip(baseline_truth, baseline_gps, strict=True)]
    alt_errors = [math.hypot(float(g["gps_x_m"]) - float(t["x_m"]), float(g["gps_y_m"]) - float(t["y_m"])) for t, g in zip(alt_truth, alt_gps, strict=True)]
    error_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 5), layout="constrained")
    bins = min(24, max(6, round(math.sqrt(max(len(base_errors), len(alt_errors))))))
    combined = base_errors + alt_errors
    low, high = min(combined), max(combined)
    if low == high:
        pad = max(abs(low) * .05, .5)
        low, high = low - pad, high + pad
    ax.hist(base_errors, bins=bins, range=(low, high), alpha=.65, label="Original route error", edgecolor="white")
    ax.hist(alt_errors, bins=bins, range=(low, high), alpha=.55, label="Alternative route error", edgecolor="white")
    ax.set(title=f"Route-deviation GPS position error (offline evaluation)\n{provenance}", xlabel="Position error from scenario truth (m)", ylabel="Observation count")
    ax.grid(True, axis="y", alpha=.3)
    ax.legend()
    fig.savefig(error_path, dpi=160)
    plt.close(fig)


def run(config_path: Path) -> dict[str, Path]:
    """Run the alternate-route SUMO config, then create separate truth/GPS/labels."""
    with config_path.open(encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    gps_settings = config["gps"]
    route_settings = config["attacks"]["route_deviation"]
    simulation_config = _resolve(route_settings["simulation_config"])
    truth_output = _resolve(route_settings["truth_output"])
    gps_output = _resolve(route_settings["gps_output"])
    labels_output = _resolve(route_settings["labels_output"])
    summary_output = _resolve(route_settings["summary_output"])
    trajectory_plot = _resolve(route_settings["trajectory_plot"])
    error_plot = _resolve(route_settings["error_plot"])
    baseline_truth_path = _resolve(gps_settings["input_file"])
    baseline_gps_path = _resolve(gps_settings["output_file"])
    if not simulation_config.is_file():
        raise FileNotFoundError(f"Alternative-route config not found: {simulation_config}")
    with simulation_config.open(encoding="utf-8") as stream:
        route_simulation = yaml.safe_load(stream)["simulation"]
    if gps_output in (baseline_truth_path, baseline_gps_path) or truth_output in (baseline_truth_path, baseline_gps_path):
        raise ValueError("Route-deviation outputs must not overwrite M1/M2 baseline files")

    runner = PROJECT_ROOT / "src/simulation/run_sumo.py"
    subprocess.run(
        [sys.executable, str(runner), "--config", str(simulation_config), "--output", str(truth_output)],
        cwd=PROJECT_ROOT, check=True,
    )
    baseline_truth = _read_csv(baseline_truth_path, ("time_s", "trip_id", "vehicle_id", "x_m", "y_m", "route_id"))
    baseline_gps = _read_csv(baseline_gps_path, GPS_FIELDS, exact=True)
    alt_truth = _read_csv(truth_output, ("time_s", "trip_id", "vehicle_id", "x_m", "y_m", "route_id", "road_id"))
    expected_route_id = str(route_settings["expected_route_id"])
    actual_route_ids = sorted({row["route_id"] for row in alt_truth})
    if actual_route_ids != [expected_route_id]:
        raise ValueError(f"Expected alternative route {expected_route_id}, observed route IDs {actual_route_ids}")
    expected_edges = set(route_settings["expected_route_edges"])
    observed_edges = {row["road_id"] for row in alt_truth}
    if not expected_edges.issubset(observed_edges):
        raise ValueError(f"Alternative route did not traverse all configured edges: expected {sorted(expected_edges)}, observed {sorted(observed_edges)}")

    gps_seed = int(gps_settings["seed"])
    sigma_m = float(gps_settings["position_std_m"])
    alt_gps, gps_noise_summary = gps_normal.generate(truth_output, gps_output, gps_seed, sigma_m)
    labels = make_route_labels(alt_truth)
    _write_csv(labels_output, ROUTE_LABEL_FIELDS, labels)
    normal_error = _error_metrics(baseline_truth, baseline_gps, "gps_x_m", "gps_y_m")
    alt_error = _error_metrics(alt_truth, alt_gps, "gps_x_m", "gps_y_m")
    _plot_route_comparison(baseline_truth, baseline_gps, alt_truth, alt_gps, trajectory_plot, error_plot)
    summary = {
        "scenario_type": "route_deviation",
        "simulation_only": True,
        "actual_vehicle_route_changed": True,
        "fabricated_coordinate_offset_applied": False,
        "sumo_seed": int(route_simulation["seed"]), "gps_seed": gps_seed,
        "normal_route_id": sorted({row["route_id"] for row in baseline_truth}),
        "alternative_route_id": actual_route_ids,
        "alternative_route_edges_configured": list(route_settings["expected_route_edges"]),
        "alternative_route_edges_observed": sorted(observed_edges),
        "baseline_record_count": len(baseline_truth), "alternative_record_count": len(alt_truth),
        "normal_position_error_offline": normal_error,
        "alternative_position_error_offline": alt_error,
        "gps_noise_model": "independent_gaussian_xy", "per_axis_standard_deviation_m": sigma_m,
        "gps_noise_sample_summary_from_generator": gps_noise_summary["radial_error_m"],
        "coordinate_frame": "SUMO local Cartesian network coordinates in meters",
        "observation_schema_excludes_truth_and_labels": True,
    }
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return {"alternative_truth": truth_output, "observations": gps_output, "labels": labels_output, "summary": summary_output, "trajectory_plot": trajectory_plot, "error_plot": error_plot}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config/experiment_config.yaml")
    args = parser.parse_args()
    try:
        outputs = run(args.config.resolve())
    except (FileNotFoundError, OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError, yaml.YAMLError) as error:
        parser.error(str(error))
    for kind, path in outputs.items():
        print(f"Generated {kind}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
