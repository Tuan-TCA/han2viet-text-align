# -*- coding: utf-8 -*-
"""
Giai đoạn 04_dong_hang (Version 4 - Numeric-Normalized Bertalign + Value-Aware Boundary Re-aligner):
1. Đọc trực tiếp từ `03_text_sach/output/v3/` và xuất ra `04_dong_hang/output/v4/`.
2. Chuẩn hóa số Hán -> số Ả Rập trong chuỗi nội bộ `src_text` đưa cho Bertalign
   (ví dụ: "四千八百廿人" -> " 4820 人", "一貫五陌" -> " 1 貫 5 陌") để LaBSE khớp trực tiếp
   các con số trong sổ thuế/binh chế của Cap_01, đồng thời giữ nguyên 100% chữ Hán cổ ở cột `Chinese`.
3. Nâng cấp 3-Phase Boundary Shift Re-aligner:
   - Pha A: Ghép các cặp khuyết vế đối nghịch (1-0 + 0-1) và hấp thụ mảnh mồ côi.
   - Pha B: Dịch chuyển câu biên giữa (k, k+1) kết hợp:
       + Độ lệch tỷ lệ độ dài Việt/Hán so với vùng chuẩn của từng khối.
       + Độ trùng khớp giá trị con số (đặc biệt các số >= 10 và số mồ côi ở biên).
       + Từ khóa ranh giới Hán cổ - Việt (又/Lại, 凡/Phàm, 其/Về, 耳/thôi, 也矣/vậy).
4. Chuẩn hóa logic gán nhãn sát `real_label`:
   - Tách biên trên tỷ lệ độ dài theo thể loại khối: `2.35` cho văn xuôi/bảng kê (`Cap_01`, `Cap_02_VI`)
     và `3.20` cho thơ văn tự do (`Cap_02_V`).
   - Đổi kiểm tra lệch số học sang đối chiếu giá trị con số (`>= 10`) để không phạt oan
     các từ định danh (`第一`, `三司`) hay cụm số Hán tách rời.
"""

import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd
from bertalign import Bertalign
from tqdm import tqdm

# ==============================================================================
# 1. CẤU HÌNH ĐƯỜNG DẪN & THAM SỐ VERSION 4
# ==============================================================================
INPUT_VERSION = "v3"
OUTPUT_VERSION = "v4"

SCRIPT_DIR = Path(__file__).resolve().parent
STAGE_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = STAGE_DIR.parent
CLEAN_DIR = PROJECT_ROOT / "03_text_sach" / "output" / INPUT_VERSION
OUT_DIR = STAGE_DIR / "output" / OUTPUT_VERSION

MAX_ALIGN = 5
OCR_CONF_THRESHOLD = 0.55

# Ngưỡng độ dài riêng cho văn xuôi/sổ sách vs thơ văn tự do
BLOCK_CONFIGS = [
    {
        "name": "Cap_01",
        "genre": "prose",
        "han_file": CLEAN_DIR / "Cap_01_HAN_clean.jsonl",
        "viet_file": CLEAN_DIR / "Cap_01_VIET_clean.jsonl",
        "out_xlsx": OUT_DIR / "Align_Cap_01.xlsx",
        "ideal_low": 0.80,
        "ideal_high": 1.55,
        "ratio_min": 0.42,
        "ratio_max": 2.35,
    },
    {
        "name": "Cap_02_V",
        "genre": "poetry_mixed",
        "han_file": CLEAN_DIR / "Cap_02_V_HAN_clean.jsonl",
        "viet_file": CLEAN_DIR / "Cap_02_V_VIET_clean.jsonl",
        "out_xlsx": OUT_DIR / "Align_Cap_02_V.xlsx",
        "ideal_low": 0.85,
        "ideal_high": 1.75,
        "ratio_min": 0.42,
        "ratio_max": 3.20,
    },
    {
        "name": "Cap_02_VI",
        "genre": "prose",
        "han_file": CLEAN_DIR / "Cap_02_VI_HAN_clean.jsonl",
        "viet_file": CLEAN_DIR / "Cap_02_VI_VIET_clean.jsonl",
        "out_xlsx": OUT_DIR / "Align_Cap_02_VI.xlsx",
        "ideal_low": 0.80,
        "ideal_high": 1.60,
        "ratio_min": 0.42,
        "ratio_max": 2.35,
    },
]

