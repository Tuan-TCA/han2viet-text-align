#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pure LLM API Hán–Việt alignment (NO embeddings, anchors or DP).

Install: pip install pandas openpyxl requests

Quick start (OpenAI-compatible chat endpoint):
  set ALIGN_API_URL=https://provider.example/v1/chat/completions
  set ALIGN_API_TOKEN=your_api_key
  set ALIGN_API_MODEL=your_chat_model
  python align_pure_api.py 1 3 10 20 --auth bearer

Browser cookie session (ONLY if the website offers an authorized JSON API):
  set ALIGN_API_URL=https://your-site.example/actual/api/endpoint
  set ALIGN_API_TOKEN=your_session_token
  python align_pure_api.py 1 3 10 20 --auth cookie --cookie-name token

Unknown/non-OpenAI API? Supply a JSON request template file and response path:
  python align_pure_api.py 1 3 --auth cookie --request-template request.json \
      --response-path data.answer

Example request.json (placeholders in strings get substituted):
  {"model": "{model}", "messages": [
    {"role":"system", "content":"{system_prompt}"},
    {"role":"user", "content":"{user_prompt}"}
  ]}

NOTE: Browser cookies are NOT automatically API keys. Obtain the actual endpoint,
request JSON shape, and response shape from the service's documented API (or an
API for which you have permission). Never share session cookies.
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
SENT_PER_PAGE = 16

HEADERS = [
    "Pair_ID", "Chinese", "Vietnamese", "OMISSION", "ADDITION", "MISSING",
    "Alignment_Type", "Punct_Anchor_Match", "Label_Target", "OCR_Conf_Min", "Note",
]
DESCRIPTIONS = [
    "Mã định danh cặp câu (VD: C001_V001) là số trang pdf Hán - Việt trong phần được cấp",
    "Câu hoặc cặp câu tiếng Hán trích xuất từ ảnh nguồn",
    "Câu hoặc cặp câu tiếng Việt tương ứng trích xuất từ ảnh đích",
    "1 (True) / 0 (False): Thiếu nội dung vế Việt bỏ phần quan trọng của vế Hán hoặc mất đoạn nguồn",
    "1 (True) / 0 (False): Thừa nội dung vế Việt chứa câu khác, chú thích lệch hoặc sai phạm vi cặp",
    "1 (True) / 0 (False): Khuyết toàn bộ vế Hán hoặc Việt (1-0, 0-1) hoặc đoạn tương ứng bị bỏ sót",
    "Loại liên kết: 1-1 (đơn), 1-N (tách câu), N-1 (gộp câu), N-M, 1-0, 0-1",
    "1 / 0: Khớp dấu câu đặc biệt (?, !, ;, :, « ») hoặc số đếm/niên hiệu Hán-Việt",
    "Nhãn huấn luyện cuối cùng: 1 (Aligned chuẩn) / 0 (Misaligned - có lỗi Omission/Addition/Missing)",
    "Độ tin cậy OCR thấp nhất của các ký tự trong cặp câu [0.0 - 1.0] để lọc nhiều ảnh mờ",
    "Ghi chú chi tiết lỗi OCR, dị bản chữ Hán/Nôm hoặc giải thích chú thích công cụ sử dụng (nếu có)",
]
COLORS = ["1F4E79"]*3 + ["843C0C"]*3 + ["2F5597"]*2 + ["375623", "2F5597", "1F4E79"]
WIDTHS = [16, 40, 70, 14, 14, 14, 18, 20, 18, 16, 60]

