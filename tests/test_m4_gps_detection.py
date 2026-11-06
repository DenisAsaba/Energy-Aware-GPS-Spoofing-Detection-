"""M4 oracle-assisted detector and evaluation unit/regression tests."""

import csv
import hashlib
import tempfile
import unittest
from pathlib import Path

from src.detection.gps_spoofing import (
    PREDICTION_FIELDS, _read_labels, _score_scenario, calibrate_threshold,
    classification_metrics, predict_position_residuals,
)

ROOT = Path(__file__).resolve().parents[1]


class M4GpsDetectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp.name)
        self.truth = self.tmp / "truth.csv"
        self.gps = self.tmp / "gps.csv"
        self.truth.write_text(
            "time_s,vehicle_id,x_m,y_m\n"
            "1,ev_a,0,0\n2,ev_a,0,0\n3,ev_a,0,0\n4,ev_a,0,0\n"
            "5,ev_b,0,0\n6,ev_b,0,0\n", encoding="utf-8")
        self.gps.write_text(
            "time_s,vehicle_id,gps_x_m,gps_y_m\n"
            "1,ev_a,1,0\n2,ev_a,2,0\n3,ev_a,3,0\n4,ev_a,4,0\n"
            "5,ev_b,5,0\n7,other,0,0\n", encoding="utf-8")
        self.truth_before = self.truth.read_bytes()
        self.gps_before = self.gps.read_bytes()

    def tearDown(self):
        self.temp.cleanup()

    def test_below_above_and_exact_threshold_predictions(self):
        predictions, _ = predict_position_residuals(self.truth, self.gps, threshold_m=2.0)
        by_key = {(r["time_s"], r["vehicle_id"]): r["predicted_attack"] for r in predictions}
        self.assertEqual(by_key[(1.0, "ev_a")], 0)
        self.assertEqual(by_key[(2.0, "ev_a")], 0)  # equality is normal
        self.assertEqual(by_key[(3.0, "ev_a")], 1)
        self.assertEqual(by_key[(4.0, "ev_a")], 1)
        self.assertEqual(by_key[(5.0, "ev_b")], 1)

    def test_matching_uses_time_and_vehicle_and_reports_unmatched(self):
        predictions, stats = predict_position_residuals(self.truth, self.gps, 2.0)
        self.assertEqual(len(predictions), 5)
        self.assertEqual(stats["matched_observations"], 5)
        self.assertEqual(stats["unmatched_observations"], 1)
        self.assertEqual(stats["unmatched_truth_records"], 1)
        self.assertEqual(predictions[-1]["vehicle_id"], "ev_b")

    def test_prediction_inputs_and_csv_schema_do_not_include_labels(self):
        predictions, _ = predict_position_residuals(self.truth, self.gps, 2.0)
        out = self.tmp / "predictions.csv"
        with out.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=PREDICTION_FIELDS)
            writer.writeheader(); writer.writerows(predictions)
        with out.open(encoding="utf-8", newline="") as stream:
            fields = csv.DictReader(stream).fieldnames
        self.assertEqual(tuple(fields), PREDICTION_FIELDS)
        self.assertNotIn("attack_active", fields)
        self.assertNotIn("attack_type", fields)

    def test_confusion_and_all_metric_formulas(self):
        predictions = [{"time_s": float(i), "vehicle_id": "v", "predicted_attack": p}
                       for i, p in enumerate((1, 0, 1, 0), start=1)]
        labels = {(float(i), "v"): y for i, y in enumerate((1, 1, 0, 0), start=1)}
        result = classification_metrics(predictions, labels)
        self.assertEqual((result["true_positive"], result["false_positive"],
                          result["true_negative"], result["false_negative"]), (1, 1, 1, 1))
        for metric in ("precision", "recall", "f1", "false_positive_rate", "accuracy"):
            self.assertEqual(result[metric], 0.5)

    def test_unmatched_prediction_and_label_records_are_reported(self):
        predictions = [{"time_s": 1.0, "vehicle_id": "a", "predicted_attack": 0},
                       {"time_s": 3.0, "vehicle_id": "extra_prediction", "predicted_attack": 1}]
        labels = {(1.0, "a"): 0, (2.0, "extra_label"): 1}
        result = classification_metrics(predictions, labels)
        self.assertEqual(result["matched_observations"], 1)
        self.assertEqual(result["unmatched_prediction_records"], 1)
        self.assertEqual(result["unmatched_label_records"], 1)

    def test_zero_denominators_and_detection_delay(self):
        predictions = [{"time_s": 1.0, "vehicle_id": "v", "predicted_attack": 0},
                       {"time_s": 2.0, "vehicle_id": "v", "predicted_attack": 1}]
        labels = {(1.0, "v"): 0, (2.0, "v"): 1}
        result = classification_metrics(predictions, {(1.0, "v"): 0})
        self.assertEqual(result["precision"], 0.0)
        self.assertEqual(result["recall"], 0.0)
        self.assertEqual(result["f1"], 0.0)
        self.assertEqual(result["false_positive_rate"], 0.0)
        self.assertEqual(result["accuracy"], 1.0)
        score = _score_scenario(predictions, labels, scenario="jump", threshold_m=1,
                                match_stats={"unmatched_observations": 0, "unmatched_truth_records": 0})
        self.assertEqual(score["detection_delay_s"], 0.0)
        missed = _score_scenario([predictions[0]], labels, scenario="jump", threshold_m=1,
                                 match_stats={"unmatched_observations": 0, "unmatched_truth_records": 0})
        self.assertIsNone(missed["detection_delay_s"])

    def test_binary_label_validation(self):
        labels = self.tmp / "labels.csv"
        labels.write_text("time_s,vehicle_id,attack_active\n1,ev,yes\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "binary"):
            _read_labels(labels)

    def test_calibration_uses_normal_prefix_and_holds_out_suffix(self):
        threshold, calibration_keys, evaluation_keys, details = calibrate_threshold(
            self.truth, self.gps, quantile=0.5, calibration_fraction=0.6)
        self.assertEqual(len(calibration_keys), 3)
        self.assertEqual(len(evaluation_keys), 2)
        self.assertTrue(calibration_keys.isdisjoint(evaluation_keys))
        self.assertEqual(threshold, 2.0)
        self.assertEqual(details["unmatched_observations"], 1)
        self.assertEqual(details["unmatched_truth_records"], 1)

    def test_reproducible_predictions_and_truth_gps_unchanged(self):
        a, _ = predict_position_residuals(self.truth, self.gps, 2.5)
        b, _ = predict_position_residuals(self.truth, self.gps, 2.5)
        self.assertEqual(a, b)
        self.assertEqual(self.truth.read_bytes(), self.truth_before)
        self.assertEqual(self.gps.read_bytes(), self.gps_before)

    def test_preserves_existing_m0_m3_files(self):
        protected = []
        for relative in ("sumo/network/m0.nod.xml", "sumo/network/m0.edg.xml",
                         "sumo/network/m0.net.xml", "sumo/routes/m0.rou.xml",
                         "sumo/network/m3.nod.xml", "sumo/network/m3.edg.xml",
                         "sumo/network/m3.net.xml", "sumo/routes/m3_route_deviation.rou.xml",
                         "config/experiment_config.yaml", "config/m3_route_deviation.yaml",
                         "docs/M2_NORMAL_GPS.md", "docs/M3_GPS_ATTACKS.md",
                         "src/sensors/gps_normal.py", "src/attacks/gps_attacks.py"):
            path = ROOT / relative
            if path.is_file(): protected.append(path)
        for relative in ("data/raw", "data/processed", "data/attacks", "reports/m2", "reports/m3",
                         "results/m0", "results/figures/m0_m1", "results/tables", "results/metrics"):
            directory = ROOT / relative
            if directory.exists(): protected.extend(p for p in directory.rglob("*") if p.is_file())
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
        predict_position_residuals(self.truth, self.gps, 2.5)
        after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
