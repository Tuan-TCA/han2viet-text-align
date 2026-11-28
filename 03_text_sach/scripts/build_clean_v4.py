# -*- coding: utf-8 -*-
"""
Giai đoạn 03_text_sach (Version 4 - Structural Phiên-Âm Purge + Vietnamese Orthography & OCR Spell-Restorer):
Giải quyết triệt để toàn bộ lỗi văn bản tiếng Việt từ OCR PDF cũ trước khi đưa vào gióng hàng:
  1. LOẠI BỎ TRIỆT ĐỂ 100% KHỐI PHIÊN ÂM HÁN-VIỆT Ở `Cap_02_V` THEO CẤU TRÚC SÁCH IN:
     - Thay vì dừng vòng lặp `while` ngay khi gặp 1 câu phiên âm thiếu từ khóa (khiến lọt nguyên cả bài thơ phiên âm như ở trang 65-66),
       quét toàn bộ vùng giữa bài trước và tiêu đề `(Dịch):` / `(Địch):`, dùng cửa sổ liên kết (`contiguous block lookahead`)
       để cắt sạch 100% các câu thơ phiên âm (kể cả câu phiên âm bị dán dính vào đít câu dịch của bài trước như `...Thượng Chân? %†nh Tống Cao Tông Văn hà...`),
       đồng thời giữ nguyên vẹn lời dẫn văn xuôi (như `Đan Bỉnh Ngự hoạ:`, `Nguyễn Đăng Thịnh... nay chép vài bài:`).
  2. GỠ BỎ REGEX CẮT NHẦM ĐẦU CÂU THƠ DỊCH:
     - Chỉ cắt tiền tố khi nó chứa ký tự nhiễu OCR font tiêu đề nghiêng (`%`, `†`, `®`, `⁄`, `_`, `tiitam`, `tiiạcít`, `frứng`...),
       TUYỆT ĐỐI KHÔNG cắt chữ đầu bình thường của câu thơ (`Ví không được...`, `Tứ vô diệu chỉ...`, `Ưa nhàn ở đậu...`).
  3. KHÔI PHỤC HÌNH THÁI CHÍNH TẢ TIẾNG VIỆT & XÓA CHỈ MỤC CHÚ THÍCH RÁC:
     - Quy tắc âm vị học tiếng Việt: phụ âm đầu `u + vần tiếng Việt` (`uiệc->việc`, `uui->vui`, `uề->về`, `uới->với`, `uắng->vắng`, `uậy->vậy`, `uẫn->vẫn`, `uô->vô`, `uạn->vạn`, `uàng->vàng`, `uăn->văn`, `uũ->vũ`, `uị->vị`, `uấn->vấn`, `uững->vững`, `uừa->vừa`, `uận->vận`, `uương->vương`, `uĩnh->vĩnh`...).
     - Quy tắc số đếm & ký tự chú thích chân trang dính sát từ (`ã/õ/ð + đơn vị -> 5`, `4Ô -> 40`, `S0 -> 80`, `ai2 -> ai?`, `phượng'? -> phượng`, `mũ ~Iị! ” -> mũ`, `lân" -> lân`).
  4. SỬA CHÍNH TẢ OCR TIẾNG VIỆT CÓ RÀNG BUỘC BẢO TOÀN 100% CẤU TRÚC CÂU (Constrained OCR Typo Restoration):
     - Quét các dòng tiếng Việt còn chứa từ sai chính tả OCR (như `Qung hết -> Quăng hết`, `Nội mưi -> Nội mai`, `Hoa nút -> Hoa núi`, `Nứữa đời -> Nửa đời`, `hiêng sợ -> kiêng sợ`, `khổ nhốt -> khổ nhất`, `được phối -> được phải`, `Rhuông -> Khuông`, `thuyý -> thuý`, `núo nhiệt -> náo nhiệt`, `chủy xuôi -> chảy xuôi`...).
     - Dùng mô hình sửa lỗi OCR tiếng Việt theo lô (`temperature=0.0`) với ràng buộc nghiêm ngặt: CHỈ sửa lỗi nhận dạng mặt chữ/dấu thanh tiếng Việt và xóa ký tự rác chú thích còn sót, TUYỆT ĐỐI KHÔNG dịch lại, không thêm/bớt mệnh đề, không gộp/tách câu! Kiểm tra độ lệch độ dài từ trước khi chấp nhận.

Xuất ra: `03_text_sach/output/v4/` VÀ cập nhật trực tiếp `03_text_sach/han.txt`, `03_text_sach/viet.txt`.
"""

import json
import os
import re
import shutil
import sys
import time
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from tqdm import tqdm

SCRIPT_DIR = Path(__file__).resolve().parent
STAGE_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = STAGE_DIR.parent
OCR_DIR = PROJECT_ROOT / "02_ocr_tho"
V3_OUT_DIR = STAGE_DIR / "output" / "v3"
V4_OUT_DIR = STAGE_DIR / "output" / "v4"
SPELL_CACHE_JSONL = V4_OUT_DIR / "viet_ocr_spell_cache.jsonl"

sys.path.insert(0, str(SCRIPT_DIR))
from build_clean_v3 import (  # noqa: E402
    MIN_VIET_WORDS,
    PURE_VIET_WORDS,
    SINO_VIET_MARKERS,
    compute_sino_viet_score,
    split_vietnamese_clauses,
)

