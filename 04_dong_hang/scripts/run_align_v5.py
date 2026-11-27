# -*- coding: utf-8 -*-
"""
Giai đoạn 04_dong_hang (Version 5 - Two-Pass Moore/Hunalign Lexical-Numeric Anchor + Vecalign Overlap & Anti-Fragmentation Boundary Smoothing):
1. Đọc trực tiếp từ `03_text_sach/output/v3/` (không dùng LLM sửa thô văn bản) và xuất ra `04_dong_hang/output/v5/PhuBienTapLuc_Alignment_V5.xlsx`
   cùng các file chi tiết từng khối (`Align_Cap_01.xlsx`, `Align_Cap_02_V.xlsx`, `Align_Cap_02_VI.xlsx`, `alignment_summary.json`).
2. Thuật toán gióng hàng 2 lượt kết hợp làm mịn biên có kiểm soát:
   - Lượt 1 (Pass 1 - Moore/Hunalign-style High-Precision Anchor DP & Auto Bilingual Lexicon Induction):
     + Khởi tạo từ điển neo miền Phủ Biên Tạp Lục (chức quan, địa danh, đơn vị tiền/gạo/đo lường, can chi, hư từ cổ, số trị >= 10).
     + Chạy gióng hàng thô ban đầu kết hợp LaBSE 1-1 margin similarity + điểm neo từ vựng/số học/trang sách để rút trích các cặp neo 1-1 độ tin cậy cao.
     + Từ tập cặp neo 1-1 sạch này, huấn luyện thêm trọng số liên kết từ vựng song ngữ tự động (Log-Likelihood / Dice association kiểu Moore Model 1) cho các cặp (chữ/cụm Hán <-> từ tiếng Việt) đặc thù trong văn bản (như tên thuyền, tên gỗ, tên người bị biến âm/OCR).
     + Khóa đường dẫn tìm kiếm (Anchor-Guided Search Corridor) đi qua các điểm neo đồng bộ vững chắc, ngăn hiện tượng trượt dây chuyền dài (cascade drift).
   - Lượt 2 (Pass 2 - Vecalign-style Multi-Overlap DP with Lexical/Numeric/Genre Scoring):
     + Tính embedding chồng lấp đa mức (overlaps 1..MAX_OVERLAP câu, tối đa 6 câu mỗi vế, tổng câu `a1 + a2 <= MAX_ALIGN_SUM`) có chuẩn hóa margin lân cận (CSLS/Vecalign margin).
     + Kết hợp điểm tương đồng ngữ nghĩa LaBSE (đã phạt độ dài hợp chuẩn theo thể loại văn xuôi / thơ văn), điểm khớp từ điển neo + từ vựng tự học Moore, điểm khớp giá trị số >= 10 (thưởng trùng khớp / phạt lệch số mồ côi), phạt rò rỉ phiên âm Hán-Việt trong thơ, và phạt nhẹ câu quá ngắn đứng lẻ.
   - Pha Làm Mịn Biên & Chống Vụn Câu (Controlled Boundary Smoothing & Anti-Fragmentation):
     + Hấp thụ mảnh khuyết vế (0-1 / 1-0) và gộp các cặp câu quá ngắn / bị cắt đứt giữa mệnh đề (dấu phẩy `,` / chấm phẩy `;` / câu Hán <= 7 chữ hoặc câu Việt <= 7 từ) vào cặp liền kề theo biên đồng bộ (cùng trang/thể loại, cải thiện chi phí gióng hàng tổng hợp và không phá vỡ điểm neo số học/câu hoàn chỉnh).
     + Tối ưu cục bộ ranh giới liền kề (k, k+1) sử dụng kết hợp điểm tương đồng nhúng LaBSE thực tế của các tổ hợp con và hàm chi phí từ vựng/số học/tỷ lệ độ dài.
3. Giữ nguyên 100% văn bản gốc và cấu trúc 12 cột chuẩn (`Pair_ID`, `Chinese`, `Vietnamese`, `OMISSION`, `ADDITION`, `MISSING`, `Alignment_Type`, `Punct_Anchor_Match`, `OCR_Valid`, `Label_Target`, `OCR_Conf_Min`, `Note`) để so sánh trực tiếp với `v4`.
"""

import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# Ưu tiên nạp model LaBSE từ cache cục bộ để chạy nhanh và không bị treo mạng trong môi trường offline
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import numpy as np
import pandas as pd
import torch
from sentence_transformers import SentenceTransformer
from tqdm import tqdm


def clean_text_line(line: str) -> str:
    s = re.sub(r"\s+", " ", line.strip())
    return s if s else "BLANK_LINE"


def yield_overlaps(lines: List[str], num_overlaps: int):
    prep = [clean_text_line(line) for line in lines]
    n = len(prep)
    for overlap in range(1, num_overlaps + 1):
        for _ in range(min(overlap - 1, n)):
            yield "PAD"
        for ii in range(n - overlap + 1):
            yield " ".join(prep[ii : ii + overlap])[:10000]

_LABSE_SNAPSHOT_GLOB = (
    Path.home()
    / ".cache"
    / "huggingface"
    / "hub"
    / "models--sentence-transformers--LaBSE"
    / "snapshots"
)
_LABSE_MODEL: Optional[SentenceTransformer] = None


def get_labse_model() -> SentenceTransformer:
    global _LABSE_MODEL
    if _LABSE_MODEL is None:
        snapshots = sorted(_LABSE_SNAPSHOT_GLOB.glob("*")) if _LABSE_SNAPSHOT_GLOB.exists() else []
        if snapshots:
            _LABSE_MODEL = SentenceTransformer(str(snapshots[-1]), local_files_only=True)
        else:
            _LABSE_MODEL = SentenceTransformer("sentence-transformers/LaBSE")
    return _LABSE_MODEL

# ==============================================================================
# 1. CẤU HÌNH ĐƯỜNG DẪN & THAM SỐ VERSION 5
# ==============================================================================
INPUT_VERSION = "v3"
OUTPUT_VERSION = "v5"

SCRIPT_DIR = Path(__file__).resolve().parent
STAGE_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = STAGE_DIR.parent
CLEAN_DIR = PROJECT_ROOT / "03_text_sach" / "output" / INPUT_VERSION
OUT_DIR = STAGE_DIR / "output" / OUTPUT_VERSION

MAX_OVERLAP = 5          # Số câu tối đa gộp ở 1 vế (1..5)
MAX_ALIGN_SUM = 7        # Cho phép m + n <= 7 (mở rộng có kiểm soát so với 5 của v4 để bắt các câu kê thuế/thơ tách nhỏ)
OCR_CONF_THRESHOLD = 0.55

BLOCK_CONFIGS = [
    {
        "name": "Cap_01",
        "genre": "prose",
        "han_file": CLEAN_DIR / "Cap_01_HAN_clean.jsonl",
        "viet_file": CLEAN_DIR / "Cap_01_VIET_clean.jsonl",
        "out_xlsx": OUT_DIR / "Align_Cap_01.xlsx",
        "ideal_low": 0.82,
        "ideal_high": 1.55,
        "ratio_min": 0.42,
        "ratio_max": 2.35,
        "min_cjk_frag": 8,
        "min_vi_frag": 8,
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
        "min_cjk_frag": 7,
        "min_vi_frag": 7,
    },
    {
        "name": "Cap_02_VI",
        "genre": "prose",
        "han_file": CLEAN_DIR / "Cap_02_VI_HAN_clean.jsonl",
        "viet_file": CLEAN_DIR / "Cap_02_VI_VIET_clean.jsonl",
        "out_xlsx": OUT_DIR / "Align_Cap_02_VI.xlsx",
        "ideal_low": 0.82,
        "ideal_high": 1.60,
        "ratio_min": 0.42,
        "ratio_max": 2.35,
        "min_cjk_frag": 8,
        "min_vi_frag": 8,
    },
]

FINAL_V5_XLSX = OUT_DIR / "PhuBienTapLuc_Alignment_V5.xlsx"
FINAL_FULL_COMPAT_XLSX = OUT_DIR / "PhuBienTapLuc_Alignment_Full.xlsx"


# ==============================================================================
# 2. CHUYỂN ĐỔI SỐ HÁN CỔ & TRÍCH XUẤT SỐ LIỆU ĐẶC TRƯNG
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
    """Chuyển chuỗi chữ số Hán cổ sang số nguyên."""
    if not token:
        return None
    if token.isdigit():
        return int(token)

    if len(token) == 1:
        if token in CN_DIGITS:
            return CN_DIGITS[token]
        if token in CN_UNITS:
            return CN_UNITS[token]
        if token in CN_SPECIAL:
            return CN_SPECIAL[token]
        return None

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

    if not has_unit and len(token) >= 2 and all(c in CN_DIGITS for c in token):
        val = 0
        for c in token:
            val = val * 10 + CN_DIGITS[c]
        return val

    total += current_digit
    return total if total > 0 else None


VI_WORD_NUMS = {
    "mười": 10,
    "hai mươi": 20,
    "ba mươi": 30,
    "bốn mươi": 40,
    "băm": 30,
    "năm mươi": 50,
    "sáu mươi": 60,
    "bảy mươi": 70,
    "tám mươi": 80,
    "chín mươi": 90,
    "một trăm": 100,
    "hai trăm": 200,
    "ba trăm": 300,
    "bốn trăm": 400,
    "năm trăm": 500,
    "một nghìn": 1000,
    "một ngàn": 1000,
    "một vạn": 10000,
    "hai vạn": 20000,
    "ba vạn": 30000,
    "năm vạn": 50000,
}


