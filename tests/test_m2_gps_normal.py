"""Unit tests for M2 normal GPS generation and offline evaluation."""

import csv
import json
import math
import tempfile
import unittest
from pathlib import Path

from src.sensors.gps_normal import evaluate_observations, generate_observations, save_evaluation


class M2GpsNormalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.truth = self.root / "truth.csv"
        self.truth.write_text(
            "time_s,vehicle_id,x_m,y_m,speed_mps\n"
            "1,ev_a,0,0,2\n2,ev_a,3,4,2\n1,ev_b,10,0,2\n", encoding="utf-8")
        self.before = self.truth.read_bytes()

    def tearDown(self):
        self.temp.cleanup()

    def _gen(self, name, sigma=2.0, seed=42):
        path = self.root / name
        generate_observations(self.truth, path, noise_std_m=sigma, seed=seed)
        return path

    def test_reproducible_for_same_seed_and_different_for_other_seed(self):
        a, b, c = self._gen("a.csv"), self._gen("b.csv"), self._gen("c.csv", seed=43)
        self.assertEqual(a.read_bytes(), b.read_bytes())
        self.assertNotEqual(a.read_bytes(), c.read_bytes())

    def test_zero_noise_exact_and_nonzero_noise_differs(self):
        zero, noisy = self._gen("zero.csv", 0), self._gen("noisy.csv")
        _, errors = evaluate_observations(self.truth, zero)
        self.assertTrue(all(item["position_error_m"] == 0 for item in errors))
        _, errors = evaluate_observations(self.truth, noisy)
        self.assertTrue(any(item["position_error_m"] > 0 for item in errors))

    def test_alignment_schema_and_no_leakage(self):
        gps = self._gen("gps.csv")
        with gps.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            rows = list(reader)
            self.assertEqual(reader.fieldnames, ["time_s", "vehicle_id", "gps_x_m", "gps_y_m"])
        self.assertEqual([(r["time_s"], r["vehicle_id"]) for r in rows], [("1", "ev_a"), ("2", "ev_a"), ("1", "ev_b")])
        forbidden = {"x_m", "y_m", "position_error_m", "gps_position_error", "attack_active", "attack_type"}
        self.assertFalse(forbidden.intersection(reader.fieldnames))
        metrics, errors = evaluate_observations(self.truth, gps)
        self.assertEqual(metrics["matched_observations"], len(rows))
        self.assertEqual(len(errors), len(rows))
        self.assertEqual(self.truth.read_bytes(), self.before)

    def test_metrics_and_unmatched_counts(self):
        gps = self.root / "manual.csv"
        gps.write_text("time_s,vehicle_id,gps_x_m,gps_y_m\n1,ev_a,3,4\n2,ev_a,3,6\n9,extra,0,0\n", encoding="utf-8")
        metrics, errors = evaluate_observations(self.truth, gps)
        self.assertEqual([e["position_error_m"] for e in errors], [5.0, 2.0])
        self.assertAlmostEqual(metrics["mean_error_m"], 3.5)
        self.assertAlmostEqual(metrics["mae_m"], 3.5)
        self.assertAlmostEqual(metrics["rmse_m"], math.sqrt((25 + 4) / 2))
        self.assertAlmostEqual(metrics["p95_error_m"], 4.85)
        self.assertEqual(metrics["unmatched_observations"], 1)
        self.assertEqual(metrics["unmatched_truth_records"], 1)

    def test_missing_invalid_and_duplicate_input_rejected_without_changing_truth(self):
        bad = self.root / "bad.csv"
        bad.write_text("time_s,vehicle_id,x_m,y_m\n1,ev_a,,0\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "invalid/missing"):
            generate_observations(bad, self.root / "out.csv", noise_std_m=1, seed=1)
        bad.write_text("time_s,vehicle_id,x_m,y_m\n1,ev_a,0,0\n1,ev_a,1,1\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            generate_observations(bad, self.root / "out.csv", noise_std_m=1, seed=1)
        self.assertEqual(self.truth.read_bytes(), self.before)

    def test_nonfinite_parameters_and_in_place_write_rejected(self):
        with self.assertRaisesRegex(ValueError, "finite nonnegative"):
            generate_observations(self.truth, self.root / "bad.csv", noise_std_m=float("nan"), seed=1)
        with self.assertRaisesRegex(ValueError, "separate"):
            generate_observations(self.truth, self.truth, noise_std_m=1, seed=1)

    def test_evaluation_writes_metrics_and_three_plots(self):
        gps = self._gen("gps.csv")
        out = self.root / "reports"
        metrics = save_evaluation(self.truth, gps, out)
        self.assertEqual(json.loads((out / "gps_metrics.json").read_text(encoding="utf-8")), metrics)
        self.assertEqual(len(list(out.glob("*.png"))), 3)
        self.assertTrue(all(p.stat().st_size > 1000 for p in out.glob("*.png")))


if __name__ == "__main__":
    unittest.main()
