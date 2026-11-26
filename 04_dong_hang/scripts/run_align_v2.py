# -*- coding: utf-8 -*-
"""
Giai đoạn 04_dong_hang (Version 2 - Improved):
Chạy tự động gióng hàng câu Hán cổ - Việt bằng Bertalign với MAX_ALIGN = 5
đọc từ 03_text_sach/output/v2/ và xuất ra 04_dong_hang/output/v2/ (kèm alignment_summary.json).
"""

import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
from bertalign import Bertalign
from tqdm import tqdm

# ==============================================================================
# 1. CẤU HÌNH ĐƯỜNG DẪN & NGƯỠNG HEURISTIC (VERSION 2)
# ==============================================================================
VERSION = "v2"
SCRIPT_DIR = Path(__file__).resolve().parent
STAGE_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = STAGE_DIR.parent
CLEAN_DIR = PROJECT_ROOT / "03_text_sach" / "output" / VERSION
OUT_DIR = STAGE_DIR / "output" / VERSION

MAX_ALIGN = 5               # n + m <= 5 (1-1, 1-2, 2-1, 2-2, 1-3, 3-1, 1-4, 4-1)
RATIO_MIN_OMISSION = 0.55   # Tỷ lệ (từ Việt / chữ Hán) < 0.55 -> Nghi ngờ dịch thiếu (OMISSION)
RATIO_MAX_ADDITION = 4.50   # Tỷ lệ (từ Việt / chữ Hán) > 4.50 -> Nghi ngờ dính câu khác (ADDITION)
OCR_CONF_THRESHOLD = 0.55   # Điểm tin cậy OCR < 0.55 -> Cảnh báo chữ Hán bị mờ/nhiễu

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


# ==============================================================================
# 2. CÁC HÀM XỬ LÝ & TÍNH TOÁN 11 CỘT MẪU
# ==============================================================================
def load_jsonl(filepath: Path) -> List[Dict]:
    records = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records


def count_cjk_chars(text: str) -> int:
    return sum(
        1
        for ch in text
        if ("\u4e00" <= ch <= "\u9fff")
        or ("\u3400" <= ch <= "\u4dbf")
        or ("\uf900" <= ch <= "\ufaff")
    )


def extract_numbers_count(zh_text: str, vi_text: str) -> Tuple[int, int]:
    vi_nums = re.findall(r"\d+", vi_text)
    zh_nums = re.findall(r"[一二兩三四五六七八九十百千萬万廿卅\d]+", zh_text)
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


# ==============================================================================
# 3. LUỒNG CHẠY CHÍNH (VERSION 2 -> 04_dong_hang/output/v2/)
# ==============================================================================
def run_block_alignment(block: Dict) -> Tuple[List[Dict], Dict]:
    name = block["name"]
    print(f"\n>>> [{VERSION} | MAX_ALIGN={MAX_ALIGN}] Đang gióng hàng khối [{name}]...", flush=True)

    han_records = load_jsonl(block["han_file"])
    viet_records = load_jsonl(block["viet_file"])
    print(
        f"    Nạp dữ liệu {VERSION}: {len(han_records)} câu Hán | {len(viet_records)} câu Việt",
        flush=True,
    )

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

    df_blk = pd.DataFrame(aligned_rows)
    n_ok = int((df_blk["Label_Target"] == 1).sum())
    n_flagged = len(df_blk) - n_ok
    cjk_lens = (
        df_blk[df_blk["Chinese"].notna()]["Chinese"]
        .apply(count_cjk_chars)
        .tolist()
    )
    blk_summary = {
        "han_input_sents": len(han_records),
        "viet_input_sents": len(viet_records),
        "total_pairs": len(df_blk),
        "label_1_ok": n_ok,
        "label_0_flagged": n_flagged,
        "omission": int(df_blk["OMISSION"].sum()),
        "addition": int(df_blk["ADDITION"].sum()),
        "missing": int(df_blk["MISSING"].sum()),
        "punct_anchor_match": int(df_blk["Punct_Anchor_Match"].sum()),
        "min_cjk_chars_in_row": min(cjk_lens) if cjk_lens else 0,
        "le_3_cjk_rows": sum(1 for x in cjk_lens if x <= 3),
        "alignment_types": df_blk["Alignment_Type"].value_counts().to_dict(),
    }

    print(
        f"    Đã lưu: output/{VERSION}/{block['out_xlsx'].name} ({len(aligned_rows)} cặp) | "
        f"Label=1: {n_ok} | Label=0: {n_flagged} | Min chữ Hán/dòng: {blk_summary['min_cjk_chars_in_row']}",
        flush=True,
    )
    return aligned_rows, blk_summary


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_rows = []
    blocks_summary = {}

    for block in BLOCKS:
        block_rows, blk_sum = run_block_alignment(block)
        all_rows.extend(block_rows)
        blocks_summary[block["name"]] = blk_sum

    save_to_excel(all_rows, FINAL_FULL_XLSX)

    df_all = pd.DataFrame(all_rows)
    cjk_all = (
        df_all[df_all["Chinese"].notna()]["Chinese"]
        .apply(count_cjk_chars)
        .tolist()
    )
    summary = {
        "version": VERSION,
        "params": {
            "MAX_ALIGN": MAX_ALIGN,
            "RATIO_MIN_OMISSION": RATIO_MIN_OMISSION,
            "RATIO_MAX_ADDITION": RATIO_MAX_ADDITION,
            "OCR_CONF_THRESHOLD": OCR_CONF_THRESHOLD,
        },
        "overall": {
            "total_pairs": len(df_all),
            "label_1_ok": int((df_all["Label_Target"] == 1).sum()),
            "label_0_flagged": int((df_all["Label_Target"] == 0).sum()),
            "omission": int(df_all["OMISSION"].sum()),
            "addition": int(df_all["ADDITION"].sum()),
            "missing": int(df_all["MISSING"].sum()),
            "punct_anchor_match": int(df_all["Punct_Anchor_Match"].sum()),
            "min_cjk_chars_in_row": min(cjk_all) if cjk_all else 0,
            "le_3_cjk_rows": sum(1 for x in cjk_all if x <= 3),
            "alignment_types": df_all["Alignment_Type"].value_counts().to_dict(),
        },
        "blocks": blocks_summary,
    }
    (OUT_DIR / "alignment_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(
        f"\n>>> HOÀN TẤT [{VERSION}]! File tổng hợp: output/{VERSION}/{FINAL_FULL_XLSX.name} "
        f"({len(all_rows)} cặp | Đạt chuẩn={summary['overall']['label_1_ok']})",
        flush=True,
    )


if __name__ == "__main__":
    main()
