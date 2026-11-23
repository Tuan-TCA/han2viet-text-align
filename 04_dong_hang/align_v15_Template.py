# align_v15_Template.py
# Cách dùng:
#   python align_v15_Template.py <cặp> <trang_hán> [trang_việt_đầu] [trang_việt_cuối]
# Ví dụ:
#   python align_v15_Template.py 1 1            -> cặp 01, trang Hán 1, quét HẾT vi_cleaned
#   python align_v15_Template.py 1 2 5 9        -> cặp 01, trang Hán 2, chỉ lấy trang Việt 5-9
#   python align_v15_Template.py 1 2 5          -> chỉ nhập trang đầu: lấy từ trang 5 đến hết
#
# Output: KetQua_Cap01_Trang1.xlsx theo đúng mẫu (hàng 1 tiêu đề, hàng 2 mô tả, hàng 3+ dữ liệu)
import os, re, sys, subprocess, importlib.util, unicodedata
import numpy as np
import pandas as pd

def _ensure(pkg, imp=None):
    if imp is None: imp = pkg
    if importlib.util.find_spec(imp) is None:
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])

for p, i in [("pandas","pandas"),("numpy","numpy"),("openpyxl","openpyxl"),
             ("cn2vn","cn2vn"),("cn2an","cn2an"),("torch","torch"),
             ("transformers","transformers")]:
    _ensure(p, i)

os.environ["CUDA_VISIBLE_DEVICES"] = ""
import torch
import cn2vn, cn2an
from transformers import AutoModel, AutoTokenizer
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)

# ====== CẤU HÌNH ======
SENT_PER_PAGE = 16        # mỗi trang Hán có 16 câu


def make_pair_id(cap, sent_no):
    # Đổi định dạng ID ở đây nếu cần. Ví dụ: C001_V001
    return f"C{cap:03d}_V{sent_no:03d}"


# ====== TIỆN ÍCH VĂN BẢN ======
def remove_accents(t):
    return re.sub(r'[\u0300-\u036f]', '', unicodedata.normalize('NFD', str(t))).lower()

def get_sino_tokens(h):
    try: return remove_accents(cn2vn(str(h))).split()
    except: return str(h).split()

def split_vi_text(text):
    text = str(text)
    chunks = re.split(r'(?<=[.;?!,])\s+', text)
    return [c.strip() for c in chunks if len(c.strip()) > 5]


def build_anchor_matrix(df_zh, df_vi, min_len=2, max_len=10):
    n, m = len(df_zh), len(df_vi)
    S_anchor = np.zeros((n, m))
    vi_tokens = [remove_accents(t).split() for t in df_vi['text_vi']]
    for i, zr in df_zh.iterrows():
        zt = get_sino_tokens(zr['text_zh'])
        if len(zt) < min_len: continue
        for j, vt in enumerate(vi_tokens):
            best = 0
            for n_len in range(min_len, min(max_len, len(zt)) + 1):
                for s in range(len(zt) - n_len + 1):
                    for k in range(len(vt) - n_len + 1):
                        if vt[k:k+n_len] == zt[s:s+n_len]:
                            best = max(best, n_len)
            if best > 0:
                S_anchor[i, j] = best
    return S_anchor