FINAL_FULL_XLSX = OUT_DIR / "PhuBienTapLuc_Alignment_Full.xlsx"


# ==============================================================================
# 2. BỘ CHUYỂN ĐỔI SỐ HÁN -> SỐ Ả RẬP & TRÍCH XUẤT GIÁ TRỊ SỐ
# ==============================================================================
CN_DIGITS = {
    "零": 0, "〇": 0,
    "一": 1, "壹": 1,
    "二": 2, "兩": 2, "两": 2, "貳": 2,
    "三": 3, "參": 3,
    "四": 4, "肆": 4,
    "五": 5, "伍": 5,
    "六": 6, "陸": 6,
    "七": 7, "柒": 7,
    "八": 8, "捌": 8,
    "九": 9, "玖": 9,
}
CN_UNITS = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000}
CN_SPECIAL = {"廿": 20, "卅": 30, "卌": 40}
CN_NUM_PATTERN = re.compile(r"[零〇一壹二兩两貳三參四肆五伍六陸七柒八捌九玖十拾百佰千仟千萬万廿卅卌]+")


def chinese_num_to_int(token: str) -> Optional[int]:
    """Chuyển chuỗi chữ số Hán cổ (ví dụ '四千八百廿', '十五', '三百六十') sang số nguyên."""
    if not token:
        return None
    if token.isdigit():
        return int(token)

    # Xử lý trường hợp chỉ có 1 ký tự đơn vị như "十" -> 10, "廿" -> 20
    if len(token) == 1:
        if token in CN_DIGITS:
            return CN_DIGITS[token]
        if token in CN_UNITS:
            return CN_UNITS[token]
        if token in CN_SPECIAL:
            return CN_SPECIAL[token]
        return None

    # Phân tách theo lớp 萬 / 万
    if "萬" in token or "万" in token:
        parts = re.split(r"[萬万]", token, maxsplit=1)
        high = chinese_num_to_int(parts[0]) if parts[0] else 1
        low = chinese_num_to_int(parts[1]) if (len(parts) > 1 and parts[1]) else 0
        if high is None or low is None:
            return None
        return high * 10000 + low

    total = 0
    current_digit = 0
    has_unit = False

    for ch in token:
        if ch in CN_DIGITS:
            current_digit = CN_DIGITS[ch]
        elif ch in CN_SPECIAL:
            total += CN_SPECIAL[ch]
            current_digit = 0
            has_unit = True
        elif ch in CN_UNITS:
            unit_val = CN_UNITS[ch]
            if current_digit == 0:
                current_digit = 1
            total += current_digit * unit_val
            current_digit = 0
            has_unit = True
        else:
            return None

    # Nếu chuỗi toàn chữ số nối tiếp không có đơn vị (ví dụ "二三" = 23 hoặc "四九" = 49)
    if not has_unit and len(token) >= 2 and all(c in CN_DIGITS for c in token):
        val = 0
        for c in token:
            val = val * 10 + CN_DIGITS[c]
        return val

    total += current_digit
    return total if total > 0 else None


def normalize_han_for_bertalign(han_text: str) -> str:
    """
    Chèn giá trị số Ả Rập bên cạnh cụm số Hán trong chuỗi đầu vào của Bertalign
    để LaBSE khớp trực tiếp các con số (như 4820, 250, 17110) với bản dịch tiếng Việt.
    Không làm thay đổi cột `Chinese` gốc.
    """
    def _repl(match: re.Match) -> str:
        raw = match.group(0)
        # Bỏ qua chữ "一" đứng đơn lẻ trước danh từ định danh như "第一", "一船" nếu cần,
        # nhưng giữ số >= 2 hoặc cụm có đơn vị thập/bách/thiên/vạn
        val = chinese_num_to_int(raw)
        if val is None:
            return raw
        if len(raw) == 1 and raw == "一":
            return f" {val} "
        return f" {val} "

    normalized = CN_NUM_PATTERN.sub(_repl, han_text)
    return re.sub(r"\s+", " ", normalized).strip()


def extract_number_values(zh_text: str, vi_text: str) -> Tuple[List[int], List[int]]:
    """Trích xuất danh sách giá trị số nguyên ở vế Hán và vế Việt."""
    vi_vals = [int(x) for x in re.findall(r"\d+", vi_text)]
    zh_vals: List[int] = []
    for m in CN_NUM_PATTERN.finditer(zh_text):
        v = chinese_num_to_int(m.group(0))
        if v is not None:
            zh_vals.append(v)
    for d in re.findall(r"\d+", zh_text):
        zh_vals.append(int(d))
    return zh_vals, vi_vals


