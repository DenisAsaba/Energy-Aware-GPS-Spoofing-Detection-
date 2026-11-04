"""Read-only telemetry loading and dashboard metric tests."""

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.dashboard.telemetry import TelemetryError, discover_csv_files, load_telemetry, summarize_telemetry


class DashboardTelemetryTests(unittest.TestCase):
    def test_load_and_calculate_metrics_from_existing_style_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "truth.csv"
            source = "time_s,vehicle_id,x_m,y_m,speed_mps,acceleration_mps2,battery_charge_wh,soc,energy_total_consumed_wh,energy_total_regenerated_wh\n"
            source += "1,ev_001,0,0,2,0,100,0.5,0,0\n2,ev_001,3,4,4,2,90,0.45,12,3\n"
            path.write_text(source, encoding="utf-8")
            before = path.read_bytes()
            frame = load_telemetry(path)
            summary = summarize_telemetry(frame)
            self.assertEqual(path.read_bytes(), before, "dashboard must never modify source CSV")

        self.assertEqual(summary.records, 2)
        self.assertEqual(summary.vehicle_id, "ev_001")
        self.assertEqual(summary.duration_s, 1.0)
        self.assertEqual((summary.speed_min_mps, summary.speed_mean_mps, summary.speed_max_mps), (2.0, 3.0, 4.0))
        self.assertEqual((summary.charge_initial_wh, summary.charge_final_wh), (100.0, 90.0))
        self.assertEqual((summary.soc_initial, summary.soc_final), (0.5, 0.45))
        self.assertEqual(summary.energy_consumed_total_wh, 12.0)
        self.assertEqual(summary.energy_regenerated_total_wh, 3.0)

    def test_missing_optional_values_remain_unavailable(self) -> None:
        frame = pd.DataFrame({"time_s": [1, 2], "vehicle_id": ["ev_a", "ev_a"], "speed_mps": [None, None]})
        summary = summarize_telemetry(frame)
        self.assertIsNone(summary.speed_mean_mps)
        self.assertIsNone(summary.charge_initial_wh)
        self.assertIsNone(summary.soc_initial)
        self.assertIsNone(summary.energy_consumed_total_wh)
        self.assertIsNone(summary.energy_regenerated_total_wh)

    def test_initial_final_values_follow_simulation_time(self) -> None:
        frame = pd.DataFrame({
            "time_s": [2, 1], "vehicle_id": ["ev_a", "ev_a"],
            "battery_charge_wh": [90, 100], "soc": [0.45, 0.5],
            "energy_total_consumed_wh": [12, 0], "energy_total_regenerated_wh": [3, 0],
        })
        summary = summarize_telemetry(frame)
        self.assertEqual((summary.charge_initial_wh, summary.charge_final_wh), (100.0, 90.0))
        self.assertEqual((summary.soc_initial, summary.soc_final), (0.5, 0.45))
        self.assertEqual(summary.energy_consumed_total_wh, 12.0)
        self.assertEqual(summary.energy_regenerated_total_wh, 3.0)

    def test_empty_and_malformed_files_have_readable_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            empty = Path(temp) / "empty.csv"
            empty.write_text("", encoding="utf-8")
            with self.assertRaisesRegex(TelemetryError, "Could not read"):
                load_telemetry(empty)

            malformed = Path(temp) / "malformed.csv"
            malformed.write_text("time_s,vehicle_id\n1,ev_1\n2,ev_2,extra\n", encoding="utf-8")
            with self.assertRaises(TelemetryError):
                load_telemetry(malformed)

            unsupported = Path(temp) / "unsupported.csv"
            unsupported.write_text("x,y\n1,2\n", encoding="utf-8")
            with self.assertRaisesRegex(TelemetryError, "time_s, vehicle_id"):
                load_telemetry(unsupported)

    def test_discovery_finds_only_csv_files_in_stable_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "b.csv").write_text("", encoding="utf-8")
            (root / "a.csv").write_text("", encoding="utf-8")
            (root / "run.yaml").write_text("", encoding="utf-8")
            self.assertEqual([p.name for p in discover_csv_files(root)], ["b.csv", "a.csv"])


if __name__ == "__main__":
    unittest.main()
