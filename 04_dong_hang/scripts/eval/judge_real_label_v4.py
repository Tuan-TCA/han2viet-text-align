# -*- coding: utf-8 -*-
"""
Cháº¥m tá»± Ä‘á»™ng `real_label` (CLEAN / PARTIAL / MISMATCH) báº±ng Gemini API (LLM-as-a-Judge)
trÃªn file `04_dong_hang/output/v4/PhuBienTapLuc_Alignment_Full.xlsx`.

CÃ¡ch cháº¡y:
  1. Test nhanh 100 dÃ²ng Ä‘áº§u:
     python 04_dong_hang/scripts/judge_real_label_v4.py --limit 100
  2. Cháº¡y toÃ n bá»™ file (1.951 dÃ²ng, cÃ³ tá»± Ä‘á»™ng lÆ°u checkpoint):
     python 04_dong_hang/scripts/judge_real_label_v4.py
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import List, Literal

import pandas as pd
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from tqdm import tqdm

# ==============================================================================
# 1. Cáº¤U HÃŒNH
# ==============================================================================
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]

INPUT_XLSX = PROJECT_ROOT / "04_dong_hang" / "output" / "v4" / "PhuBienTapLuc_Alignment_Full.xlsx"
OUTPUT_XLSX = PROJECT_ROOT / "04_dong_hang" / "output" / "v4" / "PhuBienTapLuc_Alignment_Full_Judged.xlsx"
CHECKPOINT_JSONL = PROJECT_ROOT / "04_dong_hang" / "output" / "v4" / "judge_checkpoint.jsonl"

MODEL_NAME = "gemini-3.5-flash-lite"   # Äá»•i sang model free tier khÃ¡c trong AI Studio náº¿u cáº§n
BATCH_SIZE = 20                   # 20 cáº·p/request -> toÃ n bá»™ 1.951 dÃ²ng chá»‰ tá»‘n ~98 request
SLEEP_BETWEEN_BATCHES = 4.5       # GiÃ¢y nghá»‰ giá»¯a cÃ¡c lÃ´ Ä‘á»ƒ khÃ´ng cháº¡m RPM cá»§a Free Tier
MAX_RETRIES = 5


# ==============================================================================
# 2. SCHEMA JSON Äáº¦U RA (STRUCTURED OUTPUT)
# ==============================================================================
class RowJudgment(BaseModel):
    row_idx: int = Field(description="Chá»‰ sá»‘ dÃ²ng gá»‘c trong báº£ng")
    real_label: Literal["CLEAN", "PARTIAL", "MISMATCH"] = Field(
        description=(
            "CLEAN: HÃ¡n vÃ  Viá»‡t dá»‹ch Ä‘Ãºng trá»n váº¹n cá»§a nhau, ranh giá»›i cÃ¢u khá»›p sáº¡ch. "
            "PARTIAL: Khá»›p ná»™i dung lÃµi nhÆ°ng trÆ°á»£t ranh giá»›i nháº¹ (má»™t váº¿ dÃ­nh thá»«a/thiáº¿u 1 má»‡nh Ä‘á» sang cÃ¢u liá»n ká»). "
            "MISMATCH: Lá»‡ch ná»™i dung hoÃ n toÃ n, khuyáº¿t má»™t váº¿, hoáº·c ghÃ©p nháº§m sang Ä‘oáº¡n khÃ¡c."
        )
    )
    reason: str = Field(description="Giáº£i thÃ­ch ngáº¯n gá»n tá»‘i Ä‘a 15 tá»« báº±ng tiáº¿ng Viá»‡t")


class BatchJudgmentResponse(BaseModel):
    results: List[RowJudgment]


SYSTEM_INSTRUCTION = """Báº¡n lÃ  chuyÃªn gia HÃ¡n NÃ´m vÃ  NLP chuyÃªn Ä‘Ã¡nh giÃ¡ cháº¥t lÆ°á»£ng giÃ³ng hÃ ng song ngá»¯ (sentence alignment) tÃ¡c pháº©m Phá»§ biÃªn táº¡p lá»¥c (chá»¯ HÃ¡n cá»• OCR - tiáº¿ng Viá»‡t).
LÆ°u Ã½: Chá»¯ HÃ¡n cÃ³ thá»ƒ chá»©a má»™t sá»‘ lá»—i OCR máº·t chá»¯ nháº¹, hÃ£y Ä‘Ã¡nh giÃ¡ dá»±a trÃªn ngá»¯ cáº£nh, con sá»‘, Ä‘á»‹a danh, chá»©c quan vÃ  máº¡ch Ã½ thá»±c táº¿.
Quy táº¯c gÃ¡n nhÃ£n nghiÃªm ngáº·t:
- CLEAN: Hai váº¿ dá»‹ch Ä‘Ãºng trá»n váº¹n cá»§a nhau, khÃ´ng bá»‹ dÃ­nh thá»«a hoáº·c há»¥t máº¥t má»‡nh Ä‘á» sang cÃ¢u trÆ°á»›c/sau.
- PARTIAL: Pháº§n lÃµi khá»›p nghÄ©a nhau, nhÆ°ng cÃ³ trÆ°á»£t ranh giá»›i cÃ¢u (má»™t bÃªn bá»‹ dÃ­nh thÃªm hoáº·c thiáº¿u 1 cá»¥m/má»‡nh Ä‘á» cá»§a cÃ¢u káº¿ cáº­n).
- MISMATCH: GhÃ©p sai hoÃ n toÃ n (ná»™i dung khÃ´ng liÃªn quan), hoáº·c khuyáº¿t háº³n má»™t váº¿ (0-1 / 1-0), hoáº·c báº£n Viá»‡t lÃ  phiÃªn Ã¢m HÃ¡n-Viá»‡t chá»© khÃ´ng pháº£i báº£n dá»‹ch.
Tráº£ vá» Ä‘Ãºng Ä‘á»§ sá»‘ lÆ°á»£ng dÃ²ng theo `row_idx` Ä‘Ã£ cung cáº¥p."""


# ==============================================================================
# 3. HÃ€M Gá»ŒI API & CHECKPOINT
# ==============================================================================
def load_checkpoint(path: Path) -> dict:
    done = {}
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rec = json.loads(line)
                    done[int(rec["row_idx"])] = rec
    return done


def append_checkpoint(path: Path, records: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def judge_batch(client: genai.Client, batch_df: pd.DataFrame) -> List[dict]:
    lines = []
    for idx, r in batch_df.iterrows():
        zh = str(r["Chinese"]) if pd.notna(r["Chinese"]) else "<MISSING>"
        vi = str(r["Vietnamese"]) if pd.notna(r["Vietnamese"]) else "<MISSING>"
        lines.append(f"[row_idx={idx} | {r['Pair_ID']}]\nZH: {zh}\nVI: {vi}")

    prompt = "HÃ£y Ä‘Ã¡nh giÃ¡ tá»«ng cáº·p cÃ¢u dÆ°á»›i Ä‘Ã¢y:\n\n" + "\n\n".join(lines)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0.0,
                    response_mime_type="application/json",
                    response_schema=BatchJudgmentResponse,
                ),
            )
            parsed = BatchJudgmentResponse.model_validate_json(response.text)
            return [item.model_dump() for item in parsed.results]
        except Exception as e:
            wait_sec = min(60, 5 * (2 ** (attempt - 1)))
            print(f"\n[Cáº£nh bÃ¡o] Lá»—i API (láº§n {attempt}/{MAX_RETRIES}): {e}. Äá»£i {wait_sec}s...", flush=True)
            time.sleep(wait_sec)

    raise RuntimeError("Gá»i API tháº¥t báº¡i sau nhiá»u láº§n thá»­. Dá»¯ liá»‡u trÆ°á»›c Ä‘Ã³ Ä‘Ã£ Ä‘Æ°á»£c lÆ°u trong checkpoint.")


def get_block(pair_id: str, idx: int) -> str:
    """Há»— trá»£ cáº£ Ä‘á»‹nh dáº¡ng má»›i P0001_C001_V186 vÃ  Ä‘á»‹nh dáº¡ng cÅ© C001_V186."""
    m = re.search(r"_V(\d+)$", str(pair_id))
    vp = int(m.group(1)) if m else 0
    if 186 <= vp <= 251 or (vp == 0 and idx < 776):
        return "Cap_01"
    if (1 <= vp <= 105) or (vp == 0 and 776 <= idx < 1519):
        return "Cap_02_V"
    return "Cap_02_VI"


# ==============================================================================
# 4. LUá»’NG CHáº Y CHÃNH & BÃO CÃO Káº¾T QUáº¢
# ==============================================================================
def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Giá»›i háº¡n sá»‘ dÃ²ng Ä‘áº§u Ä‘á»ƒ test nhanh")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("ChÆ°a Ä‘áº·t biáº¿n mÃ´i trÆ°á»ng GEMINI_API_KEY.")

    client = genai.Client(api_key=api_key)
    df = pd.read_excel(INPUT_XLSX, sheet_name="Alignment_Dataset")
    target_df = df.iloc[: args.limit].copy() if args.limit else df.copy()

    done_map = load_checkpoint(CHECKPOINT_JSONL)
    pending_indices = [i for i in target_df.index if i not in done_map]

    print(f"Tá»•ng dÃ²ng má»¥c tiÃªu: {len(target_df)} | ÄÃ£ cÃ³ trong checkpoint: {len(target_df) - len(pending_indices)} | Cáº§n cháº¥m: {len(pending_indices)}")

    for start in tqdm(range(0, len(pending_indices), BATCH_SIZE), desc="Cháº¥m real_label"):
        batch_idxs = pending_indices[start : start + BATCH_SIZE]
        batch_df = target_df.loc[batch_idxs]

        # Xá»­ lÃ½ trá»±c tiáº¿p cÃ¡c dÃ²ng MISSING (khuyáº¿t váº¿) mÃ  khÃ´ng tá»‘n token API
        missing_mask = batch_df["MISSING"] == 1
        auto_records = []
        for idx in batch_df[missing_mask].index:
            rec = {"row_idx": int(idx), "real_label": "MISMATCH", "reason": "Khuyáº¿t má»™t váº¿ (MISSING)"}
            auto_records.append(rec)
            done_map[int(idx)] = rec

        api_df = batch_df[~missing_mask]
        api_records = judge_batch(client, api_df) if len(api_df) > 0 else []
        for rec in api_records:
            done_map[int(rec["row_idx"])] = rec

        append_checkpoint(CHECKPOINT_JSONL, auto_records + api_records)
        if len(api_df) > 0:
            time.sleep(SLEEP_BETWEEN_BATCHES)

    # Gáº¯n káº¿t quáº£ vÃ o DataFrame vÃ  xuáº¥t Excel
    target_df["Real_Label"] = [done_map.get(i, {}).get("real_label", "UNKNOWN") for i in target_df.index]
    target_df["Judge_Reason"] = [done_map.get(i, {}).get("reason", "") for i in target_df.index]
    target_df["Block"] = [get_block(r["Pair_ID"], i) for i, r in target_df.iterrows()]

    with pd.ExcelWriter(OUTPUT_XLSX, engine="openpyxl") as writer:
        target_df.drop(columns=["Block"]).to_excel(writer, sheet_name="Alignment_Dataset", index=False)

    # In bÃ¡o cÃ¡o thá»‘ng kÃª
    print("\n" + "=" * 75)
    print(f"Káº¾T QUáº¢ CHáº¤M `real_label` TRÃŠN {len(target_df)} DÃ’NG (Model: {MODEL_NAME})")
    print("=" * 75)
    vc = target_df["Real_Label"].value_counts()
    for lbl in ["CLEAN", "PARTIAL", "MISMATCH"]:
        cnt = int(vc.get(lbl, 0))
        print(f"  {lbl:8s}: {cnt:4d} / {len(target_df)} ({cnt/len(target_df):.2%})")
    usable = int(vc.get("CLEAN", 0) + vc.get("PARTIAL", 0))
    print(f"  USABLE  : {usable:4d} / {len(target_df)} ({usable/len(target_df):.2%})")

    print("\n--- TRONG NHÃ“M `Label_Target == 1` ---")
    lt1 = target_df[target_df["Label_Target"] == 1]
    if len(lt1) > 0:
        vc1 = lt1["Real_Label"].value_counts()
        for lbl in ["CLEAN", "PARTIAL", "MISMATCH"]:
            cnt = int(vc1.get(lbl, 0))
            print(f"  {lbl:8s}: {cnt:4d} / {len(lt1)} ({cnt/len(lt1):.2%})")

    print("\n--- PHÃ‚N RÃƒ THEO Tá»ªNG KHá»I (Block) ---")
    ct = pd.crosstab(target_df["Block"], target_df["Real_Label"], normalize="index") * 100
    print(ct.round(2).to_string())
    print(f"\nÄÃ£ lÆ°u file káº¿t quáº£ táº¡i: {OUTPUT_XLSX}")


if __name__ == "__main__":
    main()


