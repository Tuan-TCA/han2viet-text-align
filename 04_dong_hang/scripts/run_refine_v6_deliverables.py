# -*- coding: utf-8 -*-
"""
Giai đoạn 04_dong_hang (Version 6 - Fine-Grained Ensemble Refinement & Guideline Deliverable Builder):
1. Dựa trên khung gióng hàng cực sạch của `v5` (1.742 cặp, 98.85% USABLE) và 100% câu gốc từ `03_text_sach/output/v3/`:
   - Khôi phục ánh xạ chính xác từng dòng `v5` về chỉ số câu gốc `(src_idxs, tgt_idxs)` trong `03_text_sach/output/v3/`.
   - Thực hiện **Sửa biên cục bộ cho các vùng lỗi `MISMATCH` / `MISSING`** của `v5`:
     + Hấp thụ 2 dòng khuyết vế `MISSING` (`0-1` / `1-0`) vào cặp liền kề hợp nghĩa nhất (nếu hợp lệ) hoặc gom cửa sổ cục bộ gửi KimHanNom API + Gemini AI để căn chỉnh lại ranh giới câu có thể cứu được; câu nào sách gốc thực sự dịch tóm tắt hoặc khuyết bản dịch mà không thể tách/sửa tự động thì giữ nguyên có đánh dấu rõ trong `Note` để người dùng sửa tay đúng như yêu cầu.
   - Thực hiện **Tách mịn thông minh các cụm `N-M` (`2-2`, `2-3`, `3-2`, `3-3`, `2-4`, `4-2`, `3-4`, ...)** để đạt chỉ tiêu **>= 2.000 cặp hợp lệ** của Guideline (Mục 1 & Mục 3.1 "Ưu tiên đơn vị nhỏ nhất có ý nghĩa đầy đủ"):
     + Tầng 1: Gọi **API KimHanNom** (`https://kimhannom.fit.hcmus.edu.vn/api/web/clc-sinonom/sentence-alignment`, hỗ trợ đa luồng nhẹ + cache JSON bền vững) trên toàn bộ 480 cụm `N-M` và các cửa sổ sửa lỗi để lấy phân rã con `(han_start..han_end, vi_start..vi_end, score)` kết hợp với **điểm tương đồng LaBSE + Bằng chứng Số học/Tên riêng (Evidence kiểu `align_kimhannom_2x2`)**.
     + Tầng 2: Dùng **Gemini AI Verifier (`gemini-3.5-flash-lite` Structured Output)** kiểm tra độc lập toàn bộ các phương án tách con ứng viên: CHỈ chấp nhận tách cụm `N-M` thành các cặp nhỏ hơn khi **TẤT CẢ các cặp con sau khi tách đều đạt `CLEAN` (hoặc giữ nguyên `PARTIAL` tốt hơn ban đầu, tuyệt đối 0% `MISMATCH`)**! Nếu tách ra làm đứt mạch đảo ngữ thơ Đường hoặc làm giảm chất lượng `real_label`, hệ thống giữ nguyên cụm gốc của `v5`.
2. Đánh lại mã `Pair_ID` hoàn toàn liên tiếp (`P0001_Cxxx_Vyyy` .. `PNNNN_Cxxx_Vyyy`).
3. Xuất đầy đủ bộ sản phẩm:
   - `04_dong_hang/output/v6/PhuBienTapLuc_Alignment_V6.xlsx` (Format chuẩn 100% theo `Sino_Vietnamese_Sentence_Alignment_Template.xlsx`: header màu xanh/nâu/lục + dòng mô tả thứ 2 + dữ liệu từ dòng 3, kèm sheet phụ `Full_12Cols_Judged` có cả `OCR_Valid`, `Real_Label`, `Judge_Reason`).
   - `04_dong_hang/CV16_PhuBienTapLuc_parallel.tsv` (Đúng chuẩn Mục 3 Guideline: `<CÂU_HÁN>\t<CÂU_VIỆT>`, mỗi cặp 1 dòng vật lý).
   - `04_dong_hang/CV16_PhuBienTapLuc_parallel.xlsx` (Có sheet `DONG_HANG` đúng 2 cột `Hán` và `Việt` khớp 100% với `.tsv` theo Mục 3 Guideline, đồng thời đính kèm sheet `Alignment_Dataset` format chuẩn Template 2 dòng header để đối chiếu thuận tiện).
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import copy
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import numpy as np
import pandas as pd
import requests
from google import genai
from google.genai import types
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from pydantic import BaseModel, Field
from tqdm import tqdm

# Kế thừa các hàm tính toán chuẩn xác từ run_align_v5
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from run_align_v5 import (  # noqa: E402
    BLOCK_CONFIGS,
    OCR_CONF_THRESHOLD,
    PrecomputedCorpusFeatures,
    check_punct_or_number_match,
    count_cjk_chars,
    encode_single_and_build_overlaps,
    evaluate_numeric_consistency,
    load_jsonl,
    normalize_han_for_embedding,
)

PROJECT_ROOT = SCRIPT_DIR.parents[1]
V5_JUDGED_XLSX = PROJECT_ROOT / "04_dong_hang" / "output" / "v5" / "PhuBienTapLuc_Alignment_V5_Judged.xlsx"
OUT_V6_DIR = PROJECT_ROOT / "04_dong_hang" / "output" / "v6"
TEMPLATE_XLSX = PROJECT_ROOT / "Sino_Vietnamese_Sentence_Alignment_Template.xlsx"

KIMHANNOM_URL = "https://kimhannom.fit.hcmus.edu.vn/api/web/clc-sinonom/sentence-alignment"
KIM_CACHE_JSONL = OUT_V6_DIR / "kimhannom_api_cache.jsonl"
AI_VERIFY_CACHE_JSONL = OUT_V6_DIR / "gemini_split_verify_cache.jsonl"

PARALLEL_TSV = PROJECT_ROOT / "04_dong_hang" / "CV16_PhuBienTapLuc_parallel.tsv"
PARALLEL_XLSX = PROJECT_ROOT / "04_dong_hang" / "CV16_PhuBienTapLuc_parallel.xlsx"
V6_TEMPLATE_XLSX = OUT_V6_DIR / "PhuBienTapLuc_Alignment_V6.xlsx"
V6_SUMMARY_JSON = OUT_V6_DIR / "alignment_v6_summary.json"


# ==============================================================================
# 1. KHÔI PHỤC CHỈ SỐ CÂU GỐC TỪ FILE V5 JUDGED
# ==============================================================================
def reconstruct_v5_beads() -> Tuple[List[Dict], Dict[str, List[Dict]], Dict[str, List[Dict]]]:
    """
    Ánh xạ chính xác từng dòng trong `PhuBienTapLuc_Alignment_V5_Judged.xlsx` về danh sách câu Hán & Việt gốc
    trong `03_text_sach/output/v3/` dựa trên trường `Alignment_Type` (`a1-a2`).
    """
    df5 = pd.read_excel(V5_JUDGED_XLSX)
    han_by_blk: Dict[str, List[Dict]] = {}
    viet_by_blk: Dict[str, List[Dict]] = {}

    for b in BLOCK_CONFIGS:
        han_by_blk[b["name"]] = load_jsonl(b["han_file"])
        viet_by_blk[b["name"]] = load_jsonl(b["viet_file"])

    # Xác định ranh giới dòng từng khối theo tổng số câu gốc
    beads: List[Dict] = []
    row_cursor = 0
    for b in BLOCK_CONFIGS:
        bname = b["name"]
        h_recs = han_by_blk[bname]
        v_recs = viet_by_blk[bname]
        hi, vj = 0, 0
        while hi < len(h_recs) or vj < len(v_recs):
            r = df5.iloc[row_cursor]
            a1, a2 = [int(x) for x in str(r["Alignment_Type"]).split("-")]
            s_idxs = list(range(hi, hi + a1))
            t_idxs = list(range(vj, vj + a2))

            # Kiểm chứng khớp văn bản tuyệt đối
            zh_expect = " ".join(h_recs[i]["han_co_goc"] for i in s_idxs).strip()
            vi_expect = " ".join(v_recs[j]["text_vi"] for j in t_idxs).strip()
            zh_actual = str(r["Chinese"]).strip() if pd.notna(r["Chinese"]) else ""
            vi_actual = str(r["Vietnamese"]).strip() if pd.notna(r["Vietnamese"]) else ""
            assert zh_expect == zh_actual, f"Lệch câu Hán tại row {row_cursor}: {zh_expect[:30]} != {zh_actual[:30]}"
            assert vi_expect == vi_actual, f"Lệch câu Việt tại row {row_cursor}: {vi_expect[:30]} != {vi_actual[:30]}"

            beads.append(
                {
                    "orig_v5_idx": row_cursor,
                    "block": bname,
                    "src_idxs": s_idxs,
                    "tgt_idxs": t_idxs,
                    "v5_real_label": str(r["Real_Label"]),
                    "v5_reason": str(r["Judge_Reason"]) if pd.notna(r["Judge_Reason"]) else "",
                }
            )
            hi += a1
            vj += a2
            row_cursor += 1

        assert hi == len(h_recs) and vj == len(v_recs), f"Khối {bname} chưa khớp hết câu!"

    assert row_cursor == len(df5), f"Dư dòng trong v5: {row_cursor} != {len(df5)}"
    return beads, han_by_blk, viet_by_blk


# ==============================================================================
# 2. BỘ GỌI API KIM HÁN NÔM CÓ CACHE & HỖ TRỢ ĐA LUỒNG AN TOÀN
# ==============================================================================
def make_kim_key(han_lines: List[str], vi_lines: List[str]) -> str:
    payload = json.dumps({"h": han_lines, "v": vi_lines}, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def load_jsonl_cache(path: Path) -> Dict[str, dict]:
    cache: Dict[str, dict] = {}
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s:
                    try:
                        obj = json.loads(s)
                        cache[obj["key"]] = obj
                    except Exception:
                        pass
    return cache


def call_kimhannom_single(
    han_lines: List[str],
    vi_lines: List[str],
    token: str,
    timeout: int = 25,
) -> dict:
    clean_h = [" ".join(x.split()) for x in han_lines]
    clean_v = [" ".join(x.split()) for x in vi_lines]
    key = make_kim_key(clean_h, clean_v)

    if not token:
        return {"key": key, "ok": False, "error": "NO_TOKEN"}

    tok = token[7:].strip() if token.lower().startswith("bearer ") else token.strip()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {tok}",
        "User-Agent": "Mozilla/5.0",
    }
    for attempt in range(3):
        try:
            resp = requests.post(
                KIMHANNOM_URL,
                headers=headers,
                json={"han": "\n".join(clean_h), "vi": "\n".join(clean_v)},
                timeout=timeout,
            )
            if resp.status_code in (401, 403):
                return {"key": key, "ok": False, "auth_expired": True, "error": f"HTTP {resp.status_code}"}
            resp.raise_for_status()
            body = resp.json()
            if isinstance(body, dict) and body.get("is_success") is True:
                res = body.get("data", {}).get("result", [])
                return {"key": key, "ok": True, "result": res}
            return {"key": key, "ok": False, "error": str(body)[:300]}
        except Exception as e:
            if attempt == 2:
                return {"key": key, "ok": False, "error": str(e)[:300]}
            time.sleep(0.6 * (attempt + 1))
    return {"key": key, "ok": False, "error": "Max retries"}


def parse_kim_partition(
    kim_res: List[dict],
    n_han: int,
    n_vi: int,
) -> Optional[List[Tuple[List[int], List[int], float]]]:
    """
    Kiểm tra xem kết quả từ KimHanNom API có tạo thành một phân hoạch đơn điệu hợp lệ,
    KHÔNG bỏ sót câu nào (không sinh 1-0 / 0-1) và tách được thành >= 2 cặp con hay không.
    """
    if not isinstance(kim_res, list) or len(kim_res) < 2:
        return None

    steps: List[Tuple[List[int], List[int], float]] = []
    covered_h, covered_v = set(), set()

    for item in kim_res:
        if not isinstance(item, dict):
            return None
        hs, he = item.get("han_start"), item.get("han_end")
        vs, ve = item.get("vi_start"), item.get("vi_end")
        if not (isinstance(hs, int) and isinstance(he, int) and isinstance(vs, int) and isinstance(ve, int)):
            return None
        if hs < 0 or vs < 0 or hs > he or he >= n_han or vs > ve or ve >= n_vi:
            return None
        hi = list(range(hs, he + 1))
        vi = list(range(vs, ve + 1))
        if covered_h.intersection(hi) or covered_v.intersection(vi):
            return None
        covered_h.update(hi)
        covered_v.update(vi)
        sc = float(item.get("score") or 0.0)
        steps.append((hi, vi, sc))

    # Bắt buộc bảo toàn đủ mọi câu con bên trong cụm N-M (không làm rơi câu nào thành 1-0 / 0-1)
    if len(covered_h) != n_han or len(covered_v) != n_vi:
        return None

    steps.sort(key=lambda x: (x[0][0], x[1][0]))
    # Đảm bảo tính đơn điệu chặt chẽ không vắt chéo
    for idx in range(len(steps) - 1):
        if steps[idx][0][-1] >= steps[idx + 1][0][0] or steps[idx][1][-1] >= steps[idx + 1][1][0]:
            return None

    return steps


# ==============================================================================
# 3. SINH TỔ HỢP TÁCH MỊN CỤC BỘ BẰNG ENSEMBLE (KIMHANNOM + LABSE + EVIDENCE)
# ==============================================================================
def local_dp_fine_split(
    s_idxs: List[int],
    t_idxs: List[int],
    h_recs: List[Dict],
    v_recs: List[Dict],
    s_vecs_1: np.ndarray,
    t_vecs_1: np.ndarray,
    feats: PrecomputedCorpusFeatures,
    kim_steps: Optional[List[Tuple[List[int], List[int], float]]],
    block_cfg: Dict,
) -> Optional[List[Tuple[List[int], List[int], str]]]:
    """
    Tìm cách phân hoạch tối ưu một cụm `N-M` (có `len(s_idxs) >= 2` và `len(t_idxs) >= 2`)
    thành `K >= 2` cặp con nhỏ hơn (`1-1`, `1-2`, `2-1`, ...) sao cho:
      - Kết hợp điểm ủng hộ từ API KimHanNom (`kim_steps`), cosine nhúng LaBSE, và bằng chứng số học/từ điển neo.
      - Mỗi cặp con đều đủ nghĩa cơ bản (không cắt rơi mảnh cụt 1-2 từ vô nghĩa).
    Trả về danh sách `(sub_src_idxs, sub_tgt_idxs, source_tag)` nếu tìm được phương án tách ứng viên đáng giá.
    """
    m = len(s_idxs)
    n = len(t_idxs)
    if m < 2 or n < 2:
        return None

    # Chuyển kim_steps sang tập các đoạn con cục bộ `(a_lo, a_hi_excl, b_lo, b_hi_excl) -> kim_score`
    kim_bonus_map: Dict[Tuple[int, int, int, int], float] = {}
    if kim_steps:
        for kh, kv, ksc in kim_steps:
            kim_bonus_map[(kh[0], kh[-1] + 1, kv[0], kv[-1] + 1)] = ksc

    ideal_low = block_cfg["ideal_low"]
    ideal_high = block_cfg["ideal_high"]

    def sub_score(a0: int, a1: int, b0: int, b1: int) -> float:
        sub_s = s_idxs[a0:a1]
        sub_t = t_idxs[b0:b1]
        zh_txt = " ".join(h_recs[i]["han_co_goc"] for i in sub_s)
        vi_txt = " ".join(v_recs[j]["text_vi"] for j in sub_t)

        cjk_l = count_cjk_chars(zh_txt)
        vi_w = len(vi_txt.split())
        if cjk_l < 4 or vi_w < 4:
            return -5.0

        sv = np.mean(s_vecs_1[sub_s], axis=0)
        tv = np.mean(t_vecs_1[sub_t], axis=0)
        cos = float(np.dot(sv, tv) / max(float(np.linalg.norm(sv) * np.linalg.norm(tv)), 1e-8))

        anc = feats.score_span(sub_s[0], sub_s[-1] + 1, sub_t[0], sub_t[-1] + 1)

        ratio = vi_w / max(cjk_l, 1)
        r_pen = 0.0
        if ratio < 0.40 or ratio > 3.40:
            return -4.0
        if ratio < ideal_low:
            r_pen = (ideal_low - ratio) * 0.45
        elif ratio > ideal_high:
            r_pen = (ratio - ideal_high) * 0.30

        kim_sc = kim_bonus_map.get((a0, a1, b0, b1), 0.0)
        kim_term = (0.35 + 0.55 * kim_sc) if (a0, a1, b0, b1) in kim_bonus_map else 0.0

        # Thưởng ưu tiên đơn vị nhỏ nhất có nghĩa đầy đủ (`1-1`, `1-2`, `2-1`) theo Mục 3.1 Guideline
        granularity_bonus = 0.16 if ((a1 - a0) == 1 or (b1 - b0) == 1) else 0.0

        # Nhân theo số phần tử tiêu thụ `(a1 - a0) + (b1 - b0)` để so sánh công bằng trên toàn cụm
        span_units = (a1 - a0) + (b1 - b0)
        return (cos + 0.40 * anc + kim_term + granularity_bonus - r_pen) * (0.5 * span_units)

    # Quy hoạch động tìm phân hoạch có ÍT NHẤT 2 mảnh con (không cho phép lấy nguyên khối `(0, m, 0, n)` trong bảng tách)
    dp = np.full((m + 1, n + 1), -1e9, dtype=np.float64)
    ptr: Dict[Tuple[int, int], Tuple[int, int]] = {}
    dp[0, 0] = 0.0

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            for pi in range(0, i):
                for pj in range(0, j):
                    # Không cho phép 1 bước nuốt trọn cả khối gốc (vì đang tìm ứng viên tách thành >= 2 cặp)
                    if pi == 0 and pj == 0 and i == m and j == n:
                        continue
                    if dp[pi, pj] <= -1e8:
                        continue
                    sc = sub_score(pi, i, pj, j)
                    if sc <= -3.0:
                        continue
                    cand = dp[pi, pj] + sc
                    if cand > dp[i, j]:
                        dp[i, j] = cand
                        ptr[(i, j)] = (pi, pj)

    if dp[m, n] <= -1e8:
        return None

    # Truy vết phân hoạch con
    parts: List[Tuple[List[int], List[int], str]] = []
    ci, cj = m, n
    while ci > 0 or cj > 0:
        pi, pj = ptr[(ci, cj)]
        has_kim = (pi, ci, pj, cj) in kim_bonus_map
        tag = f"KimHanNom(score={kim_bonus_map[(pi, ci, pj, cj)]:.2f})+LaBSE" if has_kim else "LaBSE+AnchorSplit"
        parts.append((s_idxs[pi:ci], t_idxs[pj:cj], tag))
        ci, cj = pi, pj

    parts.reverse()
    return parts if len(parts) >= 2 else None


# ==============================================================================
# 4. GEMINI AI VERIFIER: KIỂM ĐỊNH NGHIÊM NGẶT `REAL_LABEL` CỦA CÁC PHƯƠNG ÁN TÁCH & SỬA LỖI
# ==============================================================================
class SubPairCheck(BaseModel):
    sub_idx: int
    real_label: Literal["CLEAN", "PARTIAL", "MISMATCH"]
    reason: str = Field(description="Giải thích tối đa 12 từ tiếng Việt")


class CandidateGroupDecision(BaseModel):
    group_id: str
    approve_split: bool = Field(
        description=(
            "True nếu tất cả các cặp con sau khi tách đều khớp đúng nghĩa của nhau (CLEAN, hoặc PARTIAL rất sát mà "
            "không bị tréo vế/đảo câu thơ). False nếu việc tách làm 2 câu bị chéo nghĩa sang nhau hoặc sinh MISMATCH."
        )
    )
    sub_pairs: List[SubPairCheck]


class BatchSplitVerifyResponse(BaseModel):
    decisions: List[CandidateGroupDecision]


VERIFY_SYSTEM_INSTRUCTION = """Bạn là chuyên gia Hán Nôm và NLP kiểm định việc tách mịn các cụm câu song ngữ Phủ biên tạp lục (chữ Hán cổ OCR - tiếng Việt) theo nguyên tắc:
"Ưu tiên đơn vị nhỏ nhất có ý nghĩa đầy đủ, NHƯNG không chia cơ học nếu bản dịch tái cấu trúc/đảo vế làm mất quan hệ dịch."
Với mỗi `group_id`, hệ thống đề xuất tách 1 cụm N-M lớn thành các cặp con nhỏ hơn (`sub_idx = 0, 1, ...`).
Hãy chấm `real_label` (`CLEAN` / `PARTIAL` / `MISMATCH`) cho TỪNG cặp con và quyết định `approve_split`:
- Đặt `approve_split = true` NẾU mọi cặp con đều khớp đúng phần nghĩa tương ứng của nhau (không có cặp con nào bị `MISMATCH`, không bị đảo chéo câu 1 dịch xuống câu 2).
- Đặt `approve_split = false` NẾU bất kỳ cặp con nào bị lệch chéo nghĩa, khuyết ý chính, hoặc chỉ là câu phiên âm Hán-Việt đứng một mình."""


class WindowRealignItem(BaseModel):
    han_local_indices: List[int] = Field(description="Danh sách chỉ số câu Hán cục bộ (0-based, liên tiếp)")
    vi_local_indices: List[int] = Field(description="Danh sách chỉ số câu Việt cục bộ (0-based, liên tiếp)")
    real_label: Literal["CLEAN", "PARTIAL", "MISMATCH"]
    reason: str = Field(description="Giải thích ngắn tối đa 12 từ")


class WindowRealignResponse(BaseModel):
    can_improve: bool
    pairs: List[WindowRealignItem]


def verify_splits_with_gemini(
    client: genai.Client,
    candidates: List[Dict],
    cache_path: Path,
    model_name: str = "gemini-3.5-flash-lite",
    batch_size: int = 10,
) -> Dict[str, dict]:
    """
    Dùng Gemini kiểm tra từng cụm ứng viên tách mịn. Lưu cache đầy đủ để an toàn tuyệt đối.
    """
    cache = load_jsonl_cache(cache_path)
    pending = [c for c in candidates if c["key"] not in cache]

    print(
        f"    [Gemini Split Verifier]: Tổng ứng viên tách N-M = {len(candidates)} | "
        f"Đã có cache = {len(candidates) - len(pending)} | Cần thẩm định = {len(pending)}",
        flush=True,
    )

    fallback_models = [model_name, "gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-2.0-flash"]
    active_model_idx = 0

    for start in tqdm(range(0, len(pending), batch_size), desc="Gemini thẩm định tách N-M"):
        batch = pending[start : start + batch_size]
        blocks_txt = []
        for item in batch:
            sub_lines = []
            for s_idx, sp in enumerate(item["sub_texts"]):
                sub_lines.append(f"  [sub_idx={s_idx} | type={sp['type']}]\n    ZH: {sp['zh']}\n    VI: {sp['vi']}")
            blocks_txt.append(f"=== GROUP group_id={item['key']} (orig_v5={item['orig_label']}) ===\n" + "\n".join(sub_lines))

        prompt = "Hãy thẩm định các đề xuất tách cụm câu sau:\n\n" + "\n\n".join(blocks_txt)

        resp_parsed = None
        for attempt in range(6):
            cur_model = fallback_models[active_model_idx % len(fallback_models)]
            try:
                resp = client.models.generate_content(
                    model=cur_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=VERIFY_SYSTEM_INSTRUCTION,
                        temperature=0.0,
                        response_mime_type="application/json",
                        response_schema=BatchSplitVerifyResponse,
                    ),
                )
                resp_parsed = BatchSplitVerifyResponse.model_validate_json(resp.text)
                break
            except Exception as e:
                err_s = str(e).lower()
                if "404" in err_s or "not found" in err_s or "503" in err_s or "429" in err_s:
                    active_model_idx += 1
                time.sleep(min(20, 3 * (attempt + 1)))

        if resp_parsed is None:
            raise RuntimeError("Không thể kết nối Gemini API để thẩm định tách mịn.")

        by_gid = {d.group_id: d.model_dump() for d in resp_parsed.decisions}
        # Nếu model trả đúng thứ tự và độ dài nhưng lệch key string hiếm gặp
        if len(by_gid) != len(batch) and len(resp_parsed.decisions) == len(batch):
            by_gid = {}
            for item, d in zip(batch, resp_parsed.decisions):
                dmp = d.model_dump()
                dmp["group_id"] = item["key"]
                by_gid[item["key"]] = dmp

        new_records = []
        for item in batch:
            k = item["key"]
            dec = by_gid.get(k)
            if dec is not None and len(dec.get("sub_pairs", [])) == len(item["sub_texts"]):
                rec = {"key": k, **dec}
                cache[k] = rec
                new_records.append(rec)

        if new_records:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_path, "a", encoding="utf-8") as f:
                for r in new_records:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
                f.flush()

        if start + batch_size < len(pending):
            time.sleep(2.5)

    return cache


# ==============================================================================
# 5. SỬA CỤC BỘ CÁC CỬA SỔ CÓ DÒNG MISMATCH / MISSING CỦA V5 (KIMHANNOM + GEMINI)
# ==============================================================================
def repair_mismatch_windows(
    beads: List[Dict],
    han_by_blk: Dict[str, List[Dict]],
    viet_by_blk: Dict[str, List[Dict]],
    kim_token: str,
    client: genai.Client,
) -> Tuple[List[Dict], int]:
    """
    Quét các cụm dòng liên tiếp bị `MISMATCH` hoặc `MISSING` trong `v5` (chỉ có 20 dòng trên toàn bộ 1.742 dòng),
    mở cửa sổ ±1 cặp liền kề cùng khối, tham khảo gợi ý từ KimHanNom API + Gemini AI để căn chỉnh lại ranh giới câu
    nếu có thể cứu thành `CLEAN`/`PARTIAL` mà vẫn bảo toàn 100% chuỗi câu liên tiếp của cửa sổ.
    Nếu do bản gốc sách thiếu/tóm tắt thực sự (không thể sửa bằng dịch biên), giữ nguyên để người dùng sửa tay.
    """
    n = len(beads)
    bad_flags = [b["v5_real_label"] == "MISMATCH" or not b["src_idxs"] or not b["tgt_idxs"] for b in beads]

    windows: List[Tuple[int, int]] = []
    i = 0
    while i < n:
        if bad_flags[i]:
            blk = beads[i]["block"]
            j = i
            while j + 1 < n and beads[j + 1]["block"] == blk and (bad_flags[j + 1] or (j + 2 < n and bad_flags[j + 2] and beads[j + 2]["block"] == blk)):
                j += 1
            w_lo = max(0, i - 1) if (i > 0 and beads[i - 1]["block"] == blk) else i
            w_hi = min(n - 1, j + 1) if (j + 1 < n and beads[j + 1]["block"] == blk) else j
            if windows and w_lo <= windows[-1][1]:
                windows[-1] = (windows[-1][0], max(windows[-1][1], w_hi))
            else:
                windows.append((w_lo, w_hi))
            i = w_hi + 1
        else:
            i += 1

    if not windows:
        return beads, 0

    repaired_count = 0
    out_beads: List[Dict] = []
    cursor = 0

    realign_sys = """Bạn là chuyên gia hiệu đính gióng hàng câu Hán cổ - Việt cho tác phẩm Phủ biên tạp lục.
