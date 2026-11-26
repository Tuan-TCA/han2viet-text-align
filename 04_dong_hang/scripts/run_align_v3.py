# -*- coding: utf-8 -*-
"""
Giai đoạn 04_dong_hang (Version 3.1 - Full-Block Bertalign + 3-Phase Boundary Shift Re-aligner):
1. Đọc từ 03_text_sach/output/v3/ (đã lọc sạch phiên âm rò rỉ) và xuất ra 04_dong_hang/output/v3/.
2. Chạy Bertalign(..., max_align=5, is_split=True) toàn khối để tránh đứt biên cửa sổ gây ra
   hàng trăm dòng khuyết vế (0-1 / 1-0), đồng thời kiểm tra hậu kiểm trượt trang với viet_han_anchors.json.
3. Boundary Shift Re-aligner (3 pha):
   - Pha A: Ghép trực tiếp các cặp khuyết vế đối nghịch đứng cạnh nhau (1-0 + 0-1 hoặc 0-1 + 1-0)
            và hấp thụ các mảnh mồ côi vào cặp liền kề nếu cải thiện tỷ lệ độ dài & số học.
   - Pha B: Dịch chuyển 1 câu ở biên hai cặp liền kề (k, k+1) để cân bằng tỷ lệ Việt/Hán
            về vùng chuẩn [0.85, 1.65] và giảm lệch số lượng con số.
4. Chuẩn hóa gán nhãn sát `real_label`:
   - RATIO_MIN_OMISSION = 0.42, RATIO_MAX_ADDITION = 3.20.
   - Gắn cờ lệch số học nghiêm trọng (abs(n_zh - n_vi) >= 3 hoặc >=3 vs 0).
   - Bổ sung cột `OCR_Valid` và cập nhật `Label_Target`.
"""

import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from bertalign import Bertalign
from tqdm import tqdm

# ==============================================================================
# 1. CẤU HÌNH ĐƯỜNG DẪN & THAM SỐ VERSION 3.1
# ==============================================================================
VERSION = "v3"
SCRIPT_DIR = Path(__file__).resolve().parent
STAGE_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = STAGE_DIR.parent
CLEAN_DIR = PROJECT_ROOT / "03_text_sach" / "output" / VERSION
OUT_DIR = STAGE_DIR / "output" / VERSION
ANCHORS_JSON_PATH = PROJECT_ROOT / "02_ocr_tho" / "Viet_OCR" / "viet_han_anchors.json"

MAX_ALIGN = 5

# Tham số hậu xử lý sửa trượt biên & gán nhãn sát real_label
IDEAL_RATIO_LOW = 0.85
IDEAL_RATIO_HIGH = 1.65
RATIO_MIN_OMISSION = 0.42
RATIO_MAX_ADDITION = 3.20
OCR_CONF_THRESHOLD = 0.55

BLOCKS = [
    {
        "name": "Cap_01",
        "anchor_key": "Cap_01",
        "han_file": CLEAN_DIR / "Cap_01_HAN_clean.jsonl",
        "viet_file": CLEAN_DIR / "Cap_01_VIET_clean.jsonl",
        "viet_xlsx": PROJECT_ROOT / "02_ocr_tho" / "Cap_01" / "VIET" / "VIET_0186-0251.xlsx",
        "out_xlsx": OUT_DIR / "Align_Cap_01.xlsx",
    },
    {
        "name": "Cap_02_V",
        "anchor_key": "Cap_02",
        "han_file": CLEAN_DIR / "Cap_02_V_HAN_clean.jsonl",
        "viet_file": CLEAN_DIR / "Cap_02_V_VIET_clean.jsonl",
        "viet_xlsx": PROJECT_ROOT / "02_ocr_tho" / "Cap_02" / "VIET" / "VIET_0001-0105.xlsx",
        "out_xlsx": OUT_DIR / "Align_Cap_02_V.xlsx",
    },
    {
        "name": "Cap_02_VI",
        "anchor_key": "Cap_02_VI",
        "han_file": CLEAN_DIR / "Cap_02_VI_HAN_clean.jsonl",
        "viet_file": CLEAN_DIR / "Cap_02_VI_VIET_clean.jsonl",
        "viet_xlsx": PROJECT_ROOT / "02_ocr_tho" / "Cap_02" / "VIET" / "VIET_0405-0439.xlsx",
        "out_xlsx": OUT_DIR / "Align_Cap_02_VI.xlsx",
    },
]

