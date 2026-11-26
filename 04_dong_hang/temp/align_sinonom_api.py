#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pure API Hán–Việt alignment via Kim Hán Nôm sentence-alignment endpoint.

Install: pip install pandas openpyxl requests
Windows PowerShell:
  $env:SINONOM_TOKEN = "YOUR_TOKEN_VALUE"
Windows CMD:
  set "SINONOM_TOKEN=YOUR_TOKEN_VALUE"
  python align_sinonom_api.py 1 3 10 20
  python align_sinonom_api.py 1 3 10 20 --save-raw

Uses the same CSV layout as align_v16_fixed.py:
  <base-dir>/03_text_sach/Cap_01/HAN/3-cleaned.csv  (column: text_zh)
  <base-dir>/03_text_sach/Cap_01/VIET/vi_cleaned.csv (columns: text_vi, page_start)
No embeddings, anchors, LLM prompts, or local DP.
"""
import argparse
import json
import os
import re
import time
from pathlib import Path

import pandas as pd
import requests
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

SCRIPT_DIR = Path(__file__).resolve().parent
API_URL = "https://kimhannom.fit.hcmus.edu.vn/api/web/clc-sinonom/sentence-alignment"
SENT_PER_PAGE = 16
HEADERS = ["Pair_ID", "Chinese", "Vietnamese", "OMISSION", "ADDITION", "MISSING",
           "Alignment_Type", "Punct_Anchor_Match", "Label_Target", "OCR_Conf_Min", "Note"]
DESCRIPTIONS = [
    "Mã định danh cặp câu (VD: C001_V001) là số trang pdf Hán - Việt trong phần được cấp",
    "Câu hoặc cặp câu tiếng Hán trích xuất từ ảnh nguồn",
    "Câu hoặc cặp câu tiếng Việt tương ứng trích xuất từ ảnh đích",
    "1 (True) / 0 (False): Thiếu nội dung quan trọng ở vế Việt",
    "1 (True) / 0 (False): Thừa nội dung ở vế Việt",
    "1 (True) / 0 (False): Khuyết toàn bộ vế Hán hoặc Việt",
    "Loại liên kết: 1-1, 1-N, N-1, N-M, 1-0, 0-1",
    "1 / 0: Khớp dấu câu đặc biệt hoặc số đếm/niên hiệu Hán-Việt",
    "Nhãn huấn luyện cuối cùng: 1 = chính xác hoàn toàn; 0 = không chính xác",
    "Độ tin cậy OCR thấp nhất của các ký tự trong cặp câu",
    "Thông tin dò lỗi, chỉ số và score của API (không phải Label_Target)",
]
COLORS = ["1F4E79"] * 3 + ["843C0C"] * 3 + ["2F5597"] * 2 + ["375623", "2F5597", "1F4E79"]
WIDTHS = [16, 40, 70, 14, 14, 14, 18, 20, 18, 16, 60]


def split_vi_text(value):
    """Match v16 preprocessing; indices sent to the API refer to these chunks."""
    if pd.isna(value):
        return []
    return [x.strip() for x in re.split(r"(?<=[.;?!,])\s+", str(value).strip()) if x.strip()]


def find_han_file(folder, page):
    for width in range(1, 8):
        path = folder / f"{page:0{width}d}-cleaned.csv"
        if path.exists():
            return path
    return None


def call_api(han, vi, token=None, timeout=120, retries=3):
    """Call the website's API using Authorization: Bearer <token>."""
    token = (token or "").strip()
    if not token:
        raise ValueError(
            "Thiếu token. Trong PowerShell chạy: "
            '$env:SINONOM_TOKEN = "YOUR_TOKEN_VALUE"'
        )
    # Accept either raw token or an already prefixed value.
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "Mozilla/5.0",
    })
    for attempt in range(retries + 1):
        try:
            resp = session.post(API_URL, json={"han": "\n".join(han), "vi": "\n".join(vi)}, timeout=timeout)
            resp.raise_for_status()
            body = resp.json()
            if not isinstance(body, dict) or body.get("is_success") is not True:
                raise ValueError(f"API báo lỗi: {str(body)[:600]}")
            result = body.get("data", {}).get("result")
            if not isinstance(result, list):
                raise ValueError("API response thiếu data.result dạng list")
            return body
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status in (400, 401, 403, 404, 422):
                detail = (e.response.text if e.response is not None else "")[:700]
                raise RuntimeError(
                    f"HTTP {status}: API từ chối yêu cầu. "
                    f"Kiểm tra Bearer token, quyền truy cập và request. "
                    f"Server response: {detail}"
                ) from e
            error = e
        except (requests.RequestException, ValueError) as e:
            error = e
        if attempt == retries:
            raise RuntimeError(f"API failed after {retries + 1} attempts: {error}") from error
        time.sleep(min(2 ** attempt, 8))
    raise RuntimeError("API unreachable")


