# -*- coding: utf-8 -*-
"""
Giai đoạn 03_text_sach (Version 1 - Baseline):
Làm sạch văn bản Hán - Việt và tự động chấm câu / tách câu Hán cổ cho toàn bộ 3 khối:
  1. Cap_01     (Trang Hán 1..53, khử trùng lặp trang 49 / giữ trang 50, lọc đuôi rác trang 53)
  2. Cap_02_V   (Quyển V: Trang Hán 1 -> trước '撫邊雜錄卷之六' ở trang 51, gỡ '撫邊雜錄卷之五')
  3. Cap_02_VI  (Quyển VI: Từ sau '撫邊雜錄卷之六' ở trang 51 -> hết trang 87, bỏ trang 88..92)

Xuất kết quả vào: 03_text_sach/output/v1/ (hoặc 03_text_sach/output/pilot/ khi chạy pilot).
"""

import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd
import torch
from opencc import OpenCC
from transformers import AutoModelForTokenClassification, AutoTokenizer

# ==============================================================================
# 1. CẤU HÌNH THAM SỐ CHẠY (VERSION 1)
# ==============================================================================
PILOT_PAGES: Optional[List[int]] = None
MAX_PREVIEW_SENTS: int = 2
PILOT_VIET_MAX_SENTS: int = 15

PUNCT_MODEL_NAME = "raynardj/classical-chinese-punctuation-guwen-biaodian"
SENT_END_PUNCTS = {"。", "！", "？"}
CLAUSE_END_PUNCTS = {"；"}

# Đường dẫn thư mục dự án (nằm trong 03_text_sach/scripts/)
SCRIPT_DIR = Path(__file__).resolve().parent
STAGE_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = STAGE_DIR.parent
OCR_DIR = PROJECT_ROOT / "02_ocr_tho"
OUT_V1_DIR = STAGE_DIR / "output" / "v1"
OUT_PILOT_DIR = STAGE_DIR / "output" / "pilot"


# ==============================================================================
# 2. CÁC HÀM LÀM SẠCH TIẾNG VIỆT
# ==============================================================================
def clean_vietnamese_text(text: str) -> str:
    if not isinstance(text, str):
        return ""

    s = unicodedata.normalize("NFC", text)
    s = re.sub(r"\s+", " ", s).strip()

    s = re.sub(r"(?<=\d)[õðö](?=\b|\D)", "5", s)
    s = re.sub(
        r"\b[ðö](?=\s+(?:tiền|tiển|quan|lạng|đồng|phân|tấc|thước|sào|mẫu|bát|thưng|cáp|hốt|người|năm)\b)",
        "5",
        s,
    )
    s = re.sub(
        r"\b[Il](?=\s+(?:quan|tiền|tiển|lạng|đồng|mẫu|sào|thước|tấc|bát|hốt)\b)",
        "1",
        s,
    )
    s = re.sub(r"\b1\s+tiền\s+lỗ\s+đồng\b", "1 tiền 15 đồng", s)

    s = re.sub(r"(?<!\w)_+(?=\w)", "", s)
    s = re.sub(r'(?<=\w)["“”](?=\s+\w)', "", s)

    word_fixes = [
        (r"\bxuất tờ\b", "xuất từ"),
        (r"\btiển\b", "tiền"),
        (r"\bthuyển\b", "thuyền"),
        (r"\btuộng\b", "ruộng"),
        (r"\bđân\b", "dân"),
        (r"\bđịnh\b(?=\s*,\s*cai hợp)", "dinh"),
        (r"\bsố định\b", "số đinh"),
        (r"\bnhân định\b", "nhân đinh"),
        (r"\bđình điền\b", "đinh điền"),
        (r"\bphu Ấy\b", "phu ấy"),
        (r"\bLỄ bộ\b", "Lễ bộ"),
        (r"\bhạ đăng\b", "hạ đẳng"),
        (r"\bbạc lá để\b", "bạc lá đề"),
        (r"\bđông cân\b", "đồng cân"),
        (r"\bcắt cỏ vơi\b", "cắt cỏ voi"),
        (r"\btàu vơi\b", "tàu voi"),
        (r"\bcền gò\b", "cồn gò"),
        (r"\bsắp ong\b", "sáp ong"),
    ]
    for pattern, repl in word_fixes:
        s = re.sub(pattern, repl, s)

    for _ in range(2):
        s = re.sub(r"(?<=\d)\.(?=\d{3}\b)", "", s)

    return re.sub(r"\s+", " ", s).strip()


