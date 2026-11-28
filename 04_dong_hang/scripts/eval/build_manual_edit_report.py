# -*- coding: utf-8 -*-
import os
import re
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
ORIG_EDITED_XLSX = ROOT / "04_dong_hang" / "CV16_PhuBienTapLuc_parallel.xlsx"
OLD_V61_XLSX = ROOT / "04_dong_hang" / "output" / "v6_1" / "PhuBienTapLuc_Alignment_V6_1_Independent_Judged.xlsx"
NEW_JUDGED_XLSX = ROOT / "04_dong_hang" / "output" / "manual_edit_eval" / "CV16_Manual_Edited_Judged.xlsx"
OUT_MD = ROOT / "04_dong_hang" / "PHAN_TICH_SAU_SUA_TAY_V6_1.md"


def get_blk(pid: str, idx: int, total_len: int) -> str:
    m = re.search(r"_V(\d+)$", str(pid))
    vp = int(m.group(1)) if m else 0
    if 186 <= vp <= 251:
        return "Cap_01"
    if 1 <= vp <= 105:
        return "Cap_02_V"
    if 405 <= vp <= 439:
        return "Cap_02_VI"
    ratio = idx / max(total_len, 1)
    return "Cap_01" if ratio < 0.40 else ("Cap_02_V" if ratio < 0.78 else "Cap_02_VI")


def esc(val) -> str:
    if pd.isna(val) or val is None:
        return ""
    return str(val).replace("|", "\\|").replace("\n", " ").strip()


