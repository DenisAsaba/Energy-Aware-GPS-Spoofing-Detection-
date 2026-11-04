"""Run and inspect the implemented M0/M1 SUMO EV simulation."""

from __future__ import annotations

import argparse
import csv
import logging
import math
import statistics
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

try:
    from .run_sumo import run as run_simulation
except ImportError:  # Direct script execution from src/simulation.
    from run_sumo import run as run_simulation


ROOT = Path(__file__).resolve().parents[2]
REQUIRED_COLUMNS = {"time_s", "vehicle_id", "x_m", "y_m", "speed_mps"}
LOGGER = logging.getLogger("m0_m1_demo")


def read_telemetry(csv_path: Path) -> list[dict[str, str]]:
    """Read and validate fields needed for the summary and trajectory plots."""
    with csv_path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = set(reader.fieldnames or ())
        missing = REQUIRED_COLUMNS - fields
        if missing:
            raise ValueError(f"Telemetry CSV is missing required columns: {sorted(missing)}")
        rows = list(reader)
    if not rows:
        raise ValueError(f"Telemetry CSV has no rows: {csv_path}")
    times = [_number(row, "time_s", required=True) for row in rows]
    if any(current <= previous for previous, current in zip(times, times[1:])):
        raise ValueError("Telemetry time_s values must be strictly increasing")
    return rows


def _number(row: dict[str, str], field: str, *, required: bool = False) -> float | None:
    raw = row.get(field)
    if raw is None or raw.strip() == "":
        if required:
            raise ValueError(f"Required telemetry value {field!r} is missing")
        return None
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError(f"Telemetry value {field!r} must be finite")
    return value


def summarize_telemetry(rows: list[dict[str, str]]) -> dict[str, float | int | None]:
    """Calculate summary values solely from columns present in the CSV."""
    if not rows:
        raise ValueError("Cannot summarize empty telemetry")
    times = [_number(row, "time_s", required=True) for row in rows]
    xs = [_number(row, "x_m", required=True) for row in rows]
    ys = [_number(row, "y_m", required=True) for row in rows]
    speeds = [_number(row, "speed_mps", required=True) for row in rows]
    distance = sum(math.hypot(x2 - x1, y2 - y1) for x1, y1, x2, y2 in zip(xs, ys, xs[1:], ys[1:]))
    return {
        "record_count": len(rows),
        "sample_start_s": times[0],
        "sample_end_s": times[-1],
        "sampled_duration_s": times[-1] - times[0],
        "speed_min_mps": min(speeds),
        "speed_mean_mps": statistics.fmean(speeds),
        "speed_max_mps": max(speeds),
        "sampled_path_distance_m": distance,
        "battery_charge_start_wh": _number(rows[0], "battery_charge_wh"),
        "battery_charge_end_wh": _number(rows[-1], "battery_charge_wh"),
        "battery_capacity_wh": _number(rows[-1], "battery_capacity_wh"),
        "energy_total_consumed_wh": _number(rows[-1], "energy_total_consumed_wh"),
        "energy_total_regenerated_wh": _number(rows[-1], "energy_total_regenerated_wh"),
        "soc_start": _number(rows[0], "soc"),
        "soc_end": _number(rows[-1], "soc"),
    }


def _save_plots(rows: list[dict[str, str]], csv_path: Path, output_dir: Path) -> list[Path]:
    """Save trajectory, speed, and available battery/SOC plots from CSV values."""
    output_dir.mkdir(parents=True, exist_ok=True)
    times = [_number(row, "time_s", required=True) for row in rows]
    xs = [_number(row, "x_m", required=True) for row in rows]
    ys = [_number(row, "y_m", required=True) for row in rows]
    speeds = [_number(row, "speed_mps", required=True) for row in rows]
    charges = [_number(row, "battery_charge_wh") for row in rows]
    soc = [_number(row, "soc") for row in rows]
    stem = csv_path.stem
    paths: list[Path] = []
    battery_plot = output_dir / f"{stem}_battery_charge_soc_time.png"
    planned_paths = [output_dir / f"{stem}_trajectory_xy.png", output_dir / f"{stem}_speed_time.png"]
    if any(value is not None for value in charges) or any(value is not None for value in soc):
        planned_paths.append(battery_plot)
    existing = [path for path in planned_paths if path.exists()]
    if existing:
        raise FileExistsError(f"Refusing to overwrite existing plots: {', '.join(map(str, existing))}")

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(xs, ys, linewidth=1.8)
    ax.scatter([xs[0]], [ys[0]], label="Start", zorder=3)
    ax.scatter([xs[-1]], [ys[-1]], label="Last recorded point", zorder=3)
    ax.set(title="EV ground-truth trajectory", xlabel="X (m)", ylabel="Y (m)")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    trajectory = output_dir / f"{stem}_trajectory_xy.png"
    fig.savefig(trajectory, dpi=150)
    plt.close(fig)
    paths.append(trajectory)

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(times, speeds, linewidth=1.5)
    ax.set(title="EV speed over simulation time", xlabel="Simulation time (s)", ylabel="Speed (m/s)")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    speed_plot = output_dir / f"{stem}_speed_time.png"
    fig.savefig(speed_plot, dpi=150)
    plt.close(fig)
    paths.append(speed_plot)

    has_charge = any(value is not None for value in charges)
    has_soc = any(value is not None for value in soc)
    if has_charge or has_soc:
        fig, charge_ax = plt.subplots(figsize=(8, 5))
        if has_charge:
            charge_ax.plot(times, [value if value is not None else float("nan") for value in charges],
                           color="tab:blue", label="Battery charge")
            charge_ax.set_ylabel("Battery charge (Wh)", color="tab:blue")
        charge_ax.set_xlabel("Simulation time (s)")
        charge_ax.set_title("EV battery charge and state of charge")
        charge_ax.grid(True, alpha=0.3)
        if has_soc:
            soc_ax = charge_ax.twinx()
            soc_ax.plot(times, [value * 100 if value is not None else float("nan") for value in soc],
                        color="tab:orange", label="SOC")
            soc_ax.set_ylabel("State of charge (%)", color="tab:orange")
            handles1, labels1 = charge_ax.get_legend_handles_labels()
            handles2, labels2 = soc_ax.get_legend_handles_labels()
            charge_ax.legend(handles1 + handles2, labels1 + labels2)
        elif has_charge:
            charge_ax.legend()
        fig.tight_layout()
        fig.savefig(battery_plot, dpi=150)
        plt.close(fig)
        paths.append(battery_plot)
    return paths


