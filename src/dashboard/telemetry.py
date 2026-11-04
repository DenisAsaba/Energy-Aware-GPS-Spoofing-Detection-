"""Read-only loading and summary calculations for M0/M1 telemetry CSV files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from pandas.errors import EmptyDataError, ParserError


REQUIRED_COLUMNS = {"time_s", "vehicle_id"}
NUMERIC_COLUMNS = {
    "time_s", "x_m", "y_m", "speed_mps", "acceleration_mps2", "heading_deg",
    "electricity_wh", "energy_consumed_wh", "energy_total_consumed_wh",
    "energy_total_regenerated_wh", "battery_charge_wh", "battery_capacity_wh", "soc",
}


class TelemetryError(ValueError):
    """An empty, malformed, or unsupported telemetry file."""


@dataclass(frozen=True)
class TelemetrySummary:
    records: int
    duration_s: float | None
    vehicle_id: str | None
    speed_min_mps: float | None
    speed_mean_mps: float | None
    speed_max_mps: float | None
    charge_initial_wh: float | None
    charge_final_wh: float | None
    soc_initial: float | None
    soc_final: float | None
    energy_consumed_total_wh: float | None
    energy_regenerated_total_wh: float | None


def discover_csv_files(data_dir: Path) -> list[Path]:
    """Return CSV paths in a stable order without opening or changing them."""
    return sorted((p for p in data_dir.glob("*.csv") if p.is_file()), reverse=True)


def load_telemetry(path: Path) -> pd.DataFrame:
    """Load a telemetry CSV, preserving optional missing values as NaN."""
    try:
        frame = pd.read_csv(path, dtype={"vehicle_id": "string", "road_id": "string", "route_id": "string"})
    except (EmptyDataError, ParserError, UnicodeDecodeError, OSError) as exc:
        raise TelemetryError(f"Could not read telemetry CSV: {exc}") from exc
    if frame.empty:
        raise TelemetryError("CSV contains a header but no telemetry records.")
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise TelemetryError(f"CSV is missing required identification columns: {', '.join(sorted(missing))}.")
    for column in NUMERIC_COLUMNS.intersection(frame.columns):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def _first_last_numeric(frame: pd.DataFrame, column: str) -> tuple[float | None, float | None]:
    if column not in frame:
        return None, None
    ordered = frame.sort_values("time_s", kind="stable") if "time_s" in frame else frame
    values = ordered[column].dropna()
    if values.empty:
        return None, None
    return float(values.iloc[0]), float(values.iloc[-1])


def _last_numeric(frame: pd.DataFrame, column: str) -> float | None:
    if column not in frame:
        return None
    ordered = frame.sort_values("time_s", kind="stable") if "time_s" in frame else frame
    values = ordered[column].dropna()
    return float(values.iloc[-1]) if not values.empty else None


def summarize_telemetry(frame: pd.DataFrame) -> TelemetrySummary:
    """Calculate descriptive metrics only from present, numeric CSV values."""
    times = frame["time_s"].dropna() if "time_s" in frame else pd.Series(dtype=float)
    duration = float(times.max() - times.min()) if not times.empty else None
    speeds = frame["speed_mps"].dropna() if "speed_mps" in frame else pd.Series(dtype=float)
    vehicle_values = frame["vehicle_id"].dropna().astype(str).unique()
    charge = _first_last_numeric(frame, "battery_charge_wh")
    soc = _first_last_numeric(frame, "soc")
    return TelemetrySummary(
        records=len(frame),
        duration_s=duration,
        vehicle_id=str(vehicle_values[0]) if len(vehicle_values) == 1 else None,
        speed_min_mps=float(speeds.min()) if not speeds.empty else None,
        speed_mean_mps=float(speeds.mean()) if not speeds.empty else None,
        speed_max_mps=float(speeds.max()) if not speeds.empty else None,
        charge_initial_wh=charge[0], charge_final_wh=charge[1],
        soc_initial=soc[0], soc_final=soc[1],
        # These are separate cumulative SUMO device outputs; never combine them.
        energy_consumed_total_wh=_last_numeric(frame, "energy_total_consumed_wh"),
        energy_regenerated_total_wh=_last_numeric(frame, "energy_total_regenerated_wh"),
    )
