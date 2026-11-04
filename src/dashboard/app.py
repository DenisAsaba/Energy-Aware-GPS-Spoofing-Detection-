"""Streamlit dashboard for read-only inspection of M0/M1 telemetry."""

from __future__ import annotations

from pathlib import Path

import plotly.express as px
import streamlit as st

from telemetry import TelemetryError, discover_csv_files, load_telemetry, summarize_telemetry


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "raw"


def _format(value: float | None, suffix: str = "", digits: int = 2) -> str:
    return f"{value:,.{digits}f}{suffix}" if value is not None else "Unavailable"


def _line_chart(frame, column: str, title: str, y_label: str):
    if column not in frame or frame[column].notna().sum() == 0 or "time_s" not in frame:
        st.info(f"{title} unavailable: the CSV does not contain usable `{column}` and `time_s` values.")
        return
    plot = frame.dropna(subset=["time_s", column])
    fig = px.line(plot, x="time_s", y=column, title=title, labels={"time_s": "Time (s)", column: y_label})
    fig.update_layout(margin={"l": 20, "r": 20, "t": 55, "b": 20})
    st.plotly_chart(fig, width="stretch")


def main() -> None:
    st.set_page_config(page_title="EV Research Dashboard", page_icon="⚡", layout="wide")
    st.title("EV Research Dashboard")
    st.caption("Read-only inspection of M0/M1 SUMO ground-truth telemetry. Road-network X/Y are meters, not longitude/latitude.")

    with st.sidebar:
        st.header("Simulation run")
        if st.button("Refresh file list", width="stretch"):
            st.rerun()
        files = discover_csv_files(DATA_DIR)
        if not files:
            st.info(f"No simulation CSV files found in `{DATA_DIR}`.")
            return
        selected = st.selectbox("Telemetry CSV", files, format_func=lambda p: p.name)

    st.write(f"**Selected file:** `{selected}`")
    try:
        frame = load_telemetry(selected)
    except TelemetryError as exc:
        st.error(f"Unable to display this file: {exc}")
        return

    summary = summarize_telemetry(frame)
    st.write(f"**Vehicle ID:** {summary.vehicle_id or 'Unavailable / multiple IDs'}")
    st.caption("Time is simulation seconds; speed m/s; position m; acceleration m/s²; battery and energy Wh; SOC is a fraction (0–1).")

    kpis = [
        ("Records", str(summary.records)), ("Duration", _format(summary.duration_s, " s")),
        ("Speed min / avg / max", " / ".join(_format(v, " m/s") for v in (summary.speed_min_mps, summary.speed_mean_mps, summary.speed_max_mps))),
        ("Battery charge initial → final", f"{_format(summary.charge_initial_wh, ' Wh')} → {_format(summary.charge_final_wh, ' Wh')}"),
        ("SOC initial → final", f"{_format(summary.soc_initial * 100 if summary.soc_initial is not None else None, '%')} → {_format(summary.soc_final * 100 if summary.soc_final is not None else None, '%')}"),
        ("Cumulative energy consumed", _format(summary.energy_consumed_total_wh, " Wh")),
        ("Cumulative energy regenerated", _format(summary.energy_regenerated_total_wh, " Wh")),
    ]
    for offset in range(0, len(kpis), 4):
        cols = st.columns(min(4, len(kpis) - offset))
        for col, (label, value) in zip(cols, kpis[offset:offset + 4]):
            col.metric(label, value)

    st.subheader("Trajectory")
    trajectory = frame.dropna(subset=[column for column in ("x_m", "y_m") if column in frame.columns]) if {"x_m", "y_m"}.issubset(frame.columns) else frame.iloc[0:0]
    if not trajectory.empty:
        fig = px.line(trajectory, x="x_m", y="y_m", title="EV trajectory (road-network coordinates)",
                      labels={"x_m": "X position (m)", "y_m": "Y position (m)"})
        fig.update_traces(mode="lines+markers")
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("Trajectory unavailable: usable `x_m` and `y_m` columns are required.")

    left, right = st.columns(2)
    with left:
        _line_chart(frame, "speed_mps", "Speed over time", "Speed (m/s)")
        _line_chart(frame, "soc", "Battery state of charge over time", "SOC (fraction)")
        _line_chart(frame, "energy_consumed_wh", "Per-step energy consumed", "Energy (Wh)")
    with right:
        _line_chart(frame, "acceleration_mps2", "Acceleration over time", "Acceleration (m/s²)")
        _line_chart(frame, "battery_charge_wh", "Battery charge over time", "Charge (Wh)")
        _line_chart(frame, "energy_total_regenerated_wh", "Cumulative energy regenerated", "Regenerated energy (Wh)")
        _line_chart(frame, "energy_total_consumed_wh", "Cumulative energy consumed", "Consumed energy (Wh)")

    st.subheader("Raw telemetry")
    st.dataframe(frame, width="stretch", hide_index=True)


if __name__ == "__main__":
    main()