# Mở rộng danh sách âm tiết Hán-Việt thường gặp trong thơ chữ Hán để nhận diện khối phiên âm 100% chính xác
EXTRA_SV_WORDS = {
    "thiên", "địa", "nhân", "tâm", "tính", "mệnh", "mạnh", "thời", "thần", "thánh", "hiền", "quân",
    "thần", "phụ", "tử", "ynh", "đệ", "bằng", "hữu", "gia", "quốc", "thiên", "hạ", "sơn", "hà",
    "giang", "hải", "phong", "vân", "vũ", "lộ", "sương", "tuyết", "nhật", "nguyệt", "tinh", "thần",
    "xuân", "hạ", "thu", "đông", "hoa", "thảo", "mộc", "thụ", "lâm", "trúc", "tùng", "mai", "lan",
    "cúc", "hạc", "long", "phượng", "lân", "quy", "ngư", "điểu", "nhạn", "âu", "lộ", "thi", "thư",
    "lễ", "nhạc", "cầm", "kỳ", "tửu", "trà", "ẩm", "tuý", "túy", "mộng", "tỉnh", "nhàn", "ẩn",
    "hành", "tàng", "dụng", "xả", "xuất", "xử", "đắc", "thất", "vinh", "nhục", "bần", "phú", "quý",
    "tiện", "cổ", "kim", "lai", "vãng", "khứ", "hoàn", "quy", "đăng", "lâm", "du", "ngoạn", "khán",
    "vọng", "thính", "vấn", "đáp", "ngôn", "viết", "vân", "ca", "vịnh", "ngâm", "tiếu", "khấp",
    "thán", "bi", "hoan", "hỷ", "nộ", "ái", "ố", "dục", "ưu", "sầu", "hận", "khổ", "lạc", "an",
    "nguy", "trị", "loạn", "hưng", "vong", "thịnh", "suy", "thành", "bại", "thị", "phi", "chân",
    "giả", "thiện", "ác", "chính", "tà", "công", "tư", "minh", "ám", "thanh", "trọc", "cao", "đê",
    "viễn", "cận", "thâm", "thiển", "đại", "tiểu", "đa", "thiểu", "trường", "đoản", "phương", "viên",
    "hồng", "lục", "thanh", "bạch", "hoàng", "hắc", "đan", "bích", "thuý", "thúy", "tử", "kim",
    "ngọc", "châu", "bảo", "kiếm", "đao", "cung", "tiễn", "xa", "mã", "chu", "thuyền", "lâu", "đài",
    "đình", "các", "cung", "điện", "miếu", "đường", "tự", "am", "thôn", "ổ", "khê", "giản", "động",
    "thạch", "nham", "bích", "ngạn", "châu", "đảo", "phố", "thành", "quách", "biên", "phương",
    "nhất", "nhị", "tam", "tứ", "ngũ", "lục", "thất", "bát", "cửu", "thập", "bách", "thiên", "vạn",
    "ức", "vô", "hữu", "bất", "vị", "phi", "nhược", "tuy", "nhiên", "nhi", "dĩ", "chi", "kỳ", "giả",
    "dã", "hĩ", "hồ", "tai", "nhĩ", "ư", "vu", "tự", "tòng", "đáo", "tại", "vi", "tác", "thử", "bỉ",
    "hà", "thuỳ", "thùy", "ngô", "ngã", "nhĩ", "quân", "dư", "cùng", "tận", "độc", "cô", "quả",
    "nho", "sĩ", "nông", "công", "thương", "khách", "tăng", "đạo", "tiên", "phật", "quỷ", "ma",
}
ALL_SV_MARKERS = SINO_VIET_MARKERS | EXTRA_SV_WORDS

# Các từ thuần Việt CHỈ có trong câu dịch (loại các từ đồng âm Hán-Việt như 'không', 'cùng', 'người', 'năm', 'mười')
STRICT_NATIVE_VIET = {
    "những", "được", "chẳng", "chưa", "nhưng", "rằng", "của", "chiếc", "chốn", "nước", "trời",
    "biển", "núi", "sông", "đất", "mắt", "thấy", "biết", "ngồi", "đứng", "nằm", "chảy", "bay",
    "rơi", "mưa", "gió", "nắng", "trăng", "chiều", "sớm", "đêm", "ngày", "tháng", "mấy", "ấy",
    "này", "đó", "kia", "đây", "đâu", "sao", "nào", "vậy", "thôi", "lắm", "rất", "hơn", "kém",
    "vào", "ra", "lên", "xuống", "về", "với", "cho", "lấy", "bởi", "vì", "nên", "mà", "thì",
}


