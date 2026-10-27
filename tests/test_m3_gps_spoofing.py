"""Fast M3 unit tests using a small synthetic trip; no SUMO process required."""

import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src/attacks"))
import gps_spoofing  # noqa: E402


class GpsSpoofingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture_dir = tempfile.TemporaryDirectory()
        self.fixture_root = Path(self.fixture_dir.name)
        self.normal = []
        self.truth = []
        for time_s in range(1, 6):
            self.normal.append({
                "time_s": str(float(time_s)), "trip_id": "trip_test", "vehicle_id": "ev_test",
                "gps_seed": "123", "noise_model": "independent_gaussian_xy", "position_std_m": "3.0",
                "gps_x_m": str(time_s * 10 + 0.25), "gps_y_m": str(time_s * 2 - 0.1),
            })
            self.truth.append({
                "time_s": str(float(time_s)), "trip_id": "trip_test", "vehicle_id": "ev_test",
                "x_m": str(time_s * 10), "y_m": str(time_s * 2),
            })

    def tearDown(self) -> None:
        self.fixture_dir.cleanup()

    def test_offset_is_constant_inside_half_open_interval(self) -> None:
        attacked, labels = gps_spoofing.apply_attack(self.normal, "offset", {
            "onset_time_s": 2, "duration_s": 2, "magnitude_m": 10, "direction_deg": 90,
        })
        self.assertEqual([r["attack_active"] for r in labels], ["false", "true", "true", "false", "false"])
        self.assertAlmostEqual(attacked[1]["gps_x_m"], float(self.normal[1]["gps_x_m"]))
        self.assertAlmostEqual(attacked[1]["gps_y_m"] - float(self.normal[1]["gps_y_m"]), 10)
        self.assertAlmostEqual(labels[2]["displacement_m"], 10)
        self.assertEqual(attacked[3]["gps_y_m"], self.normal[3]["gps_y_m"])

    def test_jump_is_abrupt_and_returns_to_normal_after_duration(self) -> None:
        attacked, labels = gps_spoofing.apply_attack(self.normal, "jump", {
            "onset_time_s": 3, "duration_s": 1, "magnitude_m": 7, "direction_deg": 0,
        })
        self.assertEqual([r["attack_active"] for r in labels], ["false", "false", "true", "false", "false"])
        self.assertAlmostEqual(attacked[2]["gps_x_m"] - float(self.normal[2]["gps_x_m"]), 7)
        self.assertEqual(attacked[3]["gps_x_m"], self.normal[3]["gps_x_m"])

    def test_drift_grows_linearly_from_zero_and_resets_at_end(self) -> None:
        attacked, labels = gps_spoofing.apply_attack(self.normal, "drift", {
            "onset_time_s": 2, "duration_s": 3, "drift_rate_mps": 2, "direction_deg": 0,
        })
        self.assertEqual([r["attack_active"] for r in labels], ["false", "true", "true", "true", "false"])
        self.assertEqual([r["displacement_m"] for r in labels], [0, 0, 2, 4, 0])
        self.assertAlmostEqual(attacked[2]["gps_x_m"] - float(self.normal[2]["gps_x_m"]), 2)
        self.assertEqual(attacked[4]["gps_x_m"], self.normal[4]["gps_x_m"])

    def test_outside_interval_is_all_inactive_and_invalid_parameters_rejected(self) -> None:
        attacked, labels = gps_spoofing.apply_attack(self.normal, "offset", {
            "onset_time_s": 10, "duration_s": 2, "magnitude_m": 5, "direction_deg": 0,
        })
        self.assertTrue(all(row["attack_active"] == "false" for row in labels))
        self.assertEqual([r["gps_x_m"] for r in attacked], [r["gps_x_m"] for r in self.normal])
        for bad in (
            {"onset_time_s": 1, "duration_s": 0, "magnitude_m": 5, "direction_deg": 0},
            {"onset_time_s": 1, "duration_s": 2, "magnitude_m": 5, "direction_deg": 360},
            {"onset_time_s": 1, "duration_s": 2, "magnitude_m": float("nan"), "direction_deg": 0},
        ):
            with self.assertRaises(ValueError):
                gps_spoofing.apply_attack(self.normal, "offset", bad)
        with self.assertRaisesRegex(ValueError, "overflowed"):
            gps_spoofing.apply_attack(self.normal, "drift", {
                "onset_time_s": 1, "duration_s": 4, "drift_rate_mps": 1e308, "direction_deg": 0,
            })

    def test_reproducible_and_preserves_normal_schema_data_and_truth(self) -> None:
        normal_bytes = self._write_csv("normal.csv", gps_spoofing.GPS_FIELDS, self.normal, self.fixture_root)
        truth_bytes = self._write_csv("truth.csv", gps_spoofing.TRUTH_FIELDS, self.truth, self.fixture_root)
        normal_path = self.fixture_root / "normal.csv"
        truth_path = self.fixture_root / "truth.csv"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_paths = gps_spoofing.generate_attack(
                normal_path, truth_path, "drift",
                {"onset_time_s": 2, "duration_s": 3, "drift_rate_mps": 2, "direction_deg": 0},
                root / "attacks", root / "figures", root / "tables",
            )
            first = output_paths["observations"].read_bytes()
            attacked, _ = gps_spoofing.apply_attack(self.normal, "drift", {
                "onset_time_s": 2, "duration_s": 3, "drift_rate_mps": 2, "direction_deg": 0,
            })
            second_path = root / "repeat.csv"
            gps_spoofing._write_csv(second_path, gps_spoofing.GPS_FIELDS, attacked)
            self.assertEqual(first, second_path.read_bytes())
            with output_paths["observations"].open(newline="", encoding="utf-8") as stream:
                observation_reader = csv.DictReader(stream)
                observation_rows = list(observation_reader)
            with output_paths["labels"].open(newline="", encoding="utf-8") as stream:
                label_reader = csv.DictReader(stream)
                label_rows = list(label_reader)
            self.assertEqual(tuple(observation_reader.fieldnames or ()), gps_spoofing.GPS_FIELDS)
            self.assertFalse({"attack_type", "attack_active", "x_m", "y_m"}.intersection(observation_reader.fieldnames or ()))
            self.assertEqual(tuple(label_reader.fieldnames or ()), gps_spoofing.LABEL_FIELDS)
            self.assertEqual(len(observation_rows), len(label_rows))
            self.assertEqual(
                [(r["trip_id"], r["vehicle_id"], r["time_s"]) for r in observation_rows],
                [(r["trip_id"], r["vehicle_id"], r["time_s"]) for r in label_rows],
            )
            self.assertEqual(normal_path.read_bytes(), normal_bytes)
            self.assertEqual(truth_path.read_bytes(), truth_bytes)
            summary = json.loads(output_paths["summary"].read_text(encoding="utf-8"))
            self.assertEqual(summary["active_record_count"], 3)
            self.assertTrue(output_paths["trajectory_plot"].is_file())
            self.assertTrue(output_paths["error_plot"].is_file())

    def test_load_inputs_rejects_duplicate_or_unmatched_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            normal_path = root / "normal.csv"
            truth_path = root / "truth.csv"
            self._write_csv(normal_path.name, gps_spoofing.GPS_FIELDS, self.normal, root)
            self._write_csv(truth_path.name, gps_spoofing.TRUTH_FIELDS, self.truth, root)
            gps_spoofing.load_inputs(normal_path, truth_path)
            duplicate_rows = [*self.normal, dict(self.normal[0])]
            self._write_csv(normal_path.name, gps_spoofing.GPS_FIELDS, duplicate_rows, root)
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                gps_spoofing.load_inputs(normal_path, truth_path)
            self._write_csv(normal_path.name, gps_spoofing.GPS_FIELDS, self.normal[:-1], root)
            with self.assertRaisesRegex(ValueError, "keys do not match"):
                gps_spoofing.load_inputs(normal_path, truth_path)

    def _write_csv(self, name: str, fields: tuple[str, ...], rows: list[dict], root: Path | None = None) -> bytes:
        path = (root or self.fixture_root) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        return path.read_bytes()


if __name__ == "__main__":
    unittest.main()