class OmniEncoder:
    def __init__(self, model_path):
        self.tok = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
        self.model = AutoModel.from_pretrained(
            model_path, trust_remote_code=True, device_map="cpu", torch_dtype=torch.float32
        ).eval()

    @torch.no_grad()
    def encode(self, texts, batch_size=8):
        outs = []
        for s in range(0, len(texts), batch_size):
            batch = texts[s:s+batch_size]
            enc = self.tok(batch, padding=True, truncation=True, max_length=1024, return_tensors="pt")
            h = self.model(**enc).last_hidden_state
            mask = enc['attention_mask'].unsqueeze(-1).float()
            emb = (h * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
            emb = torch.nn.functional.normalize(emb, dim=-1)
            outs.append(emb.cpu().numpy())
        return np.vstack(outs)


# ====== DP CĂN CHỈNH ======
def _backtrace(bp, n, m):
    out, i, j = [], n, m
    while i > 0 or j > 0:
        if i == 0: out.append(([], [j-1])); j -= 1
        elif j == 0: out.append(([i-1], [])); i -= 1
        else:
            d = bp[i][j]
            if d == 1: out.append(([i-1], [j-1])); i -= 1; j -= 1
            elif d == 2: out.append(([i-1], [j-2, j-1])); i -= 1; j -= 2
            elif d == 4: out.append(([i-2, i-1], [j-1])); i -= 2; j -= 1
            elif d == 7: out.append(([i-1], [])); i -= 1
            else: out.append(([], [j-1])); j -= 1
    out.reverse()
    return out


def standard_dp_align(S, gap=-1.5):
    n, m = S.shape
    dp = np.full((n+1, m+1), -1e9); dp[0, 0] = 0
    bp = np.zeros((n+1, m+1), dtype=int)
    for i in range(1, n+1): dp[i, 0] = dp[i-1, 0] + gap
    for j in range(1, m+1): dp[0, j] = dp[0, j-1] + gap
    for i in range(1, n+1):
        for j in range(1, m+1):
            best = dp[i-1][j-1] + S[i-1][j-1]; d = 1
            if j >= 2:
                sc = dp[i-1][j-2] + (S[i-1][j-2] + S[i-1][j-1]) / 2
                if sc > best: best, d = sc, 2
            if i >= 2:
                sc = dp[i-2][j-1] + (S[i-2][j-1] + S[i-1][j-1]) / 2
                if sc > best: best, d = sc, 4
            if dp[i-1][j] + gap > best: best, d = dp[i-1][j] + gap, 7
            if dp[i][j-1] + gap > best: best, d = dp[i][j-1] + gap, 8
            dp[i][j], bp[i][j] = best, d
    return _backtrace(bp, n, m)


def dynamic_window_dp(S, hard_anchors, gap=-2.0):
    n, m = S.shape
    dp = np.full((n+1, m+1), -1e9); dp[0, 0] = 0
    bp = np.zeros((n+1, m+1), dtype=int)
    window_bounds = {}
    for i in range(n):
        lower_bound = 0; upper_bound = m
        for (ai, aj) in hard_anchors:
            if ai < i: lower_bound = max(lower_bound, aj)
            elif ai > i: upper_bound = min(upper_bound, aj)
        window_bounds[i] = (max(0, lower_bound - 5), min(m, upper_bound + 5))

    for i in range(1, n+1):
        for j in range(1, m+1):
            w_start, w_end = window_bounds[i-1]
            if not (w_start <= j-1 <= w_end):
                dp[i][j] = -1e9; continue
            best = dp[i-1][j-1] + S[i-1][j-1]; d = 1
            if j >= 2:
                sc = dp[i-1][j-2] + (S[i-1][j-2] + S[i-1][j-1]) / 2
                if sc > best: best, d = sc, 2
            if i >= 2:
                sc = dp[i-2][j-1] + (S[i-2][j-1] + S[i-1][j-1]) / 2
                if sc > best: best, d = sc, 4
            if dp[i-1][j] + gap > best: best, d = dp[i-1][j] + gap, 7
            if dp[i][j-1] + gap > best: best, d = dp[i][j-1] + gap, 8
            dp[i][j], bp[i][j] = best, d
    return _backtrace(bp, n, m)


def to_index_map(align, n_zh):
    """Chỉ số câu Hán -> danh sách chỉ số mảnh Việt (gộp 2 câu Hán thì cùng nhận chung)."""
    m = {i: [] for i in range(n_zh)}
    for zi, vi in align:
        for z in zi:
            m[z] = vi
    return m


# ====== XUẤT EXCEL THEO MẪU ======
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

HEADER_COLORS = ["1F4E79", "1F4E79", "1F4E79",      # A-C
                 "843C0C", "843C0C", "843C0C",      # D-F
                 "2F5597", "2F5597",                # G-H
                 "375623",                          # I
                 "2F5597",                          # J
                 "1F4E79"]                          # K

COL_WIDTHS = [16, 40, 70, 14, 14, 14, 18, 20, 18, 16, 60]


def write_template_xlsx(rows, out_file):
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"

    thin = Side(style="thin", color="BFBFBF")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    # Hàng 1: tiêu đề
    for c, (h, color) in enumerate(zip(HEADERS, HEADER_COLORS), start=1):
        cell = ws.cell(row=1, column=c, value=h)
        cell.font = Font(bold=True, color="FFFFFF", size=12)
        cell.fill = PatternFill("solid", start_color=color, end_color=color)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border

    # Hàng 2: mô tả
    for c, d in enumerate(DESCRIPTIONS, start=1):
        cell = ws.cell(row=2, column=c, value=d)
        cell.font = Font(italic=True, size=10)
        cell.fill = PatternFill("solid", start_color="D9E1F2", end_color="D9E1F2")
        cell.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
        cell.border = border

    # Hàng 3+: dữ liệu
    for r, row in enumerate(rows, start=3):
        values = [row['Pair_ID'], row['Chinese'], row['Vietnamese'],
                  None, None, None, None, None, None, None, row['Note']]
        for c, v in enumerate(values, start=1):
            cell = ws.cell(row=r, column=c, value=v)
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = border

    for c, w in enumerate(COL_WIDTHS, start=1):
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.row_dimensions[1].height = 32
    ws.row_dimensions[2].height = 105
    ws.freeze_panes = "A3"

    wb.save(out_file)


def find_han_file(han_dir, page):
    seen = set()
    for width in range(1, 8):
        name = f"{page:0{width}d}-cleaned.csv"
        if name in seen: continue
        seen.add(name)
        p = os.path.join(han_dir, name)
        if os.path.exists(p):
            return p
    return None


def main():
    if len(sys.argv) < 3:
        print("Cách dùng: python align_v15_Template.py <cặp> <trang_hán> [trang_việt_đầu] [trang_việt_cuối]")
        return

    cap = int(sys.argv[1])
    page = int(sys.argv[2])
    vi_start = int(sys.argv[3]) if len(sys.argv) >= 4 else None   # None = từ đầu file
    vi_end = int(sys.argv[4]) if len(sys.argv) >= 5 else None     # None = đến hết file

    base_dir = os.path.dirname(SCRIPT_DIR)
    cap_dir = os.path.join(base_dir, '03_text_sach', f'Cap_{cap:02d}')
    han_dir = os.path.join(cap_dir, 'HAN')
    vi_path = os.path.join(cap_dir, 'VIET', 'vi_cleaned.csv')
    omni_path = os.path.join(base_dir, 'OmniAlign', 'OmniAlign')

    zh_path = find_han_file(han_dir, page)
    if zh_path is None:
        print(f"Không tìm thấy file Hán cho trang {page} trong: {han_dir}")
        return

    df_zh = pd.read_csv(zh_path, encoding='utf-8-sig')
    df_zh = df_zh.dropna(subset=['text_zh']).reset_index(drop=True)
    df_vi = pd.read_csv(vi_path, encoding='utf-8-sig')

    # Lọc trang Việt (mặc định: quét hết file)
    if vi_start is not None:
        df_vi = df_vi[df_vi['page_start'] >= vi_start]
    if vi_end is not None:
        df_vi = df_vi[df_vi['page_start'] <= vi_end]
    df_vi = df_vi.reset_index(drop=True)

    if df_vi.empty:
        print(f"Không có dòng Việt nào trong khoảng trang {vi_start}-{vi_end}.")
        return

    vi_range_txt = (f"{df_vi['page_start'].min()}-{df_vi['page_start'].max()}")

    # Cắt mảnh, nhớ dòng gốc + trang Việt
    new_rows = []
    for row_id, row in df_vi.iterrows():
        for chunk in split_vi_text(row['text_vi']):
            new_rows.append({
                'page_start': row['page_start'],
                'text_vi': chunk,             # mảnh: dùng cho embedding/anchor
                'row_id': row_id,             # chỉ số dòng gốc (sau khi lọc trang)
                'row_text': row['text_vi'],   # nguyên văn dòng gốc
            })
    df_vi = pd.DataFrame(new_rows).reset_index(drop=True)

    print(f"Cặp {cap} | Trang Hán {page} | Hán: {len(df_zh)} câu | "
          f"Việt (trang {vi_range_txt}): {len(df_vi)} mảnh vụn")

    print("\n[1/4] Trích xuất đặc trưng...")
    S_ANC = build_anchor_matrix(df_zh, df_vi)
    enc = OmniEncoder(omni_path)
    zh_emb = enc.encode(df_zh['text_zh'].tolist())
    vi_emb = enc.encode(df_vi['text_vi'].tolist())
    S_SEM = zh_emb @ vi_emb.T
    S_total = (1.0 * S_SEM) + (5.0 * S_ANC)

    print("\n[2/4] Tìm Hard Anchors...")
    hard_anchors = []
    for i in range(len(df_zh)):
        for j in range(len(df_vi)):
            if S_ANC[i, j] >= 3:
                hard_anchors.append((i, j))
    hard_rows = {ai for (ai, aj) in hard_anchors}

    print("\n[3/4] Chạy song song v1 và v6...")
    align_v1 = standard_dp_align(S_total, gap=-1.5)
    map_v1 = to_index_map(align_v1, len(df_zh))

    S_total_v6 = S_total.copy()
    for (i, j) in hard_anchors:
        S_total_v6[i, j] += 100.0
    align_v6 = dynamic_window_dp(S_total_v6, hard_anchors, gap=-2.0)
    map_v6 = to_index_map(align_v6, len(df_zh))

    print("\n[4/4] Fusion + xuất Excel theo mẫu...")
    row_info = df_vi.drop_duplicates('row_id').set_index('row_id')[['row_text', 'page_start']]

    def chunks_to_text(idx):
        return " ".join(df_vi.iloc[x]['text_vi'] for x in idx)

    def chunks_to_row_ids(idx):
        return list(dict.fromkeys(int(df_vi.iloc[x]['row_id']) for x in idx))

    out_rows = []
    for i in range(len(df_zh)):
        idx_v1, idx_v6 = map_v1[i], map_v6[i]
        text_v1 = chunks_to_text(idx_v1)

        if i in hard_rows:
            idx = idx_v1
        elif len(text_v1) > 200 or not idx_v1:
            idx = idx_v6
        else:
            idx = idx_v1

        rids = chunks_to_row_ids(idx)
        viet_text = " ".join(str(row_info.loc[r, 'row_text']) for r in rids)   # câu/dòng Việt đầy đủ
        viet_pages = list(dict.fromkeys(int(row_info.loc[r, 'page_start']) for r in rids))
        cum = chunks_to_text(idx)                                              # cụm (mảnh) khớp

        k = i + 1                                           # câu thứ k trên trang
        sent_no = (page - 1) * SENT_PER_PAGE + k            # số câu toàn cục (16 câu/trang)

        note = (f"Cụm: {cum if cum else '(không có)'} | "
                f"Trang: {page} (Việt: {', '.join(map(str, viet_pages)) if viet_pages else '-'}) | "
                f"Câu: {k}")

        out_rows.append({
            'Pair_ID': make_pair_id(cap, sent_no),
            'Chinese': df_zh.iloc[i]['text_zh'],
            'Vietnamese': viet_text,
            'Note': note,
        })

    out_file = f'KetQua_Cap{cap:02d}_Trang{page}.xlsx'
    write_template_xlsx(out_rows, out_file)
    print(f"\nHoàn tất! Lưu tại: {out_file}")


if __name__ == "__main__":
    main()