# ==============================================================================
# 1. KHÔI PHỤC HÌNH THÁI CHÍNH TẢ TIẾNG VIỆT (ORTHOGRAPHIC RULES)
# ==============================================================================
# Bảng vần tiếng Việt hợp lệ sau phụ âm 'v' khi bị in nghiêng nhận nhầm thành 'u'
ITALIC_U_TO_V_RHYMES = (
    r"iệc|iệt|iện|iệm|ięc|"
    r"ui|ụi|ùi|ủi|ũi|"
    r"ề|ế|ệ|ể|ễ|ê|"
    r"ới|ời|ởi|ỡi|ợi|ơi|"
    r"ắng|ẳng|ặng|ằng|ẵm|ăm|ắp|ặp|ăn|ặn|ằn|ẳn|ẵn|"
    r"ậy|ấy|ầy|ẩy|ẫy|ây|ays|"
    r"ẫn|ần|ẩn|ận|ân|ấng|ầng|ẩng|ẫng|âng|ất|ật|ứt|"
    r"ô|ố|ồ|ổ|ỗ|ộ|ốc|ộc|ốn|ộn|ống|ộng|ốt|ột|"
    r"ạn|ản|ãn|àn|án|an|ang|àng|ảng|ãng|ạng|áng|anh|ành|ảnh|ãnh|ạnh|ánh|ách|ạch|"
    r"ăn|ắn|ằn|ẳn|ẵn|ặn|"
    r"ững|ừng|ửng|ững|ưng|ức|ực|ừa|ửa|ữa|ựa|ưa|ước|ược|ươi|ười|ưởi|ưỡi|ượi|ươn|ườn|ưởng|ưỡng|ượng|ướng|ướt|ượt|ưu|ựu|"
    r"ị|ì|ỉ|ĩ|í|i|ia|ỉa|ịa|ía|ìa|ích|ịch|iên|iền|iển|iễn|iện|iến|iêng|iềng|iếng|iết|iệt|iêu|iều|iểu|iễu|iệu|iếu|in|ìn|ỉn|ịn|ính|ình|ỉnh|ĩnh|ịnh|íp|ịp|ít|ịt|"
    r"a|à|ả|ã|á|ạ|ai|ài|ải|ãi|ái|ại|am|àm|ảm|ãm|ám|ạm|ao|ào|ảo|ão|áo|ạo|ap|áp|ạp|at|át|ạt|au|àu|ảu|áu|ạu|ay|ày|ảy|ãy|áy|ạy|"
    r"e|è|ẻ|ẽ|é|ẹ|em|èm|ẻm|ẽm|ém|ẹm|en|èn|ẻn|ẽn|én|ẹn|eng|èng|ẻng|éng|ẹng|eo|èo|ẻo|ẽo|éo|ẹo|ép|ẹp|ét|ẹt|"
    r"o|ò|ỏ|õ|ó|ọ|oa|oà|oả|oã|oá|oạ|oai|oài|oải|oãi|oái|oại|oan|oàn|oản|oãn|oán|oạn|oang|oàng|oảng|oãng|oáng|oạng|oanh|oành|oảnh|oánh|oạnh|oắt|oặt|óc|ọc|oi|òi|ỏi|õi|ói|ọi|om|òm|ỏm|õm|óm|ọm|on|òn|ỏn|õn|ón|ọn|ong|òng|ỏng|õng|óng|ọng|óp|ọp|ót|ọt|"
    r"ơ|ờ|ở|ỡ|ớ|ợ|ơm|ờm|ởm|ỡm|ớm|ợm|ơn|ờn|ởn|ỡn|ớn|ợn|ơp|ợp|ớt|ợt"
)

# Những từ thực sự bắt đầu bằng 'u' hợp lệ trong tiếng Việt (không được đổi sang 'v')
VALID_U_INITIAL_WORDS = {
    "u", "ù", "ủ", "ũ", "ú", "ụ",
    "ua", "ùa", "ủa", "ũa", "úa", "ụa",
    "uẩn", "uất", "uể", "uế", "uệ",
    "um", "ùm", "ủm", "úm",
    "un", "ùn", "ủn", "ún",
    "ung", "ùng", "ủng", "ũng", "úng", "ụng",
    "uốn", "uồn", "uổn", "uỗn", "uộn",
    "uống", "uổng", "uỗng",
    "uôm", "uøm", "uơi", "uớt", "uột",
    "úp", "ụp", "út", "ụt",
    "uy", "uỷ", "ủy", "uỹ", "uý", "uỵ", "uyệt", "uyên", "uyển", "uyễn", "uyện", "uyết",
    "uỳnh", "uỵch", "uýnh",
    "ư", "ừ", "ử", "ữ", "ứ", "ự",
    "ưa", "ừa", "ửa", "ữa", "ứa", "ựa",
    "ức", "ực", "ưng", "ừng", "ửng", "ững", "ứng", "ựng",
    "ước", "ược", "ươi", "ười", "ưởi", "ưỡi", "ượi", "ươm", "ườm", "ươn", "ườn", "ưỡn",
    "ương", "ường", "ưởng", "ưỡng", "ướng", "ượng", "ướp", "ượp", "ướt", "ượt", "ưu", "ừu", "ửu", "ữu", "ứu", "ựu",
}

U_WORD_RE = re.compile(rf"\b([uU])({ITALIC_U_TO_V_RHYMES})\b")


def fix_italic_u_to_v(text: str) -> str:
    def _sub(m: re.Match) -> str:
        full = m.group(0)
        if full.lower() in VALID_U_INITIAL_WORDS:
            return full
        prefix = "V" if m.group(1) == "U" else "v"
        return prefix + m.group(2)

    return U_WORD_RE.sub(_sub, text)


