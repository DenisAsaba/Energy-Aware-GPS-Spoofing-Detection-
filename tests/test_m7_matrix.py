from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from src.experiments.m7_matrix import (
    _annotate_detection, aggregate_pairs, aggregate_runs, build_matrix, paired_comparisons,
)

ROOT = Path(__file__).resolve().parents[1]


class M7MatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = yaml.safe_load((ROOT / "config/m7_energy_routing.yaml").read_text(encoding="utf-8"))

    def test_matrix_has_separate_splits_and_complete_paired_test_rows(self):
        rows = build_matrix(self.config)
        self.assertEqual(sum(row["split"] == "calibration" for row in rows), 1)
        self.assertEqual(sum(row["split"] == "validation" for row in rows), 1)
        test_attacks = [row for row in rows if row["split"] == "test" and row["attack_type"] != "none"]
        self.assertEqual(len(test_attacks), 48)
        self.assertEqual(len({(row["pair_id"], row["condition"]) for row in rows}), len(rows))
        self.assertEqual({row["condition"] for row in test_attacks},
                         {"unprotected_spoofed", "protected_spoofed"})
        by_pair = {}
        for row in test_attacks:
            by_pair.setdefault(row["pair_id"], []).append(row)
        for pair in by_pair.values():
            self.assertEqual(len(pair), 2)
            self.assertEqual(pair[0]["seed"], pair[1]["seed"])
            self.assertEqual(pair[0]["gps_seed"], pair[1]["gps_seed"])
            self.assertEqual(pair[0]["attack_parameters"], pair[1]["attack_parameters"])

    def test_alert_at_attack_recovery_is_not_active_attack_detection(self):
        row = {"detector_alert_times_s": [3.0, 4.0]}
        _annotate_detection(row, {"onset_s": 1.0, "duration_s": 2.0})
        self.assertFalse(row["attack_detected"])
        self.assertIsNone(row["detection_delay_s"])
        self.assertTrue(row["post_attack_alert"])
        self.assertEqual(row["post_attack_alert_delay_s"], 2.0)

    def test_paired_delta_and_conservative_mitigation_definition(self):
        base = {"split": "test", "attack_type": "offset", "seed": 803,
                "attack_parameters": {"magnitude_m": 180}, "destination_arrived": True,
                "protected_fallback_activated": False, "executed_edges": ["direct"],
                "reroute_count": 0, "route_distance_m": 1400, "travel_time_s": 100,
                "energy_consumed_wh": 200, "soc_change": -0.004}
        rows = [dict(base, condition="unprotected_spoofed", pair_id="p"),
                dict(base, condition="protected_spoofed", pair_id="p",
                     protected_fallback_activated=True, route_distance_m=1300)]
        pair = paired_comparisons(rows)[0]
        self.assertEqual(pair["protected_minus_unprotected_route_distance_m"], -100)
        self.assertTrue(pair["mitigation_success"])

    def test_aggregate_uses_sample_standard_deviation(self):
        rows = [{"split": "test", "attack_type": "none", "condition": "normal_navigation",
                 "route_distance_m": d, "travel_time_s": 10, "energy_consumed_wh": 5,
                 "soc_change": -0.1, "destination_arrived": True, "attack_detected": None,
                 "detector_alert_count": 0, "eligible_fix_count": 10,
                 "protected_fallback_activated": False, "mitigation_success": None,
                 "reroute_count": 0, "battery_telemetry_available": True}
                for d in (10, 14)]
        aggregate = aggregate_runs(rows)[0]
        self.assertEqual(aggregate["route_distance_m_mean"], 12)
        self.assertEqual(aggregate["route_distance_m_std"], 2 ** 0.5 * 2)
        self.assertEqual(aggregate["arrival_rate"], 1)
        self.assertEqual(aggregate["false_positive_rate_per_fix"], 0)

    def test_paired_aggregate_reports_mean_std_and_median_by_attack_parameters(self):
        rows = []
        for seed, delta in ((803, -4.0), (804, -2.0)):
            params = {"magnitude_m": 60.0, "duration_s": 30.0}
            base = {"split": "test", "attack_type": "drift", "seed": seed,
                "attack_parameters": params, "destination_arrived": True,
                "protected_fallback_activated": True, "executed_edges": ["direct"],
                "reroute_count": 0, "route_distance_m": 1000.0,
                "travel_time_s": 100.0, "energy_consumed_wh": 100.0, "soc_change": -0.01}
            rows.extend((dict(base, condition="unprotected_spoofed", pair_id=str(seed)),
                         dict(base, condition="protected_spoofed", pair_id=str(seed),
                              route_distance_m=1000 + delta)))
        summary = aggregate_pairs(paired_comparisons(rows))[0]
        self.assertEqual(summary["n_pairs"], 2)
        self.assertEqual(summary["delta_route_distance_m_mean"], -3)
        self.assertAlmostEqual(summary["delta_route_distance_m_std"], 2 ** 0.5)
        self.assertEqual(summary["delta_route_distance_m_median"], -3)


if __name__ == "__main__":
    unittest.main()