def evaluate_numeric_consistency(zh_text: str, vi_text: str) -> Tuple[bool, int, str]:
    """
    Đánh giá tính nhất quán số học theo giá trị thực tế thay vì đếm cụm thô:
    Trả về: (is_severe_mismatch, shared_significant_nums, debug_msg)
    """
    zh_vals, vi_vals = extract_number_values(zh_text, vi_text)
    set_zh = set(zh_vals)
    set_vi = set(vi_vals)

    # Các con số đặc trưng (>= 10, ít trùng ngẫu nhiên)
    sig_zh = {x for x in set_zh if x >= 10}
    sig_vi = {x for x in set_vi if x >= 10}
    shared_sig = sig_zh & sig_vi
    shared_all = set_zh & set_vi

    # Nếu khớp được ít nhất 1 con số >= 10 (ví dụ 250, 360, 4820, 15...) -> an toàn số học
    if len(shared_sig) >= 1:
        return False, len(shared_sig), ""

    # Nếu một bên có >= 3 con số lớn (>= 10) mà bên kia hoàn toàn không trùng số nào -> lệch câu
    if (len(sig_zh) >= 3 and len(sig_vi) == 0) or (len(sig_vi) >= 3 and len(sig_zh) == 0):
        return (
            True,
            0,
            f"Lệch số học nghiêm trọng (Hán có {len(sig_zh)} số >=10 vs Việt có {len(sig_vi)} số >=10)",
        )

    if len(sig_zh) >= 2 and len(sig_vi) >= 2 and len(shared_all) == 0:
        return (
            True,
            0,
            f"Lệch giá trị số (Hán: {sorted(sig_zh)[:4]} vs Việt: {sorted(sig_vi)[:4]})",
        )

    return False, len(shared_sig), ""


# ==============================================================================
# 3. CÁC HÀM ĐO LƯỜNG BIÊN CÂU & TỪ KHÓA HÁN CỔ - VIỆT
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


def check_punct_or_number_match(zh_text: str, vi_text: str) -> int:
    if not zh_text or not vi_text:
        return 0
    for zh_p, vi_p in [("？", "?"), ("！", "!"), ("：", ":")]:
        if zh_p in zh_text and vi_p in vi_text:
            return 1
    zh_vals, vi_vals = extract_number_values(zh_text, vi_text)
    if set(zh_vals) & set(vi_vals):
        return 1
    return 1 if (len(zh_vals) > 0 and len(vi_vals) > 0) else 0


BOUNDARY_LEXICAL_PAIRS = [
    (r"^又", r"^(?:lại|vả lại)\b"),
    (r"^凡", r"^phàm\b"),
    (r"^按", r"^xét\b"),
    (r"^其", r"^(?:về|còn như|còn)\b"),
    (r"^至如|^至於", r"^(?:đến như|cho đến)\b"),
    (r"耳[。！？]?$", r"\bthôi[.,;!?]?$"),
    (r"[也矣][。！？]?$", r"\bvậy[.,;!?]?$"),
    (r"[哉乎][。！？]?$", r"(?:chăng|thay|ư|sao|không)[?!.]?$"),
]


def lexical_boundary_bonus(zh_text: str, vi_text: str) -> float:
    """Thưởng điểm nếu đầu/cuối câu Hán và Việt khớp cặp hư từ cổ điển."""
    zh_clean = zh_text.strip()
    vi_clean = vi_text.strip().lower()
    bonus = 0.0
    for zh_pat, vi_pat in BOUNDARY_LEXICAL_PAIRS:
        if re.search(zh_pat, zh_clean) and re.search(vi_pat, vi_clean):
            bonus += 0.25
    return bonus