def parse_api_alignments(result, n_han, n_vi):
    """Validate inclusive 0-based response ranges, preserving API decisions as-is."""
    steps = []
    covered_h, covered_v = set(), set()
    for k, item in enumerate(result):
        if not isinstance(item, dict):
            raise ValueError(f"result[{k}] is not an object")
        hs, he = item.get("han_start"), item.get("han_end")
        vs, ve = item.get("vi_start"), item.get("vi_end")
        if all(type(v) is int and v == -1 for v in (hs, he)):
            hi = []
        elif all(type(v) is int for v in (hs, he)) and 0 <= hs <= he < n_han:
            hi = list(range(hs, he + 1))
        else:
            raise ValueError(f"Invalid Han range at result[{k}]: {hs}..{he}")
        if all(type(v) is int and v == -1 for v in (vs, ve)):
            vi = []
        elif all(type(v) is int for v in (vs, ve)) and 0 <= vs <= ve < n_vi:
            vi = list(range(vs, ve + 1))
        else:
            raise ValueError(f"Invalid Viet range at result[{k}]: {vs}..{ve}")
        if not hi and not vi:
            raise ValueError(f"Both sides empty at result[{k}]")
        if covered_h.intersection(hi) or covered_v.intersection(vi):
            raise ValueError(f"Overlapping API ranges at result[{k}]; raw result saved if --save-raw")
        covered_h.update(hi)
        covered_v.update(vi)
        steps.append({"h": hi, "v": vi, "score": item.get("score")})

    # Unmentioned lines are displayed as unmatched, never silently dropped.
    for i in range(n_han):
        if i not in covered_h:
            steps.append({"h": [i], "v": [], "score": None})
    for j in range(n_vi):
        if j not in covered_v:
            steps.append({"h": [], "v": [j], "score": None})
    steps.sort(key=lambda s: (s["h"][0] if s["h"] else float("inf"),
                              s["v"][0] if s["v"] else float("inf")))
    return steps


def alignment_type(h, v):
    if not h: return "0-1"
    if not v: return "1-0"
    if len(h) == 1 and len(v) == 1: return "1-1"
    if len(h) == 1: return "1-N"
    if len(v) == 1: return "N-1"
    return "N-M"


def write_xlsx(rows, output):
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    side = Side(style="thin", color="BFBFBF")
    border = Border(left=side, right=side, top=side, bottom=side)
    for col, (name, color) in enumerate(zip(HEADERS, COLORS), 1):
        cell = ws.cell(1, col, name)
        cell.font = Font(bold=True, color="FFFFFF", size=12)
        cell.fill = PatternFill("solid", fgColor=color)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border
    for col, desc in enumerate(DESCRIPTIONS, 1):
        cell = ws.cell(2, col, desc)
        cell.font = Font(italic=True, size=10)
        cell.fill = PatternFill("solid", fgColor="D9E1F2")
        cell.alignment = Alignment(vertical="top", wrap_text=True)
        cell.border = border
    for row_num, row in enumerate(rows, 3):
        for col, header in enumerate(HEADERS, 1):
            cell = ws.cell(row_num, col, row.get(header))
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = border
    for col, width in enumerate(WIDTHS, 1):
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.row_dimensions[1].height = 32
    ws.row_dimensions[2].height = 105
    ws.freeze_panes = "A3"
    wb.save(output)


