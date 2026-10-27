"""M0/M1 integration test: the seeded EV trip completes and exports repeatable telemetry."""

import csv
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src/simulation"))
import run_sumo  # noqa: E402


class SumosmokeTest(unittest.TestCase):
    def test_ev_trip_completes_and_exports_repeatable_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            outputs = [Path(temp_dir) / f"run_{index}" / "truth.csv" for index in (1, 2)]
            for output_path in outputs:
                result = subprocess.run(
                    [
                        sys.executable,
                        str(PROJECT_ROOT / "src/simulation/run_sumo.py"),
                        "--seed",
                        "42",
                        "--output",
                        str(output_path),
                    ],
                    cwd=PROJECT_ROOT,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
                self.assertIn("Trip completed: vehicle_id=ev_001 timesteps=", result.stderr)
                self.assertTrue(output_path.is_file())
                with output_path.open(newline="", encoding="utf-8") as stream:
                    reader = csv.DictReader(stream)
                    self.assertEqual(reader.fieldnames, run_sumo.CSV_FIELDS)
                    rows = list(reader)
                self.assertGreater(len(rows), 0)
                self.assertEqual(run_sumo.validate_telemetry_csv(output_path)[0], len(rows))

            self.assertEqual(outputs[0].read_bytes(), outputs[1].read_bytes())


if __name__ == "__main__":
    unittest.main()