def pair_alignment_cost(
    han_items: List[Dict],
    viet_items: List[Dict],
    ideal_low: float,
    ideal_high: float,
) -> float:
    """
    Hàm chi phí (càng thấp càng tốt) đánh giá độ khớp của 1 cặp (han_items, viet_items):
    - Phạt khi tỷ lệ vi_words / cjk_len lệch khỏi [ideal_low, ideal_high].
    - Thưởng mạnh khi trùng khớp giá trị con số (đặc biệt số >= 10).
    - Phạt khi có số >= 10 xuất hiện ở một bên nhưng không có ở bên kia.
    - Thưởng khi khớp hư từ đầu/cuối câu Hán cổ - Việt.
    """
    if not han_items or not viet_items:
        return 10.0

    zh_text = " ".join(x["han_co_goc"] for x in han_items)
    vi_text = " ".join(x["text_vi"] for x in viet_items)

    cjk_len = max(count_cjk_chars(zh_text), 1)
    vi_words = len(vi_text.split())
    ratio = vi_words / cjk_len

    if ratio < ideal_low:
        ratio_cost = (ideal_low - ratio) * 1.5
    elif ratio > ideal_high:
        ratio_cost = (ratio - ideal_high) * 1.1
    else:
        ratio_cost = 0.0

    zh_vals, vi_vals = extract_number_values(zh_text, vi_text)
    sig_zh = {x for x in zh_vals if x >= 10}
    sig_vi = {x for x in vi_vals if x >= 10}

    shared_sig = len(sig_zh & sig_vi)
    unmatched_sig = len(sig_zh ^ sig_vi)
    num_cost = 0.22 * unmatched_sig - 0.45 * shared_sig

    lex_bonus = lexical_boundary_bonus(zh_text, vi_text)
    return ratio_cost + num_cost - lex_bonus


