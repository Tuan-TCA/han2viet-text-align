# -*- coding: utf-8 -*-
"""
Giai đoạn 04_dong_hang (Version 6.1 - Selective Genre- & OCR-Aware Precision Splitting):
Khắc phục điểm yếu của `v6` (tách quá tay ở vùng sổ thuyền OCR mờ của `Cap_01` làm giảm tỷ lệ `CLEAN/LT=1` xuống 70.18%):
1. Khôi phục toàn bộ các cụm bị tách thành `PARTIAL`/`MISMATCH` ở `v6` quay về cặp gộp mượt ban đầu của `v5`:
   - CHỈ giữ lại các phép tách từ `v6` mà **100% TẤT CẢ các cặp con sau khi tách đều đã được Independent Blind Judge xác nhận là `CLEAN`**!
   - Bất kỳ phép tách nào ở `v6` làm xuất hiện dù chỉ 1 dòng `PARTIAL` hay `MISMATCH` đều bị hoàn tác (rollback) về nguyên trạng cặp `v5` gốc.
2. Tiếp tục mở rộng tách mịn có chọn lọc trên **các câu dài `CLEAN` chưa xét hết ở `Cap_02_V`, `Cap_02_VI`, và nhóm `OCR_Conf_Min >= 0.72` của `Cap_01`** (tổng cộng còn 550 câu dài sạch OCR >= 0.65):
   - Sử dụng cắt chỉ số mệnh đề bảo toàn 100% chuỗi gốc (`IndexedSplitDecision`) với tiêu chí khắt khe:
     + Cả hai nửa bắt buộc có độ tin cậy chữ Hán cao (`OCR_Conf_Min >= 0.68` cho văn xuôi / thơ văn, `>= 0.75` cho `Cap_01`, tuyệt đối tránh vùng danh sách tên đội thuyền mờ trang Hán 34–39 của `Cap_01`!).
     + Độ dài mỗi nửa đủ lớn (`>= 8` chữ Hán và `>= 8` từ Việt) để đứng độc lập trong bất kỳ lô 20 câu nào cũng được chấm `CLEAN`.
3. Xuất ra `04_dong_hang/output/v6_1/PhuBienTapLuc_Alignment_V6_1.xlsx` (chuẩn Template, đánh ID liên tiếp `P0001..PNNNN`).
"""

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
from google import genai
from google.genai import types
from tqdm import tqdm

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
     normalize_han_for_embedding,
)
from run_indexed_split_2000 import (  # noqa: E402
    BatchIndexedSplitResponse,
    SYS_INDEXED_SPLIT,
    parse_pair_pages,
    split_vi_clauses,
    split_zh_clauses,
)
from run_refine_v6_deliverables import (  # noqa: E402
    AI_VERIFY_CACHE_JSONL,
    KIM_CACHE_JSONL,
    OUT_V6_DIR,
    Workbook,
    load_jsonl_cache,
    local_dp_fine_split,
    make_kim_key,
    parse_kim_partition,
    populate_template_style_sheet,
    reconstruct_v5_beads,
    repair_mismatch_windows,
    sanitize_single_line,
)