FINAL_FULL_XLSX = OUT_DIR / "PhuBienTapLuc_Alignment_Full.xlsx"


# ==============================================================================
# 2. CÁC HÀM ĐO LƯỜNG CHẤT LƯỢNG CẶP CÂU & SỐ HỌC
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
    """Đếm số lượng cụm số đếm xuất hiện ở vế Hán và vế Việt."""
    vi_nums = re.findall(r"\d+", vi_text)
    zh_nums = re.findall(r"[一二兩三四五六七八九十百千萬万廿卅\d]+", zh_text)
    return len(zh_nums), len(vi_nums)


def has_severe_number_mismatch(cnt_zh_num: int, cnt_vi_num: int) -> bool:
    """Kiểm tra lệch số học nghiêm trọng giữa hai vế."""
    if abs(cnt_zh_num - cnt_vi_num) >= 3:
        return True
    if (cnt_zh_num >= 3 and cnt_vi_num == 0) or (cnt_vi_num >= 3 and cnt_zh_num == 0):
        return True
    return False


def check_punct_or_number_match(zh_text: str, vi_text: str) -> int:
    """Giữ nhất quán tiêu chí với v2 để so sánh định lượng trực tiếp."""
    if not zh_text or not vi_text:
        return 0
    for zh_p, vi_p in [("？", "?"), ("！", "!"), ("：", ":")]:
        if zh_p in zh_text and vi_p in vi_text:
            return 1
    n_zh, n_vi = extract_numbers_count(zh_text, vi_text)
    return 1 if (n_zh > 0 and n_vi > 0) else 0


# ==============================================================================
# 3. HẬU XỬ LÝ SỬA TRƯỢT RANH GIỚI LIỀN KỀ (3-PHASE BOUNDARY SHIFT RE-ALIGNER)
# ==============================================================================
def pair_ratio_and_num_error(
    han_items: List[Dict], viet_items: List[Dict]
) -> Tuple[float, int]:
    """
    Tính:
    1. Độ lệch tỷ lệ độ dài (vi_words / cjk_len) ra khỏi khoảng chuẩn [0.85, 1.65].
    2. Độ chênh lệch số lượng con số abs(cnt_zh_num - cnt_vi_num).
    """
    if not han_items or not viet_items:
        return 10.0, 10

    zh_text = " ".join(x["han_co_goc"] for x in han_items)
    vi_text = " ".join(x["text_vi"] for x in viet_items)

    cjk_len = max(count_cjk_chars(zh_text), 1)
    vi_words = len(vi_text.split())
    ratio = vi_words / cjk_len

    if ratio < IDEAL_RATIO_LOW:
        ratio_dist = (IDEAL_RATIO_LOW - ratio) * 1.4
    elif ratio > IDEAL_RATIO_HIGH:
        ratio_dist = ratio - IDEAL_RATIO_HIGH
    else:
        ratio_dist = 0.0

    n_zh, n_vi = extract_numbers_count(zh_text, vi_text)
    num_diff = abs(n_zh - n_vi)
    return ratio_dist, num_diff