# ==============================================================================
# 4. HẬU XỬ LÝ SỬA TRƯỢT RANH GIỚI LIỀN KỀ (VALUE-AWARE RE-ALIGNER)
# ==============================================================================
def boundary_shift_realign(
    pairs: List[Tuple[List[Dict], List[Dict]]],
    ideal_low: float,
    ideal_high: float,
) -> Tuple[List[Tuple[List[Dict], List[Dict]]], int]:
    """
    Pha A: Ghép trực tiếp các cặp khuyết vế đối nghịch (1-0 + 0-1) và hấp thụ mảnh mồ côi.
    Pha B: Dịch chuyển 1 phần tử biên giữa hai cặp liền kề (k, k+1) để tối thiểu hóa
           tổng chi phí `pair_alignment_cost(k) + pair_alignment_cost(k+1)`.
    """
    work = [(list(h), list(v)) for h, v in pairs]
    shift_count = 0

    # Pha A: Xử lý các dòng khuyết vế (0-1 hoặc 1-0)
    merged_work: List[Tuple[List[Dict], List[Dict]]] = []
    i = 0
    while i < len(work):
        h_cur, v_cur = work[i]

        if h_cur and not v_cur and i + 1 < len(work):
            h_next, v_next = work[i + 1]
            if not h_next and v_next:
                if pair_alignment_cost(h_cur, v_next, ideal_low, ideal_high) < 2.2:
                    merged_work.append((h_cur, v_next))
                    shift_count += 1
                    i += 2
                    continue

        if not h_cur and v_cur and i + 1 < len(work):
            h_next, v_next = work[i + 1]
            if h_next and not v_next:
                if pair_alignment_cost(h_next, v_cur, ideal_low, ideal_high) < 2.2:
                    merged_work.append((h_next, v_cur))
                    shift_count += 1
                    i += 2
                    continue

        if not h_cur and v_cur:
            absorbed = False
            if merged_work:
                h_prev, v_prev = merged_work[-1]
                if h_prev and v_prev and len(h_prev) + len(v_prev) + len(v_cur) <= MAX_ALIGN + 1:
                    c_old = pair_alignment_cost(h_prev, v_prev, ideal_low, ideal_high)
                    c_new = pair_alignment_cost(h_prev, v_prev + v_cur, ideal_low, ideal_high)
                    if c_new < c_old - 0.05:
                        merged_work[-1] = (h_prev, v_prev + v_cur)
                        shift_count += 1
                        absorbed = True
            if not absorbed and i + 1 < len(work):
                h_next, v_next = work[i + 1]
                if h_next and v_next and len(h_next) + len(v_cur) + len(v_next) <= MAX_ALIGN + 1:
                    c_old = pair_alignment_cost(h_next, v_next, ideal_low, ideal_high)
                    c_new = pair_alignment_cost(h_next, v_cur + v_next, ideal_low, ideal_high)
                    if c_new < c_old - 0.05:
                        work[i + 1] = (h_next, v_cur + v_next)
                        shift_count += 1
                        absorbed = True
            if absorbed:
                i += 1
                continue

        if h_cur and not v_cur:
            absorbed = False
            if merged_work:
                h_prev, v_prev = merged_work[-1]
                if h_prev and v_prev and len(h_prev) + len(h_cur) + len(v_prev) <= MAX_ALIGN + 1:
                    c_old = pair_alignment_cost(h_prev, v_prev, ideal_low, ideal_high)
                    c_new = pair_alignment_cost(h_prev + h_cur, v_prev, ideal_low, ideal_high)
                    if c_new < c_old - 0.05:
                        merged_work[-1] = (h_prev + h_cur, v_prev)
                        shift_count += 1
                        absorbed = True
            if not absorbed and i + 1 < len(work):
                h_next, v_next = work[i + 1]
                if h_next and v_next and len(h_cur) + len(h_next) + len(v_next) <= MAX_ALIGN + 1:
                    c_old = pair_alignment_cost(h_next, v_next, ideal_low, ideal_high)
                    c_new = pair_alignment_cost(h_cur + h_next, v_next, ideal_low, ideal_high)
                    if c_new < c_old - 0.05:
                        work[i + 1] = (h_cur + h_next, v_next)
                        shift_count += 1
                        absorbed = True
            if absorbed:
                i += 1
                continue

        merged_work.append((h_cur, v_cur))
        i += 1

    # Pha B: Dịch chuyển 1 phần tử biên giữa cặp k và k+1 (chạy 3 lượt hội tụ)
    for _pass in range(3):
        moved_in_pass = 0
        for k in range(len(merged_work) - 1):
            h1, v1 = merged_work[k]
            h2, v2 = merged_work[k + 1]
            if not h1 or not v1 or not h2 or not v2:
                continue

            base_cost = (
                pair_alignment_cost(h1, v1, ideal_low, ideal_high)
                + pair_alignment_cost(h2, v2, ideal_low, ideal_high)
            )
            best_cost = base_cost - 0.18  # Ngưỡng cải thiện tối thiểu để tránh rung lắc biên
            best_state = None

            candidates = []
            if len(v1) >= 2 and len(h2) + len(v2) + 1 <= MAX_ALIGN + 1:
                candidates.append((h1, v1[:-1], h2, [v1[-1]] + v2))
            if len(v2) >= 2 and len(h1) + len(v1) + 1 <= MAX_ALIGN + 1:
                candidates.append((h1, v1 + [v2[0]], h2, v2[1:]))
            if len(h1) >= 2 and len(h2) + len(v2) + 1 <= MAX_ALIGN + 1:
                candidates.append((h1[:-1], v1, [h1[-1]] + h2, v2))
            if len(h2) >= 2 and len(h1) + len(v1) + 1 <= MAX_ALIGN + 1:
                candidates.append((h1 + [h2[0]], v1, h2[1:], v2))

            for nh1, nv1, nh2, nv2 in candidates:
                new_cost = (
                    pair_alignment_cost(nh1, nv1, ideal_low, ideal_high)
                    + pair_alignment_cost(nh2, nv2, ideal_low, ideal_high)
                )
                if new_cost < best_cost:
                    best_cost = new_cost
                    best_state = (nh1, nv1, nh2, nv2)

            if best_state is not None:
                merged_work[k] = (best_state[0], best_state[1])
                merged_work[k + 1] = (best_state[2], best_state[3])
                shift_count += 1
                moved_in_pass += 1

        if moved_in_pass == 0:
            break

    return merged_work, shift_count


