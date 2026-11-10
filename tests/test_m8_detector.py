"""M8 detector formula, causality, persistence, and boundary checks."""

import csv
import tempfile
import unittest
from pathlib import Path

from src.detection.gps_only import (
    apply_temporal_thresholds,
    calibrate_temporal_thresholds,
    extract_gps_features,
)
from src.detection.m8_detector import (
    M8_THRESHOLDS,
    apply_m8_thresholds,
    calibrate_m8_thresholds,
    extract_m8_features,
    prediction_input_contract,
)


class M8DetectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write_gps(self, name, rows, extra_header=None):
        path = self.root / name
        header = ["time_s", "vehicle_id", "gps_x_m", "gps_y_m"] + (extra_header or [])
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(header)
            writer.writerows(rows)
        return path

    def test_acceleration_formula_and_irregular_time_intervals(self):
        path = self.write_gps("irregular.csv", [
            [0, "a", 0, 0], [2, "a", 0, 4], [5, "a", 0, 19],
        ])
        rows = extract_m8_features(path, rolling_speed_window=2)
        # Speeds are 2 m/s and 5 m/s; acceleration divides the 3 m/s change by 3 s.
        self.assertEqual(rows[1]["estimated_speed_mps"], 2.0)
        self.assertEqual(rows[2]["estimated_speed_mps"], 5.0)
        self.assertAlmostEqual(rows[2]["signed_acceleration_mps2"], 1.0)
        self.assertAlmostEqual(rows[2]["abs_acceleration_mps2"], 1.0)
        self.assertEqual(rows[2]["estimated_heading_deg"], 0.0)

    def test_rolling_speed_consistency_warmup_and_units(self):
        path = self.write_gps("rolling.csv", [
            [0, "a", 0, 0], [1, "a", 0, 1], [2, "a", 0, 3],
            [3, "a", 0, 6], [4, "a", 0, 10],
        ])
        rows = extract_m8_features(path, rolling_speed_window=2)
        self.assertIsNone(rows[1]["speed_consistency_mps"])
        self.assertIsNone(rows[2]["speed_consistency_mps"])
        # At t=3, rolling speed spans p1..p3 = 2.5 m/s; prior per-fix median is 1.5.
        self.assertAlmostEqual(rows[3]["rolling_displacement_speed_mps"], 2.5)
        self.assertAlmostEqual(rows[3]["recent_median_speed_mps"], 1.5)
        self.assertAlmostEqual(rows[3]["speed_consistency_mps"], 1.0)

    def test_invalid_duplicate_and_missing_fixes_do_not_update_state(self):
        path = self.write_gps("invalid.csv", [
            [0, "a", 0, 0], [1, "a", 0, 1], [1, "a", 0, 99],
            [2, "a", "NaN", 0], [3, "a", 0, 3], [2.5, "a", 0, 2.5],
            [4, "a", 0, 4],
        ])
        rows = extract_m8_features(path, rolling_speed_window=2)
        self.assertEqual(rows[2]["exclusion_reason"], "duplicate_timestamp_vehicle")
        self.assertEqual(rows[3]["exclusion_reason"], "missing_or_invalid_coordinate")
        self.assertAlmostEqual(rows[4]["estimated_speed_mps"], 1.0)
        self.assertEqual(rows[5]["exclusion_reason"], "out_of_order_timestamp")
        self.assertAlmostEqual(rows[6]["estimated_speed_mps"], 1.0)

    def test_multiple_vehicles_have_independent_state(self):
        path = self.write_gps("vehicles.csv", [
            [0, "a", 0, 0], [0, "b", 10, 10], [1, "a", 0, 2],
            [1, "b", 10, 13], [2, "a", 0, 5], [2, "b", 10, 17],
        ])
        rows = extract_m8_features(path, rolling_speed_window=2)
        self.assertEqual(rows[2]["estimated_speed_mps"], 2.0)
        self.assertEqual(rows[3]["estimated_speed_mps"], 3.0)
        self.assertEqual(rows[4]["signed_acceleration_mps2"], 1.0)
        self.assertEqual(rows[5]["signed_acceleration_mps2"], 1.0)

    def test_stationary_vehicle_has_zero_speed_and_undefined_heading(self):
        path = self.write_gps("stationary.csv", [[0, "a", 2, 2], [1, "a", 2, 2], [2, "a", 2, 2]])
        rows = extract_m8_features(path, rolling_speed_window=2)
        self.assertEqual(rows[1]["estimated_speed_mps"], 0.0)
        self.assertIsNone(rows[1]["estimated_heading_deg"])
        self.assertIsNone(rows[1]["heading_change_deg"])
        self.assertEqual(rows[2]["abs_acceleration_mps2"], 0.0)

    def test_persistence_latches_then_clears_using_only_current_and_past_fixes(self):
        rows = [
            {"time_s": i, "vehicle_id": "a", "eligible": 1,
             "estimated_speed_mps": 10.0 if i == 2 else 0.0,
             "speed_change_mps": 0.0, "heading_change_deg": 0.0,
             "abs_acceleration_mps2": 0.0, "speed_consistency_mps": 0.0,
             "raw_anomaly": 0, "_source_index": i}
            for i in range(6)
        ]
        thresholds = {name: 1.0 for name in M8_THRESHOLDS.values()}
        policy = {"trigger_count": 1, "trigger_window": 1, "clear_after_clean_fixes": 2}
        predicted = apply_m8_thresholds(rows, thresholds, policy)
        self.assertEqual([row["predicted_attack"] for row in predicted], [0, 0, 1, 1, 0, 0])
        self.assertEqual(predicted[2]["m8_raw_rules"], "estimated_speed_mps")

    def test_m5_baseline_predictions_match_existing_api(self):
        path = self.write_gps("baseline.csv", [[i, "a", i * (i + 1), 0] for i in range(12)])
        features = extract_m8_features(path, rolling_speed_window=2)
        thresholds = {
            "max_speed_mps": 1000.0, "max_speed_change_mps": 1000.0,
            "max_heading_change_deg": 180.0, "max_abs_acceleration_mps2": 1000.0,
            "max_speed_consistency_mps": 1000.0,
        }
        expected = apply_temporal_thresholds(features, {key: thresholds[key] for key in (
            "max_speed_mps", "max_speed_change_mps", "max_heading_change_deg")})
        actual = apply_m8_thresholds(features, thresholds,
                                    {"trigger_count": 1, "trigger_window": 1,
                                     "clear_after_clean_fixes": 1})
        self.assertEqual([row["m5_predicted_attack"] for row in actual],
                         [row["predicted_attack"] for row in expected])

    def test_future_rows_cannot_change_prefix_features_or_predictions(self):
        prefix = [[0, "a", 0, 0], [1, "a", 0, 2], [2, "a", 0, 5], [3, "a", 0, 9]]
        first = extract_m8_features(self.write_gps("prefix.csv", prefix + [[4, "a", 0, 14]]),
                                    rolling_speed_window=2)
        second = extract_m8_features(self.write_gps("changed_future.csv", prefix + [[4, "a", 10000, -5000]]),
                                     rolling_speed_window=2)
        for left, right in zip(first[:4], second[:4]):
            for field in ("estimated_speed_mps", "signed_acceleration_mps2", "speed_consistency_mps"):
                self.assertEqual(left[field], right[field])

    def test_input_schema_rejects_ground_truth_labels_and_other_privileged_columns(self):
        path = self.write_gps("leaky.csv", [[0, "a", 0, 0, 0, 0, 0]],
                              extra_header=["x_m", "y_m", "attack_active"])
        with self.assertRaisesRegex(ValueError, "only"):
            extract_m8_features(path, rolling_speed_window=2)
        contract = prediction_input_contract()
        self.assertEqual(set(contract["allowed_columns"]), {"time_s", "vehicle_id", "gps_x_m", "gps_y_m"})
        self.assertTrue(contract["labels_opened_only_after_predictions"])

    def test_per_trip_calibration_prefixes_are_pooled_and_deterministic(self):
        trips = []
        for index in range(2):
            path = self.write_gps(f"cal{index}.csv", [[i, "a", 0, i * i + index] for i in range(30)])
            trips.append(extract_m8_features(path, rolling_speed_window=2))
        first = calibrate_m8_thresholds(trips, quantile=.9, calibration_fraction_per_trip=.5)
        second = calibrate_m8_thresholds(trips, quantile=.9, calibration_fraction_per_trip=.5)
        self.assertEqual(first, second)
        thresholds, details = first
        self.assertEqual(set(thresholds), set(M8_THRESHOLDS.values()))
        self.assertEqual(len(details["trips"]), 2)
        self.assertTrue(all(details["pooled_feature_counts"].values()))

    def test_invalid_persistence_is_rejected(self):
        with self.assertRaises(ValueError):
            apply_m8_thresholds([], {}, {"trigger_count": 2, "trigger_window": 1,
                                         "clear_after_clean_fixes": 1})


if __name__ == "__main__":
    unittest.main()
