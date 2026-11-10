"""M8 experiment split, event scoring, and reproducibility helper tests."""

import csv
import tempfile
import unittest
from pathlib import Path

import yaml

from src.experiments.m8_evaluation import _metrics, _validate_splits, compare_runs

ROOT = Path(__file__).resolve().parents[1]


class M8EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.config = yaml.safe_load((ROOT / "config/m8_detector.yaml").read_text(encoding="utf-8"))

    def test_split_assignments_use_disjoint_trip_ids_seeds_and_route_groups(self):
        manifest = _validate_splits(self.config)
        self.assertEqual(set(manifest), {"calibration", "validation", "smoke", "final_test"})
        self.assertTrue(set(manifest["calibration"]["sumo_seeds"]).isdisjoint(manifest["validation"]["sumo_seeds"]))
        self.assertTrue(set(manifest["smoke"]["sumo_seeds"]).isdisjoint(manifest["final_test"]["sumo_seeds"]))
        self.assertTrue(set(manifest["smoke"]["route_groups"]).isdisjoint(manifest["final_test"]["route_groups"]))

    def test_split_validator_rejects_reused_seed_and_route(self):
        broken = yaml.safe_load(yaml.safe_dump(self.config))
        broken["splits"]["validation"]["trips"][0]["seed"] = 1001
        with self.assertRaisesRegex(ValueError, "seeds overlap"):
            _validate_splits(broken)
        broken = yaml.safe_load(yaml.safe_dump(self.config))
        broken["splits"]["smoke"]["trips"][0]["route_group"] = "m0_straight"
        with self.assertRaisesRegex(ValueError, "route groups overlap"):
            _validate_splits(broken)

    def test_active_and_post_attack_metrics_are_separate(self):
        predictions = [
            {"time_s": 10, "vehicle_id": "a", "eligible": 1, "predicted_attack": 0},
            {"time_s": 11, "vehicle_id": "a", "eligible": 1, "predicted_attack": 1},
            {"time_s": 12, "vehicle_id": "a", "eligible": 1, "predicted_attack": 1},
            {"time_s": 13, "vehicle_id": "a", "eligible": 1, "predicted_attack": 0},
        ]
        labels = {
            (10.0, "a"): {"attack_active": 0}, (11.0, "a"): {"attack_active": 1},
            (12.0, "a"): {"attack_active": 1}, (13.0, "a"): {"attack_active": 0},
        }
        result = _metrics(predictions, labels, split="smoke",
                          trip={"trip_id": "t", "seed": 4, "route_group": "r"},
                          scenario="jump", detector="M8",
                          settings={"onset_s": 11, "duration_s": 2, "magnitude_m": 20})
        self.assertEqual((result["tp"], result["fp"], result["tn"], result["fn"]), (2, 0, 2, 0))
        self.assertEqual(result["active_attack_detection_rate"], 1.0)
        self.assertEqual(result["detection_delay_s"], 0.0)
        self.assertEqual(result["post_attack_alerts"], 0)

    def test_post_attack_alert_does_not_count_as_event_detection(self):
        predictions = [
            {"time_s": 10, "vehicle_id": "a", "eligible": 1, "predicted_attack": 0},
            {"time_s": 11, "vehicle_id": "a", "eligible": 1, "predicted_attack": 0},
            {"time_s": 12, "vehicle_id": "a", "eligible": 1, "predicted_attack": 1},
        ]
        labels = {(10.0, "a"): {"attack_active": 0}, (11.0, "a"): {"attack_active": 1},
                  (12.0, "a"): {"attack_active": 0}}
        result = _metrics(predictions, labels, split="smoke",
                          trip={"trip_id": "t", "seed": 4, "route_group": "r"},
                          scenario="jump", detector="M8",
                          settings={"onset_s": 11, "duration_s": 1, "magnitude_m": 20})
        self.assertEqual(result["active_attack_detection_rate"], 0.0)
        self.assertEqual(result["missed_attack_rate"], 1.0)
        self.assertEqual(result["detection_delay_s"], "")
        self.assertEqual(result["post_attack_alerts"], 1)

    def test_compare_runs_excludes_metadata_and_checks_all_csv_json_png(self):
        with tempfile.TemporaryDirectory() as temporary:
            first, second = Path(temporary) / "a", Path(temporary) / "b"
            first.mkdir(); second.mkdir()
            for root in (first, second):
                (root / "predictions.csv").write_text("x\n1\n", encoding="utf-8")
                (root / "summary.json").write_text("{\"ok\": true}\n", encoding="utf-8")
                (root / "plot.png").write_bytes(b"same plot")
                (root / "metadata.json").write_text(root.name, encoding="utf-8")
            result = compare_runs(first, second)
            self.assertTrue(result["identical"])
            (second / "predictions.csv").write_text("x\n2\n", encoding="utf-8")
            self.assertFalse(compare_runs(first, second)["identical"])


if __name__ == "__main__":
    unittest.main()