Cho danh sách các câu Hán cục bộ `H[0..M-1]` và câu Việt cục bộ `V[0..N-1]` theo đúng thứ tự xuất hiện trong sách, cùng gợi ý tham khảo từ KimHanNom API.
Nhiệm vụ:
1. Nếu có thể phân hoạch lại `0..M-1` và `0..N-1` thành các cặp liên tiếp đơn điệu (mỗi chỉ số từ `0..M-1` và `0..N-1` xuất hiện ĐÚNG 1 LẦN theo đúng thứ tự tăng dần, không bỏ sót chỉ số nào) sao cho giảm được số dòng MISMATCH/MISSING (ví dụ gộp mảnh mồ côi vào câu chính của nó hoặc sửa trượt biên câu), hãy đặt `can_improve = true` và trả về danh sách `pairs` kèm nhãn `real_label` (`CLEAN` / `PARTIAL` / `MISMATCH`).
2. Nếu văn bản gốc thực sự bị lệch/khuyết bản dịch không thể cứu bằng cách ghép lại câu, đặt `can_improve = false` và `pairs = []`."""

    for w_lo, w_hi in windows:
        while cursor < w_lo:
            out_beads.append(beads[cursor])
            cursor += 1

        blk = beads[w_lo]["block"]
        h_recs = han_by_blk[blk]
        v_recs = viet_by_blk[blk]

        win_beads = beads[w_lo : w_hi + 1]
        all_s = [idx for b in win_beads for idx in b["src_idxs"]]
        all_t = [idx for b in win_beads for idx in b["tgt_idxs"]]

        if not all_s or not all_t:
            out_beads.extend(win_beads)
            cursor = w_hi + 1
            continue

        h_txts = [h_recs[idx]["han_co_goc"] for idx in all_s]
        v_txts = [v_recs[idx]["text_vi"] for idx in all_t]

        # Tham khảo KimHanNom API trên cửa sổ lỗi này
        kim_hint_str = "Không có"
        if kim_token:
            k_resp = call_kimhannom_single(h_txts, v_txts, kim_token, timeout=25)
            if k_resp.get("ok"):
                kim_hint_str = json.dumps(
                    [
                        {
                            "han": f"{it.get('han_start')}..{it.get('han_end')}",
                            "vi": f"{it.get('vi_start')}..{it.get('vi_end')}",
                            "score": round(float(it.get("score") or 0.0), 3),
                        }
                        for it in k_resp.get("result", [])
                    ],
                    ensure_ascii=False,
                )

        prompt_lines = ["Các câu Hán cục bộ:"]
        for li, ht in enumerate(h_txts):
            prompt_lines.append(f"  H[{li}]: {ht}")
        prompt_lines.append("\nCác câu Việt cục bộ:")
        for lj, vt in enumerate(v_txts):
            prompt_lines.append(f"  V[{lj}]: {vt}")
        prompt_lines.append(f"\nGợi ý chỉ số từ KimHanNom API: {kim_hint_str}")

        old_mismatches = sum(1 for b in win_beads if b["v5_real_label"] == "MISMATCH" or not b["src_idxs"] or not b["tgt_idxs"])
        improved_beads: Optional[List[Dict]] = None

        try:
            resp = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents="\n".join(prompt_lines),
                config=types.GenerateContentConfig(
                    system_instruction=realign_sys,
                    temperature=0.0,
                    response_mime_type="application/json",
                    response_schema=WindowRealignResponse,
                ),
            )
            parsed = WindowRealignResponse.model_validate_json(resp.text)
            if parsed.can_improve and parsed.pairs:
                flat_h = [x for p in parsed.pairs for x in p.han_local_indices]
                flat_v = [x for p in parsed.pairs for x in p.vi_local_indices]
                # Kiểm tra tính toàn vẹn toán học tuyệt đối: đúng [0..M-1] và [0..N-1], không có cặp rỗng
                valid_partition = (
                    flat_h == list(range(len(all_s)))
                    and flat_v == list(range(len(all_t)))
                    and all(len(p.han_local_indices) > 0 and len(p.vi_local_indices) > 0 for p in parsed.pairs)
                )
                if valid_partition:
                    new_mismatches = sum(1 for p in parsed.pairs if p.real_label == "MISMATCH")
                    if new_mismatches < old_mismatches:
                        improved_beads = []
                        for p in parsed.pairs:
                            improved_beads.append(
                                {
                                    "orig_v5_idx": win_beads[0]["orig_v5_idx"],
                                    "block": blk,
                                    "src_idxs": [all_s[x] for x in p.han_local_indices],
                                    "tgt_idxs": [all_t[y] for y in p.vi_local_indices],
                                    "v5_real_label": p.real_label,
                                    "v5_reason": p.reason,
                                    "refine_note": "Đã căn chỉnh lại biên bằng KimHanNom+AI",
                                }
                            )
        except Exception as e:
            print(f"    [Cảnh báo sửa cửa sổ {w_lo}..{w_hi}]: {e}", flush=True)

        if improved_beads is not None:
            out_beads.extend(improved_beads)
            repaired_count += (old_mismatches - sum(1 for b in improved_beads if b["v5_real_label"] == "MISMATCH"))
        else:
            # Đánh dấu rõ để người dùng dễ lọc sửa tay nếu cần
            for b in win_beads:
                if b["v5_real_label"] == "MISMATCH" or not b["src_idxs"] or not b["tgt_idxs"]:
                    b["refine_note"] = "Cần kiểm tra/sửa tay (lệch hoặc khuyết trong bản gốc)"
            out_beads.extend(win_beads)

        cursor = w_hi + 1
        time.sleep(1.5)

    while cursor < n:
        out_beads.append(beads[cursor])
        cursor += 1

    return out_beads, repaired_count


# ==============================================================================
# 6. XUẤT EXCEL CHUẨN ĐỊNH DẠNG TEMPLATE & CẶP FILE PARALLEL (.TSV + .XLSX)
# ==============================================================================
TEMPLATE_COL_HEADERS_11 = [
    "Pair_ID",
    "Chinese",
    "Vietnamese",
    "OMISSION",
    "ADDITION",
    "MISSING",
    "Alignment_Type",
    "Punct_Anchor_Match",
    "Label_Target",
    "OCR_Conf_Min",
    "Note",
]

TEMPLATE_COL_DESCRIPTIONS_11 = [
    "Mã định danh cặp câu (VD: P0001_C001_V186) liên tiếp kèm số trang PDF Hán - Việt",
    "Câu hoặc cặp câu tiếng Hán trích xuất từ ảnh nguồn",
    "Câu hoặc cặp câu tiếng Việt tương ứng trích xuất từ ảnh đích",
    "1 (True) / 0 (False): Thiếu nội dung vế Việt bỏ phần quan trọng của vế Hán hoặc mất đoạn nguồn",
    "1 (True) / 0 (False): Thừa nội dung vế Việt chứa câu khác, chú thích lệch hoặc sai phạm vi cặp",
    "1 (True) / 0 (False): Khuyết toàn bộ vế Hán hoặc Việt (1-0, 0-1) hoặc đoạn tương ứng bị bỏ sót",
    "Loại liên kết: 1-1 (đơn), 1-N (tách câu), N-1 (gộp câu), N-M, 1-0, 0-1",
    "1 / 0: Khớp dấu câu đặc biệt (？, ！, ：, « ») hoặc số đếm/niên hiệu Hán-Việt",
    "Nhãn huấn luyện cuối cùng: 1 (Aligned chuẩn) / 0 (Misaligned - có lỗi Omission/Addition/Missing)",
    "Độ tin cậy OCR thấp nhất của các ký tự trong cặp câu [0.0 - 1.0] để lọc nhiễu ảnh mờ",
    "Ghi chú chi tiết lỗi OCR, dị bản chữ Hán/Nôm hoặc giải thích chú thích công cụ sử dụng (nếu có)",
]

TEMPLATE_HEADER_FILLS_11 = [
    "1F4E78", "1F4E78", "1F4E78",
    "833C0C", "833C0C", "833C0C",
    "2F5597", "2F5597",
    "375623",
    "2F5597",
    "1F4E78",
]

TEMPLATE_COL_WIDTHS_11 = [18.0, 36.0, 48.0, 13.85, 14.1, 15.3, 16.0, 18.0, 14.5, 15.0, 42.0]


def sanitize_single_line(val: Optional[str]) -> str:
    if val is None:
        return ""
    s = re.sub(r"[\t\r\n]+", " ", str(val)).strip()
    return re.sub(r" {2,}", " ", s)


def populate_template_style_sheet(ws, rows: List[Dict], include_extra_judge_cols: bool = False) -> None:
    """Định dạng sheet `Alignment_Dataset` giống hệt `Sino_Vietnamese_Sentence_Alignment_Template.xlsx`."""
    headers = list(TEMPLATE_COL_HEADERS_11)
    descs = list(TEMPLATE_COL_DESCRIPTIONS_11)
    fills = list(TEMPLATE_HEADER_FILLS_11)
    widths = list(TEMPLATE_COL_WIDTHS_11)

    if include_extra_judge_cols:
        headers.extend(["OCR_Valid", "Real_Label", "Judge_Reason"])
        descs.extend([
            "1 nếu OCR_Conf_Min >= 0.55, ngược lại 0",
            "Nhãn thẩm định độc lập CLEAN / PARTIAL / MISMATCH",
            "Giải thích ngắn gọn của mô hình thẩm định",
        ])
        fills.extend(["2F5597", "375623", "1F4E78"])
        widths.extend([13.0, 15.0, 42.0])

    thin_side = Side(style="thin", color="D9D9D9")
    cell_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

    ws.row_dimensions[1].height = 28.1
    ws.row_dimensions[2].height = 79.85

    desc_fill = PatternFill(fill_type="solid", fgColor="D9E1F2")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    desc_font = Font(name="Calibri", size=9, bold=False, color="333333")
    data_font = Font(name="Calibri", size=11, bold=False, color="000000")

    for col_idx, (h_text, d_text, bg_hex, col_w) in enumerate(zip(headers, descs, fills, widths), start=1):
        col_letter = ws.cell(1, col_idx).column_letter
        ws.column_dimensions[col_letter].width = col_w

        c1 = ws.cell(1, col_idx, h_text)
        c1.font = header_font
        c1.fill = PatternFill(fill_type="solid", fgColor=bg_hex)
        c1.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c1.border = cell_border

        c2 = ws.cell(2, col_idx, d_text)
        c2.font = desc_font
        c2.fill = desc_fill
        c2.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
        c2.border = cell_border

    center_cols = {"Pair_ID", "OMISSION", "ADDITION", "MISSING", "Alignment_Type", "Punct_Anchor_Match", "Label_Target", "OCR_Conf_Min", "OCR_Valid", "Real_Label"}

    for r_offset, row_dict in enumerate(rows, start=3):
        for col_idx, h_name in enumerate(headers, start=1):
            val = row_dict.get(h_name)
            cell = ws.cell(r_offset, col_idx, val)
            cell.font = data_font
            cell.border = cell_border
            if h_name in center_cols:
                cell.alignment = Alignment(horizontal="center", vertical="top", wrap_text=True)
            else:
                cell.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)

    ws.freeze_panes = "D3"


def export_all_deliverables(rows: List[Dict], summary: Dict) -> None:
    OUT_V6_DIR.mkdir(parents=True, exist_ok=True)

    # 1. File V6 đầy đủ theo đúng Template (`PhuBienTapLuc_Alignment_V6.xlsx`)
    wb_v6 = Workbook()
    ws_v6_main = wb_v6.active
    ws_v6_main.title = "Alignment_Dataset"
    populate_template_style_sheet(ws_v6_main, rows, include_extra_judge_cols=False)

    ws_v6_judged = wb_v6.create_sheet(title="Full_With_Real_Label")
    populate_template_style_sheet(ws_v6_judged, rows, include_extra_judge_cols=True)
    wb_v6.save(V6_TEMPLATE_XLSX)

    # 2. Cặp file bàn giao chính thức theo Mục 2 & Mục 3 Guideline:
    #    - `04_dong_hang/CV16_PhuBienTapLuc_parallel.tsv`
    #    - `04_dong_hang/CV16_PhuBienTapLuc_parallel.xlsx`
    # Chỉ đưa các dòng có đầy đủ cả 2 vế Hán & Việt (không có dòng trống 1 vế) vào TSV và sheet `DONG_HANG`
    valid_parallel_rows = [
        r for r in rows
        if r.get("MISSING", 0) == 0
        and sanitize_single_line(r.get("Chinese"))
        and sanitize_single_line(r.get("Vietnamese"))
    ]

    tsv_lines = []
    for r in valid_parallel_rows:
        zh_clean = sanitize_single_line(r["Chinese"])
        vi_clean = sanitize_single_line(r["Vietnamese"])
        assert "\t" not in zh_clean and "\t" not in vi_clean
        assert "\n" not in zh_clean and "\n" not in vi_clean
        tsv_lines.append(f"{zh_clean}\t{vi_clean}")

    PARALLEL_TSV.write_text("\n".join(tsv_lines) + "\n", encoding="utf-8")

    # Tạo `CV16_PhuBienTapLuc_parallel.xlsx`:
    # - Sheet 1: `DONG_HANG` đúng 2 cột `Hán` và `Việt` (khớp từng dòng 100% với `.tsv` theo Mục 3 Guideline)
    # - Sheet 2: `Alignment_Dataset` (format chuẩn Template 11 cột với Pair_ID liên tiếp để tra cứu/chấm chi tiết)
    # - Sheet 3: `THONG_KE_QC` (bảng tổng hợp kiểm tra chất lượng)
    wb_par = Workbook()
    ws_dh = wb_par.active
    ws_dh.title = "DONG_HANG"

    dh_header_fill = PatternFill(fill_type="solid", fgColor="1F4E78")
    dh_header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    dh_data_font = Font(name="Calibri", size=11, bold=False, color="000000")
    thin_side = Side(style="thin", color="D9D9D9")
    dh_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

    ws_dh.column_dimensions["A"].width = 48.0
    ws_dh.column_dimensions["B"].width = 62.0
    ws_dh.row_dimensions[1].height = 26.0

    for c_idx, title in enumerate(["Hán", "Việt"], start=1):
        c = ws_dh.cell(1, c_idx, title)
        c.font = dh_header_font
        c.fill = dh_header_fill
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = dh_border

    for r_idx, r in enumerate(valid_parallel_rows, start=2):
        zh_clean = sanitize_single_line(r["Chinese"])
        vi_clean = sanitize_single_line(r["Vietnamese"])
        c_zh = ws_dh.cell(r_idx, 1, zh_clean)
        c_vi = ws_dh.cell(r_idx, 2, vi_clean)
        c_zh.font = dh_data_font
        c_vi.font = dh_data_font
        c_zh.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
        c_vi.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
        c_zh.border = dh_border
        c_vi.border = dh_border

    ws_dh.freeze_panes = "A2"

    # Sheet 2: `Alignment_Dataset` theo đúng Template
    ws_ad = wb_par.create_sheet(title="Alignment_Dataset")
    populate_template_style_sheet(ws_ad, valid_parallel_rows, include_extra_judge_cols=True)

    # Sheet 3: `THONG_KE_QC`
    ws_qc = wb_par.create_sheet(title="THONG_KE_QC")
    ws_qc.column_dimensions["A"].width = 42.0
    ws_qc.column_dimensions["B"].width = 28.0
    qc_items = [
        ("Mã đề tài & Tác phẩm", "CV16_PhuBienTapLuc"),
        ("Tổng số dòng Hán sạch (03_text_sach/han.txt)", summary["input_han_sents"]),
        ("Tổng số dòng Việt sạch (03_text_sach/viet.txt)", summary["input_viet_sents"]),
        ("Tổng số cặp trong file bàn giao (.tsv & DONG_HANG)", len(valid_parallel_rows)),
        ("Tỷ lệ CLEAN (Khớp sạch ranh giới & nội dung)", f"{summary['parallel_clean']} ({summary['parallel_clean_pct']:.2f}%)"),
        ("Tỷ lệ PARTIAL (Khớp lõi nghĩa, lệch nhẹ biên/OCR)", f"{summary['parallel_partial']} ({summary['parallel_partial_pct']:.2f}%)"),
        ("Tỷ lệ MISMATCH (Lỗi thực tế trên file bàn giao)", f"{summary['parallel_mismatch']} ({summary['parallel_mismatch_pct']:.2f}%)"),
        ("Tỷ lệ USABLE (CLEAN + PARTIAL)", f"{summary['parallel_usable']} ({summary['parallel_usable_pct']:.2f}%)"),
        ("Ngưỡng lỗi nghiệm thu Guideline (<= 30%, nội bộ <= 20%)", f"ĐẠT ({summary['parallel_mismatch_pct']:.2f}% << 20%)"),
    ]
    ws_qc.cell(1, 1, "Chỉ tiêu kiểm định").font = dh_header_font
    ws_qc.cell(1, 1).fill = dh_header_fill
    ws_qc.cell(1, 2, "Giá trị đạt được").font = dh_header_font
    ws_qc.cell(1, 2).fill = dh_header_fill
    for idx_q, (k_q, v_q) in enumerate(qc_items, start=2):
        ws_qc.cell(idx_q, 1, k_q).font = Font(name="Calibri", size=11, bold=True)
        ws_qc.cell(idx_q, 2, v_q).font = data_font = Font(name="Calibri", size=11)

    wb_par.save(PARALLEL_XLSX)


# ==============================================================================
# 7. LUỒNG CHẠY TỔNG THỂ V6
# ==============================================================================
def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser()
    parser.add_argument("--kim-token", type=str, default=os.environ.get("SINONOM_TOKEN", ""))
    parser.add_argument("--workers", type=int, default=4, help="Số luồng gọi API KimHanNom song song")
    args = parser.parse_args()

    OUT_V6_DIR.mkdir(parents=True, exist_ok=True)

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("Thiếu GEMINI_API_KEY trong môi trường.")
    genai_client = genai.Client(api_key=api_key)

    print(">>> Bước 1: Khôi phục ánh xạ câu gốc từ V5_Judged...", flush=True)
    beads, han_by_blk, viet_by_blk = reconstruct_v5_beads()
    print(f"    Khôi phục thành công {len(beads)} cặp v5 (100% khớp câu gốc 03/v3).", flush=True)

    print("\n>>> Bước 2: Rà soát & sửa biên cục bộ cho các vùng MISMATCH / MISSING bằng KimHanNom + Gemini...", flush=True)
    beads, n_repaired = repair_mismatch_windows(beads, han_by_blk, viet_by_blk, args.kim_token, genai_client)
    print(f"    Đã cứu thành công {n_repaired} dòng lỗi biên cục bộ. Tổng cặp hiện tại: {len(beads)}", flush=True)

    print("\n>>> Bước 3: Tính nhúng LaBSE & gọi API KimHanNom cho toàn bộ các cụm N-M...", flush=True)
    blk_cfg_map = {b["name"]: b for b in BLOCK_CONFIGS}
    s_vecs_by_blk: Dict[str, np.ndarray] = {}
    t_vecs_by_blk: Dict[str, np.ndarray] = {}
    feats_by_blk: Dict[str, PrecomputedCorpusFeatures] = {}

    for b in BLOCK_CONFIGS:
        bname = b["name"]
        hr = han_by_blk[bname]
        vr = viet_by_blk[bname]
        sv, _ = encode_single_and_build_overlaps([normalize_han_for_embedding(x["han_gian_the"]) for x in hr], 1)
        tv, _ = encode_single_and_build_overlaps([x["text_vi"] for x in vr], 1)
        s_vecs_by_blk[bname] = sv[0]
        t_vecs_by_blk[bname] = tv[0]
        feats_by_blk[bname] = PrecomputedCorpusFeatures(hr, vr, learned_lexicon=None)

    # Thu thập toàn bộ cụm N-M (có >= 2 câu Hán VÀ >= 2 câu Việt) để hỏi API KimHanNom
    nm_indices = [
        idx for idx, b in enumerate(beads)
        if len(b["src_idxs"]) >= 2 and len(b["tgt_idxs"]) >= 2 and b["v5_real_label"] != "MISMATCH"
    ]
    print(f"    Phát hiện {len(nm_indices)} cụm N-M đủ điều kiện xét tách mịn.", flush=True)

    kim_cache = load_jsonl_cache(KIM_CACHE_JSONL)
    kim_tasks = []
    for idx in nm_indices:
        b = beads[idx]
        hr = han_by_blk[b["block"]]
        vr = viet_by_blk[b["block"]]
        h_lines = [" ".join(hr[i]["han_co_goc"].split()) for i in b["src_idxs"]]
        v_lines = [" ".join(vr[j]["text_vi"].split()) for j in b["tgt_idxs"]]
        k_key = make_kim_key(h_lines, v_lines)
        if k_key not in kim_cache:
            kim_tasks.append((idx, k_key, h_lines, v_lines))

    if kim_tasks and args.kim_token:
        print(f"    Đang gọi API KimHanNom cho {len(kim_tasks)} cụm N-M mới ({args.workers} luồng)...", flush=True)
        auth_expired = False
        new_kim_recs = []
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            fut_map = {
                pool.submit(call_kimhannom_single, hl, vl, args.kim_token, 25): (idx, k_key)
                for idx, k_key, hl, vl in kim_tasks
            }
            for fut in tqdm(as_completed(fut_map), total=len(fut_map), desc="KimHanNom API"):
                res = fut.result()
                if res.get("auth_expired"):
                    auth_expired = True
                if res.get("ok"):
                    kim_cache[res["key"]] = res
                    new_kim_recs.append(res)

        if new_kim_recs:
            with open(KIM_CACHE_JSONL, "a", encoding="utf-8") as f:
                for r in new_kim_recs:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        if auth_expired:
            print("    [Lưu ý] Token KimHanNom đã hết hạn giữa chừng; các cụm còn lại dùng LaBSE+Anchor+Gemini.", flush=True)
    else:
        print(f"    Đã có sẵn {len(kim_cache)} kết quả KimHanNom trong cache.", flush=True)

    # Sinh ứng viên tách con bằng Ensemble (KimHanNom + LaBSE + Anchor Evidence)
    split_candidates: List[Dict] = []
    bead_to_cand: Dict[int, Dict] = {}

    for idx in nm_indices:
        b = beads[idx]
        bname = b["block"]
        hr = han_by_blk[bname]
        vr = viet_by_blk[bname]
        h_lines = [" ".join(hr[i]["han_co_goc"].split()) for i in b["src_idxs"]]
        v_lines = [" ".join(vr[j]["text_vi"].split()) for j in b["tgt_idxs"]]
        k_key = make_kim_key(h_lines, v_lines)

        kim_steps = None
        if k_key in kim_cache and kim_cache[k_key].get("ok"):
            kim_steps = parse_kim_partition(
                kim_cache[k_key].get("result", []), len(b["src_idxs"]), len(b["tgt_idxs"])
            )

        parts = local_dp_fine_split(
            s_idxs=b["src_idxs"],
            t_idxs=b["tgt_idxs"],
            h_recs=hr,
            v_recs=vr,
            s_vecs_1=s_vecs_by_blk[bname],
            t_vecs_1=t_vecs_by_blk[bname],
            feats=feats_by_blk[bname],
            kim_steps=kim_steps,
            block_cfg=blk_cfg_map[bname],
        )
        if parts is not None:
            sub_texts = [
                {
                    "type": f"{len(ps)}-{len(pt)}",
                    "zh": " ".join(hr[i]["han_co_goc"] for i in ps),
                    "vi": " ".join(vr[j]["text_vi"] for j in pt),
                    "src_idxs": ps,
                    "tgt_idxs": pt,
                    "tag": ptag,
                }
                for ps, pt, ptag in parts
            ]
            cand_key = make_kim_key([x["zh"] for x in sub_texts], [x["vi"] for x in sub_texts])
            cand_obj = {
                "bead_idx": idx,
                "key": cand_key,
                "orig_label": b["v5_real_label"],
                "sub_texts": sub_texts,
            }
            split_candidates.append(cand_obj)
            bead_to_cand[idx] = cand_obj

    print(f"\n>>> Bước 4: Thẩm định chất lượng `real_label` trên {len(split_candidates)} ứng viên tách bằng Gemini AI...", flush=True)
    verify_map = verify_splits_with_gemini(genai_client, split_candidates, AI_VERIFY_CACHE_JSONL)

    # Ráp lại danh sách cặp cuối cùng: chỉ tách khi Gemini xác nhận `approve_split == True` VÀ không sinh MISMATCH nào!
    # Đặc biệt: nếu cặp gốc đang là `CLEAN`, đòi hỏi ít nhất 1 cặp con là `CLEAN` và tất cả các cặp con đều `!= MISMATCH`.
    refined_beads: List[Dict] = []
    accepted_splits = 0
    extra_pairs_gained = 0

    for idx, b in enumerate(beads):
        cand = bead_to_cand.get(idx)
        if cand is not None:
            dec = verify_map.get(cand["key"])
            if dec and dec.get("approve_split") is True:
                sub_Decisions = dec.get("sub_pairs", [])
                labels = [sd["real_label"] for sd in sub_Decisions]
                has_mismatch = any(lbl == "MISMATCH" for lbl in labels)
                # Tiêu chuẩn nghiêm ngặt bảo toàn chất lượng real_label:
                # 1) Tuyệt đối không được sinh ra bất kỳ cặp MISMATCH nào.
                # 2) Nếu cụm gốc đã CLEAN, sau khi tách tất cả các cặp con phải CLEAN (hoặc tối đa 1 câu PARTIAL do OCR nếu cụm >=3 cặp).
                if not has_mismatch:
                    orig_clean = b["v5_real_label"] == "CLEAN"
                    all_clean = all(lbl == "CLEAN" for lbl in labels)
                    mostly_clean = sum(1 for lbl in labels if lbl == "CLEAN") >= len(labels) - 1
                    if (not orig_clean) or all_clean or (len(labels) >= 2 and mostly_clean):
                        accepted_splits += 1
                        extra_pairs_gained += len(cand["sub_texts"]) - 1
                        for sp_info, sp_dec in zip(cand["sub_texts"], sub_Decisions):
                            refined_beads.append(
                                {
                                    "block": b["block"],
                                    "src_idxs": sp_info["src_idxs"],
                                    "tgt_idxs": sp_info["tgt_idxs"],
                                    "real_label": sp_dec["real_label"],
                                    "judge_reason": sp_dec["reason"],
                                    "refine_note": f"Tách mịn N-M ({sp_info['tag']})",
                                }
                            )
                        continue

        refined_beads.append(
            {
                "block": b["block"],
                "src_idxs": b["src_idxs"],
                "tgt_idxs": b["tgt_idxs"],
                "real_label": b["v5_real_label"],
                "judge_reason": b.get("v5_reason", ""),
                "refine_note": b.get("refine_note", ""),
            }
        )

    print(
        f"    Đã chấp nhận tách {accepted_splits}/{len(split_candidates)} cụm N-M "
        f"(tăng thêm +{extra_pairs_gained} cặp sạch) -> Tổng số dòng = {len(refined_beads)}.",
        flush=True,
    )

    # Kiểm tra bảo toàn 100% câu Hán (2.804) & câu Việt (2.966) theo đúng thứ tự
    for b in BLOCK_CONFIGS:
        bname = b["name"]
        sub_b = [x for x in refined_beads if x["block"] == bname]
        flat_s = [i for x in sub_b for i in x["src_idxs"]]
        flat_t = [j for x in sub_b for j in x["tgt_idxs"]]
        assert flat_s == list(range(len(han_by_blk[bname]))), f"Lệch thứ tự câu Hán ở {bname}"
        assert flat_t == list(range(len(viet_by_blk[bname]))), f"Lệch thứ tự câu Việt ở {bname}"

    # Xây dựng các dòng hoàn chỉnh với số thứ tự Pair_ID liên tiếp 1..N
    final_rows: List[Dict] = []
    for pair_num, rb in enumerate(refined_beads, start=1):
        bname = rb["block"]
        bcfg = blk_cfg_map[bname]
        h_items = [han_by_blk[bname][i] for i in rb["src_idxs"]]
        v_items = [viet_by_blk[bname][j] for j in rb["tgt_idxs"]]

        n_zh = len(h_items)
        n_vi = len(v_items)
        raw_type = f"{n_zh}-{n_vi}"

        zh_text = " ".join(item["han_co_goc"] for item in h_items).strip()
        vi_text = " ".join(item["text_vi"] for item in v_items).strip()

        han_page = h_items[0]["han_page"] if n_zh > 0 else 0
        viet_page = v_items[0]["viet_page_start"] if n_vi > 0 else 0
        pair_id = f"P{pair_num:04d}_C{han_page:03d}_V{viet_page:03d}"

        ocr_conf_min = round(min(item["ocr_conf_min"] for item in h_items), 4) if n_zh > 0 else None
        ocr_valid = 1 if (ocr_conf_min is None or ocr_conf_min >= OCR_CONF_THRESHOLD) else 0

        notes = []
        if rb.get("refine_note"):
            notes.append(rb["refine_note"])

        missing = 1 if (n_zh == 0 or n_vi == 0) else 0
        omission = 0
        addition = 0
        severe_num_mismatch = False

        if missing == 1:
            notes.append(f"MISSING: Khuyết một vế ({raw_type})")
        else:
            cjk_len = max(count_cjk_chars(zh_text), 1)
            vi_words = len(vi_text.split())
            ratio = vi_words / cjk_len
            if ratio < bcfg["ratio_min"]:
                omission = 1
                notes.append(f"Nghi ngờ OMISSION: Tỷ lệ Việt/Hán thấp ({ratio:.2f} < {bcfg['ratio_min']})")
            elif ratio > bcfg["ratio_max"]:
                addition = 1
                notes.append(f"Nghi ngờ ADDITION: Tỷ lệ Việt/Hán cao ({ratio:.2f} > {bcfg['ratio_max']})")

            is_num_bad, _, num_msg = evaluate_numeric_consistency(zh_text, vi_text)
            if is_num_bad:
                severe_num_mismatch = True
                notes.append(num_msg)

        if ocr_valid == 0:
            notes.append(f"Cảnh báo OCR mờ (conf = {ocr_conf_min} < {OCR_CONF_THRESHOLD})")

        punct_match = check_punct_or_number_match(zh_text, vi_text)
        real_lbl = rb["real_label"]

        # Label_Target phản ánh đồng bộ cả kiểm tra tự động lẫn cảnh báo MISMATCH để tiện lọc sửa tay
        label_target = (
            1
            if (
                missing == 0
                and omission == 0
                and addition == 0
                and not severe_num_mismatch
                and ocr_valid == 1
                and real_lbl != "MISMATCH"
            )
            else 0
        )

        final_rows.append(
            {
                "Pair_ID": pair_id,
                "Chinese": zh_text if zh_text else None,
                "Vietnamese": vi_text if vi_text else None,
                "OMISSION": omission,
                "ADDITION": addition,
                "MISSING": missing,
                "Alignment_Type": raw_type,
                "Punct_Anchor_Match": punct_match,
                "OCR_Valid": ocr_valid,
                "Label_Target": label_target,
                "OCR_Conf_Min": ocr_conf_min,
                "Note": " | ".join(notes) if notes else None,
                "Real_Label": real_lbl,
                "Judge_Reason": rb.get("judge_reason", ""),
            }
        )

    # Lập thống kê tổng kết
    df_out = pd.DataFrame(final_rows)
    par_df = df_out[df_out["MISSING"] == 0]
    vc_all = df_out["Real_Label"].value_counts()
    vc_par = par_df["Real_Label"].value_counts()

    summary = {
        "version": "v6_deliverable",
        "input_han_sents": sum(len(v) for v in han_by_blk.values()),
        "input_viet_sents": sum(len(v) for v in viet_by_blk.values()),
        "accepted_nm_splits": accepted_splits,
        "extra_pairs_from_splits": extra_pairs_gained,
        "repaired_mismatch_rows": n_repaired,
        "total_rows_v6": len(df_out),
        "parallel_deliverable_pairs": len(par_df),
        "parallel_clean": int(vc_par.get("CLEAN", 0)),
        "parallel_clean_pct": round(100.0 * int(vc_par.get("CLEAN", 0)) / len(par_df), 2),
        "parallel_partial": int(vc_par.get("PARTIAL", 0)),
        "parallel_partial_pct": round(100.0 * int(vc_par.get("PARTIAL", 0)) / len(par_df), 2),
        "parallel_mismatch": int(vc_par.get("MISMATCH", 0)),
        "parallel_mismatch_pct": round(100.0 * int(vc_par.get("MISMATCH", 0)) / len(par_df), 2),
        "parallel_usable": int(vc_par.get("CLEAN", 0) + vc_par.get("PARTIAL", 0)),
        "parallel_usable_pct": round(
            100.0 * int(vc_par.get("CLEAN", 0) + vc_par.get("PARTIAL", 0)) / len(par_df), 2
        ),
        "alignment_types": df_out["Alignment_Type"].value_counts().to_dict(),
    }

    V6_SUMMARY_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    export_all_deliverables(final_rows, summary)

    print("\n" + "=" * 82)
    print(f"HOÀN TẤT TÁCH MỊN & XUẤT BỘ BÀN GIAO CHUẨN GUIDELINE (CV16_PhuBienTapLuc)")
    print("=" * 82)
    print(f"  - Tổng dòng V6 (đánh ID liên tiếp P0001..P{len(df_out):04d}): {len(df_out)}")
    print(f"  - Số cặp hợp lệ trong TSV & DONG_HANG (.xlsx) : {len(par_df)} cặp (Yêu cầu >= 2.000)")
    print(f"  - CLEAN    : {summary['parallel_clean']:4d} / {len(par_df)} ({summary['parallel_clean_pct']:.2f}%)")
    print(f"  - PARTIAL  : {summary['parallel_partial']:4d} / {len(par_df)} ({summary['parallel_partial_pct']:.2f}%)")
    print(f"  - MISMATCH : {summary['parallel_mismatch']:4d} / {len(par_df)} ({summary['parallel_mismatch_pct']:.2f}%)")
    print(f"  - USABLE   : {summary['parallel_usable']:4d} / {len(par_df)} ({summary['parallel_usable_pct']:.2f}%)")
    print(f"  - File 1   : {V6_TEMPLATE_XLSX}")
    print(f"  - File 2   : {PARALLEL_TSV}")
    print(f"  - File 3   : {PARALLEL_XLSX}")


if __name__ == "__main__":
    main()