def deterministic_viet_clean(text: str, loai: str = "van_xuoi") -> str:
    """Làm sạch quy tắc tất định: gỡ rác chú thích, sửa chữ in nghiêng v->u, sửa số OCR."""
    if not isinstance(text, str):
        return ""
    s = unicodedata.normalize("NFC", text)
    s = re.sub(r"\s+", " ", s).strip()

    # 1. Cắt phần bài thơ phiên âm kế tiếp bị dán dính vào cuối câu dịch (vd: `...Thượng Chân? %†nh Tống Cao Tông...`)
    s = re.sub(r"(?<=[.?!])\s*(?:[%†®©⁄+]+|\bđð1\b|\b4⁄2\w*)[^.?!]*$", "", s)
    s = re.sub(r"\s*\+4⁄\?nh[^.?!]*$", "", s)
    s = re.sub(r"\s+[A-ZÀ-Ỹ][a-zà-ỹ]+\s+thật\s+ngẫu\s+thành\s+Phù\s+danh.*$", "", s)

    # 2. CHỈ cắt tiền tố đầu dòng thơ nếu tiền tố đó CHỨA KÝ TỰ RÁC OCR TIÊU ĐỀ NGHIÊNG (tuyệt đối không cắt câu sạch!)
    if loai == "dich_tho":
        s = re.sub(r"^(?:k¿|ớ5P\s*ó|\+4⁄\?|đð1\s*4†nh|1⁄;mh\s+gió\s+thiếu\s+nữ\s*\([^)]*\)|%qày\s+xuân\s+ngẫu\s+frứng|®ình\s+sơn\s+chồng\s+Biếc|Tiiạcít\s+động\s+tuây\s+luổn|Km\s+đữ\s+chắn\s+sóng)\s*", "", s)
        # Tổng quát: tiền tố ngắn có chứa %, †, ®, ⁄, _, số lạc giữa chữ trước chữ Hoa đầu câu thơ
        m_garble_head = re.match(r"^([^,.;?!]{2,28}[%†®©⁄_0-9][^,.;?!]{0,18}?)\s+([A-ZÀ-Ỹ][a-zà-ỹ]+\s+[a-zà-ỹ]+.*)$", s)
        if m_garble_head:
            s = m_garble_head.group(2)

    # 3. Xóa các cụm chỉ mục chú thích chân trang bị hỏng OCR nằm cạnh từ:
    #    Ví dụ: `~Iị! ”`, `'?”`, `”?`, `'?`, `"?`, `”'`, `!"`, `1"`, `2"`, `ai2` (cuối câu nghi vấn)
    s = re.sub(r"\s*~Iị!\s*[”\"]?", "", s)
    s = re.sub(r"(?<=[a-zA-ZÀ-ỹ])\d+(?=[”\"']?(?:[,.;:?!)]|\s|$))", lambda m: "?" if m.group(0) == "2" and s.endswith(m.group(0)) else "", s)
    s = re.sub(r"(?<=\w)(?:'\?+\"?|\"\?+'?|”\?+|'\”|”'|!+\”|\*+|”\"|''|\”(?=\s+[a-zà-ỹ,;]))", "", s)
    s = re.sub(r'(?<=\w)["”](?=[,.;:?!]|\s+[a-zà-ỹ])', "", s)
    s = re.sub(r"^[^\wÀ-ỹ\"“(]+(?=[A-ZÀ-Ỹ0-9])", "", s)

    # 4. Sửa lỗi chữ in nghiêng `u` -> `v` (`uiệc->việc`, `uui->vui`, `uề uới->về với`, `uô->vô`, ...)
    s = fix_italic_u_to_v(s)
    s = re.sub(r"\buu\s+nho\b", "vu nho", s, flags=re.IGNORECASE)

    # 5. Sửa lỗi OCR số đếm trong bảng kê thuế/quân bị nhận nhầm chữ cái / dấu ngã
    s = re.sub(r"(?<=\d)[õðöã](?=\b|\D)", "5", s)
    s = re.sub(r"(?<=\d)[ÔO](?=\b|\s)", "0", s)
    s = re.sub(r"\bS(?=\d+\b)", "8", s)
    s = re.sub(r"\bG1\b(?=\s+đội)", "61", s)
    s = re.sub(
        r"\b[ðöõã](?=\s+(?:tiền|tiển|quan|lạng|đồng|phân|tấc|thước|sào|mẫu|bát|thưng|cáp|hốt|người|năm|thuyền|tên|phu)\b)",
        "5",
        s,
    )
    s = re.sub(
        r"\b[Il](?=\s+(?:quan|tiền|tiển|lạng|đồng|mẫu|sào|thước|tấc|bát|hốt)\b)",
        "1",
        s,
    )
    s = re.sub(r"\b1\s+tiền\s+lỗ\s+đồng\b", "1 tiền 15 đồng", s)

    # 6. Sửa các từ lỗi OCR phổ biến lặp lại nhiều lần trong văn bản
    common_fixes = [
        (r"\bxuất tờ\b", "xuất từ"),
        (r"\btiển\b", "tiền"),
        (r"\bTiển\b", "Tiền"),
        (r"\bthuyển\b", "thuyền"),
        (r"\bthuyên\b", "thuyền"),
        (r"\btuộng\b", "ruộng"),
        (r"\bđân\b", "dân"),
        (r"\bsố định\b", "số đinh"),
        (r"\bnhân định\b", "nhân đinh"),
        (r"\bdân đính\b", "dân đinh"),
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
        (r"\bbình lính\b", "binh lính"),
        (r"\bnúo nhiệt\b", "náo nhiệt"),
        (r"\bthuyý\b", "thuý"),
        (r"\bNứữa\b", "Nửa"),
        (r"\bQung hết\b", "Quăng hết"),
        (r"\bLĩa nhàn\b", "Ưa nhàn"),
        (r"\bVụ Tai\b", "Vụ Lai"),
        (r"\bphúi mũ\b", "phủi mũ"),
        (r"\bsao hiêng sợ\b", "sao kiêng sợ"),
        (r"\bkhổ nhốt\b", "khổ nhất"),
        (r"\bHọc được phối còn\b", "Học được phải còn"),
        (r"\bNội mưi\b", "Nội mai"),
        (r"\bHoa nút\b", "Hoa núi"),
        (r"\bba tấc thong\b", "ba tấc lưỡi"),
        (r"\bLô thánh\b", "Lỗ thánh"),
        (r"\bRhuông\b", "Khuông"),
        (r"\bHữu Riên\b", "Hữu kiên"),
        (r"\bcø\b", "cơ"),
        (r"\btất ca\b", "tất cả"),
        (r"\bmôi đội\b", "mỗi đội"),
        (r"\bmôi thuyền\b", "mỗi thuyền"),
        (r"\bmôi người\b", "mỗi người"),
        (r"\b1y long\b", "Ly long"),
        (r"\bxiêng xích\b", "xiềng xích"),
        (r"\bThâm nghĩ\b", "Thầm nghĩ"),
    ]
    for pat, rep in common_fixes:
        s = re.sub(pat, rep, s)

    # Xóa dấu chấm phân cách hàng nghìn để thống nhất số học
    for _ in range(2):
        s = re.sub(r"(?<=\d)\.(?=\d{3}\b)", "", s)

    if re.fullmatch(r"[\d\W_a-z]{1,4}", s):
        return ""
    return re.sub(r"\s+", " ", s).strip()


