#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lấy text từ PDF (có lớp text) bằng pdfplumber, tách câu và lưu theo từng trang:

    OUT_DIR/
    ├── 0170/
    │   ├── 0170_sentences.txt     mỗi câu một dòng
    │   ├── 0170_sentences.csv     id, confidence, page_end, text, các cờ kiểm tra
    │   └── 0170_page_text.txt     text thô pdfplumber trả về (để đối chiếu)
    ├── 0171/ ...
    ├── all_sentences.csv / all_sentences.jsonl
    └── summary.csv                trang, số dòng, số câu, confidence TB, số in trên trang

LƯU Ý VỀ "ĐỘ TIN CẬY":
  pdfplumber đọc lớp text có sẵn trong PDF, không chạy OCR nên KHÔNG có điểm tin cậy của OCR.
  `confidence` ở đây là điểm heuristic 0–1 đo mức "text có sạch không": tỉ lệ ký tự hợp lệ
  (chữ Latin có dấu, chữ số, dấu câu); lỗi font như (cid:123), ký tự thay thế U+FFFD, ký tự lạ
  sẽ làm điểm giảm. 1.0 = sạch. Nó KHÔNG đảm bảo chữ đúng 100%.
  Nếu PDF là bản quét (chỉ có ảnh), pdfplumber không lấy được text -> dùng notebook OCR.

