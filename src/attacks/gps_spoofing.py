"""Apply deterministic GPS offset, jump, or drift scenarios to normal GPS data."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
import statistics
import tempfile
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GPS_FIELDS = ("time_s", "trip_id", "vehicle_id", "gps_seed", "noise_model", "position_std_m", "gps_x_m", "gps_y_m")
LABEL_FIELDS = ("time_s", "trip_id", "vehicle_id", "attack_type", "attack_active", "displacement_x_m", "displacement_y_m", "displacement_m")
TRUTH_FIELDS = ("time_s", "trip_id", "vehicle_id", "x_m", "y_m")
ATTACK_TYPES = ("offset", "jump", "drift")


def _read_csv(path: Path, required: tuple[str, ...], exact: bool = False) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if exact and tuple(reader.fieldnames or ()) != required:
            raise ValueError(f"{path} has an unexpected schema: {reader.fieldnames}")
        missing = set(required) - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"{path} is missing columns: {', '.join(sorted(missing))}")
        rows = list(reader)
    if not rows:
        raise ValueError(f"CSV contains no rows: {path}")
    return rows


def _key(row: dict[str, Any]) -> tuple[str, str, float]:
    return str(row["trip_id"]), str(row["vehicle_id"]), float(row["time_s"])


def _validate_rows(rows: list[dict[str, str]], positions: tuple[str, str], source: str) -> None:
    keys: set[tuple[str, str, float]] = set()
    last_time: dict[tuple[str, str], float] = {}
    for line, row in enumerate(rows, start=2):
        try:
            time_s = float(row["time_s"])
            x, y = float(row[positions[0]]), float(row[positions[1]])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"Invalid time or position in {source} line {line}") from error
        if not all(math.isfinite(v) for v in (time_s, x, y)):
            raise ValueError(f"Non-finite time or position in {source} line {line}")
        if not row.get("trip_id") or not row.get("vehicle_id"):
            raise ValueError(f"Missing trip_id or vehicle_id in {source} line {line}")
        key = _key(row)
        if key in keys:
            raise ValueError(f"Duplicate (trip_id, vehicle_id, time_s) in {source} line {line}")
        keys.add(key)
        vehicle_key = (key[0], key[1])
        if time_s <= last_time.get(vehicle_key, -math.inf):
            raise ValueError(f"Timestamps must increase within each trip and vehicle in {source}")
        last_time[vehicle_key] = time_s


def load_inputs(normal_path: Path, truth_path: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Load M2 observations and truth; require exact unique key alignment."""
    normal = _read_csv(normal_path, GPS_FIELDS, exact=True)
    truth = _read_csv(truth_path, TRUTH_FIELDS)
    _validate_rows(normal, ("gps_x_m", "gps_y_m"), str(normal_path))
    _validate_rows(truth, ("x_m", "y_m"), str(truth_path))
    normal_keys = {_key(row) for row in normal}
    truth_keys = {_key(row) for row in truth}
    if normal_keys != truth_keys:
        raise ValueError(
            f"Normal GPS and truth keys do not match: {len(normal_keys-truth_keys)} GPS-only, "
            f"{len(truth_keys-normal_keys)} truth-only records"
        )
    return normal, truth