# ==============================================================================
# 2. BỘ LỌC KHỐI PHIÊN ÂM THEO CẤU TRÚC ĐOẠN TRƯỚC `(Dịch):` (KHÔNG BỎ SÓT!)
# ==============================================================================
def score_line_phien_am_likelihood(text: str) -> Tuple[float, float, bool]:
    """
    Tính (sv_ratio, strict_native_ratio, has_ocr_phien_am_clue) sau khi đã sửa `u->v` để nhận diện chính xác
    cả những câu phiên âm bị hỏng OCR nặng (như `Ái nhèn kết ốG tại Vụ Lai`, `Học đắc hoàn tu đại nhãn khai`).
    """
    norm_txt = fix_italic_u_to_v(text)
    words = re.findall(r"[0-9a-zA-ZÀ-ỹ]+", norm_txt.lower())
    if not words:
        return 0.0, 0.0, False
    sv_cnt = sum(1 for w in words if w in ALL_SV_MARKERS)
    nat_cnt = sum(1 for w in words if w in STRICT_NATIVE_VIET)
    has_garble = bool(re.search(r"\b(?:bh\w*|0\w+|ốg|sùuh|đóáo|nhèn|ttu|ẫñ)\b|[%†⁄]", text.lower()))
    return sv_cnt / len(words), nat_cnt / len(words), has_garble


def split_intro_from_phien_am(text: str) -> Tuple[str, bool]:
    """
    Nếu dòng là câu văn xuôi dẫn nhập nối với câu thơ phiên âm (sau dấu `:` hoặc tiêu đề),
    tách giữ phần văn xuôi dẫn nhập và bỏ phần phiên âm.
    Trả về `(kept_intro_text, did_strip_phien_am)`.
    """
    t = text.strip()
    if re.fullmatch(r"\([^)]{3,50}(?:lục|đề)\)\.?", t, flags=re.IGNORECASE):
        return "", True

    m_copier = re.match(r"^(\([^)]{3,50}(?:lục|đề)\)\.?)\s+(.+)$", t, flags=re.IGNORECASE)
    if m_copier:
        sv_r, nat_r, gar = score_line_phien_am_likelihood(m_copier.group(2))
        if sv_r >= 0.28 or gar or nat_r <= 0.10:
            return "", True

    m_intro = re.match(
        r"^(.{4,200}?(?:hoạ|rằng|như sau|vân|bài|đề[^:]{0,40})\s*:)\s+(.+)$",
        t,
        flags=re.IGNORECASE,
    )
    if m_intro:
        intro_part, rest_part = m_intro.group(1).strip(), m_intro.group(2).strip()
        sv_r, nat_r, gar = score_line_phien_am_likelihood(rest_part)
        if sv_r >= 0.25 or gar or nat_r <= 0.12:
            return intro_part, True

    return t, False


