"""M3 route scenario tests: labels plus a real SUMO alternative-route trip."""

import csv
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src/attacks"))
import route_deviation  # noqa: E402


class RouteDeviationTest(unittest.TestCase):
    def test_route_labels_are_separate_and_keep_trip_keys(self) -> None:
        truth = [
            {"time_s": "1.0", "trip_id": "alt_trip", "vehicle_id": "ev_001", "route_id": "ev_route_alternative", "x_m": "2", "y_m": "3"},
            {"time_s": "2.0", "trip_id": "alt_trip", "vehicle_id": "ev_001", "route_id": "ev_route_alternative", "x_m": "4", "y_m": "5"},
        ]
        labels = route_deviation.make_route_labels(truth)
        self.assertEqual(len(labels), 2)
        self.assertTrue(all(row["attack_active"] == "true" for row in labels))
        self.assertTrue(all(row["attack_type"] == "route_deviation" for row in labels))
        self.assertEqual(labels[0]["trip_id"], truth[0]["trip_id"])
        self.assertNotIn("x_m", labels[0])
        self.assertNotIn("gps_x_m", labels[0])

    def test_sumo_completes_genuine_valid_alternative_route(self) -> None:
        baseline_route = ET.parse(PROJECT_ROOT / "sumo/routes/ev.rou.xml").getroot().find("route")
        alternative_route = ET.parse(PROJECT_ROOT / "sumo/routes/ev_alternative.rou.xml").getroot().find("route")
        self.assertIsNotNone(baseline_route)
        self.assertIsNotNone(alternative_route)
        baseline_edges = baseline_route.attrib["edges"].split()
        alternative_edges = alternative_route.attrib["edges"].split()
        self.assertNotEqual(baseline_edges, alternative_edges)
        self.assertEqual(baseline_edges[0], "A0A1")
        self.assertEqual(alternative_edges, ["A0B0", "B0B1"])

        with tempfile.TemporaryDirectory() as temp_dir:
            outputs = [Path(temp_dir) / f"route_deviation_{index}.csv" for index in (1, 2)]
            for output in outputs:
                result = subprocess.run(
                    [sys.executable, str(PROJECT_ROOT / "src/simulation/run_sumo.py"),
                     "--config", str(PROJECT_ROOT / "config/route_deviation.yaml"), "--output", str(output)],
                    cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=60, check=False,
                )
                self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertEqual(outputs[0].read_bytes(), outputs[1].read_bytes())
            with outputs[0].open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
        self.assertGreater(len(rows), 0)
        self.assertTrue(all(row["route_id"] == "ev_route_alternative" for row in rows))
        road_ids = {row["road_id"] for row in rows}
        self.assertTrue(set(alternative_edges).issubset(road_ids), road_ids)
        self.assertTrue(set(baseline_edges).isdisjoint(road_ids), road_ids)


if __name__ == "__main__":
    unittest.main()
