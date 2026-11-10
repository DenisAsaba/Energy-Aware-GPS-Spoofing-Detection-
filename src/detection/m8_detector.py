"""Causal, GPS-only M8 detector with interpretable thresholds and alarm persistence.

Only timestamp, vehicle ID, and observed GPS X/Y are accepted. Coordinates are
SUMO-local meters. No simulator state, labels, attack metadata, or future fixes
are consumed by this module.
"""

from __future__ import annotations

from collections import deque
import csv
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from src.detection.gps_only import (
    FEATURE_THRESHOLDS,
    apply_temporal_thresholds,
    calibrate_temporal_thresholds,
    extract_gps_features,
)

M8_THRESHOLDS = {
    **FEATURE_THRESHOLDS,
    "abs_acceleration_mps2": "max_abs_acceleration_mps2",
    "speed_consistency_mps": "max_speed_consistency_mps",
}
FORBIDDEN_INPUT_FIELDS = frozenset({
    "x_m", "y_m", "speed_mps", "acceleration_mps2", "heading_deg", "road_id",
    "route_id", "attack_type", "attack_active", "attack_id", "attack_intensity",
    "gps_position_error_m", "position_error_m", "m4_residual_m",
})


def extract_m8_features(gps_path: Path, *, rolling_speed_window: int) -> list[dict[str, Any]]:
    """Return causal per-fix features; rolling fields are null during warm-up.

    Signed acceleration is ``(v_t-v_(t-1))/(t_t-t_(t-1))`` in m/s^2; the
    detector thresholds its absolute value. For window W, rolling speed is the
    straight-line displacement from the fix W intervals before the current fix
    divided by elapsed time. It is compared with the median of the W prior
    per-fix GPS speeds. This feature first becomes available after W prior
    eligible speed estimates. Invalid/duplicate/out-of-order fixes follow M5:
    they are excluded and never update state.
    """
    if isinstance(rolling_speed_window, bool) or rolling_speed_window < 2:
        raise ValueError("rolling_speed_window must be an integer of at least 2")
    if int(rolling_speed_window) != rolling_speed_window:
        raise ValueError("rolling_speed_window must be an integer")
    window = int(rolling_speed_window)
    try:
        with Path(gps_path).open(encoding="utf-8-sig", newline="") as stream:
            header = next(csv.reader(stream), [])
    except OSError as exc:
        raise ValueError(f"Could not read GPS observations {gps_path}: {exc}") from exc
    allowed = {"time_s", "vehicle_id", "gps_x_m", "gps_y_m"}
    if len(header) != len(set(header)) or set(header) != allowed:
        raise ValueError(f"M8 input must contain only {sorted(allowed)}; got {header}")
    base_rows = extract_gps_features(Path(gps_path))
    state: dict[str, dict[str, Any]] = {}
    output: list[dict[str, Any]] = []
    for base in base_rows:
        row = dict(base)
        row.update({"signed_acceleration_mps2": None, "abs_acceleration_mps2": None,
                    "rolling_displacement_speed_mps": None,
                    "recent_median_speed_mps": None, "speed_consistency_mps": None,
                    "raw_anomaly": 0, "raw_rules_triggered": ""})
        if not base["eligible"]:
            output.append(row)
            continue
        vehicle = str(base["vehicle_id"])
        track = state.setdefault(vehicle, {"positions": deque(maxlen=window + 1),
                                            "speeds": deque(maxlen=window)})
        t = float(base["time_s"])
        x, y = float(base["gps_x_m"]), float(base["gps_y_m"])
        speed = float(base["estimated_speed_mps"])
        dt = float(base["elapsed_s"])
        prior_speeds: deque[float] = track["speeds"]
        prior_positions: deque[tuple[float, float, float]] = track["positions"]
        previous_speed = prior_speeds[-1] if prior_speeds else None
        if previous_speed is not None:
            signed_acceleration = (speed - previous_speed) / dt
            row["signed_acceleration_mps2"] = signed_acceleration
            row["abs_acceleration_mps2"] = abs(signed_acceleration)
        if len(prior_speeds) >= window and len(prior_positions) >= window:
            old_t, old_x, old_y = list(prior_positions)[-window]
            elapsed = t - old_t
            if elapsed > 0:
                rolling_speed = math.hypot(x - old_x, y - old_y) / elapsed
                recent_median = float(np.median(list(prior_speeds)[-window:]))
                row["rolling_displacement_speed_mps"] = rolling_speed
                row["recent_median_speed_mps"] = recent_median
                row["speed_consistency_mps"] = abs(rolling_speed - recent_median)
        fired: list[str] = []
        for feature in FEATURE_THRESHOLDS:
            value = row.get(feature)
            # Raw features are not predictions until thresholds are applied.
            if value is not None:
                row[f"_{feature}"] = float(value)
        track["positions"].append((t, x, y))
        prior_speeds.append(speed)
        output.append(row)
    return output


