import csv
import tempfile
import unittest
from pathlib import Path

from src.detection.gps_only import (
    PREDICTION_FIELDS,
    _prediction_csv,
    apply_temporal_thresholds,
    calibrate_temporal_thresholds,
    extract_gps_features,
    score_scenario,
)


class GPSOnlyFeatureTests(unittest.TestCase):
    def write_gps(self, rows):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "gps.csv"
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["time_s", "vehicle_id", "gps_x_m", "gps_y_m"])
            writer.writerows(rows)
        return path

    def test_speed_heading_and_first_fix_are_causal(self):
        rows = [[0, "a", 0, 0], [1, "a", 0, 2], [2, "a", 2, 2], [3, "a", 2, 22]]
        features = extract_gps_features(self.write_gps(rows))
        self.assertEqual(features[0]["exclusion_reason"], "first_observation")
        self.assertEqual(features[1]["estimated_speed_mps"], 2)
        self.assertEqual(features[1]["estimated_heading_deg"], 0)
        self.assertEqual(features[2]["heading_change_deg"], 90)
        self.assertEqual(features[3]["estimated_speed_mps"], 20)
        self.assertEqual(features[3]["speed_change_mps"], 18)

    def test_bad_duplicate_and_out_of_order_rows_are_excluded_without_state_update(self):
        rows = [[0, "a", 0, 0], [1, "a", 1, 0], [1, "a", 2, 0],
                [0.5, "a", 3, 0], [2, "a", "NaN", 0], [2, "a", 2, 0],
                ["", "a", 0, 0], [3, "b", 0, 0], [4, "b", 0, 3]]
        features = extract_gps_features(self.write_gps(rows))
        self.assertEqual(features[2]["exclusion_reason"], "duplicate_timestamp_vehicle")
        self.assertEqual(features[3]["exclusion_reason"], "out_of_order_timestamp")
        self.assertEqual(features[4]["exclusion_reason"], "missing_or_invalid_coordinate")
        self.assertTrue(features[5]["eligible"])
        self.assertEqual(features[6]["exclusion_reason"], "missing_or_invalid_timestamp")
        self.assertEqual(features[7]["exclusion_reason"], "first_observation")
        self.assertEqual(features[8]["estimated_speed_mps"], 3)

    def test_threshold_rules_are_strict_and_reproducible(self):
        features = extract_gps_features(self.write_gps(
            [[i, "a", i * i, 0] for i in range(10)]))
        a = calibrate_temporal_thresholds(features, quantile=.8, calibration_fraction=.5)
        b = calibrate_temporal_thresholds(features, quantile=.8, calibration_fraction=.5)
        self.assertEqual(a, b)
        thresholds, calibration, evaluation, _ = a
        scored = apply_temporal_thresholds(features, thresholds,
                                           calibration_indices=calibration,
                                           evaluation_indices=evaluation)
        self.assertTrue(all(row["evaluation_split"] == "calibration" for row in scored
                            if row["_source_index"] in calibration))
        eligible = next(row for row in scored if row["eligible"])
        exact = {"max_speed_mps": eligible["estimated_speed_mps"],
                 "max_speed_change_mps": eligible["speed_change_mps"] or 0,
                 "max_heading_change_deg": eligible["heading_change_deg"] or 0}
        exact_result = apply_temporal_thresholds([eligible], exact)[0]
        self.assertEqual(exact_result["predicted_attack"], 0)

    def test_metrics_report_counts_and_delay(self):
        predictions = [
            {"time_s": 1, "vehicle_id": "a", "eligible": 1,
             "evaluation_split": "evaluation", "predicted_attack": 0},
            {"time_s": 2, "vehicle_id": "a", "eligible": 1,
             "evaluation_split": "evaluation", "predicted_attack": 1},
            {"time_s": 3, "vehicle_id": "a", "eligible": 0,
             "evaluation_split": "evaluation", "predicted_attack": ""},
        ]
        labels = {(1.0, "a"): 0, (2.0, "a"): 1, (3.0, "a"): 1}
        result = score_scenario(predictions, labels, scenario="jump",
                                input_keys=set(labels))
        self.assertEqual((result["true_positive"], result["true_negative"]), (1, 1))
        self.assertEqual(result["detection_delay_s"], 0)
        self.assertEqual(result["excluded_observations"], 1)
        self.assertEqual(result["excluded_labeled_observations"], 1)

    def test_prediction_schema_has_no_truth_or_label_fields_and_refuses_overwrite(self):
        forbidden = {"x_m", "y_m", "gps_position_error_m", "attack_active", "attack_type"}
        self.assertTrue(forbidden.isdisjoint(PREDICTION_FIELDS))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "predictions.csv"
            _prediction_csv(path, [])
            original = path.read_bytes()
            with self.assertRaises(FileExistsError):
                _prediction_csv(path, [])
            self.assertEqual(path.read_bytes(), original)

    def test_stationary_and_multiple_vehicle_tracks(self):
        rows = [[0, "a", 2, 2], [0, "b", 10, 10], [1, "a", 2, 2],
                [1, "b", 10, 11], [2, "a", 2, 2], [2, "b", 10, 12]]
        features = extract_gps_features(self.write_gps(rows))
        a = [row for row in features if row["vehicle_id"] == "a"]
        b = [row for row in features if row["vehicle_id"] == "b"]
        self.assertIsNone(a[1]["estimated_heading_deg"])
        self.assertEqual(a[1]["estimated_speed_mps"], 0)
        self.assertEqual(b[1]["estimated_speed_mps"], 1)
        self.assertEqual(b[1]["estimated_heading_deg"], 0)


if __name__ == "__main__":
    unittest.main()
