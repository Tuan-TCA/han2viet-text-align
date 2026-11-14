# align-hybird.py
import os, re, sys, subprocess, importlib.util, unicodedata
import numpy as np
import pandas as pd

# 1. Ép buộc chạy trên CPU
os.environ["CUDA_VISIBLE_DEVICES"] = ""

# 2. Đảm bảo thư mục làm việc luôn là thư mục chứa file script này
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)

def _ensure(pkg, imp=None):
    if imp is None: imp = pkg
    if importlib.util.find_spec(imp) is None:
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])

for p, i in [("pandas","pandas"),("numpy","numpy"),("openpyxl","openpyxl"),
             ("cn2vn","cn2vn"),("cn2an","cn2an"),
             ("torch","torch"),("transformers","transformers")]:
    _ensure(p, i)

import torch
import cn2vn, cn2an
from transformers import AutoModel, AutoTokenizer

# ---------- Tiền xử lý ----------
def remove_accents(t):
    return re.sub(r'[\u0300-\u036f]', '', unicodedata.normalize('NFD', str(t))).lower()

def get_sino_tokens(h):
    try: return remove_accents(cn2vn(str(h))).split()
    except: return str(h).split()

def extract_nums(text, is_han=False):
    text = str(text); nums = set()
    if is_han:
        for cn in re.findall(r'[一二三四五六七八九十百千萬万兩]+', text):
            try: nums.add(str(cn2an.cn2an(cn, "smart")))
            except: pass
    for n in re.findall(r'\d+', text): nums.add(n)
    return nums

# ---------- Dang anchors ----------
def build_anchors(df_zh, df_vi, min_len=2, max_len=8):
    anchors = {}
    vi_tokens = [remove_accents(t).split() for t in df_vi['text_vi']]
    for i, zr in df_zh.iterrows():
        zt = get_sino_tokens(zr['text_zh'])
        if len(zt) < min_len: continue
        for j, vt in enumerate(vi_tokens):
            best = 0
            for n in range(min_len, min(max_len, len(zt)) + 1):
                for s in range(len(zt) - n + 1):
                    for k in range(len(vt) - n + 1):
                        if vt[k:k+n] == zt[s:s+n]:
                            best = max(best, n); break
            if best >= min_len:
                anchors[(i, j)] = max(anchors.get((i, j), 0), best)
    return {k: v for k, v in anchors.items() if v >= min_len}