def boundary_shift_realign(
    pairs: List[Tuple[List[Dict], List[Dict]]]
) -> Tuple[List[Tuple[List[Dict], List[Dict]]], int]:
    """
    Duyệt qua từng cặp liền kề (k, k+1):
    - Pha A1: Ghép trực tiếp hai dòng khuyết vế đối nghịch đứng cạnh nhau (1-0 + 0-1 hoặc 0-1 + 1-0).
    - Pha A2: Hấp thụ các dòng 0-1 / 1-0 mồ côi vào cặp liền kề nếu cùng vùng trang và cải thiện tỷ lệ.
    - Pha B: Dịch chuyển 1 phần tử biên giữa hai cặp liền kề k và k+1 (chạy 2 lượt hội tụ).
    """
    work = [(list(h), list(v)) for h, v in pairs]
    shift_count = 0

    # Pha A1 & A2: Xử lý các dòng khuyết vế (0-1 hoặc 1-0)
    merged_work: List[Tuple[List[Dict], List[Dict]]] = []
    i = 0
    while i < len(work):
        h_cur, v_cur = work[i]

        # Trường hợp 1: Dòng hiện tại là 1-0 và dòng kế tiếp là 0-1 -> ghép thành 1 cặp hoàn chỉnh
        if h_cur and not v_cur and i + 1 < len(work):
            h_next, v_next = work[i + 1]
            if not h_next and v_next:
                r_new, _ = pair_ratio_and_num_error(h_cur, v_next)
                if r_new < 2.2:
                    merged_work.append((h_cur, v_next))
                    shift_count += 1
                    i += 2
                    continue

        # Trường hợp 2: Dòng hiện tại là 0-1 và dòng kế tiếp là 1-0 -> ghép thành 1 cặp hoàn chỉnh
        if not h_cur and v_cur and i + 1 < len(work):
            h_next, v_next = work[i + 1]
            if h_next and not v_next:
                r_new, _ = pair_ratio_and_num_error(h_next, v_cur)
                if r_new < 2.2:
                    merged_work.append((h_next, v_cur))
                    shift_count += 1
                    i += 2
                    continue

        # Trường hợp 3: Dòng hiện tại là 0-1 (chỉ có Việt) -> thử gộp vào dòng trước hoặc dòng sau
        if not h_cur and v_cur:
            absorbed = False
            if merged_work:
                h_prev, v_prev = merged_work[-1]
                if h_prev and v_prev and len(h_prev) + len(v_prev) + len(v_cur) <= MAX_ALIGN + 1:
                    old_r, old_n = pair_ratio_and_num_error(h_prev, v_prev)
                    new_r, new_n = pair_ratio_and_num_error(h_prev, v_prev + v_cur)
                    if new_r < old_r and new_n <= old_n:
                        merged_work[-1] = (h_prev, v_prev + v_cur)
                        shift_count += 1
                        absorbed = True
            if not absorbed and i + 1 < len(work):
                h_next, v_next = work[i + 1]
                if h_next and v_next and len(h_next) + len(v_cur) + len(v_next) <= MAX_ALIGN + 1:
                    old_r, old_n = pair_ratio_and_num_error(h_next, v_next)
                    new_r, new_n = pair_ratio_and_num_error(h_next, v_cur + v_next)
                    if new_r < old_r and new_n <= old_n:
                        work[i + 1] = (h_next, v_cur + v_next)
                        shift_count += 1
                        absorbed = True
            if absorbed:
                i += 1
                continue

        # Trường hợp 4: Dòng hiện tại là 1-0 (chỉ có Hán) -> thử gộp vào dòng trước hoặc dòng sau
        if h_cur and not v_cur:
            absorbed = False
            if merged_work:
                h_prev, v_prev = merged_work[-1]
                if h_prev and v_prev and len(h_prev) + len(h_cur) + len(v_prev) <= MAX_ALIGN + 1:
                    old_r, old_n = pair_ratio_and_num_error(h_prev, v_prev)
                    new_r, new_n = pair_ratio_and_num_error(h_prev + h_cur, v_prev)
                    if new_r < old_r and new_n <= old_n:
                        merged_work[-1] = (h_prev + h_cur, v_prev)
                        shift_count += 1
                        absorbed = True
            if not absorbed and i + 1 < len(work):
                h_next, v_next = work[i + 1]
                if h_next and v_next and len(h_cur) + len(h_next) + len(v_next) <= MAX_ALIGN + 1:
                    old_r, old_n = pair_ratio_and_num_error(h_next, v_next)
                    new_r, new_n = pair_ratio_and_num_error(h_cur + h_next, v_next)
                    if new_r < old_r and new_n <= old_n:
                        work[i + 1] = (h_cur + h_next, v_next)
                        shift_count += 1
                        absorbed = True
            if absorbed:
                i += 1
                continue

        merged_work.append((h_cur, v_cur))
        i += 1

    # Pha B: Dịch chuyển 1 phần tử biên giữa hai cặp liền kề k và k+1 (chạy 2 lượt hội tụ)
    for _pass in range(2):
        for k in range(len(merged_work) - 1):
            h1, v1 = merged_work[k]
            h2, v2 = merged_work[k + 1]
            if not h1 or not v1 or not h2 or not v2:
                continue

            r1, n1 = pair_ratio_and_num_error(h1, v1)
            r2, n2 = pair_ratio_and_num_error(h2, v2)
            base_r = r1 + r2
            base_n = n1 + n2

            best_move = None

            # Ứng viên 1: Chuyển câu Việt cuối của k sang đầu k+1
            if len(v1) >= 2 and len(h2) + len(v2) + 1 <= MAX_ALIGN + 1:
                nv1, nv2 = v1[:-1], [v1[-1]] + v2
                nr1, nn1 = pair_ratio_and_num_error(h1, nv1)
                nr2, nn2 = pair_ratio_and_num_error(h2, nv2)
                if (nr1 + nr2 < base_r - 0.12) and (
                    nn1 + nn2 < base_n or (nn1 + nn2 == base_n and base_n == 0 and nr1 + nr2 < base_r - 0.35)
                ):
                    best_move = (h1, nv1, h2, nv2, nr1 + nr2, nn1 + nn2)

            # Ứng viên 2: Chuyển câu Việt đầu của k+1 lên cuối k
            if len(v2) >= 2 and len(h1) + len(v1) + 1 <= MAX_ALIGN + 1:
                nv1, nv2 = v1 + [v2[0]], v2[1:]
                nr1, nn1 = pair_ratio_and_num_error(h1, nv1)
                nr2, nn2 = pair_ratio_and_num_error(h2, nv2)
                if (nr1 + nr2 < base_r - 0.12) and (
                    nn1 + nn2 < base_n or (nn1 + nn2 == base_n and base_n == 0 and nr1 + nr2 < base_r - 0.35)
                ):
                    if best_move is None or (nr1 + nr2 < best_move[4]):
                        best_move = (h1, nv1, h2, nv2, nr1 + nr2, nn1 + nn2)

            # Ứng viên 3: Chuyển câu Hán cuối của k sang đầu k+1
            if len(h1) >= 2 and len(h2) + len(v2) + 1 <= MAX_ALIGN + 1:
                nh1, nh2 = h1[:-1], [h1[-1]] + h2
                nr1, nn1 = pair_ratio_and_num_error(nh1, v1)
                nr2, nn2 = pair_ratio_and_num_error(nh2, v2)
                if (nr1 + nr2 < base_r - 0.12) and (nn1 + nn2 < base_n):
                    if best_move is None or (nr1 + nr2 < best_move[4]):
                        best_move = (nh1, v1, nh2, v2, nr1 + nr2, nn1 + nn2)

            # Ứng viên 4: Chuyển câu Hán đầu của k+1 lên cuối k
            if len(h2) >= 2 and len(h1) + len(v1) + 1 <= MAX_ALIGN + 1:
                nh1, nh2 = h1 + [h2[0]], h2[1:]
                nr1, nn1 = pair_ratio_and_num_error(nh1, v1)
                nr2, nn2 = pair_ratio_and_num_error(nh2, v2)
                if (nr1 + nr2 < base_r - 0.12) and (nn1 + nn2 < base_n):
                    if best_move is None or (nr1 + nr2 < best_move[4]):
                        best_move = (nh1, v1, nh2, v2, nr1 + nr2, nn1 + nn2)

            if best_move is not None:
                merged_work[k] = (best_move[0], best_move[1])
                merged_work[k + 1] = (best_move[2], best_move[3])
                shift_count += 1

    return merged_work, shift_count