def extract_vi_numbers(vi_text: str) -> List[int]:
    """Trích xuất số nguyên tiếng Việt (hỗ trợ cả '1 vạn 4349', '4.349', chữ số chữ cái phổ biến)."""
    vals: List[int] = []
    # Xử lý dạng "X vạn Y" (ví dụ: "1 vạn 4349" -> 14349)
    for m in re.finditer(r"(\d+)\s*vạn(?:\s*(\d+))?", vi_text, flags=re.IGNORECASE):
        high = int(m.group(1)) * 10000
        low = int(m.group(2)) if m.group(2) else 0
        vals.append(high + low)

    # Xử lý số có dấu chấm phân cách hàng nghìn (ví dụ 10.285)
    cleaned = re.sub(r"(?<=\d)\.(?=\d{3}\b)", "", vi_text)
    for d in re.findall(r"\d+", cleaned):
        vals.append(int(d))

    low_vi = vi_text.lower()
    for phrase, num in VI_WORD_NUMS.items():
        if re.search(rf"\b{re.escape(phrase)}\b", low_vi):
            vals.append(num)
    return vals


def extract_number_values(zh_text: str, vi_text: str) -> Tuple[List[int], List[int]]:
    """Trích xuất danh sách giá trị số nguyên ở vế Hán và vế Việt."""
    vi_vals = extract_vi_numbers(vi_text)
    zh_vals: List[int] = []
    for m in CN_NUM_PATTERN.finditer(zh_text):
        v = chinese_num_to_int(m.group(0))
        if v is not None:
            zh_vals.append(v)
    for d in re.findall(r"\d+", zh_text):
        zh_vals.append(int(d))
    return zh_vals, vi_vals


def normalize_han_for_embedding(han_text: str) -> str:
    """Chuẩn hóa nội bộ chuỗi Hán cho LaBSE (thêm số Ả Rập bên cạnh cụm số Hán) mà không sửa văn bản gốc."""
    def _repl(match: re.Match) -> str:
        raw = match.group(0)
        val = chinese_num_to_int(raw)
        if val is None:
            return raw
        if len(raw) == 1 and raw in ("一", "二", "三") and val < 10:
            return f"{raw} {val} "
        return f" {val} "

    normalized = CN_NUM_PATTERN.sub(_repl, han_text)
    return re.sub(r"\s+", " ", normalized).strip()


# ==============================================================================
# 3. TỪ ĐIỂN NEO MIỀN (CHỨC QUAN, ĐỊA DANH, ĐƠN VỊ TIỀN/GẠO, CAN CHI) & MOORE LEXICON
# ==============================================================================
# Danh mục từ vựng neo biên soạn cho Phủ Biên Tạp Lục (bao phủ cả biến thể giản thể/phồn thể & lỗi OCR thường gặp)
SEED_ANCHOR_LEXICON: List[Tuple[str, str, float]] = [
    # --- Đơn vị tiền tệ, thuế khóa, đo lường ---
    (r"貫|贯", r"\bquan\b", 0.30),
    (r"陌", r"\btiền\b", 0.25),
    (r"文", r"\bđồng\b", 0.22),
    (r"兩|两", r"\blạng\b", 0.30),
    (r"笏|忽", r"\bhốt\b", 0.35),
    (r"米", r"\bgạo\b", 0.32),
    (r"粟|穀|谷", r"\bthóc\b", 0.32),
    (r"鉢|钵|秩", r"\bbát\b", 0.28),
    (r"升", r"\bthưng\b", 0.35),
    (r"合", r"\bcáp\b", 0.30),
    (r"尺", r"\bthước\b", 0.32),
    (r"寸", r"\btấc\b", 0.32),
    (r"斤", r"\bcân\b", 0.28),
    (r"畝|亩", r"\bmẫu\b", 0.35),
    (r"篙|高", r"\bsào\b", 0.25),
    (r"艘|船|般", r"\bthuyền\b|\bchiếc\b", 0.28),
    (r"象", r"\bvoi\b|\btượng\b", 0.32),
    (r"馬|马", r"\bngựa\b|\bmã\b", 0.28),
    # --- Chức quan, ngạch binh, hạng đinh ---
    (r"知府|葬府", r"\btri phủ\b", 0.45),
    (r"知縣|知县", r"\btri huyện\b", 0.45),
    (r"訓導|训导|到導|到导", r"\bhuấn đạo\b", 0.48),
    (r"該府|该府", r"\bcai phủ\b", 0.45),
    (r"記府|记府|祀府", r"\bký phủ\b", 0.45),
    (r"記縣|记县|祀縣|祀县", r"\bký huyện\b", 0.45),
    (r"該總|该总", r"\bcai tổng\b", 0.45),
    (r"該社|该社|欣社", r"\bcai xã\b", 0.42),
    (r"社長|社长", r"\bxã trưởng\b", 0.45),
    (r"將臣|将臣|時臣|时臣", r"\btướng thần\b", 0.48),
    (r"首合", r"\bthủ hợp\b", 0.48),
    (r"該合|该合", r"\bcai hợp\b", 0.48),
    (r"司吏", r"\bty lại\b", 0.45),
    (r"提吏|糧吏|粮吏", r"\bđề lại\b", 0.45),
    (r"通吏|通夾|通夹", r"\bthông lại\b", 0.45),
    (r"隊長|队长|陽長|阳长", r"\bđội trưởng\b", 0.40),
    (r"記錄|记录|己錄|己录", r"\bký lục\b", 0.45),
    (r"該簿|该簿|後落|后落", r"\bcai bạ\b", 0.45),
    (r"戶部|户部", r"\bhộ bộ\b", 0.48),
    (r"禮部|礼部", r"\blễ bộ\b", 0.48),
    (r"吏部", r"\blại bộ\b", 0.48),
    (r"兵部", r"\bbinh bộ\b", 0.48),
    (r"尚書|尚书", r"\bthượng thư\b", 0.48),
    (r"進士|进士", r"\btiến sĩ\b", 0.48),
    (r"生徒|生徒", r"\bsinh đồ\b|\bsinh đô\b", 0.45),
    (r"饒學|饶学|說孝|说孝", r"\bnhiêu học\b|\bnhiêu - học\b", 0.48),
    (r"饒夫|饶夫|樣夫|样夫", r"\bnhiêu phu\b", 0.45),
    (r"正戶|正户", r"\bchính hộ\b", 0.45),
    (r"客戶|客户", r"\bkhách hộ\b", 0.45),
    (r"老項|老项", r"\bhạng lão\b", 0.45),
    (r"雇項|雇项|雇一|雇二|雇三", r"\bhạng cố\b", 0.45),
    (r"窮項|穷项", r"\bhạng cùng\b", 0.45),
    (r"逃亡| xiêu", r"\bphiêu tán\b|\btrốn\b|\bxiêu\b", 0.35),
    (r"寓祿|寓禄|富祿|富禄", r"\bngụ lộc\b", 0.45),
    (r"別納|别纳|別初|别初", r"\bbiệt nạp\b", 0.48),
    (r"上禮|上礼", r"\bthượng lễ\b", 0.45),
    (r"內禮|内礼", r"\bnội lễ\b", 0.45),
    (r"正旦", r"\bchính đán\b", 0.50),
    # --- Địa danh & Nhân vật lịch sử trọng yếu ---
    (r"順化|顺化", r"\bthuận hoá\b|\bthuận hóa\b", 0.45),
    (r"廣南|广南", r"\bquảng nam\b", 0.45),
    (r"順廣|顺广|廣順|广顺", r"\bthuận quảng\b", 0.48),
    (r"升華|升华|升葬", r"\bthăng hoa\b", 0.50),
    (r"富春|隱春|隐春|隔春", r"\bphú xuân\b|\bdương xuân\b", 0.45),
    (r"富榮|富荣", r"\bphú vang\b", 0.50),
    (r"香茶|香柔", r"\bhương trà\b", 0.50),
    (r"廣田|广田", r"\bquảng điền\b", 0.50),
    (r"康祿|康禄|秦祿|秦禄", r"\bkhang lộc\b", 0.50),
    (r"麗水|丽水|麗小|丽小", r"\blệ thuỷ\b|\blệ thủy\b", 0.50),
    (r"布政|市政|制政", r"\bbố chính\b", 0.50),
    (r"廣義|广义", r"\bquảng ngãi\b", 0.50),
    (r"歸仁|归仁|兩仁|两仁", r"\bquy nhơn\b", 0.50),
    (r"平康|平乘", r"\bbình khang\b", 0.50),
    (r"延慶|延庆", r"\bdiên khánh\b", 0.50),
    (r"平順|平顺", r"\bbình thuận\b", 0.50),
    (r"嘉定|嘉宏|義定|义定", r"\bgia định\b", 0.50),
    (r"河仙", r"\bhà tiên\b", 0.55),
    (r"乂安", r"\bnghệ an\b", 0.52),
    (r"石河", r"\bthạch hà\b", 0.52),
    (r"洞海", r"\bđộng hải\b", 0.55),
    (r"天姥|天兆", r"\bthiên mụ\b", 0.52),
    (r"文廟|文庙", r"\bvăn miếu\b", 0.52),
    (r"端國公|端国公", r"\bđoan quốc công\b", 0.55),
    (r"居貞|居贞|知貞|知贞", r"\bcư trinh\b|\bcư trình\b", 0.55),
    (r"鄧悉|邓悉", r"\bđặng tất\b", 0.55),
    (r"洪德", r"\bhồng đức\b", 0.52),
    (r"景興|景兴", r"\bcảnh hưng\b", 0.52),
    (r"景治", r"\bcảnh trị\b", 0.52),
    # --- Can Chi / Mốc năm ---
    (r"甲子", r"\bgiáp tý\b", 0.55),
    (r"乙丑", r"\bất sửu\b|\bất dậu\b", 0.45),
    (r"丙戌", r"\bbính tuất\b", 0.55),
    (r"己丑|已丑", r"\bkỷ sửu\b", 0.55),
    (r"庚申", r"\bcanh thân\b", 0.55),
    (r"癸酉", r"\bquý dậu\b", 0.55),
    (r"乙亥", r"\bất hợi\b", 0.55),
    # --- Tiêu đề thơ / Sản vật đặc trưng ---
    (r"一曰", r"\bbài đầu\b|\bmột là\b|\bkim dữ\b", 0.35),
    (r"二曰", r"\bhai là\b|\bbình sơn\b", 0.35),
    (r"三曰", r"\bba là\b|\btiêu tự\b", 0.35),
    (r"四曰", r"\bbốn là\b|\bgiang thành\b", 0.35),
    (r"五曰", r"\bnăm là\b", 0.35),
    (r"六曰", r"\bsáu là\b", 0.35),
    (r"七曰", r"\bbảy là\b", 0.35),
    (r"八曰", r"\btám là\b", 0.35),
    (r"九曰", r"\bchín là\b", 0.35),
    (r"十曰", r"\bmười là\b", 0.35),
    (r"人參|人参", r"\bnhân sâm\b", 0.50),
    (r"犀角", r"\bsừng tê\b", 0.52),
    (r"象牙", r"\bngà voi\b", 0.52),
    (r"鐵林|鉄林|缺林", r"\bgỗ lim\b", 0.48),
    (r"抄木", r"\bgỗ sao\b", 0.50),
    (r"楠木|曰楠", r"\bgỗ nam\b|\bhương nam\b|\bbạch nam\b", 0.50),
]