# ---------- Encoder ----------
class OmniEncoder:
    def __init__(self, model_path):
        print(f"  [Omni] Loading {model_path} (CPU)...")
        self.tok = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
        self.model = AutoModel.from_pretrained(
            model_path, trust_remote_code=True,
            device_map="cpu", torch_dtype=torch.float32,
        ).eval()

    @torch.no_grad()
    def encode(self, texts, batch_size=8):
        outs = []
        for s in range(0, len(texts), batch_size):
            batch = texts[s:s+batch_size]
            enc = self.tok(batch, padding=True, truncation=True,
                           max_length=512, return_tensors="pt")
            h = self.model(**enc).last_hidden_state
            mask = enc['attention_mask'].unsqueeze(-1).float()
            emb = (h * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
            emb = torch.nn.functional.normalize(emb, dim=-1)
            outs.append(emb.cpu().numpy())
            print(f"    [{s+len(batch)}/{len(texts)}]", end="\r")
        print()
        return np.vstack(outs)

class LaBSEEncoder:
    def __init__(self):
        from sentence_transformers import SentenceTransformer
        print("  [LaBSE] Fallback encoder...")
        self.m = SentenceTransformer("sentence-transformers/LaBSE", device="cpu")
    def encode(self, texts, batch_size=32):
        return self.m.encode(texts, convert_to_numpy=True,
                             normalize_embeddings=True, show_progress_bar=True)

# ---------- DP ----------
def dp_align(sim, anchors=None, gap=-1.0, anchor_bonus=5.0):
    """Tăng gap âm hơn (-1.0) và anchor_bonus lớn hơn (5.0) để ưu tiên neo"""
    n, m = sim.shape
    dp = np.full((n+1, m+1), -1e9); dp[0,0] = 0
    bp = np.zeros((n+1, m+1), dtype=int)
    for i in range(1, n+1): dp[i,0] = dp[i-1,0] + gap
    for j in range(1, m+1): dp[0,j] = dp[0,j-1] + gap
    for i in range(1, n+1):
        for j in range(1, m+1):
            bonus = anchor_bonus if (anchors and (i-1, j-1) in anchors) else 0.0
            best = dp[i-1][j-1] + sim[i-1][j-1] + bonus; d = 1
            if j >= 2:
                sc = dp[i-1][j-2] + (sim[i-1][j-2] + sim[i-1][j-1]) / 2
                if sc > best: best, d = sc, 2
            if i >= 2:
                sc = dp[i-2][j-1] + (sim[i-2][j-1] + sim[i-1][j-1]) / 2
                if sc > best: best, d = sc, 3
            if dp[i-1][j] + gap > best: best, d = dp[i-1][j] + gap, 4
            if dp[i][j-1] + gap > best: best, d = dp[i][j-1] + gap, 5
            dp[i][j], bp[i][j] = best, d
    out, i, j = [], n, m
    while i > 0 or j > 0:
        if i == 0: out.append(([], [j-1])); j -= 1
        elif j == 0: out.append(([i-1], [])); i -= 1
        else:
            d = bp[i][j]
            if d == 1: out.append(([i-1],[j-1])); i-=1; j-=1
            elif d == 2: out.append(([i-1],[j-2,j-1])); i-=1; j-=2
            elif d == 3: out.append(([i-2,i-1],[j-1])); i-=2; j-=1
            elif d == 4: out.append(([i-1],[])); i-=1
            else: out.append(([],[j-1])); j-=1
    out.reverse()
    return out

# ---------- Main ----------
def main():
    zh_path = r'..\03_text_sach\Cap_01\HAN\zh_cleaned.csv'
    vi_path = r'..\03_text_sach\Cap_01\VIET\vi_cleaned.csv'
    omni_path = r'..\OmniAlign\OmniAlign'
    
    print(f"Đang đọc file Hán: {zh_path}")
    print(f"Đang đọc file Việt: {vi_path}")
    
    try:
        df_zh = pd.read_csv(zh_path)
        df_vi = pd.read_csv(vi_path)
    except FileNotFoundError as e:
        print(f"\nLỖI: Không tìm thấy file. Hãy kiểm tra lại xem file có đúng vị trí không.\n{e}")
        return

    # Lọc bỏ chú thích rác trong tiếng Việt
    df_vi = df_vi[~df_vi['text_vi'].str.startswith(('Bản ', '°', ':', "''", '#'))].reset_index(drop=True)
    
    print(f"Hán: {len(df_zh)} câu | Việt: {len(df_vi)} câu (sau khi lọc rác)")

    print("\n[1/4] Sinh Dang anchors...")
    anchors = build_anchors(df_zh, df_vi)
    print(f"  -> {len(anchors)} anchor thô")

    # BỎ QUA BƯỚC LỌC VÙNG, CHẠY ALIGN TRÊN TOÀN BỘ ĐỂ GIỮ NGỮ CẢNH
    print("\n[2/4] Encode + DP (trên toàn bộ dữ liệu)...")
    try:
        enc = OmniEncoder(omni_path)
        print("  [Omni] Load thành công — dùng OmniAlign")
    except Exception as e:
        print(f"  [Omni] Lỗi: {e}")
        print("  → Fallback LaBSE")
        enc = LaBSEEncoder()

    print("  Encoding Hán...")
    zh_emb = enc.encode(df_zh['text_zh'].tolist())
    print("  Encoding Việt...")
    vi_emb = enc.encode(df_vi['text_vi'].tolist())

    sim = zh_emb @ vi_emb.T

    print("\n[3/4] Căn chỉnh (DP)...")
    alignments = dp_align(sim, anchors, gap=-1.0, anchor_bonus=5.0)

    print("\n[4/4] Xuất kết quả...")
    results = []
    for zi, vi in alignments:
        # Chỉ lấy những cặp có cả Hán và Việt
        if not zi or not vi:
            continue
            
        zh_t = "".join(df_zh.iloc[x]['text_zh'] for x in zi)
        vi_t = " ".join(df_vi.iloc[x]['text_vi'] for x in vi)
        sc = float(np.mean([sim[a][b] for a in zi for b in vi]))
        has_anchor = any((a, b) in anchors for a in zi for b in vi)
        
        results.append({
            'Han_Text': zh_t, 'Viet_Text': vi_t,
            'Score': round(sc, 3),
            'Status': 'OK' if sc >= 0.3 or has_anchor else 'LOW',
            'Anchor': 'YES' if has_anchor else ''
        })

    df_out = pd.DataFrame(results)
    out_file = 'KetQua_Omni.xlsx'
    
    with pd.ExcelWriter(out_file, engine='openpyxl') as w:
        df_out[['Han_Text','Viet_Text']].to_excel(w, sheet_name='DONG_HANG', index=False)
        df_out.to_excel(w, sheet_name='THONG_KE', index=False)
        
    print(f"\nXong! Tìm thấy {len(results)} cặp Hán-Việt.")
    print(f"Trong đó có {sum(1 for r in results if r['Anchor'] == 'YES')} cặp có Neo (Anchor).")
    print(f"File kết quả đã lưu tại: {os.path.abspath(out_file)}")

if __name__ == "__main__":
    main()