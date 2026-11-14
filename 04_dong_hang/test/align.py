# align_ga_omni.py — Genetic Algorithm + OmniAlign + Dang Anchors
import os, re, sys, subprocess, importlib.util, unicodedata, random
import numpy as np
import pandas as pd

# 1. Cài đặt thư viện thiếu (bao gồm deap cho GA)
def _ensure(pkg, imp=None):
    if imp is None: imp = pkg
    if importlib.util.find_spec(imp) is None:
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])

for p, i in [("pandas","pandas"),("numpy","numpy"),("openpyxl","openpyxl"),
             ("cn2vn","cn2vn"),("cn2an","cn2an"),("torch","torch"),
             ("transformers","transformers"),("deap","deap")]:
    _ensure(p, i)

os.environ["CUDA_VISIBLE_DEVICES"] = ""
import torch
import cn2vn, cn2an
from transformers import AutoModel, AutoTokenizer
from deap import base, creator, tools, algorithms

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)

# ---------- Tiền xử lý ----------
def remove_accents(t):
    return re.sub(r'[\u0300-\u036f]', '', unicodedata.normalize('NFD', str(t))).lower()

def get_sino_tokens(h):
    try: return remove_accents(cn2vn(str(h))).split()
    except: return str(h).split()

def split_vi_text(text):
    """Băm nhỏ đoạn văn bản OCR bị gộp dựa trên dấu câu và số liệu"""
    # Cắt tại dấu chấm, chấm phẩy, hoặc trước các cụm số liệu
    chunks = re.split(r'(?<=[.;?!])\s+|(?<=[,])\s+(?=\D*\d)', str(text))
    # Lọc bỏ các đoạn quá ngắn (rác)
    return [c.strip() for c in chunks if len(c.strip()) > 15]

# ---------- Đặc trưng ----------
def build_anchor_matrix(df_zh, df_vi, min_len=3, max_len=10):
    """Tạo ma trận Neo (S_anchor) dựa trên n-gram Hán-Việt"""
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
                S_anchor[i, j] = best  # Trọng số = độ dài n-gram khớp
    return S_anchor

def build_pos_penalty(n, m):
    """Tạo ma trận phạt vị trí (S_pos) - Phạt các cặp lệch xa nhau"""
    S_pos = np.zeros((n, m))
    for i in range(n):
        for j in range(m):
            # Khoảng cách chuẩn hóa từ 0 đến 1
            S_pos[i, j] = abs(i / max(1, n-1) - j / max(1, m-1))
    return S_pos

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
        return np.vstack(outs)

# ---------- DP & Fitness ----------
def dp_align(S, gap=-1.0):
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
            if i >= 2:
                sc = dp[i-2][j-1] + (S[i-2][j-1] + S[i-1][j-1]) / 2
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

# Biến toàn cục cho Fitness
S_SEM, S_ANC, S_POS = None, None, None

def evaluate(individual):
    w_sem, w_anc, w_pos = individual
    # Tổng hợp ma trận điểm: Cộng điểm ngữ nghĩa + Neo, Trừ điểm phạt vị trí
    S_total = (w_sem * S_SEM) + (w_anc * S_ANC) - (w_pos * S_POS)
    
    alignments = dp_align(S_total, gap=-1.0)
    
    fitness = 0
    n_gaps = 0
    for zi, vi in alignments:
        if zi and vi:
            # Điểm cộng: Ngữ nghĩa + Neo (nếu cặp này có neo)
            for a in zi:
                for b in vi:
                    fitness += w_sem * S_SEM[a,b]
                    if S_ANC[a,b] > 0:
                        fitness += w_anc * 10  # Thưởng lớn nếu khớp neo
        else:
            n_gaps += 1
            
    fitness -= 0.5 * n_gaps
    return (fitness,)

# ---------- Main ----------
def main():
    zh_path = r'..\03_text_sach\Cap_01\HAN\zh_cleaned.csv'
    vi_path = r'..\03_text_sach\Cap_01\VIET\vi_cleaned.csv'
    omni_path = r'..\OmniAlign\OmniAlign'

    df_zh = pd.read_csv(zh_path)
    df_vi = pd.read_csv(vi_path)
    
    # 1. LỌC TRANG & BĂM NHỎ VĂN BẢN VIỆT
    df_vi = df_vi[(df_vi['page_start'] >= 186) & (df_vi['page_start'] <= 188)]
    new_rows = []
    for _, row in df_vi.iterrows():
        for chunk in split_vi_text(row['text_vi']):
            new_rows.append({'page_start': row['page_start'], 'text_vi': chunk})
    df_vi = pd.DataFrame(new_rows).reset_index(drop=True)
    
    print(f"Hán: {len(df_zh)} câu | Việt: {len(df_vi)} câu (Đã băm nhỏ)")

    # 2. TRÍCH XUẤT ĐẶC TRƯNG
    print("\n[1/4] Trích xuất đặc trưng...")
    global S_SEM, S_ANC, S_POS
    S_ANC = build_anchor_matrix(df_zh, df_vi)
    S_POS = build_pos_penalty(len(df_zh), len(df_vi))
    
    print("  Load OmniAlign...")
    enc = OmniEncoder(omni_path)
    zh_emb = enc.encode(df_zh['text_zh'].tolist())
    vi_emb = enc.encode(df_vi['text_vi'].tolist())
    S_SEM = zh_emb @ vi_emb.T

    # 3. GENETIC ALGORITHM
    print("\n[2/4] Tối ưu hóa bằng Genetic Algorithm...")
    creator.create("FitnessMax", base.Fitness, weights=(1.0,))
    creator.create("Individual", list, fitness=creator.FitnessMax)

    toolbox = base.Toolbox()
    toolbox.register("attr_float", random.uniform, 0.0, 1.0)
    toolbox.register("individual", tools.initRepeat, creator.Individual, toolbox.attr_float, n=3)
    toolbox.register("population", tools.initRepeat, list, toolbox.individual)
    toolbox.register("evaluate", evaluate)
    toolbox.register("mate", tools.cxBlend, alpha=0.5)
    toolbox.register("mutate", tools.mutGaussian, mu=0, sigma=0.2, indpb=0.2)
    toolbox.register("select", tools.selTournament, tournsize=3)

    pop = toolbox.population(n=20)  # Quần thể 20 cá thể
    algorithms.eaSimple(pop, toolbox, cxpb=0.7, mutpb=0.2, ngen=10, verbose=False)
    best_ind = tools.selBest(pop, 1)[0]
    w_sem, w_anc, w_pos = best_ind
    print(f"  -> Trọng số tối ưu: Semantic={w_sem:.2f}, Anchor={w_anc:.2f}, PosPenalty={w_pos:.2f}")

    # 4. ALIGN VÀ XUẤT KẾT QUẢ
    print("\n[3/4] Align với trọng số tối ưu...")
    S_total = (w_sem * S_SEM) + (w_anc * S_ANC) - (w_pos * S_POS)
    alignments = dp_align(S_total, gap=-1.0)

    print("\n[4/4] Xuất kết quả...")
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
    out_file = 'KetQua_GA_Omni.xlsx'
    with pd.ExcelWriter(out_file, engine='openpyxl') as w:
        df_out.to_excel(w, index=False)
        
    print(f"\nHoàn tất! Lưu tại: {out_file}")

if __name__ == "__main__":
    main()