COMPILED_SEED_LEXICON = [
    (re.compile(zh_pat), re.compile(vi_pat, flags=re.IGNORECASE), weight)
    for zh_pat, vi_pat, weight in SEED_ANCHOR_LEXICON
]

BOUNDARY_LEXICAL_PAIRS = [
    (re.compile(r"^又"), re.compile(r"^(?:lại|vả lại)\b", re.IGNORECASE), 0.22),
    (re.compile(r"^凡"), re.compile(r"^phàm\b", re.IGNORECASE), 0.25),
    (re.compile(r"^按"), re.compile(r"^xét\b", re.IGNORECASE), 0.25),
    (re.compile(r"^其"), re.compile(r"^(?:về|còn như|còn|ngoài ra)\b", re.IGNORECASE), 0.20),
    (re.compile(r"^至如|^至於|^至于"), re.compile(r"^(?:đến như|cho đến)\b", re.IGNORECASE), 0.25),
    (re.compile(r"^但如|^但"), re.compile(r"^(?:nhưng nếu|nhưng|song|duy)\b", re.IGNORECASE), 0.22),
    (re.compile(r"耳[。！？]?$"), re.compile(r"\bthôi[.,;!?]?$", re.IGNORECASE), 0.22),
    (re.compile(r"[也矣][。！？]?$"), re.compile(r"\bvậy[.,;!?]?$", re.IGNORECASE), 0.20),
    (re.compile(r"[哉乎][。！？]?$"), re.compile(r"(?:chăng|thay|ư|sao|không)[?!.]?$", re.IGNORECASE), 0.22),
]

VI_STOPWORDS = {
    "và", "của", "là", "có", "các", "những", "được", "trong", "cho", "với", "làm", "không",
    "người", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín", "mười", "mỗi",
    "thì", "mà", "đều", "ở", "từ", "đến", "như", "cũng", "lại", "ra", "vào", "lên", "xuống",
    "ấy", "này", "đó", "về", "theo", "lấy", "phải", "còn", "hay", "hoặc", "rất", "lắm",
}


def extract_zh_ngrams(text: str) -> Set[str]:
    """Tách ký tự đơn và bigram chữ Hán để học từ điển Moore tự động."""
    cjk = [ch for ch in text if "\u4e00" <= ch <= "\u9fff"]
    feats: Set[str] = set()
    for ch in cjk:
        if ch not in "之乎者也矣焉哉於于而以則其及與与不無无有為为曰云人一二三四五六七八九十百千萬万":
            feats.add(ch)
    for idx in range(len(cjk) - 1):
        bg = cjk[idx] + cjk[idx + 1]
        feats.add(bg)
    return feats


def extract_vi_tokens(text: str) -> Set[str]:
    """Tách từ đơn và từ ghép 2 âm tiết tiếng Việt để học từ điển Moore tự động."""
    words = [
        w.lower()
        for w in re.findall(r"[a-zA-ZÀ-ỹĐđ]+", text)
        if len(w) >= 2 and w.lower() not in VI_STOPWORDS
    ]
    feats = set(words)
    for idx in range(len(words) - 1):
        feats.add(f"{words[idx]} {words[idx + 1]}")
    return feats


def induce_moore_bilingual_lexicon(
    han_records: List[Dict],
    viet_records: List[Dict],
    anchor_pairs: List[Tuple[int, int]],
    min_cooc: int = 3,
    min_dice: float = 0.42,
) -> Dict[Tuple[str, str], float]:
    """
    Học tự động bảng tương hợp từ vựng song ngữ (kiểu Moore / Hunalign Pass-1 -> Pass-2)
    từ tập cặp neo 1-1 có độ tin cậy cao của chính khối văn bản đang gióng hàng.
    """
    zh_df: Counter = Counter()
    vi_df: Counter = Counter()
    cooc: Counter = Counter()

    for hi, vj in anchor_pairs:
        zh_feats = extract_zh_ngrams(han_records[hi]["han_co_goc"])
        vi_feats = extract_vi_tokens(viet_records[vj]["text_vi"])
        for zf in zh_feats:
            zh_df[zf] += 1
        for vf in vi_feats:
            vi_df[vf] += 1
        for zf in zh_feats:
            for vf in vi_feats:
                cooc[(zf, vf)] += 1

    learned: Dict[Tuple[str, str], float] = {}
    for (zf, vf), c_zv in cooc.items():
        if c_zv < min_cooc:
            continue
        dice = (2.0 * c_zv) / (zh_df[zf] + vi_df[vf])
        if dice >= min_dice:
            # Trọng số có trần an toàn để tránh nhiễu từ phổ biến
            weight = min(0.35, 0.18 * dice * math.log2(1.0 + c_zv))
            learned[(zf, vf)] = weight
    return learned


# ==============================================================================
# 4. ĐẶC TRƯNG ĐOẠN GỘP & HÀM ĐIỂM NEO TỪ VỰNG / SỐ HỌC / THỂ LOẠI
# ==============================================================================
def count_cjk_chars(text: str) -> int:
    return sum(
        1
        for ch in text
        if ("\u4e00" <= ch <= "\u9fff")
        or ("\u3400" <= ch <= "\u4dbf")
        or ("\uf900" <= ch <= "\ufaff")
    )


SINO_VIET_SYLLABLES = {
    "nhất", "nhị", "tam", "tứ", "ngũ", "lục", "thất", "bát", "cửu", "thập", "bách", "thiên", "vạn",
    "thiên", "địa", "nhân", "gia", "quốc", "sơn", "thuỷ", "thủy", "phong", "vân", "nguyệt", "nhật",
    "xuân", "hạ", "thu", "đông", "hoa", "thảo", "mộc", "thụ", "lâm", "giang", "hà", "hải", "khê",
    "thành", "lâu", "đài", "các", "tự", "chung", "cổ", "tửu", "thi", "ca", "phượng", "lân", "độc",
    "cô", "nhàn", "tuý", "túy", "mộng", "tâm", "tình", "hận", "bi", "hoan", "khách", "quân", "thần",
    "bình", "nguyên", "thâm", "giản", "ngư", "phủ", "mục", "đồng", "hữu", "vô", "tại", "vi", "tác",
    "bất", "tri", "hà", "xứ", "kim", "cổ", "sinh", "tử", "mệnh", "thời", "hồ", "hĩ", "tai", "nhĩ",
}


def detect_transliteration_leak(vi_text: str) -> bool:
    """
    Phát hiện dòng tiếng Việt bị dính câu phiên âm Hán-Việt nguyên bài thơ (như 'Thác lạc nhân gia lục thụ gian',
    'Lỗ thánh khấp lân trí mạnh hĩ') vốn thường không nên tách riêng làm vế dịch độc lập cho câu thơ khác.
    """
    words = [w.lower() for w in re.findall(r"[a-zA-ZÀ-ỹĐđ]+", vi_text)]
    if len(words) < 5:
        return False
    sv_hits = sum(1 for w in words if w in SINO_VIET_SYLLABLES)
    # Các từ thuần Việt đặc trưng chỉ xuất hiện trong bản dịch nghĩa, hiếm có trong phiên âm Hán-Việt
    native_markers = {"những", "chẳng", "không", "được", "trong", "ngoài", "của", "nhưng", "rằng", "ấy", "này", "mấy"}
    native_hits = sum(1 for w in words if w in native_markers)
    return (sv_hits / len(words) >= 0.55) and (native_hits == 0)


