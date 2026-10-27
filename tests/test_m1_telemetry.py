"""Unit checks for M1 telemetry collection and CSV validation."""

import csv
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src/simulation"))
import run_sumo  # noqa: E402


class TelemetryCollectionTest(unittest.TestCase):
    def test_collect_vehicle_record_reads_traci_and_derives_soc(self) -> None:
        battery = {
            "device.battery.chargeLevel": "53999.5",
            "device.battery.capacity": "60000",
            "device.battery.energyConsumed": "0.5",
            "device.battery.totalEnergyConsumed": "1.2",
            "device.battery.totalEnergyRegenerated": "0.1",
        }
        with (
            patch.object(run_sumo.traci.simulation, "getTime", return_value=12.0),
            patch.object(run_sumo.traci.vehicle, "getPosition", return_value=(10.0, 20.0)),
            patch.object(run_sumo.traci.vehicle, "getSpeed", return_value=5.0),
            patch.object(run_sumo.traci.vehicle, "getAcceleration", return_value=0.2),
            patch.object(run_sumo.traci.vehicle, "getAngle", return_value=90.0),
            patch.object(run_sumo.traci.vehicle, "getRoadID", return_value="A0A1"),
            patch.object(run_sumo.traci.vehicle, "getRouteID", return_value="ev_route"),
            patch.object(run_sumo.traci.vehicle, "getParameter", side_effect=lambda _v, key: battery[key]),
            patch.object(run_sumo.traci.vehicle, "getElectricityConsumption", return_value=0.5),
        ):
            record = run_sumo.collect_vehicle_record("ev_001", "ev_001_seed_42", 42)

        self.assertEqual(record["vehicle_id"], "ev_001")
        self.assertEqual(record["road_id"], "A0A1")
        self.assertEqual(record["route_id"], "ev_route")
        self.assertAlmostEqual(record["soc"], 53999.5 / 60000)
        self.assertEqual(record["total_energy_consumed_wh"], 1.2)
        self.assertEqual(record["electricity_consumption_wh_per_s"], 0.5)

    def test_csv_validator_accepts_required_schema_and_optional_blanks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "truth.csv"
            row = self.valid_row(time_s=1)
            row["battery_charge_wh"] = ""
            row["soc"] = ""
            with csv_path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=run_sumo.CSV_FIELDS)
                writer.writeheader()
                writer.writerow(row)

            self.assertEqual(run_sumo.validate_telemetry_csv(csv_path), (1, 1.0))

    def test_csv_validator_rejects_non_increasing_time(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "truth.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=run_sumo.CSV_FIELDS)
                writer.writeheader()
                writer.writerow(self.valid_row(time_s=2))
                writer.writerow(self.valid_row(time_s=2))

            with self.assertRaisesRegex(ValueError, "strictly increasing"):
                run_sumo.validate_telemetry_csv(csv_path)

    @staticmethod
    def valid_row(time_s: int) -> dict[str, str | int]:
        row = {name: "" for name in run_sumo.CSV_FIELDS}
        row.update(
            {
                "time_s": time_s,
                "trip_id": "ev_001_seed_42",
                "vehicle_id": "ev_001",
                "seed": 42,
                "x_m": 10,
                "y_m": 20,
                "speed_mps": 5,
                "acceleration_mps2": 0,
                "heading_deg": 90,
                "road_id": "A0A1",
                "route_id": "ev_route",
            }
        )
        return row


if __name__ == "__main__":
    unittest.main()
