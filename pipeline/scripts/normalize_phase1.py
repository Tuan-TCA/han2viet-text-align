"""Build source-linked, local Stage 1 artifacts; never modify source files."""

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path

from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[1]
OCR = Path("02_ocr_tho")
BENCHMARK = Path("Cap01_Silver_Benchmark_Merged.xlsx")
INPUTS = {"Cap_01": (53, 186, 251), "Cap_02": (92, 1, 105)}
HEADER = re.compile(r"^=== (Cap_\d+) \| PAGE (\d+) ===[^\S\r\n]*\r?$", re.M)
VERIFIED = "đã xác minh mốc"
UNVERIFIED = "chưa xác minh"
SIMILARITY = 0.90


def nfc(text):
    return unicodedata.normalize("NFC", text)


def source(path, sheet=None, row=None):
    return {"path": path.as_posix(), **({"sheet": sheet, "row": row} if sheet else {})}


def table(sheet):
    rows = iter(sheet.values)
    fields = next(rows)
    if not all(fields) or len(set(fields)) != len(fields):
        raise ValueError(f"Invalid header in sheet {sheet.title}")
    return [(i, dict(zip(fields, row))) for i, row in enumerate(rows, 2)
            if any(cell is not None for cell in row)]


def load_han(cap, path, pages_expected, raw_offset, norm_offset):
    text = (ROOT / path).read_bytes().decode("utf-8-sig")
    markers = list(HEADER.finditer(text))
    if (not markers or text[:markers[0].start()].strip()
            or [m[1] for m in markers] != [cap] * pages_expected
            or [int(m[2]) for m in markers] != list(range(1, pages_expected + 1))):
        raise ValueError(f"Missing, duplicate, or out-of-order page header in {path}")
    rows = []
    for i, m in enumerate(markers):
        page = int(m[2])
        body_start = m.end() + (text[m.end():m.end()+1] == "\n")
        body_end = markers[i+1].start() if i+1 < len(markers) else len(text)
        body = text[body_start:body_end]
        raw = body.strip()
        if not raw:
            raise ValueError(f"Empty OCR page: {cap} {page}")
        normalized = nfc(raw)
        trim_start = body_start + len(body) - len(body.lstrip())
        rows.append({"id": f"{cap}-HAN-{page:03d}", "cap": cap, "han_pdf_page": page,
                     "pdf_path": f"01_nguon/{cap}/HAN.pdf", "source": source(path),
                     "file_body_span": [body_start, body_end],
                     "file_text_span": [trim_start, trim_start + len(raw)],
                     "body_original": body, "text_original": raw, "text_nfc": normalized,
                     "global_raw_span": [raw_offset, raw_offset + len(raw)],
                     "global_nfc_span": [norm_offset, norm_offset + len(normalized)]})
        raw_offset += len(raw)
        norm_offset += len(normalized)
    return rows, raw_offset, norm_offset


def parse_page_refs(value):
    if value is None:
        return []
    refs = []
    for part in str(value).split(","):
        match = re.fullmatch(r"\s*(\d+)\s*(?:\(([^)]+)\))?\s*", part)
        if not match:
            raise ValueError(f"Unknown Han page reference: {part!r}")
        refs.append({"han_pdf_page": int(match[1]), "qualifier": match[2]})
    return refs