def load_and_clean_viet(
    xlsx_path: Path,
    allowed_pages: Optional[Set[int]] = None,
    max_sents: Optional[int] = None,
) -> List[Dict]:
    df = pd.read_excel(xlsx_path, sheet_name="CAU_VIET")

    mask = (df["dung_de_ghep"] == True) & (  # noqa: E712
        ~df["loai"].isin(["chu_thich", "tieu_de", "phien_am"])
    )
    df_filtered = df[mask].copy()

    if allowed_pages is not None:
        df_filtered = df_filtered[
            df_filtered["viet_page_start"].isin(allowed_pages)
        ].copy()

    if max_sents is not None:
        df_filtered = df_filtered.head(max_sents).copy()

    records = []
    for idx, row in enumerate(df_filtered.itertuples(index=False), start=1):
        cleaned_vi = clean_vietnamese_text(str(row.text_vi))
        if not cleaned_vi:
            continue
        records.append(
            {
                "sent_idx": idx,
                "viet_page_start": int(row.viet_page_start),
                "viet_page_end": int(row.viet_page_end),
                "loai": str(row.loai),
                "text_vi": cleaned_vi,
            }
        )
    return records


def get_viet_pages_for_han_pilot(xlsx_path: Path, han_pages: List[int]) -> Set[int]:
    df_pages = pd.read_excel(xlsx_path, sheet_name="TRANG_VIET")
    max_han, min_han = max(han_pages), min(han_pages)
    matched_viet_pages: Set[int] = set()

    for row in df_pages.itertuples(index=False):
        moc_str = "" if pd.isna(row.han_trang_co_moc) else str(row.han_trang_co_moc)
        nums_in_moc = [int(x) for x in re.findall(r"\d+", moc_str)]
        if any(p in han_pages for p in nums_in_moc):
            matched_viet_pages.add(int(row.viet_pdf_page))
        elif (
            not pd.isna(row.han_cua_so_tu)
            and not pd.isna(row.han_cua_so_den)
            and int(row.han_cua_so_tu) >= min_han
            and int(row.han_cua_so_den) <= max_han
        ):
            matched_viet_pages.add(int(row.viet_pdf_page))

    if matched_viet_pages:
        matched_viet_pages.add(max(matched_viet_pages) + 1)
    return matched_viet_pages


# ==============================================================================
# 3. CÁC HÀM LÀM SẠCH, CHẤM CÂU & TÁCH CÂU TIẾNG HÁN CỔ (V1)
# ==============================================================================
def is_cjk_char(ch: str) -> bool:
    cp = ord(ch)
    return (
        (0x4E00 <= cp <= 0x9FFF)
        or (0x3400 <= cp <= 0x4DBF)
        or (0xF900 <= cp <= 0xFAFF)
        or (0x20000 <= cp <= 0x2CEAF)
        or (0x2F800 <= cp <= 0x2FA1F)
    )