def filter_cap02_v_phien_am_structural(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict]:
    """
    Lọc sạch 100% khối phiên âm Hán-Việt trong `Cap_02_V` bằng quét cấu trúc khối ngược từ `(Dịch):`
    có nhìn trước 2–3 dòng (`lookahead`): không bị dừng nhầm khi 1 câu cuối bài phiên âm có chứa chữ thông dụng!
    """
    df = df.copy()
    recovered_prose = 0
    dropped_pa = 0
    trimmed_intro = 0

    # Bước A: Khôi phục 3 đoạn chính văn cuối trang bị gán nhầm chu_thich (trang 32, 95, 97)
    for pg, idx_start, idx_end in [(32, 435, 445), (95, 1209, 1214), (97, 1257, 1260)]:
        sub = df.loc[idx_start:idx_end]
        if not sub.empty and (sub["viet_page_start"] == pg).all():
            joined_prose = " ".join(str(x).strip() for x in sub["text_vi"] if str(x).strip())
            sents = [s.strip() for s in re.split(r"(?<=[.?!])\s+", joined_prose) if s.strip()]
            df.loc[idx_start:idx_end, "dung_de_ghep"] = False
            for offset, sent_txt in enumerate(sents):
                target_idx = idx_start + offset
                if target_idx <= idx_end:
                    df.loc[target_idx, "loai"] = "van_xuoi"
                    df.loc[target_idx, "dung_de_ghep"] = True
                    df.loc[target_idx, "text_vi"] = sent_txt
                    recovered_prose += 1

    # Bước B: Với mỗi tiêu đề `(Dịch):`, gom toàn bộ các dòng nội dung giữa tiêu đề `(Dịch):` trước đó và tiêu đề `(Dịch):` hiện tại.
    # Phần cuối của khoảng này (ngay sát trên `(Dịch):` hiện tại) CHẮC CHẮN là bài thơ phiên âm của `(Dịch):` hiện tại!
    dich_idxs = df.index[
        (df["loai"] == "tieu_de")
        & (df["text_vi"].astype(str).str.contains(r"dịch|địch|dich", case=False, na=False))
    ].tolist()

    prev_dich_idx = -1
    for d_idx in dich_idxs:
        # Thu thập danh sách chỉ số các dòng ứng viên (bỏ qua chu_thich & phien_am đã tắt sẵn) nằm trên `d_idx`
        cand_rows = []
        cursor = d_idx - 1
        while cursor > prev_dich_idx and cursor >= 0 and len(cand_rows) < 35:
            r_loai = str(df.loc[cursor, "loai"])
            r_txt = str(df.loc[cursor, "text_vi"]).strip()
            if r_loai in ("chu_thich", "so_trang") or not df.loc[cursor, "dung_de_ghep"]:
                cursor -= 1
                continue
            if r_loai == "tieu_de":
                break
            cand_rows.append(cursor)
            cursor -= 1

        # Duyệt ngược từ dòng sát trên `(Dịch):` đi lên:
        # Chừng nào dòng hiện tại HOẶC dòng ngay phía trên nó vẫn mang đặc trưng phiên âm (sv_ratio cao, ít từ thuần Việt),
        # tiếp tục xóa cho tới khi chạm vào lời dẫn `...hoạ:` / `...rằng:` hoặc chạm vào khổ thơ dịch của bài trước!
        idx_pos = 0
        while idx_pos < len(cand_rows):
            r_i = cand_rows[idx_pos]
            txt = str(df.loc[r_i, "text_vi"]).strip()

            # 1) Kiểm tra dòng lời dẫn có đuôi phiên âm (`Đan Bỉnh Ngự hoạ: ...`)
            kept, did_trim = split_intro_from_phien_am(txt)
            if did_trim:
                if kept:
                    df.loc[r_i, "text_vi"] = kept
                    trimmed_intro += 1
                else:
                    df.loc[r_i, "dung_de_ghep"] = False
                    dropped_pa += 1
                break

            # 2) Nếu dòng kết thúc bằng `hoạ:` / `rằng:` / `như sau:` -> đây chính là lời dẫn mở đầu bài thơ, giữ lại và dừng!
            if re.search(r"(?:hoạ|rằng|như sau|bài)\s*:\s*$", txt, flags=re.IGNORECASE):
                break

            # 3) Nếu dòng có chứa câu kết của bài trước + tiêu đề rác của bài phiên âm mới ở cuối (vd `...Thượng Chân? %†nh Tống...`)
            m_glued = re.match(r"^(.+?[.?!])\s+((?:[%†®©⁄+0-9_]+|[A-ZÀ-Ỹ]\w+\s+(?:hoạ|vịnh|ngẫu|tự|thư)).*)$", txt)
            if m_glued:
                left_part, right_part = m_glued.group(1).strip(), m_glued.group(2).strip()
                sv_l, nat_l, _ = score_line_phien_am_likelihood(left_part)
                sv_r, nat_r, gar_r = score_line_phien_am_likelihood(right_part)
                if nat_l >= 0.12 and (sv_r >= 0.30 or gar_r or nat_r == 0):
                    df.loc[r_i, "text_vi"] = left_part
                    trimmed_intro += 1
                    break

            sv_cur, nat_cur, gar_cur = score_line_phien_am_likelihood(txt)
            is_pa_cur = (
                (sv_cur >= 0.30 and nat_cur <= 0.14)
                or (gar_cur and nat_cur <= 0.15)
                or (idx_pos == 0 and nat_cur <= 0.18 and len(txt.split()) <= 18)  # Dòng ngay sát trên `(Dịch):` luôn là câu cuối bài phiên âm!
            )

            # Lookahead 1-2 dòng phía trên: nếu dòng hiện tại hơi mơ hồ (vd `Học đắc hoàn tu đại nhãn khai` có `nat_cur` thấp hoặc vừa)
            # nhưng 1-2 dòng ngay trên nó RÕ RÀNG là phiên âm (`Vị nhân tối khổ thị uô học`, `Bản sùuh tung tích...`), thì dòng hiện tại
            # nằm kẹp giữa khối phiên âm và `(Dịch):` nên BẮT BUỘC cũng là phiên âm!
            if not is_pa_cur and idx_pos + 1 < len(cand_rows):
                upper_checks = []
                for look in (1, 2):
                    if idx_pos + look < len(cand_rows):
                        u_txt = str(df.loc[cand_rows[idx_pos + look], "text_vi"]).strip()
                        usv, unat, ugar = score_line_phien_am_likelihood(u_txt)
                        upper_checks.append((usv >= 0.34 and unat <= 0.10) or (ugar and unat <= 0.10))
                if any(upper_checks) and nat_cur <= 0.22 and len(txt.split()) <= 20:
                    is_pa_cur = True

            if is_pa_cur:
                df.loc[r_i, "dung_de_ghep"] = False
                dropped_pa += 1
                idx_pos += 1
                continue

            break

        prev_dich_idx = d_idx

    # Bước C: Quét vét các dòng phiên âm lẻ còn sót (nếu tiêu đề `(Dịch):` bị rớt mất trong OCR)
    for idx, row in df.iterrows():
        if not row["dung_de_ghep"] or row["loai"] in ("chu_thich", "tieu_de", "phien_am"):
            continue
        txt = str(row["text_vi"]).strip()
        kept, did_trim = split_intro_from_phien_am(txt)
        if did_trim:
            if kept:
                df.loc[idx, "text_vi"] = kept
                trimmed_intro += 1
            else:
                df.loc[idx, "dung_de_ghep"] = False
                dropped_pa += 1
            continue
        sv_r, nat_r, gar = score_line_phien_am_likelihood(txt)
        if (sv_r >= 0.48 and nat_r == 0.0) or (sv_r >= 0.38 and gar and nat_r == 0.0):
            df.loc[idx, "dung_de_ghep"] = False
            dropped_pa += 1

    return df, {
        "recovered_prose_sents": recovered_prose,
        "dropped_leaked_phien_am_rows": dropped_pa,
        "trimmed_intro_with_phien_am_rows": trimmed_intro,
    }


