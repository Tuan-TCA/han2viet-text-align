# -*- coding: utf-8 -*-
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
P_XLSX = ROOT / "04_dong_hang" / "CV16_PhuBienTapLuc_parallel.xlsx"
OLD_XLSX = ROOT / "04_dong_hang" / "output" / "v6_1" / "PhuBienTapLuc_Alignment_V6_1_Independent_Judged.xlsx"
OUT_DIR = ROOT / "04_dong_hang" / "output" / "manual_edit_eval"
BLIND_OUT = OUT_DIR / "CV16_Manual_Edited_BlindInput.xlsx"

ad = pd.read_excel(P_XLSX, sheet_name="Alignment_Dataset", skiprows=[1])
dh = pd.read_excel(P_XLSX, sheet_name="DONG_HANG")
old = pd.read_excel(OLD_XLSX)

print("Alignment_Dataset rows:", len(ad), "cols:", list(ad.columns))
print("DONG_HANG rows:", len(dh))

dh_diffs = 0
for i in range(min(len(dh), len(old))):
    if str(dh.iloc[i]["Hán"]).strip() != str(old.iloc[i]["Chinese"]).strip() or str(dh.iloc[i]["Việt"]).strip() != str(old.iloc[i]["Vietnamese"]).strip():
        dh_diffs += 1
print("DONG_HANG diffs vs old v6.1:", dh_diffs, "| len diff:", len(dh) - len(old))

# Drop trailing completely empty rows if Excel saved empty formatting rows, or check what they are
empty_both = ad[ad["Chinese"].isna() & ad["Vietnamese"].isna() & ad["Pair_ID"].isna()]
print("Completely empty rows (Pair_ID, Chinese, Vietnamese all NaN):", len(empty_both), empty_both.index.tolist())

old_pairs = set(
    (str(r["Chinese"]).strip() if pd.notna(r["Chinese"]) else "", str(r["Vietnamese"]).strip() if pd.notna(r["Vietnamese"]) else "")
    for _, r in old.iterrows()
)

changed_rows = []
for idx, r in ad.iterrows():
    z = str(r["Chinese"]).strip() if pd.notna(r["Chinese"]) else ""
    v = str(r["Vietnamese"]).strip() if pd.notna(r["Vietnamese"]) else ""
    if (z, v) not in old_pairs:
        changed_rows.append((idx + 3, r["Pair_ID"], z[:45], v[:55]))

print(f"Total changed/new rows in Alignment_Dataset vs old v6.1: {len(changed_rows)}")
for item in changed_rows[:30]:
    print("  ExcelRow", item[0], "| Pair_ID:", item[1], "| ZH:", item[2], "| VI:", item[3])

# Prepare clean BlindInput (excluding completely blank Excel trailing rows if any, while keeping 1-0 / 0-1 rows)
valid_ad = ad[~(ad["Chinese"].isna() & ad["Vietnamese"].isna() & ad["Pair_ID"].isna())].copy()
# Fill synthetic Pair_ID ONLY in the temporary BlindInput copy if user inserted a row without Pair_ID so judge_real_label.py can format prompt cleanly
filled_pids = []
for idx, r in valid_ad.iterrows():
    pid = str(r["Pair_ID"]).strip() if pd.notna(r["Pair_ID"]) and str(r["Pair_ID"]).strip() else f"INSERTED_EXCEL_ROW_{idx+3}"
    filled_pids.append(pid)
valid_ad["Excel_Row_In_Source"] = valid_ad.index + 3
valid_ad["Orig_Pair_ID"] = valid_ad["Pair_ID"]
valid_ad["Pair_ID"] = filled_pids
valid_ad["MISSING"] = [1 if (pd.isna(r["Chinese"]) or not str(r["Chinese"]).strip() or pd.isna(r["Vietnamese"]) or not str(r["Vietnamese"]).strip()) else 0 for _, r in valid_ad.iterrows()]

OUT_DIR.mkdir(parents=True, exist_ok=True)
cols_keep = [c for c in valid_ad.columns if not str(c).startswith("Unnamed") and c not in ("Real_Label", "Judge_Reason")]
valid_ad[cols_keep].to_excel(BLIND_OUT, sheet_name="Alignment_Dataset", index=False)
print(f"Saved BlindInput with {len(valid_ad)} rows to {BLIND_OUT}")