def load_han_char_stream_for_block(
    block_name: str,
    pages_dir: Path,
    pilot_pages: Optional[List[int]] = None,
) -> List[Dict]:
    json_files = sorted(pages_dir.glob("*.json"))
    char_stream: List[Dict] = []

    for jf in json_files:
        data = json.loads(jf.read_text(encoding="utf-8"))
        page_num = int(data.get("info", {}).get("page", 0))

        if pilot_pages is not None and page_num not in pilot_pages:
            continue

        if block_name == "Cap_01":
            if page_num == 49:
                continue
        elif block_name == "Cap_02_V":
            if page_num > 51:
                continue
        elif block_name == "Cap_02_VI":
            if page_num < 51 or page_num > 87:
                continue

        rows = data.get("rows", [])
        started_q6_on_p51 = False

        for row in rows:
            row_text = row.get("han", "").strip()
            row_conf = float(row.get("confidence", 0.0))
            row_page = int(row.get("page", page_num))
            row_col = str(row.get("column", ""))

            if block_name == "Cap_01":
                if page_num == 53 and int(row.get("segment", 0)) >= 4:
                    continue
            elif block_name == "Cap_02_V":
                if page_num == 1 and "撫邊雜錄卷之五" in row_text:
                    row_text = row_text.replace("撫邊雜錄卷之五", "")
                if page_num == 51 and "撫邊雜錄卷之六" in row_text:
                    before_q6 = row_text.split("撫邊雜錄卷之六")[0]
                    for ch in before_q6:
                        if is_cjk_char(ch):
                            char_stream.append(
                                {"char": ch, "han_page": row_page, "confidence": row_conf}
                            )
                    break
            elif block_name == "Cap_02_VI":
                if page_num == 51:
                    if not started_q6_on_p51:
                        if "撫邊雜錄卷之六" in row_text:
                            started_q6_on_p51 = True
                            row_text = row_text.split("撫邊雜錄卷之六", 1)[1]
                        else:
                            continue
                if page_num == 87 and row_col in {"Cap02-087-COL01", "Cap02-087-COL06"}:
                    continue

            for ch in row_text:
                if is_cjk_char(ch):
                    char_stream.append(
                        {
                            "char": ch,
                            "han_page": row_page,
                            "confidence": row_conf,
                        }
                    )

    return char_stream


def load_punct_model(
    model_name: str = PUNCT_MODEL_NAME,
) -> Tuple[AutoTokenizer, AutoModelForTokenClassification, torch.device]:
    try:
        tokenizer = AutoTokenizer.from_pretrained(model_name, local_files_only=True)
        model = AutoModelForTokenClassification.from_pretrained(
            model_name, local_files_only=True
        )
    except Exception:
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModelForTokenClassification.from_pretrained(model_name)

    model.eval()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)
    return tokenizer, model, device


def punctuate_char_stream(
    char_stream: List[Dict],
    tokenizer: AutoTokenizer,
    model: AutoModelForTokenClassification,
    device: torch.device,
    window_size: int = 400,
    stride: int = 300,
) -> List[str]:
    if not char_stream:
        return []

    id2label = model.config.id2label
    chars = [item["char"] for item in char_stream]
    n_chars = len(chars)
    punct_after = [""] * n_chars

    start = 0
    margin = (window_size - stride) // 2

    while start < n_chars:
        end = min(start + window_size, n_chars)
        chunk_chars = chars[start:end]

        encoded = tokenizer(
            chunk_chars,
            is_split_into_words=True,
            return_tensors="pt",
            truncation=True,
            max_length=512,
        )
        word_ids = encoded.word_ids(batch_index=0)
        inputs = {k: v.to(device) for k, v in encoded.items()}

        with torch.no_grad():
            logits = model(**inputs).logits[0]
        pred_ids = logits.argmax(dim=-1).cpu().tolist()

        chunk_preds = [""] * len(chunk_chars)
        for tok_idx, wid in enumerate(word_ids):
            if wid is None:
                continue
            label = id2label[pred_ids[tok_idx]]
            chunk_preds[wid] = "" if label == "O" else label

        write_from = 0 if start == 0 else margin
        write_to = len(chunk_chars) if end == n_chars else (len(chunk_chars) - margin)

        for local_i in range(write_from, write_to):
            punct_after[start + local_i] = chunk_preds[local_i]

        if end == n_chars:
            break
        start += stride

    return punct_after


def normalize_punct(p: str) -> str:
    if not p or p in {'"', "'", "（", "）", "【", "】"}:
        return ""
    return p