Chạy:   python pdf_text_to_sentences.py --pdf VIET.pdf --out ./out --start 170 --end 190
Trong notebook/Kaggle: dán vào một cell và chạy (cần `pip install pdfplumber` nếu chưa có).
"""
import argparse
import csv
import json
import re
import unicodedata
from pathlib import Path

import numpy as np

try:
    import pdfplumber
except ImportError as e:
    raise SystemExit("Thiếu pdfplumber. Cài bằng: pip install pdfplumber") from e

# ===================== CẤU HÌNH MẶC ĐỊNH (có thể ghi đè bằng tham số dòng lệnh) =====================
PDF_PATH = "./01_nguon/Cap_01/VIET.pdf"
OUT_DIR = "./02_ocr_tho/Cap_01/VIET_pdfplumber"
PAGE_START, PAGE_END = 170, 190     # đánh số từ 1 theo thứ tự trang của file PDF

# ===================== GHÉP DÒNG / ĐOẠN / CÂU =====================
# ===== Cấu hình ghép dòng / đoạn / câu =====
INDENT_RATIO = 0.8          # thụt đầu dòng > 0.8 * chiều cao dòng  => bắt đầu đoạn mới
SHORT_LINE_RATIO = 2.5      # dòng kết thúc cách mép phải chuẩn > 2.5 * chiều cao dòng => hết đoạn
DROP_PAGE_NUMBERS = True    # bỏ số trang đứng riêng ở đầu/cuối trang
PAGE_NUM_GAP_RATIO = 1.5    # số trang phải cách dòng kế bên > 1.5 * khoảng cách dòng
EXTRA_DROP_PATTERNS = []    # regex các dòng cần bỏ (vd: tiêu đề chạy đầu trang)
LOW_CONF = 0.90             # câu có confidence TB < ngưỡng này sẽ có needs_review=True
ABBREVIATIONS = {"tr", "vv", "tp", "ts", "gs", "pgs", "st", "nxb", "sđd", "tk"}

TERMINAL_END = re.compile(r'[.?!…]+["”’»)\]]*$')
SENT_CANDIDATE = re.compile(r'([.?!…]+)(["”’»)\]]*)(\s+|$)')
OPENERS = "\"“‘«(["


def clean_text(s):
    s = unicodedata.normalize("NFC", str(s))
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s+([,;:.!?])", r"\1", s)
    return s


def _yc(l):
    return (l["y0"] + l["y1"]) / 2


def drop_page_furniture(lines):
    """Bỏ số trang đứng riêng + các dòng khớp EXTRA_DROP_PATTERNS. Trả về (lines, số trang in)."""
    lines = [l for l in lines
             if not any(re.search(p, l["text"]) for p in EXTRA_DROP_PATTERNS)]
    printed = None
    if DROP_PAGE_NUMBERS and len(lines) >= 2:
        if len(lines) >= 3:   # khoảng cách dòng điển hình (phân vị 25 để không bị số trang/đoạn trống kéo lệch)
            pitch = float(np.percentile(np.diff([_yc(l) for l in lines]), 25))
        else:
            pitch = float(np.median([l["y1"] - l["y0"] for l in lines]))
        is_num = lambda l: re.fullmatch(r"[\W_]*\d{1,4}[\W_]*", l["text"]) is not None
        if is_num(lines[-1]) and _yc(lines[-1]) - _yc(lines[-2]) > PAGE_NUM_GAP_RATIO * pitch:
            printed = re.sub(r"\D", "", lines.pop()["text"])
        elif is_num(lines[0]) and _yc(lines[1]) - _yc(lines[0]) > PAGE_NUM_GAP_RATIO * pitch:
            printed = re.sub(r"\D", "", lines.pop(0)["text"])
    return lines, printed


def build_paragraphs(lines):
    """Tách đoạn bằng thụt đầu dòng và dòng cuối đoạn ngắn."""
    if not lines:
        return []
    med_h = float(np.median([l["y1"] - l["y0"] for l in lines]))
    left_ref = float(np.percentile([l["x0"] for l in lines], 20))
    right_ref = float(np.percentile([l["x1"] for l in lines], 90))
    paras, prev = [], None
    for l in lines:
        indent = (l["x0"] - left_ref) > INDENT_RATIO * med_h
        prev_short = prev is not None and (right_ref - prev["x1"]) > SHORT_LINE_RATIO * med_h
        if prev is None or indent or prev_short:
            paras.append(dict(lines=[l], starts_para=bool(indent) or prev is not None))
        else:
            paras[-1]["lines"].append(l)
        prev = l
    return paras


def join_lines(lines):
    """Nối các dòng của một đoạn; ghi lại khoảng ký tự + confidence của từng dòng."""
    text, spans = "", []
    for l in lines:
        if text and not text.endswith("-"):
            text += " "
        s = len(text)
        text += l["text"]
        spans.append((s, len(text), l["score"]))
    return text, spans


def split_spans(text):
    """Tách câu theo . ? ! … — không tách ở số (153.181), viết tắt, chữ cái viết tắt, số thứ tự."""
    spans, start = [], 0
    for m in SENT_CANDIDATE.finditer(text):
        rest = text[m.end():]
        if rest:
            nxt = rest.lstrip(OPENERS)
            if not (nxt and nxt[0].isupper()):
                continue
        if m.group(1) == ".":
            before = text[start:m.start()]
            tok = (re.findall(r"\S+", before) or [""])[-1]
            tl = tok.lower().strip(OPENERS)
            if tl in ABBREVIATIONS or (len(tok) == 1 and tok.isupper()):
                continue
            if re.fullmatch(r"\d{1,2}", tok) and before.strip() == tok:
                continue
        spans.append((start, m.end(2)))
        start = m.end()
    if text[start:].strip():
        spans.append((start, len(text)))
    return spans


def _score_of(spans, s, e):
    tot = w = 0.0
    for ls, le, sc in spans:
        o = min(e, le) - max(s, ls)
        if o > 0:
            tot += o * sc
            w += o
    return tot / w if w else 0.0


def _page_at(marks, pos):
    page = marks[0][1]
    for off, pg in marks:
        if off <= pos:
            page = pg
    return page


def build_sentences(pages):
    """pages: [(page_name, lines)] theo thứ tự trang. Trả về (records, printed_numbers)."""
    paras, printed_map = [], {}
    for page_name, lines in pages:
        lines, printed = drop_page_furniture(lines)
        printed_map[page_name] = printed
        for j, p in enumerate(build_paragraphs(lines)):
            text, spans = join_lines(p["lines"])
            paras.append(dict(text=text, spans=spans, starts_para=p["starts_para"],
                              first_on_page=(j == 0), marks=[(0, page_name)]))

    merged = []
    for p in paras:
        if (merged and p["first_on_page"] and not p["starts_para"]
                and not TERMINAL_END.search(merged[-1]["text"])):
            prev = merged[-1]
            sep = "" if prev["text"].endswith("-") else " "
            off = len(prev["text"]) + len(sep)
            prev["text"] += sep + p["text"]
            prev["spans"] += [(s + off, e + off, sc) for s, e, sc in p["spans"]]
            prev["marks"].append((off, p["marks"][0][1]))
        else:
            merged.append(p)

    records, counters = [], {}
    for pi, p in enumerate(merged):
        for s, e in split_spans(p["text"]):
            txt = p["text"][s:e].strip()
            if not txt:
                continue
            page = _page_at(p["marks"], s)
            page_end = _page_at(p["marks"], max(s, e - 1))
            counters[page] = counters.get(page, 0) + 1
            score = _score_of(p["spans"], s, e)
            records.append(dict(
                id=f"{page}-{counters[page]:03d}", page=page, page_end=page_end,
                text=txt, score=round(score, 4), n_chars=len(txt),
                cross_page=(page != page_end),
                incomplete_start=(pi == 0 and s == 0 and not p["starts_para"]),
                incomplete_end=(pi == len(merged) - 1 and e >= len(p["text"].rstrip())
                                and not TERMINAL_END.search(txt)),
                needs_review=score < LOW_CONF,
            ))
    return records, printed_map

# ===================== ĐỘ TIN CẬY HEURISTIC CHO TEXT TRÍCH TỪ PDF =====================
_PUNCT_OK = set(".,;:!?…-–—'\"“”‘’()[]{}«»/%&+*=<>·")


def line_quality(text):
    """0–1: tỉ lệ ký tự 'hợp lệ' (chữ Latin/số/dấu câu). Lỗi font (cid:xx), U+FFFD, ký tự lạ -> điểm thấp."""
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return 0.0
    if re.search(r"\(cid:\d+\)", text):
        return 0.0
    ok = 0
    for c in chars:
        if c.isdigit() or c in _PUNCT_OK:
            ok += 1
        elif unicodedata.category(c).startswith(("L", "M")) and "LATIN" in unicodedata.name(c, "") or \
                unicodedata.category(c) == "Mn":
            ok += 1
    score = ok / len(chars)
    if "\ufffd" in text:          # ký tự thay thế U+FFFD = font/encoding hỏng
        score = min(score, 0.5)
    return score


def extract_page_lines(page):
    """Các dòng text của một trang pdfplumber, kèm toạ độ (y tăng từ trên xuống) và confidence heuristic."""
    lines = []
    for ln in page.extract_text_lines(strip=True, return_chars=False):
        text = clean_text(ln["text"])
        if not text:
            continue
        lines.append(dict(text=text, score=line_quality(text),
                          x0=float(ln["x0"]), x1=float(ln["x1"]),
                          y0=float(ln["top"]), y1=float(ln["bottom"])))
    return lines


# ===================== CHƯƠNG TRÌNH CHÍNH =====================
def run(pdf_path, out_dir, start, end):
    pdf_path, out_dir = Path(pdf_path), Path(out_dir)
    if not pdf_path.exists():
        raise FileNotFoundError(f"Không tìm thấy PDF: {pdf_path}")
    out_dir.mkdir(parents=True, exist_ok=True)

    pages, raw_text = [], {}
    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        print(f"PDF: {pdf_path} | tổng số trang: {total} | trích trang {start}–{end}")
        if start < 1 or end > total or start > end:
            raise ValueError(f"Khoảng trang {start}–{end} không hợp lệ; PDF có {total} trang.")
        for page_no in range(start, end + 1):
            page = pdf.pages[page_no - 1]
            name = f"{page_no:04d}"
            raw_text[name] = page.extract_text() or ""
            pages.append((name, extract_page_lines(page)))
            page.flush_cache()   # giải phóng bộ nhớ

    if not any(lines for _, lines in pages):
        raise SystemExit(
            "Không trích được text từ các trang này: PDF có vẻ là bản quét (chỉ có ảnh). "
            "pdfplumber không OCR được; hãy dùng notebook OCR (PaddleOCR).")

    records, printed_map = build_sentences(pages)
    for r in records:                       # đổi tên cho rõ nghĩa
        r["confidence"] = r.pop("score")

    by_page = {}
    for r in records:
        by_page.setdefault(r["page"], []).append(r)

    fields = ["id", "confidence", "page", "page_end", "text", "n_chars",
              "cross_page", "incomplete_start", "incomplete_end", "needs_review"]
    summary = []
    for name, lines in pages:
        recs = by_page.get(name, [])
        d = out_dir / name
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{name}_page_text.txt").write_text(raw_text[name], encoding="utf-8")
        (d / f"{name}_sentences.txt").write_text("".join(r["text"] + "\n" for r in recs), encoding="utf-8")
        with open(d / f"{name}_sentences.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(recs)
        mean_conf = float(np.mean([r["confidence"] for r in recs])) if recs else 0.0
        summary.append(dict(page=name, n_lines=len(lines), n_sentences=len(recs),
                            mean_confidence=round(mean_conf, 4),
                            printed_page_no=printed_map.get(name) or ""))

    with open(out_dir / "all_sentences.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(records)
    with open(out_dir / "all_sentences.jsonl", "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(out_dir / "summary.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0].keys()))
        w.writeheader()
        w.writerows(summary)

    print(f"\nXong: {len(records)} câu từ {len(pages)} trang -> {out_dir}")
    print(f"{'Trang':<8}{'Số in':<8}{'Dòng':<7}{'Câu':<6}{'Conf TB':<8}")
    for s in summary:
        print(f"{s['page']:<8}{str(s['printed_page_no'] or '-'):<8}{s['n_lines']:<7}{s['n_sentences']:<6}{s['mean_confidence']:<8}")
    return records, summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="PDF (text layer) -> câu theo từng trang, bằng pdfplumber")
    ap.add_argument("--pdf", default=PDF_PATH)
    ap.add_argument("--out", default=OUT_DIR)
    ap.add_argument("--start", type=int, default=PAGE_START)
    ap.add_argument("--end", type=int, default=PAGE_END)
    args, _ = ap.parse_known_args()     # parse_known_args: chạy được cả trong cell Jupyter/Kaggle
    run(args.pdf, args.out, args.start, args.end)