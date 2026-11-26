"""Independent scoring methods sharing a monotone span/skip lattice."""
from functools import lru_cache
import math

from candidate_boundaries import entities, numbers
from coarse_alignment import units
from preprocess import content

WEIGHTS = {'M2': {'length':1.0}, 'M3': {'semantic':2.6},
           'M4': {'number':1.3,'entity':1.15},
           'M5': {'length':0.85,'semantic':1.3,'number':0.85,'entity':0.65,'boundary':0.40}}


class SemanticEncoder:
    def __init__(self, model_dir, batch, limit):
        import numpy as np
        import torch
        from transformers import AutoModel, AutoTokenizer
        import transformers.dynamic_module_utils as dynamic
        import transformers.utils.hub as hub
        torch.set_num_threads(min(torch.get_num_threads(), 4))
        # The trusted project-local model uses custom code. Keep its import cache in Stage 03.
        cache = str(model_dir.parents[1] / '03_text_sach/artifacts/model_cache')
        dynamic.HF_MODULES_CACHE = hub.HF_MODULES_CACHE = cache
        self.tok = AutoTokenizer.from_pretrained(model_dir, local_files_only=True, trust_remote_code=True)
        self.model = AutoModel.from_pretrained(model_dir, local_files_only=True, trust_remote_code=True).eval()
        self.torch, self.np, self.batch, self.limit = torch, np, batch, limit

    def encode(self, texts):
        result = []
        for i in range(0,len(texts),self.batch):
            x = self.tok(texts[i:i+self.batch], padding=True, truncation=True, max_length=self.limit,
                         return_tensors='pt')
            with self.torch.inference_mode():
                y = self.model(**x).last_hidden_state
                mask = x['attention_mask'].unsqueeze(-1)
                result.extend(((y*mask).sum(1)/mask.sum(1).clamp(min=1)).cpu().numpy())
        return self.np.array(result)

    def lattice(self, han_atoms, viet):
        np = self.np
        def prefix(texts):
            matrix = self.encode(texts)
            return np.concatenate((np.zeros_like(matrix[:1]), matrix.cumsum(0)), axis=0)
        h,v = prefix(han_atoms),prefix(viet)
        def similarity(i,k,j,l):
            a,b = h[k]-h[i],v[l]-v[j]
            return float(np.dot(a,b)/(max(1e-8,np.linalg.norm(a)*np.linalg.norm(b))))
        return similarity


def lattice_points(marks, removed=()):
    return [p for p,m in marks.items() if not m['blocked'] and (set(m['sources'])-set(removed))]


def dynamic(raw, viet, marks, cfg, ratio, weights, semantic=None, removed=()):
    cuts = lattice_points(marks,removed)
    hn,vn = len(cuts)-1,len(viet)
    relevant = weights.keys()
    @lru_cache(None)
    def features(text, han):
        return (len(content(text)) if han else units(text),
                numbers(text,han) if 'number' in relevant else set(),
                entities(text,han) if 'entity' in relevant else set())
    @lru_cache(None)
    def vs(j,l): return features(' '.join(viet[j:l]),False)
    @lru_cache(None)
    def hs(i,k): return features(raw[cuts[i]:cuts[k]],True)
    @lru_cache(None)
    def sim(i,k,j,l): return semantic(i,k,j,l) if semantic else 0.
    dp = [[(-math.inf,None) for _ in range(vn+1)] for _ in range(hn+1)]
    dp[0][0]=(0.,None)
    def extend(i,j,k,l,delta,kind,features):
        value = dp[i][j][0]+delta
        if value > dp[k][l][0]+1e-10:
            dp[k][l]=(value,(i,j,kind,delta,features))
    for i in range(hn+1):
        for j in range(vn+1):
            if dp[i][j][0]==-math.inf: continue
            if j<vn: extend(i,j,i,j+1,-0.9,'skip_vi',{})
            for k in range(i+1,min(hn,i+cfg['max_han_skip'])+1):
                extend(i,j,k,j,-0.28-0.013*(cuts[k]-cuts[i]),'skip_han',{})
            if j==vn: continue
            for k in range(i+1,hn+1):
                if cuts[k]-cuts[i]>cfg['max_han_chars'] and k>i+1: break
                hc,hnum,hent=hs(i,k)
                if not hc: continue
                for l in range(j+1,min(vn,j+cfg['max_vi_merge'])+1):
                    vc,vnum,vent=vs(j,l)
                    if not vc: continue
                    signals = {}
                    if 'length' in relevant: signals['length']=-abs(math.log((hc+1)/(vc*ratio+1)))
                    if 'semantic' in relevant: signals['semantic']=sim(i,k,j,l)-0.45
                    if 'number' in relevant:
                        signals['number']=len(hnum&vnum)/max(1,len(hnum|vnum))-(0.18 if hnum and vnum and not hnum&vnum else 0)
                    if 'entity' in relevant: signals['entity']=len(hent&vent)/max(1,len(hent|vent))
                    if 'boundary' in relevant and k<hn:
                        from candidate_boundaries import SOURCE_WEIGHTS
                        signals['boundary']=sum(SOURCE_WEIGHTS[s] for s in marks[cuts[k]]['sources'] if s not in removed)
                    # A modest merge cost and source-independent structural prior.
                    delta=0.18*(l-j)-0.30*(l-j-1)+sum(weights[s]*x for s,x in signals.items())
                    extend(i,j,k,l,delta,'match',signals)
    output=[]; i,j=hn,vn
    while (i,j)!=(0,0):
        a,b,kind,score,signals = dp[i][j][1]
        output.append({'han':[cuts[a],cuts[i]],'vi':[b,j],'kind':kind,'score':score,'signals':signals})
        i,j=a,b
    return list(reversed(output))


def baseline(raw, cuts):
    return [{'han':[a,b],'vi':[0,0],'kind':'baseline','score':None,'signals':{}}
            for a,b in zip(cuts,cuts[1:]) if a<b]
