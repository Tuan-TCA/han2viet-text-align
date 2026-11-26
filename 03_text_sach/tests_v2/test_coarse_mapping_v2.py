"""Unit and integration tests for Coarse Mapping V2 (multi-workbook, cross-book, source integrity)."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import Mock
import uuid

STAGE = Path(__file__).resolve().parents[1]
ROOT = STAGE.parent
for _p in (str(STAGE / "scripts_v2"), str(STAGE / "scripts"), str(ROOT / "pipeline" / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from api_integration import ALIGN, SEPARATE
from preprocess_v2 import (
    WORKBOOK_SPECS,
    analyze_page051_and_book6_anchors,
    cap_coord_page,
    cap_ordinal_page,
    cap_pdf_page_from_coord,
    load_sources_v2,
    verify_frozen_s4_and_han,
    verify_reversible_t1,
)
from refine_coarse_mapping_v2 import (
    CoarseClientV2,
    choices_v2,
    collect_v2,
    cross_book_window,
    structural_coord,
)
from refine_coarse_mapping import reconcile


class TempFolder:
    def __init__(self):
        base = Path(r"C:\Users\Tuan TCA\.gemini\antigravity-cli\brain\2c0813f8-5d47-4ca3-b7a4-6024a57ac49f\scratch\tmp_v2_tests")
        base.mkdir(parents=True, exist_ok=True)
        self.path = base / uuid.uuid4().hex
        self.path.mkdir(parents=True, exist_ok=True)

    def __enter__(self) -> Path:
        return self.path

    def __exit__(self, *args):
        shutil.rmtree(self.path, ignore_errors=True)


class CoarseMappingV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.han_pages, cls.viet_segments, cls.mapping_rows, cls.wb_audits = load_sources_v2()
        cls.s4_audit = verify_frozen_s4_and_han(cls.han_pages)
        cls.transitions = analyze_page051_and_book6_anchors(cls.han_pages, cls.viet_segments, cls.mapping_rows)

    def test_multi_workbook_inventory_and_namespace_integrity(self):
        self.assertEqual(len(self.han_pages), 145)
        self.assertEqual(self.s4_audit["total_segments"], 2808)
        self.assertEqual(self.s4_audit["total_source_chars"], 53328)
        self.assertEqual(len(self.viet_segments), 2054)  # 685 + 991 + 378

        by_book = {}
        for v in self.viet_segments:
            by_book.setdefault(v["book_id"], []).append(v)
        self.assertEqual(len(by_book["Cap_01_Book_III"]), 685)
        self.assertEqual(len(by_book["Book_V"]), 991)
        self.assertEqual(len(by_book["Book_VI"]), 378)

        # Preserve Cap_02_VI namespace and associate with Cap_02
        self.assertTrue(all(v["cap"] == "Cap_02" for v in by_book["Book_VI"]))
        self.assertTrue(all(v["id"].startswith("Cap_02_VI-VI-") for v in by_book["Book_VI"]))
        self.assertTrue(all(v["id"].startswith("Cap_02-VI-") for v in by_book["Book_V"]))

        # Zero ID collisions across entire corpus
        all_ids = [v["id"] for v in self.viet_segments]
        self.assertEqual(len(all_ids), len(set(all_ids)))

        # Book V precedes Book VI in Cap_02 reading order
        cap02_books = [v["book_id"] for v in self.viet_segments if v["cap"] == "Cap_02"]
        first_b6 = cap02_books.index("Book_VI")
        self.assertTrue(all(b == "Book_V" for b in cap02_books[:first_b6]))
        self.assertTrue(all(b == "Book_VI" for b in cap02_books[first_b6:]))

    def test_page_coordinate_distinction_and_continuity(self):
        b5_audit = self.wb_audits["VIET_0001-0105"]
        b6_audit = self.wb_audits["VIET_0405-0439"]
        self.assertEqual(b5_audit["pdf_page_range"], [1, 105])
        self.assertEqual(b5_audit["printed_page_range"], [304, 408])
        self.assertEqual(b5_audit["book_local_page_range"], [1, 105])
        self.assertEqual(b5_audit["cap_ordinal_page_range"], [1, 105])

        self.assertEqual(b6_audit["pdf_page_range"], [405, 439])
        self.assertEqual(b6_audit["printed_page_range"], [409, 443])
        self.assertEqual(b6_audit["book_local_page_range"], [1, 35])
        self.assertEqual(b6_audit["cap_ordinal_page_range"], [106, 140])

        # Coordinate round-trip and seamless transition 105 -> 405
        self.assertEqual(cap_coord_page("Cap_02", 105), 105)
        self.assertEqual(cap_coord_page("Cap_02", 405), 106)
        self.assertEqual(cap_pdf_page_from_coord("Cap_02", 105), 105)
        self.assertEqual(cap_pdf_page_from_coord("Cap_02", 106), 405)
        self.assertEqual(cap_ordinal_page("Cap_01", 186), 1)
        self.assertEqual(cap_ordinal_page("Cap_02", 439), 140)

        # Structural check across 50 -> 51 -> 52 has zero synthetic gap
        rows = [
            {"Han_Page": 50, "B2_Range": [104, 105]},
            {"Han_Page": 51, "B2_Range": [105, 405]},
            {"Han_Page": 52, "B2_Range": [405, 406]},
        ]
        st = structural_coord(rows, "B2_Range", "Cap_02")
        self.assertEqual(st["gap_pages"], 0)
        self.assertEqual(st["backward"], 0)
        self.assertEqual(st["mean_width"], 2.0)

    def test_reversible_t1_across_all_books(self):
        for v in self.viet_segments:
            self.assertTrue(
                verify_reversible_t1(v["text_original"], v["text_t1"], v["normalized_source_spans"]),
                msg=f"Failed T1 round-trip for {v['id']}",
            )

    def test_page051_cross_book_and_intra_s4_transition(self):
        p51 = self.transitions["page_051_transition"]
        self.assertEqual(p51["right_hand_book_v"]["global_raw_span"], [40741, 40805])
        self.assertEqual(p51["book_vi_heading_column"]["global_raw_span"], [40805, 40812])
        self.assertEqual(p51["book_vi_heading_column"]["han_text"], "撫邊雜錄卷之六")
        self.assertEqual(p51["book_vi_heading_column"]["containing_s4_id"], "Cap_02-051-052-S4-0006")
        self.assertEqual(p51["left_hand_book_vi_prose"]["intra_s4_prose_start_offset"], 40812)
        self.assertFalse(p51["left_hand_book_vi_prose"]["forced_to_s4_boundary"])
        self.assertEqual(
            p51["left_hand_book_vi_prose"]["cross_page_to_052_segment"]["id_zh"],
            "Cap_02-051-052-S4-0012",
        )

        # Cross-book window at seam selects 5 Book V closing + 5 Book VI opening segments
        cap02_pool = [v for v in self.viet_segments if v["cap"] == "Cap_02"]
        seam = sum(1 for v in cap02_pool if v["book_id"] == "Book_V")
        win = cross_book_window(cap02_pool, seam, size=10, shift=0)
        self.assertEqual(len(win), 10)
        self.assertEqual([v["book_id"] for v in win], ["Book_V"] * 5 + ["Book_VI"] * 5)
        self.assertEqual(win[4]["id"], "Cap_02-VI-0105-018")
        self.assertEqual(win[5]["id"], "Cap_02_VI-VI-0405-003")

        # Cross-book anchor choice includes all 19 Book V p.105 + 8 Book VI p.405 segments = 27
        opts = choices_v2([], cap02_pool, 105.5, [105, 106], "Cap_02", seam_index=seam)
        self.assertEqual(opts[0]["pdf_range"], [105, 405])
        self.assertEqual(len(opts[0]["ids"]), 27)

        # Monotone reconciliation across 50 -> 51 -> 52
        p50 = [{"range": [104, 105], "adjusted": 1.8}]
        p52 = [{"range": [104, 105], "adjusted": 9.0}, {"range": [106, 107], "adjusted": 2.5}]
        solved = reconcile([p50, opts, p52])
        self.assertEqual(solved[1]["range"], [105, 106])
        self.assertEqual(solved[2]["range"], [106, 107])

    def test_http_429_backoff_and_exact_cache_verification(self):
        with TempFolder() as tmp:
            cfg = {"api_timeout": 10}
            c = CoarseClientV2(tmp, cfg, live=True, api_delay=0.0, api_retries=2)
            c.token = "secret_test_token_xyz"
            # Forbidden Separate call
            with self.assertRaises(ValueError):
                c.call(SEPARATE, {"text": "甲"})

            # 429 followed by 200 succeeds via bounded retry and redacts token
            r429 = Mock(status_code=429, text='{"code":"000429"}', headers={"Retry-After": "0"})
            r200 = Mock(
                status_code=200,
                text='{"is_success":true,"code":"000000","note":"secret_test_token_xyz","data":{"result":[]}}',
                headers={},
            )
            c.session.post = Mock(side_effect=[r429, r200])
            payload = {"han": "物產之美", "vi": "Những vật sản quý."}
            res = c.call(ALIGN, payload)
            self.assertEqual(res["status"], "ok")
            self.assertEqual(c.http_429_count, 1)
            self.assertEqual(c.retries_used, 1)
            self.assertIsNone(c.halt)
            log_text = (tmp / "requests.jsonl").read_text(encoding="utf-8")
            self.assertNotIn("secret_test_token_xyz", log_text)
            c.close()

            # Exact-payload cache hit offline
            c2 = CoarseClientV2(tmp, cfg, live=False, api_delay=0.0, api_retries=1)
            res2 = c2.call(ALIGN, payload)
            self.assertEqual(res2["status"], "ok")
            self.assertEqual(c2.hits, 1)
            c2.close()


if __name__ == "__main__":
    unittest.main()
