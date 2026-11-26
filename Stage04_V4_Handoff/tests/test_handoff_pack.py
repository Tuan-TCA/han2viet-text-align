from pathlib import Path
import json, re, unittest, collections
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "inputs"
DATA = ROOT / "candidate_data"

def parse_pages(path, cap):
    text = path.read_text(encoding="utf-8-sig")
    matches = list(re.finditer(rf"(?m)^=== {re.escape(cap)} \| PAGE (\d{{3}}) ===\s*\n", text))
    out = {}
    for i, m in enumerate(matches):
        page = int(m.group(1))
        start = m.end()
        end = matches[i+1].start() if i+1 < len(matches) else len(text)
        out[page] = text[start:end].strip()
    return text, out

class HandoffPackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cap1_file, cls.cap1_pages = parse_pages(INPUT/"Cap_01_HAN_all_pages.txt", "Cap_01")
        cls.cap2_file, cls.cap2_pages = parse_pages(INPUT/"Cap_02_HAN_all_pages.txt", "Cap_02")
        cls.cap1_raw = "".join(cls.cap1_pages[p] for p in sorted(cls.cap1_pages))
        cls.cap2_raw = "".join(cls.cap2_pages[p] for p in sorted(cls.cap2_pages))
        cls.global_raw = cls.cap1_raw + cls.cap2_raw
        cls.segments = [json.loads(x) for x in (INPUT/"han_segments_full.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        cls.extension = json.loads((DATA/"page3_4_candidate_extension.json").read_text(encoding="utf-8"))
        cls.extended = json.loads((DATA/"v4_candidate_extended.json").read_text(encoding="utf-8"))
        cls.fresh = [json.loads(x) for x in (DATA/"fresh_benchmark_seed.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]

    def test_full_raw_char_counts(self):
        self.assertEqual(len(self.cap1_pages), 53)
        self.assertEqual(len(self.cap2_pages), 92)
        self.assertEqual(len(self.cap1_raw), 23738)
        self.assertEqual(len(self.cap2_raw), 29590)
        self.assertEqual(len(self.global_raw), 53328)

    def test_all_s4_global_offsets_round_trip(self):
        for seg in self.segments:
            a,b = seg["global_raw_span"]
            self.assertEqual(self.global_raw[a:b], seg["text_original"], seg["id_zh"])
            self.assertEqual(b-a, len(seg["text_original"]), seg["id_zh"])

    def test_all_source_file_spans_round_trip(self):
        for seg in self.segments:
            source_text = self.cap1_file if seg["id_zh"].startswith("Cap_01-") else self.cap2_file
            parts = [source_text[x["file_span"][0]:x["file_span"][1]] for x in seg["source"]]
            self.assertEqual("".join(parts), seg["text_original"], seg["id_zh"])

    def test_page3_page4_offsets(self):
        self.assertEqual((sum(len(self.cap1_pages[p]) for p in [1,2]), sum(len(self.cap1_pages[p]) for p in [1,2,3])), (905,1371))
        self.assertEqual(sum(len(self.cap1_pages[p]) for p in [1,2,3,4]),1764)

    def test_extension_spans_are_contiguous_and_reconstruct(self):
        groups=self.extension["groups"]
        cursor=893
        for g in groups:
            self.assertEqual(g["start"],cursor,g["id"])
            self.assertEqual(self.global_raw[g["start"]:g["end"]],g["han_text"],g["id"])
            cursor=g["end"]
        self.assertEqual(cursor,1499)

    def test_extension_vi_ids_exist_and_labels_are_unknown(self):
        wb=load_workbook(INPUT/"VIET_Cap01_0186-0251.xlsx",read_only=True,data_only=True)
        ws=wb["CAU_VIET"]; headers=[c.value for c in ws[1]]
        ids=set()
        for row in ws.iter_rows(min_row=2,values_only=True):
            rec=dict(zip(headers,row))
            if rec.get("id_vi"): ids.add(str(rec["id_vi"]))
        for g in self.extension["groups"]:
            for vid in g["vi_ids"]:
                self.assertIn(vid,ids)
            self.assertEqual(g["label_target"],"UNKNOWN")
            self.assertEqual(g["reviewer_label"],"")

    def test_special_s4_splits_are_logged(self):
        groups={g["id"]:g for g in self.extension["groups"]}
        self.assertTrue(any(x["span"]==[881,905] for x in groups["EXT-001"]["split_inside_s4_unit"]))
        self.assertTrue(any(x["span"]==[1397,1411] for x in groups["EXT-005"]["split_inside_s4_unit"]))
        self.assertTrue(any(x["span"]==[1397,1411] for x in groups["EXT-006"]["split_inside_s4_unit"]))

    def test_extended_v4_is_contiguous_and_not_full_corpus(self):
        cursor=0
        for g in self.extended["groups"]:
            self.assertEqual(g["Han_Start"],cursor)
            self.assertEqual(self.global_raw[g["Han_Start"]:g["Han_End"]],g["Han_Text"])
            self.assertEqual(g["Label_Target"],"UNKNOWN")
            cursor=g["Han_End"]
        self.assertEqual(cursor,1499)
        self.assertEqual(self.extended["coverage"]["next_unprocessed_offset"],1499)

    def test_current_review_files_are_not_gold(self):
        wb=load_workbook(INPUT/"Semantic_Gold_Review_verified_v2.xlsx",read_only=True,data_only=True)
        ws=wb["API_Row_Review"]; headers=[c.value for c in ws[1]]
        rows=[dict(zip(headers,r)) for r in ws.iter_rows(min_row=2,values_only=True)]
        self.assertEqual(len(rows),15)
        self.assertEqual(sum(bool(r.get("Reviewer_Label")) for r in rows),0)
        counts=collections.Counter(r.get("Proposed_Label") for r in rows)
        self.assertEqual((counts["TRUE"],counts["FALSE"],counts["UNKNOWN"]),(5,7,3))

    def test_fresh_windows_have_context_and_are_disjoint(self):
        seen={}
        for rec in self.fresh:
            cap=rec["cap"]
            for page in rec["han_pages"]:
                self.assertNotIn((cap,page),seen)
                seen[(cap,page)]=rec["window"]
            self.assertEqual(len(rec["page_contexts"]),2)
            self.assertTrue(rec["ordered_unique_viet"])
            self.assertTrue(rec["ordered_unique_vi_ids"])
            self.assertTrue(all(x.get("raw") for x in rec["page_contexts"]))

    def test_expected_fresh_window_list(self):
        expected={"Cap_01-027-028","Cap_01-047-048","Cap_01-051-052","Cap_02-009-010","Cap_02-026-027","Cap_02-047-048"}
        self.assertEqual({x["window"] for x in self.fresh},expected)

if __name__ == "__main__":
    unittest.main()
