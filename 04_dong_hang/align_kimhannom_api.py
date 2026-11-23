#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sentence alignment using ONLY the Kim Han Nom HTTP API.

Usage (PowerShell):
    $env:SINONOM_TOKEN = "YOUR_TOKEN"
    python align_kimhannom_api.py 1 12 20 22

Input (same layout as align_v16_fixed.py):
    <base-dir>/03_text_sach/Cap_01/HAN/12-cleaned.csv   (text_zh)
    <base-dir>/03_text_sach/Cap_01/VIET/vi_cleaned.csv  (text_vi, page_start)

Install: pip install requests pandas openpyxl

Raw API response is always saved as JSON. Excel is produced when the response
contains recognizable alignment pairs; unrecognized formats fail explicitly.
"""

import argparse
import json
import os
import re
from pathlib import Path

import pandas as pd
import requests
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

URL = "https://kimhannom.fit.hcmus.edu.vn/api/web/clc-sinonom/sentence-alignment"
SCRIPT_DIR = Path(__file__).resolve().parent
SENT_PER_PAGE = 16
HEADERS = [
    "Pair_ID", "Chinese", "Vietnamese", "OMISSION", "ADDITION", "MISSING",
    "Alignment_Type", "Punct_Anchor_Match", "Label_Target", "OCR_Conf_Min", "Note",
]
DESCRIPTIONS = [
    "Mã định danh cặp câu", "Vế Hán", "Vế Việt",
    "1 nếu vế Việt thiếu nội dung quan trọng (chưa đánh giá)",
    "1 nếu vế Việt có nội dung thừa (chưa đánh giá)",
    "1 nếu khuyết vế Hán hoặc Việt (chưa đánh giá)",
    "Kiểu ghép 1-1, 1-N, N-1, N-M, 1-0, 0-1 (nếu xác định được)",
    "Khớp dấu câu (chưa đánh giá)",
    "Nhãn đúng/sai theo ngữ nghĩa (chưa đánh giá)",
    "Độ tin cậy OCR (chưa có)", "Ghi chú",
]


def find_han_file(han_dir: Path, page: int) -> Path:
    for width in range(1, 8):
        path = han_dir / f"{page:0{width}d}-cleaned.csv"
        if path.is_file():
            return path
    raise FileNotFoundError(f"No Han CSV for page {page} in {han_dir}")


def split_vi_text(text: str) -> list[str]:
    # Preserve v16 segmentation: punctuation followed by whitespace.
    return [s.strip() for s in re.split(r"(?<=[.;?!,])\s+", str(text).strip()) if s.strip()]


def load_inputs(cap: int, page: int, vi_start: int | None, vi_end: int | None,
                base_dir: Path) -> tuple[list[str], list[str]]:
    cap_dir = base_dir / "03_text_sach" / f"Cap_{cap:02d}"
    han_df = pd.read_csv(find_han_file(cap_dir / "HAN", page), encoding="utf-8-sig")
    vi_df = pd.read_csv(cap_dir / "VIET" / "vi_cleaned.csv", encoding="utf-8-sig")
    if "text_zh" not in han_df or not {"text_vi", "page_start"}.issubset(vi_df.columns):
        raise ValueError("Expected columns: Han text_zh; Viet text_vi, page_start")

    vi_df["page_start"] = pd.to_numeric(vi_df["page_start"], errors="coerce")
    if vi_start is not None:
        vi_df = vi_df[vi_df["page_start"] >= vi_start]
    if vi_end is not None:
        vi_df = vi_df[vi_df["page_start"] <= vi_end]
    han = han_df["text_zh"].dropna().astype(str).str.strip().tolist()
    han = [s for s in han if s]
    vi = [piece for text in vi_df["text_vi"].dropna().astype(str)
          for piece in split_vi_text(text)]
    if not han or not vi:
        raise ValueError("Empty Han/Viet input after filtering")
    return han, vi


def call_api(han: list[str], vi: list[str], token: str) -> dict:
    token = token.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token:
        raise ValueError('Missing token: PowerShell: $env:SINONOM_TOKEN = "YOUR_TOKEN"')
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
    }
    response = requests.post(URL, json={"han": "\n".join(han), "vi": "\n".join(vi)},
                             headers=headers, timeout=120)
    response.raise_for_status()
    try:
        envelope = response.json()
    except ValueError as exc:
        raise RuntimeError(f"API returned non-JSON response: {response.text[:500]}") from exc
    if not isinstance(envelope, dict) or envelope.get("code") != "000000" or envelope.get("is_success") is not True:
        raise RuntimeError(f"Kim Han Nom API error: {json.dumps(envelope, ensure_ascii=False)[:1500]}")
    return envelope


def text_value(value, original: list[str]) -> str:
    """Convert API text, arrays of text, or explicit {indices: ...} to text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for name in ("text", "sentence", "content"):
            if name in value:
                return text_value(value[name], original)
        if "indices" in value:
            ids = value["indices"]
            if not isinstance(ids, list) or any(not isinstance(i, int) or i < 0 or i >= len(original) for i in ids):
                raise ValueError(f"Invalid API indices: {ids}")
            return " ".join(original[i] for i in ids)
    if isinstance(value, list):
        return " ".join(text_value(item, original) for item in value)
    raise ValueError(f"Unrecognized API text field: {value!r}")


