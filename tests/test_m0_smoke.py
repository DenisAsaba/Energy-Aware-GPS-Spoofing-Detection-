"""Integration smoke test for the local M0 SUMO EV trip."""

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class M0SmokeTest(unittest.TestCase):
    def test_python_runner_completes_ev_trip(self) -> None:
        result = subprocess.run(
            [sys.executable, "src/simulation/run_sumo.py", "--config", "config/experiment_config.yaml"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("Completed EV run: vehicle=ev_001 timesteps=", result.stderr)
        self.assertTrue((ROOT / "results/m0/run_metadata.yaml").is_file())


if __name__ == "__main__":
    unittest.main()