class PrecomputedCorpusFeatures:
    """
    Tiền tính toán toàn bộ đặc trưng số học, từ điển neo hạt giống, hư từ biên và n-gram Moore
    cho từng câu đơn để việc hợp nhất đặc trưng trên đoạn gộp `1..max_overlap` diễn ra bằng phép hợp tập hợp O(1),
    không phải chạy lại hàng trăm biểu thức chính quy trong vòng lặp quy hoạch động.
    """

    def __init__(
        self,
        han_records: List[Dict],
        viet_records: List[Dict],
        learned_lexicon: Optional[Dict[Tuple[str, str], float]] = None,
    ):
        self.n_src = len(han_records)
        self.n_tgt = len(viet_records)

        # Số học từng câu
        self.zh_nums: List[Set[int]] = []
        for hr in han_records:
            zv, _ = extract_number_values(hr["han_co_goc"], "")
            self.zh_nums.append(set(zv))

        self.vi_nums: List[Set[int]] = []
        for vr in viet_records:
            self.vi_nums.append(set(extract_vi_numbers(vr["text_vi"])))

        # Chỉ số các mục từ điển neo hạt giống xuất hiện ở từng câu
        self.zh_seed_hits: List[Set[int]] = []
        for hr in han_records:
            txt = hr["han_co_goc"]
            self.zh_seed_hits.append({k for k, (z_re, _, _) in enumerate(COMPILED_SEED_LEXICON) if z_re.search(txt)})

        self.vi_seed_hits: List[Set[int]] = []
        for vr in viet_records:
            txt = vr["text_vi"]
            self.vi_seed_hits.append({k for k, (_, v_re, _) in enumerate(COMPILED_SEED_LEXICON) if v_re.search(txt)})

        self.seed_weights = [w for _, _, w in COMPILED_SEED_LEXICON]

        # Hư từ đầu câu / cuối câu & dấu câu đặc biệt
        self.zh_start_b: List[Set[int]] = []
        self.zh_end_b: List[Set[int]] = []
        self.zh_punct: List[Set[str]] = []
        for hr in han_records:
            s = hr["han_co_goc"].strip()
            self.zh_start_b.append({k for k in range(6) if BOUNDARY_LEXICAL_PAIRS[k][0].search(s)})
            self.zh_end_b.append({k for k in range(6, 9) if BOUNDARY_LEXICAL_PAIRS[k][0].search(s)})
            self.zh_punct.append({p for p in ("？", "！", "：") if p in s})

        self.vi_start_b: List[Set[int]] = []
        self.vi_end_b: List[Set[int]] = []
        self.vi_punct: List[Set[str]] = []
        for vr in viet_records:
            s = vr["text_vi"].strip()
            self.vi_start_b.append({k for k in range(6) if BOUNDARY_LEXICAL_PAIRS[k][1].search(s)})
            self.vi_end_b.append({k for k in range(6, 9) if BOUNDARY_LEXICAL_PAIRS[k][1].search(s)})
            self.vi_punct.append({p for p in ("?", "!", ":") if p in s})

        # Bảng tra nhanh Moore lexicon: ánh xạ mỗi zh_ngram -> list[(vi_tok, weight)]
        self.moore_adj: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
        if learned_lexicon:
            for (zf, vf), w in learned_lexicon.items():
                self.moore_adj[zf].append((vf, w))

        active_zh_keys = set(self.moore_adj.keys())
        active_vi_keys = {vf for (_, vf) in learned_lexicon.keys()} if learned_lexicon else set()

        self.zh_moore_feats: List[Set[str]] = [
            extract_zh_ngrams(hr["han_co_goc"]) & active_zh_keys if active_zh_keys else set()
            for hr in han_records
        ]
        self.vi_moore_feats: List[Set[str]] = [
            extract_vi_tokens(vr["text_vi"]) & active_vi_keys if active_vi_keys else set()
            for vr in viet_records
        ]

    def score_span(self, s_start: int, s_end: int, t_start: int, t_end: int) -> float:
        """
        Tính điểm neo từ vựng + số học cho đoạn nguồn `[s_start, s_end)` và đoạn đích `[t_start, t_end)`.
        Hoàn toàn dùng phép hợp tập hợp số nguyên/chuỗi đã tiền xử lý, tốc độ ~50x nhanh hơn regex trực tiếp.
        """
        if s_start >= s_end or t_start >= t_end:
            return 0.0

        score = 0.0

        # 1. Điểm số học
        z_nums: Set[int] = set()
        for i in range(s_start, s_end):
            z_nums |= self.zh_nums[i]
        v_nums: Set[int] = set()
        for j in range(t_start, t_end):
            v_nums |= self.vi_nums[j]

        sig_zh = {x for x in z_nums if x >= 10}
        sig_vi = {x for x in v_nums if x >= 10}
        shared_sig = sig_zh & sig_vi
        unmatched_sig = sig_zh ^ sig_vi

        if shared_sig:
            large_bonus = sum(0.28 if v >= 100 else 0.18 for v in shared_sig)
            score += min(0.85, large_bonus)

        if len(sig_zh) >= 2 and len(sig_vi) >= 2 and not shared_sig:
            score -= 0.35
        elif len(unmatched_sig) >= 3 and not shared_sig:
            score -= 0.28
        else:
            score -= min(0.24, 0.06 * len(unmatched_sig))

        small_zh = {x for x in z_nums if 2 <= x <= 9}
        small_vi = {x for x in v_nums if 2 <= x <= 9}
        shared_small = small_zh & small_vi
        if shared_small:
            score += min(0.14, 0.045 * len(shared_small))

        # 2. Điểm từ điển neo hạt giống
        z_seeds: Set[int] = set()
        for i in range(s_start, s_end):
            z_seeds |= self.zh_seed_hits[i]
        if z_seeds:
            v_seeds: Set[int] = set()
            for j in range(t_start, t_end):
                v_seeds |= self.vi_seed_hits[j]
            common_seeds = z_seeds & v_seeds
            if common_seeds:
                seed_bonus = sum(self.seed_weights[k] for k in common_seeds)
                score += min(0.75, seed_bonus * 0.45)

        # 3. Hư từ đầu/cuối đoạn & dấu câu
        bound_bonus = 0.0
        common_start = self.zh_start_b[s_start] & self.vi_start_b[t_start]
        for k in common_start:
            bound_bonus += BOUNDARY_LEXICAL_PAIRS[k][2]
        common_end = self.zh_end_b[s_end - 1] & self.vi_end_b[t_end - 1]
        for k in common_end:
            bound_bonus += BOUNDARY_LEXICAL_PAIRS[k][2]

        zp: Set[str] = set()
        for i in range(s_start, s_end):
            zp |= self.zh_punct[i]
        if zp:
            vp: Set[str] = set()
            for j in range(t_start, t_end):
                vp |= self.vi_punct[j]
            for zh_p, vi_p in [("？", "?"), ("！", "!"), ("：", ":")]:
                if zh_p in zp and vi_p in vp:
                    bound_bonus += 0.08
        score += min(0.30, bound_bonus * 0.5)

        # 4. Điểm từ điển song ngữ tự học Moore
        if self.moore_adj:
            zf_set: Set[str] = set()
            for i in range(s_start, s_end):
                zf_set |= self.zh_moore_feats[i]
            if zf_set:
                vf_set: Set[str] = set()
                for j in range(t_start, t_end):
                    vf_set |= self.vi_moore_feats[j]
                if vf_set:
                    moore_bonus = 0.0
                    for zf in zf_set:
                        for vf, w in self.moore_adj[zf]:
                            if vf in vf_set:
                                moore_bonus += w
                    score += min(0.35, moore_bonus * 0.40)

        return score


# ==============================================================================
# 5. MÃ HÓA ĐA MỨC OVERLAP (VECALIGN/BERTALIGN) & MA TRẬN CSLS MARGIN
# ==============================================================================
def encode_single_and_build_overlaps(sents: List[str], max_overlap: int) -> Tuple[np.ndarray, np.ndarray]:
    """
    Mã hóa LaBSE trên từng câu đơn (1x N câu -> cực nhanh trên CPU, không nghẽn O(L^2) attention của câu gộp dài),
    sau đó tổng hợp embedding chồng lấp đa mức 1..max_overlap bằng tổng có trọng số độ dài chuẩn hóa L2
    (Mean-Pooled Normalized Sub-Segment Embedding theo Vecalign / Laser-Overlap).
    Trả về:
      - vecs: shape (max_overlap, N, dim) đã chuẩn hóa L2
      - byte_lens: shape (max_overlap, N) độ dài UTF-8 byte chính xác của đoạn gộp
    """
    prep = [clean_text_line(s) for s in sents]
    n_sents = len(prep)
    encoder = get_labse_model()

    t0 = os.times()
    single_vecs = np.asarray(
        encoder.encode(prep, batch_size=64, show_progress_bar=False, normalize_embeddings=True),
        dtype=np.float32,
    )
    dim = single_vecs.shape[-1]

    single_bytes = np.array([len(s.encode("utf-8")) for s in prep], dtype=np.float32)
    # Trọng số theo căn bậc hai độ dài byte giúp câu dài đóng góp nhiều hơn câu cụt mà không nuốt chửng mệnh đề ngắn
    weights = np.sqrt(np.maximum(single_bytes, 4.0))[:, None]
    weighted_single = single_vecs * weights

    vecs = np.zeros((max_overlap, n_sents, dim), dtype=np.float32)
    byte_lens = np.zeros((max_overlap, n_sents), dtype=np.float32)

    vecs[0] = single_vecs
    byte_lens[0] = single_bytes

    # Prefix sums cho tổng hợp vector O(1) mỗi đoạn overlap
    prefix_vec = np.zeros((n_sents + 1, dim), dtype=np.float32)
    prefix_vec[1:] = np.cumsum(weighted_single, axis=0)

    prefix_bytes = np.zeros(n_sents + 1, dtype=np.float32)
    prefix_bytes[1:] = np.cumsum(single_bytes)

    for ov in range(2, max_overlap + 1):
        ov_idx = ov - 1
        # Các vị trí đầu < ov - 1 tương ứng PAD
        byte_lens[ov_idx, : ov - 1] = 3.0
        if n_sents >= ov:
            end_idxs = np.arange(ov - 1, n_sents)
            sum_v = prefix_vec[end_idxs + 1] - prefix_vec[end_idxs + 1 - ov]
            norms = np.linalg.norm(sum_v, axis=1, keepdims=True)
            vecs[ov_idx, ov - 1 :] = sum_v / np.maximum(norms, 1e-8)
            byte_lens[ov_idx, ov - 1 :] = (
                prefix_bytes[end_idxs + 1] - prefix_bytes[end_idxs + 1 - ov] + (ov - 1)
            )

    return vecs, byte_lens


def build_raw_text_overlaps(items: List[Dict], field: str, max_overlap: int) -> List[List[str]]:
    """Tạo bảng tra nhanh chuỗi gộp văn bản gốc (1..max_overlap) phục vụ tính điểm từ vựng/số học."""
    n = len(items)
    raw_sents = [x[field] for x in items]
    mat: List[List[str]] = []
    for ov in range(1, max_overlap + 1):
        row = []
        for end_idx in range(n):
            start_idx = end_idx - ov + 1
            if start_idx < 0:
                row.append("")
            else:
                row.append(" ".join(raw_sents[start_idx : end_idx + 1]))
        mat.append(row)
    return mat


