#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Căn chỉnh Hán–Việt, sửa lỗi DP/anchors/fusion của align_v15_Template.py.

Usage:
    python align_v16_fixed.py <cap> <trang_han> [trang_viet_dau] [trang_viet_cuoi]

Cần các gói: numpy pandas openpyxl torch transformers cn2vn
Cần mô hình OmniAlign local theo cấu trúc dự án gốc.
"""

import argparse
import os
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

SENT_PER_PAGE = 16
SCRIPT_DIR = Path(__file__).resolve().parent

HEADERS = ["Pair_ID", "Chinese", "Vietnamese", "OMISSION", "ADDITION", "MISSING",
           "Alignment_Type", "Punct_Anchor_Match", "Label_Target", "OCR_Conf_Min", "Note"]
DESCRIPTIONS = [
    "Mã định danh cặp câu (VD: C001_V001) là số trang pdf Hán - Việt trong phần được cấp",
    "Câu hoặc cặp câu tiếng Hán trích xuất từ ảnh nguồn",
    "Câu hoặc cặp câu tiếng Việt tương ứng trích xuất từ ảnh đích",
    "1 (True) / 0 (False): Thiếu nội dung vế Việt bỏ phần quan trọng của vế Hán hoặc mất đoạn nguồn",
    "1 (True) / 0 (False): Thừa nội dung vế Việt chứa câu khác, chú thích lệch hoặc sai phạm vi cặp",
    "1 (True) / 0 (False): Khuyết toàn bộ vế Hán hoặc Việt (1-0, 0-1) hoặc đoạn tương ứng bị bỏ sót",
    "Loại liên kết: 1-1 (đơn), 1-N (tách câu), N-1 (gộp câu), N-M, 1-0, 0-1",
    "1 / 0: Khớp dấu câu đặc biệt ( ?, !, ;, :, « ») hoặc số đếm/niên hiệu Hán-Việt",
    "Nhãn huấn luyện cuối cùng: 1 (Aligned chuẩn) / 0 (Misaligned - có lỗi Omission/Addition/Missing)",
    "Độ tin cậy OCR thấp nhất của các ký tự trong cặp câu [0.0 - 1.0] để lọc nhiều ảnh mờ",
    "Ghi chú chi tiết lỗi OCR, dị bản chữ Hán/Nôm hoặc giải thích chú thích công cụ sử dụng (nếu có)",
]
HEADER_COLORS = ["1F4E79"] * 3 + ["843C0C"] * 3 + ["2F5597"] * 2 + ["375623", "2F5597", "1F4E79"]
COL_WIDTHS = [16, 40, 70, 14, 14, 14, 18, 20, 18, 16, 60]


def make_pair_id(cap, sent_no):
    return f"C{cap:03d}_V{sent_no:03d}"


def remove_accents(text):
    s = unicodedata.normalize("NFD", str(text).lower())
    return re.sub(r"[\u0300-\u036f]", "", s).replace("đ", "d")


def word_tokens(text):
    return re.findall(r"[^\W_]+", remove_accents(text), flags=re.UNICODE)


def get_sino_tokens(text):
    from cn2vn import cn2vn
    return word_tokens(cn2vn(str(text)))


def split_vi_text(text):
    if pd.isna(text):
        return []
    chunks = re.split(r"(?<=[.;?!,])\s+", str(text).strip())
    # Không bỏ mất câu ngắn, vì DP phải biết các mảnh đầu vào.
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def build_anchor_matrix(df_zh, df_vi, min_len=2, max_len=10):
    """Longest common *contiguous* token n-gram; dùng inverted index thay vòng lặp bậc cao."""
    zh_tokens = [get_sino_tokens(t) for t in df_zh['text_zh']]
    vi_tokens = [word_tokens(t) for t in df_vi['text_vi']]
    mat = np.zeros((len(zh_tokens), len(vi_tokens)), dtype=np.float32)
    if not zh_tokens or not vi_tokens:
        return mat

    index = defaultdict(set)
    for j, tokens in enumerate(vi_tokens):
        for k in range(min_len, min(max_len, len(tokens)) + 1):
            for start in range(len(tokens) - k + 1):
                index[tuple(tokens[start:start + k])].add(j)
    for i, tokens in enumerate(zh_tokens):
        for k in range(min_len, min(max_len, len(tokens)) + 1):
            for start in range(len(tokens) - k + 1):
                for j in index.get(tuple(tokens[start:start + k]), ()):
                    mat[i, j] = max(mat[i, j], k)
    return mat


class OmniEncoder:
    def __init__(self, model_path):
        import torch
        from transformers import AutoModel, AutoTokenizer
        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(str(model_path), trust_remote_code=True)
        self.model = AutoModel.from_pretrained(
            str(model_path), trust_remote_code=True, torch_dtype=torch.float32
        ).to('cpu').eval()

    def encode(self, texts, batch_size=8):
        if not texts:
            return np.empty((0, 0), dtype=np.float32)
        outs = []
        with self.torch.no_grad():
            for start in range(0, len(texts), batch_size):
                batch = list(texts[start:start + batch_size])
                enc = self.tok(batch, padding=True, truncation=True, max_length=1024, return_tensors="pt")
                outputs = self.model(**enc)
                h = outputs.last_hidden_state
                mask = enc['attention_mask'].unsqueeze(-1).float()
                emb = (h * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
                outs.append(self.torch.nn.functional.normalize(emb, dim=-1).cpu().numpy())
        return np.vstack(outs)


def select_monotonic_anchors(anchor_matrix, min_strength=3):
    """Chọn một chuỗi anchor tăng nghiêm ngặt theo cả chỉ số Hán và Việt.

    Tránh khóa các anchor đảo thứ tự hoặc nhiều anchor cùng hàng/cột.
    """
    candidates = [(i, j, float(anchor_matrix[i, j]))
                  for i, j in np.argwhere(anchor_matrix >= min_strength)]
    candidates.sort()
    if not candidates:
        return []
    best = [w for _, _, w in candidates]
    prev = [-1] * len(candidates)
    for k, (i, j, weight) in enumerate(candidates):
        for p in range(k):
            pi, pj, _ = candidates[p]
            if pi < i and pj < j and best[p] + weight > best[k]:
                best[k], prev[k] = best[p] + weight, p
    idx = max(range(len(candidates)), key=best.__getitem__)
    result = []
    while idx != -1:
        result.append((candidates[idx][0], candidates[idx][1]))
        idx = prev[idx]
    return list(reversed(result))


def build_similarity_matrix(semantic, anchors, anchor_weight=1.5):
    """Chuẩn hóa cosine về [0,1], anchor capped về [0,1].
    Không có cộng +100 ép anchor; DP quyết định đường đi toàn cục.
    """
    if semantic.shape != anchors.shape:
        raise ValueError("Semantic và anchor matrix không cùng kích thước")
    semantic_scaled = np.clip((np.asarray(semantic, dtype=float) + 1.0) / 2.0, 0, 1)
    anchor_scaled = np.clip(np.asarray(anchors, dtype=float) / 5.0, 0, 1)
    return semantic_scaled + anchor_weight * anchor_scaled


# Các trạng thái: 1=1-1, 2=1-2, 4=2-1, 7=1-0, 8=0-1
MOVES = {1: (1, 1), 2: (1, 2), 4: (2, 1), 7: (1, 0), 8: (0, 1)}


def _backtrace(bp, n, m):
    result, i, j = [], n, m
    while i or j:
        d = int(bp[i, j])
        if d not in MOVES:
            raise RuntimeError(f"Backtrace không hợp lệ tại ({i},{j}); không có đường DP")
        di, dj = MOVES[d]
        if di > i or dj > j:
            raise RuntimeError(f"Backtrace vượt biên tại ({i},{j}) với move {d}")
        result.append((list(range(i - di, i)), list(range(j - dj, j))))
        i -= di
        j -= dj
    return list(reversed(result))


def standard_dp_align(S, gap=-1.5, allowed=None):
    """Global DP liên tục, hỗ trợ 1-1, 1-2, 2-1 và gap.

    allowed: boolean mask (n,m) nếu cần giới hạn ô ghép; gap không bị khóa.
    """
    S = np.asarray(S, dtype=float)
    if S.ndim != 2 or not np.isfinite(S).all():
        raise ValueError("S phải là ma trận 2D có giá trị hữu hạn")
    n, m = S.shape
    if allowed is not None:
        allowed = np.asarray(allowed, dtype=bool)
        if allowed.shape != S.shape:
            raise ValueError("allowed sai kích thước")
    dp = np.full((n + 1, m + 1), -np.inf, dtype=float)
    bp = np.zeros((n + 1, m + 1), dtype=np.int8)
    dp[0, 0] = 0
    for i in range(1, n + 1):
        dp[i, 0], bp[i, 0] = dp[i - 1, 0] + gap, 7
    for j in range(1, m + 1):
        dp[0, j], bp[0, j] = dp[0, j - 1] + gap, 8

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            candidates = [(dp[i - 1, j] + gap, 7), (dp[i, j - 1] + gap, 8)]
            if allowed is None or allowed[i - 1, j - 1]:
                candidates.append((dp[i - 1, j - 1] + S[i - 1, j - 1], 1))
            if j >= 2 and (allowed is None or (allowed[i - 1, j - 2] and allowed[i - 1, j - 1])):
                candidates.append((dp[i - 1, j - 2] + (S[i - 1, j - 2] + S[i - 1, j - 1]) / 2, 2))
            if i >= 2 and (allowed is None or (allowed[i - 2, j - 1] and allowed[i - 1, j - 1])):
                candidates.append((dp[i - 2, j - 1] + (S[i - 2, j - 1] + S[i - 1, j - 1]) / 2, 4))
            dp[i, j], bp[i, j] = max(candidates, key=lambda x: x[0])
    if not np.isfinite(dp[n, m]):
        raise RuntimeError("Không thể tìm đường căn chỉnh")
    return _backtrace(bp, n, m)


def dynamic_window_dp(S, hard_anchors, gap=-1.5, margin=5):
    """Giới hạn tương ứng với các anchor tăng thứ tự; nếu bị chặn, fallback global DP.

    Lưu ý: anchor là gợi ý vị trí, không phải ràng buộc bắt buộc.
    """
    n, m = S.shape
    anchors = sorted(set(hard_anchors))
    if any(not (0 <= i < n and 0 <= j < m) for i, j in anchors):
        raise ValueError('Anchor ngoài giới hạn')
    if any(i >= ni or j >= nj for (i, j), (ni, nj) in zip(anchors, anchors[1:])):
        raise ValueError('Hard anchors mâu thuẫn thứ tự')
    if not anchors:
        return standard_dp_align(S, gap=gap)
    allowed = np.ones((n, m), dtype=bool)
    for i in range(n):
        before = [j for ai, j in anchors if ai < i]
        after = [j for ai, j in anchors if ai > i]
        lo = max(0, (max(before) if before else 0) - margin)
        hi = min(m - 1, (min(after) if after else m - 1) + margin)
        allowed[i, :] = False
        if lo <= hi:
            allowed[i, lo:hi + 1] = True
        own = [j for ai, j in anchors if ai == i]
        for j in own:
            allowed[i, j] = True
    return standard_dp_align(S, gap=gap, allowed=allowed)


def to_index_map(align, n_zh):
    result = {i: [] for i in range(n_zh)}
    for zi, vi in align:
        for z in zi:
            if result[z]:
                raise ValueError(f"Câu Hán {z} được ghi hai lần")
            result[z] = list(vi)
    return result


def validate_alignment(align, n, m):
    """Mỗi Hán/mảnh Việt xuất hiện đúng 1 lần trong path (gộp 2-1 là một step)."""
    z_ids = [z for zi, _ in align for z in zi]
    v_ids = [v for _, vi in align for v in vi]
    if z_ids != list(range(n)) or v_ids != list(range(m)):
        raise ValueError("Alignment trùng/lệch thứ tự/bỏ sót index")
    if any((len(z), len(v)) not in {(1, 1), (1, 2), (2, 1), (1, 0), (0, 1)} for z, v in align):
        raise ValueError("Phép gộp không hợp lệ")


def write_template_xlsx(rows, out_file):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    ws = wb.active
    ws.title = 'Sheet1'
    thin = Side(style='thin', color='BFBFBF')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    for c, (header, color) in enumerate(zip(HEADERS, HEADER_COLORS), 1):
        cell = ws.cell(row=1, column=c, value=header)
        cell.font = Font(bold=True, color='FFFFFF', size=12)
        cell.fill = PatternFill('solid', start_color=color, end_color=color)
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        cell.border = border
    for c, description in enumerate(DESCRIPTIONS, 1):
        cell = ws.cell(row=2, column=c, value=description)
        cell.font = Font(italic=True, size=10)
        cell.fill = PatternFill('solid', start_color='D9E1F2', end_color='D9E1F2')
        cell.alignment = Alignment(horizontal='left', vertical='top', wrap_text=True)
        cell.border = border
    for r, row in enumerate(rows, 3):
        values = [row['Pair_ID'], row['Chinese'], row['Vietnamese'],
                  None, None, None, None, None, None, None, row['Note']]
        for c, value in enumerate(values, 1):
            cell = ws.cell(row=r, column=c, value=value)
            cell.alignment = Alignment(vertical='top', wrap_text=True)
            cell.border = border
    for c, width in enumerate(COL_WIDTHS, 1):
        ws.column_dimensions[get_column_letter(c)].width = width
    ws.row_dimensions[1].height = 32
    ws.row_dimensions[2].height = 105
    ws.freeze_panes = 'A3'
    wb.save(str(out_file))


def find_han_file(han_dir, page):
    for width in range(1, 8):
        p = han_dir / f'{page:0{width}d}-cleaned.csv'
        if p.exists():
            return p
    return None


def run(cap, page, vi_start=None, vi_end=None, base_dir=None, model_dir=None, output_dir=None):
    base_dir = Path(base_dir) if base_dir else SCRIPT_DIR.parent
    cap_dir = base_dir / '03_text_sach' / f'Cap_{cap:02d}'
    han_path = find_han_file(cap_dir / 'HAN', page)
    if han_path is None:
        raise FileNotFoundError(f'Không tìm thấy CSV Hán trang {page} trong {cap_dir / "HAN"}')
    viet_path = cap_dir / 'VIET' / 'vi_cleaned.csv'
    df_zh = pd.read_csv(han_path, encoding='utf-8-sig')
    df_vi = pd.read_csv(viet_path, encoding='utf-8-sig')
    if 'text_zh' not in df_zh.columns or not {'text_vi', 'page_start'}.issubset(df_vi.columns):
        raise ValueError('CSV phải chứa text_zh; và text_vi, page_start tương ứng')
    df_zh = df_zh.dropna(subset=['text_zh']).reset_index(drop=True)
    df_vi = df_vi.dropna(subset=['text_vi', 'page_start'])
    if vi_start is not None:
        df_vi = df_vi[df_vi['page_start'] >= vi_start]
    if vi_end is not None:
        df_vi = df_vi[df_vi['page_start'] <= vi_end]
    df_vi = df_vi.reset_index(drop=True)
    if df_zh.empty or df_vi.empty:
        raise ValueError('Không có câu Hán hoặc dòng Việt trong phạm vi đã chọn')
    vi_range = f"{df_vi['page_start'].min()}-{df_vi['page_start'].max()}"

    pieces = []
    for row_id, row in df_vi.iterrows():
        for chunk in split_vi_text(row['text_vi']):
            pieces.append({'page_start': row['page_start'], 'text_vi': chunk, 'row_id': row_id})
    df_chunks = pd.DataFrame(pieces)
    if df_chunks.empty:
        raise ValueError('Không tạo được mảnh Việt hợp lệ')
    print(f'Cặp {cap} | Trang Hán {page} | Hán {len(df_zh)} | Việt ({vi_range}): {len(df_chunks)} mảnh')

    print('[1/3] Embeddings và anchors...')
    S_ANC = build_anchor_matrix(df_zh, df_chunks)
    enc = OmniEncoder(model_dir or base_dir / 'OmniAlign' / 'OmniAlign')
    zh_emb = enc.encode(df_zh['text_zh'].astype(str).tolist())
    vi_emb = enc.encode(df_chunks['text_vi'].astype(str).tolist())
    S_SEM = zh_emb @ vi_emb.T
    S = build_similarity_matrix(S_SEM, S_ANC)
    anchors = select_monotonic_anchors(S_ANC, min_strength=3)
    print(f'[2/3] DP toàn cục (anchor hợp thứ tự: {len(anchors)})...')
    # Thêm bonus nhẹ cho anchor nhất quán, không ép +100 như bản cũ.
    for i, j in anchors:
        S[i, j] += 0.5
    alignment = standard_dp_align(S, gap=-1.5)
    validate_alignment(alignment, len(df_zh), len(df_chunks))

    # Không fusion hai đường DP: một đường toàn cục giữ đúng thứ tự.
    # Xuất text mảnh thay vì nguyên 'row_text' để tránh lặp nguyên văn khi một
    # dòng nguồn bị chia thành nhiều mảnh và rơi vào các câu Hán khác nhau.
    print('[3/3] Xuất Excel...')
    by_zh = to_index_map(alignment, len(df_zh))
    rows = []
    for i in range(len(df_zh)):
        indices = by_zh[i]
        texts = [str(df_chunks.iloc[j]['text_vi']) for j in indices]
        pages = list(dict.fromkeys(str(df_chunks.iloc[j]['page_start']) for j in indices))
        orig_rows = list(dict.fromkeys(str(df_chunks.iloc[j]['row_id']) for j in indices))
        text = ' '.join(texts)
        sent_no = (page - 1) * SENT_PER_PAGE + i + 1
        rows.append({
            'Pair_ID': make_pair_id(cap, sent_no),
            'Chinese': str(df_zh.iloc[i]['text_zh']),
            'Vietnamese': text,
            'Note': f"Cụm: {text or '(không có)'} | Trang: {page} (Việt: {', '.join(pages) or '-'}) | "
                    f"Dòng Việt: {', '.join(orig_rows) or '-'} | Câu: {i + 1}",
        })
    out_dir = Path(output_dir) if output_dir else SCRIPT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    outfile = out_dir / f'KetQua_Cap{cap:02d}_Trang{page}.xlsx'
    write_template_xlsx(rows, outfile)
    # Không tự gán nhãn huấn luyện hay OCR confidence khi chưa có ground truth.
    print(f'Hoàn tất: {outfile}')
    return outfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cap', type=int)
    parser.add_argument('page', type=int)
    parser.add_argument('vi_start', nargs='?', type=int, default=None)
    parser.add_argument('vi_end', nargs='?', type=int, default=None)
    parser.add_argument('--base-dir', type=Path, default=None)
    parser.add_argument('--model-dir', type=Path, default=None)
    parser.add_argument('--output-dir', type=Path, default=None)
    args = parser.parse_args()
    run(args.cap, args.page, args.vi_start, args.vi_end,
        base_dir=args.base_dir, model_dir=args.model_dir, output_dir=args.output_dir)


if __name__ == '__main__':
    main()