SYSTEM_PROMPT = """You are a professional Chinese-to-Vietnamese semantic sentence aligner.
The Vietnamese is a MEANING TRANSLATION, not a phonetic transliteration.
Align the given Chinese sentence units against the given Vietnamese text units by meaning.
Use the full context. Never invent, rewrite, paraphrase or translate the original text.
Return exactly one JSON object and NO markdown:
{"alignments":[{"zh":[0],"vi":[0,1]}, {"zh":[1],"vi":[]} ]}
All indices are 0-based into the input arrays.
Rules:
- Each Chinese index must occur exactly once; each Vietnamese index at most once.
- Preserve the original order (monotonic, non-crossing alignments).
- You MAY group adjacent Chinese units and adjacent Vietnamese units (N-M),
  or mark Chinese units unmatched with vi=[].
- Add an insertion step with zh=[] and vi=[j] for Vietnamese content without Chinese source.
- Every Vietnamese index must occur exactly once, including inserted/unmatched content.
- Match only genuinely corresponding meanings, not merely related topics or words.
- An empty match is better than fabricating a correspondence.
- Prefer groups that cover precisely the same meaning; don't pad matches with unrelated text.
- No evaluation labels: the output is an alignment proposal, not ground truth."""


def split_vi_text(text):
    if pd.isna(text):
        return []
    return [part.strip() for part in re.split(r"(?<=[.;?!,])\s+", str(text).strip()) if part.strip()]


def find_han_file(folder, page):
    for width in range(1, 8):
        candidate = folder / f"{page:0{width}d}-cleaned.csv"
        if candidate.exists():
            return candidate
    return None


def substitute(obj, vars_):
    if isinstance(obj, str):
        for key, value in vars_.items():
            obj = obj.replace("{" + key + "}", value)
        return obj
    if isinstance(obj, list):
        return [substitute(v, vars_) for v in obj]
    if isinstance(obj, dict):
        return {k: substitute(v, vars_) for k, v in obj.items()}
    return obj


def get_path(obj, path):
    for part in path.split("."):
        if isinstance(obj, list):
            obj = obj[int(part)]
        else:
            obj = obj[part]
    return obj


def parse_json_content(content):
    if isinstance(content, dict):
        return content
    if isinstance(content, list):
        content = "".join(x.get("text", "") if isinstance(x, dict) else str(x) for x in content)
    if not isinstance(content, str):
        raise ValueError("API output must be text or an alignment JSON object")
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise ValueError("Response is not JSON: " + text[:350])
        return json.loads(match.group(0))


def validate_alignments(result, n_zh, n_vi):
    if not isinstance(result, dict) or not isinstance(result.get("alignments"), list):
        raise ValueError("Missing alignments list in model result")
    alignments = result["alignments"]
    z_seen, v_seen = [], []
    for step in alignments:
        if not isinstance(step, dict):
            raise ValueError("Alignment step must be a JSON object")
        zi, vi = step.get("zh"), step.get("vi")
        if not isinstance(zi, list) or not isinstance(vi, list) or (not zi and not vi):
            raise ValueError(f"Invalid alignment step: {step}")
        if any(type(x) is not int for x in zi + vi):
            raise ValueError("Indices must be integers")
        if zi and zi != list(range(zi[0], zi[-1] + 1)):
            raise ValueError(f"Noncontiguous Chinese step: {zi}")
        if vi and vi != list(range(vi[0], vi[-1] + 1)):
            raise ValueError(f"Noncontiguous Vietnamese step: {vi}")
        z_seen.extend(zi) 
        v_seen.extend(vi)
    if z_seen != list(range(n_zh)):
        raise ValueError(f"Chinese indices missing, duplicated or out of order: {z_seen}")
    if v_seen != list(range(n_vi)):
        raise ValueError(f"Vietnamese indices missing, duplicated or out of order: {v_seen}")
    return alignments