def compute_margin_similarity(
    src_vecs: np.ndarray,
    tgt_vecs: np.ndarray,
    i: int,
    j: int,
    a1: int,
    a2: int,
) -> float:
    """
    Tính điểm tương đồng ngữ nghĩa Vecalign/Bertalign có trừ trung bình lân cận (margin)
    cho đoạn nguồn kết thúc tại câu `i` (độ dài `a1`) và đoạn đích kết thúc tại câu `j` (độ dài `a2`).
    Chỉ số `i`, `j` tính từ 1..N.
    """
    n_src = src_vecs.shape[1]
    n_tgt = tgt_vecs.shape[1]
    sv = src_vecs[a1 - 1, i - 1]
    tv = tgt_vecs[a2 - 1, j - 1]
    sim = float(np.dot(sv, tv))

    # Lân cận phía đích
    t_left = j - a2
    t_right = j + 1
    t_ns = []
    if t_left >= 1:
        t_ns.append(float(np.dot(sv, tgt_vecs[0, t_left - 1])))
    if t_right <= n_tgt:
        t_ns.append(float(np.dot(sv, tgt_vecs[0, t_right - 1])))
    t_avg = sum(t_ns) / len(t_ns) if t_ns else 0.0

    # Lân cận phía nguồn
    s_left = i - a1
    s_right = i + 1
    s_ns = []
    if s_left >= 1:
        s_ns.append(float(np.dot(tv, src_vecs[0, s_left - 1])))
    if s_right <= n_src:
        s_ns.append(float(np.dot(tv, src_vecs[0, s_right - 1])))
    s_avg = sum(s_ns) / len(s_ns) if s_ns else 0.0

    return sim - 0.5 * (t_avg + s_avg)


# ==============================================================================
# 6. HAI LƯỢT GIÓNG HÀNG ĐỘNG (PASS 1 ANCHOR + PASS 2 OVERLAP DP)
# ==============================================================================
def run_pass1_anchor_extraction(
    han_records: List[Dict],
    viet_records: List[Dict],
    src_vecs: np.ndarray,
    tgt_vecs: np.ndarray,
    feats_p1: PrecomputedCorpusFeatures,
    top_k: int = 8,
) -> Tuple[List[Tuple[int, int]], List[Tuple[int, int]]]:
    """
    Lượt 1 (Moore/Hunalign Pass-1 Anchor Alignment):
    - Tìm top-k ứng viên 1-1 bằng ma trận cosine kết hợp thưởng từ điển neo hạt giống + con số >= 10.
    - Giải quy hoạch động 1-1 / 1-0 / 0-1 trên dải đường chéo mở rộng để thu đường dẫn thô `coarse_path`
      và lọc ra tập cặp neo 1-1 chất lượng cao `high_conf_anchors` (dùng để học từ điển Moore & ghim hành lang Pass 2).
    """
    n_src = len(han_records)
    n_tgt = len(viet_records)
    k = min(top_k, n_tgt)

    sim_mat = np.matmul(src_vecs[0], tgt_vecs[0].T)
    part_idxs = np.argpartition(-sim_mat, k - 1, axis=1)[:, :k]
    row_arange = np.arange(n_src)[:, None]
    part_sims = sim_mat[row_arange, part_idxs]
    order = np.argsort(-part_sims, axis=1)
    idxs = part_idxs[row_arange, order]
    dists = part_sims[row_arange, order]

    # Tạo bảng điểm sparse cho các cặp 1-1 tiềm năng
    cand_scores: Dict[Tuple[int, int], float] = {}
    for hi in range(n_src):
        for rank in range(idxs.shape[1]):
            vj = int(idxs[hi, rank])
            if vj < 0:
                continue
            sem_sim = float(dists[hi, rank])
            lex_num = feats_p1.score_span(hi, hi + 1, vj, vj + 1)
            cand_scores[(hi, vj)] = sem_sim + 0.55 * lex_num

    # Bổ sung trực tiếp các cặp khớp số lớn hiếm (>= 20) nằm gần vị trí tương đối ngay cả khi OCR làm giảm điểm cosine
    sig_num_to_vi: Dict[int, List[int]] = defaultdict(list)
    for vj in range(n_tgt):
        for val in feats_p1.vi_nums[vj]:
            if val >= 20:
                sig_num_to_vi[val].append(vj)

    yx_ratio = n_tgt / max(n_src, 1)
    for hi in range(n_src):
        for val in feats_p1.zh_nums[hi]:
            if val >= 20 and 1 <= len(sig_num_to_vi.get(val, [])) <= 4:
                for vj in sig_num_to_vi[val]:
                    if abs(vj - hi * yx_ratio) <= 120 and (hi, vj) not in cand_scores:
                        sem_sim = float(sim_mat[hi, vj])
                        lex_num = feats_p1.score_span(hi, hi + 1, vj, vj + 1)
                        cand_scores[(hi, vj)] = sem_sim + 0.65 * lex_num

    # DP Lượt 1 trong hành lang đường chéo (win_size = 240)
    win_size = max(220, int(max(n_src, n_tgt) * 0.08))
    search_bounds = []
    for i in range(n_src + 1):
        center = int(round(yx_ratio * i))
        search_bounds.append((max(0, center - win_size), min(n_tgt, center + win_size)))

    dp_cost: List[np.ndarray] = []
    dp_ptr: List[np.ndarray] = []
    for i in range(n_src + 1):
        j_lo, j_hi = search_bounds[i]
        width = j_hi - j_lo + 1
        dp_cost.append(np.full(width, -1e9, dtype=np.float32))
        dp_ptr.append(np.zeros(width, dtype=np.uint8))

    dp_cost[0][0] = 0.0
    skip_1 = -0.04

    for i in range(n_src + 1):
        j_lo, j_hi = search_bounds[i]
        for j in range(j_lo, j_hi + 1):
            if i == 0 and j == 0:
                continue
            best_sc = -1e9
            best_op = 0  # 0: (0,1), 1: (1,0), 2: (1,1)

            # (0, 1): tiến đích
            if j - 1 >= j_lo:
                sc = float(dp_cost[i][j - 1 - j_lo]) + skip_1
                if sc > best_sc:
                    best_sc = sc
                    best_op = 0

            # (1, 0): tiến nguồn
            if i >= 1:
                p_lo, p_hi = search_bounds[i - 1]
                if p_lo <= j <= p_hi:
                    sc = float(dp_cost[i - 1][j - p_lo]) + skip_1
                    if sc > best_sc:
                        best_sc = sc
                        best_op = 1

            # (1, 1): khớp neo
            if i >= 1 and j >= 1:
                p_lo, p_hi = search_bounds[i - 1]
                if p_lo <= j - 1 <= p_hi:
                    match_sc = cand_scores.get((i - 1, j - 1), -0.25)
                    sc = float(dp_cost[i - 1][(j - 1) - p_lo]) + match_sc
                    if sc > best_sc:
                        best_sc = sc
                        best_op = 2

            dp_cost[i][j - j_lo] = best_sc
            dp_ptr[i][j - j_lo] = best_op

    # Truy vết Pass 1
    ci, cj = n_src, n_tgt
    coarse_1to1: List[Tuple[int, int]] = []
    high_conf_anchors: List[Tuple[int, int]] = []

    while ci > 0 or cj > 0:
        j_lo, _ = search_bounds[ci]
        op = int(dp_ptr[ci][cj - j_lo])
        if op == 2:
            hi, vj = ci - 1, cj - 1
            coarse_1to1.append((hi, vj))
            raw_sc = cand_scores.get((hi, vj), 0.0)
            cjk_l = count_cjk_chars(han_records[hi]["han_co_goc"])
            vi_w = len(viet_records[vj]["text_vi"].split())
            ratio = vi_w / max(cjk_l, 1)
            if raw_sc >= 0.58 and 0.50 <= ratio <= 2.40 and cjk_l >= 6:
                high_conf_anchors.append((hi, vj))
            ci -= 1
            cj -= 1
        elif op == 1:
            ci -= 1
        else:
            cj -= 1

    coarse_1to1.reverse()
    high_conf_anchors.reverse()
    return coarse_1to1, high_conf_anchors


def build_second_pass_corridor(
    coarse_1to1: List[Tuple[int, int]],
    n_src: int,
    n_tgt: int,
    win_margin: int = 8,
) -> List[Tuple[int, int]]:
    """Xây dựng hành lang tìm kiếm hẹp nhưng đủ rộng (win_margin=8) bám theo quỹ đạo đồng bộ Pass 1."""
    knots = [(0, 0)] + [(hi + 1, vj + 1) for hi, vj in coarse_1to1]
    if knots[-1] != (n_src, n_tgt):
        knots.append((n_src, n_tgt))

    bounds: List[Tuple[int, int]] = [(0, min(n_tgt, win_margin))]
    prev_s, prev_t = 0, 0
    for cur_s, cur_t in knots[1:]:
        if cur_s <= prev_s:
            prev_t = max(prev_t, cur_t)
            continue
        lo = max(0, prev_t - win_margin)
        hi = min(n_tgt, cur_t + win_margin)
        for _s in range(prev_s + 1, cur_s + 1):
            bounds.append((lo, hi))
        prev_s, prev_t = cur_s, cur_t

    # Đảm bảo đầu mút cuối chứa n_tgt
    b_lo, b_hi = bounds[n_src]
    bounds[n_src] = (b_lo, max(b_hi, n_tgt))
    return bounds


def get_v5_alignment_types(max_overlap: int = 5, max_sum: int = 7) -> List[Tuple[int, int]]:
    """Sinh các kiểu ghép (0,1), (1,0) và (x, y) với 1<=x,y<=max_overlap và x+y <= max_sum."""
    types: List[Tuple[int, int]] = [(0, 1), (1, 0)]
    for x in range(1, max_overlap + 1):
        for y in range(1, max_overlap + 1):
            if x + y <= max_sum:
                types.append((x, y))
    return types


