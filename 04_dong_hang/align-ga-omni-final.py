# align_final.py — Bản ổn định (OmniAlign + DP + Smart Split)
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

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)

def remove_accents(t):
    return re.sub(r'[\u0300-\u036f]', '', unicodedata.normalize('NFD', str(t))).lower()

def get_sino_tokens(h):
    try: return remove_accents(cn2vn(str(h))).split()
    except: return str(h).split()

def split_vi_text(text):
    """Cắt thông minh tại tất cả các dấu câu (kể cả dấu phẩy)"""
    text = str(text)
    # Cắt tại chấm, chấm phẩy, chấm hỏi, chấm than VÀ dấu phẩy
    chunks = re.split(r'(?<=[.;?!,])\s+', text)
    # Giữ lại các đoạn > 5 ký tự để tránh các mảnh vụn vô nghĩa
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
                           max_length=1024, return_tensors="pt")
            h = self.model(**enc).last_hidden_state
            mask = enc['attention_mask'].unsqueeze(-1).float()
            emb = (h * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
            emb = torch.nn.functional.normalize(emb, dim=-1)
            outs.append(emb.cpu().numpy())
        return np.vstack(outs)

def dp_align(S, gap=-1.0, anchor_bonus=5.0):
    n, m = S.shape
    dp = np.full((n+1, m+1), -1e9); dp[0,0] = 0
    bp = np.zeros((n+1, m+1), dtype=int)
    for i in range(1, n+1): dp[i,0] = dp[i-1,0] + gap
    for j in range(1, m+1): dp[0,j] = dp[0,j-1] + gap
    for i in range(1, n+1):
        for j in range(1, m+1):
            best = dp[i-1][j-1] + S[i-1][j-1]; d = 1
            if j >= 2:
                sc = dp[i-1][j-2] + (S[i-1][j-2] + S[i-1][j-1]) / 2
                if sc > best: best, d = sc, 2
            if j >= 3:
                sc = dp[i-1][j-3] + (S[i-1][j-3] + S[i-1][j-2] + S[i-1][j-1]) / 3
                if sc > best: best, d = sc, 3
            if j >= 4:
                sc = dp[i-1][j-4] + (S[i-1][j-4] + S[i-1][j-3] + S[i-1][j-2] + S[i-1][j-1]) / 4
                if sc > best: best, d = sc, 6
            if i >= 2:
                sc = dp[i-2][j-1] + (S[i-2][j-1] + S[i-1][j-1]) / 2
                if sc > best: best, d = sc, 4
            if dp[i-1][j] + gap > best: best, d = dp[i-1][j] + gap, 7
            if dp[i][j-1] + gap > best: best, d = dp[i][j-1] + gap, 8
            dp[i][j], bp[i][j] = best, d
    out, i, j = [], n, m
    while i > 0 or j > 0:
        if i == 0: out.append(([], [j-1])); j -= 1
        elif j == 0: out.append(([i-1], [])); i -= 1
        else:
            d = bp[i][j]
            if d == 1: out.append(([i-1],[j-1])); i-=1; j-=1
            elif d == 2: out.append(([i-1],[j-2,j-1])); i-=1; j-=2
            elif d == 3: out.append(([i-1],[j-3,j-2,j-1])); i-=1; j-=3
            elif d == 4: out.append(([i-2,i-1],[j-1])); i-=2; j-=1
            elif d == 6: out.append(([i-1],[j-4,j-3,j-2,j-1])); i-=1; j-=4
            elif d == 7: out.append(([i-1],[])); i-=1
            else: out.append(([],[j-1])); j-=1
    out.reverse()
    return out

def main():
    zh_path = r'..\03_text_sach\Cap_01\HAN\zh_cleaned.csv'
    vi_path = r'..\03_text_sach\Cap_01\VIET\vi_cleaned.csv'
    omni_path = r'..\OmniAlign\OmniAlign'

    df_zh = pd.read_csv(zh_path)
    df_vi = pd.read_csv(vi_path)
    
    # 1. LỌC TRANG
    df_vi = df_vi[(df_vi['page_start'] >= 186) & (df_vi['page_start'] <= 188)]
    
    # 2. BĂM NHỎ TẠI DẤU PHẨY
    new_rows = []
    for _, row in df_vi.iterrows():
        for chunk in split_vi_text(row['text_vi']):
            new_rows.append({'page_start': row['page_start'], 'text_vi': chunk})
    df_vi = pd.DataFrame(new_rows).reset_index(drop=True)
    
    print(f"Hán: {len(df_zh)} câu | Việt: {len(df_vi)} câu (Đã băm nhỏ)")

    print("\n[1/3] Trích xuất đặc trưng...")
    S_ANC = build_anchor_matrix(df_zh, df_vi)
    enc = OmniEncoder(omni_path)
    zh_emb = enc.encode(df_zh['text_zh'].tolist())
    vi_emb = enc.encode(df_vi['text_vi'].tolist())
    S_SEM = zh_emb @ vi_emb.T

    print("\n[2/3] Align...")
    # TRỌNG SỐ CỐ ĐỊNH (Đã được chứng minh hiệu quả ở bản trước)
    # Semantic = 1.0, Anchor = 5.0. Phạt gap mạnh hơn (-1.5)
    S_total = (1.0 * S_SEM) + (5.0 * S_ANC)
    alignments = dp_align(S_total, gap=-1.5, anchor_bonus=5.0)

    print("\n[3/3] Xuất kết quả...")
    results = []
    for zi, vi in alignments:
        if not zi: continue
        zh_t = "".join(df_zh.iloc[x]['text_zh'] for x in zi)
        vi_t = " ".join(df_vi.iloc[x]['text_vi'] for x in vi) if vi else "[TRỐNG]"
        pages = sorted(set(df_vi.iloc[x]['page_start'] for x in vi)) if vi else []
        
        results.append({
            'Page': ",".join(map(str, pages)),
            'Han_Text': zh_t, 'Viet_Text': vi_t,
        })

    df_out = pd.DataFrame(results)
    out_file = 'KetQua_Final.xlsx'
    with pd.ExcelWriter(out_file, engine='openpyxl') as w:
        df_out.to_excel(w, index=False)
        
    print(f"\nHoàn tất! Lưu tại: {out_file}")

if __name__ == "__main__":
    main()