"""M2 tests for normal GPS observation generation and evaluation separation."""

import csv
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src/sensors"))
import gps_normal  # noqa: E402


class NormalGpsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.truth_path = self.root / "truth.csv"
        with self.truth_path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=["time_s", "trip_id", "vehicle_id", "seed", "x_m", "y_m", "speed_mps"])
            writer.writeheader()
            writer.writerows([
                {"time_s": index, "trip_id": "trip_1", "vehicle_id": "ev_1", "seed": 42, "x_m": index * 10, "y_m": 20}
                for index in range(1, 21)
            ])

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_reproducible_seed_and_preserves_truth_bytes(self) -> None:
        original = self.truth_path.read_bytes()
        first, summary = gps_normal.generate(self.truth_path, self.root / "gps1.csv", seed=19, sigma_m=3.0)
        second, _ = gps_normal.generate(self.truth_path, self.root / "gps2.csv", seed=19, sigma_m=3.0)
        self.assertEqual((self.root / "gps1.csv").read_bytes(), (self.root / "gps2.csv").read_bytes())
        self.assertEqual(first, second)
        self.assertEqual(self.truth_path.read_bytes(), original)
        self.assertTrue(summary["ground_truth_used_only_for_offline_evaluation"])

    def test_noise_is_nonzero_configurable_and_gps_schema_has_no_truth(self) -> None:
        observations, _ = gps_normal.generate(self.truth_path, self.root / "gps.csv", seed=123, sigma_m=4.0)
        self.assertEqual(len(observations), 20)
        self.assertTrue(any(abs(row["gps_x_m"] - index * 10) > 1e-9 or abs(row["gps_y_m"] - 20) > 1e-9 for index, row in enumerate(observations, start=1)))
        with (self.root / "gps.csv").open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            self.assertEqual(tuple(reader.fieldnames or ()), gps_normal.GPS_FIELDS)
            rows = list(reader)
        self.assertTrue(all(float(row["position_std_m"]) == 4.0 for row in rows))
        self.assertTrue({"gps_x_m", "gps_y_m", "time_s", "trip_id", "vehicle_id"}.issubset(reader.fieldnames or ()))
        self.assertFalse({"x_m", "y_m", "gps_position_error", "attack_active"}.intersection(reader.fieldnames or ()))

    def test_zero_sigma_gives_exact_coordinates_and_invalid_sigma_rejected(self) -> None:
        observations, summary = gps_normal.generate(self.truth_path, self.root / "zero.csv", seed=7, sigma_m=0.0)
        self.assertEqual(observations[0]["gps_x_m"], 10.0)
        self.assertEqual(observations[0]["gps_y_m"], 20.0)
        self.assertEqual(summary["radial_error_m"]["maximum"], 0.0)
        with self.assertRaisesRegex(ValueError, "finite and nonnegative"):
            gps_normal.generate(self.truth_path, self.root / "bad.csv", seed=7, sigma_m=-1)

    def test_refuses_to_overwrite_truth(self) -> None:
        original = self.truth_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "separate file"):
            gps_normal.generate(self.truth_path, self.truth_path, seed=7, sigma_m=3)
        self.assertEqual(self.truth_path.read_bytes(), original)

    def test_summary_error_values_are_deterministic(self) -> None:
        _, first = gps_normal.generate(self.truth_path, self.root / "a.csv", seed=5, sigma_m=3)
        _, second = gps_normal.generate(self.truth_path, self.root / "b.csv", seed=5, sigma_m=3)
        self.assertEqual(first, second)
        self.assertGreater(first["radial_error_m"]["mean"], 0)


if __name__ == "__main__":
    unittest.main()