class DirectAPI:
    def __init__(self, args):
        self.url = args.api_url
        self.token = args.token
        self.model = args.model
        self.auth = args.auth
        self.cookie_name = args.cookie_name
        self.timeout = args.timeout
        self.retries = args.retries
        self.response_path = args.response_path
        self.session = requests.Session()
        self.request_template = None
        if args.request_template:
            with open(args.request_template, encoding="utf-8") as f:
                self.request_template = json.load(f)
        if not self.url:
            raise ValueError("Set ALIGN_API_URL or --api-url to your actual API endpoint")
        if self.auth != "none" and not self.token:
            raise ValueError("Set ALIGN_API_TOKEN or --token; do not share your token")

    def _request(self, zh_texts, vi_texts, feedback=""):
        user_prompt = json.dumps({
            "chinese": [{"index": i, "text": t} for i, t in enumerate(zh_texts)],
            "vietnamese": [{"index": i, "text": t} for i, t in enumerate(vi_texts)],
            "previous_validation_error": feedback or None,
        }, ensure_ascii=False)
        vars_ = {"model": self.model, "system_prompt": SYSTEM_PROMPT, "user_prompt": user_prompt}
        if self.request_template is None:
            payload = {"model": self.model, "temperature": 0,
                       "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                                    {"role": "user", "content": user_prompt}]}
        else:
            payload = substitute(self.request_template, vars_)
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        cookies = None
        if self.auth == "bearer":
            headers["Authorization"] = "Bearer " + self.token
        elif self.auth == "cookie":
            cookies = {self.cookie_name: self.token}
        elif self.auth == "header":
            headers[self.cookie_name] = self.token

        response = self.session.post(self.url, headers=headers, cookies=cookies,
                                     json=payload, timeout=self.timeout)
        response.raise_for_status()
        body = response.json()
        if self.response_path:
            content = get_path(body, self.response_path)
        else:
            # Default: OpenAI chat completions; also accept direct alignments JSON.
            content = body if "alignments" in body else get_path(body, "choices.0.message.content")
        return parse_json_content(content)

    def align(self, zh_texts, vi_texts):
        error = ""
        for attempt in range(self.retries + 1):
            try:
                response = self._request(zh_texts, vi_texts, feedback=error)
                return validate_alignments(response, len(zh_texts), len(vi_texts))
            except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as exc:
                error = str(exc)
                if isinstance(exc, requests.HTTPError) and exc.response is not None:
                    if exc.response.status_code in (401, 403, 404):
                        raise RuntimeError(
                            f"HTTP {exc.response.status_code}: Check API endpoint, authorization, "
                            "and whether this token is valid for this API."
                        ) from exc
                if attempt >= self.retries:
                    raise RuntimeError(f"API/validation failed after {attempt + 1} attempts: {error}") from exc
                print(f"  Attempt {attempt+1} failed: {error[:180]}; retrying...")
                time.sleep(min(2 ** attempt, 10))
        raise AssertionError("Unreachable")


def export_xlsx(rows, output):
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
    for row_idx, row in enumerate(rows, 3):
        for col, value in enumerate(row, 1):
            cell = ws.cell(row_idx, col, value)
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = border
    for col, width in enumerate(WIDTHS, 1):
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.row_dimensions[1].height = 32
    ws.row_dimensions[2].height = 105
    ws.freeze_panes = "A3"
    output.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output)


