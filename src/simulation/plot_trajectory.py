"""Plot SUMO ground-truth x/y coordinates from a telemetry CSV."""

from __future__ import annotations

import argparse
import csv
import math
import os
from pathlib import Path
import tempfile


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REQUIRED_COLUMNS = {"trip_id", "vehicle_id", "x_m", "y_m"}


def load_trajectories(csv_path: Path) -> dict[str, tuple[list[float], list[float]]]:
    """Read and validate x/y positions grouped by trip and vehicle."""
    trajectories: dict[str, tuple[list[float], list[float]]] = {}
    with csv_path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"Telemetry CSV is missing columns: {', '.join(sorted(missing))}")
        for line_number, row in enumerate(reader, start=2):
            try:
                x_m = float(row["x_m"])
                y_m = float(row["y_m"])
            except (TypeError, ValueError) as error:
                raise ValueError(f"Invalid x_m/y_m on CSV line {line_number}") from error
            if not math.isfinite(x_m) or not math.isfinite(y_m):
                raise ValueError(f"Non-finite x_m/y_m on CSV line {line_number}")
            key = f"{row['trip_id']} / {row['vehicle_id']}"
            if key not in trajectories:
                trajectories[key] = ([], [])
            trajectories[key][0].append(x_m)
            trajectories[key][1].append(y_m)
    if not trajectories:
        raise ValueError(f"Telemetry CSV contains no trajectories: {csv_path}")
    return trajectories


def plot_trajectory(csv_path: Path, output_path: Path, show: bool = False) -> int:
    """Save a labeled x/y trajectory plot and optionally open a plot window."""
    trajectories = load_trajectories(csv_path)

    # The managed Windows environment may not allow Matplotlib's default user cache.
    cache_path = Path(tempfile.gettempdir()) / "ev-gps-agent-matplotlib"
    cache_path.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache_path))

    import matplotlib

    if not show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure, axis = plt.subplots(figsize=(8, 6), layout="constrained")
    total_points = 0
    for label, (x_values, y_values) in trajectories.items():
        axis.plot(x_values, y_values, marker=".", markersize=3, label=label)
        axis.scatter(x_values[0], y_values[0], marker="o", s=48, zorder=3, label=f"{label} start")
        axis.scatter(x_values[-1], y_values[-1], marker="X", s=56, zorder=3, label=f"{label} end")
        total_points += len(x_values)

    axis.set_title("SUMO EV ground-truth trajectory")
    axis.set_xlabel("X position (m)")
    axis.set_ylabel("Y position (m)")
    axis.set_aspect("equal", adjustable="datalim")
    axis.grid(True, alpha=0.3)
    axis.legend(fontsize="small")
    figure.savefig(output_path, dpi=160)
    if show:
        plt.show()
    plt.close(figure)
    return total_points


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=PROJECT_ROOT / "data/raw/truth.csv")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "results/figures/ev_trajectory.png")
    parser.add_argument("--show", action="store_true", help="open a plot window after saving the PNG")
    args = parser.parse_args()
    try:
        count = plot_trajectory(args.input.resolve(), args.output.resolve(), args.show)
    except (FileNotFoundError, OSError, ValueError) as error:
        parser.error(str(error))
    print(f"Saved {count} trajectory points to {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
