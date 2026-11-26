# -*- coding: utf-8 -*-
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
CLEAN_V3 = ROOT / "03_text_sach" / "output" / "v3"
OUT_V2 = ROOT / "04_dong_hang" / "output" / "v2" / "PhuBienTapLuc_Alignment_Full.xlsx"
OUT_V3 = ROOT / "04_dong_hang" / "output" / "v3" / "PhuBienTapLuc_Alignment_Full.xlsx"

# 1. Kiểm tra toàn vẹn câu Hán đầu vào vs đầu ra v3
print("=" * 80)
print("1. KIỂM TRA TOÀN VẸN CÂU HÁN ĐẦU VÀO (03_text_sach/v3) VS ĐẦU RA (04_dong_hang/v3)")
print("=" * 80)
han_in_total = 0
for fn in ["Cap_01_HAN_clean.jsonl", "Cap_02_V_HAN_clean.jsonl", "Cap_02_VI_HAN_clean.jsonl"]:
    lines = [l for l in (CLEAN_V3 / fn).read_text(encoding="utf-8").splitlines() if l.strip()]
    han_in_total += len(lines)
    print(f"  - {fn}: {len(lines)} câu")

df2 = pd.read_excel(OUT_V2, sheet_name="Alignment_Dataset")
df3 = pd.read_excel(OUT_V3, sheet_name="Alignment_Dataset")

han_out_total = sum(int(t.split("-")[0]) for t in df3["Alignment_Type"].astype(str))
print(f"=> Tổng câu Hán đầu vào v3 : {han_in_total}")
print(f"=> Tổng câu Hán trong Excel v3: {han_out_total} (Chênh lệch: {han_out_total - han_in_total})")

# 2. Bảng so sánh định lượng v2 vs v3
print("\n" + "=" * 80)
print("2. SO SÁNH CHỈ SỐ CHẤT LƯỢNG: v2 VS v3")
print("=" * 80)

def summarize(df: pd.DataFrame, name: str):
    n = len(df)
    l1 = int((df["Label_Target"] == 1).sum())
    pm = int((df["Punct_Anchor_Match"] == 1).sum())
    vc = df["Alignment_Type"].value_counts()
    ext = sum(vc.get(k, 0) for k in ["1-4", "4-1", "0-1", "1-0"])
    print(f"[{name}]")
    print(f"  - Tổng số cặp (total_pairs)     : {n}")
    print(f"  - Label_Target = 1              : {l1} ({l1/n:.2%})")
    print(f"  - Punct_Anchor_Match = 1        : {pm} ({pm/n:.2%})")
    print(f"  - Cặp 1-1                       : {vc.get('1-1', 0)} ({vc.get('1-1', 0)/n:.2%})")
    print(f"  - Nhóm cực đoan (1-4,4-1,0-1,1-0): {ext} ({ext/n:.2%}) -> chi tiết: "
          f"1-4={vc.get('1-4',0)}, 4-1={vc.get('4-1',0)}, 0-1={vc.get('0-1',0)}, 1-0={vc.get('1-0',0)}")

summarize(df2, "VERSION 2 (Baseline)")
print("-" * 40)
summarize(df3, "VERSION 3 (Improved)")

# 3. Kiểm tra độ lệch trang (max_resid & p95) theo từng khối
print("\n" + "=" * 80)
print("3. ĐỘ LỆCH TRANG (PAGE DRIFT) TRÊN TỪNG KHỐI (v2 vs v3)")
print("=" * 80)

def check_drift(df: pd.DataFrame, label: str):
    v = df[df["MISSING"] == 0].copy()
    v["hp"] = v["Pair_ID"].str.slice(1, 4).astype(int)
    v["vp"] = v["Pair_ID"].str.slice(6, 9).astype(int)
    
    def get_blk(vp):
        if 186 <= vp <= 251: return "Cap_01"
        if 1 <= vp <= 105: return "Cap_02_V"
        if 405 <= vp <= 439: return "Cap_02_VI"
        return "Other"
    
    v["blk"] = v["vp"].apply(get_blk)
    print(f"[{label}]")
    for b in ["Cap_01", "Cap_02_V", "Cap_02_VI"]:
        sub = v[v["blk"] == b]
        if len(sub) < 5: continue
        coef = np.polyfit(sub["hp"], sub["vp"], 1)
        res = np.abs(sub["vp"] - np.polyval(coef, sub["hp"]))
        print(f"  - {b:10s}: n={len(sub):4d} | max_resid={res.max():5.2f} trang | p95={np.percentile(res, 95):5.2f} trang")

check_drift(df2, "v2")
check_drift(df3, "v3")

# 4. In 12 mẫu ngẫu nhiên từ v3 để hậu kiểm
print("\n" + "=" * 80)
print("4. 12 MẪU HẬU KIỂM NGẪU NHIÊN TỪ v3")
print("=" * 80)
v3_valid = df3[df3["MISSING"] == 0].copy()
v3_valid["hp"] = v3_valid["Pair_ID"].str.slice(1, 4).astype(int)
v3_valid["vp"] = v3_valid["Pair_ID"].str.slice(6, 9).astype(int)

s_cap1 = v3_valid[(v3_valid["vp"] >= 186) & (v3_valid["vp"] <= 251)].sample(4, random_state=42)
s_cap2v = v3_valid[(v3_valid["vp"] <= 105) & (v3_valid["vp"].between(20, 35) | v3_valid["vp"].between(95, 102))].sample(4, random_state=42)
s_cap2vi = v3_valid[v3_valid["vp"] >= 405].sample(4, random_state=42)

for title, grp in [("CAP_01 (Thuế/Binh chế)", s_cap1), ("CAP_02_V (Thơ văn vùng 20-35 & 95-102)", s_cap2v), ("CAP_02_VI (Địa lý/Sản vật)", s_cap2vi)]:
    print(f"\n--- {title} ---")
    for idx, r in grp.iterrows():
        print(f"[Row {idx} | {r['Pair_ID']} | Type={r['Alignment_Type']} | Label={r['Label_Target']} | Note={r['Note']}]")
        print(f"  ZH: {r['Chinese']}")
        print(f"  VI: {r['Vietnamese']}")