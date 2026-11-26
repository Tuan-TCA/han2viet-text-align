"""End-to-end acceptance criteria verification for Coarse Mapping V2 artifacts."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import unittest

from openpyxl import load_workbook

STAGE = Path(__file__).resolve().parents[1]
ROOT = STAGE.parent
V1_DIR = STAGE / "artifacts" / "coarse_mapping"
V2_DIR = STAGE / "artifacts" / "coarse_mapping_v2"
PROD_DIR = STAGE / "artifacts" / "production"
BASELINE_HASHES = Path(
    r"C:\Users\Tuan TCA\.gemini\antigravity-cli\brain\2c0813f8-5d47-4ca3-b7a4-6024a57ac49f\scratch\baseline_hashes.json"
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@unittest.skipUnless((V2_DIR / "manifest.json").is_file(), "V2 artifacts not yet generated")
class AcceptanceCriteriaV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((V2_DIR / "manifest.json").read_text(encoding="utf-8"))
        cls.metrics = json.loads((V2_DIR / "metrics.json").read_text(encoding="utf-8"))
        cls.integrity = json.loads((V2_DIR / "source_integrity.json").read_text(encoding="utf-8"))
        cls.v1_map = read_jsonl(V1_DIR / "page_mapping_refined.jsonl")
        cls.v2_map = read_jsonl(V2_DIR / "page_mapping_refined.jsonl")
        cls.v1_ctx = read_jsonl(V1_DIR / "window_context_refined.jsonl")
        cls.v2_ctx = read_jsonl(V2_DIR / "window_context_refined.jsonl")
        cls.viet_ext = read_jsonl(V2_DIR / "viet_segments_extended.jsonl")
        cls.s4 = read_jsonl(PROD_DIR / "han_segments.jsonl")

    def test_required_files_exist_and_reopen(self):
        required_files = [
            "page_mapping_refined.xlsx",
            "page_mapping_refined.jsonl",
            "window_context_refined.jsonl",
            "viet_segments_extended.jsonl",
            "mapping_comparison.xlsx",
            "mapping_candidates.xlsx",
            "uncertain_pages.xlsx",
            "source_integrity.json",
            "metrics.json",
            "manifest.json",
            "requests.jsonl",
            "coarse_mapping_report.md",
            "STAGE04_INTEGRATION_GUIDE.md",
        ]
        for fname in required_files:
            fpath = V2_DIR / fname
            self.assertTrue(fpath.is_file(), f"Missing required artifact: {fname}")
            self.assertGreater(fpath.stat().st_size, 0, f"Empty artifact: {fname}")

        self.assertTrue((V2_DIR / "checkpoints").is_dir())
        self.assertGreater(len(list((V2_DIR / "checkpoints").glob("*.json"))), 0)

        # Reopen every Excel workbook and verify non-empty sheets
        for xname in ("page_mapping_refined.xlsx", "mapping_comparison.xlsx", "mapping_candidates.xlsx", "uncertain_pages.xlsx"):
            wb = load_workbook(V2_DIR / xname, read_only=True, data_only=True)
            try:
                self.assertGreaterEqual(len(wb.sheetnames), 1)
                for sname in wb.sheetnames:
                    rows = list(wb[sname].iter_rows(max_row=3, values_only=True))
                    self.assertGreaterEqual(len(rows), 1, f"Empty sheet {sname} in {xname}")
            finally:
                wb.close()

        # Reopen requests.jsonl
        _ = read_jsonl(V2_DIR / "requests.jsonl")

    def test_frozen_s4_and_han_character_accounting(self):
        self.assertEqual(len(self.s4), 2808)
        total_chars = sum(len(r["text_original"]) for r in self.s4)
        self.assertEqual(total_chars, 53328)
        # Verify global offsets form exact contiguous [0, 53328) partition
        cursor = 0
        seen_ids = set()
        for r in self.s4:
            self.assertNotIn(r["id_zh"], seen_ids)
            seen_ids.add(r["id_zh"])
            a, b = r["global_raw_span"]
            self.assertEqual(a, cursor)
            self.assertEqual(b - a, len(r["text_original"]))
            cursor = b
        self.assertEqual(cursor, 53328)

        # Verify S4 segments embedded in window_context_refined.jsonl are unmodified
        s4_by_id = {r["id_zh"]: r for r in self.s4}
        for ctx in self.v2_ctx:
            for seg in ctx["han"]:
                self.assertEqual(seg, s4_by_id[seg["id_zh"]])

    def test_unaffected_mappings_unchanged(self):
        self.assertEqual(len(self.v2_map), 145)
        self.assertEqual(len(self.v2_ctx), 145)
        v1_by_k = {(r["Cap"], r["Han_Page"]): r for r in self.v1_map}
        v1_ctx_by_k = {(r["cap"], r["han_page"]): r for r in self.v1_ctx}

        for r2 in self.v2_map:
            key = (r2["Cap"], r2["Han_Page"])
            if r2["Cap"] == "Cap_01" or r2["Han_Page"] <= 50 or r2["Han_Page"] >= 88:
                self.assertEqual(r2, v1_by_k[key], f"Modified unaffected mapping at {key}")
            else:
                self.assertNotEqual(r2["Mapping_Status"], "UNMATCHED", f"Expected mapped Book VI page at {key}")

        for c2 in self.v2_ctx:
            key = (c2["cap"], c2["han_page"])
            if c2["cap"] == "Cap_01" or c2["han_page"] <= 50 or c2["han_page"] >= 88:
                self.assertEqual(c2, v1_ctx_by_k[key], f"Modified unaffected context at {key}")

    def test_book_v_and_vi_ids_and_non_exclusion(self):
        self.assertEqual(len(self.viet_ext), 2054)
        ids = [r["id"] for r in self.viet_ext]
        self.assertEqual(len(ids), len(set(ids)))

        b5_ids = {r["id"] for r in self.viet_ext if r["book_id"] == "Book_V"}
        b6_ids = {r["id"] for r in self.viet_ext if r["book_id"] == "Book_VI"}
        self.assertEqual(len(b5_ids), 991)
        self.assertEqual(len(b6_ids), 378)
        self.assertEqual(len(b5_ids & b6_ids), 0)
        self.assertTrue(all(i.startswith("Cap_02-VI-") for i in b5_ids))
        self.assertTrue(all(i.startswith("Cap_02_VI-VI-") for i in b6_ids))

        # Verify 100% of eligible Book VI IDs are retained in padded page contexts across 051-087
        padded_union = set()
        for c in self.v2_ctx:
            if c["cap"] == "Cap_02" and 51 <= c["han_page"] <= 87:
                padded_union.update(c.get("padded_context_vi_ids", []))
        self.assertEqual(b6_ids - padded_union, set())

    def test_page_051_explicit_transition_and_no_gold_labels(self):
        p51_map = next(r for r in self.v2_map if r["Cap"] == "Cap_02" and r["Han_Page"] == 51)
        self.assertEqual(p51_map["Mapping_Status"], "VERIFIED")
        self.assertEqual(p51_map["Original_Verified_VI_Pages"], [105, 405])
        self.assertEqual(p51_map["B2_Range"], [105, 405])
        self.assertEqual(len(p51_map["Selected_VI_IDs"]), 27)
        self.assertIn("book_transition", p51_map["Evidence"])
        bt = p51_map["Evidence"]["book_transition"]
        self.assertEqual(bt["left_hand_book_vi_prose"]["intra_s4_prose_start_offset"], 40812)
        self.assertFalse(bt["left_hand_book_vi_prose"]["forced_to_s4_boundary"])

        # No semantic Gold labels assigned
        self.assertEqual(self.metrics["semantic_gold_labels_assigned"], 0)
        for r in self.v2_map:
            self.assertNotIn("Label_Target", r)

    def test_no_token_exposure_and_baseline_hashes_intact(self):
        token = os.getenv("SINONOM_TOKEN", "").strip()
        if token and len(token) >= 8:
            raw_tok = token.split()[-1]
            for fpath in V2_DIR.rglob("*"):
                if fpath.is_file() and fpath.suffix in {".json", ".jsonl", ".md"}:
                    txt = fpath.read_text(encoding="utf-8", errors="ignore")
                    self.assertNotIn(raw_tok, txt, f"Token leaked in {fpath}")

        if BASELINE_HASHES.is_file():
            baseline = json.loads(BASELINE_HASHES.read_text(encoding="utf-8"))
            for rel, expected_sha in baseline.items():
                if expected_sha == "LOCKED":
                    continue
                fp = ROOT / rel
                self.assertTrue(fp.is_file(), f"Tracked shared file missing: {rel}")
                self.assertEqual(sha256_file(fp), expected_sha, f"Shared file modified: {rel}")


if __name__ == "__main__":
    unittest.main()