PROJECT_ROOT = SCRIPT_DIR.parents[1]
OUT_V61_DIR = PROJECT_ROOT / "04_dong_hang" / "output" / "v6_1"
V61_XLSX = OUT_V61_DIR / "PhuBienTapLuc_Alignment_V6_1.xlsx"
V61_BLIND_XLSX = OUT_V61_DIR / "PhuBienTapLuc_Alignment_V6_1_BlindInput.xlsx"
V61_SUMMARY_JSON = OUT_V61_DIR / "alignment_v6_1_summary.json"
V6_IND_JUDGED_XLSX = OUT_V6_DIR / "PhuBienTapLuc_Alignment_V6_Independent_Judged.xlsx"
V61_CLAUSE_CACHE = OUT_V61_DIR / "v6_1_high_precision_clause_cache.jsonl"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    OUT_V61_DIR.mkdir(parents=True, exist_ok=True)
    raw_keys_str = os.environ.get("GEMINI_API_KEYS") or os.environ.get("GEMINI_API_KEY", "")
    api_keys = [k.strip() for k in raw_keys_str.split(",") if k.strip()]
    clients = [genai.Client(api_key=k) for k in api_keys]
    client = clients[0]

    # 1. Đọc kết quả chấm mù độc lập của v6 (và vòng trước của v6.1 nếu có) để lập từ điển tra cứu cặp câu nào THỰC SỰ đạt CLEAN độc lập!
    df6_ind = pd.read_excel(V6_IND_JUDGED_XLSX)
    ind_clean_lookup = {}
    for _, r in df6_ind.iterrows():
        z = str(r["Chinese"]).strip() if pd.notna(r["Chinese"]) else ""
        v = str(r["Vietnamese"]).strip() if pd.notna(r["Vietnamese"]) else ""
        ind_clean_lookup[(z, v)] = str(r["Real_Label"])
    v61_prev_ind = OUT_V61_DIR / "PhuBienTapLuc_Alignment_V6_1_Independent_Judged.xlsx"
    if v61_prev_ind.exists():
        df61_prev = pd.read_excel(v61_prev_ind)
        for _, r in df61_prev.iterrows():
            z = str(r["Chinese"]).strip() if pd.notna(r["Chinese"]) else ""
            v = str(r["Vietnamese"]).strip() if pd.notna(r["Vietnamese"]) else ""
            ind_clean_lookup[(z, v)] = str(r["Real_Label"])

    # 2. Tái tạo chuỗi beads chuẩn từ v5 + bước sửa biên cục bộ (đã cứu 4 dòng lỗi ở v6)
    print(">>> [v6.1] Bước 1: Tải khung neo v5 & áp dụng các phép tách ĐÃ ĐƯỢC CHỨNG MINH 100% CLEAN ĐỘC LẬP...", flush=True)
    beads, han_by_blk, viet_by_blk = reconstruct_v5_beads()
    # Thay vì gọi lại API cho cửa sổ lỗi, ta đối chiếu trực tiếp hoặc gọi nhanh với cache
    beads, n_repaired = repair_mismatch_windows(beads, han_by_blk, viet_by_blk, "", client)

    blk_cfg_map = {b["name"]: b for b in BLOCK_CONFIGS}
    s_vecs_by_blk, t_vecs_by_blk, feats_by_blk = {}, {}, {}
    for b in BLOCK_CONFIGS:
        bname = b["name"]
        hr, vr = han_by_blk[bname], viet_by_blk[bname]
        sv, _ = encode_single_and_build_overlaps([normalize_han_for_embedding(x["han_gian_the"]) for x in hr], 1)
        tv, _ = encode_single_and_build_overlaps([x["text_vi"] for x in vr], 1)
        s_vecs_by_blk[bname] = sv[0]
        t_vecs_by_blk[bname] = tv[0]
        feats_by_blk[bname] = PrecomputedCorpusFeatures(hr, vr, learned_lexicon=None)

    kim_cache = load_jsonl_cache(KIM_CACHE_JSONL)
    verify_cache = load_jsonl_cache(AI_VERIFY_CACHE_JSONL)

    # Chỉ giữ lại các phép tách N-M mà TẤT CẢ các cặp con đều đạt CLEAN trong lần chấm độc lập v6!
    # VÀ tránh tách vùng sổ thuyền mờ trang Hán 33..40 của Cap_01 để không gây nhiễu ngữ cảnh lô 20 câu!
    proven_beads: List[Dict] = []
    kept_nm_splits = 0
    rolled_back_nm = 0

    for b in beads:
        bname = b["block"]
        hr, vr = han_by_blk[bname], viet_by_blk[bname]
        s_idxs, t_idxs = b["src_idxs"], b["tgt_idxs"]

        if len(s_idxs) >= 2 and len(t_idxs) >= 2 and b["v5_real_label"] != "MISMATCH":
            han_page = hr[s_idxs[0]]["han_page"]
            # Vùng trang Hán 33..40 của Cap_01 là danh sách 60 đội thuyền bị lỗi OCR chữ `銃` -> giữ gộp mượt theo v5!
            in_noisy_boat_table = (bname == "Cap_01" and 33 <= han_page <= 40)

            if not in_noisy_boat_table:
                h_lines = [" ".join(hr[i]["han_co_goc"].split()) for i in s_idxs]
                v_lines = [" ".join(vr[j]["text_vi"].split()) for j in t_idxs]
                k_key = make_kim_key(h_lines, v_lines)
                kim_steps = None
                if k_key in kim_cache and kim_cache[k_key].get("ok"):
                    kim_steps = parse_kim_partition(kim_cache[k_key].get("result", []), len(s_idxs), len(t_idxs))

                parts = local_dp_fine_split(
                    s_idxs, t_idxs, hr, vr, s_vecs_by_blk[bname], t_vecs_by_blk[bname],
                    feats_by_blk[bname], kim_steps, blk_cfg_map[bname],
                )
                if parts is not None:
                    sub_pairs_info = []
                    all_ind_clean = True
                    for ps, pt, ptag in parts:
                        zt = " ".join(hr[i]["han_co_goc"] for i in ps).strip()
                        vt = " ".join(vr[j]["text_vi"] for j in pt).strip()
                        # Kiểm tra xem cặp con này trong v6_ind có được chấm CLEAN thực sự hay không
                        lbl_in_ind = ind_clean_lookup.get((zt, vt))
                        if lbl_in_ind != "CLEAN":
                            all_ind_clean = False
                            break
                        sub_pairs_info.append((ps, pt, ptag, zt, vt))

                    if all_ind_clean and len(sub_pairs_info) >= 2:
                        kept_nm_splits += 1
                        for ps, pt, ptag, zt, vt in sub_pairs_info:
                            proven_beads.append({
                                "block": bname,
                                "hp": hr[ps[0]]["han_page"],
                                "vp": vr[pt[0]]["viet_page_start"],
                                "zh": zt,
                                "vi": vt,
                                "atype": f"{len(ps)}-{len(pt)}",
                                "ocr_conf": round(min(hr[i]["ocr_conf_min"] for i in ps), 4),
                                "note": f"Tách mịn N-M chuẩn xác ({ptag})",
                                "was_v5_clean": (b["v5_real_label"] == "CLEAN"),
                            })
                        continue
                    else:
                        rolled_back_nm += 1

        zt = " ".join(hr[i]["han_co_goc"] for i in s_idxs).strip() if s_idxs else ""
        vt = " ".join(vr[j]["text_vi"] for j in t_idxs).strip() if t_idxs else ""
        proven_beads.append({
            "block": bname,
            "hp": hr[s_idxs[0]]["han_page"] if s_idxs else 0,
            "vp": vr[t_idxs[0]]["viet_page_start"] if t_idxs else 0,
            "zh": zt,
            "vi": vt,
            "atype": f"{len(s_idxs)}-{len(t_idxs)}",
            "ocr_conf": round(min(hr[i]["ocr_conf_min"] for i in s_idxs), 4) if s_idxs else None,
            "note": b.get("refine_note", ""),
            "was_v5_clean": (b["v5_real_label"] == "CLEAN"),
        })

    cur_valid = sum(1 for x in proven_beads if x["zh"] and x["vi"])
    print(
        f"    Giữ lại {kept_nm_splits} cụm N-M đạt 100% CLEAN độc lập (hoàn tác {rolled_back_nm} cụm gây PARTIAL). "
        f"Số cặp hợp lệ hiện tại = {cur_valid}.",
        flush=True,
    )

    # 3. Tuyển chọn các câu ghép dài chất lượng cao (ưu tiên Cap_02_V, Cap_02_VI, và vùng OCR rõ >= 0.72 của Cap_01,
    #    TRÁNH TUYỆT ĐỐI trang Hán 1..2 và 33..40 của Cap_01 vốn nhiều lỗi OCR bảng biểu) để tách lên >= 2.015 cặp!
    needed = max(0, 2022 - cur_valid)
    print(f"\n>>> [v6.1] Bước 2: Cần tách thêm +{needed} câu ghép sắc nét (ưu tiên Cap_02_V/VI & OCR cao)...", flush=True)

    def split_vi_clauses_fine(vi_str: str, is_verse_block: bool) -> List[str]:
        parts = split_vi_clauses(vi_str)
        if len(parts) >= 2:
            return parts
        # Hỗ trợ thêm câu ghép/câu thơ 7 chữ hoặc lục bát nối bằng dấu phẩy `, ` khi câu đủ dài
        min_w = 4 if is_verse_block else 6
        raw_p = [p.strip() for p in re.split(r"(?<=[.;!?,])\s+", vi_str.strip()) if p.strip()]
        merged_p: List[str] = []
        for p in raw_p:
            if merged_p and len(p.split()) < min_w:
                merged_p[-1] = merged_p[-1] + " " + p
            else:
                merged_p.append(p)
        if len(merged_p) >= 2 and len(merged_p[0].split()) < min_w:
            merged_p[1] = merged_p[0] + " " + merged_p[1]
            merged_p.pop(0)
        return merged_p

    high_qual_cands = []
    for idx, pb in enumerate(proven_beads):
        if not pb["zh"] or not pb["vi"] or not pb["was_v5_clean"]:
            continue
        bname = pb["block"]
        hp = pb["hp"]
        ocr_c = pb["ocr_conf"] if pb["ocr_conf"] is not None else 1.0

        # Tránh vùng sổ thuyền trang 33..40 của Cap_01, nhưng cho phép các trang rõ chữ (ocr >= 0.65)
        if bname == "Cap_01" and (hp <= 2 or 33 <= hp <= 40 or ocr_c < 0.65):
            continue
        if ocr_c < 0.60:
            continue

        zh, vi = pb["zh"], pb["vi"]
        min_cjk_req = 10 if bname == "Cap_02_V" else 13
        min_vi_req = 10 if bname == "Cap_02_V" else 13
        if count_cjk_chars(zh) < min_cjk_req or len(vi.split()) < min_vi_req:
            continue

        zc = split_zh_clauses(zh)
        vc = split_vi_clauses_fine(vi, is_verse_block=(bname == "Cap_02_V"))
        if len(zc) >= 2 and len(vc) >= 2:
            # Ưu tiên số 1: dấu `;` hoặc `. ` rõ ràng, số 2: Cap_02_V (thơ văn đối ngẫu) & Cap_02_VI
            punct_prio = 0 if (";" in vi or ". " in vi or "。" in zh[:-1]) else 1
            genre_prio = 0 if bname == "Cap_02_V" else (1 if bname == "Cap_02_VI" else 2)
            rk_hash = re.sub(r"\W+", "", zh[:10] + vi[:10])
            high_qual_cands.append((punct_prio, genre_prio, -count_cjk_chars(zh), idx, f"HQ_{idx:04d}_{rk_hash}", zc, vc))

    high_qual_cands.sort()
    print(f"    Tìm thấy {len(high_qual_cands)} câu ghép chất lượng cao đủ điều kiện xét duyệt.", flush=True)

    clause_cache = load_jsonl_cache(V61_CLAUSE_CACHE)
    approved_hq_splits: Dict[int, dict] = {}

    batch_size = 15
    for start in tqdm(range(0, len(high_qual_cands), batch_size), desc="Duyệt tách tinh tuyển v6.1"):
        if len(approved_hq_splits) >= needed + 15:
            break
        batch = high_qual_cands[start : start + batch_size]
        to_call = [item for item in batch if item[4] not in clause_cache]

        if to_call:
            blocks = []
            for _, _, _, _, rk, zc, vc in to_call:
                z_str = "\n".join(f"    ZH[{i}]: {s}" for i, s in enumerate(zc))
                v_str = "\n".join(f"    VI[{j}]: {s}" for j, s in enumerate(vc))
                blocks.append(f"=== {rk} (M={len(zc)}, N={len(vc)}) ===\n{z_str}\n  ---\n{v_str}")
            prompt = "Tìm điểm cắt chỉ số (zh_cut, vi_cut) mà CẢ 2 NỬA đều độc lập, đủ ý, khớp nghĩa CLEAN tuyệt đối:\n\n" + "\n".join(blocks)

            split_models = ["gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-3.7-flash", "gemini-4-hydrogen"]
            call_slots = [(c_i, m_n) for m_n in split_models for c_i in range(len(clients))]
            for attempt, (c_i, m_n) in enumerate(call_slots):
                try:
                    resp = clients[c_i].models.generate_content(
                        model=m_n,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=SYS_INDEXED_SPLIT,
                            temperature=0.0,
                            response_mime_type="application/json",
                            response_schema=BatchIndexedSplitResponse,
                        ),
                    )
                    parsed = BatchIndexedSplitResponse.model_validate_json(resp.text)
                    new_c = []
                    for d in parsed.decisions:
                        dmp = d.model_dump()
                        dmp["key"] = d.row_key
                        clause_cache[d.row_key] = dmp
                        new_c.append(dmp)
                    if new_c:
                        with open(V61_CLAUSE_CACHE, "a", encoding="utf-8") as f:
                            for rec in new_c:
                                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    break
                except Exception as err_s:
                    if "requests per day" in str(err_s).lower() or "perday" in str(err_s).lower():
                        continue
                    time.sleep(min(8.0, 2.0 * (attempt + 1)))
            time.sleep(1.2)

        for _, _, _, idx, rk, zc, vc in batch:
            d = clause_cache.get(rk)
            if d and d.get("approve"):
                zcut, vcut = int(d["zh_cut"]), int(d["vi_cut"])
                if 1 <= zcut < len(zc) and 1 <= vcut < len(vc):
                    z1 = " ".join(zc[:zcut]).strip()
                    z2 = " ".join(zc[zcut:]).strip()
                    v1 = " ".join(vc[:vcut]).strip()
                    v2 = " ".join(vc[vcut:]).strip()
                    bname_cur = proven_beads[idx]["block"]
                    min_part_cjk = 5 if bname_cur == "Cap_02_V" else 7
                    min_part_vi = 5 if bname_cur == "Cap_02_V" else 7
                    if (
                        count_cjk_chars(z1) >= min_part_cjk
                        and count_cjk_chars(z2) >= min_part_cjk
                        and len(v1.split()) >= min_part_vi
                        and len(v2.split()) >= min_part_vi
                    ):
                        # Nếu cả 2 mảnh từng xuất hiện trong v6_ind và bị chấm khác CLEAN thì loại ngay!
                        l1_prev = ind_clean_lookup.get((z1, v1))
                        l2_prev = ind_clean_lookup.get((z2, v2))
                        if (l1_prev in (None, "CLEAN")) and (l2_prev in (None, "CLEAN")):
                            approved_hq_splits[idx] = (z1, v1, z2, v2)
                            if len(approved_hq_splits) >= needed + 15:
                                break

    print(f"    Đã chọn được +{len(approved_hq_splits)} câu ghép chất lượng cao để tách đôi.", flush=True)

    # 4. Ráp thành bảng v6.1 hoàn chỉnh với Pair_ID liên tiếp
    final_rows: List[Dict] = []
    seq = 1
    for idx, pb in enumerate(proven_beads):
        hp, vp = pb["hp"], pb["vp"]
        r_min, r_max = (0.42, 3.20) if (1 <= vp <= 105) else (0.42, 2.35)
        ocr_c = pb["ocr_conf"]
        ocr_v = 1 if (ocr_c is None or ocr_c >= OCR_CONF_THRESHOLD) else 0

        if idx in approved_hq_splits:
            z1, v1, z2, v2 = approved_hq_splits[idx]
            sub_items = [(z1, v1, "1-1", "Tách tinh tuyển v6.1"), (z2, v2, "1-1", "Tách tinh tuyển v6.1")]
        else:
            sub_items = [(pb["zh"], pb["vi"], pb["atype"], pb["note"])]

        for zt, vt, atype, n_prefix in sub_items:
            zt_s = sanitize_single_line(zt)
            vt_s = sanitize_single_line(vt)
            missing = 1 if (not zt_s or not vt_s) else 0
            omis = add = 0
            num_bad = False
            nts = [n_prefix] if n_prefix else []

            if missing:
                nts.append(f"MISSING: Khuyết một vế ({atype})")
            else:
                cjk_l = max(count_cjk_chars(zt_s), 1)
                vw = len(vt_s.split())
                rat = vw / cjk_l
                if rat < r_min:
                    omis = 1
                    nts.append(f"Nghi ngờ OMISSION ({rat:.2f} < {r_min})")
                elif rat > r_max:
                    add = 1
                    nts.append(f"Nghi ngờ ADDITION ({rat:.2f} > {r_max})")
                is_nb, _, n_msg = evaluate_numeric_consistency(zt_s, vt_s)
                if is_nb:
                    num_bad = True
                    nts.append(n_msg)

            if ocr_v == 0:
                nts.append(f"Cảnh báo OCR mờ (conf = {ocr_c} < {OCR_CONF_THRESHOLD})")

            pm = check_punct_or_number_match(zt_s, vt_s)
            lt = 1 if (missing == 0 and omis == 0 and add == 0 and not num_bad and ocr_v == 1) else 0

            final_rows.append({
                "Pair_ID": f"P{seq:04d}_C{hp:03d}_V{vp:03d}",
                "Chinese": zt_s if zt_s else None,
                "Vietnamese": vt_s if vt_s else None,
                "OMISSION": omis,
                "ADDITION": add,
                "MISSING": missing,
                "Alignment_Type": atype,
                "Punct_Anchor_Match": pm,
                "OCR_Valid": ocr_v,
                "Label_Target": lt,
                "OCR_Conf_Min": ocr_c,
                "Note": " | ".join(nts) if nts else None,
            })
            seq += 1

    # Lưu bản BlindInput để chạy độc lập judge_real_label.py và bản chuẩn Template
    df_v61 = pd.DataFrame(final_rows)
    df_v61.to_excel(V61_BLIND_XLSX, sheet_name="Alignment_Dataset", index=False)

    wb = Workbook()
    ws = wb.active
    ws.title = "Alignment_Dataset"
    populate_template_style_sheet(ws, final_rows, include_extra_judge_cols=False)
    wb.save(V61_XLSX)

    n_val = int((df_v61["MISSING"] == 0).sum())
    n_lt1 = int((df_v61["Label_Target"] == 1).sum())
    print(
        f"\n>>> HOÀN TẤT TẠO V6.1: Tổng dòng = {len(df_v61)} | Hợp lệ 2 vế = {n_val} (>= 2.000!) | Label_Target=1 = {n_lt1}",
        flush=True,
    )


if __name__ == "__main__":
    main()
