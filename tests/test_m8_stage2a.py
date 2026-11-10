"""Tests for M8 Stage 2A scenario input generation."""
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from src.experiments.m8_stage2a_scenarios import SCENARIOS, build_scenario_inputs


class M8Stage2AScenarioTests(unittest.TestCase):
    def test_scenarios_cover_turns_stops_speed_and_traffic(self):
        self.assertEqual(set(SCENARIOS), {"urban_turns_light", "urban_stop_restart", "urban_brake_accel"})
        self.assertTrue(all(len(v["route"]) >= 4 for v in SCENARIOS.values()))
        self.assertNotEqual(SCENARIOS["urban_turns_light"]["speed_factor"], SCENARIOS["urban_brake_accel"]["speed_factor"])
        self.assertEqual(SCENARIOS["urban_turns_light"]["traffic"], 0)
        self.assertGreater(SCENARIOS["urban_brake_accel"]["traffic"], SCENARIOS["urban_stop_restart"]["traffic"])

    def test_builds_connected_network_and_seeded_scenario_routes(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = build_scenario_inputs(Path(tmp) / "one", "urban_stop_restart", 2101)
            second = build_scenario_inputs(Path(tmp) / "two", "urban_stop_restart", 2101)
            self.assertTrue(first["network"].is_file())
            root = ET.parse(first["routes"]).getroot()
            self.assertEqual(len(root.findall("vehicle")), 6)
            ev = root.find("vehicle[@id='ev_001']")
            self.assertIsNotNone(ev.find("stop"))
            self.assertEqual(first["routes"].read_bytes(), second["routes"].read_bytes())
            self.assertTrue(root.find("route[@id='evroute']").get("edges").startswith("west east"))

    def test_unknown_scenario_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(ValueError, "unknown"):
            build_scenario_inputs(Path(tmp), "m7", 1)


if __name__ == "__main__":
    unittest.main()