# ==============================================================================
# 3. KHÔI PHỤC CHÍNH TẢ OCR TIẾNG VIỆT CÓ KIỂM SOÁT CHO CÁC CÂU CÒN LỖI MẶT CHỮ
# ==============================================================================
VIET_VOWELS = set("aàảãáạăằẳẵắặâầẩẫấậeèẻẽéẹêềểễếệiìỉĩíịoòỏõóọôồổỗốộơờởỡớợuùủũúụưừửữứựyỳỷỹýỵ")
VALID_ONSETS = {
    "", "b", "c", "ch", "d", "đ", "g", "gh", "gi", "h", "k", "kh", "l", "m", "n", "ng", "ngh",
    "nh", "p", "ph", "q", "qu", "r", "s", "t", "th", "tr", "v", "x",
}
VALID_CODAS = {"", "c", "ch", "m", "n", "ng", "nh", "p", "t"}


def is_suspicious_viet_token(tok: str) -> bool:
    """Kiểm tra một token có dấu hiệu lỗi OCR tiếng Việt (chứa chữ số lẫn chữ cái, phụ âm đầu/cuối bất hợp lệ, ký tự lạ)."""
    if not tok:
        return False
    # Số thuần túy -> hợp lệ
    if tok.isdigit():
        return False
    # Chữ lẫn số (như `ai2`, `4Ô`, `0L`, `1y`) -> lỗi OCR!
    if any(c.isdigit() for c in tok) and any(c.isalpha() for c in tok):
        return True
    # Viết hoa bất thường ở giữa từ (như `ốG`, `RẰy`, `thuyý`)
    if len(tok) >= 2 and any(c.isupper() for c in tok[1:]) and not tok.isupper():
        return True

    low = tok.lower()
    if not re.fullmatch(r"[a-zà-ỹđ]+", low):
        return True

    # Tách onset - nucleus - coda tiếng Việt
    idx = 0
    if low.startswith(("ngh",)):
        onset, idx = "ngh", 3
    elif low.startswith(("qu", "gi", "ch", "gh", "kh", "ng", "nh", "ph", "th", "tr")):
        onset, idx = low[:2], 2
        if onset in ("gi", "qu") and idx == len(low):
            return False
    else:
        while idx < len(low) and low[idx] not in VIET_VOWELS:
            idx += 1
        onset = low[:idx]

    if onset not in VALID_ONSETS:
        return True

    v_start = idx
    while idx < len(low) and low[idx] in VIET_VOWELS:
        idx += 1
    nucleus = low[v_start:idx]
    coda = low[idx:]

    if not nucleus and onset not in ("gi",):
        return True
    if len(nucleus) > 3:
        return True
    if coda not in VALID_CODAS:
        return True
    return False


def line_needs_ocr_spellcheck(text: str) -> bool:
    if re.search(r"[%†®©⁄~_]|'\?|\"\?|\”\?", text):
        return True
    tokens = re.findall(r"[0-9a-zA-ZÀ-ỹĐđ]+", text)
    for t in tokens:
        if is_suspicious_viet_token(t):
            return True
    return False


class SpellFixItem(BaseModel):
    idx: int
    fixed_text: str = Field(description="Câu tiếng Việt đã sửa lỗi nhận dạng ký tự OCR, giữ nguyên 100% ý và cấu trúc câu")


class BatchSpellFixResponse(BaseModel):
    items: List[SpellFixItem]


SPELL_SYS_PROMPT = """Bạn là bộ khôi phục lỗi OCR chính tả tiếng Việt cho sách in Phủ biên tạp lục.
Các câu dưới đây được trích từ lớp OCR của sách in tiếng Việt nên có một số lỗi nhận dạng mặt chữ cơ bản (ví dụ: `tod -> toả`, `chún -> chán`, `Lú ngọc -> Lá ngọc`, `của hang -> cửa hang`, `Nhòn tới -> Nhàn tới`, `uô tôm mù -> vô tâm mà`, `mưu móc -> mưa móc`, `chuốf -> chuối`, `chủy xuôi -> chảy xuôi`, `dụng xd -> dụng xả`, `4Ô -> 40`, ký tự rác chú thích còn dính).
QUY TẮC NGHIÊM NGẶT:
1. CHỈ sửa các từ bị lỗi mặt chữ/dấu thanh OCR tiếng Việt và xóa ký tự chú thích rác (`®`, `†`, `'?`, số chú thích dính đuôi từ).
2. TUYỆT ĐỐI KHÔNG viết lại câu, KHÔNG diễn giải lại văn phong, KHÔNG thêm hoặc cắt bỏ mệnh đề, giữ nguyên các tên riêng Hán-Việt và con số thực tế."""


