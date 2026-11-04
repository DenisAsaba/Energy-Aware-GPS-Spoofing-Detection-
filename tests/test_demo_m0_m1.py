"""Tests for the M0/M1 demonstration summary, plots, and GUI options."""

import contextlib
import csv
import io
import math
import tempfile
import unittest
from pathlib import Path

from src.simulation.demo_m0_m1 import read_telemetry, run_demo, summarize_telemetry, _save_plots
from src.simulation.run_sumo import build_sumo_args, run as run_simulation

ROOT = Path(__file__).resolve().parents[1]


class DemoWorkflowTest(unittest.TestCase):
    def test_demo_summary_and_plots_match_generated_csv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "new_run.csv"
            figures = Path(directory) / "figures"
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                result = run_demo(output_path=output, figures_dir=figures)

            with output.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            summary = result["summary"]
            expected_distance = sum(
                math.hypot(float(b["x_m"]) - float(a["x_m"]), float(b["y_m"]) - float(a["y_m"]))
                for a, b in zip(rows, rows[1:])
            )
            self.assertEqual(summary["record_count"], len(rows))
            self.assertEqual(summary["sampled_duration_s"], float(rows[-1]["time_s"]) - float(rows[0]["time_s"]))
            self.assertAlmostEqual(summary["speed_min_mps"], min(float(row["speed_mps"]) for row in rows))
            self.assertAlmostEqual(summary["speed_mean_mps"], sum(float(row["speed_mps"]) for row in rows) / len(rows))
            self.assertAlmostEqual(summary["speed_max_mps"], max(float(row["speed_mps"]) for row in rows))
            self.assertAlmostEqual(summary["sampled_path_distance_m"], expected_distance)
            self.assertEqual(summary["battery_charge_start_wh"], float(rows[0]["battery_charge_wh"]))
            self.assertEqual(summary["battery_charge_end_wh"], float(rows[-1]["battery_charge_wh"]))
            self.assertEqual(summary["battery_capacity_wh"], float(rows[-1]["battery_capacity_wh"]))
            self.assertEqual(summary["energy_total_consumed_wh"], float(rows[-1]["energy_total_consumed_wh"]))
            self.assertEqual(summary["energy_total_regenerated_wh"], float(rows[-1]["energy_total_regenerated_wh"]))
            self.assertEqual(summary["soc_start"], float(rows[0]["soc"]))
            self.assertEqual(summary["soc_end"], float(rows[-1]["soc"]))
            self.assertEqual(len(result["plots"]), 3)
            for plot in result["plots"]:
                self.assertTrue(plot.is_file())
                self.assertGreater(plot.stat().st_size, 1000)
                self.assertTrue(plot.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertIn("Records:", printed.getvalue())
            self.assertIn("Cumulative battery energy consumed:", printed.getvalue())

    def test_missing_battery_fields_are_not_fabricated_or_plotted(self) -> None:
        rows = [
            {"time_s": "0", "vehicle_id": "ev", "x_m": "0", "y_m": "0", "speed_mps": "1"},
            {"time_s": "1", "vehicle_id": "ev", "x_m": "1", "y_m": "0", "speed_mps": "2"},
        ]
        summary = summarize_telemetry(rows)
        self.assertIsNone(summary["battery_charge_start_wh"])
        self.assertIsNone(summary["energy_total_consumed_wh"])
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "minimal.csv"
            csv_path.write_text("time_s,vehicle_id,x_m,y_m,speed_mps\n0,ev,0,0,1\n1,ev,1,0,2\n", encoding="utf-8")
            read_rows = read_telemetry(csv_path)
            plots = _save_plots(read_rows, csv_path, Path(directory) / "figures")
            printed = io.StringIO()
            from src.simulation.demo_m0_m1 import _print_summary
            with contextlib.redirect_stdout(printed):
                _print_summary(csv_path, summary, plots)
        self.assertEqual(len(plots), 2)
        self.assertFalse(any("battery" in path.name for path in plots))
        self.assertNotIn("Battery charge:", printed.getvalue())
        self.assertNotIn("Cumulative battery energy consumed:", printed.getvalue())

    def test_keep_open_is_opt_in_and_requires_gui(self) -> None:
        settings = {"seed": 42, "step_length_s": 1.0, "begin_s": 0, "end_s": 600}
        network = ROOT / "sumo/network/m0.net.xml"
        routes = ROOT / "sumo/routes/m0.rou.xml"
        normal_gui_args = build_sumo_args("sumo-gui", network, routes, settings, gui=True)
        keep_open_args = build_sumo_args("sumo-gui", network, routes, settings, gui=True, keep_open=True)
        self.assertNotIn("--quit-on-end", normal_gui_args)
        self.assertIn("--quit-on-end", keep_open_args)
        self.assertEqual(keep_open_args[keep_open_args.index("--quit-on-end") + 1], "false")
        with self.assertRaisesRegex(ValueError, "requires --gui"):
            build_sumo_args("sumo", network, routes, settings, keep_open=True)

    def test_existing_csv_and_plot_files_are_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            historical_csv = root / "historical.csv"
            historical_csv.write_text("preserve this CSV", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                run_simulation(ROOT / "config/experiment_config.yaml", output_path=historical_csv)
            self.assertEqual(historical_csv.read_text(encoding="utf-8"), "preserve this CSV")

            rows = [
                {"time_s": "0", "vehicle_id": "ev", "x_m": "0", "y_m": "0", "speed_mps": "1"},
                {"time_s": "1", "vehicle_id": "ev", "x_m": "1", "y_m": "0", "speed_mps": "2"},
            ]
            figure_dir = root / "figures"
            figure_dir.mkdir()
            historical_plot = figure_dir / "historical_trajectory_xy.png"
            historical_plot.write_bytes(b"preserve this plot")
            with self.assertRaises(FileExistsError):
                _save_plots(rows, root / "historical.csv", figure_dir)
            self.assertEqual(historical_plot.read_bytes(), b"preserve this plot")


if __name__ == "__main__":
    unittest.main()