def load_viet(cap, path, han_count, first_vi, last_vi):
    with (ROOT / path).open("rb") as fh:
        book = load_workbook(fh, read_only=True, data_only=True)
        try:
            text_rows, mapping_rows = (table(book[s]) for s in ("CAU_VIET", "TRANG_VIET"))
        finally:
            book.close()
    ids, viet, mapping = set(), [], []
    issues = []
    counts = Counter()
    previous = (first_vi, 0)
    texts = defaultdict(list)
    for i, row in text_rows:
        id_vi, first, last = (row[k] for k in ("id_vi", "viet_page_start", "viet_page_end"))
        id_match = re.fullmatch(rf"{cap}-VI-(\d{{4}})-(\d+)", str(id_vi))
        if not id_match or id_vi in ids:
            raise ValueError(f"Invalid or duplicate Việt ID at {path}:{i}: {id_vi}")
        ids.add(id_vi)
        if (type(first) is not int or type(last) is not int or not first_vi <= first <= last <= last_vi
                or first != int(id_match[1])):
            raise ValueError(f"Invalid Việt page range at {path}:{i}")
        order = (first, int(id_match[2]))
        if order <= previous:
            issues.append({"type": "viet_source_order", "row": i, "id": id_vi})
        previous = order
        flag, text = row["dung_de_ghep"], row["text_vi"]
        if type(flag) is not bool:
            raise ValueError(f"Expected Excel Boolean at {path}:{i}")
        counts["included" if flag else "excluded"] += 1
        if not flag:
            continue
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"Flagged Việt passage has no text at {path}:{i}")
        texts[nfc(text).strip()].append(id_vi)
        viet.append({"id": id_vi, "cap": cap, "source": source(path, "CAU_VIET", i),
                     "pdf_path": f"01_nguon/{cap}/VIET.pdf", "viet_page_start": first,
                     "viet_page_end": last, "text_original": text, "text_nfc": nfc(text),
                     "loai": row["loai"], "dung_de_ghep": flag, "co_ra_soat": row["co_ra_soat"]})

    touched = Counter(p for r in viet for p in range(r["viet_page_start"], r["viet_page_end"] + 1))
    windows = set()
    for i, row in mapping_rows:
        verified = row["trang_thai_moc"] == VERIFIED
        status = row["trang_thai_moc"]
        anchors = parse_page_refs(row["han_trang_co_moc"])
        candidates = parse_page_refs(row["han_trang_ung_vien"])
        lo, hi = row["han_cua_so_tu"], row["han_cua_so_den"]
        page = row["viet_pdf_page"]
        if status not in (VERIFIED, UNVERIFIED) or verified != bool(anchors):
            issues.append({"type": "inconsistent_anchor_status", "row": i})
        if type(lo) is int and type(hi) is int and 1 <= lo <= hi <= han_count:
            windows.update(range(lo, hi + 1))
            if any(not lo <= ref["han_pdf_page"] <= hi for ref in anchors + candidates):
                issues.append({"type": "anchor_or_candidate_outside_window", "row": i})
        else:
            issues.append({"type": "invalid_window", "row": i})
        if row["so_muc_ghep_cham_trang"] != touched[page]:
            issues.append({"type": "different_viet_touch_count", "row": i,
                           "sheet_count": row["so_muc_ghep_cham_trang"], "recount": touched[page]})
        mapping.append({**row, "cap": cap, "source": source(path, "TRANG_VIET", i),
                        "verified_overlap": anchors if verified else [], "candidate_refs": candidates,
                        "han_search_window": [lo, hi], "hard_sentence_constraint": False})
    if [m["viet_pdf_page"] for m in mapping] != list(range(first_vi, last_vi + 1)):
        raise ValueError(f"Missing, repeated, or out-of-order TRANG_VIET pages in {path}")
    audit = {"source_rows": len(text_rows), **counts, "mapping_rows": len(mapping),
             "verified_mapping_rows": sum(bool(r["verified_overlap"]) for r in mapping),
             "unverified_mapping_rows": sum(r["trang_thai_moc"] == UNVERIFIED for r in mapping),
             "cross_page_segments": sum(r["viet_page_start"] != r["viet_page_end"] for r in viet),
             "han_pages_outside_all_mapping_windows": sorted(set(range(1, han_count + 1)) - windows),
             "repeated_viet_text_ids": [group for group in texts.values() if len(group) > 1],
             "issues": issues}
    return viet, mapping, audit


def similar_pages(han):
    pages = [(r["id"], "".join(r["text_nfc"].split())) for r in han]
    found = []
    for (id_a, a), (id_b, b) in combinations(pages, 2):
        matcher = SequenceMatcher(None, a, b, autojunk=False)
        # Use both directions because difflib ratios can depend on input order.
        if matcher.quick_ratio() >= SIMILARITY:
            score = max(matcher.ratio(), SequenceMatcher(None, b, a, autojunk=False).ratio())
            if score >= SIMILARITY:
                found.append({"page_ids": [id_a, id_b], "score": round(score, 6),
                              "exact_ignoring_whitespace": a == b})
    return found


