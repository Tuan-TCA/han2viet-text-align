# -*- coding: utf-8 -*-
"""
Giai đoạn 03_text_sach (Version 3 - De-noised Phien-Am & Natural Clause Boundaries):
Làm sạch văn bản Hán - Việt và tự động chấm câu / tách câu Hán cổ cho toàn bộ 3 khối:
  1. Cap_01     (Trang Hán 1..53, khử trùng lặp trang 49 / giữ trang 50, lọc đuôi rác trang 53)
  2. Cap_02_V   (Quyển V: Trang Hán 1 -> trước '撫邊雜錄卷之六' ở trang 51, gỡ '撫邊雜錄卷之五')
  3. Cap_02_VI  (Quyển VI: Từ sau '撫邊雜錄卷之六' ở trang 51 -> hết trang 87, bỏ trang 88..92)

Cải tiến cốt lõi ở Version 3:
  1. LOẠI BỎ TRIỆT ĐỂ PHIÊN ÂM HÁN-VIỆT RÒ RỈ TRƯỚC '(Dịch):' Ở QUYỂN V:
     - Quét tất cả các dòng tieu_de '(Dịch):' / '(Địch):'.
     - Các dòng van_xuoi / dich_tho đứng ngay trước '(Dịch):' mà thuộc phần phiên âm bài thơ
       (nhận diện qua mật độ âm tiết Hán-Việt / dấu hiệu OCR phiên âm hoặc sau lời dẫn 'rằng:', 'hoạ:')
       được tách riêng phần lời dẫn xuôi (nếu dính chung dòng) và loại bỏ hoàn toàn phần phiên âm.
  2. KHÔI PHỤC ĐOẠN CHÍNH VĂN CUỐI TRANG BỊ GÁN NHẦM 'chu_thich' (trang 32, 40, 95, 97 của Quyển V)
     & LÀM SẠCH TIÊU ĐỀ BÀI THƠ / RÁC OCR DÍNH ĐẦU CÂU ('k¿', '+4⁄?', '1. Kim dữ...', 'Châu tiitam cò đậu...').
  3. CÂN BẰNG HẠT ĐỘ TỰ NHIÊN (vừa giữ biên câu chuẩn, vừa đảm bảo > 2.000 cặp sạch):
     - MIN_HAN_CJK_CHARS = 5, HAN_COMMA_SPLIT_LEN = 25 (thay vì 15 của v2).
     - MIN_VIET_WORDS = 6, VIET_LONG_SENT_WORDS = 45, VIET_COMMA_CHUNK_WORDS = 22.

Xuất kết quả vào: 03_text_sach/output/v3/ (kèm run_metadata.json).
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
# 1. CẤU HÌNH THAM SỐ CHẠY (VERSION 3)
# ==============================================================================
VERSION = "v3"
PILOT_PAGES: Optional[List[int]] = None
MAX_PREVIEW_SENTS: int = 2

# Tham số hạt độ câu Hán (chặn câu vụn <=4 chữ & không cắt vụn cơ học ở 11-15 chữ)
MIN_HAN_CJK_CHARS: int = 5
HAN_COMMA_SPLIT_LEN: int = 25

# Tham số hạt độ câu Việt (giữ ranh giới câu tự nhiên, chỉ tách câu kê khai thực sự dài)
MIN_VIET_WORDS: int = 6
VIET_LONG_SENT_WORDS: int = 45
VIET_COMMA_CHUNK_WORDS: int = 22

PUNCT_MODEL_NAME = "raynardj/classical-chinese-punctuation-guwen-biaodian"
SENT_END_PUNCTS = {"。", "！", "？"}
CLAUSE_END_PUNCTS = {"；", "："}

# Đường dẫn thư mục dự án
SCRIPT_DIR = Path(__file__).resolve().parent
STAGE_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = STAGE_DIR.parent
OCR_DIR = PROJECT_ROOT / "02_ocr_tho"
OUT_DIR = STAGE_DIR / "output" / VERSION

# Tập từ vựng Hán-Việt đặc trưng trong phiên âm thơ (không/hiếm dùng như hư từ thuần Việt)
SINO_VIET_MARKERS = {
    "nhất", "nhị", "tam", "tứ", "ngũ", "lục", "thất", "bát", "cửu", "thập",
    "bách", "thiên", "vạn", "uạn", "ức", "bất", "hữu", "vô", "uô", "0ô",
    "chi", "nhi", "dĩ", "kỳ", "tự", "thử", "ngô", "ngã", "quân", "nhân",
    "địa", "sơn", "thủy", "thuỷ", "phong", "vân", "uân", "nguyệt", "nhật",
    "dạ", "xuân", "thu", "hàn", "khách", "bhách", "tâm", "sầu", "hận",
    "thán", "thún", "yên", "ba", "lộ", "môn", "đường", "quốc", "vương",
    "uương", "thần", "thánh", "thúnh", "hiền", "tử", "sinh", "lão", "thiếu",
    "niên", "trường", "cổ", "kim", "đông", "tây", "nam", "bắc", "thượng",
    "hạ", "trung", "nội", "ngoại", "giai", "độc", "tương", "hà", "thuỳ",
    "thuy", "khởi", "vị", "uị", "dữ", "ư", "hồ", "tai", "hề", "giả", "dã",
    "hỹ", "hỳ", "nhược", "phi", "vi", "ui", "thị", "tại", "cư", "hành",
    "hàùnh", "hùnh", "lai", "khứ", "bhứ", "quy", "qui", "tri", "trì", "kiến",
    "hiến", "văn", "uăn", "ngôn", "vân", "viết", "hoàn", "phục", "khước",
    "mạn", "tần", "dục", "khẳng", "ưng", "đồng", "tận", "du", "nhàn", "ngoạ",
    "ngoa", "ngoq", "phú", "quí", "quý", "biệt", "thành", "sự", "lý", "lăng",
    "tiêu", "thạch", "giản", "ngọc", "điệp", "bích", "hán", "hún", "châu",
    "lạc", "hoa", "thụ", "điểu", "hạc", "ẩm", "tửu", "bôi", "chước", "toạ",
    "toa", "tịch", "dương", "giang", "hải", "hỏi", "triều", "lãng", "đình",
    "lâu", "đài", "song", "trúc", "tùng", "bách", "mai", "lan", "cúc", "liễu",
    "sương", "tuyết", "vũ", "uũ", "ẩm", "mộng", "tỉnh", "hoài", "ức", "niệm",
    "vọng", "uọng", "khán", "khan", "thính", "mình", "minh", "thanh", "tĩnh",
    "không", "hư", "trần", "thế", "triết", "vĩnh", "uĩnh", "thệ", "lộc",
}

# Các hư từ thuần Việt chỉ xuất hiện trong câu dịch nghĩa / văn xuôi tiếng Việt
PURE_VIET_WORDS = {
    "những", "được", "chẳng", "chưa", "nhưng", "rằng", "của", "trong",
    "ngoài", "người", "cùng", "chiếc", "chốn", "nước", "trời", "biển",
    "núi", "sông", "đất", "lòng", "mắt", "thấy", "biết", "ngồi", "đứng",
    "nằm", "chảy", "bay", "rơi", "mưa", "gió", "nắng", "trăng", "chiều",
    "sớm", "đêm", "ngày", "tháng", "năm", "mười", "trăm", "nghìn", "muôn",
}


# ==============================================================================
# 2. PHÁT HIỆN PHIÊN ÂM RÒ RỈ & LÀM SẠCH TIẾNG VIỆT (V3)
# ==============================================================================
def compute_sino_viet_score(text: str) -> Tuple[float, float]:
    """Trả về (tỷ lệ âm tiết Hán-Việt, tỷ lệ từ thuần Việt) của một chuỗi."""
    words = re.findall(r"[0-9a-zA-ZÀ-ỹ]+", text.lower())
    if not words:
        return 0.0, 0.0
    sv_cnt = sum(1 for w in words if w in SINO_VIET_MARKERS)
    pv_cnt = sum(1 for w in words if w in PURE_VIET_WORDS)
    return sv_cnt / len(words), pv_cnt / len(words)


def is_leaked_phien_am_line(text: str) -> bool:
    """
    Kiểm tra một dòng đứng trước '(Dịch):' có phải câu phiên âm Hán-Việt bị gán nhầm nhãn không.
    """
    t = text.strip()
    if not t:
        return False

    # Chữ ký người sao chép Hán-Việt đứng cuối bài thơ phiên âm
    if re.fullmatch(r"\([^)]{3,45}(?:lục|đề)\)\.?", t, flags=re.IGNORECASE):
        return True

    sv_ratio, pv_ratio = compute_sino_viet_score(t)
    # Đặc trưng lỗi OCR của trang in nghiêng phần phiên âm ('uô', 'uạn', 'uị', 'uân', '0ô', 'bhách')
    has_italic_ocr_artifact = bool(
        re.search(r"\b(?:uô|0ô|uạn|uị|uân|uũ|uọng|uĩnh|bhách|bhứ|bhôi)\b", t.lower())
    )

    if sv_ratio >= 0.42 and pv_ratio <= 0.12:
        return True
    if sv_ratio >= 0.30 and pv_ratio == 0.0:
        return True
    if has_italic_ocr_artifact and pv_ratio <= 0.10 and sv_ratio >= 0.22:
        return True
    return False


def strip_embedded_phien_am_tail(text: str) -> str:
    """
    Xử lý các dòng văn xuôi dẫn nhập bị dính câu phiên âm đầu tiên ở cuối dòng, ví dụ:
      - 'Nguyễn Nghi hoạ: Thạch động thôn vân Lăng tiêu nhất khí...' -> giữ 'Nguyễn Nghi hoạ:'
      - '...và hiến thơ rằng: Lam phong chỉnh chỉnh hướng Nam bhỳ; ...' -> giữ phần văn xuôi dẫn nhập
      - '(Khâu Đình Quỹbái lục). ổ Vị cách trần phân uiễn...' -> bỏ phần phiên âm sau dấu chấm.
    """
    # Trường hợp dòng bắt đầu bằng chú dẫn người chép rồi nối sang bài phiên âm mới
    m_copier = re.match(r"^(\([^)]{3,45}(?:lục|đề)\)\.?)\s+(.+)$", text.strip(), flags=re.IGNORECASE)
    if m_copier and is_leaked_phien_am_line(m_copier.group(2)):
        return ""

    # Trường hợp lời dẫn 'hoạ:' / 'rằng:' / 'đề ...:' nối trực tiếp với câu thơ phiên âm
    m_intro = re.match(
        r"^(.{5,180}?(?:hoạ|rằng|như sau|vân|đề[^:]{0,35})\s*:)\s+(.+)$",
        text.strip(),
        flags=re.IGNORECASE,
    )
    if m_intro:
        intro_part, rest_part = m_intro.group(1).strip(), m_intro.group(2).strip()
        if is_leaked_phien_am_line(rest_part):
            return intro_part
    return text


def clean_poem_heading_and_ocr_noise(text: str, loai: str) -> str:
    """
    Làm sạch ký tự rác OCR đầu câu ('k¿', '+4⁄?', 'ớ5P ó') và gỡ tiền tố tên bài thơ bị in dính
    vào câu đầu của bản dịch thơ (ví dụ: 'Châu tiitam cò đậu Núi lồng sắc biển...' -> 'Núi lồng sắc biển...').
    """
    s = text.strip()

    # 1. Loại bỏ cụm rác OCR đầu câu / giữa câu đã phát hiện ở v2
    s = re.sub(r"^(?:k¿|ớ5P\s*ó|\+4⁄\?|đð1\s*4†nh|\bHBấy\b)\s*", lambda m: "Bấy " if "HBấy" in m.group(0) else "", s)
    s = re.sub(r"\s*\+4⁄\?nh[^.?!]*$", "", s)  # Cắt đuôi tiêu đề bài phiên âm dính cuối câu trang 50
    s = re.sub(r"\s+[A-ZÀ-Ỹ][a-zà-ỹ]+\s+thật\s+ngẫu\s+thành\s+Phù\s+danh.*$", "", s)  # Cắt phiên âm dính cuối trang 63
    s = re.sub(r"^[^\wÀ-ỹ\"“(]+(?=[A-ZÀ-Ỹ])", "", s)

    # 2. Gỡ số thứ tự đầu mục bài thơ kiểu '1. ...' hoặc '10. ...' nếu dính tiêu đề ngắn trước chữ Hoa đầu câu thơ
    if loai == "dich_tho":
        # Mẫu: '[số.] <Tiêu đề ngắn 2-4 từ không dấu phẩy/chấm> <Chữ Hoa mở đầu câu thơ 5/7 chữ>'
        m_title = re.match(
            r"^(?:\d+[.,]?\s*)?([@%?(\wÀ-ỹ][\wÀ-ỹ'’?()]*\s+[\wÀ-ỹ'’?()]+(?:\s+[\wÀ-ỹ'’?()]+){0,2})\s+([A-ZÀ-Ỹ][a-zà-ỹ]+\s+[a-zà-ỹ]+.*)$",
            s,
        )
        if m_title:
            cand_title, rest_poem = m_title.group(1), m_title.group(2)
            # Chỉ cắt nếu phần rest_poem đủ dài (>= 5 từ) và phần đầu giống tiêu đề bị hỏng OCR hoặc tiêu đề ngắn (< 24 ký tự)
            has_ocr_garble = bool(re.search(r"[@%?0-9]|tiitam|tiiạcít|luổn|liứng|đt\b", cand_title.lower()))
            first_clause_words = len(re.split(r"[,.;?!]", rest_poem)[0].split())
            if has_ocr_garble or (len(cand_title) <= 22 and first_clause_words in {4, 5, 6, 7, 8}):
                s = rest_poem

    return s.strip()


def clean_vietnamese_text(text: str, loai: str = "van_xuoi") -> str:
    """Chuẩn hóa NFC, lọc rác OCR, gỡ tiêu đề thơ dính câu và chuẩn hóa số hàng nghìn."""
    if not isinstance(text, str):
        return ""

    s = unicodedata.normalize("NFC", text)
    s = re.sub(r"\s+", " ", s).strip()
    s = clean_poem_heading_and_ocr_noise(s, loai=loai)

    # Sửa lỗi OCR số đếm
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

    # Xóa ký tự chú thích OCR rác nằm sát sau từ (như `bời”`, `Khâm'?`, `xuất tụ”`, `dư đổ`)
    s = re.sub(r"(?<!\w)_+(?=\w)", "", s)
    s = re.sub(r'(?<=\w)(?:\'\?|\?”|”\'|\*"|\'\'|["“”])(?=\s+\w)', "", s)

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
        (r"\bdư đổ\b", "dư đồ"),
        (r"\bđiệt trừ\b", "diệt trừ"),
        (r"\bbình cách\b", "binh cách"),
    ]
    for pattern, repl in word_fixes:
        s = re.sub(pattern, repl, s)

    # Xóa dấu chấm '.' phân cách hàng nghìn
    for _ in range(2):
        s = re.sub(r"(?<=\d)\.(?=\d{3}\b)", "", s)

    # Bỏ các dòng rác chỉ còn số trang hỏng (vd '31ã')
    if re.fullmatch(r"[\d\W_a-z]{1,4}", s):
        return ""

    return re.sub(r"\s+", " ", s).strip()


def recover_and_filter_cap02_v_dataframe(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict]:
    """
    Xử lý chuyên biệt cho VIET_0001-0105.xlsx (Cap_02_V):
      1. Khôi phục 3 đoạn văn xuôi chính văn ở cuối trang 32, 95, 97 bị gán nhầm thành 'chu_thich'
         (khiến bản Hán ở trang 16, 43, 45 bị dư câu gây trượt trang dây chuyền).
      2. Quét ngược từ mọi dòng tiêu đề '(Dịch):' / '(Địch):' để loại bỏ toàn bộ các câu phiên âm
         Hán-Việt bị rò rỉ dưới nhãn 'van_xuoi' hoặc 'dich_tho'.
    """
    df = df.copy()
    recovered_prose_lines = 0
    dropped_phien_am_rows = 0
    trimmed_intro_rows = 0

    # --- Bước A: Khôi phục các dòng chính văn cuối trang bị gán nhầm 'chu_thich' ---
    # Các đoạn văn xuôi bị cắt ngang ở cuối trang 32 (idx 435..445), trang 95 (idx 1209..1214), trang 97 (idx 1257..1260)
    page_prose_recover_ranges = [
        (32, 435, 445),
        (95, 1209, 1214),
        (97, 1257, 1260),
    ]
    for pg, idx_start, idx_end in page_prose_recover_ranges:
        sub = df.loc[idx_start:idx_end]
        if not sub.empty and (sub["viet_page_start"] == pg).all():
            joined_prose = " ".join(str(x).strip() for x in sub["text_vi"] if str(x).strip())
            # Tách câu theo dấu chấm hết câu chuẩn
            sents = [s.strip() for s in re.split(r"(?<=[.?!])\s+", joined_prose) if s.strip()]
            # Ghi lại vào các dòng đầu của dải và tắt các dòng thừa
            df.loc[idx_start:idx_end, "dung_de_ghep"] = False
            for offset, sent_txt in enumerate(sents):
                target_idx = idx_start + offset
                if target_idx <= idx_end:
                    df.loc[target_idx, "loai"] = "van_xuoi"
                    df.loc[target_idx, "dung_de_ghep"] = True
                    df.loc[target_idx, "text_vi"] = sent_txt
                    recovered_prose_lines += 1

    # --- Bước B: Quét ngược trước mọi dòng '(Dịch):' / '(Địch):' để lọc phiên âm rò rỉ ---
    dich_header_idxs = df.index[
        (df["loai"] == "tieu_de")
        & (df["text_vi"].astype(str).str.contains(r"dịch|địch|dich", case=False, na=False))
    ].tolist()

    for d_idx in dich_header_idxs:
        # Quét ngược tối đa 25 dòng trước '(Dịch):'
        cursor = d_idx - 1
        steps = 0
        while cursor >= 0 and steps < 25:
            row_loai = str(df.loc[cursor, "loai"])
            row_txt = str(df.loc[cursor, "text_vi"]).strip()

            # Bỏ qua chú thích cuối trang xen giữa bài phiên âm vắt trang và tiêu đề '(Dịch):'
            if row_loai == "chu_thich":
                cursor -= 1
                steps += 1
                continue

            # Nếu gặp sẵn dòng đã gắn nhãn phien_am hoặc số thứ tự bài thơ (1, 2, 3) thì tiếp tục quét qua
            if row_loai == "phien_am" or (
                row_loai == "tieu_de" and re.fullmatch(r"\d+|[.*]+", row_txt)
            ):
                cursor -= 1
                steps += 1
                continue

            # Nếu gặp tiêu đề '(Dịch):' của bài trước thì dừng ngay
            if row_loai == "tieu_de":
                break

            # Kiểm tra dòng van_xuoi / dich_tho hiện tại:
            trimmed = strip_embedded_phien_am_tail(row_txt)
            if trimmed != row_txt:
                if trimmed:
                    df.loc[cursor, "text_vi"] = trimmed
                    trimmed_intro_rows += 1
                else:
                    df.loc[cursor, "dung_de_ghep"] = False
                    dropped_phien_am_rows += 1
                # Đã chạm tới lời dẫn mở đầu bài thơ -> dừng quét ngược
                break

            if is_leaked_phien_am_line(row_txt):
                df.loc[cursor, "dung_de_ghep"] = False
                dropped_phien_am_rows += 1
                cursor -= 1
                steps += 1
                continue

            # Nếu dòng ngắn dạng 'Lý Nhân Trường hoạ:' đứng độc lập ngay đầu khối phiên âm -> giữ làm lời dẫn rồi dừng
            if re.search(r"(?:hoạ|rằng|như sau)\s*:\s*$", row_txt, flags=re.IGNORECASE):
                break

            # Gặp câu dịch thơ của bài trước hoặc câu văn xuôi thật -> dừng quét
            break

    # --- Bước C: Quét bổ sung các câu phiên âm lẻ còn sót (không có tiêu đề '(Dịch):' ngay sau do lỗi OCR) ---
    for idx, row in df.iterrows():
        if not row["dung_de_ghep"] or row["loai"] in ("chu_thich", "tieu_de", "phien_am"):
            continue
        txt = str(row["text_vi"]).strip()
        trimmed = strip_embedded_phien_am_tail(txt)
        if trimmed != txt:
            if trimmed:
                df.loc[idx, "text_vi"] = trimmed
                trimmed_intro_rows += 1
            else:
                df.loc[idx, "dung_de_ghep"] = False
                dropped_phien_am_rows += 1
            continue
        sv_r, pv_r = compute_sino_viet_score(txt)
        if sv_r >= 0.50 and pv_r == 0.0:
            df.loc[idx, "dung_de_ghep"] = False
            dropped_phien_am_rows += 1

    filter_report = {
        "recovered_prose_sents": recovered_prose_lines,
        "dropped_leaked_phien_am_rows": dropped_phien_am_rows,
        "trimmed_intro_with_phien_am_rows": trimmed_intro_rows,
    }
    return df, filter_report


def merge_short_viet_segments(
    segments: List[str], min_words: int = MIN_VIET_WORDS
) -> List[str]:
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
    Tách câu tiếng Việt giữ ranh giới tự nhiên (Version 3):
      - Ưu tiên tách tại ';' hoặc ':' (khi mỗi vế >= 6 từ).
      - Chỉ tách tại dấu phẩy ',' khi mệnh đề thực sự dài (> 45 từ), theo cụm >= 22 từ.
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
            if sub_clauses and buf_words < MIN_VIET_WORDS + 3:
                sub_clauses[-1] = f"{sub_clauses[-1]} {leftover}"
            else:
                sub_clauses.append(leftover)

        final_clauses.extend(
            merge_short_viet_segments(sub_clauses, min_words=MIN_VIET_WORDS)
        )

    return final_clauses if final_clauses else [text]


def load_and_clean_viet(block_name: str, xlsx_path: Path) -> Tuple[List[Dict], Dict]:
    df = pd.read_excel(xlsx_path, sheet_name="CAU_VIET")
    filter_info = {}

    if block_name == "Cap_02_V":
        df, filter_info = recover_and_filter_cap02_v_dataframe(df)

    mask = (df["dung_de_ghep"] == True) & (  # noqa: E712
        ~df["loai"].isin(["chu_thich", "tieu_de", "phien_am"])
    )
    df_filtered = df[mask].copy()

    records: List[Dict] = []
    for row in df_filtered.itertuples(index=False):
        row_loai = str(row.loai)
        cleaned_vi = clean_vietnamese_text(str(row.text_vi), loai=row_loai)
        if not cleaned_vi:
            continue

        clauses = split_vietnamese_clauses(cleaned_vi)
        for cl in clauses:
            records.append(
                {
                    "sent_idx": len(records) + 1,
                    "viet_page_start": int(row.viet_page_start),
                    "viet_page_end": int(row.viet_page_end),
                    "loai": row_loai,
                    "text_vi": cl,
                }
            )
    return records, filter_info


# ==============================================================================
# 3. CÁC HÀM LÀM SẠCH & TÁCH CÂU TIẾNG HÁN CỔ (V3: HAN_COMMA_SPLIT_LEN = 25)
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
                "han_page_end": buf_pages[-1],
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
            prev["han_page_end"] = buf_pages[-1]
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
            "total_cjk_chars": sum(cjk_lens),
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

        viet_sentences, v_filter_info = load_and_clean_viet(bname, blk["viet_xlsx"])
        save_jsonl(viet_sentences, blk["viet_out"])

        if v_filter_info:
            print(f"    [Lọc Phiên âm & Khôi phục chính văn {bname}]: {v_filter_info}")

        h_stat = print_head_tail_summary(
            f"{bname} HÁN", blk["han_out"], han_sentences, is_han=True, n_sample=MAX_PREVIEW_SENTS
        )
        v_stat = print_head_tail_summary(
            f"{bname} VIỆT", blk["viet_out"], viet_sentences, is_han=False, n_sample=MAX_PREVIEW_SENTS
        )
        meta_stats[bname] = {"han": h_stat, "viet": v_stat, "filter_info": v_filter_info}

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
    print(
        f"\n>>> Hoàn tất [{VERSION}]! Đã lưu metadata tại: {(OUT_DIR / 'run_metadata.json').relative_to(PROJECT_ROOT)}"
    )


if __name__ == "__main__":
    main()
