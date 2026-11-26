import sys, unittest, json
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from stage04_v4 import build

ROOT = HERE.parent
class Stage04V4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = build(
            ROOT / "inputs" / "han_segments_pilot_2pages.jsonl",
            ROOT / "inputs" / "VIET_Cap01_0186-0251.xlsx",
            ROOT / "inputs" / "baseline_reconstruction.json",
            ROOT / "inputs" / "Semantic_Gold_Review_verified_v2.xlsx",
        )
        cls.groups = cls.result["groups"]

    def test_exact_group_count_and_order(self):
        self.assertEqual(len(self.groups), 12)
        self.assertEqual([g["Han_Start"] for g in self.groups], [0,35,55,213,267,326,337,372,545,647,664,731])

    def test_no_overlap_and_contiguous_aligned_spans(self):
        cursor = 0
        for g in self.groups:
            self.assertEqual(g["Han_Start"], cursor)
            self.assertGreater(g["Han_End"], g["Han_Start"])
            cursor = g["Han_End"]
        self.assertEqual(cursor, 893)

    def test_page3_tail_is_explicitly_unresolved(self):
        tail = self.result["unresolved_han"][0]
        self.assertEqual((tail["Han_Start"], tail["Han_End"]), (893,905))
        self.assertIn("阮金珠", tail["Han_Text"])
        self.assertEqual(len(self.result["unresolved_vi"]), 4)

    def test_545_boundary(self):
        self.assertEqual(self.groups[8]["Han_Start"], 545)
        self.assertTrue(self.groups[8]["Han_Text"].startswith("有印"))

    def test_memorial_day_clause(self):
        g = self.groups[10]
        self.assertEqual((g["Han_Start"],g["Han_End"]),(664,731))
        self.assertIn("諱日亦照",g["Han_Text"])
        self.assertEqual(g["VI_ID"],"Cap_01-VI-0188-003")

    def test_phu_ly_aggregate(self):
        g = self.groups[11]
        self.assertEqual((g["Han_Start"],g["Han_End"]),(731,893))
        self.assertIn("符離",g["Han_Text"])
        self.assertEqual(g["VI_ID"],"Cap_01-VI-0188-004")

    def test_no_wrong_page3_vietnamese_assignments(self):
        ids={g["VI_ID"] for g in self.groups}
        self.assertNotIn("Cap_01-VI-0189-002",ids)
        self.assertNotIn("Cap_01-VI-0189-003",ids)
        self.assertNotIn("Cap_01-VI-0189-004",ids)

    def test_review_workbook_internal_conflict_is_detected(self):
        audit = self.result["review_workbook_audit"]["s4_t1_011_audit"]
        self.assertEqual(audit["recorded_span"], [664,727])
        self.assertTrue(audit["evidence_mentions_664_731"])
        self.assertTrue(audit["conflict"])

    def test_all_labels_remain_unverified(self):
        self.assertTrue(all(g["Label_Target"]=="UNKNOWN" for g in self.groups))
        self.assertTrue(all(g["Assessment_Status"]=="SOURCE_BASED_PROVISIONAL_NOT_GOLD" for g in self.groups))

if __name__ == "__main__":
    unittest.main()