def run(args):
    base = Path(args.base_dir) if args.base_dir else SCRIPT_DIR.parent
    root = base / "03_text_sach" / f"Cap_{args.cap:02d}"
    zh_file = find_han_file(root / "HAN", args.page)
    if zh_file is None:
        raise FileNotFoundError(f"Chinese CSV not found: {root / 'HAN'} (page {args.page})")
    vi_file = root / "VIET" / "vi_cleaned.csv"
    df_zh = pd.read_csv(zh_file, encoding="utf-8-sig")
    df_vi = pd.read_csv(vi_file, encoding="utf-8-sig")
    if "text_zh" not in df_zh or not {"text_vi", "page_start"}.issubset(df_vi.columns):
        raise ValueError("Input columns required: text_zh; text_vi and page_start")
    df_zh = df_zh.dropna(subset=["text_zh"]).reset_index(drop=True)
    df_vi = df_vi.dropna(subset=["text_vi", "page_start"])
    if args.vi_start is not None:
        df_vi = df_vi[df_vi.page_start >= args.vi_start]
    if args.vi_end is not None:
        df_vi = df_vi[df_vi.page_start <= args.vi_end]
    df_vi = df_vi.reset_index(drop=True)
    zh_texts = df_zh.text_zh.astype(str).tolist()
    pieces = []
    for i, r in df_vi.iterrows():
        for text in split_vi_text(r.text_vi):
            pieces.append({"text": text, "row_id": i, "page": str(r.page_start)})
    vi_texts = [x["text"] for x in pieces]
    if not zh_texts or not vi_texts:
        raise ValueError("No Chinese or Vietnamese sentences found")
    print(f"Chinese: {len(zh_texts)} | Vietnamese fragments: {len(vi_texts)}")
    print("Using ONLY direct model API alignment; embeddings, anchors, DP are DISABLED.")
    api = DirectAPI(args)
    alignments = api.align(zh_texts, vi_texts)
    print(f"API returned {len(alignments)} validated alignment steps")

    rows = []
    for step in alignments:
        zi, vi = step["zh"], step["vi"]
        if not zi:
            # Excel template has no dedicated standalone insertion rows; keep them
            # explicitly rather than losing unmatched Vietnamese content.
            pair_id = f"C{args.cap:03d}_INSERT_V{vi[0]+1:03d}"
            chinese = ""
            vietnamese = " ".join(vi_texts[j] for j in vi)
            note = f"API-only | 0-{len(vi)} unmatched Vietnamese insertion | Vietnamese pieces: {vi}"
        else:
            sent_no = (args.page - 1) * SENT_PER_PAGE + zi[0] + 1
            pair_id = f"C{args.cap:03d}_V{sent_no:03d}"
            chinese = " ".join(zh_texts[i] for i in zi)
            vietnamese = " ".join(vi_texts[j] for j in vi)
            pages = list(dict.fromkeys(pieces[j]["page"] for j in vi))
            orig_rows = list(dict.fromkeys(str(pieces[j]["row_id"]) for j in vi))
            note = (f"API-only | Chinese indices: {zi} | Vietnamese indices: {vi} | "
                    f"Việt pages: {', '.join(pages) or '-'} | Việt rows: {', '.join(orig_rows) or '-'}")
        # No invented training labels or OCR confidences.
        alignment_type = (f"{len(zi)}-{len(vi)}" if len(zi) <= 1 and len(vi) <= 1
                          else "1-N" if len(zi) == 1 else "N-1" if len(vi) == 1 else "N-M")
        rows.append([pair_id, chinese, vietnamese, None, None, None,
                     alignment_type, None, None, None, note])

    outdir = Path(args.output_dir) if args.output_dir else SCRIPT_DIR
    outfile = outdir / f"KetQua_Cap{args.cap:02d}_Trang{args.page}_PURE_API.xlsx"
    export_xlsx(rows, outfile)
    print("Saved:", outfile)
    if args.save_raw:
        rawfile = outfile.with_suffix(".json")
        rawfile.write_text(json.dumps({"chinese": zh_texts, "vietnamese": vi_texts,
                                       "alignments": alignments}, ensure_ascii=False, indent=2),
                           encoding="utf-8")
        print("Raw alignment:", rawfile)
    return outfile


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cap", type=int)
    p.add_argument("page", type=int)
    p.add_argument("vi_start", nargs="?", type=int)
    p.add_argument("vi_end", nargs="?", type=int)
    p.add_argument("--base-dir", type=Path)
    p.add_argument("--output-dir", type=Path)
    p.add_argument("--api-url", default=os.getenv("ALIGN_API_URL", ""))
    p.add_argument("--token", default=os.getenv("ALIGN_API_TOKEN", ""))
    p.add_argument("--model", default=os.getenv("ALIGN_API_MODEL", ""))
    p.add_argument("--auth", choices=["bearer", "cookie", "header", "none"], default="bearer")
    p.add_argument("--cookie-name", default="token", help="Cookie name or header name")
    p.add_argument("--request-template", type=Path, help="Optional JSON request template")
    p.add_argument("--response-path", default="", help="Dot path e.g. choices.0.message.content")
    p.add_argument("--timeout", type=int, default=180)
    p.add_argument("--retries", type=int, default=2)
    p.add_argument("--save-raw", action="store_true")
    run(p.parse_args())


if __name__ == "__main__":
    main()