def _print_summary(csv_path: Path, summary: dict[str, float | int | None], plots: list[Path]) -> None:
    """Print a human-readable, data-backed summary and artifact locations."""
    print(f"Telemetry CSV: {csv_path}")
    print(f"Records: {summary['record_count']}")
    print(f"Sampled duration: {summary['sampled_duration_s']:.1f} s ({summary['sample_start_s']:.1f} to {summary['sample_end_s']:.1f} s)")
    print("Speed (m/s): min={:.3f}, mean={:.3f}, max={:.3f}".format(
        summary["speed_min_mps"], summary["speed_mean_mps"], summary["speed_max_mps"]))
    print(f"Sampled X/Y path distance: {summary['sampled_path_distance_m']:.3f} m")
    charge_values = []
    if summary["battery_charge_start_wh"] is not None:
        charge_values.append(f"start={summary['battery_charge_start_wh']:.2f} Wh")
    if summary["battery_charge_end_wh"] is not None:
        charge_values.append(f"end={summary['battery_charge_end_wh']:.2f} Wh")
    if summary["battery_capacity_wh"] is not None:
        charge_values.append(f"capacity={summary['battery_capacity_wh']:.2f} Wh")
    if charge_values:
        print("Battery charge: " + ", ".join(charge_values))
    if summary["energy_total_consumed_wh"] is not None:
        message = f"Cumulative battery energy consumed: {summary['energy_total_consumed_wh']:.2f} Wh"
        if summary["energy_total_regenerated_wh"] is not None:
            message += f"; regenerated: {summary['energy_total_regenerated_wh']:.2f} Wh"
        print(message)
    if summary["soc_start"] is not None and summary["soc_end"] is not None:
        print("SOC: start={:.2f}%, end={:.2f}%".format(
            summary["soc_start"] * 100, summary["soc_end"] * 100))
    if plots:
        print("Plots:")
        for path in plots:
            print(f"  {path}")
    else:
        print("Plots: no telemetry values available")


def run_demo(
    *,
    config_path: Path = ROOT / "config/experiment_config.yaml",
    gui: bool = False,
    keep_open: bool = False,
    output_path: Path | None = None,
    figures_dir: Path = ROOT / "results/figures/m0_m1",
) -> dict[str, Any]:
    """Run existing M0/M1 simulation, then summarize and plot its new CSV."""
    csv_path = run_simulation(config_path, gui=gui, output_path=output_path, keep_open=keep_open)
    rows = read_telemetry(csv_path)
    summary = summarize_telemetry(rows)
    plots = _save_plots(rows, csv_path, figures_dir)
    _print_summary(csv_path, summary, plots)
    return {"csv_path": csv_path, "summary": summary, "plots": plots}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config/experiment_config.yaml")
    parser.add_argument("--gui", action="store_true", help="watch the EV in SUMO-GUI")
    parser.add_argument("--keep-open", action="store_true", help="keep the completed GUI open until you close it (requires --gui)")
    parser.add_argument("--output", type=Path, help="optional new CSV path; default is timestamped under data/raw")
    parser.add_argument("--figures-dir", type=Path, default=ROOT / "results/figures/m0_m1")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        run_demo(config_path=args.config, gui=args.gui, keep_open=args.keep_open,
                 output_path=args.output, figures_dir=args.figures_dir)
    except Exception as exc:
        LOGGER.error("M0/M1 demonstration failed: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