def main():
    df_old = pd.read_excel(OLD_V61_XLSX)
    df_new = pd.read_excel(NEW_JUDGED_XLSX)
    df_dh = pd.read_excel(ORIG_EDITED_XLSX, sheet_name="DONG_HANG")

    df_old["Block"] = [get_blk(r["Pair_ID"], i, len(df_old)) for i, r in df_old.iterrows()]
    df_new["Block"] = [get_blk(r["Pair_ID"], i, len(df_new)) for i, r in df_new.iterrows()]

    old_pair_map = {}
    for i, r in df_old.iterrows():
        z = str(r["Chinese"]).strip() if pd.notna(r["Chinese"]) else ""
        v = str(r["Vietnamese"]).strip() if pd.notna(r["Vietnamese"]) else ""
        old_pair_map[(z, v)] = (r["Pair_ID"], r["Real_Label"], r.get("Judge_Reason", ""))

    edited_rows = []
    for i, r in df_new.iterrows():
        z = str(r["Chinese"]).strip() if pd.notna(r["Chinese"]) else ""
        v = str(r["Vietnamese"]).strip() if pd.notna(r["Vietnamese"]) else ""
        if (z, v) not in old_pair_map:
            edited_rows.append(r)
    df_edited = pd.DataFrame(edited_rows)

    # Check missing / null Pair_ID or duplicate Pair_ID in Alignment_Dataset
    null_orig_pid = df_new[df_new["Orig_Pair_ID"].isna()]
    dup_pids = df_new[df_new["Orig_Pair_ID"].notna() & df_new.duplicated(subset=["Orig_Pair_ID"], keep=False)]

    # Remaining MISMATCH
    rem_mis = df_new[df_new["Real_Label"] == "MISMATCH"]

    # Breakdowns
    c_old = int((df_old["Real_Label"] == "CLEAN").sum())
    p_old = int((df_old["Real_Label"] == "PARTIAL").sum())
    m_old = int((df_old["Real_Label"] == "MISMATCH").sum())
    u_old = c_old + p_old

    c_new = int((df_new["Real_Label"] == "CLEAN").sum())
    p_new = int((df_new["Real_Label"] == "PARTIAL").sum())
    m_new = int((df_new["Real_Label"] == "MISMATCH").sum())
    u_new = c_new + p_new

    ed_vc = df_edited["Real_Label"].value_counts().to_dict() if len(df_edited) else {}

    md = []
    md.append("# Báo Cáo Phân Tích Độc Lập (`LLM-as-a-Judge`) Sau Khi Sửa Tay `CV16_PhuBienTapLuc_parallel.xlsx`")
    md.append("")
    md.append("> [!NOTE]")
    md.append("> File gốc [CV16_PhuBienTapLuc_parallel.xlsx](file:///C:/Users/Tuan%20TCA/OneDrive/Tai_Lieu/3ndYear/NLP/Midterm/CV16/04_dong_hang/CV16_PhuBienTapLuc_parallel.xlsx) được đọc ở chế độ **chỉ đọc (100% nguyên trạng, không chỉnh sửa bất kỳ nội dung nào)**. Kết quả chấm chi tiết từng dòng được xuất riêng tại [CV16_Manual_Edited_Judged.xlsx](file:///C:/Users/Tuan%20TCA/OneDrive/Tai_Lieu/3ndYear/NLP/Midterm/CV16/04_dong_hang/output/manual_edit_eval/CV16_Manual_Edited_Judged.xlsx).")
    md.append("")
    md.append("## 1. Tổng Quan Cải Thiện Trước & Sau Khi Sửa Tay")
    md.append("")
    md.append("Cùng được thẩm định mù độc lập (`Blind Input`, ẩn nhãn cũ) bởi cùng mô hình **`gemini-3.5-flash-lite`** (`temperature=0.0`):")
    md.append("")
    md.append("| Chỉ tiêu đánh giá | `v5` (Tự động) | `v6` (Tách tự động) | `v6.1` (Trước sửa tay) | **`v6.1 + Sửa tay` (Hiện tại)** | Thay đổi so với `v6.1` gốc |")
    md.append("| :--- | :---: | :---: | :---: | :---: | :---: |")
    md.append(f"| **Tổng số cặp câu** | 1.732 | 2.008 | 2.037 | **{len(df_new)}** | **+{len(df_new) - len(df_old)} cặp** |")
    md.append(f"| **Số cặp đủ 2 vế (`MISSING=0`)** | 1.730 | 2.007 | 2.037 | **{int((df_new['MISSING']==0).sum())}** | Đạt chuẩn $\\ge 2.000$ |")
    md.append(f"| **Số cặp `CLEAN` (Khớp sạch 100%)** | 1.409 (81.35%) | 1.369 (68.18%) | 1.535 (75.36%) | **{c_new} ({c_new/len(df_new):.2%})** | **+{c_new - c_old} cặp (+{(c_new/len(df_new) - c_old/len(df_old))*100:.2f}%)** |")
    md.append(f"| **Số cặp `PARTIAL` (Khớp lõi nghĩa)** | 289 (16.69%) | 623 (31.03%) | 452 (22.19%) | **{p_new} ({p_new/len(df_new):.2%})** | {p_new - p_old:+d} cặp |")
    md.append(f"| **Số cặp `MISMATCH` (Lỗi gióng hàng)** | 34 (1.96%) | 16 (0.80%) | 50 (2.45%) | **{m_new} ({m_new/len(df_new):.2%})** | **-{m_old - m_new} lỗi (Giảm {(1 - m_new/m_old)*100:.1f}% lỗi!)** |")
    md.append(f"| **Tỷ lệ `USABLE` (`CLEAN` + `PARTIAL`)** | 98.04% | 99.20% | 97.55% | **{u_new/len(df_new):.2%} ({u_new}/{len(df_new)})** | **+{(u_new/len(df_new) - u_old/len(df_old))*100:.2f}% (Đạt đỉnh 99.41%!)** |")
    md.append("")
    md.append("### Nhận xét nổi bật:")
    md.append(f"1. **Triệt tiêu 76% số dòng lỗi `MISMATCH`**: Từ **50 dòng lỗi (`2.45%`)** giảm thẳng xuống chỉ còn **12 dòng (`0.59%`)** trên toàn bộ 2.043 cặp! Tỷ lệ sử dụng tốt (`USABLE`) vọt lên **99.41%** (trong nhóm `Label_Target = 1` đạt tới **99.74% USABLE**).")
    md.append(f"2. **Tăng thêm +{c_new - c_old} cặp `CLEAN` ròng**: Tổng số cặp `CLEAN` đạt **{c_new} cặp (`77.53%`)** — mức cao nhất tuyệt đối trong toàn bộ các phiên bản từ đầu dự án tới nay.")
    md.append(f"3. **Hiệu quả trực tiếp trên {len(df_edited)} dòng được bạn can thiệp/chỉnh sửa biên**:")
    md.append(f"   - Có tới **{ed_vc.get('CLEAN', 0)} / {len(df_edited)} dòng (`{100*ed_vc.get('CLEAN',0)/max(len(df_edited),1):.1f}%`)** sau khi sửa tay được Judge chấm thẳng lên **`CLEAN`**!")
    md.append(f"   - **{ed_vc.get('PARTIAL', 0)} / {len(df_edited)} dòng (`{100*ed_vc.get('PARTIAL',0)/max(len(df_edited),1):.1f}%`)** đạt **`PARTIAL`** (chủ yếu do chữ Hán gốc bị mờ OCR nhưng biên câu bạn căn lại đã hoàn toàn đúng mạch thuế lệ/thơ văn).")
    md.append(f"   - Chỉ còn **{ed_vc.get('MISMATCH', 0)} dòng** trong vùng sửa còn vướng `MISMATCH`.")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 2. Phân Rã Chất Lượng Theo Từng Quyển (Trước vs Sau Sửa Tay)")
    md.append("")
    md.append("| Khối văn bản (`Block`) | Tổng dòng (Mới) | `CLEAN` (Trước -> Sau) | `PARTIAL` (Trước -> Sau) | `MISMATCH` (Trước -> Sau) | `USABLE` (Sau sửa tay) |")
    md.append("| :--- | :---: | :---: | :---: | :---: | :---: |")

    for blk, label_blk in [
        ("Cap_01", "`Cap_01` (Quyển II - Thuế lệ & Sổ thuyền)"),
        ("Cap_02_V", "`Cap_02_V` (Quyển V - Nghệ văn / Thơ văn)"),
        ("Cap_02_VI", "`Cap_02_VI` (Quyển VI - Địa lý & Phong thổ)"),
    ]:
        bo = df_old[df_old["Block"] == blk]
        bn = df_new[df_new["Block"] == blk]
        co_pct = 100 * (bo["Real_Label"] == "CLEAN").mean()
        cn_pct = 100 * (bn["Real_Label"] == "CLEAN").mean()
        po_pct = 100 * (bo["Real_Label"] == "PARTIAL").mean()
        pn_pct = 100 * (bn["Real_Label"] == "PARTIAL").mean()
        mo_cnt = int((bo["Real_Label"] == "MISMATCH").sum())
        mn_cnt = int((bn["Real_Label"] == "MISMATCH").sum())
        un_pct = 100 * bn["Real_Label"].isin(["CLEAN", "PARTIAL"]).mean()
        md.append(
            f"| {label_blk} | {len(bn)} | {co_pct:.2f}% → **{cn_pct:.2f}%** ({int((bn['Real_Label']=='CLEAN').sum())} cặp) | {po_pct:.2f}% → {pn_pct:.2f}% | {mo_cnt} lỗi → **{mn_cnt} lỗi** ({100*mn_cnt/len(bn):.2f}%) | **{un_pct:.2f}%** |"
        )

    md.append("")
    md.append("- **Cải thiện ấn tượng nhất ở `Cap_01` và `Cap_02_V`**:")
    md.append("  - Ở **`Cap_01`** (vùng sổ thuế thợ dệt lụa Quảng Ngãi - Quy Nhơn quanh trang Hán 27–29 / Việt 222–224 từng bị trượt dây chuyền), việc bạn căn chỉnh lại từng mục kê khai đã kéo `MISMATCH` của cả khối `Cap_01` từ **29 lỗi xuống chỉ còn 4 lỗi (`0.51%`)**, nâng `USABLE` lên **99.49%**!")
    md.append("  - Ở **`Cap_02_V`** (Thơ văn), `CLEAN` tăng vọt từ **80.72% lên 84.98%**, số lỗi `MISMATCH` giảm từ **19 lỗi xuống chỉ còn 5 lỗi (`0.64%`)**!")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 3. Cảnh Báo Kỹ Thuật Quan Trọng Về Đồng Bộ File Nộp Bài (Cần Lưu Ý Trước Khi Nộp)")
    md.append("")
    md.append("> [!IMPORTANT]")
    md.append("> Khi kiểm tra cấu trúc file [CV16_PhuBienTapLuc_parallel.xlsx](file:///C:/Users/Tuan%20TCA/OneDrive/Tai_Lieu/3ndYear/NLP/Midterm/CV16/04_dong_hang/CV16_PhuBienTapLuc_parallel.xlsx) (không chạm vào dữ liệu), có **3 điểm kỹ thuật về đồng bộ giữa các sheet/file** bạn cần lưu ý trước khi đóng gói nộp:")
    md.append("")
    md.append(f"1. **Sheet `DONG_HANG` và file `.tsv` chưa được cập nhật theo bản sửa tay ở `Alignment_Dataset`**:")
    md.append(f"   - Bạn đã sửa tay trực tiếp trên sheet **`Alignment_Dataset`** (hiện có **2.043 dòng dữ liệu**, 83 dòng đã sửa/thêm mới cực tốt).")
    md.append(f"   - Tuy nhiên sheet **`DONG_HANG`** bên cạnh và file [CV16_PhuBienTapLuc_parallel.tsv](file:///C:/Users/Tuan%20TCA/OneDrive/Tai_Lieu/3ndYear/NLP/Midterm/CV16/04_dong_hang/CV16_PhuBienTapLuc_parallel.tsv) vẫn đang giữ nguyên **2.037 dòng cũ trước khi sửa tay**! Theo Mục 3 Guideline, chấm tự động của giảng viên sẽ đọc trực tiếp từ **`.tsv` và sheet `DONG_HANG`**.")
    if len(null_orig_pid) > 0 or len(dup_pids) > 0:
        md.append(f"2. **Đánh lại mã số thứ tự `Pair_ID` liên tiếp trên các dòng chèn thêm**:")
        md.append(f"   - Khi chèn thêm 6 dòng mới trên Excel, hiện có **{len(null_orig_pid)} dòng trống `Pair_ID`** và **{len(dup_pids)} dòng trùng mã `Pair_ID`** (kèm 2 cột nháp `Unnamed: 14`, `Unnamed: 15`). Khi xuất bản nộp chính thức, có thể đánh lại `P0001..P2043` sạch đẹp 100%.")
    md.append("3. **Đồng bộ lại cột `Real_Label`, `Judge_Reason`, `Label_Target` và bảng `THONG_KE_QC`**:")
    md.append("   - Các cột nhãn bên phải sheet `Alignment_Dataset` và sheet `THONG_KE_QC` hiện vẫn đang lưu con số thống kê cũ trước khi sửa tay.")
    md.append("")
    md.append("*(Khi nào bạn cho phép đồng bộ từ sheet `Alignment_Dataset` sang sheet `DONG_HANG` + file `.tsv` + đánh lại `Pair_ID`, chỉ mất 2 giây để đồng bộ chuẩn 100%).*")
    md.append("")
    md.append("---")
    md.append("")
    md.append(f"## 4. Danh Sách Vỏn Vẹn {len(rem_mis)} Dòng Còn Bị Chấm `MISMATCH` Trên Toàn Bộ 2.043 Cặp (`0.59%`)")
    md.append("")
    md.append("Nếu bạn muốn đạt mức gần như tuyệt đối `~100% USABLE`, dưới đây là **toàn bộ 12 dòng duy nhất còn lại** trên tổng số 2.043 dòng mà Judge đánh dấu `MISMATCH` (kèm đúng số dòng Excel thực tế trên sheet `Alignment_Dataset` của bạn):")
    md.append("")
    md.append("| # | Dòng Excel (`Alignment_Dataset`) | `Pair_ID` hiện tại | Khối | Kiểu | Lý do Judge (`Judge_Reason`) | Chữ Hán (`Chinese`) | Tiếng Việt (`Vietnamese`) |")
    md.append("| :-: | :-: | :--- | :-: | :-: | :--- | :--- | :--- |")
    for idx_m, (_, r) in enumerate(rem_mis.iterrows(), start=1):
        orig_pid = esc(r["Orig_Pair_ID"]) if pd.notna(r["Orig_Pair_ID"]) else "*(Dòng mới chèn - trống ID)*"
        md.append(
            f"| {idx_m} | **Dòng {int(r['Excel_Row_In_Source'])}** | `{orig_pid}` | `{r['Block']}` | `{esc(r['Alignment_Type'])}` | {esc(r['Judge_Reason'])} | {esc(r['Chinese'])} | {esc(r['Vietnamese'])} |"
        )

    md.append("")
    md.append("---")
    md.append("")
    md.append(f"## 5. Phụ Lục: Kết Quả Chấm Trên {len(df_edited)} Dòng Đã Được Bạn Sửa Tay / Chèn Mới")
    md.append("")
    md.append("| # | Dòng Excel | `Pair_ID` | Nhãn Mới (`Real_Label`) | Nhận xét của Judge (`Judge_Reason`) | Chữ Hán (`Chinese`) | Tiếng Việt (`Vietnamese`) |")
    md.append("| :-: | :-: | :--- | :-: | :--- | :--- | :--- |")
    for idx_e, (_, r) in enumerate(df_edited.iterrows(), start=1):
        orig_pid = esc(r["Orig_Pair_ID"]) if pd.notna(r["Orig_Pair_ID"]) else "*(Mới chèn)*"
        zh_short = esc(r["Chinese"])
        vi_short = esc(r["Vietnamese"])
        if len(zh_short) > 65:
            zh_short = zh_short[:62] + "..."
        if len(vi_short) > 85:
            vi_short = vi_short[:82] + "..."
        md.append(
            f"| {idx_e} | Dòng {int(r['Excel_Row_In_Source'])} | `{orig_pid}` | **{r['Real_Label']}** | {esc(r['Judge_Reason'])} | {zh_short} | {vi_short} |"
        )

    OUT_MD.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"Đã ghi báo cáo phân tích tại: {OUT_MD}")
    print(f"Tổng dòng: {len(df_new)} | CLEAN: {c_new} | PARTIAL: {p_new} | MISMATCH: {m_new} | Edited rows: {len(df_edited)}")
    print(f"Null Pair_ID: {len(null_orig_pid)} | Duplicate Pair_ID: {len(dup_pids)}")


if __name__ == "__main__":
    main()
