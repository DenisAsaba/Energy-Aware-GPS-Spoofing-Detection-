"""Key-aligned M9 fusion policies over frozen M5/M8 prediction streams.

This module accepts detector predictions only. It never reads labels, simulator
truth, route progress, or future observations.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable


def _flag(value: Any) -> int:
    if value in (1, True, "1", "True", "true"):
        return 1
    if value in (0, False, "0", "False", "false"):
        return 0
    return 0


def _eligible(row: dict[str, Any] | None) -> bool:
    return row is not None and _flag(row.get("eligible")) == 1 and _flag(row.get("predicted_attack")) in (0, 1)


def _key(row: dict[str, Any]) -> tuple[float, str]:
    try:
        time_s = float(row["time_s"])
        vehicle = str(row["vehicle_id"]).strip()
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("prediction rows require numeric time_s and vehicle_id") from exc
    if not vehicle:
        raise ValueError("prediction rows require a nonempty vehicle_id")
    return time_s, vehicle


def align_and_fuse(
    m5_rows: Iterable[dict[str, Any]],
    m8_rows: Iterable[dict[str, Any]],
    *,
    association_window: int = 2,
    clear_after_joint_clean: int = 3,
) -> list[dict[str, Any]]:
    """Join predictions by ``(time_s, vehicle_id)`` and produce causal policies.

    The M5 fast-suspect output is copied immediately for every eligible M5
    record, even if its M8 counterpart is missing/ineligible. Fusion decisions
    and state counters advance only on observations eligible in *both* streams.
    Ineligible/missing rows never clear state or consume the association window.

    A positive M5 record opens/refreshes a per-vehicle event through the next
    ``association_window`` joint-eligible observations. M8 corroborates when
    its unchanged prediction is active at any joint-eligible observation in
    that inclusive window. Corroborated suspicion latches until
    ``clear_after_joint_clean`` consecutive joint-eligible observations have
    both M5 and M8 inactive. State is isolated by vehicle.
    """
    if isinstance(association_window, bool) or int(association_window) != association_window or association_window < 0:
        raise ValueError("association_window must be a nonnegative integer")
    if isinstance(clear_after_joint_clean, bool) or int(clear_after_joint_clean) != clear_after_joint_clean or clear_after_joint_clean < 1:
        raise ValueError("clear_after_joint_clean must be a positive integer")

    left: dict[tuple[float, str], dict[str, Any]] = {}
    right: dict[tuple[float, str], dict[str, Any]] = {}
    for target, rows, name in ((left, m5_rows, "M5"), (right, m8_rows, "M8")):
        for row in rows:
            key = _key(row)
            if key in target:
                raise ValueError(f"duplicate {name} prediction key: {key}")
            target[key] = row

    states: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "joint_index": 0, "pending_until": -1, "pending_event_id": "",
        "next_event_id": 1, "corroborated": 0, "clean": 0,
    })
    output: list[dict[str, Any]] = []
    for key in sorted(left.keys() | right.keys(), key=lambda k: (k[0], k[1])):
        time_s, vehicle = key
        m5, m8 = left.get(key), right.get(key)
        m5_ok, m8_ok = _eligible(m5), _eligible(m8)
        m5_flag = _flag(m5.get("predicted_attack")) if m5_ok else 0
        m8_flag = _flag(m8.get("predicted_attack")) if m8_ok else 0
        joint = m5_ok and m8_ok
        state = states[vehicle]
        fast = m5_flag if m5_ok else 0
        event_id = ""
        pending = 0
        corroborated_now = 0
        if joint:
            state["joint_index"] += 1
            ordinal = state["joint_index"]
            if m5_flag:
                event_continues = ordinal <= state["pending_until"]
                if not event_continues:
                    state["pending_event_id"] = f"{vehicle}:{state['next_event_id']}"
                    state["next_event_id"] += 1
                state["pending_until"] = ordinal + int(association_window)
            pending = int(ordinal <= state["pending_until"])
            if m8_flag and pending:
                state["corroborated"] = 1
                state["clean"] = 0
                corroborated_now = 1
                event_id = state["pending_event_id"]
            elif state["corroborated"]:
                if not m5_flag and not m8_flag:
                    state["clean"] += 1
                    if state["clean"] >= int(clear_after_joint_clean):
                        state["corroborated"] = 0
                        state["clean"] = 0
                else:
                    state["clean"] = 0
            if pending and not event_id:
                event_id = state["pending_event_id"]
        output.append({
            "time_s": time_s, "vehicle_id": vehicle,
            "m5_present": int(m5 is not None), "m8_present": int(m8 is not None),
            "m5_eligible": int(m5_ok), "m8_eligible": int(m8_ok),
            "joint_eligible": int(joint),
            "m5_prediction": m5_flag if m5_ok else "",
            "m8_prediction": m8_flag if m8_ok else "",
            "or_prediction": int(bool(m5_flag or m8_flag)) if joint else "",
            "and_prediction": int(bool(m5_flag and m8_flag)) if joint else "",
            "m5_fast_suspect": fast,
            "m8_corroboration": m8_flag if m8_ok else "",
            "m5_event_pending": pending if joint else "",
            "corroborated_now": corroborated_now if joint else "",
            "corroborated_suspicion": int(state["corroborated"]),
            "corroborated_event_id": event_id,
            "joint_clean_count": int(state["clean"]),
        })
    return output

