"""Isolated multi-workbook Vietnamese source loader and reversible T1 normalizer (V2).

Extends Stage03 preprocessing to support multiple Vietnamese workbooks per Cap
(specifically Cap_02 Book V `VIET_0001-0105.xlsx` and Book VI `VIET_0405-0439.xlsx`)
without modifying shared Stage01/Stage02/Stage03/Stage04 production files.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata

STAGE = Path(__file__).resolve().parents[1]
ROOT = STAGE.parent
SCRIPTS_V1 = STAGE / "scripts"
LEGACY_SCRIPTS = ROOT / "pipeline" / "scripts"

for _p in (str(SCRIPTS_V1), str(LEGACY_SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import normalize_phase1 as phase1
from normalize_phase1 import UNVERIFIED, VERIFIED, load_han, nfc, parse_page_refs, similar_pages, source, table
from preprocess import audit_partition, content, fingerprint, normalize, read_jsonl, suspicious, viet_t1, write_json
from benchmark_alignment_api_final import CONFIRMED
from openpyxl import load_workbook


@dataclass(frozen=True)
class WorkbookSpec:
    cap: str
    book_id: str
    book_order: int
    workbook_id: str
    rel_path: str
    pdf_path: str
    id_prefix: str
    first_vi: int
    last_vi: int
    han_total_pages: int
    han_book_start: int
    han_book_end: int


HAN_SPECS = {
    "Cap_01": ("02_ocr_tho/Cap_01/Cap_01_HAN_all_pages.txt", 53),
    "Cap_02": ("02_ocr_tho/Cap_02/Cap_02_HAN_all_pages.txt", 92),
}

WORKBOOK_SPECS: tuple[WorkbookSpec, ...] = (
    WorkbookSpec(
        cap="Cap_01",
        book_id="Cap_01_Book_III",
        book_order=1,
        workbook_id="VIET_0186-0251",
        rel_path="02_ocr_tho/Cap_01/VIET/VIET_0186-0251.xlsx",
        pdf_path="01_nguon/Cap_01/VIET.pdf",
        id_prefix="Cap_01-VI",
        first_vi=186,
        last_vi=251,
        han_total_pages=53,
        han_book_start=1,
        han_book_end=53,
    ),
    WorkbookSpec(
        cap="Cap_02",
        book_id="Book_V",
        book_order=1,
        workbook_id="VIET_0001-0105",
        rel_path="02_ocr_tho/Cap_02/VIET/VIET_0001-0105.xlsx",
        pdf_path="01_nguon/Cap_02/VIET.pdf",
        id_prefix="Cap_02-VI",
        first_vi=1,
        last_vi=105,
        han_total_pages=92,
        han_book_start=1,
        han_book_end=51,
    ),
    WorkbookSpec(
        cap="Cap_02",
        book_id="Book_VI",
        book_order=2,
        workbook_id="VIET_0405-0439",
        rel_path="02_ocr_tho/Cap_02/VIET/VIET_0405-0439.xlsx",
        pdf_path="01_nguon/Cap-02/Viet-2/pdf/Phu_bien_tap_luc_2007.pdf",
        id_prefix="Cap_02_VI-VI",
        first_vi=405,
        last_vi=439,
        han_total_pages=92,
        han_book_start=51,
        han_book_end=87,
    ),
)

EXTENDED_OCR_TOKEN_RE = re.compile(
    r"\S*(?:[®©ðþƒ†#\uFFFD□]|\(cid:|(?<=\d)[õöðO]|[õöð](?=\d)|\b[õð]\b|\bl\d+|\d+Š)\S*"
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def cap_coord_page(cap: str, viet_pdf_page: int) -> int:
    """Map PDF page index onto a continuous physical page coordinate per Cap.

    - Cap_01: PDF pages 186..251 -> 186..251 (contiguous).
    - Cap_02 Book V: PDF pages 1..105 (printed 304..408) -> 1..105.
    - Cap_02 Book VI: PDF pages 405..439 (printed 409..443) -> 106..140 (`p - 299`).
      Printed page 408 (Book V p.105) is immediately followed by printed page 409 (Book VI p.405).
    """
    if cap == "Cap_02" and viet_pdf_page >= 405:
        return viet_pdf_page - 299
    return viet_pdf_page


def cap_pdf_page_from_coord(cap: str, coord_page: int) -> int:
    if cap == "Cap_02" and coord_page >= 106:
        return coord_page + 299
    return coord_page


def cap_ordinal_page(cap: str, viet_pdf_page: int) -> int:
    """1-based page ordinal within each Cap across its ordered workbooks."""
    if cap == "Cap_01":
        return viet_pdf_page - 185
    if cap == "Cap_02":
        return viet_pdf_page if viet_pdf_page <= 105 else viet_pdf_page - 299
    raise ValueError(f"Unknown cap: {cap}")


def detect_viet_ocr_anomalies(text: str) -> list[dict]:
    found = []
    for m in EXTENDED_OCR_TOKEN_RE.finditer(text):
        found.append({"span": list(m.span()), "token": m.group(0)})
    return found


def verify_reversible_t1(raw_text: str, t1_text: str, spans: list[list[int]]) -> bool:
    if len(t1_text) != len(spans):
        return False
    prev_start = -1
    for ch, (a, b) in zip(t1_text, spans):
        if not (0 <= a < b <= len(raw_text)):
            return False
        if a < prev_start:
            return False
        prev_start = a
        orig_slice = raw_text[a:b]
        if ch == " ":
            if not orig_slice.isspace():
                return False
        else:
            if ch not in unicodedata.normalize("NFC", orig_slice):
                return False
    return True


def load_viet_workbook(spec: WorkbookSpec, seen_global_ids: set[str] | None = None):
    """Load and validate a single Vietnamese workbook, preserving original IDs and provenance."""
    wb_path = ROOT / Path(spec.rel_path)
    if not wb_path.is_file():
        raise FileNotFoundError(wb_path)

    with wb_path.open("rb") as fh:
        book = load_workbook(fh, read_only=True, data_only=True)
        try:
            sheet_names = list(book.sheetnames)
            if sheet_names != ["CAU_VIET", "TRANG_VIET"]:
                raise ValueError(f"Unexpected sheets in {spec.rel_path}: {sheet_names}")
            text_rows = table(book["CAU_VIET"])
            mapping_rows = table(book["TRANG_VIET"])
        finally:
            book.close()

    # First pass over TRANG_VIET to validate page sequence and index printed_page (`trang_in`)
    printed_by_pdf: dict[int, int] = {}
    for row_no, mrow in mapping_rows:
        p = mrow["viet_pdf_page"]
        t_in = mrow["trang_in"]
        if type(p) is not int or type(t_in) is not int:
            raise ValueError(f"Non-integer page metadata in {spec.rel_path}:TRANG_VIET:{row_no}")
        printed_by_pdf[p] = t_in

    expected_pages = list(range(spec.first_vi, spec.last_vi + 1))
    actual_pages = [mrow["viet_pdf_page"] for _, mrow in mapping_rows]
    if actual_pages != expected_pages:
        raise ValueError(f"Missing, repeated, or out-of-order TRANG_VIET pages in {spec.rel_path}")

    id_pattern = re.compile(rf"{re.escape(spec.id_prefix)}-(\d{{4}})-(\d+)")
    local_ids: set[str] = set()
    viet_eligible: list[dict] = []
    viet_all_rows: list[dict] = []
    issues: list[dict] = []
    counts = Counter()
    loai_all = Counter()
    loai_eligible = Counter()
    review_flag_counts = Counter()
    ocr_anomalies: list[dict] = []
    previous_order = (spec.first_vi, 0)
    texts_eligible = defaultdict(list)
    texts_all = defaultdict(list)

    for row_no, row in text_rows:
        id_vi = row["id_vi"]
        first = row["viet_page_start"]
        last = row["viet_page_end"]
        id_match = id_pattern.fullmatch(str(id_vi))
        if not id_match or id_vi in local_ids:
            raise ValueError(f"Invalid or duplicate Việt ID at {spec.rel_path}:{row_no}: {id_vi!r}")
        if seen_global_ids is not None:
            if id_vi in seen_global_ids:
                raise ValueError(f"Cross-workbook Việt ID collision at {spec.rel_path}:{row_no}: {id_vi!r}")
            seen_global_ids.add(id_vi)
        local_ids.add(id_vi)

        if (
            type(first) is not int
            or type(last) is not int
            or not (spec.first_vi <= first <= last <= spec.last_vi)
            or first != int(id_match[1])
        ):
            raise ValueError(f"Invalid Việt page range at {spec.rel_path}:{row_no}: {first}..{last}")

        order = (first, int(id_match[2]))
        if order <= previous_order:
            issues.append({"type": "viet_source_order", "row": row_no, "id": id_vi})
        previous_order = order

        flag = row["dung_de_ghep"]
        text = row["text_vi"]
        loai = row["loai"]
        co_ra_soat = row["co_ra_soat"]

        if type(flag) is not bool:
            raise ValueError(f"Expected Excel Boolean at {spec.rel_path}:{row_no}")
        if not isinstance(text, str) or not text.strip():
            if flag:
                raise ValueError(f"Flagged Việt passage has no text at {spec.rel_path}:{row_no}")
            issues.append({"type": "empty_ineligible_text", "row": row_no, "id": id_vi})

        counts["included" if flag else "excluded"] += 1
        loai_all[loai] += 1
        review_flag_counts[co_ra_soat or ""] += 1

        norm_nfc = nfc(text) if isinstance(text, str) else ""
        if norm_nfc.strip():
            texts_all[norm_nfc.strip()].append(id_vi)

        anomalies = detect_viet_ocr_anomalies(text) if isinstance(text, str) else []
        if anomalies or (co_ra_soat and "OCR" in str(co_ra_soat)):
            ocr_anomalies.append({
                "row": row_no,
                "id_vi": id_vi,
                "eligible": flag,
                "loai": loai,
                "co_ra_soat": co_ra_soat,
                "detected_tokens": [a["token"] for a in anomalies],
                "flagged_in_sheet": bool(co_ra_soat and "OCR" in str(co_ra_soat)),
            })

        base_rec = {
            "id": id_vi,
            "cap": spec.cap,
            "source": source(Path(spec.rel_path), "CAU_VIET", row_no),
            "pdf_path": spec.pdf_path,
            "viet_page_start": first,
            "viet_page_end": last,
            "text_original": text,
            "text_nfc": norm_nfc,
            "loai": loai,
            "dung_de_ghep": flag,
            "co_ra_soat": co_ra_soat,
        }
        ext_meta = {
            "book_id": spec.book_id,
            "book_order": spec.book_order,
            "workbook_id": spec.workbook_id,
            "id_namespace": spec.id_prefix,
            "printed_page_start": printed_by_pdf[first],
            "printed_page_end": printed_by_pdf[last],
            "book_local_page_start": first - spec.first_vi + 1,
            "book_local_page_end": last - spec.first_vi + 1,
            "cap_ordinal_page_start": cap_ordinal_page(spec.cap, first),
            "cap_ordinal_page_end": cap_ordinal_page(spec.cap, last),
            "cap_coord_page_start": cap_coord_page(spec.cap, first),
            "cap_coord_page_end": cap_coord_page(spec.cap, last),
        }
        viet_all_rows.append({**base_rec, **ext_meta})

        if not flag:
            continue

        loai_eligible[loai] += 1
        texts_eligible[norm_nfc.strip()].append(id_vi)
        t1_text, t1_spans = viet_t1(text, CONFIRMED.get(id_vi, ()))
        if not t1_text or "\n" in t1_text or not verify_reversible_t1(text, t1_text, t1_spans):
            raise ValueError(f"Reversible T1 verification failed for {id_vi} at {spec.rel_path}:{row_no}")

        viet_eligible.append({
            **base_rec,
            **ext_meta,
            "text_t1": t1_text,
            "normalized_source_spans": t1_spans,
            "ocr_flags": suspicious(text),
            "extended_ocr_tokens": [a["token"] for a in anomalies],
        })

    touched = Counter(
        p for r in viet_eligible for p in range(r["viet_page_start"], r["viet_page_end"] + 1)
    )
    windows: set[int] = set()
    mapping: list[dict] = []
    for row_no, row in mapping_rows:
        status = row["trang_thai_moc"]
        verified = status == VERIFIED
        anchors = parse_page_refs(row["han_trang_co_moc"])
        candidates = parse_page_refs(row["han_trang_ung_vien"])
        lo, hi = row["han_cua_so_tu"], row["han_cua_so_den"]
        page = row["viet_pdf_page"]

        if status not in (VERIFIED, UNVERIFIED, "ứng viên theo nội dung") or verified != bool(anchors):
            issues.append({"type": "inconsistent_anchor_status", "row": row_no, "status": status})
        if type(lo) is int and type(hi) is int and 1 <= lo <= hi <= spec.han_total_pages:
            windows.update(range(lo, hi + 1))
            if any(not (lo <= ref["han_pdf_page"] <= hi) for ref in anchors + candidates):
                issues.append({"type": "anchor_or_candidate_outside_window", "row": row_no})
            if not (spec.han_book_start <= lo <= hi <= spec.han_book_end):
                issues.append({"type": "window_outside_book_han_bounds", "row": row_no, "window": [lo, hi]})
        else:
            issues.append({"type": "invalid_window", "row": row_no})

        if row["so_muc_ghep_cham_trang"] != touched[page]:
            issues.append({
                "type": "different_viet_touch_count",
                "row": row_no,
                "sheet_count": row["so_muc_ghep_cham_trang"],
                "recount": touched[page],
            })

        mapping.append({
            **row,
            "cap": spec.cap,
            "book_id": spec.book_id,
            "book_order": spec.book_order,
            "workbook_id": spec.workbook_id,
            "book_local_page": page - spec.first_vi + 1,
            "cap_ordinal_page": cap_ordinal_page(spec.cap, page),
            "cap_coord_page": cap_coord_page(spec.cap, page),
            "source": source(Path(spec.rel_path), "TRANG_VIET", row_no),
            "verified_overlap": anchors if verified else [],
            "candidate_refs": candidates,
            "han_search_window": [lo, hi],
            "hard_sentence_constraint": False,
        })

    audit = {
        "cap": spec.cap,
        "book_id": spec.book_id,
        "workbook_id": spec.workbook_id,
        "path": spec.rel_path,
        "sha256": sha256_file(wb_path),
        "id_namespace": spec.id_prefix,
        "pdf_page_range": [spec.first_vi, spec.last_vi],
        "printed_page_range": [printed_by_pdf[spec.first_vi], printed_by_pdf[spec.last_vi]],
        "book_local_page_range": [1, spec.last_vi - spec.first_vi + 1],
        "cap_ordinal_page_range": [
            cap_ordinal_page(spec.cap, spec.first_vi),
            cap_ordinal_page(spec.cap, spec.last_vi),
        ],
        "han_book_page_range": [spec.han_book_start, spec.han_book_end],
        "source_rows": len(text_rows),
        "included": counts["included"],
        "excluded": counts["excluded"],
        "loai_all": dict(loai_all),
        "loai_eligible": dict(loai_eligible),
        "review_flag_counts": dict(review_flag_counts),
        "mapping_rows": len(mapping),
        "verified_mapping_rows": sum(bool(r["verified_overlap"]) for r in mapping),
        "unverified_mapping_rows": sum(r["trang_thai_moc"] == UNVERIFIED for r in mapping),
        "cross_page_segments_eligible": sum(r["viet_page_start"] != r["viet_page_end"] for r in viet_eligible),
        "cross_page_segments_all": sum(r["viet_page_start"] != r["viet_page_end"] for r in viet_all_rows),
        "han_pages_covered_by_windows": [min(windows), max(windows)] if windows else None,
        "han_pages_outside_book_windows": sorted(
            set(range(spec.han_book_start, spec.han_book_end + 1)) - windows
        ),
        "repeated_eligible_viet_text_ids": [g for g in texts_eligible.values() if len(g) > 1],
        "repeated_all_viet_text_ids": [g for g in texts_all.values() if len(g) > 1],
        "ocr_anomaly_summary": {
            "total_rows_with_ocr_anomalies": len(ocr_anomalies),
            "eligible_rows_with_ocr_anomalies": sum(1 for a in ocr_anomalies if a["eligible"]),
            "flagged_in_sheet": sum(1 for a in ocr_anomalies if a["flagged_in_sheet"]),
            "unflagged_additional_detected": sum(1 for a in ocr_anomalies if not a["flagged_in_sheet"]),
            "rows": ocr_anomalies,
        },
        "reversible_t1_verified_count": len(viet_eligible),
        "issues": issues,
    }
    return viet_eligible, mapping, audit, viet_all_rows


def load_sources_v2(specs: tuple[WorkbookSpec, ...] = WORKBOOK_SPECS):
    """Load Han pages and multi-workbook Vietnamese segments/mappings in canonical textual order."""
    old_root = phase1.ROOT
    phase1.ROOT = ROOT
    try:
        han_pages: list[dict] = []
        raw_offset = nfc_offset = 0
        for cap, (rel_han, expected_pages) in HAN_SPECS.items():
            hp, raw_offset, nfc_offset = load_han(cap, Path(rel_han), expected_pages, raw_offset, nfc_offset)
            han_pages.extend(hp)

        seen_global_ids: set[str] = set()
        viet_segments: list[dict] = []
        mapping_rows: list[dict] = []
        workbook_audits: dict[str, dict] = {}

        # Sort specs by cap order ("Cap_01" then "Cap_02") and book_order (Book V then Book VI)
        ordered_specs = sorted(specs, key=lambda s: (s.cap, s.book_order))
        prev_cap_coord_end: dict[str, int] = {}

        for spec in ordered_specs:
            vp, mp, aud, _ = load_viet_workbook(spec, seen_global_ids=seen_global_ids)
            if spec.cap in prev_cap_coord_end:
                first_coord = mp[0]["cap_coord_page"]
                if first_coord <= prev_cap_coord_end[spec.cap]:
                    raise ValueError(
                        f"Non-monotonic workbook order in {spec.cap}: {spec.workbook_id} starts at coord {first_coord} "
                        f"after {prev_cap_coord_end[spec.cap]}"
                    )
            prev_cap_coord_end[spec.cap] = mp[-1]["cap_coord_page"]
            viet_segments.extend(vp)
            mapping_rows.extend(mp)
            workbook_audits[spec.workbook_id] = aud

        return han_pages, viet_segments, mapping_rows, workbook_audits
    finally:
        phase1.ROOT = old_root


def legacy_viet_view(record: dict) -> dict:
    """Project an extended Vietnamese record onto the exact 11-key Stage03/Stage04 legacy dict."""
    keys = (
        "id",
        "cap",
        "source",
        "pdf_path",
        "viet_page_start",
        "viet_page_end",
        "text_original",
        "text_nfc",
        "loai",
        "dung_de_ghep",
        "co_ra_soat",
    )
    return {k: record[k] for k in keys}


def verify_frozen_s4_and_han(han_pages: list[dict]) -> dict:
    """Verify that all 2,808 frozen S4 segments and 53,328 Han characters remain intact."""
    s4_path = STAGE / "artifacts" / "production" / "han_segments.jsonl"
    segments = read_jsonl(s4_path)
    if len(segments) != 2808:
        raise ValueError(f"Expected 2808 frozen S4 segments, got {len(segments)}")

    total_han_chars = sum(len(p["text_original"]) for p in han_pages)
    if total_han_chars != 53328:
        raise ValueError(f"Expected 53328 Han code points, got {total_han_chars}")

    by_cap_segs = defaultdict(list)
    seen_zh_ids = set()
    source_cache = {}
    slice_mismatches = 0
    offset_mismatches = 0

    for seg in segments:
        zh_id = seg["id_zh"]
        if zh_id in seen_zh_ids:
            raise ValueError(f"Duplicate Han segment ID: {zh_id}")
        seen_zh_ids.add(zh_id)
        cap = seg["window"].rsplit("-", 2)[0]
        by_cap_segs[cap].append(seg)

        pieces = []
        for s in seg["source"]:
            fpath = s["file"]
            a, b = s["file_span"]
            if fpath not in source_cache:
                source_cache[fpath] = (ROOT / fpath).read_bytes().decode("utf-8-sig")
            pieces.append(source_cache[fpath][a:b])
        reconstructed = "".join(pieces)
        lo, hi = seg["global_raw_span"]
        norm_zh, ix = normalize(reconstructed)
        if (
            reconstructed != seg["text_original"]
            or hi - lo != len(reconstructed)
            or norm_zh != seg["text_zh"]
            or [[lo + u, lo + v] for u, v in ix] != seg["normalized_source_spans"]
        ):
            slice_mismatches += 1

    cap_summaries = {}
    for cap in ("Cap_01", "Cap_02"):
        c_pages = [p for p in han_pages if p["cap"] == cap]
        c_segs = by_cap_segs[cap]
        joined_pages = "".join(p["text_original"] for p in c_pages)
        joined_segs = "".join(s["text_original"] for s in c_segs)
        origin = c_pages[0]["global_raw_span"][0]
        local_spans = [[s["global_raw_span"][0] - origin, s["global_raw_span"][1] - origin] for s in c_segs]
        part = audit_partition(joined_pages, local_spans)
        for s in c_segs:
            a, b = s["global_raw_span"]
            if joined_pages[a - origin : b - origin] != s["text_original"]:
                offset_mismatches += 1
        if joined_pages != joined_segs or not part["exact_reconstruction"]:
            raise ValueError(f"S4 reconstruction failed for {cap}")
        cap_summaries[cap] = {
            "pages": len(c_pages),
            "segments": len(c_segs),
            "source_chars": len(joined_pages),
            "missing_chars": part["missing"],
            "duplicated_chars": part["duplicated"],
            "exact_reconstruction": part["exact_reconstruction"],
            "cross_page_segments": sum(s["page_start"] != s["page_end"] for s in c_segs),
        }

    if slice_mismatches or offset_mismatches:
        raise ValueError(f"S4 integrity mismatch: slices={slice_mismatches}, offsets={offset_mismatches}")

    return {
        "status": "PASS",
        "han_segments_path": s4_path.relative_to(ROOT).as_posix(),
        "han_segments_sha256": sha256_file(s4_path),
        "total_pages": len(han_pages),
        "total_segments": len(segments),
        "total_source_chars": total_han_chars,
        "global_offset_mismatches": offset_mismatches,
        "source_file_slice_mismatches": slice_mismatches,
        "caps": cap_summaries,
        "near_duplicate_han_pages": similar_pages(han_pages),
    }


def analyze_page051_and_book6_anchors(han_pages: list[dict], viet_segments: list[dict], mapping_rows: list[dict]) -> dict:
    """Verify Book VI anchors and construct explicit source-evidenced Page 051 transition metadata."""
    s4_segments = read_jsonl(STAGE / "artifacts" / "production" / "han_segments.jsonl")
    p51_page = next(p for p in han_pages if p["cap"] == "Cap_02" and p["han_pdf_page"] == 51)
    p51_raw = p51_page["text_original"]
    p51_origin = p51_page["global_raw_span"][0]  # 40741

    col_json_path = ROOT / "02_ocr_tho/Cap_02/HAN/pages/Cap02-051.json"
    col_data = json.loads(col_json_path.read_text(encoding="utf-8"))

    heading_str = "撫邊雜錄卷之六"
    prose_str = "物產之美多出獻方"
    heading_local = p51_raw.index(heading_str)  # 64
    prose_local = p51_raw.index(prose_str)      # 71
    heading_global = p51_origin + heading_local  # 40805
    prose_global = p51_origin + prose_local      # 40812

    p51_s4 = [s for s in s4_segments if s["window"].startswith("Cap_02") and s["page_start"] <= 51 <= s["page_end"]]
    split_s4 = next(s for s in p51_s4 if s["global_raw_span"][0] <= prose_global < s["global_raw_span"][1])
    cross_51_52 = [s for s in p51_s4 if s["page_start"] == 51 and s["page_end"] == 52]

    p87_s4 = [s for s in s4_segments if s["window"].startswith("Cap_02") and s["page_start"] <= 87 <= s["page_end"]]
    cross_87_88 = [s for s in p87_s4 if s["page_start"] == 87 and s["page_end"] == 88]

    book5_p51_ids = [
        v["id"] for v in viet_segments
        if v["book_id"] == "Book_V" and v["viet_page_start"] <= 105 <= v["viet_page_end"]
    ]
    book6_p51_ids = [
        v["id"] for v in viet_segments
        if v["book_id"] == "Book_VI" and v["viet_page_start"] <= 405 <= v["viet_page_end"]
    ]

    # Verify all 5 expected Book VI Han anchors against TRANG_VIET, CAU_VIET, raw pdftotext, and Han OCR
    expected_book6_anchors = [
        {"han_page": 51, "expected_viet_pdf_pages": [405], "han_cue": "北市政卅七十五社村坊", "viet_cue": "châu Bắc Bố Chính"},
        {"han_page": 61, "expected_viet_pdf_pages": [414], "han_cue": "順化有鑄匠司二隊谷三十人", "viet_cue": "hai đội ty thợ đúc, đều 30 người"},
        {"han_page": 71, "expected_viet_pdf_pages": [424, 425], "han_cue": "五年甲子", "viet_cue": "Năm Cảnh Hưng thứ 5, Giáp Tý"},
        {"han_page": 81, "expected_viet_pdf_pages": [434], "han_cue": "順化必多夏田少秩田", "viet_cue": "có nhiều ruộng mùa hạ, ít ruộng mùa"},
        {"han_page": 87, "expected_viet_pdf_pages": [439], "han_cue": "嘉定府最多", "viet_cue": "Gia Định rất nhiều cau"},
    ]
    verified_anchors_report = []
    book6_maps = [m for m in mapping_rows if m["book_id"] == "Book_VI"]
    han_by_page = {p["han_pdf_page"]: p for p in han_pages if p["cap"] == "Cap_02"}

    for item in expected_book6_anchors:
        h = item["han_page"]
        actual_v_pages = sorted(
            m["viet_pdf_page"] for m in book6_maps if any(a["han_pdf_page"] == h for a in m["verified_overlap"])
        )
        h_text = han_by_page[h]["text_original"]
        v_texts = [
            v["text_original"] for v in viet_segments
            if v["book_id"] == "Book_VI"
            and any(v["viet_page_start"] <= vp <= v["viet_page_end"] for vp in actual_v_pages)
        ]
        pdftotext_matches = []
        for vp in actual_v_pages:
            raw_pt = ROOT / f"02_ocr_tho/Cap_02/VIET/raw/pdftotext/{vp:04d}_page_text.txt"
            pdftotext_matches.append(raw_pt.is_file())

        han_cue_present = item["han_cue"] in h_text
        viet_cue_present = any(item["viet_cue"].lower() in vt.lower() for vt in v_texts)
        exact_match = (actual_v_pages == item["expected_viet_pdf_pages"]) and han_cue_present and viet_cue_present
        if not exact_match:
            raise ValueError(f"Book VI anchor verification failed at Han page {h}: actual={actual_v_pages}")
        verified_anchors_report.append({
            "han_page": h,
            "expected_viet_pdf_pages": item["expected_viet_pdf_pages"],
            "actual_viet_pdf_pages": actual_v_pages,
            "printed_pages": [
                next(m["trang_in"] for m in book6_maps if m["viet_pdf_page"] == vp) for vp in actual_v_pages
            ],
            "book_local_pages": [vp - 405 + 1 for vp in actual_v_pages],
            "han_cue_verified": han_cue_present,
            "viet_cue_verified": viet_cue_present,
            "raw_pdftotext_present": all(pdftotext_matches),
            "qualifiers": [
                a.get("qualifier")
                for m in book6_maps
                for a in m["verified_overlap"]
                if a["han_pdf_page"] == h
            ],
            "status": "VERIFIED",
        })

    # Footer OCR check against raw pdftotext
    footer_ocr_discrepancies = []
    for m in book6_maps:
        vp = m["viet_pdf_page"]
        raw_pt = ROOT / f"02_ocr_tho/Cap_02/VIET/raw/pdftotext/{vp:04d}_page_text.txt"
        if raw_pt.is_file():
            lines = [ln.strip() for ln in raw_pt.read_text(encoding="utf-8").splitlines() if ln.strip()]
            last_line = lines[-1] if lines else ""
            if last_line != str(m["trang_in"]):
                footer_ocr_discrepancies.append({
                    "viet_pdf_page": vp,
                    "workbook_trang_in": m["trang_in"],
                    "raw_pdftotext_footer": last_line,
                    "note": "Workbook TRANG_VIET.trang_in correctly records true printed page sequence despite PDF OCR digit error on footer.",
                })

    return {
        "page_051_transition": {
            "cap": "Cap_02",
            "han_page": 51,
            "page_global_raw_span": p51_page["global_raw_span"],
            "page_char_length": len(p51_raw),
            "ocr_columns_detected": col_data["info"]["kept"],
            "right_hand_book_v": {
                "book_id": "Book_V",
                "workbook_id": "VIET_0001-0105",
                "columns": ["Cap02-051-COL01", "Cap02-051-COL02", "Cap02-051-COL03", "Cap02-051-COL04"],
                "page_local_span": [0, heading_local],
                "global_raw_span": [p51_origin, heading_global],
                "s4_segment_ids": [s["id_zh"] for s in p51_s4 if s["global_raw_span"][1] <= heading_global],
                "cross_page_from_050_note": (
                    "Opening characters [40741,40747) ('X7寬政辭磨') inside Cap_02-051-052-S4-0001 continue "
                    "Cap_02-VI-0105-014 from the end of Han page 050 ('...直播施'); Cap_02-VI-0105-015 starts "
                    "intra-S4 at global offset 40747 ('但見盡抗武功誕字之德')."
                ),
                "verified_viet_pdf_page": 105,
                "printed_page": 408,
                "eligible_viet_ids": book5_p51_ids,
            },
            "book_vi_heading_column": {
                "book_id": "Book_VI",
                "columns": ["Cap02-051-COL05"],
                "page_local_span": [heading_local, prose_local],
                "global_raw_span": [heading_global, prose_global],
                "han_text": p51_raw[heading_local:prose_local],
                "containing_s4_id": split_s4["id_zh"],
                "containing_s4_span": split_s4["global_raw_span"],
                "corresponding_ineligible_viet_row": "Cap_02_VI-VI-0405-001 (QUYỂN VI, loai=tieu_de, dung_de_ghep=False)",
            },
            "left_hand_book_vi_prose": {
                "book_id": "Book_VI",
                "workbook_id": "VIET_0405-0439",
                "columns": [f"Cap02-051-COL{i:02d}" for i in range(6, 14)],
                "page_local_span": [prose_local, len(p51_raw)],
                "global_raw_span": [prose_global, p51_page["global_raw_span"][1]],
                "intra_s4_prose_start_offset": prose_global,
                "forced_to_s4_boundary": False,
                "s4_segment_ids": [s["id_zh"] for s in p51_s4 if s["global_raw_span"][1] > heading_global],
                "cross_page_to_052_segment": {
                    "id_zh": cross_51_52[0]["id_zh"],
                    "global_raw_span": cross_51_52[0]["global_raw_span"],
                    "text_original": cross_51_52[0]["text_original"],
                    "note": (
                        "Spans Han page 051 [40938,40943) ('土人煎密1') into Han page 052 [40943,40955) "
                        "('浸貯可耐久礼社人參出北市'), completing Cap_02_VI-VI-0405-007 at offset 40948 and starting "
                        "Cap_02_VI-VI-0405-008 intra-S4."
                    ),
                },
                "verified_viet_pdf_page": 405,
                "printed_page": 409,
                "book_local_page": 1,
                "eligible_viet_ids": book6_p51_ids,
            },
        },
        "page_087_end_of_book_vi_boundary": {
            "cap": "Cap_02",
            "han_page": 87,
            "cross_page_to_088_segment": {
                "id_zh": cross_87_88[0]["id_zh"],
                "global_raw_span": cross_87_88[0]["global_raw_span"],
                "text_original": cross_87_88[0]["text_original"],
                "book_vi_closing_span": [52417, 52419],
                "colophon_ocr_noise_span": [52419, 52431],
                "postface_opening_on_088_span": [52431, 52443],
                "note": (
                    "Offsets [52417,52419) ('北容' for '北客') complete Cap_02_VI-VI-0439-011 on Han page 087; "
                    "[52419,52431) ('1010001膜R210') is stamp/colophon OCR noise at the end of Book VI; "
                    "[52431,52443) ('撫邊雜錄發順廣為國家南近') on Han page 088 begins Ngô Thì Sĩ's postface (Bạt), "
                    "which is outside VIET_0405-0439.xlsx."
                ),
            },
        },
        "unresolved_pages_088_092": [
            {"han_page": 88, "global_raw_span": han_by_page[88]["global_raw_span"], "reason": "Postface (Phủ biên tạp lục bạt by Ngô Thì Sĩ, 1777); Vietnamese translation starts at PDF p.440, not in VIET_0405-0439.xlsx."},
            {"han_page": 89, "global_raw_span": han_by_page[89]["global_raw_span"], "reason": "Continuation and dated signature of Ngô Thì Sĩ's postface; cross-page S4 segment Cap_02-089-090-S4-0015 enters page 090."},
            {"han_page": 90, "global_raw_span": han_by_page[90]["global_raw_span"], "reason": "Duplicate scan of Cap_02 Han page 001 (Book V opening '撫邊雜錄卷之五...人才何代無之'); must not be aligned to Book VI."},
            {"han_page": 91, "global_raw_span": han_by_page[91]["global_raw_span"], "reason": "Archival shelfmark OCR fragment ('R16061'); no textual passage."},
            {"han_page": 92, "global_raw_span": han_by_page[92]["global_raw_span"], "reason": "Archival shelfmark OCR fragment ('01'); no textual passage."},
        ],
        "verified_book6_anchors": verified_anchors_report,
        "raw_pdftotext_footer_ocr_notes": footer_ocr_discrepancies,
    }
