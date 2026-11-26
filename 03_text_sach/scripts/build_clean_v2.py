# -*- coding: utf-8 -*-
"""
Giai đoạn 03_text_sach (Version 2 - Anti-fragment & Clause-balanced):
Làm sạch văn bản Hán - Việt và tự động chấm câu / tách câu Hán cổ cho toàn bộ 3 khối:
  1. Cap_01     (Trang Hán 1..53, khử trùng lặp trang 49 / giữ trang 50, lọc đuôi rác trang 53)
  2. Cap_02_V   (Quyển V: Trang Hán 1 -> trước '撫邊雜錄卷之六' ở trang 51, gỡ '撫邊雜錄卷之五')
  3. Cap_02_VI  (Quyển VI: Từ sau '撫邊雜錄卷之六' ở trang 51 -> hết trang 87, bỏ trang 88..92)

Cải tiến Version 2:
  - CHẶN CÂU VỤN 1-4 CHỮ HÁN (MIN_HAN_CJK_CHARS = 5):
      + Lớp 1: Khi số chữ Hán trong bộ đệm < 5 chữ mà gặp dấu kết câu (。！？；：),
        tự động hạ xuống dấu phẩy '，' để nối liền với cụm sau.
      + Lớp 2: Mảnh dư ở cuối khối nếu < 5 chữ Hán được gộp ngược vào câu liền trước.
        Đảm bảo 0 câu Hán có độ dài <= 4 chữ!
  - CÂN BẰNG ĐỘ DÀI MỆNH ĐỀ HÁN - VIỆT ĐỂ THU > 2.000 CẶP DÒNG:
      + Ngắt mệnh đề Hán tại '；', '：' (khi >= 5 chữ) và tại '，' khi mệnh đề >= 15 chữ Hán.
      + Tách các câu kê khai tiếng Việt dài tại '; ', ': ' và ', ' (với câu > 32 từ),
        đồng thời gộp lại nếu mảnh Việt < 6 từ.

Xuất kết quả vào: 03_text_sach/output/v2/ (kèm file run_metadata.json).
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
# 1. CẤU HÌNH THAM SỐ CHẠY (VERSION 2)
# ==============================================================================
VERSION = "v2"
PILOT_PAGES: Optional[List[int]] = None
MAX_PREVIEW_SENTS: int = 2
PILOT_VIET_MAX_SENTS: int = 15

# Tham số kiểm soát hạt độ câu Hán (triệt tiêu câu vụn 1, 2, 3, 4 chữ)
MIN_HAN_CJK_CHARS: int = 5       # Tuyệt đối không tạo câu Hán < 5 chữ
HAN_COMMA_SPLIT_LEN: int = 15    # Ngắt mệnh đề tại dấu '，' khi đã tích lũy >= 15 chữ Hán

# Tham số kiểm soát hạt độ câu Việt (tách câu kê khai dài, tránh mảnh vụn)
MIN_VIET_WORDS: int = 6          # Không tạo mảnh tiếng Việt < 6 từ khi tách mệnh đề
VIET_LONG_SENT_WORDS: int = 32   # Câu Việt > 32 từ sẽ tách thêm tại dấu ', ' mỗi ~15 từ
VIET_COMMA_CHUNK_WORDS: int = 15

PUNCT_MODEL_NAME = "raynardj/classical-chinese-punctuation-guwen-biaodian"
SENT_END_PUNCTS = {"。", "！", "？"}
CLAUSE_END_PUNCTS = {"；", "："}

# Đường dẫn thư mục dự án (nằm trong 03_text_sach/scripts/)
SCRIPT_DIR = Path(__file__).resolve().parent
STAGE_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = STAGE_DIR.parent
OCR_DIR = PROJECT_ROOT / "02_ocr_tho"
OUT_DIR = STAGE_DIR / "output" / VERSION


# ==============================================================================
# 2. CÁC HÀM LÀM SẠCH & TÁCH MỆNH ĐỀ TIẾNG VIỆT
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


def merge_short_viet_segments(
    segments: List[str], min_words: int = MIN_VIET_WORDS
) -> List[str]:
    """Gộp các mảnh tiếng Việt quá ngắn (< min_words) vào vế liền kề để tránh câu vụn."""
    if len(segments) <= 1:
        return segments

    merged: List[str] = []
    carry = ""

    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        if carry:
            seg = f"{carry} {seg}"
            carry = ""

        if len(seg.split()) < min_words:
            carry = seg
        else:
            merged.append(seg)

    if carry:
        if merged:
            merged[-1] = f"{merged[-1]} {carry}"
        else:
            merged.append(carry)

    return merged


def split_vietnamese_clauses(text: str) -> List[str]:
    """
    Tách các câu tiếng Việt quá dài thành các mệnh đề cân đối với vế Hán:
      1. Tách tại ';' hoặc ':' (gộp lại nếu mảnh < MIN_VIET_WORDS từ).
      2. Nếu mệnh đề vẫn dài > VIET_LONG_SENT_WORDS (32 từ), tách tiếp tại ','
         theo cụm >= VIET_COMMA_CHUNK_WORDS (15 từ), đồng thời gộp mảnh dư ngắn ở cuối.
    """
    if len(text.split()) < MIN_VIET_WORDS * 2:
        return [text]

    raw_semi = [p.strip() for p in re.split(r"(?<=[;:])\s+", text) if p.strip()]
    semi_clauses = merge_short_viet_segments(raw_semi, min_words=MIN_VIET_WORDS)

    final_clauses: List[str] = []
    for clause in semi_clauses:
        if len(clause.split()) <= VIET_LONG_SENT_WORDS:
            final_clauses.append(clause)
            continue

        comma_parts = [p.strip() for p in re.split(r"(?<=,)\s+", clause) if p.strip()]
        buf: List[str] = []
        buf_words = 0
        sub_clauses: List[str] = []

        for part in comma_parts:
            buf.append(part)
            buf_words += len(part.split())
            if buf_words >= VIET_COMMA_CHUNK_WORDS:
                sub_clauses.append(" ".join(buf))
                buf = []
                buf_words = 0

        if buf:
            leftover = " ".join(buf)
            if sub_clauses and buf_words < MIN_VIET_WORDS + 2:
                sub_clauses[-1] = f"{sub_clauses[-1]} {leftover}"
            else:
                sub_clauses.append(leftover)

        final_clauses.extend(
            merge_short_viet_segments(sub_clauses, min_words=MIN_VIET_WORDS)
        )

    return final_clauses if final_clauses else [text]


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

    records: List[Dict] = []
    for row in df_filtered.itertuples(index=False):
        cleaned_vi = clean_vietnamese_text(str(row.text_vi))
        if not cleaned_vi:
            continue

        clauses = split_vietnamese_clauses(cleaned_vi)
        for cl in clauses:
            records.append(
                {
                    "sent_idx": len(records) + 1,
                    "viet_page_start": int(row.viet_page_start),
                    "viet_page_end": int(row.viet_page_end),
                    "loai": str(row.loai),
                    "text_vi": cl,
                }
            )
    return records


# ==============================================================================
# 3. CÁC HÀM LÀM SẠCH, CHỐNG CÂU VỤN & TÁCH CÂU TIẾNG HÁN CỔ (V2)
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


def count_cjk_in_str(text: str) -> int:
    return sum(1 for ch in text if is_cjk_char(ch))


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
    min_cjk_chars: int = MIN_HAN_CJK_CHARS,
    comma_split_len: int = HAN_COMMA_SPLIT_LEN,
) -> List[Dict]:
    """
    Xây dựng danh sách câu Hán cổ với cơ chế 2 lớp chống câu vụn (1, 2, 3, 4 chữ).
    """
    raw_sentences: List[Dict] = []
    buf_chars: List[str] = []
    buf_pages: List[int] = []
    buf_confs: List[float] = []

    def finalize_punct(text: str) -> str:
        if not text:
            return ""
        if text[-1] in {"，", "：", "；", "、"}:
            return text[:-1] + "。"
        if text[-1] not in SENT_END_PUNCTS:
            return text + "。"
        return text

    def flush_to_raw():
        if not buf_chars:
            return
        han_co_goc = finalize_punct("".join(buf_chars))
        raw_sentences.append(
            {
                "han_page": buf_pages[0],
                "ocr_conf_min": min(buf_confs),
                "han_co_goc": han_co_goc,
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

        cjk_len = len(buf_pages)

        if p in SENT_END_PUNCTS or p in CLAUSE_END_PUNCTS:
            if cjk_len < min_cjk_chars:
                buf_chars.append("，")
            else:
                buf_chars.append(p if p in SENT_END_PUNCTS else "。")
                flush_to_raw()
        elif p == "，":
            if cjk_len >= comma_split_len:
                buf_chars.append("。")
                flush_to_raw()
            else:
                buf_chars.append("，")
        elif p:
            buf_chars.append(p)

    if buf_chars:
        if raw_sentences and len(buf_pages) < min_cjk_chars:
            prev = raw_sentences[-1]
            prev_base = prev["han_co_goc"].rstrip("。！？，；：")
            tail_text = finalize_punct("".join(buf_chars))
            prev["han_co_goc"] = prev_base + "，" + tail_text
            prev["ocr_conf_min"] = min(prev["ocr_conf_min"], min(buf_confs))
            buf_chars.clear()
            buf_pages.clear()
            buf_confs.clear()
        else:
            flush_to_raw()

    final_sentences: List[Dict] = []
    for rec in raw_sentences:
        if final_sentences and count_cjk_in_str(rec["han_co_goc"]) < min_cjk_chars:
            prev = final_sentences[-1]
            merged_goc = prev["han_co_goc"].rstrip("。！？") + "，" + rec["han_co_goc"]
            prev["han_co_goc"] = merged_goc
            prev["han_gian_the"] = opencc_converter.convert(merged_goc)
            prev["ocr_conf_min"] = round(
                min(prev["ocr_conf_min"], rec["ocr_conf_min"]), 4
            )
        else:
            goc = rec["han_co_goc"]
            final_sentences.append(
                {
                    "sent_idx": len(final_sentences) + 1,
                    "han_page": rec["han_page"],
                    "ocr_conf_min": round(rec["ocr_conf_min"], 4),
                    "han_co_goc": goc,
                    "han_gian_the": opencc_converter.convert(goc),
                }
            )

    return final_sentences


def save_jsonl(records: List[Dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def print_head_tail_summary(
    label: str, out_path: Path, records: List[Dict], is_han: bool, n_sample: int = 2
) -> Dict:
    if is_han:
        cjk_lens = [count_cjk_in_str(r["han_co_goc"]) for r in records]
        short_cnt = sum(1 for x in cjk_lens if x <= 4)
        stats = {
            "count": len(records),
            "min_cjk": min(cjk_lens),
            "avg_cjk": round(sum(cjk_lens) / len(cjk_lens), 2),
            "le_4_chars_count": short_cnt,
        }
        extra = f" | min_cjk={stats['min_cjk']}, avg_cjk={stats['avg_cjk']}, câu <=4 chữ={short_cnt}"
    else:
        w_lens = [len(r["text_vi"].split()) for r in records]
        stats = {
            "count": len(records),
            "min_words": min(w_lens),
            "avg_words": round(sum(w_lens) / len(w_lens), 2),
        }
        extra = f" | min_words={stats['min_words']}, avg_words={stats['avg_words']}"

    print(f"\n--- {label}: {out_path.name} (Tổng: {len(records):,} câu{extra}) ---")
    for r in records[:n_sample]:
        txt = r["han_co_goc"] if is_han else r["text_vi"]
        pg = r["han_page"] if is_han else r["viet_page_start"]
        print(f"    Đầu #{r['sent_idx']} (p.{pg}): {txt}")
    for r in records[-n_sample:]:
        txt = r["han_co_goc"] if is_han else r["text_vi"]
        pg = r["han_page"] if is_han else r["viet_page_start"]
        print(f"    Cuối #{r['sent_idx']} (p.{pg}): {txt}")
    return stats


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tokenizer, model, device = load_punct_model(PUNCT_MODEL_NAME)
    opencc_t2s = OpenCC("t2s")

    blocks = [
        {
            "name": "Cap_01",
            "han_dir": OCR_DIR / "Cap_01" / "HAN" / "pages",
            "viet_xlsx": OCR_DIR / "Cap_01" / "VIET" / "VIET_0186-0251.xlsx",
            "han_out": OUT_DIR / "Cap_01_HAN_clean.jsonl",
            "viet_out": OUT_DIR / "Cap_01_VIET_clean.jsonl",
        },
        {
            "name": "Cap_02_V",
            "han_dir": OCR_DIR / "Cap_02" / "HAN" / "pages",
            "viet_xlsx": OCR_DIR / "Cap_02" / "VIET" / "VIET_0001-0105.xlsx",
            "han_out": OUT_DIR / "Cap_02_V_HAN_clean.jsonl",
            "viet_out": OUT_DIR / "Cap_02_V_VIET_clean.jsonl",
        },
        {
            "name": "Cap_02_VI",
            "han_dir": OCR_DIR / "Cap_02" / "HAN" / "pages",
            "viet_xlsx": OCR_DIR / "Cap_02" / "VIET" / "VIET_0405-0439.xlsx",
            "han_out": OUT_DIR / "Cap_02_VI_HAN_clean.jsonl",
            "viet_out": OUT_DIR / "Cap_02_VI_VIET_clean.jsonl",
        },
    ]

    print("=" * 90)
    print(
        f"CHẠY LÀM SẠCH & TÁCH CÂU [{VERSION}] -> {OUT_DIR.relative_to(PROJECT_ROOT)}"
    )
    print("=" * 90)

    meta_stats = {}
    for blk in blocks:
        bname = blk["name"]
        print(f"\n>>> Đang xử lý khối [{bname}] ...")

        char_stream = load_han_char_stream_for_block(
            bname, blk["han_dir"], pilot_pages=PILOT_PAGES
        )
        punct_after = punctuate_char_stream(char_stream, tokenizer, model, device)
        han_sentences = build_han_sentences(char_stream, punct_after, opencc_t2s)
        save_jsonl(han_sentences, blk["han_out"])

        viet_sentences = load_and_clean_viet(blk["viet_xlsx"])
        save_jsonl(viet_sentences, blk["viet_out"])

        h_stat = print_head_tail_summary(
            f"{bname} HÁN", blk["han_out"], han_sentences, is_han=True, n_sample=MAX_PREVIEW_SENTS
        )
        v_stat = print_head_tail_summary(
            f"{bname} VIỆT", blk["viet_out"], viet_sentences, is_han=False, n_sample=MAX_PREVIEW_SENTS
        )
        meta_stats[bname] = {"han": h_stat, "viet": v_stat}

    metadata = {
        "version": VERSION,
        "params": {
            "MIN_HAN_CJK_CHARS": MIN_HAN_CJK_CHARS,
            "HAN_COMMA_SPLIT_LEN": HAN_COMMA_SPLIT_LEN,
            "MIN_VIET_WORDS": MIN_VIET_WORDS,
            "VIET_LONG_SENT_WORDS": VIET_LONG_SENT_WORDS,
            "VIET_COMMA_CHUNK_WORDS": VIET_COMMA_CHUNK_WORDS,
        },
        "blocks": meta_stats,
    }
    (OUT_DIR / "run_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n>>> Hoàn tất! Đã lưu metadata tại: {(OUT_DIR / 'run_metadata.json').relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
