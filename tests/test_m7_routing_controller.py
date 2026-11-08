from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from src.experiments.m7_energy_routing import (
    compile_network, extract_gps_features_from_rows, validate_network,
)
from src.experiments.m7_routing_controller import RoutingController, energy_metrics


ROOT = Path(__file__).resolve().parents[1]


class FakeTraCI:
    def __init__(self):
        def find_route(start, end):
            edges = (start, end) if start == "alternate_a" else (start, "direct_a", end)
            return SimpleNamespace(edges=edges)
        self.simulation = SimpleNamespace(findRoute=find_route)
        self.vehicle = SimpleNamespace(setRoute=lambda vehicle, route: setattr(self, "last_route", list(route)))


class M7ControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.net = compile_network(ROOT)

    def test_routes_connected_and_share_endpoints(self):
        result = validate_network(self.net)
        self.assertEqual(result["endpoints"]["direct"], result["endpoints"]["alternate"])
        self.assertEqual(result["endpoints"]["direct"], ["origin", "destination"])

    def test_gps_changes_unprotected_route_decision(self):
        ctrl = RoutingController({"direct": (450, 0), "alternate": (450, 180)}, False, "direct_b")
        self.assertEqual(ctrl.choose_gps_route(300, 0), "direct")
        self.assertEqual(ctrl.choose_gps_route(300, 180), "alternate")

    def test_normal_gps_does_not_trigger_fallback(self):
        traci = FakeTraCI()
        ctrl = RoutingController({"direct": (450, 0), "alternate": (450, 180)}, True, "direct_b")
        route, _ = ctrl.decide(time_s=4, gps_x_m=300, gps_y_m=0, detector_alert=False,
                               current_edge="approach", traci=traci, vehicle_id="ev")
        self.assertIsNone(route)
        self.assertFalse(ctrl.fallback_active)
        self.assertFalse(hasattr(traci, "last_route"))

    def test_alert_activates_oracle_fallback_and_records_reason_time(self):
        traci = FakeTraCI()
        ctrl = RoutingController({"direct": (450, 0), "alternate": (450, 180)}, True, "direct_b")
        route, reason = ctrl.decide(time_s=7, gps_x_m=300, gps_y_m=180,
            detector_alert=True, current_edge="approach", traci=traci, vehicle_id="ev")
        self.assertEqual(route, ["approach", "direct_a", "direct_b"])
        self.assertEqual(reason, "m5_alert_oracle_fallback")
        self.assertTrue(ctrl.fallback_active)
        self.assertEqual(ctrl.route_changes[0]["time_s"], 7)
        self.assertTrue(ctrl.route_changes[0]["reason"])

    def test_oracle_fallback_preserves_reachability_on_alternate_branch(self):
        traci = FakeTraCI()
        ctrl = RoutingController({"direct": (450, 0), "alternate": (450, 180)}, True, "direct_b")
        route, reason = ctrl.decide(time_s=9, gps_x_m=700, gps_y_m=180,
            detector_alert=True, current_edge="alternate_a", traci=traci, vehicle_id="ev")
        self.assertEqual(reason, "m5_alert_oracle_fallback")
        self.assertEqual(route, ["alternate_a", "alternate_b"])
        self.assertTrue(ctrl.fallback_active)

    def test_unprotected_never_calls_oracle_fallback(self):
        traci = FakeTraCI()
        ctrl = RoutingController({"direct": (450, 0), "alternate": (450, 180)}, False, "direct_b")
        route, reason = ctrl.decide(time_s=1, gps_x_m=300, gps_y_m=180,
            detector_alert=True, current_edge="approach", traci=traci, vehicle_id="ev")
        self.assertEqual(route, ["approach", "alternate_a", "alternate_b"])
        self.assertEqual(reason, "gps_nearest_route_reference")
        self.assertFalse(ctrl.fallback_active)

    def test_m5_adapter_contains_only_current_and_prior_gps_schema(self):
        features = extract_gps_features_from_rows([
            {"time_s": 1, "vehicle_id": "ev", "gps_x_m": 10, "gps_y_m": 0},
            {"time_s": 2, "vehicle_id": "ev", "gps_x_m": 20, "gps_y_m": 0},
        ])
        self.assertEqual(features[-1]["estimated_speed_mps"], 10.0)
        self.assertFalse({"x_m", "y_m", "attack_active", "attack_type"} & features[-1].keys())

    def test_energy_missing_values_are_not_fabricated(self):
        result = energy_metrics([{"energy_total_consumed_wh": None, "soc": None}])
        self.assertIsNone(result["energy_consumed_wh"])
        self.assertIsNone(result["initial_soc"])
        self.assertFalse(result["battery_telemetry_available"])

    def test_energy_uses_only_sumos_reported_values(self):
        result = energy_metrics([
            {"energy_total_consumed_wh": 2.0, "soc": 0.5},
            {"energy_total_consumed_wh": 5.5, "soc": 0.49},
        ])
        self.assertEqual(result["energy_consumed_wh"], 5.5)
        self.assertEqual(result["initial_soc"], 0.5)
        self.assertEqual(result["final_soc"], 0.49)


if __name__ == "__main__":
    unittest.main()