def calibrate_m8_thresholds(
    calibration_trips: Iterable[list[dict[str, Any]]], *, quantile: float,
    calibration_fraction_per_trip: float,
) -> tuple[dict[str, float], dict[str, Any]]:
    """Pool normal-only chronological prefixes, using M5's split/calibration API.

    Each trip is passed separately through M5's existing calibration function
    to identify its own prefix, preventing one long trip from consuming the
    pooled prefix. Thresholds are NumPy quantiles over pooled prefix features.
    """
    trips = list(calibration_trips)
    if not trips:
        raise ValueError("at least one normal calibration trip is required")
    pooled: dict[str, list[float]] = {feature: [] for feature in M8_THRESHOLDS}
    trip_details = []
    for trip_index, features in enumerate(trips):
        m5_thresholds, cal_indices, _, details = calibrate_temporal_thresholds(
            features, quantile=quantile, calibration_fraction=calibration_fraction_per_trip)
        counts: dict[str, int] = {}
        for feature in M8_THRESHOLDS:
            values = [float(row[feature]) for row in features
                      if row.get("eligible") and row.get("_source_index") in cal_indices
                      and row.get(feature) is not None]
            pooled[feature].extend(values)
            counts[feature] = len(values)
        if any(counts[name] == 0 for name in M8_THRESHOLDS):
            raise ValueError(f"calibration trip {trip_index} has insufficient eligible rolling features")
        trip_details.append({"trip_index": trip_index, "m5_calibration": details,
                             "prefix_feature_counts": counts,
                             "m5_thresholds_from_existing_api": m5_thresholds})
    thresholds = {M8_THRESHOLDS[feature]: float(np.quantile(values, quantile))
                  for feature, values in pooled.items()}
    return thresholds, {
        "method": "pooled NumPy linear quantiles from each normal trip's chronological prefix",
        "normal_quantile": quantile,
        "calibration_fraction_per_trip": calibration_fraction_per_trip,
        "threshold_units": {"max_speed_mps": "m/s", "max_speed_change_mps": "m/s",
                            "max_heading_change_deg": "degrees",
                            "max_abs_acceleration_mps2": "m/s^2",
                            "max_speed_consistency_mps": "m/s"},
        "pooled_feature_counts": {feature: len(values) for feature, values in pooled.items()},
        "trips": trip_details,
    }


def _validate_persistence(policy: dict[str, int]) -> tuple[int, int, int]:
    required = {"trigger_count", "trigger_window", "clear_after_clean_fixes"}
    if set(policy) != required:
        raise ValueError(f"persistence policy must contain exactly {sorted(required)}")
    k, n, clear = (policy[name] for name in ("trigger_count", "trigger_window", "clear_after_clean_fixes"))
    if any(isinstance(value, bool) or int(value) != value for value in (k, n, clear)):
        raise ValueError("persistence values must be integers")
    if not (1 <= k <= n and n >= 1 and clear >= 1):
        raise ValueError("persistence must satisfy 1 <= trigger_count <= trigger_window and clear_after_clean_fixes >= 1")
    return int(k), int(n), int(clear)


def apply_m8_thresholds(
    features: list[dict[str, Any]], thresholds: dict[str, float],
    persistence: dict[str, int],
) -> list[dict[str, Any]]:
    """Apply fixed OR thresholds followed by causal k-of-n alarm persistence.

    A triggered alarm remains latched until ``clear_after_clean_fixes``
    consecutive eligible fixes have no raw threshold exceedance. Excluded fixes
    neither enter the k-of-n window nor clear the alarm.
    """
    if set(thresholds) != set(M8_THRESHOLDS.values()) or any(
        not math.isfinite(float(value)) or float(value) < 0 for value in thresholds.values()
    ):
        raise ValueError(f"thresholds must have finite nonnegative values for {sorted(M8_THRESHOLDS.values())}")
    k, n, clear_after = _validate_persistence(persistence)
    raw_rows: list[dict[str, Any]] = []
    m5_thresholds = {name: float(thresholds[name]) for name in FEATURE_THRESHOLDS.values()}
    # Keep M5's exact prediction semantics available as a matched baseline.
    m5_rows = apply_temporal_thresholds(features, m5_thresholds)
    for row in features:
        out = dict(row)
        if not row.get("eligible"):
            out.update({"m8_raw_anomaly": "", "m8_raw_rules": "", "predicted_attack": ""})
            raw_rows.append(out)
            continue
        rules = []
        for feature, threshold_name in M8_THRESHOLDS.items():
            value = row.get(feature)
            if value is not None and float(value) > float(thresholds[threshold_name]):
                rules.append(feature)
        out["m8_raw_anomaly"] = int(bool(rules))
        out["m8_raw_rules"] = ";".join(rules)
        raw_rows.append(out)
    states: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(raw_rows):
        row["m5_predicted_attack"] = m5_rows[index].get("predicted_attack", "")
        if not row.get("eligible"):
            continue
        vehicle = str(row["vehicle_id"])
        state = states.setdefault(vehicle, {"hits": deque(maxlen=n), "active": False, "clean": 0})
        raw = int(row["m8_raw_anomaly"])
        state["hits"].append(raw)
        if sum(state["hits"]) >= k:
            state["active"] = True
            state["clean"] = 0
        elif state["active"]:
            state["clean"] += 1
            if state["clean"] >= clear_after:
                state["active"] = False
                state["clean"] = 0
        row["persistence_hits_in_window"] = sum(state["hits"])
        row["predicted_attack"] = int(state["active"])
    return raw_rows


def prediction_input_contract() -> dict[str, Any]:
    """Return a serializable statement of allowed and forbidden data inputs."""
    return {
        "allowed_columns": ["time_s", "vehicle_id", "gps_x_m", "gps_y_m"],
        "allowed_temporal_context": "prior valid GPS fixes for the same vehicle only",
        "forbidden_fields": sorted(FORBIDDEN_INPUT_FIELDS),
        "labels_opened_only_after_predictions": True,
    }
