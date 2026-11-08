"""M7-only SUMO route decisions; M5 receives GPS fixes only."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any


@dataclass
class RoutingController:
    """Choose a route from GPS, or use an explicitly oracle-assisted fallback."""
    references: dict[str, tuple[float, float]]
    protected: bool
    destination_edge: str
    active_route: str = "direct"
    fallback_active: bool = False
    route_changes: list[dict[str, Any]] = field(default_factory=list)
    fallback_events: list[dict[str, Any]] = field(default_factory=list)

    def choose_gps_route(self, gps_x_m: float, gps_y_m: float) -> str:
        """Return the nearest route reference using only the observable fix."""
        return min(self.references, key=lambda route: math.dist(
            (gps_x_m, gps_y_m), self.references[route]))

    def decide(self, *, time_s: float, gps_x_m: float, gps_y_m: float,
               detector_alert: bool, current_edge: str, traci: Any,
               vehicle_id: str) -> tuple[list[str] | None, str | None]:
        """Return a connected TraCI route and reason when navigation must change.

        Oracle route lookup is gated behind a protected detector alert. Neither
        oracle position nor edge is passed to the M5 detector.
        """
        if self.protected and detector_alert and not self.fallback_active:
            self.fallback_active = True
            # SUMO internal junction edges are not valid routing origins. At
            # that instant, keep SUMO's already-connected route and record the
            # oracle fallback as a maintained-route decision.
            if current_edge.startswith(":"):
                self.fallback_events.append({"time_s": float(time_s),
                    "reason": "m5_alert_oracle_fallback_maintained_route",
                    "current_edge": current_edge, "action": "maintain_during_internal_transition"})
                return None, "m5_alert_oracle_fallback_maintained_route"
            target = ("alternate_b" if current_edge in {"alternate_a", "alternate_b"}
                      else "direct_b")
            if current_edge == target:
                self.fallback_events.append({"time_s": float(time_s),
                    "reason": "m5_alert_oracle_fallback_maintained_route",
                    "current_edge": current_edge, "action": "already_on_destination_edge"})
                return None, "m5_alert_oracle_fallback_maintained_route"
            found = traci.simulation.findRoute(current_edge, target)
            edges = list(found.edges)
            if not edges or edges[0] != current_edge or edges[-1] != target:
                self.fallback_active = False
                raise RuntimeError("Oracle fallback could not find a connected destination route")
            route_name = "oracle_fallback"
            reason = "m5_alert_oracle_fallback"
            self.fallback_events.append({"time_s": float(time_s), "reason": reason,
                "current_edge": current_edge, "target_edge": target,
                "action": "reroute_from_current_route_progress"})
        elif not self.fallback_active and current_edge == "approach":
            route_name = self.choose_gps_route(gps_x_m, gps_y_m)
            if route_name == self.active_route:
                return None, None
            edges = ["approach", "direct_a", "direct_b"] if route_name == "direct" else [
                "approach", "alternate_a", "alternate_b"]
            reason = "gps_nearest_route_reference"
        else:
            return None, None
        if edges[0] != current_edge:
            raise RuntimeError(f"Proposed route does not start at current edge {current_edge!r}")
        traci.vehicle.setRoute(vehicle_id, edges)
        self.active_route = route_name
        self.route_changes.append({"time_s": float(time_s), "route": route_name,
                                   "reason": reason, "from_edge": current_edge,
                                   "route_edges": edges})
        return edges, reason


def energy_metrics(rows: list[dict[str, Any]]) -> dict[str, float | None]:
    """Summarize only telemetry values supplied by SUMO; absent stays null."""
    values = [row for row in rows if row.get("energy_total_consumed_wh") is not None]
    regenerated = [row for row in rows if row.get("energy_total_regenerated_wh") is not None]
    soc = [row for row in rows if row.get("soc") is not None]
    charge = [row for row in rows if row.get("battery_charge_wh") is not None]
    return {
        # A fresh SUMO trip starts with zero cumulative consumption; use the
        # final reported cumulative total so the first active step is included.
        "energy_consumed_wh": float(values[-1]["energy_total_consumed_wh"]) if values else None,
        "initial_soc": float(soc[0]["soc"]) if soc else None,
        "final_soc": float(soc[-1]["soc"]) if soc else None,
        "soc_change": float(soc[-1]["soc"]) - float(soc[0]["soc"]) if soc else None,
        "initial_battery_charge_wh": float(charge[0]["battery_charge_wh"]) if charge else None,
        "final_battery_charge_wh": float(charge[-1]["battery_charge_wh"]) if charge else None,
        "energy_regenerated_wh": (float(regenerated[-1]["energy_total_regenerated_wh"])
                                   if regenerated else None),
        "battery_telemetry_available": bool(values and soc),
    }
