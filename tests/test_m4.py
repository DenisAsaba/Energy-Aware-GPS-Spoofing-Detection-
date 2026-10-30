"""Unit and isolation tests for M4 motion, map matching, fusion, evaluation."""
import csv
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"src/sensors"),str(ROOT/"src/mapping"),str(ROOT/"src/fusion"),str(ROOT/"src/experiments")]
import motion, map_matching, sensor_fusion, run_m4


class MotionTests(unittest.TestCase):
    def test_seed_schema_units_and_does_not_change_truth(self):
        truth=ROOT/"data/raw/truth.csv";before=hashlib.sha256(truth.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as d:
            a,b=Path(d)/"a.csv",Path(d)/"b.csv"
            self.assertEqual(motion.generate(truth,a,55,.25,2,.15),83)
            motion.generate(truth,b,55,.25,2,.15)
            self.assertEqual(a.read_bytes(),b.read_bytes())
            with a.open(newline="") as f: rows=list(csv.DictReader(f))
            self.assertEqual(tuple(rows[0]),motion.FIELDS)
            self.assertTrue(all(float(r["speed_mps"])>=0 and 0<=float(r["heading_deg"])<360 for r in rows))
        self.assertEqual(hashlib.sha256(truth.read_bytes()).hexdigest(),before)


class MapMatchingTests(unittest.TestCase):
    def setUp(self):
        self.edges=map_matching.load_network(ROOT/"sumo/network/grid.net.xml")
        self.motion=[{"time_s":"1","trip_id":"t","vehicle_id":"v","speed_mps":"10","heading_deg":"0"},
                     {"time_s":"2","trip_id":"t","vehicle_id":"v","speed_mps":"10","heading_deg":"0"}]
    def test_candidate_geometry_heading_and_no_candidate(self):
        cs=map_matching.candidates(1.6,15,self.edges,0,10,16)
        self.assertEqual(cs[0].edge.edge_id,"A0A1")
        self.assertAlmostEqual(cs[0].distance,0,places=5)
        self.assertEqual(map_matching.candidates(100,100,self.edges,0,5,16),[])
    def test_continuity_prefers_connected_road_and_retains_unmatched_row(self):
        gps=[{"time_s":"1","trip_id":"t","vehicle_id":"v","gps_x_m":"1.6","gps_y_m":"15"},
             {"time_s":"2","trip_id":"t","vehicle_id":"v","gps_x_m":"450","gps_y_m":"498.4"},
             {"time_s":"3","trip_id":"t","vehicle_id":"v","gps_x_m":"100","gps_y_m":"100"}]
        rows=map_matching.match_rows(gps,self.motion[:1]+[{**self.motion[0],"time_s":"2"},{**self.motion[0],"time_s":"3"}],self.edges,30,16)
        self.assertEqual(rows[0]["matched_road_id"],"A0A1")
        self.assertEqual(rows[1]["matched_road_id"],"A1B1")
        self.assertEqual(rows[2]["matched"],"false")
    def test_network_connectivity(self):
        a=map_matching.candidates(1.6,490,self.edges,0,20,16)[0]
        b=map_matching.candidates(20,498.4,self.edges,90,30,16)[0]
        self.assertTrue(math_isfinite(map_matching._network_distance(a,b,self.edges)))


def math_isfinite(v):
    import math
    return math.isfinite(v)


class FusionAndEvaluationTests(unittest.TestCase):
    def test_initializes_at_gps_and_handles_missing_motion_and_gps(self):
        gps=[{"time_s":"1","trip_id":"t","vehicle_id":"v","gps_x_m":"10","gps_y_m":"20"},
             {"time_s":"2","trip_id":"t","vehicle_id":"v","gps_x_m":"","gps_y_m":""},
             {"time_s":"3","trip_id":"t","vehicle_id":"v","gps_x_m":"12","gps_y_m":"20"}]
        rows=sensor_fusion.fuse(gps,[],3,1.5)
        self.assertEqual(len(rows),3);self.assertEqual(float(rows[0]["fused_x_m"]),10)
        self.assertEqual(rows[1]["gps_used"],"false");self.assertEqual(float(rows[1]["fused_x_m"]),10)
        self.assertGreater(float(rows[2]["fused_x_m"]),10)
        self.assertLess(float(rows[2]["fused_x_m"]),12)
    def test_evaluation_metrics(self):
        truth=[{"time_s":"1","trip_id":"t","vehicle_id":"v","x_m":"0","y_m":"0"},
               {"time_s":"2","trip_id":"t","vehicle_id":"v","x_m":"0","y_m":"0"}]
        est=[{"time_s":"1","trip_id":"t","vehicle_id":"v","x":"3","y":"4"},
             {"time_s":"2","trip_id":"t","vehicle_id":"v","x":"0","y":"0"}]
        got=run_m4.metrics(truth,est,"x","y")
        self.assertEqual(got["valid_records"],2);self.assertEqual(got["mean_error_m"],2.5)
        self.assertAlmostEqual(got["rmse_m"],(12.5)**.5)

    def test_estimators_ignore_truth_and_attack_label_columns(self):
        gps={"time_s":"1","trip_id":"t","vehicle_id":"v","gps_x_m":"1.6","gps_y_m":"15",
             "x_m":"999999","y_m":"-999999","attack_active":"true"}
        motion_row={"time_s":"1","trip_id":"t","vehicle_id":"v","speed_mps":"10","heading_deg":"0",
                    "x_m":"-999999","attack_active":"false"}
        edges=map_matching.load_network(ROOT/"sumo/network/grid.net.xml")
        match1=map_matching.match_rows([gps],[motion_row],edges)
        fused1=sensor_fusion.fuse([gps],[motion_row],3,1.5)
        gps["x_m"],gps["y_m"],gps["attack_active"]="-42","42","false"
        motion_row["x_m"],motion_row["attack_active"]="42","true"
        self.assertEqual(match1,map_matching.match_rows([gps],[motion_row],edges))
        self.assertEqual(fused1,sensor_fusion.fuse([gps],[motion_row],3,1.5))
        self.assertTrue({"x_m","y_m","attack_active"}.isdisjoint(match1[0]))
        self.assertTrue({"x_m","y_m","attack_active"}.isdisjoint(fused1[0]))

    def test_complete_pipeline_preserves_all_m0_m3_csv_inputs(self):
        legacy=sorted((ROOT/"data/raw").glob("*.csv"))+sorted((ROOT/"data/processed").glob("*.csv"))+sorted((ROOT/"data/attacks").glob("*.csv"))
        before={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in legacy}
        report=run_m4.run(ROOT/"config/experiment_config.yaml","all","all")
        after={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in legacy}
        self.assertEqual(before,after)
        self.assertEqual(set(report["scenarios"]),{"normal","offset","jump","drift","route_deviation"})
        output=ROOT/"data/m4/estimates"
        self.assertTrue((output/"fused_normal.csv").is_file())
        metrics=json.loads((ROOT/"results/tables/m4_metrics.json").read_text(encoding="utf-8"))
        self.assertTrue(metrics["ground_truth_used_only_for_evaluation"])


if __name__=="__main__":unittest.main()
