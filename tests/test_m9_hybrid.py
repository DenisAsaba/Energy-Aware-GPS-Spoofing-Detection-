from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from src.detection.m9_hybrid import align_and_fuse
from src.experiments.m9_error_analysis import _metrics, _write_csv, compare_runs


def _rows(flags, *, vehicle="ev", times=None, eligible=None):
    times = times or list(range(1, len(flags) + 1))
    eligible = eligible or [1] * len(flags)
    return [{"time_s": t, "vehicle_id": vehicle, "eligible": e, "predicted_attack": f}
            for t, f, e in zip(times, flags, eligible)]


class TestM9Hybrid(unittest.TestCase):
    def test_alignment_uses_keys_not_row_order(self):
        m5 = _rows([1, 0], times=[1, 2])
        m8 = _rows([1, 0], times=[2, 1])
        got = align_and_fuse(m5, m8)
        self.assertEqual([(r["time_s"], r["or_prediction"], r["and_prediction"]) for r in got],
                         [(1.0, 1, 0), (2.0, 1, 0)])

    def test_or_and_truth_table(self):
        m5, m8 = _rows([0, 1, 1, 0]), _rows([0, 0, 1, 1])
        got = align_and_fuse(m5, m8)
        self.assertEqual([r["or_prediction"] for r in got], [0, 1, 1, 1])
        self.assertEqual([r["and_prediction"] for r in got], [0, 0, 1, 0])

    def test_m5_fast_suspect_is_immediate_and_short_attack_survives(self):
        got = align_and_fuse(_rows([0, 1, 0]), _rows([0, 0, 0]))
        self.assertEqual(got[1]["m5_fast_suspect"], 1)
        self.assertEqual(got[1]["or_prediction"], 1)
        self.assertEqual(got[1]["m5_event_pending"], 1)

    def test_m8_corroborates_same_or_next_two_joint_observations(self):
        got = align_and_fuse(_rows([1, 0, 0, 0]), _rows([0, 0, 1, 0]))
        self.assertEqual(got[2]["corroborated_now"], 1)
        self.assertEqual(got[2]["corroborated_event_id"], "ev:1")

    def test_event_expires_after_two_following_joint_observations(self):
        got = align_and_fuse(_rows([1, 0, 0, 0, 0]), _rows([0, 0, 0, 1, 0]))
        self.assertEqual(got[3]["m5_event_pending"], 0)
        self.assertEqual(got[3]["corroborated_now"], 0)

    def test_missing_and_ineligible_records_do_not_advance_or_clear(self):
        m5 = _rows([1, 0, 0, 0], times=[1, 2, 3, 4])
        m8 = _rows([0, 0, 1], times=[1, 3, 4])
        got = align_and_fuse(m5, m8)
        at2 = next(r for r in got if r["time_s"] == 2)
        at3 = next(r for r in got if r["time_s"] == 3)
        at4 = next(r for r in got if r["time_s"] == 4)
        self.assertEqual(at2["m5_fast_suspect"], 0)
        self.assertEqual(at2["joint_eligible"], 0)
        self.assertEqual(at3["m5_event_pending"], 1)
        self.assertEqual(at3["corroborated_now"], 0)
        self.assertEqual(at4["corroborated_now"], 1)
        m5[2]["eligible"] = 0
        got = align_and_fuse(m5, _rows([0, 1, 0, 0]))
        self.assertEqual(got[2]["joint_eligible"], 0)

    def test_multiple_vehicles_have_independent_state(self):
        m5 = _rows([1], vehicle="a", times=[1]) + _rows([0, 0], vehicle="b", times=[1, 2])
        m8 = _rows([0], vehicle="a", times=[1]) + _rows([0, 1], vehicle="b", times=[1, 2])
        got = align_and_fuse(m5, m8)
        b2 = next(r for r in got if r["vehicle_id"] == "b" and r["time_s"] == 2)
        self.assertEqual(b2["corroborated_now"], 0)

    def test_corroborated_state_clears_after_three_joint_clean_fixes(self):
        got = align_and_fuse(_rows([1, 0, 0, 0, 0]), _rows([1, 0, 0, 0, 0]))
        self.assertEqual([r["corroborated_suspicion"] for r in got], [1, 1, 1, 0, 0])

    def test_future_invariance(self):
        m5, m8 = _rows([0, 1, 0, 0]), _rows([0, 0, 1, 0])
        prefix = align_and_fuse(m5[:2], m8[:2])
        full = align_and_fuse(m5, m8)
        self.assertEqual(prefix, full[:2])

    def test_deterministic_and_ignores_oracle_or_label_fields(self):
        m5, m8 = _rows([0, 1, 0]), _rows([0, 1, 0])
        plain = align_and_fuse(m5, m8)
        tainted = [{**r, "attack_active": 1, "x_m": 9999, "route_id": "oracle", "future_x": -1}
                   for r in m5]
        self.assertEqual(align_and_fuse(m5, m8), plain)
        self.assertEqual(align_and_fuse(tainted, m8), plain)

    def test_duplicate_keys_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate M5"):
            align_and_fuse(_rows([0, 1], times=[1, 1]), _rows([0], times=[1]))

    def test_metrics_use_eligible_key_match(self):
        rows = [{"time_s": 1, "vehicle_id": "ev", "eligible": 1, "pred": 1},
                {"time_s": 2, "vehicle_id": "ev", "eligible": 0, "pred": 1}]
        score = _metrics(rows, {(1.0, "ev"): 1, (2.0, "ev"): 0}, "pred")
        self.assertEqual((score["tp"], score["fp"], score["eligible_observations"]), (1, 0, 1))

    def test_output_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rows.csv"
            _write_csv(path, [{"x": 1}])
            with self.assertRaises(FileExistsError):
                _write_csv(path, [{"x": 2}])
            with path.open(newline="", encoding="utf-8") as f:
                self.assertEqual(next(csv.DictReader(f))["x"], "1")

    def test_reproducibility_compare(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "a", Path(tmp) / "b"
            a.mkdir(); b.mkdir()
            _write_csv(a / "predictions.csv", [{"time_s": 1, "prediction": 0}])
            _write_csv(b / "predictions.csv", [{"time_s": 1, "prediction": 0}])
            _write_csv(a / "trip_manifest.csv", [{"path": "a"}])
            _write_csv(b / "trip_manifest.csv", [{"path": "b"}])
            self.assertTrue(compare_runs(a, b)["byte_identical"])
            _write_csv(b / "changed.csv", [{"x": 1}])
            self.assertFalse(compare_runs(a, b)["byte_identical"])


if __name__ == "__main__":
    unittest.main()