def validate_attack(attack_type: str, parameters: dict[str, Any]) -> dict[str, float]:
    """Validate and normalize the interval and geometry for one attack."""
    if attack_type not in ATTACK_TYPES:
        raise ValueError(f"Unsupported coordinate attack: {attack_type}")
    try:
        onset = float(parameters["onset_time_s"])
        duration = float(parameters["duration_s"])
        direction = float(parameters["direction_deg"])
        strength = float(parameters["drift_rate_mps"] if attack_type == "drift" else parameters["magnitude_m"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"Missing or invalid parameters for {attack_type}") from error
    if not all(math.isfinite(v) for v in (onset, duration, direction, strength)):
        raise ValueError("Attack parameters must be finite numbers")
    if duration <= 0:
        raise ValueError("duration_s must be greater than zero")
    if not math.isfinite(onset + duration):
        raise ValueError("Attack interval end must be finite")
    if not 0 <= direction < 360:
        raise ValueError("direction_deg must be in [0, 360)")
    if strength <= 0:
        name = "drift_rate_mps" if attack_type == "drift" else "magnitude_m"
        raise ValueError(f"{name} must be greater than zero")
    return {"onset_time_s": onset, "duration_s": duration, "direction_deg": direction, "strength": strength}


def apply_attack(
    normal_rows: list[dict[str, str]], attack_type: str, parameters: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Transform only GPS coordinates; put attack labels and offsets in a separate stream."""
    normalized = validate_attack(attack_type, parameters)
    onset, end = normalized["onset_time_s"], normalized["onset_time_s"] + normalized["duration_s"]
    direction = math.radians(normalized["direction_deg"])
    magnitude = normalized["strength"]
    dx_unit, dy_unit = math.cos(direction), math.sin(direction)
    dx_unit = 0.0 if abs(dx_unit) < 1e-12 else dx_unit
    dy_unit = 0.0 if abs(dy_unit) < 1e-12 else dy_unit
    attacked: list[dict[str, Any]] = []
    labels: list[dict[str, Any]] = []
    for row in normal_rows:
        time_s = float(row["time_s"])
        active = onset <= time_s < end
        displacement = 0.0
        if active:
            displacement = magnitude * (time_s - onset) if attack_type == "drift" else magnitude
        dx, dy = displacement * dx_unit, displacement * dy_unit
        if not all(math.isfinite(v) for v in (displacement, dx, dy)):
            raise ValueError("Attack displacement overflowed; reduce magnitude, rate, or interval")
        observation = {field: row[field] for field in GPS_FIELDS}
        if dx != 0.0 or dy != 0.0:
            x_m, y_m = float(row["gps_x_m"]) + dx, float(row["gps_y_m"]) + dy
            if not math.isfinite(x_m) or not math.isfinite(y_m):
                raise ValueError("Attacked GPS coordinate overflowed; reduce attack parameters")
            observation["gps_x_m"], observation["gps_y_m"] = x_m, y_m
        attacked.append(observation)
        labels.append({
            "time_s": row["time_s"], "trip_id": row["trip_id"], "vehicle_id": row["vehicle_id"],
            "attack_type": attack_type, "attack_active": str(active).lower(),
            "displacement_x_m": dx, "displacement_y_m": dy, "displacement_m": displacement,
        })
    return attacked, labels


def _error_metrics(truth: list[dict[str, str]], observations: list[dict[str, Any]], x_col: str, y_col: str) -> dict[str, float | int]:
    truth_by_key = {_key(row): row for row in truth}
    obs_by_key = {_key(row): row for row in observations}
    if truth_by_key.keys() != obs_by_key.keys():
        raise ValueError("Cannot evaluate records with different truth/observation keys")
    errors = [math.hypot(float(obs_by_key[k][x_col]) - float(t["x_m"]), float(obs_by_key[k][y_col]) - float(t["y_m"])) for k, t in truth_by_key.items()]
    ordered = sorted(errors)
    return {
        "count": len(errors), "mean_m": statistics.fmean(errors), "median_m": statistics.median(errors),
        "standard_deviation_m_population": statistics.pstdev(errors),
        "p95_m_nearest_rank": ordered[math.ceil(.95 * len(ordered)) - 1],
        "minimum_m": min(errors), "maximum_m": max(errors),
    }


def _write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _setup_matplotlib() -> None:
    cache_path = Path(tempfile.gettempdir()) / "ev-gps-agent-matplotlib"
    cache_path.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache_path))
    import matplotlib
    matplotlib.use("Agg")


def _plot_outputs(
    truth: list[dict[str, str]], normal: list[dict[str, str]], attacked: list[dict[str, Any]],
    attack_type: str, parameters: dict[str, Any], figure_dir: Path,
) -> tuple[Path, Path]:
    import matplotlib.pyplot as plt
    _setup_matplotlib()
    figure_dir.mkdir(parents=True, exist_ok=True)
    truth_by_key = {_key(row): row for row in truth}
    normal_by_key = {_key(row): row for row in normal}
    attacked_by_key = {_key(row): row for row in attacked}
    keys = [_key(row) for row in normal]
    truth_ordered = [truth_by_key[k] for k in keys]
    normal_ordered = [normal_by_key[k] for k in keys]
    attacked_ordered = [attacked_by_key[k] for k in keys]
    config_note = json.dumps(parameters, sort_keys=True)
    gps_seeds = sorted({int(row["gps_seed"]) for row in normal})
    seed_note = f"GPS seed={gps_seeds}"
    trajectory_path = figure_dir / f"gps_{attack_type}_trajectory.png"
    error_path = figure_dir / f"gps_{attack_type}_error_distribution.png"
    fig, ax = plt.subplots(figsize=(9, 6), layout="constrained")
    ax.plot([float(r["x_m"]) for r in truth_ordered], [float(r["y_m"]) for r in truth_ordered], label="Ground truth", linewidth=2)
    ax.plot([float(r["gps_x_m"]) for r in normal_ordered], [float(r["gps_y_m"]) for r in normal_ordered], ".--", ms=3, label="Normal GPS")
    ax.plot([float(r["gps_x_m"]) for r in attacked_ordered], [float(r["gps_y_m"]) for r in attacked_ordered], ".-", ms=3, label=f"GPS with {attack_type}")
    ax.set(title=f"{attack_type.title()} GPS scenario ({seed_note})\n{config_note}", xlabel="SUMO network X (m)", ylabel="SUMO network Y (m)")
    ax.set_aspect("equal", adjustable="datalim")
    ax.grid(True, alpha=.3)
    ax.legend()
    fig.savefig(trajectory_path, dpi=160)
    plt.close(fig)

    normal_errors = [math.hypot(float(r["gps_x_m"]) - float(t["x_m"]), float(r["gps_y_m"]) - float(t["y_m"])) for t, r in zip(truth_ordered, normal_ordered, strict=True)]
    attacked_errors = [math.hypot(float(r["gps_x_m"]) - float(t["x_m"]), float(r["gps_y_m"]) - float(t["y_m"])) for t, r in zip(truth_ordered, attacked_ordered, strict=True)]
    fig, ax = plt.subplots(figsize=(8, 5), layout="constrained")
    bins = min(24, max(6, round(math.sqrt(len(normal_errors)))))
    combined = normal_errors + attacked_errors
    low, high = min(combined), max(combined)
    if low == high:
        pad = max(abs(low) * .05, .5)
        low, high = low - pad, high + pad
    ax.hist(normal_errors, bins=bins, range=(low, high), alpha=.65, label="Normal GPS", edgecolor="white")
    ax.hist(attacked_errors, bins=bins, range=(low, high), alpha=.55, label=f"{attack_type.title()} GPS", edgecolor="white")
    ax.set(title=f"{attack_type.title()} position error (offline; {seed_note})\n{config_note}", xlabel="Position error from ground truth (m)", ylabel="Observation count")
    ax.grid(True, axis="y", alpha=.3)
    ax.legend()
    fig.savefig(error_path, dpi=160)
    plt.close(fig)
    return trajectory_path, error_path


def generate_attack(
    normal_path: Path, truth_path: Path, attack_type: str, parameters: dict[str, Any],
    output_dir: Path, figure_dir: Path, summary_dir: Path,
) -> dict[str, Path]:
    """Write one observation stream, separate labels, plots, and offline summary."""
    normal, truth = load_inputs(normal_path, truth_path)
    attacked, labels = apply_attack(normal, attack_type, parameters)
    observation_path = output_dir / f"gps_{attack_type}.csv"
    labels_path = output_dir / f"labels_{attack_type}.csv"
    summary_path = summary_dir / f"gps_{attack_type}_summary.json"
    for path in (observation_path, labels_path):
        if path.resolve() in (normal_path.resolve(), truth_path.resolve()):
            raise ValueError(f"Refusing to overwrite baseline input: {path}")
    _write_csv(observation_path, GPS_FIELDS, attacked)
    _write_csv(labels_path, LABEL_FIELDS, labels)
    _setup_matplotlib()
    trajectory_path, error_path = _plot_outputs(truth, normal, attacked, attack_type, parameters, figure_dir)
    active_count = sum(row["attack_active"] == "true" for row in labels)
    summary = {
        "scenario_type": attack_type,
        "simulation_only": True,
        "normal_gps_input": str(normal_path), "truth_reference_for_offline_evaluation": str(truth_path),
        "gps_seed": sorted({int(row["gps_seed"]) for row in normal}),
        "attack_random_seed": None,
        "attack_is_deterministic_given_input_and_parameters": True,
        "parameters": parameters,
        "interval_semantics": "active when onset_time_s <= time_s < onset_time_s + duration_s; displacement returns to zero at interval end",
        "direction_convention": "degrees counterclockwise from SUMO +x; 0=+x/east, 90=+y/north",
        "record_count": len(attacked), "active_record_count": active_count,
        "normal_position_error_offline": _error_metrics(truth, normal, "gps_x_m", "gps_y_m"),
        "attacked_position_error_offline": _error_metrics(truth, attacked, "gps_x_m", "gps_y_m"),
        "observation_schema_excludes_truth_and_labels": True,
    }
    summary_dir.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return {"observations": observation_path, "labels": labels_path, "summary": summary_path, "trajectory_plot": trajectory_path, "error_plot": error_path}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config/experiment_config.yaml")
    parser.add_argument("--attack", choices=(*ATTACK_TYPES, "all"), default="all")
    args = parser.parse_args()
    try:
        with args.config.open(encoding="utf-8") as stream:
            config = yaml.safe_load(stream)
        settings = config["attacks"]
        resolve = lambda value: (Path(value) if Path(value).is_absolute() else PROJECT_ROOT / value).resolve()
        normal_path = resolve(config["gps"]["output_file"])
        truth_path = resolve(config["gps"]["input_file"])
        output_dir, figure_dir, summary_dir = map(resolve, (settings["output_dir"], settings["figure_dir"], settings["summary_dir"]))
        selected = ATTACK_TYPES if args.attack == "all" else (args.attack,)
        for attack_type in selected:
            outputs = generate_attack(normal_path, truth_path, attack_type, settings["scenarios"][attack_type], output_dir, figure_dir, summary_dir)
            print(f"Generated {attack_type}: " + ", ".join(f"{kind}={path}" for kind, path in outputs.items()))
    except (FileNotFoundError, OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as error:
        parser.error(str(error))
    print("Route deviation is a separate genuine SUMO scenario: run src/attacks/route_deviation.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