# ==============================================================================
# 5. XÂY DỰNG DÒNG KẾT QUẢ 12 CỘT
# ==============================================================================
def build_alignment_row(
    han_items: List[Dict],
    viet_items: List[Dict],
    ratio_min: float,
    ratio_max: float,
) -> Dict:
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

        if ratio < ratio_min:
            omission = 1
            notes.append(
                f"Nghi ngờ OMISSION: Tỷ lệ Việt/Hán thấp ({ratio:.2f} < {ratio_min})"
            )
        elif ratio > ratio_max:
            addition = 1
            notes.append(
                f"Nghi ngờ ADDITION: Tỷ lệ Việt/Hán cao ({ratio:.2f} > {ratio_max})"
            )

        is_num_bad, _, num_msg = evaluate_numeric_consistency(zh_text, vi_text)
        if is_num_bad:
            severe_num_mismatch = True
            notes.append(num_msg)

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
# 6. LUỒNG CHẠY CHÍNH (ĐỌC 03/v3 -> XUẤT 04/v4)
# ==============================================================================
def run_block_alignment(block: Dict) -> Tuple[List[Dict], Dict]:
    name = block["name"]
    print(
        f"\n>>> [{OUTPUT_VERSION} | Input={INPUT_VERSION} | Numeric-Norm + MAX_ALIGN={MAX_ALIGN}] "
        f"Đang gióng hàng khối [{name}]...",
        flush=True,
    )

    han_records = load_jsonl(block["han_file"])
    viet_records = load_jsonl(block["viet_file"])
    print(
        f"    Nạp dữ liệu {INPUT_VERSION}: {len(han_records)} câu Hán | {len(viet_records)} câu Việt",
        flush=True,
    )

    # Chuẩn hóa số Hán -> số Ả Rập trong chuỗi nội bộ đưa cho Bertalign
    src_text = "\n".join(
        normalize_han_for_bertalign(item["han_gian_the"]) for item in han_records
    )
    tgt_text = "\n".join(item["text_vi"] for item in viet_records)

    aligner = Bertalign(src_text, tgt_text, max_align=MAX_ALIGN, is_split=True)
    aligner.align_sents()

    raw_pairs: List[Tuple[List[Dict], List[Dict]]] = [
        ([han_records[i] for i in src_idxs], [viet_records[j] for j in tgt_idxs])
        for src_idxs, tgt_idxs in aligner.result
    ]

    realigned_pairs, n_shifts = boundary_shift_realign(
        raw_pairs,
        ideal_low=block["ideal_low"],
        ideal_high=block["ideal_high"],
    )
    print(
        f"    [Value-Aware Re-aligner]: Đã tinh chỉnh {n_shifts} biên câu / cặp khuyết vế.",
        flush=True,
    )

    out_han_cnt = sum(len(h) for h, _ in realigned_pairs)
    out_viet_cnt = sum(len(v) for _, v in realigned_pairs)
    assert out_han_cnt == len(han_records), f"Lệch số câu Hán: {out_han_cnt} != {len(han_records)}"
    assert out_viet_cnt == len(viet_records), f"Lệch số câu Việt: {out_viet_cnt} != {len(viet_records)}"

    aligned_rows = [
        build_alignment_row(
            h_items,
            v_items,
            ratio_min=block["ratio_min"],
            ratio_max=block["ratio_max"],
        )
        for h_items, v_items in tqdm(realigned_pairs, desc=f"Xuất dòng [{name}]")
    ]
    save_to_excel(aligned_rows, block["out_xlsx"])

    df_blk = pd.DataFrame(aligned_rows)
    n_ok = int((df_blk["Label_Target"] == 1).sum())
    n_flagged = len(df_blk) - n_ok
    blk_summary = {
        "han_input_sents": len(han_records),
        "viet_input_sents": len(viet_records),
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
        "alignment_types": df_blk["Alignment_Type"].value_counts().to_dict(),
    }

    print(
        f"    Đã lưu: output/{OUTPUT_VERSION}/{block['out_xlsx'].name} ({len(aligned_rows)} cặp) | "
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

    for block in BLOCK_CONFIGS:
        block_rows, blk_sum = run_block_alignment(block)
        all_rows.extend(block_rows)
        blocks_summary[block["name"]] = blk_sum

    save_to_excel(all_rows, FINAL_FULL_XLSX)

    df_all = pd.DataFrame(all_rows)
    summary = {
        "input_version": INPUT_VERSION,
        "output_version": OUTPUT_VERSION,
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
            "alignment_types": df_all["Alignment_Type"].value_counts().to_dict(),
        },
        "blocks": blocks_summary,
    }
    (OUT_DIR / "alignment_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(
        f"\n>>> HOÀN TẤT [{OUTPUT_VERSION}]! File tổng hợp: output/{OUTPUT_VERSION}/{FINAL_FULL_XLSX.name} "
        f"({len(all_rows)} cặp | Đạt chuẩn={summary['overall']['label_1_ok']})",
        flush=True,
    )


if __name__ == "__main__":
    main()