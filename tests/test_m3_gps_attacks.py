"""M3 attack behavior, reproducibility, route and separation regressions."""

import csv
import hashlib
import tempfile
import unittest
from pathlib import Path

from src.attacks.gps_attacks import (
    GPS_FIELDS, LABEL_FIELDS, build_alternative_network, evaluate_m3,
    generate_attack, validate_alternative_route,
)
from src.sensors.gps_normal import evaluate_observations

ROOT = Path(__file__).resolve().parents[1]


class M3GpsAttackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp.name)
        self.truth = self.tmp / "truth.csv"
        self.truth.write_text(
            "time_s,vehicle_id,x_m,y_m,speed_mps\n"
            "1,ev,0,0,3\n2,ev,1,0,3\n3,ev,2,0,3\n"
            "4,ev,3,0,3\n5,ev,4,0,3\n6,ev,5,0,3\n", encoding="utf-8")
        self.truth_before = self.truth.read_bytes()
        self.settings = {"attack_id": "test", "onset_s": 2, "duration_s": 3,
                         "magnitude_m": 10, "direction_deg": 90,
                         "rate_mps": 2, "max_displacement_m": 3}

    def tearDown(self):
        self.temp.cleanup()

    def _make(self, name, kind, **overrides):
        path = self.tmp / name
        settings = {**self.settings, **overrides}
        labels = generate_attack(self.truth, path, attack_type=kind, settings=settings,
                                 noise_std_m=0, seed=17)[1]
        with path.open(encoding="utf-8", newline="") as f:
            gps_reader = csv.DictReader(f); gps = list(gps_reader)
            self.assertEqual(tuple(gps_reader.fieldnames), GPS_FIELDS)
        with labels.open(encoding="utf-8", newline="") as f:
            label_reader = csv.DictReader(f); label_rows = list(label_reader)
            self.assertEqual(tuple(label_reader.fieldnames), LABEL_FIELDS)
        self.assertTrue({"attack_type", "attack_active", "attack_intensity"}.isdisjoint(GPS_FIELDS))
        return path, gps, label_rows

    def test_constant_offset_only_during_half_open_window(self):
        _, rows, labels = self._make("offset.csv", "offset")
        self.assertEqual([r["attack_active"] for r in labels], ["0", "1", "1", "1", "0", "0"])
        self.assertEqual([(float(r["gps_x_m"]), float(r["gps_y_m"])) for r in rows],
                         [(0, 0), (11, 0), (12, 0), (13, 0), (4, 0), (5, 0)])
        self.assertEqual([float(r["attack_intensity"]) for r in labels], [0, 10, 10, 10, 0, 0])

    def test_jump_is_sudden_and_recovers_at_window_end(self):
        _, rows, labels = self._make("jump.csv", "jump")
        self.assertEqual([r["attack_active"] for r in labels], ["0", "1", "1", "1", "0", "0"])
        self.assertEqual([float(r["gps_x_m"]) for r in rows], [0, 11, 12, 13, 4, 5])

    def test_drift_grows_linearly_and_caps(self):
        _, rows, labels = self._make("drift.csv", "drift", max_displacement_m=3, direction_deg=90)
        self.assertEqual([float(r["gps_x_m"]) for r in rows], [0, 3, 5, 6, 4, 5])
        self.assertEqual([float(r["attack_intensity"]) for r in labels], [0, 2, 3, 3, 0, 0])

    def test_same_seed_reproduces_and_truth_is_unchanged(self):
        a = self.tmp / "a.csv"; b = self.tmp / "b.csv"
        generate_attack(self.truth, a, attack_type="offset", settings=self.settings, noise_std_m=2, seed=21)
        generate_attack(self.truth, b, attack_type="offset", settings=self.settings, noise_std_m=2, seed=21)
        self.assertEqual(a.read_bytes(), b.read_bytes())
        self.assertEqual(self.truth.read_bytes(), self.truth_before)

    def test_evaluation_uses_truth_metrics_and_separate_plots(self):
        gps, _, _ = self._make("offset_eval.csv", "offset")
        labels = self.tmp / "offset_eval_labels.csv"
        metrics = evaluate_m3(self.truth, gps, labels, self.tmp / "plots", "offset_test")
        self.assertEqual(metrics["matched_observations"], 6)
        self.assertEqual(metrics["active_attack_observations"], 3)
        self.assertEqual(metrics["mean_error_m"], 5.0)
        self.assertTrue((self.tmp / "plots/offset_test_trajectory.png").is_file())
        self.assertTrue((self.tmp / "plots/offset_test_error_time.png").is_file())

    def test_separate_alternative_network_route_valid_and_m0_inputs_unchanged(self):
        m0_paths = [ROOT / "sumo/network/m0.nod.xml", ROOT / "sumo/network/m0.edg.xml",
                    ROOT / "sumo/network/m0.net.xml", ROOT / "sumo/routes/m0.rou.xml"]
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in m0_paths}
        network = ROOT / "sumo/network/m3.net.xml"
        if not network.exists(): build_alternative_network(ROOT)
        validate_alternative_route(network, ROOT / "sumo/routes/m3_route_deviation.rou.xml",
                                   "route_alternative", ["road_alt_0", "road_alt_1"])
        self.assertTrue(network.is_file())
        self.assertEqual({p: hashlib.sha256(p.read_bytes()).hexdigest() for p in m0_paths}, before)

    def test_existing_m0_m2_outputs_and_truth_are_preserved(self):
        protected = [ROOT / "sumo/network/m0.nod.xml", ROOT / "sumo/network/m0.edg.xml",
                     ROOT / "sumo/network/m0.net.xml", ROOT / "sumo/routes/m0.rou.xml"]
        for directory in (ROOT / "data/raw", ROOT / "data/processed", ROOT / "reports/m2",
                          ROOT / "results/figures/m0_m1"):
            if directory.exists(): protected.extend(p for p in directory.rglob("*") if p.is_file())
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
        generate_attack(self.truth, self.tmp / "preservation.csv", attack_type="jump",
                        settings=self.settings, noise_std_m=0, seed=17)
        after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
        self.assertEqual(after, before)

    def test_duplicate_output_refused(self):
        path = self.tmp / "once.csv"
        generate_attack(self.truth, path, attack_type="offset", settings=self.settings,
                        noise_std_m=0, seed=1)
        with self.assertRaises(FileExistsError):
            generate_attack(self.truth, path, attack_type="offset", settings=self.settings,
                            noise_std_m=0, seed=1)


if __name__ == "__main__":
    unittest.main()