def run_pass2_overlap_dp(
    han_records: List[Dict],
    viet_records: List[Dict],
    src_vecs: np.ndarray,
    tgt_vecs: np.ndarray,
    src_lens: np.ndarray,
    tgt_lens: np.ndarray,
    corridor: List[Tuple[int, int]],
    feats_p2: PrecomputedCorpusFeatures,
    block_cfg: Dict,
) -> List[Tuple[List[int], List[int]]]:
    """
    Lượt 2 (Vecalign-style Overlap DP + Moore/Domain Lexical-Numeric Scoring + Anti-Fragmentation Prior):
    Tìm phân hoạch toàn cục tối ưu tổng điểm khớp đoạn m-n.
    """
    n_src = len(han_records)
    n_tgt = len(viet_records)
    char_ratio = float(np.sum(src_lens[0]) / max(np.sum(tgt_lens[0]), 1.0))
    align_types = get_v5_alignment_types(MAX_OVERLAP, MAX_ALIGN_SUM)

    dp_cost: List[np.ndarray] = []
    dp_ptr: List[np.ndarray] = []
    for i in range(n_src + 1):
        j_lo, j_hi = corridor[i]
        w = j_hi - j_lo + 1
        dp_cost.append(np.full(w, -1e9, dtype=np.float32))
        dp_ptr.append(np.zeros(w, dtype=np.uint8))

    dp_cost[0][0] = 0.0

    # Phạt mạnh hơn đối với hành động bỏ trống vế (0-1 / 1-0) để hạn chế sinh dòng MISSING giả tạo
    skip_penalty = -0.18
    ideal_low = block_cfg["ideal_low"]
    ideal_high = block_cfg["ideal_high"]
    is_poetry_block = block_cfg["genre"] == "poetry_mixed"

    # Tiền tính toán độ dài CJK, số từ Việt và cờ phiên âm cho tốc độ DP
    zh_cjk_single = [count_cjk_chars(x["han_co_goc"]) for x in han_records]
    vi_words_single = [len(x["text_vi"].split()) for x in viet_records]
    vi_translit_flag = [detect_transliteration_leak(x["text_vi"]) for x in viet_records]

    zh_cjk_prefix = [0]
    for v in zh_cjk_single:
        zh_cjk_prefix.append(zh_cjk_prefix[-1] + v)

    vi_words_prefix = [0]
    for v in vi_words_single:
        vi_words_prefix.append(vi_words_prefix[-1] + v)

    score_cache: Dict[Tuple[int, int, int, int], float] = {}

    def _bead_score(i: int, j: int, a1: int, a2: int) -> float:
        key = (i, j, a1, a2)
        cached = score_cache.get(key)
        if cached is not None:
            return cached

        # 1. Điểm tương đồng ngữ nghĩa LaBSE (có CSLS margin) * phạt độ dài byte chuẩn Bertalign
        sem_margin = compute_margin_similarity(src_vecs, tgt_vecs, i, j, a1, a2)
        sl = float(src_lens[a1 - 1, i - 1])
        tl = float(tgt_lens[a2 - 1, j - 1]) * char_ratio
        len_pen = math.log2(1.0 + min(sl, tl) / max(sl, tl, 1.0))
        base_sem = sem_margin * len_pen

        # 2. Điểm neo từ vựng + số học + từ điển tự học Moore (tra cứu O(1) từ bộ nhớ tiền xử lý)
        anchor_bonus = feats_p2.score_span(i - a1, i, j - a2, j)

        # 3. Điều chuẩn theo tỷ lệ từ Việt / chữ Hán & chống vụn câu
        cjk_cnt = max(zh_cjk_prefix[i] - zh_cjk_prefix[i - a1], 1)
        vi_cnt = vi_words_prefix[j] - vi_words_prefix[j - a2]
        ratio = vi_cnt / cjk_cnt

        ratio_adj = 0.0
        if ratio < ideal_low * 0.65:
            ratio_adj -= (ideal_low * 0.65 - ratio) * 0.22
        elif ratio > ideal_high * 1.45:
            ratio_adj -= min(0.35, (ratio - ideal_high * 1.45) * 0.14)
        elif ideal_low <= ratio <= ideal_high:
            ratio_adj += 0.025

        # Chống tách vụn: nếu 1 câu rất ngắn (<= 5 chữ Hán hoặc <= 5 từ Việt) bị tách 1-1 độc lập
        # hoặc kết thúc bằng dấu phẩy lửng ở tiếng Việt mà không phải hết ý, phạt nhẹ để DP ưu tiên gộp vào câu chính
        frag_adj = 0.0
        if a1 == 1 and a2 == 1 and (cjk_cnt <= 5 or vi_cnt <= 5):
            frag_adj -= 0.045
        vi_last_txt = viet_records[j - 1]["text_vi"].rstrip()
        zh_last_txt = han_records[i - 1]["han_co_goc"].rstrip()
        if vi_last_txt.endswith((",", ";")) and not zh_last_txt.endswith(("。", "！", "？")):
            frag_adj -= 0.025
        elif vi_last_txt.endswith((".", "!", "?")) and zh_last_txt.endswith(("。", "！", "？")):
            frag_adj += 0.020

        # Trong khối thơ văn (Cap_02_V), nếu dòng tiếng Việt duy nhất chỉ là câu phiên âm Hán-Việt rò rỉ,
        # phạt ghép 1-1 với câu Hán kế tiếp để ưu tiên gộp nó chung với câu dịch thơ thật bên cạnh
        if is_poetry_block and a2 == 1 and vi_translit_flag[j - 1]:
            frag_adj -= 0.16

        # Khuyến khích nhẹ các bước tiến cân đối, tránh lạm dụng gộp quá to (ví dụ 1-5, 5-1) khi không có bằng chứng
        size_reg = -0.018 * max(0, (a1 + a2) - 4)

        # Quan trọng: Trong quy hoạch động phân hoạch câu, mỗi bước tiến tiêu thụ (a1 + a2) câu gốc.
        # Nhân chuẩn hóa theo số lượng câu trung bình `0.5 * (a1 + a2)` cho thành phần thưởng tương đồng
        # giúp cặp gộp đúng (ví dụ 1-2 hoặc 2-1 hoàn chỉnh ý) cạnh tranh công bằng với hai cặp 1-1 bị cắt vụn!
        step_weight = 1.0 + 0.14 * ((a1 + a2) - 2)
        total_sc = base_sem * step_weight + 0.22 * anchor_bonus + ratio_adj + frag_adj + size_reg
        score_cache[key] = total_sc
        return total_sc

    for i in range(n_src + 1):
        j_lo, j_hi = corridor[i]
        for j in range(j_lo, j_hi + 1):
            if i == 0 and j == 0:
                continue
            best_sc = -1e9
            best_a = 0

            for a_idx, (a1, a2) in enumerate(align_types):
                pi = i - a1
                pj = j - a2
                if pi < 0 or pj < 0:
                    continue
                p_lo, p_hi = corridor[pi]
                if pj < p_lo or pj > p_hi:
                    continue
                prev_sc = float(dp_cost[pi][pj - p_lo])
                if prev_sc <= -1e8:
                    continue

                if a1 == 0 or a2 == 0:
                    cur_sc = skip_penalty
                else:
                    cur_sc = _bead_score(i, j, a1, a2)

                cand_sc = prev_sc + cur_sc
                if cand_sc > best_sc:
                    best_sc = cand_sc
                    best_a = a_idx

            dp_cost[i][j - j_lo] = best_sc
            dp_ptr[i][j - j_lo] = best_a

    # Truy vết kết quả Pass 2
    alignment: List[Tuple[List[int], List[int]]] = []
    ci, cj = n_src, n_tgt
    while ci > 0 or cj > 0:
        j_lo, _ = corridor[ci]
        a_idx = int(dp_ptr[ci][cj - j_lo])
        a1, a2 = align_types[a_idx]
        src_idxs = list(range(ci - a1, ci))
        tgt_idxs = list(range(cj - a2, cj))
        alignment.append((src_idxs, tgt_idxs))
        ci -= a1
        cj -= a2

    alignment.reverse()
    return alignment


# ==============================================================================
# 7. LÀM MỊN BIÊN CÓ KIỂM SOÁT & CHỐNG VỤN CÂU (SMOOTHING & ANTI-FRAGMENTATION)
# ==============================================================================
def compute_segment_cosine(
    src_idxs: List[int],
    tgt_idxs: List[int],
    src_vecs_1: np.ndarray,
    tgt_vecs_1: np.ndarray,
) -> float:
    """Tính cosine similarity trung bình có trọng số độ dài cho tổ hợp câu bất kỳ."""
    if not src_idxs or not tgt_idxs:
        return -0.5
    sv = np.mean(src_vecs_1[src_idxs], axis=0)
    tv = np.mean(tgt_vecs_1[tgt_idxs], axis=0)
    sn = float(np.linalg.norm(sv))
    tn = float(np.linalg.norm(tv))
    if sn < 1e-8 or tn < 1e-8:
        return 0.0
    return float(np.dot(sv, tv) / (sn * tn))


def hybrid_pair_cost(
    src_idxs: List[int],
    tgt_idxs: List[int],
    han_records: List[Dict],
    viet_records: List[Dict],
    src_vecs_1: np.ndarray,
    tgt_vecs_1: np.ndarray,
    feats_p2: PrecomputedCorpusFeatures,
    block_cfg: Dict,
) -> float:
    """
    Hàm chi phí tổng hợp (càng thấp càng tốt) kết hợp:
    - Độ lệch tỷ lệ độ dài Việt/Hán.
    - Độ khớp ngữ nghĩa cosine thực tế (1 - cos_sim).
    - Điểm neo từ vựng + số học >= 10 + hư từ biên câu.
    - Ràng buộc độ dài tối thiểu chống vụn câu & dấu chấm câu kết thúc trọn ý.
    """
    if not src_idxs or not tgt_idxs:
        return 8.5

    zh_text = " ".join(han_records[i]["han_co_goc"] for i in src_idxs)
    vi_text = " ".join(viet_records[j]["text_vi"] for j in tgt_idxs)

    cjk_len = max(count_cjk_chars(zh_text), 1)
    vi_words = len(vi_text.split())
    ratio = vi_words / cjk_len

    ideal_low = block_cfg["ideal_low"]
    ideal_high = block_cfg["ideal_high"]

    if ratio < ideal_low:
        ratio_cost = (ideal_low - ratio) * 1.45
    elif ratio > ideal_high:
        ratio_cost = (ratio - ideal_high) * 1.05
    else:
        ratio_cost = 0.0

    cos_sim = compute_segment_cosine(src_idxs, tgt_idxs, src_vecs_1, tgt_vecs_1)
    sem_cost = (1.0 - cos_sim) * 1.35

    anchor_sc = feats_p2.score_span(src_idxs[0], src_idxs[-1] + 1, tgt_idxs[0], tgt_idxs[-1] + 1)

    frag_penalty = 0.0
    if cjk_len < block_cfg["min_cjk_frag"] or vi_words < block_cfg["min_vi_frag"]:
        frag_penalty += 0.22
    if vi_text.rstrip().endswith((",", ";", ":")):
        frag_penalty += 0.12

    return ratio_cost + sem_cost - 0.85 * anchor_sc + frag_penalty