def parse_alignment(envelope: dict, han: list[str], vi: list[str]) -> list[tuple[str, str]]:
    data = envelope.get("data")
    result = data.get("result") if isinstance(data, dict) else None
    if not isinstance(result, list):
        raise ValueError("Expected data.result to be a list; inspect the saved JSON")
    pairs = []
    for number, group in enumerate(result, 1):
        if isinstance(group, dict):
            h = next((group[k] for k in ("han", "chinese", "zh", "source", "src") if k in group), None)
            v = next((group[k] for k in ("vi", "vietnamese", "target", "tgt") if k in group), None)
            if h is None and v is None:
                raise ValueError(f"Unrecognized alignment group #{number}: {group!r}")
        elif isinstance(group, (list, tuple)) and len(group) == 2:
            h, v = group
        else:
            raise ValueError(f"Unrecognized alignment group #{number}: {group!r}")
        pairs.append((text_value(h, han), text_value(v, vi)))
    return pairs


def export_excel(pairs: list[tuple[str, str]], cap: int, page: int, destination: Path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    for col, (name, description) in enumerate(zip(HEADERS, DESCRIPTIONS), 1):
        cell = ws.cell(1, col, name)
        cell.fill = PatternFill("solid", fgColor="1F4E79")
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(wrap_text=True)
        ws.cell(2, col, description).alignment = Alignment(wrap_text=True)
    for index, (chinese, vietnamese) in enumerate(pairs):
        # Consecutive output IDs; API can merge or split source sentences.
        pair_id = f"C{cap:03d}_V{(page - 1) * SENT_PER_PAGE + index + 1:03d}"
        typ = f"{int(bool(chinese))}-{int(bool(vietnamese))}"  # Only indicate presence; NOT true group cardinality.
        values = [pair_id, chinese, vietnamese, None, None, None,
                  None, None, None, None, f"Kim Han Nom API | output group {index + 1} | presence {typ}"]
        for col, value in enumerate(values, 1):
            ws.cell(index + 3, col, value).alignment = Alignment(vertical="top", wrap_text=True)
    for col, width in enumerate([19, 50, 75, 14, 14, 14, 20, 22, 18, 16, 60], 1):
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.row_dimensions[2].height = 75
    ws.freeze_panes = "A3"
    wb.save(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cap", type=int)
    parser.add_argument("page", type=int)
    parser.add_argument("vi_start", type=int, nargs="?", default=None)
    parser.add_argument("vi_end", type=int, nargs="?", default=None)
    parser.add_argument("--base-dir", type=Path, default=SCRIPT_DIR.parent)
    parser.add_argument("--output-dir", type=Path, default=SCRIPT_DIR)
    args = parser.parse_args()

    han, vi = load_inputs(args.cap, args.page, args.vi_start, args.vi_end, args.base_dir)
    print(f"Inputs: {len(han)} Han sentences, {len(vi)} Vietnamese fragments")
    envelope = call_api(han, vi, os.getenv("SINONOM_TOKEN", ""))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"KetQua_Cap{args.cap:02d}_Trang{args.page}"
    json_path = args.output_dir / f"{stem}_api.json"
    json_path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Raw API JSON:", json_path)
    try:
        pairs = parse_alignment(envelope, han, vi)
    except ValueError as exc:
        raise RuntimeError(f"API succeeded, but cannot safely parse its alignment format: {exc}. "
                           f"Check {json_path}") from exc
    xlsx_path = args.output_dir / f"{stem}.xlsx"
    export_excel(pairs, args.cap, args.page, xlsx_path)
    print(f"Saved {len(pairs)} alignment groups: {xlsx_path}")


if __name__ == "__main__":
    main()
