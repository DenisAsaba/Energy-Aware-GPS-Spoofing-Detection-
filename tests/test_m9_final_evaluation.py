from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from src.experiments.m9_final_evaluation import (
    _aggregate, _matrix, _prediction_rows, _validate_preflight, _write_csv,
)


ROOT = Path(__file__).resolve().parents[1]


class M9FinalEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = yaml.safe_load((ROOT / "config/m9_analysis.yaml").read_text(encoding="utf-8"))

    def test_approved_matrix_exact_ids_and_short_jumps(self) -> None:
        cases = _matrix(self.config)
        self.assertEqual(len(cases), 12)
        jumps = {(c["magnitude_m"], c["duration_s"]) for c in cases if c["attack_type"] == "jump"}
        self.assertEqual(jumps, {(30.0, 1.0), (30.0, 5.0), (60.0, 1.0), (60.0, 5.0)})
        self.assertFalse(any(c["duration_s"] == 8 for c in cases if c["attack_type"] == "jump"))
        self.assertEqual(_validate_preflight(self.config, ROOT)["counts"]["attack_events"], 72)

    def test_stage1_attack_conditions_remain_frozen(self) -> None:
        self.assertEqual(self.config["attacks"]["jump"]["duration_s"], 8)
        self.assertEqual(self.config["attacks"]["offset"]["duration_s"], 25)
        self.assertEqual(self.config["attacks"]["drift"]["rate_mps"], 1.0)

    def test_profile_allocation_has_two_seeds_each(self) -> None:
        result = _validate_preflight(self.config, ROOT)
        self.assertEqual(result["profile_assignment"], {
            "urban_turns_light": [2501, 2504],
            "urban_stop_restart": [2502, 2505],
            "urban_brake_accel": [2503, 2506],
        })
        self.assertEqual(result["counts"]["normal_control_datasets"], 6)
        self.assertEqual(result["counts"]["instances_per_case_overall"], 6)

    def test_keyed_prediction_rows_retain_fusion_streams(self) -> None:
        m5 = [{"time_s": 1, "vehicle_id": "v1", "eligible": 1, "predicted_attack": 1}]
        m8 = [{"time_s": 1, "vehicle_id": "v1", "eligible": 1, "predicted_attack": 0}]
        fused = [{"time_s": 1, "vehicle_id": "v1", "joint_eligible": 1,
            "m5_prediction": 1, "m8_prediction": 0, "or_prediction": 1,
            "and_prediction": 0, "m5_fast_suspect": 1,
            "m8_corroboration": 0, "corroborated_suspicion": 0}]
        rows = _prediction_rows(m5, m8, fused)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["both_prediction"], 0)
        self.assertEqual(rows[0]["m5_only_prediction"], 1)
        self.assertEqual(rows[0]["or_prediction"], 1)
        self.assertEqual(rows[0]["and_prediction"], 0)
        self.assertEqual(rows[0]["m5_fast_suspect"], 1)
        self.assertEqual(rows[0]["corroborated_suspicion"], 0)

    def test_write_csv_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "rows.csv"
            _write_csv(path, [{"a": 1}])
            with self.assertRaises(FileExistsError):
                _write_csv(path, [{"a": 2}])

    def test_attack_aggregate_names_inactive_rate_without_calling_it_normal_fpr(self) -> None:
        rows = [{"profile": "urban_turns_light", "attack_type": "jump", "magnitude_or_rate": 30.0,
            "duration_s": 1.0, "detector": "M5", "tp": 1, "fp": 2, "tn": 8, "fn": 0,
            "active_event": 1, "event_detected": 1, "detection_delay_s": 0.0,
            "eligible_observations": 11, "post_attack_alerts": 0}]
        result = _aggregate(rows, ("profile", "attack_type", "magnitude_or_rate", "duration_s", "detector"))[0]
        self.assertAlmostEqual(result["inactive_observation_fpr"], 0.2)
        self.assertNotIn("normal_fpr", result)


if __name__ == "__main__":
    unittest.main()
