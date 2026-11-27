# -*- coding: utf-8 -*-
"""
Chấm tự động `Real_Label` (CLEAN / PARTIAL / MISMATCH) bằng Gemini API (LLM-as-a-Judge)
với tham số CLI tổng quát (`--input`, `--output`, `--checkpoint`, `--model`, `--limit`, `--batch-size`, `--sleep`)
và cơ chế tự động fallback/retry khi gặp lỗi 404 (model không khả dụng), 503 (quá tải) hoặc 429 (chạm giới hạn RPM).

Ví dụ chạy cho v5:
  python 04_dong_hang/scripts/judge_real_label.py ^
      --input 04_dong_hang/output/v5/PhuBienTapLuc_Alignment_V5.xlsx ^
      --output 04_dong_hang/output/v5/PhuBienTapLuc_Alignment_V5_Judged.xlsx ^
      --checkpoint 04_dong_hang/output/v5/judge_checkpoint.jsonl
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Literal, Optional

import pandas as pd
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from tqdm import tqdm

# ==============================================================================
# 1. CẤU HÌNH MẶC ĐỊNH & DANH SÁCH MODEL FREE TIER FALLBACK
# ==============================================================================
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]

DEFAULT_INPUT = PROJECT_ROOT / "04_dong_hang" / "output" / "v5" / "PhuBienTapLuc_Alignment_V5.xlsx"
DEFAULT_OUTPUT = PROJECT_ROOT / "04_dong_hang" / "output" / "v5" / "PhuBienTapLuc_Alignment_V5_Judged.xlsx"
DEFAULT_CHECKPOINT = PROJECT_ROOT / "04_dong_hang" / "output" / "v5" / "judge_checkpoint.jsonl"

DEFAULT_MODEL = "gemini-3.5-flash-lite"
FALLBACK_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.8-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash",
]

DEFAULT_BATCH_SIZE = 20
DEFAULT_SLEEP_SEC = 4.5
MAX_RETRIES_PER_MODEL = 4


# ==============================================================================
# 2. SCHEMA JSON ĐẦU RA (GIỮ NGUYÊN CHUẨN V4: CLEAN / PARTIAL / MISMATCH)
# ==============================================================================
class RowJudgment(BaseModel):
    row_idx: int = Field(description="Chỉ số dòng gốc trong bảng")
    real_label: Literal["CLEAN", "PARTIAL", "MISMATCH"] = Field(
        description=(
            "CLEAN: Hán và Việt dịch đúng trọn vẹn của nhau, ranh giới câu khớp sạch. "
            "PARTIAL: Khớp nội dung lõi nhưng trượt ranh giới nhẹ (một vế dính thừa/thiếu 1 mệnh đề sang câu liền kề). "
            "MISMATCH: Lệch nội dung hoàn toàn, khuyết một vế, hoặc ghép nhầm sang đoạn khác."
        )
    )
    reason: str = Field(description="Giải thích ngắn gọn tối đa 15 từ bằng tiếng Việt")


class BatchJudgmentResponse(BaseModel):
    results: List[RowJudgment]


SYSTEM_INSTRUCTION = """Bạn là chuyên gia Hán Nôm và NLP chuyên đánh giá chất lượng gióng hàng song ngữ (sentence alignment) tác phẩm Phủ biên tạp lục (chữ Hán cổ OCR - tiếng Việt).
Lưu ý: Chữ Hán có thể chứa một số lỗi OCR mặt chữ nhẹ, hãy đánh giá dựa trên ngữ cảnh, con số, địa danh, chức quan và mạch ý thực tế.
Quy tắc gán nhãn nghiêm ngặt:
- CLEAN: Hai vế dịch đúng trọn vẹn của nhau, không bị dính thừa hoặc hụt mất mệnh đề sang câu trước/sau.
- PARTIAL: Phần lõi khớp nghĩa nhau, nhưng có trượt ranh giới câu (một bên bị dính thêm hoặc thiếu 1 cụm/mệnh đề của câu kế cận).
- MISMATCH: Ghép sai hoàn toàn (nội dung không liên quan), hoặc khuyết hẳn một vế (0-1 / 1-0), hoặc bản Việt là phiên âm Hán-Việt chứ không phải bản dịch.
Trả về đúng đủ số lượng dòng theo `row_idx` đã cung cấp."""


# ==============================================================================
# 3. QUẢN LÝ CHECKPOINT AN TOÀN & CHỌN MODEL TỰ ĐỘNG FALLBACK
# ==============================================================================
def load_checkpoint(path: Path) -> Dict[int, dict]:
    done: Dict[int, dict] = {}
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, start=1):
                raw = line.strip()
                if not raw:
                    continue
                try:
                    rec = json.loads(raw)
                    if "row_idx" in rec and rec.get("real_label") in ("CLEAN", "PARTIAL", "MISMATCH"):
                        done[int(rec["row_idx"])] = rec
                except json.JSONDecodeError:
                    print(f"[Cảnh báo] Bỏ qua dòng checkpoint lỗi JSON tại dòng {line_num}.", flush=True)
    return done


def append_checkpoint(path: Path, records: List[dict]) -> None:
    if not records:
        return
    if not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def build_candidate_models(preferred_model: str) -> List[str]:
    candidates = [m.strip() for m in preferred_model.split(",") if m.strip()]
    for fb in FALLBACK_MODELS:
        if fb not in candidates:
            candidates.append(fb)
    return candidates


class ModelSelector:
    """Giữ trạng thái model đang hoạt động tốt và tự động chuyển model khi gặp 404 / 503 liên tiếp."""

    def __init__(self, preferred_model: str):
        self.candidates = build_candidate_models(preferred_model)
        self.active_idx = 0
        self.dead_404_models = set()

    @property
    def current_model(self) -> str:
        return self.candidates[self.active_idx]

    def mark_404_and_advance(self, bad_model: str) -> str:
        self.dead_404_models.add(bad_model)
        for idx, m in enumerate(self.candidates):
            if m not in self.dead_404_models:
                self.active_idx = idx
                return m
        raise RuntimeError(f"Tất cả các model ứng viên đều trả về 404/không tồn tại: {self.candidates}")

    def next_available_after_overload(self) -> str:
        for step in range(1, len(self.candidates) + 1):
            nxt_idx = (self.active_idx + step) % len(self.candidates)
            cand = self.candidates[nxt_idx]
            if cand not in self.dead_404_models:
                self.active_idx = nxt_idx
                return cand
        return self.current_model


def is_404_error(err: Exception) -> bool:
    msg = str(err).lower()
    return "404" in msg or "not_found" in msg or "not found" in msg or "is not supported" in msg


def is_overload_or_rate_error(err: Exception) -> bool:
    msg = str(err).lower()
    return (
        "503" in msg
        or "unavailable" in msg
        or "overloaded" in msg
        or "429" in msg
        or "resource_exhausted" in msg
        or "quota" in msg
        or "500" in msg
        or "deadline" in msg
    )


def judge_batch(
    client: genai.Client,
    selector: ModelSelector,
    batch_df: pd.DataFrame,
) -> List[dict]:
    expected_indices = [int(i) for i in batch_df.index]
    lines = []
    for idx, r in batch_df.iterrows():
        zh = str(r["Chinese"]) if pd.notna(r["Chinese"]) else "<MISSING>"
        vi = str(r["Vietnamese"]) if pd.notna(r["Vietnamese"]) else "<MISSING>"
        lines.append(f"[row_idx={idx} | {r['Pair_ID']}]\nZH: {zh}\nVI: {vi}")

    prompt = "Hãy đánh giá từng cặp câu dưới đây:\n\n" + "\n\n".join(lines)

    total_attempts = max(8, len(selector.candidates) * MAX_RETRIES_PER_MODEL)
    overload_streak = 0

    for attempt in range(1, total_attempts + 1):
        model_name = selector.current_model
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0.0,
                    response_mime_type="application/json",
                    response_schema=BatchJudgmentResponse,
                ),
            )
            parsed = BatchJudgmentResponse.model_validate_json(response.text)
            by_idx = {int(item.row_idx): item.model_dump() for item in parsed.results}

            # Đảm bảo trả về đủ tất cả row_idx trong lô; nếu thiếu cá biệt dòng nào thì gọi bù riêng
            missing_in_resp = [i for i in expected_indices if i not in by_idx]
            if missing_in_resp and len(parsed.results) == len(expected_indices):
                # Trường hợp hiếm model đánh lại số thứ tự 0..k-1 thay vì row_idx gốc
                by_idx = {}
                for real_i, item in zip(expected_indices, parsed.results):
                    d = item.model_dump()
                    d["row_idx"] = real_i
                    by_idx[real_i] = d
                missing_in_resp = []

            if missing_in_resp:
                sub_records = judge_batch(client, selector, batch_df.loc[missing_in_resp])
                for rec in sub_records:
                    by_idx[int(rec["row_idx"])] = rec

            return [by_idx[i] for i in expected_indices]

        except Exception as e:
            if is_404_error(e):
                new_m = selector.mark_404_and_advance(model_name)
                print(
                    f"\n[Fallback 404] Model `{model_name}` không khả dụng ({e}). Chuyển sang `{new_m}`...",
                    flush=True,
                )
                continue

            overload_streak += 1
            if is_overload_or_rate_error(e) and overload_streak >= 2:
                old_m = model_name
                new_m = selector.next_available_after_overload()
                overload_streak = 0
                wait_sec = min(30, 4 * attempt)
                print(
                    f"\n[Fallback 503/429] Model `{old_m}` quá tải/giới hạn ({e}). "
                    f"Đợi {wait_sec}s rồi thử sang `{new_m}`...",
                    flush=True,
                )
                time.sleep(wait_sec)
            else:
                wait_sec = min(60, 5 * (2 ** min(attempt - 1, 3)))
                print(
                    f"\n[Cảnh báo] Lỗi API trên `{model_name}` (lần {attempt}/{total_attempts}): {e}. "
                    f"Đợi {wait_sec}s...",
                    flush=True,
                )
                time.sleep(wait_sec)

    raise RuntimeError(
        "Gọi API thất bại sau khi đã thử retry và fallback qua các model. "
        "Toàn bộ kết quả trước đó đã được lưu an toàn trong checkpoint."
    )


def get_block(pair_id: str, idx: int, total_len: int) -> str:
    """Nhận diện khối Cap_01 / Cap_02_V / Cap_02_VI từ số trang Việt trong Pair_ID."""
    m = re.search(r"_V(\d+)$", str(pair_id))
    vp = int(m.group(1)) if m else 0
    if 186 <= vp <= 251:
        return "Cap_01"
    if 1 <= vp <= 105:
        return "Cap_02_V"
    if 405 <= vp <= 439:
        return "Cap_02_VI"
    # Dự phòng cho dòng khuyết vế Việt (V000) dựa trên vị trí tương đối
    ratio = idx / max(total_len, 1)
    if ratio < 0.40:
        return "Cap_01"
    if ratio < 0.78:
        return "Cap_02_V"
    return "Cap_02_VI"


# ==============================================================================
# 4. LUỒNG CHẠY CHÍNH & BÁO CÁO KẾT QUẢ
# ==============================================================================
def resolve_path(p_str: str) -> Path:
    p = Path(p_str)
    return p if p.is_absolute() else (PROJECT_ROOT / p).resolve()


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Chấm tự động Real_Label (CLEAN / PARTIAL / MISMATCH) bằng Gemini LLM-as-a-Judge."
    )
    parser.add_argument(
        "--input",
        type=str,
        default=str(DEFAULT_INPUT),
        help="Đường dẫn file Excel gióng hàng đầu vào (.xlsx)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Đường dẫn file Excel kết quả đầu ra (.xlsx). Mặc định thêm hậu tố `_Judged.xlsx` cạnh file input.",
    )
    parser.add_argument(
        "--checkpoint",
        type=str,
        default=None,
        help="Đường dẫn file checkpoint (.jsonl). Mặc định đặt `judge_checkpoint.jsonl` cùng thư mục output.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        help=f"Tên model ưu tiên (hoặc danh sách phân tách dấu phẩy). Mặc định: {DEFAULT_MODEL}",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Giới hạn số dòng đầu tiên để test nhanh",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Số cặp câu mỗi request API (mặc định: {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=DEFAULT_SLEEP_SEC,
        help=f"Thời gian nghỉ (giây) giữa các lô gọi API (mặc định: {DEFAULT_SLEEP_SEC})",
    )
    args = parser.parse_args()

    input_xlsx = resolve_path(args.input)
    if not input_xlsx.exists():
        raise FileNotFoundError(f"Không tìm thấy file đầu vào: {input_xlsx}")

    if args.output:
        output_xlsx = resolve_path(args.output)
    else:
        output_xlsx = input_xlsx.with_name(f"{input_xlsx.stem}_Judged.xlsx")

    if args.checkpoint:
        checkpoint_jsonl = resolve_path(args.checkpoint)
    else:
        checkpoint_jsonl = output_xlsx.parent / "judge_checkpoint.jsonl"

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("Chưa đặt biến môi trường GEMINI_API_KEY.")

    client = genai.Client(api_key=api_key)
    selector = ModelSelector(args.model)

    xl = pd.ExcelFile(input_xlsx)
    sheet = "Alignment_Dataset" if "Alignment_Dataset" in xl.sheet_names else xl.sheet_names[0]
    df = pd.read_excel(input_xlsx, sheet_name=sheet)
    target_df = df.iloc[: args.limit].copy() if args.limit else df.copy()

    done_map = load_checkpoint(checkpoint_jsonl)
    pending_indices = [int(i) for i in target_df.index if int(i) not in done_map]

    print(
        f"Input: {input_xlsx}\n"
        f"Output: {output_xlsx}\n"
        f"Checkpoint: {checkpoint_jsonl}\n"
        f"Model ưu tiên: {selector.current_model} (chuỗi fallback: {selector.candidates})\n"
        f"Tổng dòng mục tiêu: {len(target_df)} | Đã có trong checkpoint: {len(target_df) - len(pending_indices)} | "
        f"Cần chấm mới: {len(pending_indices)}",
        flush=True,
    )

    for start in tqdm(range(0, len(pending_indices), args.batch_size), desc="Chấm real_label"):
        batch_idxs = pending_indices[start : start + args.batch_size]
        batch_df = target_df.loc[batch_idxs]

        # Xử lý trực tiếp các dòng MISSING (khuyết một vế) không tốn token API
        if "MISSING" in batch_df.columns:
            missing_mask = batch_df["MISSING"] == 1
        else:
            missing_mask = batch_df["Chinese"].isna() | batch_df["Vietnamese"].isna()

        auto_records = []
        for idx in batch_df[missing_mask].index:
            rec = {
                "row_idx": int(idx),
                "real_label": "MISMATCH",
                "reason": "Khuyết một vế (MISSING)",
            }
            auto_records.append(rec)
            done_map[int(idx)] = rec

        api_df = batch_df[~missing_mask]
        api_records = judge_batch(client, selector, api_df) if len(api_df) > 0 else []
        for rec in api_records:
            done_map[int(rec["row_idx"])] = rec

        append_checkpoint(checkpoint_jsonl, auto_records + api_records)
        if len(api_df) > 0 and (start + args.batch_size < len(pending_indices)):
            time.sleep(args.sleep)

    # Gắn kết quả vào DataFrame và xuất Excel (giữ nguyên thứ tự cột chuẩn của v4)
    target_df["Real_Label"] = [done_map.get(int(i), {}).get("real_label", "UNKNOWN") for i in target_df.index]
    target_df["Judge_Reason"] = [done_map.get(int(i), {}).get("reason", "") for i in target_df.index]
    target_df["Block"] = [get_block(r["Pair_ID"], idx, len(target_df)) for idx, r in target_df.iterrows()]

    if not output_xlsx.parent.exists():
        output_xlsx.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_xlsx, engine="openpyxl") as writer:
        target_df.drop(columns=["Block"]).to_excel(writer, sheet_name="Alignment_Dataset", index=False)

    # In báo cáo thống kê
    print("\n" + "=" * 78)
    print(f"KẾT QUẢ CHẤM `Real_Label` TRÊN {len(target_df)} DÒNG (Model thực chạy: {selector.current_model})")
    print("=" * 78)
    vc = target_df["Real_Label"].value_counts()
    for lbl in ["CLEAN", "PARTIAL", "MISMATCH"]:
        cnt = int(vc.get(lbl, 0))
        print(f"  {lbl:8s}: {cnt:4d} / {len(target_df)} ({cnt/len(target_df):.2%})")
    usable = int(vc.get("CLEAN", 0) + vc.get("PARTIAL", 0))
    print(f"  USABLE  : {usable:4d} / {len(target_df)} ({usable/len(target_df):.2%})")

    if "Label_Target" in target_df.columns:
        print("\n--- TRONG NHÓM `Label_Target == 1` ---")
        lt1 = target_df[target_df["Label_Target"] == 1]
        if len(lt1) > 0:
            vc1 = lt1["Real_Label"].value_counts()
            for lbl in ["CLEAN", "PARTIAL", "MISMATCH"]:
                cnt = int(vc1.get(lbl, 0))
                print(f"  {lbl:8s}: {cnt:4d} / {len(lt1)} ({cnt/len(lt1):.2%})")
            u1 = int(vc1.get("CLEAN", 0) + vc1.get("PARTIAL", 0))
            print(f"  USABLE  : {u1:4d} / {len(lt1)} ({u1/len(lt1):.2%})")

    print("\n--- PHÂN RÃ THEO TỪNG KHỐI (Block) ---")
    ct = pd.crosstab(target_df["Block"], target_df["Real_Label"], normalize="index") * 100
    print(ct.round(2).to_string())
    print(f"\nĐã lưu file kết quả tại: {output_xlsx}", flush=True)


if __name__ == "__main__":
    main()
