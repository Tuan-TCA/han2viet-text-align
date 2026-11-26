# -*- coding: utf-8 -*-
"""
Giai đoạn 04_dong_hang (Version 1 - Baseline):
Chạy tự động gióng hàng câu Hán cổ - Việt bằng Bertalign với MAX_ALIGN = 8
đọc từ 03_text_sach/output/v1/ và xuất ra 04_dong_hang/output/v1/.
"""

import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
from bertalign import Bertalign
from tqdm import tqdm

SCRIPT_DIR = Path(__file__).resolve().parent
STAGE_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = STAGE_DIR.parent
CLEAN_DIR = PROJECT_ROOT / "03_text_sach" / "output" / "v1"
OUT_DIR = STAGE_DIR / "output" / "v1"

MAX_ALIGN = 8
RATIO_MIN_OMISSION = 0.55
RATIO_MAX_ADDITION = 4.50
OCR_CONF_THRESHOLD = 0.55

BLOCKS = [
    {
        "name": "Cap_01",
        "han_file": CLEAN_DIR / "Cap_01_HAN_clean.jsonl",
        "viet_file": CLEAN_DIR / "Cap_01_VIET_clean.jsonl",
        "out_xlsx": OUT_DIR / "Align_Cap_01.xlsx",
    },
    {
        "name": "Cap_02_V",
        "han_file": CLEAN_DIR / "Cap_02_V_HAN_clean.jsonl",
        "viet_file": CLEAN_DIR / "Cap_02_V_VIET_clean.jsonl",
        "out_xlsx": OUT_DIR / "Align_Cap_02_V.xlsx",
    },
    {
        "name": "Cap_02_VI",
        "han_file": CLEAN_DIR / "Cap_02_VI_HAN_clean.jsonl",
        "viet_file": CLEAN_DIR / "Cap_02_VI_VIET_clean.jsonl",
        "out_xlsx": OUT_DIR / "Align_Cap_02_VI.xlsx",
    },
]

FINAL_FULL_XLSX = OUT_DIR / "PhuBienTapLuc_Alignment_Full.xlsx"


def load_jsonl(filepath: Path) -> List[Dict]:
    records = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records


def count_cjk_chars(text: str) -> int:
    return sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")


def extract_numbers_count(zh_text: str, vi_text: str) -> Tuple[int, int]:
    vi_nums = re.findall(r"\d+", vi_text)
    zh_nums = re.findall(r"[一二兩三四五六七八九十百千萬万\d]+", zh_text)
    return len(zh_nums), len(vi_nums)


def check_punct_or_number_match(zh_text: str, vi_text: str) -> int:
    if not zh_text or not vi_text:
        return 0
    for zh_p, vi_p in [("？", "?"), ("！", "!"), ("：", ":")]:
        if zh_p in zh_text and vi_p in vi_text:
            return 1
    n_zh, n_vi = extract_numbers_count(zh_text, vi_text)
    return 1 if (n_zh > 0 and n_vi > 0) else 0


def build_alignment_row(han_items: List[Dict], viet_items: List[Dict]) -> Dict:
    n_zh = len(han_items)
    n_vi = len(viet_items)
    align_type = f"{n_zh}-{n_vi}"

    zh_text = " ".join(item["han_co_goc"] for item in han_items).strip()
    vi_text = " ".join(item["text_vi"] for item in viet_items).strip()

    han_page = han_items[0]["han_page"] if n_zh > 0 else 0
    viet_page = viet_items[0]["viet_page_start"] if n_vi > 0 else 0
    pair_id = f"C{han_page:03d}_V{viet_page:03d}"

    ocr_conf_min = (
        round(min(item["ocr_conf_min"] for item in han_items), 4)
        if n_zh > 0
        else None
    )

    notes = []
    missing = 1 if (n_zh == 0 or n_vi == 0) else 0
    omission = 0
    addition = 0

    if missing == 1:
        notes.append(f"MISSING: Khuyết một vế ({align_type})")
    else:
        cjk_len = max(count_cjk_chars(zh_text), 1)
        vi_words = len(vi_text.split())
        ratio = vi_words / cjk_len

        if ratio < RATIO_MIN_OMISSION:
            omission = 1
            notes.append(
                f"Nghi ngờ OMISSION: Tỷ lệ Việt/Hán thấp ({ratio:.2f} < {RATIO_MIN_OMISSION})"
            )
        elif ratio > RATIO_MAX_ADDITION:
            addition = 1
            notes.append(
                f"Nghi ngờ ADDITION: Tỷ lệ Việt/Hán cao ({ratio:.2f} > {RATIO_MAX_ADDITION})"
            )

        cnt_zh_num, cnt_vi_num = extract_numbers_count(zh_text, vi_text)
        if abs(cnt_zh_num - cnt_vi_num) >= 4:
            notes.append(f"Lệch số lượng con số (Hán: {cnt_zh_num} vs Việt: {cnt_vi_num})")

    if ocr_conf_min is not None and ocr_conf_min < OCR_CONF_THRESHOLD:
        notes.append(f"Cảnh báo OCR mờ (conf = {ocr_conf_min})")

    punct_match = check_punct_or_number_match(zh_text, vi_text)
    label_target = 1 if (omission == 0 and addition == 0 and missing == 0) else 0

    return {
        "Pair_ID": pair_id,
        "Chinese": zh_text if zh_text else None,
        "Vietnamese": vi_text if vi_text else None,
        "OMISSION": omission,
        "ADDITION": addition,
        "MISSING": missing,
        "Alignment_Type": align_type,
        "Punct_Anchor_Match": punct_match,
        "Label_Target": label_target,
        "OCR_Conf_Min": ocr_conf_min,
        "Note": " | ".join(notes),
    }


def save_to_excel(rows: List[Dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Alignment_Dataset", index=False)


def run_block_alignment(block: Dict) -> List[Dict]:
    name = block["name"]
    print(f"\n>>> [v1 | MAX_ALIGN={MAX_ALIGN}] Đang gióng hàng khối [{name}]...", flush=True)

    han_records = load_jsonl(block["han_file"])
    viet_records = load_jsonl(block["viet_file"])
    print(f"    Nạp dữ liệu: {len(han_records)} câu Hán | {len(viet_records)} câu Việt", flush=True)

    src_text = "\n".join(item["han_gian_the"] for item in han_records)
    tgt_text = "\n".join(item["text_vi"] for item in viet_records)

    aligner = Bertalign(src_text, tgt_text, max_align=MAX_ALIGN, is_split=True)
    aligner.align_sents()

    aligned_rows = []
    for src_idxs, tgt_idxs in tqdm(aligner.result, desc=f"Xuất dòng [{name}]"):
        han_items = [han_records[i] for i in src_idxs]
        viet_items = [viet_records[j] for j in tgt_idxs]
        aligned_rows.append(build_alignment_row(han_items, viet_items))

    save_to_excel(aligned_rows, block["out_xlsx"])
    return aligned_rows


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_rows = []
    for block in BLOCKS:
        block_rows = run_block_alignment(block)
        all_rows.extend(block_rows)

    save_to_excel(all_rows, FINAL_FULL_XLSX)
    print(f"\n>>> HOÀN TẤT v1! File tổng hợp: {FINAL_FULL_XLSX} ({len(all_rows)} cặp)", flush=True)


if __name__ == "__main__":
    main()