def load_silver(han, viet):
    with (ROOT / BENCHMARK).open("rb") as fh:
        book = load_workbook(fh, read_only=True, data_only=True)
        try:
            sheets = {name: table(book[name]) for name in book.sheetnames}
        finally:
            book.close()
    pilot = [p for p in han if p["cap"] == "Cap_01" and p["han_pdf_page"] <= 2]
    pilot_text = "".join(p["text_original"] for p in pilot)
    vi_ids = {v["id"]: v for v in viet}
    comparison = {r["Pair_ID"]: (i, r) for i, r in sheets["Comparison"]}

    def link(start, end, expected):
        if not (type(start) is type(end) is int and 0 <= start < end <= len(pilot_text)):
            return {"status": "invalid_range", "global_raw_span": None, "global_nfc_span": None}
        if pilot_text[start:end] != expected:
            return {"status": "ocr_text_mismatch", "global_raw_span": None, "global_nfc_span": None,
                    "ocr_at_benchmark_span": pilot_text[start:end]}
        global_start = pilot[0]["global_raw_span"][0] + start
        global_end = pilot[0]["global_raw_span"][0] + end
        pages = [p for p in pilot if p["global_raw_span"][0] < global_end and p["global_raw_span"][1] > global_start]
        # Don't project by length through a normalization change; raw offsets still work.
        norm_span = None
        if all(p["text_nfc"] == p["text_original"] for p in pages):
            first, last = pages[0], pages[-1]
            norm_span = [global_start - first["global_raw_span"][0] + first["global_nfc_span"][0],
                         global_end - last["global_raw_span"][0] + last["global_nfc_span"][0]]
        return {"status": "exact_ocr_slice", "global_raw_span": [global_start, global_end],
                "global_nfc_span": norm_span, "han_page_ids": [p["id"] for p in pages]}

    pairs = []
    for i, row in sheets["Alignment_Dataset"]:
        ci, compared = comparison[row["Pair_ID"]]
        vi = vi_ids.get(row["VI_ID"])
        vi_status = "missing_id" if vi is None else (
            "exact_nfc" if nfc(row["Vietnamese"]) == vi["text_nfc"] else "text_mismatch")
        pairs.append({**row, "source": source(BENCHMARK, "Alignment_Dataset", i),
                      "han_link": link(row["Han_Start_0"], row["Han_End_exclusive"], row["Chinese"]),
                      "viet_status": vi_status, "viet_source": vi and vi["source"],
                      "comparison": {**compared, "source": source(BENCHMARK, "Comparison", ci),
                                     "chatgpt_han_link": link(compared["CG_Start"], compared["CG_End"], compared["ChatGPT_Han"]),
                                     "deepseek_han_link": link(compared["DS_Start"], compared["DS_End"], compared["DeepSeek_Han"])}})
    unaligned = [{**r, "source": source(BENCHMARK, "Unaligned", i),
                  "han_link": link(r["Start_0"], r["End_exclusive"], r["Han_OCR"])}
                 for i, r in sheets["Unaligned"]]
    audit = {"kind": "silver_not_gold", "sheet_data_rows": {s: len(rows) for s, rows in sheets.items()},
             "pilot_raw_length": len(pilot_text),
             "provisional_positive_ids": [r["Pair_ID"] for r in pairs if r["Label_Target"] == 1],
             "unresolved_ids": [r["Pair_ID"] for r in pairs if r["Label_Target"] is None],
             "boundary_agreement": Counter(r["Boundary_Agreement"] for r in pairs),
             "comparison_viet_ids_agree": sum(r["VI_ID"] == r["comparison"]["VI_ID"] for r in pairs),
             "alignment_text_link_counts": Counter(r["han_link"]["status"] for r in pairs),
             "deepseek_text_link_counts": Counter(r["comparison"]["deepseek_han_link"]["status"] for r in pairs),
             "viet_link_counts": Counter(r["viet_status"] for r in pairs), "unaligned": unaligned}
    return pairs, audit


def build():
    han, viet, maps, caps = [], [], [], {}
    raw_end = norm_end = 0
    paths = [BENCHMARK]
    for cap, (count, first, last) in INPUTS.items():
        han_path = OCR / cap / f"{cap}_HAN_all_pages.txt"
        vi_path = OCR / cap / "VIET" / f"VIET_{first:04d}-{last:04d}.xlsx"
        paths.extend([han_path, vi_path])
        for lang in ("HAN", "VIET"):
            pdf = ROOT / "01_nguon" / cap / f"{lang}.pdf"
            if not pdf.is_file():
                raise FileNotFoundError(pdf)
        hp, raw_end, norm_end = load_han(cap, han_path, count, raw_end, norm_end)
        vp, mp, info = load_viet(cap, vi_path, count, first, last)
        han.extend(hp)
        viet.extend(vp)
        maps.extend(mp)
        caps[cap] = {"han_pages": len(hp), "han_pages_changed_by_nfc": [p["id"] for p in hp
                     if p["text_original"] != p["text_nfc"]], "viet": info}
    silver, silver_info = load_silver(han, viet)
    audit = {"schema_version": 1, "input_sha256": {p.as_posix(): hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
              for p in paths}, "caps": caps,
             "totals": {"han_pages": len(han), "viet_segments": len(viet), "mapping_rows": len(maps),
                        "han_raw_codepoints": raw_end, "han_nfc_codepoints": norm_end},
             "ocr_similarity": {"threshold": SIMILARITY, "metric": "max bidirectional difflib ratio; NFC without whitespace",
                                "pages_compared": len(han), "pairs": similar_pages(han)}, "silver": silver_info}
    return {"han_pages.jsonl": han, "viet_segments.jsonl": viet,
            "page_mapping.jsonl": maps, "silver_benchmark.jsonl": silver}, audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="New directory; existing paths are rejected")
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"Output already exists: {args.output}")
    tables, audit = build()
    args.output.mkdir(parents=True, exist_ok=False)
    for filename, records in tables.items():
        with (args.output / filename).open("x", encoding="utf-8", newline="\n") as f:
            for row in records:
                f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    with (args.output / "audit.json").open("x", encoding="utf-8", newline="\n") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2, default=str)
        f.write("\n")
    print(f"{args.output}: {audit['totals']}")


if __name__ == "__main__":
    main()
