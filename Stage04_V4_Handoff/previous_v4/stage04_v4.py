#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a source-grounded Stage 04 V4 pilot from frozen offline inputs.

No API calls. This is a reproducible pilot correction map for Cap_01 Han pages 1-2,
not a corpus-wide automatic semantic aligner.
"""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
from collections import Counter
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

RULES = [
    {"start": 0, "end": 35, "vi": "Cap_01-VI-0186-001", "assessment": "FALSE",
     "confidence": "HIGH", "rule": "KEEP_PARTIAL_SOURCE",
     "reason": "Vietnamese source is explicitly flagged as cut at the beginning; strict complete-match criterion is not met."},
    {"start": 35, "end": 55, "vi": "Cap_01-VI-0186-002", "assessment": "TRUE",
     "confidence": "HIGH", "rule": "KEEP_DIRECT_MATCH",
     "reason": "Direct correspondence; no material mismatch identified."},
    {"start": 55, "end": 213, "vi": "Cap_01-VI-0186-003", "assessment": "UNKNOWN",
     "confidence": "MEDIUM", "rule": "RESTORE_UNCOVERED_HAN_TAIL",
     "reason": "Restore [166,213) containing totals corresponding to 278 people, 213 quan 7 tien and 2,727 bowls; exact OCR numerals remain unverified."},
    {"start": 213, "end": 267, "vi": "Cap_01-VI-0187-001", "assessment": "UNKNOWN",
     "confidence": "MEDIUM", "rule": "KEEP_NUMERIC_REVIEW",
     "reason": "Broad topic matches, but final amount differs between OCR and Vietnamese translation."},
    {"start": 267, "end": 326, "vi": "Cap_01-VI-0187-002", "assessment": "UNKNOWN",
     "confidence": "MEDIUM", "rule": "KEEP_NUMERIC_REVIEW",
     "reason": "Main figures align, but individual monetary and deduction details require scan-level verification."},
    {"start": 326, "end": 337, "vi": "Cap_01-VI-0187-003", "assessment": "TRUE",
     "confidence": "HIGH", "rule": "KEEP_DIRECT_MATCH",
     "reason": "Short direct statement about Quảng Nam and Thuận Hóa."},
    {"start": 337, "end": 372, "vi": "Cap_01-VI-0187-004", "assessment": "TRUE",
     "confidence": "MEDIUM", "rule": "KEEP_DIRECT_MATCH",
     "reason": "Content corresponds; some OCR characters should be checked before using as formal Gold."},
    {"start": 372, "end": 545, "vi": "Cap_01-VI-0187-005", "assessment": "UNKNOWN",
     "confidence": "LOW", "rule": "RESTORE_GAP_AND_TRANSFER_REPEATED_CLAUSE",
     "reason": "Restore missing [372,396) and include [531,545) as the previous segment's boats/villages/new-certificate clause. The repeated Vietnamese wording makes full attribution uncertain."},
    {"start": 545, "end": 647, "vi": "Cap_01-VI-0188-001", "assessment": "UNKNOWN",
     "confidence": "LOW", "rule": "SPLIT_AT_SEAL_FEE_CUE",
     "reason": "Start at 有印 at offset 545. Boundary 547 is rejected because it cuts inside the next fee opening; repeated closing wording remains unresolved."},
    {"start": 647, "end": 664, "vi": "Cap_01-VI-0188-002", "assessment": "TRUE",
     "confidence": "HIGH", "rule": "KEEP_DIRECT_MATCH",
     "reason": "Direct correspondence about inner-chamber maidservants and officials' emoluments."},
    {"start": 664, "end": 731, "vi": "Cap_01-VI-0188-003", "assessment": "TRUE",
     "confidence": "HIGH", "rule": "TRANSFER_MEMORIAL_DAY_CLAUSE",
     "reason": "The original API span ended at 727 and omitted 諱日亦照 [727,731); transfer those four characters back to the annual-gifts passage to match 'ngày kỵ cũng thế'."},
    {"start": 731, "end": 893, "vi": "Cap_01-VI-0188-004", "assessment": "UNKNOWN",
     "confidence": "MEDIUM", "rule": "AGGREGATE_SELECTION_AND_PHU_LY",
     "reason": "Aggregate selection introduction and full Phù Ly/Đoàn Phúc Chiêm case. Structural opening and closing total support the group, but OCR monetary amounts need verification."},
]

UNRESOLVED_VI = [
    ("Cap_01-VI-0189-001", "Starts at Han [893,905) with Duy Xuyên/Nguyễn Kim Châu and Đông Xuân/Trần Văn Kiến; detailed passage continues on Han page 3."),
    ("Cap_01-VI-0189-002", "Continuation of Duy Xuyên/Đông Xuân; not fully represented in the two-page pilot."),
    ("Cap_01-VI-0189-003", "Minh Lành/Dương Bá Tích case belongs to later Han text, not this two-page window."),
    ("Cap_01-VI-0189-004", "Phú Châu/Trần Văn Tình case belongs to later Han text, not this two-page window."),
]

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def reconstruct_han(path: Path, end: int = 905):
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    chars = [None] * end
    owners = [None] * end
    for rec in records:
        a, b = rec["global_raw_span"]
        if a >= end or b <= 0:
            continue
        text = rec["text_original"]
        if len(text) != b - a:
            raise ValueError(f"segment length mismatch: {rec['id_zh']} [{a},{b}) vs {len(text)}")
        for pos, ch in enumerate(text):
            idx = a + pos
            if idx >= end:
                continue
            if chars[idx] is not None and chars[idx] != ch:
                raise ValueError(f"conflicting OCR character at {idx}: {chars[idx]!r} vs {ch!r}")
            chars[idx] = ch
            owners[idx] = rec["id_zh"]
    missing = [i for i, ch in enumerate(chars) if ch is None]
    if missing:
        raise ValueError(f"uncovered raw Han offsets: {missing[:20]}")
    return "".join(chars), records, owners

def load_vi(path: Path):
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb["CAU_VIET"]
    headers = [c.value for c in ws[1]]
    result = {}
    for row_no, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        rec = dict(zip(headers, row))
        if rec.get("id_vi"):
            rec["_excel_row"] = row_no
            result[str(rec["id_vi"])] = rec
    return result

def audit_review_workbook(path: Path | None):
    if path is None:
        return {"provided": False}
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb["API_Row_Review"]
    headers = [c.value for c in ws[1]]
    rows = [dict(zip(headers, row)) for row in ws.iter_rows(min_row=2, values_only=True)]
    target = next((r for r in rows if r.get("Pair_ID") == "S4-T1-011"), None)
    conflict = None
    if target:
        evidence = str(target.get("Semantic_Evidence") or "")
        conflict = {
            "pair_id": target.get("Pair_ID"),
            "recorded_span": [target.get("Han_Start"), target.get("Han_End")],
            "proposed_label": target.get("Proposed_Label"),
            "evidence_mentions_664_731": "[664,731)" in evidence,
            "conflict": target.get("Han_End") == 727 and "[664,731)" in evidence,
        }
    return {
        "provided": True,
        "sha256": sha256(path),
        "api_row_count": len(rows),
        "s4_t1_011_audit": conflict,
        "note": "The review workbook's SEM-011 evidence describes [664,731), but its row-level span is [664,727); V4 uses the frozen source offsets and reconstructs [664,731) only as the corrected candidate.",
    }

def build(han_path: Path, vi_path: Path, baseline_path: Path, review_path: Path | None = None):
    raw, segs, owners = reconstruct_han(han_path)
    vi = load_vi(vi_path)
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    old_groups = baseline["groups"]
    groups = []
    for idx, rule in enumerate(RULES, start=1):
        a, b, vid = rule["start"], rule["end"], rule["vi"]
        if vid not in vi:
            raise KeyError(f"VI ID missing from source workbook: {vid}")
        vr = vi[vid]
        vtext = str(vr.get("text_vi") or "")
        overlapping = [g for g in old_groups if g["Han_Start"] < b and g["Han_End"] > a]
        old_ids = [g["Pair_ID"] for g in overlapping]
        old_api_rows = []
        for g in overlapping:
            for source in g.get("Source_Rows", []):
                if source not in old_api_rows:
                    old_api_rows.append(source)
        units = [r for r in segs if r["global_raw_span"][0] < b and r["global_raw_span"][1] > a]
        page_start = 1 if a < 446 else 2
        page_end = 1 if b <= 446 else 2
        groups.append({
            "V4_ID": f"V4-{idx:03d}",
            "Han_Start": a, "Han_End": b,
            "Han_Text": raw[a:b],
            "VI_ID": vid, "VI_Text": vtext,
            "VI_Source_Page_Start": vr.get("viet_page_start"),
            "VI_Source_Page_End": vr.get("viet_page_end"),
            "VI_Source_Flag": vr.get("co_ra_soat"),
            "VI_Source_Excel_Row": vr["_excel_row"],
            "Han_Page_Start": page_start, "Han_Page_End": page_end,
            "Han_S4_Unit_Count": len(units),
            "Alignment_Type": "N-1" if len(units) > 1 else "1-1",
            "Assessment": rule["assessment"],
            "Assessment_Status": "SOURCE_BASED_PROVISIONAL_NOT_GOLD",
            "Confidence": rule["confidence"],
            "Rule_ID": rule["rule"],
            "Reason": rule["reason"],
            "Original_API_Pair_IDs": old_ids,
            "Original_API_Rows": old_api_rows,
            "Label_Target": "UNKNOWN",
            "Review_Status": "PENDING_INDEPENDENT_REVIEW",
        })
    # All Han code points in the two-page window are either assigned or explicitly unresolved.
    aligned_end = RULES[-1]["end"]
    unresolved_han = {
        "Han_Start": aligned_end, "Han_End": 905,
        "Han_Text": raw[aligned_end:905],
        "Reason": "Only the opening names of Duy Xuyên/Nguyễn Kim Châu and Đông Xuân/Trần Văn Kiến are visible here; the Vietnamese case continues on Han page 3.",
        "Candidate_VI_ID": "Cap_01-VI-0189-001",
        "Status": "PARTIAL_UNRESOLVED_NOT_AN_ALIGNMENT",
    }
    # Validate monotonic, non-overlapping aligned spans.
    cursor = 0
    for g in groups:
        if g["Han_Start"] != cursor:
            raise ValueError(f"non-contiguous V4 span: expected {cursor}, got {g['Han_Start']}")
        if g["Han_End"] <= g["Han_Start"]:
            raise ValueError("empty/reversed V4 span")
        cursor = g["Han_End"]
    if cursor != aligned_end:
        raise ValueError(f"unexpected aligned end: {cursor}")
    if unresolved_han["Han_Start"] != cursor or unresolved_han["Han_End"] != 905:
        raise ValueError("unresolved Han tail does not continue aligned spans")
    for g in groups:
        if g["Han_Text"] != raw[g["Han_Start"]:g["Han_End"]]:
            raise ValueError(f"Han reconstruction mismatch: {g['V4_ID']}")
        if not g["VI_Text"]:
            raise ValueError(f"empty VI text: {g['VI_ID']}")
    if groups[8]["Han_Text"][:2] != "有印":
        raise ValueError("offset 545 must start with 有印; boundary is invalid")
    if "諱日亦照" not in groups[10]["Han_Text"]:
        raise ValueError("memorial-day clause not included in VI 0188-003 group")
    if groups[10]["Han_End"] != 731 or groups[11]["Han_Start"] != 731:
        raise ValueError("annual-gifts/selection boundary must be 731")
    if any(g["VI_ID"].endswith(("0189-002", "0189-003", "0189-004")) for g in groups):
        raise ValueError("out-of-window VI IDs must not be forced into this pilot")
    return {
        "version": "Stage04-V4-pilot",
        "status": "CANDIDATE_NOT_PRODUCTION",
        "scope": "Cap_01 Han pages 1-2; VI IDs 0186-001 through 0189-004",
        "offline_only": True,
        "no_api_calls": True,
        "source_hashes": {
            "han_segments": sha256(han_path),
            "vi_workbook": sha256(vi_path),
            "baseline_reconstruction": sha256(baseline_path),
            "verified_review_workbook": sha256(review_path) if review_path else None,
        },
        "review_workbook_audit": audit_review_workbook(review_path),
        "han_window": {"start": 0, "end": 905, "characters": 905},
        "groups": groups,
        "unresolved_han": [unresolved_han],
        "unresolved_vi": [{"VI_ID": vid, "Reason": reason, "Status": "UNRESOLVED_REQUIRES_HAN_PAGE_3"} for vid, reason in UNRESOLVED_VI],
        "validation": {
            "han_reconstruction": "PASS",
            "non_overlapping_spans": "PASS",
            "complete_han_accounting_including_unresolved": "PASS",
            "vi_source_text_identity": "PASS",
            "boundary_545_starts_with_you_yin": "PASS",
            "memorial_day_clause_in_0188_003": "PASS",
            "page3_continuations_not_forced": "PASS",
        },
    }

def write_xlsx(result, out: Path):
    wb = Workbook()
    readme = wb.active
    readme.title = "Readme"
    notes = [
        ("Version", result["version"]),
        ("Status", result["status"]),
        ("Scope", result["scope"]),
        ("Important", "This is a source-grounded pilot candidate, not a production release and not expert-adjudicated Gold."),
        ("No API", "No Separate or Alignment API requests are made by this build."),
        ("Strict labels", "TRUE/FALSE/UNKNOWN in Assessment are source-based provisional judgments. Label_Target remains UNKNOWN for every group."),
        ("Han offsets", "Zero-based, end-exclusive Unicode code-point offsets over the joined two-page raw Han OCR window [0,905)."),
        ("Review-file conflict", "The verified review workbook's SEM-011 evidence says [664,731), but its row-level span is [664,727). V4 trusts the frozen source offsets, not the inconsistent prose, and creates [664,731) only as a corrected candidate."),
        ("Boundary correction", "The original API group S4-T1-011 ended at 727, not 731. V4 transfers 諱日亦照 [727,731) from the next row to VI 0188-003."),
        ("Seal-fee boundary", "V4 uses offset 545 because the Han text at 545 begins 有印. The proposed boundary 547 is rejected."),
        ("Unresolved", "Han [893,905) is only the opening of VI 0189-001; detailed continuation and VI 0189-002/003/004 require Han page 3."),
        ("Production gate", "Run fresh held-out windows from both Caps, independently review changed groups, then integrate. Do not generalize these page-specific cues blindly."),
    ]
    for r in notes: readme.append(r)
    readme.column_dimensions["A"].width = 28
    readme.column_dimensions["B"].width = 120
    for row in readme.iter_rows():
        for c in row:
            c.alignment = Alignment(vertical="top", wrap_text=True)
            c.border = Border(bottom=Side(style="thin", color="D9E1F2"))
    for c in readme[1]:
        c.fill = PatternFill("solid", fgColor="17365D"); c.font = Font(bold=True, color="FFFFFF")
    for row in readme.iter_rows(min_row=2):
        row[0].font = Font(bold=True, color="17365D")
    readme.freeze_panes = "A2"

    ws = wb.create_sheet("V4_Alignment")
    headers = ["V4_ID","Han_Start","Han_End","Han_Text","VI_ID","VI_Text","Alignment_Type","Han_S4_Unit_Count","Assessment","Assessment_Status","Confidence","Rule_ID","Reason","Original_API_Pair_IDs","Original_API_Rows","VI_Source_Page_Start","VI_Source_Page_End","VI_Source_Flag","Label_Target","Review_Status"]
    ws.append(headers)
    for g in result["groups"]:
        ws.append([
            g["V4_ID"],g["Han_Start"],g["Han_End"],g["Han_Text"],g["VI_ID"],g["VI_Text"],g["Alignment_Type"],g["Han_S4_Unit_Count"],
            g["Assessment"],g["Assessment_Status"],g["Confidence"],g["Rule_ID"],g["Reason"],
            ", ".join(g["Original_API_Pair_IDs"]),json.dumps(g["Original_API_Rows"],ensure_ascii=False),
            g["VI_Source_Page_Start"],g["VI_Source_Page_End"],g["VI_Source_Flag"],g["Label_Target"],g["Review_Status"]
        ])
    unresolved = wb.create_sheet("Unresolved")
    unresolved.append(["Side","Start","End","ID","Text_or_Reason","Status"])
    for h in result["unresolved_han"]:
        unresolved.append(["Han",h["Han_Start"],h["Han_End"],h["Candidate_VI_ID"],h["Han_Text"]+"\n"+h["Reason"],h["Status"]])
    for v in result["unresolved_vi"]:
        unresolved.append(["Vietnamese",None,None,v["VI_ID"],v["Reason"],v["Status"]])
    changes = wb.create_sheet("Change_Log")
    changes.append(["Rule_ID","Han_Span","VI_ID","Change","Evidence / Caveat"])
    for g in result["groups"]:
        changes.append([g["Rule_ID"],f'[{g["Han_Start"]},{g["Han_End"]})',g["VI_ID"],g["Reason"],g["Assessment"]+"; "+g["Confidence"]])
    metrics = wb.create_sheet("Metrics")
    mapped = sum(g["Han_End"]-g["Han_Start"] for g in result["groups"])
    metrics.append(["Metric","Value","Interpretation"])
    metrics.append(["Aligned Han chars",mapped,"Han characters assigned to candidate groups."])
    metrics.append(["Han window chars",905,"Two-page OCR window."])
    metrics.append(["Aligned Han coverage",mapped/905,"The remaining 12 characters are explicitly unresolved, not discarded."])
    metrics.append(["Han accounted incl. unresolved",1.0,"All 905 characters are either aligned candidates or in the unresolved tail."])
    metrics.append(["Candidate VI IDs",len(result["groups"]),"One candidate group per VI ID through VI 0188-004."])
    metrics.append(["Unresolved VI IDs",len(result["unresolved_vi"]),"VI 0189-001 through 004 require Han page 3."])
    counts = Counter(g["Assessment"] for g in result["groups"])
    metrics.append(["Provisional TRUE",counts["TRUE"],"Not Gold; source-based preliminary assessment."])
    metrics.append(["Provisional FALSE",counts["FALSE"],"Not Gold; strict complete-match criterion."])
    metrics.append(["Provisional UNKNOWN",counts["UNKNOWN"],"Not Gold; numeric/repetition uncertainty."])
    for sheet in wb.worksheets:
        sheet.freeze_panes = "A2"
        sheet.sheet_view.showGridLines = False
        sheet.auto_filter.ref = sheet.dimensions if sheet.max_row > 1 else "A1"
        for c in sheet[1]:
            c.fill = PatternFill("solid", fgColor="17365D")
            c.font = Font(bold=True, color="FFFFFF")
            c.alignment = Alignment(wrap_text=True, vertical="center")
        for row in sheet.iter_rows(min_row=2):
            for c in row:
                c.alignment = Alignment(wrap_text=True, vertical="top")
        if sheet.title == "V4_Alignment":
            widths = [12,12,12,65,32,95,15,18,14,34,14,34,80,40,38,15,15,35,14,30]
        elif sheet.title == "Readme":
            widths = [28,120]
        elif sheet.title == "Unresolved":
            widths = [16,12,12,32,95,38]
        elif sheet.title == "Change_Log":
            widths = [38,16,32,95,35]
        else:
            widths = [32,25,90]
        for i,w in enumerate(widths,1):
            sheet.column_dimensions[get_column_letter(i)].width = w
        for r in range(2,sheet.max_row+1):
            sheet.row_dimensions[r].height = 70 if sheet.title != "Readme" else 38
    wb.save(out)

def write_report(result, out: Path):
    counts = Counter(g["Assessment"] for g in result["groups"])
    aligned = sum(g["Han_End"]-g["Han_Start"] for g in result["groups"])
    lines = [
        "# Stage 04 V4 — Source-grounded pilot",
        "",
        "**Status: CANDIDATE_NOT_PRODUCTION**",
        "",
        "## What V4 changes",
        "",
        "V4 starts from the frozen S4-T1 API replay and applies source-backed, offset-preserving corrections. It does not call Separate or Alignment API.",
        "",
        "| # | Han span | Vietnamese ID | Operation | Assessment |",
        "|---:|---|---|---|---|",
    ]
    for g in result["groups"]:
        lines.append(f'| {g["V4_ID"]} | [{g["Han_Start"]},{g["Han_End"]}) | {g["VI_ID"]} | {g["Rule_ID"]} | {g["Assessment"]} |')
    lines += [
        "",
        "## Important adjudications",
        "",
        "- **Annual-gifts boundary:** the frozen API row S4-T1-011 ends at 727. It does not contain 諱日亦照. The verified review workbook has an internal contradiction: its SEM-011 prose describes [664,731), but the row-level offsets are [664,727). V4 follows the offsets and transfers [727,731) to VI 0188-003, making [664,731) the corrected candidate span; [731,758) begins the selection passage.",
        "- **Seal-fee boundary:** V4 uses 545 because the OCR at that offset begins 有印. The alternative 547 cuts inside the next fee opening and is rejected.",
        "- **Phù Ly:** V4 aggregates [731,893) for VI 0188-004. The detailed money OCR remains uncertain, so the group stays UNKNOWN.",
        "- **Page-3 continuation:** [893,905) is retained as an unresolved Han prefix for VI 0189-001. VI 0189-001 through 004 are not forced into the two-page alignment.",
        "- **Missing span:** [166,213) is restored to VI 0186-003; numerical OCR remains unverified.",
        "",
        "## Coverage",
        "",
        f"- Candidate-aligned Han: {aligned}/905 = {aligned/905:.1%}.",
        "- Explicitly unresolved Han: [893,905), 12 characters.",
        "- Han accounting including unresolved: 905/905 = 100%.",
        "- Candidate VI IDs: 12 (0186-001 through 0188-004).",
        "- Unresolved VI IDs: 4 (0189-001 through 0189-004), pending Han page 3.",
        f"- Source-based provisional labels: TRUE {counts['TRUE']}, FALSE {counts['FALSE']}, UNKNOWN {counts['UNKNOWN']}.",
        "",
        "These labels are not expert-adjudicated Gold. `Label_Target` remains UNKNOWN for every group.",
        "",
        "## Known limitations",
        "",
        "1. VI 0186-001 is a source fragment cut at the beginning; it is retained but FALSE under the strict complete-match rule.",
        "2. VI 0187-001 and 0187-002 contain numeric discrepancies requiring visual review.",
        "3. VI 0187-005 and 0188-001 contain similar Vietnamese closing clauses; their full semantic attribution remains UNKNOWN despite the source cue at 545.",
        "4. VI 0188-004 contains many OCR-sensitive amounts; structural completeness does not prove exact semantic equivalence.",
        "5. This is one Cap_01 pilot window. Do not apply its page-specific boundary cues as universal rules.",
        "",
        "## Next production gate",
        "",
        "Extend the same provenance-aware procedure to Han page 3 to resolve VI 0189-001..004, then test frozen V4 rules on fresh held-out windows from both Caps. Only after independent review should V4 be promoted to production.",
        "",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--han-segments", type=Path, required=True)
    ap.add_argument("--vi-workbook", type=Path, required=True)
    ap.add_argument("--baseline-json", type=Path, required=True)
    ap.add_argument("--review-workbook", type=Path, default=None)
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    result = build(args.han_segments, args.vi_workbook, args.baseline_json, args.review_workbook)
    (args.out_dir/"v4_alignment.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    write_xlsx(result,args.out_dir/"v4_alignment.xlsx")
    write_report(result,args.out_dir/"v4_report.md")
    print(json.dumps({"status":result["status"],"groups":len(result["groups"]),"unresolved_han":len(result["unresolved_han"]),"unresolved_vi":len(result["unresolved_vi"]),"validation":result["validation"]},ensure_ascii=False,indent=2))

if __name__ == "__main__":
    main()
