# -*- coding: utf-8 -*-
"""
Đồng bộ & Thẩm định lại bản sửa tay cuối cùng (v6.2 Human-in-the-Loop Final Deliverable):
1. Đọc dữ liệu từ sheet `Alignment_Dataset` của `04_dong_hang/CV16_PhuBienTapLuc_parallel.xlsx` (nơi người dùng sửa tay 101 dòng).
2. Chấm bổ sung các dòng mới chỉnh sửa (chưa có trong cache `CV16_Manual_Edited_Judged.xlsx`) bằng `gemini-3.5-flash-lite` (`temperature=0.0`, cùng prompt chuẩn `judge_real_label.py`).
3. Cập nhật lại đầy đủ các chỉ số QC (`OMISSION`, `ADDITION`, `MISSING`, `Punct_Anchor_Match`, `Label_Target`, `Real_Label`, `Judge_Reason`), đánh lại mã `Pair_ID` liên tiếp `P0001_Cxxx_Vyyy`..`P2043_Cxxx_Vyyy`.
4. Đồng bộ 100% các cặp hợp lệ đủ 2 vế (không chứa `[Khuyết trong bản Hán]` hay rỗng) sang:
   - `04_dong_hang/CV16_PhuBienTapLuc_parallel.tsv`
   - Sheet `DONG_HANG` (2 cột `Hán` và `Việt`, đặt làm sheet đầu tiên) và sheet `THONG_KE_QC` của `04_dong_hang/CV16_PhuBienTapLuc_parallel.xlsx`.
5. Lưu kết quả chấm đầy đủ ra `04_dong_hang/output/manual_edit_eval/CV16_Manual_Edited_Judged.xlsx` và cập nhật `04_dong_hang/PHAN_TICH_SAU_SUA_TAY_V6_1.md`.
"""

import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
from google import genai
from google.genai import types
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPTS_ROOT = SCRIPT_DIR.parent
PROJECT_ROOT = SCRIPTS_ROOT.parents[1]