def build_han_sentences(
    char_stream: List[Dict],
    punct_after: List[str],
    opencc_converter: OpenCC,
) -> List[Dict]:
    sentences: List[Dict] = []
    buf_chars: List[str] = []
    buf_pages: List[int] = []
    buf_confs: List[float] = []

    def flush_sentence():
        if not buf_chars:
            return
        han_co_goc = "".join(buf_chars)
        if han_co_goc[-1] in {"，", "：", "；", "、"}:
            han_co_goc = han_co_goc[:-1] + "。"
        elif han_co_goc[-1] not in SENT_END_PUNCTS:
            han_co_goc = han_co_goc + "。"

        han_gian_the = opencc_converter.convert(han_co_goc)
        sent_idx = len(sentences) + 1

        sentences.append(
            {
                "sent_idx": sent_idx,
                "han_page": buf_pages[0],
                "ocr_conf_min": round(min(buf_confs), 4),
                "han_co_goc": han_co_goc,
                "han_gian_the": han_gian_the,
            }
        )
        buf_chars.clear()
        buf_pages.clear()
        buf_confs.clear()

    for item, raw_p in zip(char_stream, punct_after):
        ch = item["char"]
        p = normalize_punct(raw_p)

        buf_chars.append(ch)
        buf_pages.append(item["han_page"])
        buf_confs.append(item["confidence"])

        if p:
            buf_chars.append(p)

        cjk_len = len(buf_pages)
        if p in SENT_END_PUNCTS or (p in CLAUSE_END_PUNCTS and cjk_len >= 180):
            flush_sentence()

    flush_sentence()
    return sentences


def save_jsonl(records: List[Dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    is_pilot = PILOT_PAGES is not None
    tokenizer, model, device = load_punct_model(PUNCT_MODEL_NAME)
    opencc_t2s = OpenCC("t2s")

    if is_pilot:
        blocks = [
            {
                "name": "Cap_01",
                "han_dir": OCR_DIR / "Cap_01" / "HAN" / "pages",
                "viet_xlsx": OCR_DIR / "Cap_01" / "VIET" / "VIET_0186-0251.xlsx",
                "han_out": OUT_PILOT_DIR / "pilot_Cap_01_HAN_clean.jsonl",
                "viet_out": OUT_PILOT_DIR / "pilot_Cap_01_VIET_clean.jsonl",
            }
        ]
    else:
        blocks = [
            {
                "name": "Cap_01",
                "han_dir": OCR_DIR / "Cap_01" / "HAN" / "pages",
                "viet_xlsx": OCR_DIR / "Cap_01" / "VIET" / "VIET_0186-0251.xlsx",
                "han_out": OUT_V1_DIR / "Cap_01_HAN_clean.jsonl",
                "viet_out": OUT_V1_DIR / "Cap_01_VIET_clean.jsonl",
            },
            {
                "name": "Cap_02_V",
                "han_dir": OCR_DIR / "Cap_02" / "HAN" / "pages",
                "viet_xlsx": OCR_DIR / "Cap_02" / "VIET" / "VIET_0001-0105.xlsx",
                "han_out": OUT_V1_DIR / "Cap_02_V_HAN_clean.jsonl",
                "viet_out": OUT_V1_DIR / "Cap_02_V_VIET_clean.jsonl",
            },
            {
                "name": "Cap_02_VI",
                "han_dir": OCR_DIR / "Cap_02" / "HAN" / "pages",
                "viet_xlsx": OCR_DIR / "Cap_02" / "VIET" / "VIET_0405-0439.xlsx",
                "han_out": OUT_V1_DIR / "Cap_02_VI_HAN_clean.jsonl",
                "viet_out": OUT_V1_DIR / "Cap_02_VI_VIET_clean.jsonl",
            },
        ]

    for blk in blocks:
        bname = blk["name"]
        char_stream = load_han_char_stream_for_block(
            bname, blk["han_dir"], pilot_pages=PILOT_PAGES
        )
        punct_after = punctuate_char_stream(char_stream, tokenizer, model, device)
        han_sentences = build_han_sentences(char_stream, punct_after, opencc_t2s)
        save_jsonl(han_sentences, blk["han_out"])

        if is_pilot:
            allowed_vi = get_viet_pages_for_han_pilot(blk["viet_xlsx"], PILOT_PAGES)
            viet_sentences = load_and_clean_viet(
                blk["viet_xlsx"], allowed_pages=allowed_vi, max_sents=PILOT_VIET_MAX_SENTS
            )
        else:
            viet_sentences = load_and_clean_viet(blk["viet_xlsx"])
        save_jsonl(viet_sentences, blk["viet_out"])
        print(f"[v1 | {bname}] Hán={len(han_sentences)} | Việt={len(viet_sentences)}")


if __name__ == "__main__":
    main()
