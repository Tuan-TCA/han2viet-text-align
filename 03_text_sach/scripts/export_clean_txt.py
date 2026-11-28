# -*- coding: utf-8 -*-
"""
Xuất file văn bản Hán và Việt đã làm sạch (`03_text_sach/han.txt` và `03_text_sach/viet.txt`)
từ `03_text_sach/output/v3/*.jsonl` theo đúng yêu cầu Mục 2 (#3) của Guideline.pdf.
"""

import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
STAGE_DIR = SCRIPT_DIR.parent
V3_DIR = STAGE_DIR / "output" / "v3"

HAN_FILES = [
    V3_DIR / "Cap_01_HAN_clean.jsonl",
    V3_DIR / "Cap_02_V_HAN_clean.jsonl",
    V3_DIR / "Cap_02_VI_HAN_clean.jsonl",
]
VIET_FILES = [
    V3_DIR / "Cap_01_VIET_clean.jsonl",
    V3_DIR / "Cap_02_V_VIET_clean.jsonl",
    V3_DIR / "Cap_02_VI_VIET_clean.jsonl",
]


def load_lines(files, field: str):
    out = []
    for fp in files:
        with open(fp, "r", encoding="utf-8") as f:
            for raw in f:
                if raw.strip():
                    obj = json.loads(raw)
                    txt = re.sub(r"[\t\r\n]+", " ", str(obj[field])).strip()
                    txt = re.sub(r" {2,}", " ", txt)
                    if txt:
                        out.append(txt)
    return out


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    han_lines = load_lines(HAN_FILES, "han_co_goc")
    viet_lines = load_lines(VIET_FILES, "text_vi")

    han_out = STAGE_DIR / "han.txt"
    viet_out = STAGE_DIR / "viet.txt"

    han_out.write_text("\n".join(han_lines) + "\n", encoding="utf-8")
    viet_out.write_text("\n".join(viet_lines) + "\n", encoding="utf-8")

    print(f"Đã xuất {han_out}: {len(han_lines)} dòng Hán sạch.")
    print(f"Đã xuất {viet_out}: {len(viet_lines)} dòng Việt sạch.")


if __name__ == "__main__":
    main()
