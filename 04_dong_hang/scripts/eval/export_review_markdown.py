# -*- coding: utf-8 -*-
import re
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
IN_XLSX = PROJECT_ROOT / "04_dong_hang" / "output" / "v6_1" / "PhuBienTapLuc_Alignment_V6_1_Independent_Judged.xlsx"
OUT_MD = PROJECT_ROOT / "04_dong_hang" / "output" / "v6_1" / "DANH_SACH_DONG_CAN_RA_SOAT_V6_1.md"


def get_blk(pid: str) -> str:
    m = re.search(r"_V(\d+)$", str(pid))
    vp = int(m.group(1)) if m else 0
    if 186 <= vp <= 251:
        return "Cap_01 (Quyển II - Thuế lệ & Sổ đội thuyền)"
    if 1 <= vp <= 105:
        return "Cap_02_V (Quyển V - Nghệ văn chí / Thơ văn)"
    return "Cap_02_VI (Quyển VI - Địa lý, Sản vật & Phong thổ)"


def parse_pages(pid: str):
    m = re.search(r"_C(\d+)_V(\d+)$", str(pid))
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def esc(val) -> str:
    if pd.isna(val) or val is None:
        return ""
    return str(val).replace("|", "\\|").replace("\n", " ").strip()


def main():
    df = pd.read_excel(IN_XLSX)
    lt0 = df[df["Label_Target"] == 0].copy()
    lt0["TSV_Line"] = lt0.index + 1
    lt0["Excel_Row_DongHang"] = lt0.index + 2
    lt0["Excel_Row_Template"] = lt0.index + 3
    lt0["Block_Name"] = lt0["Pair_ID"].apply(get_blk)

    mis = lt0[lt0["Real_Label"] == "MISMATCH"]
    par = lt0[lt0["Real_Label"] == "PARTIAL"]

    lines = [
        "# Danh sách 101 dòng `Label_Target = 0` cần lưu ý / rà soát tay (`v6.1`)",
        "",
        "Tài liệu này tổng hợp toàn bộ **101 / 2.037 dòng (`4.96%`)** có `Label_Target = 0` trong bộ dữ liệu **`v6.1`** để dễ dàng bấm Ctrl+F tìm mã `Pair_ID` hoặc nhảy thẳng tới số dòng tương ứng trên Excel / TSV.",
        "",
        "## 1. Hướng dẫn tra cứu số dòng chính xác trên từng file",
        "- **File `.tsv`**: [CV16_PhuBienTapLuc_parallel.tsv](file:///C:/Users/Tuan%20TCA/OneDrive/Tai_Lieu/3ndYear/NLP/Midterm/CV16/04_dong_hang/CV16_PhuBienTapLuc_parallel.tsv) → Xem cột **`Dòng TSV`** (chính bằng số thứ tự `Pxxxx` trong `Pair_ID`).",
        "- **Sheet `DONG_HANG`** trong [CV16_PhuBienTapLuc_parallel.xlsx](file:///C:/Users/Tuan%20TCA/OneDrive/Tai_Lieu/3ndYear/NLP/Midterm/CV16/04_dong_hang/CV16_PhuBienTapLuc_parallel.xlsx) và [PhuBienTapLuc_Alignment_V6_1_Independent_Judged.xlsx](file:///C:/Users/Tuan%20TCA/OneDrive/Tai_Lieu/3ndYear/NLP/Midterm/CV16/04_dong_hang/output/v6_1/PhuBienTapLuc_Alignment_V6_1_Independent_Judged.xlsx) → Xem cột **`Dòng DONG_HANG`** (`= Dòng TSV + 1`).",
        "- **Sheet `Alignment_Dataset` chuẩn Template** trong [PhuBienTapLuc_Alignment_V6_1.xlsx](file:///C:/Users/Tuan%20TCA/OneDrive/Tai_Lieu/3ndYear/NLP/Midterm/CV16/04_dong_hang/output/v6_1/PhuBienTapLuc_Alignment_V6_1.xlsx) → Xem cột **`Dòng Template`** (`= Dòng TSV + 2` do có 2 dòng header).",
        "- **Trang PDF gốc để đối chiếu ảnh scan**: Mã `Pxxxx_C<Trang_Hán>_V<Trang_Việt>` ghi rõ số trang Hán (`C...`) và số trang sách dịch Việt (`V...`).",
        "",
        "## 2. Thống kê nhanh 101 dòng còn lại",
        "| Phân nhóm | Số dòng | Mức độ ưu tiên | Đặc điểm & Gợi ý xử lý |",
        "| :--- | :---: | :---: | :--- |",
        f"| **Nhóm A — `MISMATCH`** | **{len(mis)} dòng** | **Cao nhất (Nên kiểm tra trước)** | Trượt biên cục bộ 1 câu kề trước/sau, khuyết câu dịch trong sách gốc, hoặc chữ Hán OCR nhiễu nặng. |",
        f"| **Nhóm B — `PARTIAL` (kèm cảnh báo OCR / tỷ lệ)** | **{len(par)} dòng** | **Thấp (Tham khảo)** | Phần nghĩa chính đã khớp nhau, chỉ bị mờ một vài chữ Hán (`OCR_Conf < 0.55`) hoặc dính nhẹ vế phụ câu kề. |",
        f"| **Tổng cộng (`Label_Target = 0`)** | **{len(lt0)} dòng** | — | Chiếm `4.96%` toàn tập (`1.936 / 2.037` dòng còn lại = `95.04%` đã đạt `Label_Target = 1`). |",
        "",
        "---",
        "",
        f"## PHẦN 1: Nhóm A — {len(mis)} dòng `MISMATCH` (Ưu tiên rà soát tay)",
        "",
    ]

    for blk, grp in mis.groupby("Block_Name", sort=False):
        lines.append(f"### {blk} — {len(grp)} dòng")
        lines.append("")
        lines.append("| # | Pair_ID | Dòng TSV | Dòng DONG_HANG | Dòng Template | Trang (Hán/Việt) | Kiểu | Lý do Judge (`Judge_Reason`) | Chữ Hán (`Chinese`) | Tiếng Việt (`Vietnamese`) |")
        lines.append("| :-: | :--- | :-: | :-: | :-: | :-: | :-: | :--- | :--- | :--- |")
        for idx_i, (_, r) in enumerate(grp.iterrows(), start=1):
            hp, vp = parse_pages(r["Pair_ID"])
            lines.append(
                f"| {idx_i} | `{r['Pair_ID']}` | {r['TSV_Line']} | {r['Excel_Row_DongHang']} | **{r['Excel_Row_Template']}** | C{hp} / V{vp} | `{r['Alignment_Type']}` | {esc(r['Judge_Reason'])} | {esc(r['Chinese'])} | {esc(r['Vietnamese'])} |"
            )
        lines.append("")

    lines.extend([
        "---",
        "",
        f"## PHẦN 2: Nhóm B — {len(par)} dòng `PARTIAL` (Đúng ý lõi nhưng mờ OCR chữ Hán / lệch nhẹ biên)",
        "",
    ])

    for blk, grp in par.groupby("Block_Name", sort=False):
        lines.append(f"### {blk} — {len(grp)} dòng")
        lines.append("")
        lines.append("| # | Pair_ID | Dòng TSV | Dòng DONG_HANG | Dòng Template | OCR Conf | Lý do Judge & Ghi chú | Chữ Hán (`Chinese`) | Tiếng Việt (`Vietnamese`) |")
        lines.append("| :-: | :--- | :-: | :-: | :-: | :-: | :--- | :--- | :--- |")
        for idx_i, (_, r) in enumerate(grp.iterrows(), start=1):
            conf_str = f"`{r['OCR_Conf_Min']:.3f}`" if pd.notna(r["OCR_Conf_Min"]) else "`N/A`"
            note_short = esc(r["Note"]).replace(" \\| ", "; ")
            lines.append(
                f"| {idx_i} | `{r['Pair_ID']}` | {r['TSV_Line']} | {r['Excel_Row_DongHang']} | **{r['Excel_Row_Template']}** | {conf_str} | **{esc(r['Judge_Reason'])}** *(Cảnh báo: {note_short})* | {esc(r['Chinese'])} | {esc(r['Vietnamese'])} |"
            )
        lines.append("")

    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Đã xuất thành công {OUT_MD} ({len(lt0)} dòng: {len(mis)} MISMATCH + {len(par)} PARTIAL).")


if __name__ == "__main__":
    main()
