"""SUMO/TraCI telemetry integration and reproducibility checks."""

import csv
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "src/simulation/run_sumo.py"
CONFIG = ROOT / "config/experiment_config.yaml"
EXPECTED_COLUMNS = [
    "time_s", "vehicle_id", "x_m", "y_m", "speed_mps", "acceleration_mps2",
    "heading_deg", "road_id", "route_id", "electricity_wh",
    "energy_consumed_wh", "energy_total_consumed_wh", "energy_total_regenerated_wh",
    "battery_charge_wh", "battery_capacity_wh", "soc",
]
NUMERIC_COLUMNS = [column for column in EXPECTED_COLUMNS if column not in {"vehicle_id", "road_id", "route_id"}]


def run_to(path: Path) -> tuple[subprocess.CompletedProcess[str], list[dict[str, str]]]:
    result = subprocess.run(
        [sys.executable, str(RUNNER), "--config", str(CONFIG), "--output", str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        return result, list(reader)


class M1TelemetryTest(unittest.TestCase):
    def test_csv_schema_types_timestep_spacing_and_reproducibility(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            first_path = Path(temp_dir) / "first.csv"
            second_path = Path(temp_dir) / "second.csv"
            first_result, rows = run_to(first_path)
            _, repeated_rows = run_to(second_path)
            metadata_path = first_path.with_name("first_metadata.yaml")
            config_snapshot = first_path.with_name("first_config.yaml")
            self.assertTrue(metadata_path.is_file())
            self.assertTrue(config_snapshot.is_file())
            with metadata_path.open(encoding="utf-8") as stream:
                metadata = yaml.safe_load(stream)

        self.assertIn("Completed EV run: vehicle=ev_001 timesteps=80", first_result.stderr)
        self.assertEqual(metadata["seed"], 42)
        self.assertEqual(metadata["telemetry_rows"], len(rows))
        self.assertEqual(rows, repeated_rows, "same SUMO seed/config should reproduce telemetry rows")
        self.assertGreaterEqual(len(rows), 2)
        self.assertEqual(list(rows[0]), EXPECTED_COLUMNS)
        self.assertTrue(all(row["vehicle_id"] == "ev_001" for row in rows))
        self.assertTrue(all(row["road_id"] == "road_0" and row["route_id"] == "route_0" for row in rows))

        times = []
        for row in rows:
            for column in NUMERIC_COLUMNS:
                self.assertTrue(row[column], f"{column} should be available for this configured EV")
                self.assertTrue(math.isfinite(float(row[column])), column)
            times.append(float(row["time_s"]))
            self.assertGreater(float(row["battery_capacity_wh"]), 0)
            self.assertGreaterEqual(float(row["battery_charge_wh"]), 0)
            self.assertLessEqual(float(row["soc"]), 1)

        self.assertEqual(times, sorted(times))
        self.assertTrue(all(math.isclose(b - a, 1.0) for a, b in zip(times, times[1:])))


if __name__ == "__main__":
    unittest.main()