def run_constrained_ocr_spellfix(records: List[Dict], block_name: str, client: genai.Client) -> Tuple[List[Dict], int]:
    cache: Dict[str, str] = {}
    if SPELL_CACHE_JSONL.exists():
        with open(SPELL_CACHE_JSONL, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    obj = json.loads(line)
                    cache[obj["orig"]] = obj["fixed"]

    suspect_idxs = [i for i, r in enumerate(records) if line_needs_ocr_spellcheck(r["text_vi"])]
    to_query = [i for i in suspect_idxs if records[i]["text_vi"] not in cache]

    print(
        f"    [{block_name} OCR Spell-Check]: Phát hiện {len(suspect_idxs)}/{len(records)} câu có token nghi lỗi OCR "
        f"(cần gọi mới: {len(to_query)}).",
        flush=True,
    )

    batch_size = 25
    for start in tqdm(range(0, len(to_query), batch_size), desc=f"Sửa lỗi OCR Việt [{block_name}]"):
        batch_i = to_query[start : start + batch_size]
        lines_prompt = [f"[idx={i}] {records[i]['text_vi']}" for i in batch_i]
        prompt = "Hãy sửa lỗi mặt chữ OCR tiếng Việt cho các dòng sau:\n\n" + "\n".join(lines_prompt)

        for attempt in range(4):
            try:
                resp = client.models.generate_content(
                    model="gemini-3.5-flash-lite",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SPELL_SYS_PROMPT,
                        temperature=0.0,
                        response_mime_type="application/json",
                        response_schema=BatchSpellFixResponse,
                    ),
                )
                parsed = BatchSpellFixResponse.model_validate_json(resp.text)
                new_entries = []
                for it in parsed.items:
                    if it.idx in batch_i:
                        orig_s = records[it.idx]["text_vi"]
                        fx_s = re.sub(r"\s+", " ", it.fixed_text).strip()
                        # Ràng buộc bảo toàn độ dài nghiêm ngặt: số từ không được lệch quá ±20% hoặc ±3 từ
                        w_orig = len(orig_s.split())
                        w_fx = len(fx_s.split())
                        if fx_s and abs(w_fx - w_orig) <= max(3, int(0.22 * w_orig)):
                            cache[orig_s] = fx_s
                            new_entries.append({"orig": orig_s, "fixed": fx_s})
                if new_entries:
                    V4_OUT_DIR.mkdir(parents=True, exist_ok=True)
                    with open(SPELL_CACHE_JSONL, "a", encoding="utf-8") as f:
                        for e in new_entries:
                            f.write(json.dumps(e, ensure_ascii=False) + "\n")
                break
            except Exception:
                time.sleep(2.5 * (attempt + 1))
        if start + batch_size < len(to_query):
            time.sleep(1.5)

    fixed_cnt = 0
    for i in suspect_idxs:
        orig_s = records[i]["text_vi"]
        fx_s = cache.get(orig_s)
        if fx_s and fx_s != orig_s:
            records[i]["text_vi"] = fx_s
            fixed_cnt += 1

    return records, fixed_cnt


def process_viet_block_v4(block_name: str, xlsx_path: Path, client: genai.Client) -> Tuple[List[Dict], Dict]:
    df = pd.read_excel(xlsx_path, sheet_name="CAU_VIET")
    filter_info = {}
    if block_name == "Cap_02_V":
        df, filter_info = filter_cap02_v_phien_am_structural(df)

    mask = (df["dung_de_ghep"] == True) & (~df["loai"].isin(["chu_thich", "tieu_de", "phien_am"]))  # noqa: E712
    df_filtered = df[mask].copy()

    records: List[Dict] = []
    for row in df_filtered.itertuples(index=False):
        row_loai = str(row.loai)
        cleaned_vi = deterministic_viet_clean(str(row.text_vi), loai=row_loai)
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

    records, n_spell_fixed = run_constrained_ocr_spellfix(records, block_name, client)
    # Chạy lại hậu kiểm số hàng nghìn & khoảng trắng sau spellfix
    for r in records:
        s = r["text_vi"]
        s = re.sub(r"(?<=\d)\.(?=\d{3}\b)", "", s)
        r["text_vi"] = re.sub(r"\s+", " ", s).strip()

    filter_info["ocr_spell_fixed_sents"] = n_spell_fixed
    filter_info["final_viet_sents"] = len(records)
    return records, filter_info


def save_jsonl(records: List[Dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    V4_OUT_DIR.mkdir(parents=True, exist_ok=True)
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    blocks = [
        ("Cap_01", OCR_DIR / "Cap_01" / "VIET" / "VIET_0186-0251.xlsx"),
        ("Cap_02_V", OCR_DIR / "Cap_02" / "VIET" / "VIET_0001-0105.xlsx"),
        ("Cap_02_VI", OCR_DIR / "Cap_02" / "VIET" / "VIET_0405-0439.xlsx"),
    ]

    meta = {"version": "v4", "blocks": {}}
    all_han_txt = []
    all_viet_txt = []

    for bname, v_xlsx in blocks:
        # Chữ Hán ở v3 đã chấm câu chuẩn xác -> copy nguyên vẹn sang 03_text_sach/output/v4/
        src_han = V3_OUT_DIR / f"{bname}_HAN_clean.jsonl"
        dst_han = V4_OUT_DIR / f"{bname}_HAN_clean.jsonl"
        shutil.copy2(src_han, dst_han)
        han_recs = [json.loads(l) for l in src_han.read_text(encoding="utf-8").splitlines() if l.strip()]
        all_han_txt.extend(r["han_co_goc"].strip() for r in han_recs)

        viet_recs, info = process_viet_block_v4(bname, v_xlsx, client)
        dst_viet = V4_OUT_DIR / f"{bname}_VIET_clean.jsonl"
        save_jsonl(viet_recs, dst_viet)
        all_viet_txt.extend(r["text_vi"].strip() for r in viet_recs)

        meta["blocks"][bname] = {"han_sents": len(han_recs), **info}
        print(f"    -> [{bname}] Hán: {len(han_recs)} câu | Việt sạch v4: {len(viet_recs)} câu | Info: {info}", flush=True)

    (V4_OUT_DIR / "run_metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # Cập nhật luôn 03_text_sach/han.txt và 03_text_sach/viet.txt chuẩn Guideline
    (STAGE_DIR / "han.txt").write_text("\n".join(all_han_txt) + "\n", encoding="utf-8")
    (STAGE_DIR / "viet.txt").write_text("\n".join(all_viet_txt) + "\n", encoding="utf-8")
    print(f"\n>>> HOÀN TẤT 03_text_sach/v4! Tổng Hán = {len(all_han_txt)} câu | Tổng Việt sạch = {len(all_viet_txt)} câu.", flush=True)


if __name__ == "__main__":
    main()
