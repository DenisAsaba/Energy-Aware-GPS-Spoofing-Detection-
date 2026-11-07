"""Unit and small-workflow tests for the isolated M6 campaign."""

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from src.experiments.m6_robustness import (
    _aggregate, _evaluate, _protected_snapshot, _stable_seed, build_experiment_matrix,
    run_campaign, validate_routes,
)

ROOT = Path(__file__).resolve().parents[1]


class M6RobustnessTests(unittest.TestCase):
    def setUp(self):
        self.config = yaml.safe_load((ROOT / "config/m6_robustness.yaml").read_text(encoding="utf-8"))

    def test_full_and_smoke_matrix_have_unique_ids_and_expected_splits(self):
        full = build_experiment_matrix(self.config)
        ids = [row["experiment_id"] for row in full]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(sum(row["split"] == "calibration" for row in full), 4)
        self.assertEqual(sum(row["split"] == "validation" for row in full), 2)
        self.assertEqual(sum(row["split"] == "test" and row["scenario"] == "normal" for row in full), 4)
        self.assertEqual(sum(row["split"] == "test" and row["scenario"] != "normal" for row in full), 48)
        self.assertEqual({row["route"] for row in full}, {"m0_route", "m3_alternative"})
        calibration_trips = {row["trip_id"] for row in full if row["split"] == "calibration"}
        validation_trips = {row["trip_id"] for row in full if row["split"] == "validation"}
        test_trips = {row["trip_id"] for row in full if row["split"] == "test"}
        self.assertTrue(calibration_trips.isdisjoint(validation_trips))
        self.assertTrue(calibration_trips.isdisjoint(test_trips))
        self.assertTrue(validation_trips.isdisjoint(test_trips))
        smoke = build_experiment_matrix(self.config, smoke=True)
        self.assertEqual(len(smoke), 6)
        self.assertEqual({row["route"] for row in smoke}, {"m0_route"})
        self.assertTrue(all(row["seed"] == 903 for row in smoke if row["split"] == "test"))

    def test_attack_matrix_uses_m3_units_and_multiple_durations(self):
        matrix = build_experiment_matrix(self.config)
        offset = [row for row in matrix if row["attack_type"] == "offset"]
        drift = [row for row in matrix if row["attack_type"] == "drift"]
        self.assertEqual({row["attack_intensity_unit"] for row in offset}, {"m"})
        self.assertEqual({row["attack_duration_s"] for row in offset}, {10.0, 30.0})
        self.assertEqual({row["attack_intensity_unit"] for row in drift}, {"mps"})
        self.assertEqual({row["attack_duration_s"] for row in drift}, {10.0, 30.0})
        self.assertEqual(_stable_seed(7, 9, "m0_route"), _stable_seed(7, 9, "m0_route"))
        self.assertNotEqual(_stable_seed(7, 9, "m0_route"), _stable_seed(7, 9, "m3_alternative"))

    def test_both_configured_routes_validate_with_sumo(self):
        routes = validate_routes(ROOT, self.config)
        self.assertEqual(set(routes), {"m0_route", "m3_alternative"})
        self.assertEqual(routes["m0_route"]["edges"], ["road_0"])
        self.assertEqual(routes["m3_alternative"]["edges"], ["road_alt_0", "road_alt_1"])

    def test_aggregation_uses_trip_rows_and_sample_standard_deviation(self):
        rows = [
            {"detector": "M5", "scenario": "jump", "attack_type": "jump", "attack_intensity": "20 m",
             "attack_duration_s": 1.0, "seed": seed, "route": "r", "f1": score,
             "precision": score, "recall": score, "false_positive_rate": 0.0,
             "accuracy": score, "detection_delay_s": delay,
             "true_positive": 1, "false_positive": 0, "true_negative": 0, "false_negative": 0}
            for seed, score, delay in ((1, .2, 0.0), (2, .8, None))
        ]
        summary = _aggregate(rows)
        selected = next(row for row in summary if row["group_by"] == "detector;scenario")
        self.assertEqual(selected["n_experiments"], 2)
        self.assertAlmostEqual(selected["f1_mean"], .5)
        self.assertAlmostEqual(selected["f1_std"], (0.18 ** .5))
        self.assertEqual(selected["detection_delay_s_n"], 1)
        self.assertEqual(selected["true_positive"], 2)
        self.assertEqual(_aggregate([]), [])

    def test_m5_prediction_bytes_do_not_depend_on_truth_or_attack_labels(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            truth = root / "truth.csv"
            gps = root / "gps.csv"
            labels = root / "labels.csv"
            truth.write_text("time_s,vehicle_id,x_m,y_m\n1,v,0,0\n2,v,0,0\n3,v,0,0\n4,v,0,0\n", encoding="utf-8")
            gps.write_text("time_s,vehicle_id,gps_x_m,gps_y_m\n1,v,0,0\n2,v,1,0\n3,v,2,0\n4,v,3,0\n", encoding="utf-8")
            labels.write_text("time_s,vehicle_id,attack_active\n1,v,0\n2,v,1\n3,v,1\n4,v,0\n", encoding="utf-8")
            record = {"experiment_id": "case", "split": "test", "scenario": "jump", "attack_type": "jump",
                      "attack_intensity": "20 m", "attack_intensity_value": 20, "attack_intensity_unit": "m",
                      "attack_duration_s": 1, "seed": 1, "route": "r"}
            thresholds = {"max_speed_mps": 100, "max_speed_change_mps": 100, "max_heading_change_deg": 360}
            first_dir = root / "first"
            first_dir.mkdir()
            _evaluate(record, truth, gps, labels, 5.0, thresholds, first_dir)
            first = (first_dir / "case_m5_predictions.csv").read_bytes()
            truth.write_text("time_s,vehicle_id,x_m,y_m\n1,v,900,900\n2,v,800,800\n3,v,700,700\n4,v,600,600\n", encoding="utf-8")
            labels.write_text("time_s,vehicle_id,attack_active\n1,v,1\n2,v,0\n3,v,0\n4,v,1\n", encoding="utf-8")
            second_dir = root / "second"
            second_dir.mkdir()
            _evaluate(record, truth, gps, labels, 5.0, thresholds, second_dir)
            self.assertEqual(first, (second_dir / "case_m5_predictions.csv").read_bytes())

    def test_smoke_campaign_is_reproducible_separate_and_run_id_protected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path = root / "config" / "m6.yaml"
            config_path.parent.mkdir()
            config = dict(self.config)
            config["routes"] = {"m0_route": self.config["routes"]["m0_route"]}
            config["routes"]["m0_route"] = {**config["routes"]["m0_route"],
                "network_file": str(ROOT / "sumo/network/m0.net.xml"),
                "route_file": str(ROOT / "sumo/routes/m0.rou.xml")}
            config["output_root"] = str(root / "reports")
            config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
            protected = [ROOT / "config/experiment_config.yaml", ROOT / "src/detection/gps_spoofing.py",
                         ROOT / "src/detection/gps_only.py", ROOT / "reports/m4/m4_final_01/summary.csv",
                         ROOT / "reports/m5/m5_final_01/summary.csv"]
            before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in protected}
            first = run_campaign(config_path, "smoke_a", smoke=True)
            second = run_campaign(config_path, "smoke_b", smoke=True)
            first_dir, second_dir = Path(first["output_dir"]), Path(second["output_dir"])
            self.assertEqual(first["test_experiments"], 4)
            self.assertEqual(first["detector_evaluations"], 8)
            for name in ("experiment_matrix.csv", "per_experiment_metrics.csv", "aggregate_metrics.csv",
                         "threshold_calibration.json", "validation_metrics.csv"):
                self.assertEqual((first_dir / name).read_bytes(), (second_dir / name).read_bytes())
            metadata = json.loads((first_dir / "run_metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["m5_prediction_excludes"], ["ground truth", "attack labels", "future GPS fixes"])
            self.assertTrue(metadata["protected_m0_m5_unchanged"])
            self.assertGreater(_protected_snapshot(ROOT)["file_count"], 0)
            self.assertEqual([path for path in protected if hashlib.sha256(path.read_bytes()).hexdigest() != before[path]], [])
            manifest = {path: hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in first_dir.rglob("*") if path.is_file()}
            with self.assertRaises(FileExistsError):
                run_campaign(config_path, "smoke_a", smoke=True)
            self.assertEqual(manifest, {path: hashlib.sha256(path.read_bytes()).hexdigest()
                                        for path in first_dir.rglob("*") if path.is_file()})


if __name__ == "__main__":
    unittest.main()