def controlled_boundary_smoothing(
    raw_alignment: List[Tuple[List[int], List[int]]],
    han_records: List[Dict],
    viet_records: List[Dict],
    src_vecs_1: np.ndarray,
    tgt_vecs_1: np.ndarray,
    feats_p2: PrecomputedCorpusFeatures,
    block_cfg: Dict,
) -> Tuple[List[Tuple[List[Dict], List[Dict]]], Dict[str, int]]:
    """
    Làm mịn biên 3 bước có kiểm soát:
    - Bước S1 (Orphan Absorption): Ghép cặp khuyết vế đối nghịch (1-0 + 0-1) và hấp thụ mảnh khuyết vế (0-1 / 1-0)
      vào cặp liền kề nếu cải thiện hoặc giữ ổn định chi phí tổng hợp.
    - Bước S2 (Boundary Shift Optimization): Dịch chuyển 1 câu ở biên giữa hai cặp liền kề (k, k+1) hoặc hoán đổi
      mảnh biên bị trượt sang câu kế tiếp (như mệnh đề 'Hộ bộ chiếu số mà sung bổ' bị dính nhầm xuống câu dưới).
    - Bước S3 (Anti-Fragmentation Merge): Gộp các cặp câu quá ngắn / bị cắt lửng giữa dấu phẩy với cặp liền kề
      nếu cùng trang/mạch văn, tổng câu sau gộp không vượt ngưỡng an toàn và chi phí trung bình trên mỗi câu giảm rõ rệt.
    """
    work: List[Tuple[List[int], List[int]]] = [(list(s), list(t)) for s, t in raw_alignment]
    stats = {"orphan_merges": 0, "boundary_shifts": 0, "antifrag_merges": 0}
    max_merged_sents = MAX_ALIGN_SUM + 1

    # --- Bước S1: Xử lý dòng khuyết vế (MISSING 0-1 / 1-0) ---
    s1_work: List[Tuple[List[int], List[int]]] = []
    idx = 0
    while idx < len(work):
        s_cur, t_cur = work[idx]

        # Ghép trực tiếp 1-0 + 0-1 hoặc 0-1 + 1-0 đứng cạnh nhau
        if s_cur and not t_cur and idx + 1 < len(work):
            s_nxt, t_nxt = work[idx + 1]
            if not s_nxt and t_nxt:
                c_pair = hybrid_pair_cost(
                    s_cur, t_nxt, han_records, viet_records, src_vecs_1, tgt_vecs_1, feats_p2, block_cfg
                )
                if c_pair < 2.6:
                    s1_work.append((s_cur, t_nxt))
                    stats["orphan_merges"] += 1
                    idx += 2
                    continue

        if not s_cur and t_cur and idx + 1 < len(work):
            s_nxt, t_nxt = work[idx + 1]
            if s_nxt and not t_nxt:
                c_pair = hybrid_pair_cost(
                    s_nxt, t_cur, han_records, viet_records, src_vecs_1, tgt_vecs_1, feats_p2, block_cfg
                )
                if c_pair < 2.6:
                    s1_work.append((s_nxt, t_cur))
                    stats["orphan_merges"] += 1
                    idx += 2
                    continue

        # Hấp thụ mảnh 0-1 hoặc 1-0 vào cặp liền trước hoặc liền sau tốt hơn
        if (not s_cur and t_cur) or (s_cur and not t_cur):
            best_choice = None
            best_delta = 0.25  # Cho phép tăng nhẹ chi phí để cứu 1 dòng MISSING khỏi MISMATCH chắc chắn

            if s1_work:
                sp, tp = s1_work[-1]
                if sp and tp and len(sp) + len(s_cur) + len(tp) + len(t_cur) <= max_merged_sents:
                    c_old = hybrid_pair_cost(
                        sp, tp, han_records, viet_records, src_vecs_1, tgt_vecs_1, feats_p2, block_cfg
                    )
                    c_new = hybrid_pair_cost(
                        sp + s_cur, tp + t_cur, han_records, viet_records, src_vecs_1, tgt_vecs_1, feats_p2, block_cfg
                    )
                    if c_new - c_old < best_delta:
                        best_delta = c_new - c_old
                        best_choice = ("prev", sp + s_cur, tp + t_cur)

            if idx + 1 < len(work):
                sn, tn = work[idx + 1]
                if sn and tn and len(s_cur) + len(sn) + len(t_cur) + len(tn) <= max_merged_sents:
                    c_old = hybrid_pair_cost(
                        sn, tn, han_records, viet_records, src_vecs_1, tgt_vecs_1, feats_p2, block_cfg
                    )
                    c_new = hybrid_pair_cost(
                        s_cur + sn, t_cur + tn, han_records, viet_records, src_vecs_1, tgt_vecs_1, feats_p2, block_cfg
                    )
                    if c_new - c_old < best_delta:
                        best_delta = c_new - c_old
                        best_choice = ("next", s_cur + sn, t_cur + tn)

            if best_choice is not None:
                if best_choice[0] == "prev":
                    s1_work[-1] = (best_choice[1], best_choice[2])
                else:
                    work[idx + 1] = (best_choice[1], best_choice[2])
                stats["orphan_merges"] += 1
                idx += 1
                continue

        s1_work.append((s_cur, t_cur))
        idx += 1

    # --- Bước S2: Dịch chuyển biên cục bộ giữa (k, k+1) dựa trên Cosine + Anchor + Ratio ---
    for _pass in range(3):
        moved = 0
        for k in range(len(s1_work) - 1):
            s1, t1 = s1_work[k]
            s2, t2 = s1_work[k + 1]
            if not s1 or not t1 or not s2 or not t2:
                continue

            base_cost = hybrid_pair_cost(
                s1, t1, han_records, viet_records, src_vecs_1, tgt_vecs_1, feats_p2, block_cfg
            ) + hybrid_pair_cost(
                s2, t2, han_records, viet_records, src_vecs_1, tgt_vecs_1, feats_p2, block_cfg
            )
            best_cost = base_cost - 0.14
            best_state = None

            cands = []
            if len(t1) >= 2 and len(s2) + len(t2) + 1 <= max_merged_sents:
                cands.append((s1, t1[:-1], s2, [t1[-1]] + t2))
            if len(t2) >= 2 and len(s1) + len(t1) + 1 <= max_merged_sents:
                cands.append((s1, t1 + [t2[0]], s2, t2[1:]))
            if len(s1) >= 2 and len(s2) + len(t2) + 1 <= max_merged_sents:
                cands.append((s1[:-1], t1, [s1[-1]] + s2, t2))
            if len(s2) >= 2 and len(s1) + len(t1) + 1 <= max_merged_sents:
                cands.append((s1 + [s2[0]], t1, s2[1:], t2))

            for ns1, nt1, ns2, nt2 in cands:
                nc = hybrid_pair_cost(
                    ns1, nt1, han_records, viet_records, src_vecs_1, tgt_vecs_1, feats_p2, block_cfg
                ) + hybrid_pair_cost(
                    ns2, nt2, han_records, viet_records, src_vecs_1, tgt_vecs_1, feats_p2, block_cfg
                )
                if nc < best_cost:
                    best_cost = nc
                    best_state = (ns1, nt1, ns2, nt2)

            if best_state is not None:
                s1_work[k] = (best_state[0], best_state[1])
                s1_work[k + 1] = (best_state[2], best_state[3])
                stats["boundary_shifts"] += 1
                moved += 1
        if moved == 0:
            break

    # --- Bước S3: Chống vụn câu & gộp theo biên đồng bộ (Anti-Fragmentation Merge) ---
    # Khi hai cặp liền kề bị cắt lửng (ví dụ câu trước quá ngắn hoặc kết thúc bằng dấu phẩy/chưa hết ý,
    # hoặc cả hai cùng bị lệch câu chéo 1-1 + 1-1 nhưng khi gộp thành 2-2 thì khớp sạch trọn vẹn mệnh đề)
    s3_work: List[Tuple[List[int], List[int]]] = []
    idx = 0
    while idx < len(s1_work):
        s_cur, t_cur = s1_work[idx]
        if idx + 1 < len(s1_work) and s_cur and t_cur:
            s_nxt, t_nxt = s1_work[idx + 1]
            if s_nxt and t_nxt and (len(s_cur) + len(s_nxt) <= MAX_OVERLAP) and (len(t_cur) + len(t_nxt) <= MAX_OVERLAP):
                total_sents = len(s_cur) + len(s_nxt) + len(t_cur) + len(t_nxt)
                if total_sents <= MAX_ALIGN_SUM:
                    zh1 = " ".join(han_records[i]["han_co_goc"] for i in s_cur)
                    vi1 = " ".join(viet_records[j]["text_vi"] for j in t_cur)
                    zh2 = " ".join(han_records[i]["han_co_goc"] for i in s_nxt)
                    vi2 = " ".join(viet_records[j]["text_vi"] for j in t_nxt)

                    cjk1, cjk2 = count_cjk_chars(zh1), count_cjk_chars(zh2)
                    vw1, vw2 = len(vi1.split()), len(vi2.split())

                    same_page_neighborhood = (
                        abs(han_records[s_nxt[0]]["han_page"] - han_records[s_cur[-1]]["han_page"]) <= 1
                        and abs(viet_records[t_nxt[0]]["viet_page_start"] - viet_records[t_cur[-1]]["viet_page_end"]) <= 1
                    )
                    same_loai = viet_records[t_cur[-1]].get("loai") == viet_records[t_nxt[0]].get("loai")

                    is_frag_or_open = (
                        cjk1 < block_cfg["min_cjk_frag"]
                        or cjk2 < block_cfg["min_cjk_frag"]
                        or vw1 < block_cfg["min_vi_frag"]
                        or vw2 < block_cfg["min_vi_frag"]
                        or vi1.rstrip().endswith((",", ";"))
                    )

                    if same_page_neighborhood and same_loai and is_frag_or_open and (cjk1 + cjk2 <= 52):
                        c1 = hybrid_pair_cost(
                            s_cur, t_cur, han_records, viet_records, src_vecs_1, tgt_vecs_1, feats_p2, block_cfg
                        )
                        c2 = hybrid_pair_cost(
                            s_nxt, t_nxt, han_records, viet_records, src_vecs_1, tgt_vecs_1, feats_p2, block_cfg
                        )
                        c_merged = hybrid_pair_cost(
                            s_cur + s_nxt,
                            t_cur + t_nxt,
                            han_records,
                            viet_records,
                            src_vecs_1,
                            tgt_vecs_1,
                            feats_p2,
                            block_cfg,
                        )
                        avg_before = 0.5 * (c1 + c2)
                        # Chỉ gộp khi cặp gộp thực sự khớp ngữ nghĩa/số học tốt hơn hẳn trung bình hai mảnh lẻ
                        if c_merged < avg_before - 0.20 and c_merged < min(c1, c2) + 0.12:
                            s3_work.append((s_cur + s_nxt, t_cur + t_nxt))
                            stats["antifrag_merges"] += 1
                            idx += 2
                            continue

        s3_work.append((s_cur, t_cur))
        idx += 1

    final_pairs: List[Tuple[List[Dict], List[Dict]]] = [
        ([han_records[i] for i in s_idxs], [viet_records[j] for j in t_idxs])
        for s_idxs, t_idxs in s3_work
    ]
    return final_pairs, stats