# ==============================================================================
# 4. XÂY DỰNG DÒNG KẾT QUẢ 12 CỘT (CÓ `OCR_Valid` & `Label_Target` SÁT `real_label`)
# ==============================================================================
def build_alignment_row(han_items: List[Dict], viet_items: List[Dict]) -> Dict:
    n_zh = len(han_items)
    n_vi = len(viet_items)
    align_type = f"{n_zh}-{n_vi}"

    zh_text = " ".join(item["han_co_goc"] for item in han_items).strip()
    vi_text = " ".join(item["text_vi"] for item in viet_items).strip()

    han_page = han_items[0]["han_page"] if n_zh > 0 else 0
    viet_page = viet_items[0]["viet_page_start"] if n_vi > 0 else 0
    pair_id = f"C{han_page:03d}_V{viet_page:03d}"

    ocr_conf_min: Optional[float] = (
        round(min(item["ocr_conf_min"] for item in han_items), 4)
        if n_zh > 0
        else None
    )
    ocr_valid = 1 if (ocr_conf_min is None or ocr_conf_min >= OCR_CONF_THRESHOLD) else 0

    notes = []
    missing = 1 if (n_zh == 0 or n_vi == 0) else 0
    omission = 0
    addition = 0
    severe_num_mismatch = False

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
        if has_severe_number_mismatch(cnt_zh_num, cnt_vi_num):
            severe_num_mismatch = True
            notes.append(
                f"Lệch số học nghiêm trọng (Hán: {cnt_zh_num} số vs Việt: {cnt_vi_num} số)"
            )

    if ocr_valid == 0:
        notes.append(f"Cảnh báo OCR mờ (conf = {ocr_conf_min} < {OCR_CONF_THRESHOLD})")

    punct_match = check_punct_or_number_match(zh_text, vi_text)

    label_target = (
        1
        if (
            missing == 0
            and omission == 0
            and addition == 0
            and not severe_num_mismatch
            and ocr_valid == 1
        )
        else 0
    )

    return {
        "Pair_ID": pair_id,
        "Chinese": zh_text if zh_text else None,
        "Vietnamese": vi_text if vi_text else None,
        "OMISSION": omission,
        "ADDITION": addition,
        "MISSING": missing,
        "Alignment_Type": align_type,
        "Punct_Anchor_Match": punct_match,
        "OCR_Valid": ocr_valid,
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
# 5. LUỒNG CHẠY CHÍNH (FULL-BLOCK BERTALIGN + RE-ALIGNER -> 04_dong_hang/output/v3/)
# ==============================================================================
def run_block_alignment(block: Dict) -> Tuple[List[Dict], Dict]:
    name = block["name"]
    print(
        f"\n>>> [{VERSION} | Full-Block MAX_ALIGN={MAX_ALIGN}] Đang gióng hàng khối [{name}]...",
        flush=True,
    )

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

    raw_pairs: List[Tuple[List[Dict], List[Dict]]] = [
        ([han_records[i] for i in src_idxs], [viet_records[j] for j in tgt_idxs])
        for src_idxs, tgt_idxs in aligner.result
    ]

    realigned_pairs, n_shifts = boundary_shift_realign(raw_pairs)
    print(
        f"    [Boundary Shift Re-aligner]: Đã tinh chỉnh {n_shifts} biên câu / cặp khuyết vế.",
        flush=True,
    )

    # Kiểm tra bảo toàn 100% số câu đầu vào
    out_han_cnt = sum(len(h) for h, _ in realigned_pairs)
    out_viet_cnt = sum(len(v) for _, v in realigned_pairs)
    assert out_han_cnt == len(han_records), f"Lệch số câu Hán: {out_han_cnt} != {len(han_records)}"
    assert out_viet_cnt == len(viet_records), f"Lệch số câu Việt: {out_viet_cnt} != {len(viet_records)}"

    aligned_rows = [
        build_alignment_row(h_items, v_items)
        for h_items, v_items in tqdm(realigned_pairs, desc=f"Xuất dòng [{name}]")
    ]
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
        "han_output_sents": out_han_cnt,
        "viet_input_sents": len(viet_records),
        "viet_output_sents": out_viet_cnt,
        "boundary_shifts_applied": n_shifts,
        "total_pairs": len(df_blk),
        "label_1_ok": n_ok,
        "label_0_flagged": n_flagged,
        "ocr_valid_1": int((df_blk["OCR_Valid"] == 1).sum()),
        "omission": int(df_blk["OMISSION"].sum()),
        "addition": int(df_blk["ADDITION"].sum()),
        "missing": int(df_blk["MISSING"].sum()),
        "punct_anchor_match": int(df_blk["Punct_Anchor_Match"].sum()),
        "punct_anchor_match_pct": round(100.0 * df_blk["Punct_Anchor_Match"].mean(), 2),
        "min_cjk_chars_in_row": min(cjk_lens) if cjk_lens else 0,
        "alignment_types": df_blk["Alignment_Type"].value_counts().to_dict(),
    }

    print(
        f"    Đã lưu: output/{VERSION}/{block['out_xlsx'].name} ({len(aligned_rows)} cặp) | "
        f"Label=1: {n_ok} ({100*n_ok/len(df_blk):.1f}%) | PunctMatch: {blk_summary['punct_anchor_match_pct']}% | "
        f"Missing: {blk_summary['missing']}",
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
            "ocr_valid_1": int((df_all["OCR_Valid"] == 1).sum()),
            "omission": int(df_all["OMISSION"].sum()),
            "addition": int(df_all["ADDITION"].sum()),
            "missing": int(df_all["MISSING"].sum()),
            "punct_anchor_match": int(df_all["Punct_Anchor_Match"].sum()),
            "punct_anchor_match_pct": round(100.0 * df_all["Punct_Anchor_Match"].mean(), 2),
            "min_cjk_chars_in_row": min(cjk_all) if cjk_all else 0,
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