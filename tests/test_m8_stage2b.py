"""Frozen Stage 2B matrix, scoring and paired-statistic tests."""
import unittest
from pathlib import Path
import yaml
from src.experiments.m8_stage2b import _condition_summaries, _matrix, _paired_comparisons, _verify_frozen

ROOT=Path(__file__).resolve().parents[1]


class M8Stage2BTests(unittest.TestCase):
    def setUp(self):
        self.config=yaml.safe_load((ROOT/"config/m8_stage2b.yaml").read_text(encoding="utf-8"))

    def test_frozen_policy_thresholds_and_reserved_seeds_match_approved_values(self):
        verified=_verify_frozen(ROOT,self.config)
        self.assertEqual(verified["reserved_final_seeds"],[1301,1302])
        self.assertEqual(verified["m8_persistence"],{"trigger_count":2,"trigger_window":5,"clear_after_clean_fixes":3})
        self.assertFalse(verified["calibration_validation_overlap"])

    def test_attack_matrix_covers_supported_types_intensities_and_durations(self):
        cases=_matrix(self.config)
        self.assertEqual(len(cases),12)
        self.assertEqual({row["attack_type"] for row in cases},{"offset","jump","drift"})
        self.assertEqual(len({row["case_id"] for row in cases}),12)
        self.assertEqual({row["duration_s"] for row in cases if row["attack_type"]=="jump"},{1.0,5.0})

    def test_condition_summary_separates_observation_and_event_metrics(self):
        rows=[]
        for seed,det,tp,fp,tn,fn,event,post in ((1301,"M5",1,1,8,2,1,1),(1301,"M8",2,1,8,1,1,2),
                                                 (1302,"M5",0,2,7,3,0,0),(1302,"M8",1,1,8,2,1,1)):
            rows.append({"scenario_type":"urban_turns_light","attack_type":"jump","attack_magnitude":30,
                         "attack_duration_s":1,"detector":det,"tp":tp,"fp":fp,"tn":tn,"fn":fn,
                         "attack_event_detected":event,"detection_delay_s":1 if event else "",
                         "post_attack_eligible_observations":10,"post_attack_alerts":post,"alerts_per_trip":1,
                         "sumo_seed":seed,"trip_id":f"t{seed}"})
        summary=_condition_summaries(rows)
        m8=next(r for r in summary if r["detector"]=="M8")
        self.assertEqual((m8["tp"],m8["fp"],m8["tn"],m8["fn"]),(3,2,16,3))
        self.assertEqual(m8["attack_event_count"],2)
        self.assertEqual(m8["active_event_detection_rate"],1.0)
        self.assertEqual(m8["post_attack_alert_rate"],0.15)

    def test_paired_comparison_uses_trip_pairs_not_observations(self):
        rows=[]
        for seed,m5,m8 in ((1301,.4,.6),(1302,.2,.5)):
            for detector,value in (("M5",m5),("M8",m8)):
                rows.append({"trip_id":f"s{seed}","sumo_seed":seed,"scenario_type":"urban_turns_light",
                             "attack_type":"offset","attack_magnitude":30,"attack_duration_s":10,
                             "detector":detector,"f1":value})
        result=next(r for r in _paired_comparisons(rows) if r["metric"]=="f1")
        self.assertEqual(result["n_paired_trips"],2)
        self.assertEqual(result["n_distinct_seeds"],2)
        self.assertAlmostEqual(result["paired_difference_m8_minus_m5_mean"],.25)
        self.assertEqual(result["ci95_low"],"")


if __name__=="__main__":
    unittest.main()