def run(args):
    base = args.base_dir or SCRIPT_DIR.parent
    cap_dir = base / "03_text_sach" / f"Cap_{args.cap:02d}"
    han_path = find_han_file(cap_dir / "HAN", args.page)
    vi_path = cap_dir / "VIET" / "vi_cleaned.csv"
    if han_path is None:
        raise FileNotFoundError(f"Missing Chinese CSV: {cap_dir / 'HAN'} (page {args.page})")
    if not vi_path.exists():
        raise FileNotFoundError(f"Missing Vietnamese CSV: {vi_path}")
    df_h = pd.read_csv(han_path, encoding="utf-8-sig")
    df_v = pd.read_csv(vi_path, encoding="utf-8-sig")
    if "text_zh" not in df_h or not {"text_vi", "page_start"}.issubset(df_v.columns):
        raise ValueError("Required CSV columns: text_zh; text_vi, page_start")
    df_h = df_h.dropna(subset=["text_zh"])
    df_v = df_v.dropna(subset=["text_vi", "page_start"])
    if args.vi_start is not None:
        df_v = df_v[pd.to_numeric(df_v.page_start, errors="coerce") >= args.vi_start]
    if args.vi_end is not None:
        df_v = df_v[pd.to_numeric(df_v.page_start, errors="coerce") <= args.vi_end]
    han = df_h.text_zh.astype(str).str.strip().tolist()
    chunks = [
        {"text": chunk, "page": row.page_start, "row": int(idx)}
        for idx, row in df_v.reset_index(drop=True).iterrows()
        for chunk in split_vi_text(row.text_vi)
    ]
    vi = [item["text"] for item in chunks]
    if not han or not vi:
        raise ValueError("No Chinese/Vietnamese sentences found in selected range")
    if "\n" in "".join(han):
        raise ValueError("A Chinese input row contains a newline; API uses newline as sentence boundary")
    print(f"Cap {args.cap} | Han page {args.page}: {len(han)} lines | Viet: {len(vi)} chunks")
    print(f"POST {API_URL}")
    body = call_api(han, vi, args.token, timeout=args.timeout, retries=args.retries)
    output_dir = args.output_dir or SCRIPT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"KetQua_Cap{args.cap:02d}_Trang{args.page}_SinoNomAPI"
    if args.save_raw:
        raw_path = output_dir / f"{stem}.json"
        raw_path.write_text(json.dumps({"input": {"han": han, "vi": vi}, "response": body},
                                       ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Raw API response: {raw_path}")
    steps = parse_api_alignments(body["data"]["result"], len(han), len(vi))
    rows = []
    for step_no, step in enumerate(steps, 1):
        hi, vj = step["h"], step["v"]
        h_text = "\n".join(han[i] for i in hi)
        v_text = "\n".join(vi[j] for j in vj)
        pair_no = (args.page - 1) * SENT_PER_PAGE + (hi[0] + 1 if hi else len(han) + step_no)
        score = step["score"]
        score_text = "-" if score is None else str(score)
        pages = ", ".join(dict.fromkeys(str(chunks[j]["page"]) for j in vj)) or "-"
        rows.append({
            "Pair_ID": f"C{args.cap:03d}_V{pair_no:03d}" if hi else f"C{args.cap:03d}_EXTRA_{step_no:03d}",
            "Chinese": h_text,
            "Vietnamese": v_text,
            "Alignment_Type": alignment_type(hi, vj),
            # Do not fabricate binary labels or omission/addition judgments.
            "Note": (f"SinoNom API score: {score_text} | "
                     f"Han indices: {hi} | Viet indices: {vj} | Viet pages: {pages}"),
        })
    output = output_dir / f"{stem}.xlsx"
    write_xlsx(rows, output)
    print(f"Saved: {output} | API groups: {len(body['data']['result'])} | Exported rows: {len(rows)}")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cap", type=int)
    parser.add_argument("page", type=int)
    parser.add_argument("vi_start", type=int, nargs="?", default=None)
    parser.add_argument("vi_end", type=int, nargs="?", default=None)
    parser.add_argument("--base-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--token", default=os.getenv("SINONOM_TOKEN", ""), help="Giá trị cookie token, được gửi bằng Authorization: Bearer")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--save-raw", action="store_true")
    args = parser.parse_args()
    if args.vi_start is not None and args.vi_end is not None and args.vi_start > args.vi_end:
        parser.error("vi_start must be <= vi_end")
    run(args)


if __name__ == "__main__":
    main()