# ==============================================================================
# 8. ĐÁNH GIÁ NHÃN HEURISTIC & XUẤT DÒNG 12 CỘT CHUẨN (TƯƠNG THÍCH V4)
# ==============================================================================
def evaluate_numeric_consistency(zh_text: str, vi_text: str) -> Tuple[bool, int, str]:
    """Đánh giá tính nhất quán số học theo giá trị số thực tế (>= 10)."""
    zh_vals, vi_vals = extract_number_values(zh_text, vi_text)
    set_zh = set(zh_vals)
    set_vi = set(vi_vals)

    sig_zh = {x for x in set_zh if x >= 10}
    sig_vi = {x for x in set_vi if x >= 10}
    shared_sig = sig_zh & sig_vi
    shared_all = set_zh & set_vi

    if len(shared_sig) >= 1:
        return False, len(shared_sig), ""

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


def build_alignment_row(
    han_items: List[Dict],
    viet_items: List[Dict],
    ratio_min: float,
    ratio_max: float,
    pair_num: int = 1,
) -> Dict:
    n_zh = len(han_items)
    n_vi = len(viet_items)
    align_type = f"{n_zh}-{n_vi}"

    zh_text = " ".join(item["han_co_goc"] for item in han_items).strip()
    vi_text = " ".join(item["text_vi"] for item in viet_items).strip()

    han_page = han_items[0]["han_page"] if n_zh > 0 else 0
    viet_page = viet_items[0]["viet_page_start"] if n_vi > 0 else 0
    pair_id = f"P{pair_num:04d}_C{han_page:03d}_V{viet_page:03d}"

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


def load_jsonl(filepath: Path) -> List[Dict]:
    records = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records


def save_to_excel(rows: List[Dict], out_path: Path) -> None:
    if not out_path.parent.exists():
        out_path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Alignment_Dataset", index=False)


# ==============================================================================
# 9. LUỒNG CHẠY CHÍNH CHO TỪNG KHỐI & TOÀN TẬP
# ==============================================================================
def run_block_alignment(block: Dict, start_pair_num: int = 1) -> Tuple[List[Dict], Dict]:
    name = block["name"]
    print(
        f"\n>>> [{OUTPUT_VERSION} | Two-Pass Anchor + Overlap Smoothing] Đang gióng hàng khối [{name}]...",
        flush=True,
    )

    han_records = load_jsonl(block["han_file"])
    viet_records = load_jsonl(block["viet_file"])
    print(
        f"    Nạp dữ liệu {INPUT_VERSION}: {len(han_records)} câu Hán | {len(viet_records)} câu Việt",
        flush=True,
    )

    src_norm_sents = [normalize_han_for_embedding(x["han_gian_the"]) for x in han_records]
    tgt_sents = [x["text_vi"] for x in viet_records]

    print(f"    Mã hóa LaBSE câu đơn & tổng hợp overlap đa mức (max_overlap={MAX_OVERLAP})...", flush=True)
    src_vecs, src_lens = encode_single_and_build_overlaps(src_norm_sents, MAX_OVERLAP)
    tgt_vecs, tgt_lens = encode_single_and_build_overlaps(tgt_sents, MAX_OVERLAP)

    # Pass 1: Khai thác cặp neo đồng bộ & học từ điển Moore đặc thù từng khối
    feats_p1 = PrecomputedCorpusFeatures(han_records, viet_records, learned_lexicon=None)
    coarse_1to1, high_conf_anchors = run_pass1_anchor_extraction(
        han_records, viet_records, src_vecs, tgt_vecs, feats_p1=feats_p1, top_k=8
    )
    learned_lexicon = induce_moore_bilingual_lexicon(
        han_records, viet_records, high_conf_anchors, min_cooc=3, min_dice=0.42
    )
    feats_p2 = PrecomputedCorpusFeatures(han_records, viet_records, learned_lexicon=learned_lexicon)
    print(
        f"    [Pass 1 - Moore/Hunalign Anchor]: {len(coarse_1to1)} điểm đường dẫn | "
        f"{len(high_conf_anchors)} neo độ tin cậy cao | {len(learned_lexicon)} cặp từ vựng tự học.",
        flush=True,
    )

    # Pass 2: Quy hoạch động chồng lấp đa mức trên hành lang neo
    corridor = build_second_pass_corridor(coarse_1to1, len(han_records), len(viet_records), win_margin=8)
    raw_alignment = run_pass2_overlap_dp(
        han_records=han_records,
        viet_records=viet_records,
        src_vecs=src_vecs,
        tgt_vecs=tgt_vecs,
        src_lens=src_lens,
        tgt_lens=tgt_lens,
        corridor=corridor,
        feats_p2=feats_p2,
        block_cfg=block,
    )

    # Làm mịn biên & chống vụn câu
    smoothed_pairs, smooth_stats = controlled_boundary_smoothing(
        raw_alignment=raw_alignment,
        han_records=han_records,
        viet_records=viet_records,
        src_vecs_1=src_vecs[0],
        tgt_vecs_1=tgt_vecs[0],
        feats_p2=feats_p2,
        block_cfg=block,
    )
    print(
        f"    [Pass 2 + Boundary Smoothing]: hấp thụ khuyết vế={smooth_stats['orphan_merges']}, "
        f"dịch biên={smooth_stats['boundary_shifts']}, chống vụn câu={smooth_stats['antifrag_merges']}.",
        flush=True,
    )

    # Kiểm tra bảo toàn tuyệt đối 100% số câu gốc
    out_han_cnt = sum(len(h) for h, _ in smoothed_pairs)
    out_viet_cnt = sum(len(v) for _, v in smoothed_pairs)
    assert out_han_cnt == len(han_records), f"Lệch số câu Hán: {out_han_cnt} != {len(han_records)}"
    assert out_viet_cnt == len(viet_records), f"Lệch số câu Việt: {out_viet_cnt} != {len(viet_records)}"

    aligned_rows = [
        build_alignment_row(
            h_items,
            v_items,
            ratio_min=block["ratio_min"],
            ratio_max=block["ratio_max"],
            pair_num=start_pair_num + offset,
        )
        for offset, (h_items, v_items) in enumerate(
            tqdm(smoothed_pairs, desc=f"Xuất dòng [{name}]")
        )
    ]
    save_to_excel(aligned_rows, block["out_xlsx"])

    df_blk = pd.DataFrame(aligned_rows)
    n_ok = int((df_blk["Label_Target"] == 1).sum())
    n_flagged = len(df_blk) - n_ok
    blk_summary = {
        "han_input_sents": len(han_records),
        "viet_input_sents": len(viet_records),
        "pass1_high_conf_anchors": len(high_conf_anchors),
        "moore_induced_lexicon_pairs": len(learned_lexicon),
        "smoothing_stats": smooth_stats,
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

    if not OUT_DIR.exists():
        OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_rows = []
    blocks_summary = {}

    for block in BLOCK_CONFIGS:
        block_rows, blk_sum = run_block_alignment(block, start_pair_num=len(all_rows) + 1)
        all_rows.extend(block_rows)
        blocks_summary[block["name"]] = blk_sum

    # Xuất ra đúng file yêu cầu PhuBienTapLuc_Alignment_V5.xlsx
    save_to_excel(all_rows, FINAL_V5_XLSX)

    df_all = pd.DataFrame(all_rows)
    summary = {
        "input_version": INPUT_VERSION,
        "output_version": OUTPUT_VERSION,
        "algorithm": "Two-Pass Moore/Hunalign Lexical-Numeric Anchor + Vecalign Overlap & Controlled Anti-Fragmentation Smoothing",
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
        f"\n>>> HOÀN TẤT [{OUTPUT_VERSION}]! File tổng hợp: output/{OUTPUT_VERSION}/{FINAL_V5_XLSX.name} "
        f"({len(all_rows)} cặp | Đạt chuẩn={summary['overall']['label_1_ok']} | Missing={summary['overall']['missing']})",
        flush=True,
    )


if __name__ == "__main__":
    main()