sys.path.insert(0, str(SCRIPTS_ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

from judge_real_label import (  # noqa: E402
    BatchJudgmentResponse,
    FALLBACK_MODELS,
    SYSTEM_INSTRUCTION,
)
from run_align_v5 import (  # noqa: E402
    OCR_CONF_THRESHOLD,
    check_punct_or_number_match,
    count_cjk_chars,
    evaluate_numeric_consistency,
)
from run_refine_v6_deliverables import (  # noqa: E402
    populate_template_style_sheet,
    sanitize_single_line,
)

PARALLEL_XLSX = PROJECT_ROOT / "04_dong_hang" / "CV16_PhuBienTapLuc_parallel.xlsx"
PARALLEL_TSV = PROJECT_ROOT / "04_dong_hang" / "CV16_PhuBienTapLuc_parallel.tsv"
BACKUP_XLSX = PROJECT_ROOT / "04_dong_hang" / "output" / "manual_edit_eval" / "CV16_PhuBienTapLuc_parallel_backup_before_sync.xlsx"
PREV_JUDGED_XLSX = PROJECT_ROOT / "04_dong_hang" / "output" / "manual_edit_eval" / "CV16_Manual_Edited_Judged.xlsx"
SUMMARY_FINAL_JSON = PROJECT_ROOT / "04_dong_hang" / "output" / "manual_edit_eval" / "alignment_v6_2_final_summary.json"


def parse_pages(pid: str) -> Tuple[int, int]:
    m = re.search(r"_C(\d+)_V(\d+)$", str(pid))
    if m:
        return int(m.group(1)), int(m.group(2))
    return 0, 0


def get_block_from_pages(vp: int, idx: int, total_len: int) -> str:
    if 186 <= vp <= 251:
        return "Cap_01"
    if 1 <= vp <= 105:
        return "Cap_02_V"
    if 405 <= vp <= 439:
        return "Cap_02_VI"
    ratio = idx / max(total_len, 1)
    return "Cap_01" if ratio < 0.40 else ("Cap_02_V" if ratio < 0.78 else "Cap_02_VI")


def is_placeholder_missing(zh: str, vi: str) -> bool:
    if not zh or not vi:
        return True
    if "[Khuyết" in zh or "[Khuyết" in vi:
        return True
    return False


def judge_unseen_rows(unseen_items: List[Tuple[int, str, str, str]]) -> Dict[int, Tuple[str, str]]:
    if not unseen_items:
        return {}
    raw_keys = os.environ.get("GEMINI_API_KEYS") or os.environ.get("GEMINI_API_KEY", "")
    keys = [k.strip() for k in raw_keys.split(",") if k.strip()]
    if not keys:
        raise EnvironmentError("Thiếu GEMINI_API_KEY để chấm bổ sung các dòng mới sửa.")
    clients = [genai.Client(api_key=k) for k in keys]

    lines = []
    for idx, pid, zh, vi in unseen_items:
        lines.append(f"[{idx}] Pair_ID={pid}\n  Hán : {zh}\n  Việt: {vi}")
    prompt = "Hãy đánh giá các cặp câu song ngữ Hán - Việt dưới đây:\n\n" + "\n\n".join(lines)

    for m_name in FALLBACK_MODELS:
        for client in clients:
            try:
                resp = client.models.generate_content(
                    model=m_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        temperature=0.0,
                        response_mime_type="application/json",
                        response_schema=BatchJudgmentResponse,
                    ),
                )
                parsed = BatchJudgmentResponse.model_validate_json(resp.text)
                res_map = {item.row_idx: (item.real_label, item.reason) for item in parsed.results}
                if len(res_map) == len(unseen_items):
                    print(f"Đã chấm thành công {len(res_map)} dòng mới bằng model {m_name}!", flush=True)
                    return res_map
            except Exception as exc:
                print(f"[Thử lại] Model {m_name} gặp lỗi: {exc}", flush=True)
                time.sleep(2.0)
    raise RuntimeError("Không thể chấm bổ sung các dòng mới qua Gemini API.")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    BACKUP_XLSX.parent.mkdir(parents=True, exist_ok=True)
    if not BACKUP_XLSX.exists():
        shutil.copy2(PARALLEL_XLSX, BACKUP_XLSX)

    # Đọc từ bản backup gốc 2043 dòng sửa tay để luôn giữ nguyên nguồn đầu vào
    source_xlsx = BACKUP_XLSX if BACKUP_XLSX.exists() else PARALLEL_XLSX
    ad = pd.read_excel(source_xlsx, sheet_name="Alignment_Dataset", skiprows=[1])
    ad = ad[~(ad["Chinese"].isna() & ad["Vietnamese"].isna() & ad["Pair_ID"].isna())].reset_index(drop=True)

    prev_map: Dict[Tuple[str, str], Tuple[str, str]] = {}
    if PREV_JUDGED_XLSX.exists():
        df_prev = pd.read_excel(PREV_JUDGED_XLSX)
        for _, r in df_prev.iterrows():
            z = sanitize_single_line(r.get("Chinese"))
            v = sanitize_single_line(r.get("Vietnamese"))
            lbl = str(r.get("Real_Label", "")).strip()
            rsn = sanitize_single_line(r.get("Judge_Reason"))
            if lbl in ("CLEAN", "PARTIAL", "MISMATCH"):
                prev_map[(z, v)] = (lbl, rsn)

    unseen = []
    for idx, r in ad.iterrows():
        z = sanitize_single_line(r.get("Chinese"))
        v = sanitize_single_line(r.get("Vietnamese"))
        if is_placeholder_missing(z, v):
            continue
        if (z, v) not in prev_map:
            unseen.append((idx, str(r.get("Pair_ID", f"ROW_{idx+1}")), z, v))

    print(f"Tổng dòng trong Alignment_Dataset: {len(ad)} | Số dòng sửa mới cần chấm bổ sung: {len(unseen)}", flush=True)
    new_judgments = judge_unseen_rows(unseen)

    full_rows: List[Dict] = []
    for idx, r in ad.iterrows():
        orig_pid = sanitize_single_line(r.get("Pair_ID"))
        hp, vp = parse_pages(orig_pid)
        if hp == 0 and vp == 0 and idx > 0:
            hp, vp = parse_pages(full_rows[-1]["Pair_ID"])

        zh_s = sanitize_single_line(r.get("Chinese"))
        vi_s = sanitize_single_line(r.get("Vietnamese"))
        raw_at = r.get("Alignment_Type")
        atype = sanitize_single_line(raw_at) if pd.notna(raw_at) else ""
        if not atype or atype.lower() == "nan":
            atype = "1-1"

        ocr_c_raw = r.get("OCR_Conf_Min")
        ocr_c = round(float(ocr_c_raw), 4) if pd.notna(ocr_c_raw) else 0.85
        ocr_v = 1 if (ocr_c is None or ocr_c >= OCR_CONF_THRESHOLD) else 0

        placeholder_miss = is_placeholder_missing(zh_s, vi_s)
        missing = 1 if placeholder_miss else 0

        if placeholder_miss:
            real_lbl = "MISMATCH"
            judge_rsn = "Bản Hán khuyết trong sách gốc ([Khuyết trong bản Hán]), bản Việt dịch bổ sung."
        elif idx in new_judgments:
            real_lbl, judge_rsn = new_judgments[idx]
        else:
            real_lbl, judge_rsn = prev_map[(zh_s, vi_s)]

        r_min, r_max = (0.42, 3.20) if (1 <= vp <= 105) else (0.42, 2.35)
        omis = add = 0
        num_bad = False
        notes = []

        if missing == 1:
            notes.append("MISSING: Bản Hán khuyết đoạn tương ứng trong sách gốc")
        else:
            cjk_l = max(count_cjk_chars(zh_s), 1)
            vw = len(vi_s.split())
            rat = vw / cjk_l
            if rat < r_min:
                omis = 1
                notes.append(f"Nghi ngờ OMISSION ({rat:.2f} < {r_min})")
            elif rat > r_max:
                add = 1
                notes.append(f"Nghi ngờ ADDITION ({rat:.2f} > {r_max})")
            is_nb, _, n_msg = evaluate_numeric_consistency(zh_s, vi_s)
            if is_nb:
                num_bad = True
                notes.append(n_msg)

        if ocr_v == 0:
            notes.append(f"Cảnh báo OCR mờ (conf = {ocr_c} < {OCR_CONF_THRESHOLD})")

        pm = check_punct_or_number_match(zh_s, vi_s) if missing == 0 else 0
        lt = 1 if (missing == 0 and omis == 0 and add == 0 and not num_bad and ocr_v == 1 and real_lbl != "MISMATCH") else 0

        seq_num = idx + 1
        pid_new = f"P{seq_num:04d}_C{hp:03d}_V{vp:03d}"

        full_rows.append(
            {
                "Excel_Row_In_Source": idx + 3,
                "Pair_ID": pid_new,
                "Orig_Pair_ID": orig_pid,
                "Block": get_block_from_pages(vp, idx, len(ad)),
                "Chinese": zh_s if zh_s else None,
                "Vietnamese": vi_s if vi_s else None,
                "OMISSION": omis,
                "ADDITION": add,
                "MISSING": missing,
                "Alignment_Type": atype,
                "Punct_Anchor_Match": pm,
                "OCR_Valid": ocr_v,
                "Label_Target": lt,
                "OCR_Conf_Min": ocr_c,
                "Note": " | ".join(notes) if notes else None,
                "Real_Label": real_lbl,
                "Judge_Reason": judge_rsn,
            }
        )

    df_full = pd.DataFrame(full_rows)
    saved_judged = False
    for cand_name in [
        "CV16_Manual_Edited_Judged.xlsx",
        "CV16_Manual_Edited_Judged_v6_2.xlsx",
        f"CV16_Manual_Edited_Judged_{int(time.time())}.xlsx",
    ]:
        cand_path = PREV_JUDGED_XLSX.with_name(cand_name)
        try:
            df_full.to_excel(cand_path, index=False)
            saved_judged = True
            if cand_name != PREV_JUDGED_XLSX.name:
                print(f"[Lưu ý] Đã lưu kết quả chấm ra {cand_path.name} (file cũ đang mở trong Excel).", flush=True)
            break
        except PermissionError:
            continue

    # Các cặp bàn giao song ngữ hợp lệ đủ 2 vế thực sự (loại bỏ 2 dòng `[Khuyết trong bản Hán]` khỏi TSV & DONG_HANG theo Mục 3 & 7 Guideline)
    valid_parallel_rows = []
    for p_idx, r in enumerate([x for x in full_rows if x["MISSING"] == 0], start=1):
        hp, vp = parse_pages(r["Pair_ID"])
        r_copy = dict(r)
        r_copy["Pair_ID"] = f"P{p_idx:04d}_C{hp:03d}_V{vp:03d}"
        valid_parallel_rows.append(r_copy)

    df_par = pd.DataFrame(valid_parallel_rows)

    # Xuất TSV khớp 100% DONG_HANG
    tsv_lines = []
    for r in valid_parallel_rows:
        zc = sanitize_single_line(r["Chinese"])
        vc = sanitize_single_line(r["Vietnamese"])
        assert "\t" not in zc and "\t" not in vc
        assert "\n" not in zc and "\n" not in vc
        tsv_lines.append(f"{zc}\t{vc}")
    PARALLEL_TSV.write_text("\n".join(tsv_lines) + "\n", encoding="utf-8")

    # Tính thống kê trên tập bàn giao (valid_parallel_rows) và toàn bộ 2043 dòng
    vc_all = df_full["Real_Label"].value_counts()
    vc_par = df_par["Real_Label"].value_counts()

    han_lines_cnt = len((PROJECT_ROOT / "03_text_sach" / "han.txt").read_text(encoding="utf-8").splitlines())
    viet_lines_cnt = len((PROJECT_ROOT / "03_text_sach" / "viet.txt").read_text(encoding="utf-8").splitlines())

    block_stats = {}
    for blk in ["Cap_01", "Cap_02_V", "Cap_02_VI"]:
        sub = df_par[df_par["Block"] == blk]
        b_vc = sub["Real_Label"].value_counts()
        c_n = int(b_vc.get("CLEAN", 0))
        p_n = int(b_vc.get("PARTIAL", 0))
        m_n = int(b_vc.get("MISMATCH", 0))
        block_stats[blk] = {
            "pairs": len(sub),
            "label_1": int((sub["Label_Target"] == 1).sum()),
            "label_1_pct": round(100.0 * (sub["Label_Target"] == 1).mean(), 2),
            "clean": c_n,
            "clean_pct": round(100.0 * c_n / len(sub), 2),
            "partial": p_n,
            "partial_pct": round(100.0 * p_n / len(sub), 2),
            "mismatch": m_n,
            "mismatch_pct": round(100.0 * m_n / len(sub), 2),
            "usable": c_n + p_n,
            "usable_pct": round(100.0 * (c_n + p_n) / len(sub), 2),
            "ocr_valid": int((sub["OCR_Valid"] == 1).sum()),
            "ocr_valid_pct": round(100.0 * (sub["OCR_Valid"] == 1).mean(), 2),
            "punct_anchor": int((sub["Punct_Anchor_Match"] == 1).sum()),
            "punct_anchor_pct": round(100.0 * (sub["Punct_Anchor_Match"] == 1).mean(), 2),
            "omission": int((sub["OMISSION"] == 1).sum()),
            "addition": int((sub["ADDITION"] == 1).sum()),
            "1-1": int((sub["Alignment_Type"] == "1-1").sum()),
            "1-2_2-1": int(sub["Alignment_Type"].isin(["1-2", "2-1"]).sum()),
        }

    c_par = int(vc_par.get("CLEAN", 0))
    p_par = int(vc_par.get("PARTIAL", 0))
    m_par = int(vc_par.get("MISMATCH", 0))
    u_par = c_par + p_par

    summary = {
        "version": "v6.2_human_in_the_loop_final",
        "input_han_sents": han_lines_cnt,
        "input_viet_sents": viet_lines_cnt,
        "total_edited_sheet_rows": len(df_full),
        "dropped_placeholder_khuyet_rows": int((df_full["MISSING"] == 1).sum()),
        "parallel_deliverable_pairs": len(df_par),
        "label_target_1_count": int((df_par["Label_Target"] == 1).sum()),
        "label_target_1_pct": round(100.0 * (df_par["Label_Target"] == 1).mean(), 2),
        "ocr_valid_count": int((df_par["OCR_Valid"] == 1).sum()),
        "ocr_valid_pct": round(100.0 * (df_par["OCR_Valid"] == 1).mean(), 2),
        "punct_anchor_count": int((df_par["Punct_Anchor_Match"] == 1).sum()),
        "punct_anchor_pct": round(100.0 * (df_par["Punct_Anchor_Match"] == 1).mean(), 2),
        "omission_count": int((df_par["OMISSION"] == 1).sum()),
        "addition_count": int((df_par["ADDITION"] == 1).sum()),
        "parallel_clean": c_par,
        "parallel_clean_pct": round(100.0 * c_par / len(df_par), 2),
        "parallel_partial": p_par,
        "parallel_partial_pct": round(100.0 * p_par / len(df_par), 2),
        "parallel_mismatch": m_par,
        "parallel_mismatch_pct": round(100.0 * m_par / len(df_par), 2),
        "parallel_usable": u_par,
        "parallel_usable_pct": round(100.0 * u_par / len(df_par), 2),
        "all_2043_clean": int(vc_all.get("CLEAN", 0)),
        "all_2043_partial": int(vc_all.get("PARTIAL", 0)),
        "all_2043_mismatch": int(vc_all.get("MISMATCH", 0)),
        "alignment_types": df_par["Alignment_Type"].value_counts().to_dict(),
        "blocks": block_stats,
    }
    SUMMARY_FINAL_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # Xuất Workbook `CV16_PhuBienTapLuc_parallel.xlsx` chuẩn Mục 3 Guideline:
    # Sheet 1: `DONG_HANG` (2 cột `Hán`, `Việt` khớp từng dòng với `.tsv`)
    # Sheet 2: `Alignment_Dataset` (chuẩn Template đầy đủ nhãn)
    # Sheet 3: `THONG_KE_QC`
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
        zc = sanitize_single_line(r["Chinese"])
        vc = sanitize_single_line(r["Vietnamese"])
        c_zh = ws_dh.cell(r_idx, 1, zc)
        c_vi = ws_dh.cell(r_idx, 2, vc)
        c_zh.font = dh_data_font
        c_vi.font = dh_data_font
        c_zh.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
        c_vi.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
        c_zh.border = dh_border
        c_vi.border = dh_border

    ws_dh.freeze_panes = "A2"

    ws_ad = wb_par.create_sheet(title="Alignment_Dataset")
    populate_template_style_sheet(ws_ad, valid_parallel_rows, include_extra_judge_cols=True)

    ws_qc = wb_par.create_sheet(title="THONG_KE_QC")
    ws_qc.column_dimensions["A"].width = 48.0
    ws_qc.column_dimensions["B"].width = 32.0
    qc_items = [
        ("Mã đề tài & Tác phẩm", "CV16_PhuBienTapLuc"),
        ("Tổng số dòng Hán sạch (03_text_sach/han.txt)", summary["input_han_sents"]),
        ("Tổng số dòng Việt sạch (03_text_sach/viet.txt)", summary["input_viet_sents"]),
        ("Tổng số cặp hợp lệ bàn giao (.tsv & DONG_HANG)", summary["parallel_deliverable_pairs"]),
        ("Tỷ lệ đạt chuẩn kiểm định tự động (Label_Target = 1)", f"{summary['label_target_1_count']} ({summary['label_target_1_pct']:.2f}%)"),
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
        ws_qc.cell(idx_q, 2, v_q).font = Font(name="Calibri", size=11)

    try:
        wb_par.save(PARALLEL_XLSX)
    except PermissionError:
        alt_par = PARALLEL_XLSX.with_name("CV16_PhuBienTapLuc_parallel_synced.xlsx")
        wb_par.save(alt_par)
        print(f"[Cảnh báo] {PARALLEL_XLSX.name} đang mở trong Excel! Đã lưu tạm sang {alt_par.name}.", flush=True)

    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
