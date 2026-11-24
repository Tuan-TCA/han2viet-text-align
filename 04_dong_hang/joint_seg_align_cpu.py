#!/usr/bin/env python3
"""Local joint Han segmentation + Vietnamese alignment. No inference API.
Python 3.10+. Install: python joint_seg_align_cpu.py install
Run: python joint_seg_align_cpu.py run --help
Evaluate: python joint_seg_align_cpu.py evaluate --output PATH
"""
import argparse, bisect, csv, hashlib, json, math, os, re, subprocess, sys, unicodedata, zipfile
from collections import Counter, defaultdict
from pathlib import Path
from functools import lru_cache

ROOT = Path(__file__).resolve().parent
if ROOT.name == '04_dong_hang': ROOT = ROOT.parent
MODELS = {'mini':'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2', 'labse':'sentence-transformers/LaBSE', 'bge':'BAAI/bge-m3', 'qwen':'Qwen/Qwen3-Embedding-0.6B'}
VARIANTS = ('V7','V8','V9','V10')
DEFAULT_DICT = Path(__file__).resolve().parent / 'Unihan.zip'
UNIHAN_URL = 'https://www.unicode.org/Public/UCD/latest/ucd/Unihan.zip'

def readcsv(p):
    with p.open(encoding='utf-8-sig', newline='') as f: return list(csv.DictReader(f))
def csvout(p, rows, fields):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('w', encoding='utf-8-sig', newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
def dump(p,obj): p.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
def content(s): return ''.join(c for c in s if not c.isspace() and not unicodedata.category(c).startswith('P'))
def norm(s):
    s=unicodedata.normalize('NFD',s.lower().replace('đ','d'))
    return ''.join(c for c in s if not unicodedata.combining(c))
def truth(x): return x is True or str(x).strip().lower() in ('1','true','yes','x','co','có')
def load_pages(folder, first,last):
    found={}
    for p in folder.glob('*.json'):
        d=json.loads(p.read_text(encoding='utf-8-sig'))
        if not isinstance(d,dict) or 'rows' not in d or 'info' not in d: continue
        page=int(d['info']['page'])
        if not first<=page<=last: continue
        if page in found: raise ValueError(f'Duplicate page: {page}')
        rows=sorted(d['rows'],key=lambda r:r['segment'])
        if [r['segment'] for r in rows]!=list(range(1,len(rows)+1)): raise ValueError(f'Invalid segments: {p}')
        parts=[''.join(r['han'].split()) for r in rows]
        if not content(''.join(parts)): raise ValueError(f'Empty page: {p}')
        found[page]=parts
    missing=set(range(first,last+1))-found.keys()
    if missing: raise ValueError(f'Missing Han pages: {sorted(missing)}')
    return found

def load_viet(path):
    from openpyxl import load_workbook
    wb=load_workbook(path,read_only=True,data_only=True)
    def table(name):
        it=iter(wb[name].values); fields=next(it); return [dict(zip(fields,r)) for r in it]
    try:
        v=[dict(id=str(r['id_vi']), first=int(r['viet_page_start']),last=int(r['viet_page_end']),text=str(r['text_vi']).strip()) for r in table('CAU_VIET') if truth(r['dung_de_ghep']) and r['text_vi']]
        maps=[r for r in table('TRANG_VIET') if isinstance(r['viet_pdf_page'],int)]
    finally: wb.close()
    if not v or not maps or len({r['id'] for r in v})!=len(v): raise ValueError('Invalid Vietnamese workbook')
    return v,maps

def window(maps,first,last,margin):
    anchors=defaultdict(list)
    for r in maps:
        for x in str(r.get('han_trang_co_moc') or '').split(','):
            m=re.match(r'\s*(\d+)',x)
            if m: anchors[int(m[1])].append(r['viet_pdf_page'])
    def estimate(p):
        if p in anchors: return min(anchors[p]),max(anchors[p])
        l=max((x for x in anchors if x<p),default=None); r=min((x for x in anchors if x>p),default=None)
        if l is not None and r is not None and max(anchors[l])<=min(anchors[r]):
            x=max(anchors[l])+(min(anchors[r])-max(anchors[l]))*(p-l)/(r-l); return math.floor(x),math.ceil(x)
        v=[x['viet_pdf_page'] for x in maps if isinstance(x.get('han_cua_so_tu'),int) and isinstance(x.get('han_cua_so_den'),int) and x['han_cua_so_tu']<=p<=x['han_cua_so_den']]
        if not v: raise ValueError(f'No Vietnamese map for Han page {p}')
        return min(v),max(v)
    estimates=[estimate(p) for p in range(first,last+1)]
    return min(x[0] for x in estimates)-margin,max(x[1] for x in estimates)+margin

# Chinese numeric parsing. Years, dates, quantities and money may be ambiguous:
# use these as soft evidence only; do not assign semantic labels.
DIG=dict(zip('零〇一二三四五六七八九', [0,0,1,2,3,4,5,6,7,8,9])); DIG.update({'兩':2,'两':2,'壹':1,'貳':2,'贰':2,'參':3,'叁':3,'肆':4,'伍':5,'陸':6,'陆':6,'柒':7,'捌':8,'玖':9})
SMALL={'十':10,'拾':10,'百':100,'佰':100,'千':1000,'仟':1000}; BIG={'萬':10000,'万':10000,'億':100000000,'亿':100000000}
ZHNUM=re.compile('['+''.join(DIG)+''.join(SMALL)+''.join(BIG)+']+')
def zhnum(s):
    if all(c in DIG for c in s): return int(''.join(str(DIG[c]) for c in s))
    total=section=0; digit=None
    for c in s:
        if c in DIG: digit=DIG[c]
        elif c in SMALL: section+=(1 if digit is None else digit)*SMALL[c]; digit=None
        elif c in BIG:
            section+=digit or 0; digit=None
            if BIG[c]==100000000: total=(total+section or 1)*BIG[c]
            else: total+=(section or 1)*BIG[c]
            section=0
    return total+section+(digit or 0)
VI_NUM=re.compile(r'(?<!\d)(\d{1,3}(?:[.\s]\d{3})+|\d+)(?:\s*(vạn|nghìn|ngàn|triệu)\b(?:\s*(\d{1,3}(?:[.\s]\d{3})+|\d+))?)?',re.I)
@lru_cache(maxsize=50000)
def nums(s,lang):
    if lang=='zh': return frozenset(zhnum(m[0]) for m in ZHNUM.finditer(s) if zhnum(m[0])>=10)
    out=set()
    for m in VI_NUM.finditer(s):
        x=int(re.sub(r'\D','',m[1])); unit=m[2]
        if unit: x=x*{'vạn':10000,'nghìn':1000,'ngàn':1000,'triệu':1000000}[unit.lower()]+(int(re.sub(r'\D','',m[3])) if m[3] else 0)
        if x>=10: out.add(x)
    return frozenset(out)

def hv_dictionary(path):
    d={}
    if not path: return d
    def lines(it):
        for line in it:
            if line.startswith('#'): continue
            parts=line.rstrip('\r\n').split('\t')
            if len(parts)>=3 and parts[1]=='kVietnamese' and parts[0].startswith('U+'):
                d[chr(int(parts[0][2:],16))]=parts[2].split()[0]
            elif len(parts)==2 and len(parts[0])==1: d[parts[0]]=parts[1].split('|')[0].strip()
    if path.suffix.lower()=='.zip':
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if name.endswith('Unihan_Readings.txt') or name.endswith('kVietnamese.txt'): lines(z.read(name).decode('utf-8-sig').splitlines())
    else: lines(path.read_text(encoding='utf-8-sig').splitlines())
    if not d: raise ValueError('No Han-Viet readings loaded')
    return d

def grams(tokens): return set(zip(tokens,tokens[1:]))
def hv_grams(text,d):
    return {g for g in grams([norm(d[c]) if c in d else '\0' for c in content(text)]) if '\0' not in g}
def vi_grams(text): return grams(re.findall(r'\w+',norm(text)))

def han_source(pages):
    raw=''; preferred={0}; page_ends=[]
    for p,parts in pages.items():
        for part in parts:
            raw+=part; preferred.add(len(raw))
        page_ends.append((len(raw),p))
    for m in re.finditer(r'[。！？；，、：!?;,]+',raw): preferred.add(m.end())
    return raw,preferred,page_ends

def candidate_spans(raw, preferred,stride,minlen,maxlen):
    n=len(raw); cuts=sorted(set(range(0,n,stride))|preferred|{n})
    # Do not begin/end inside an unbroken numeric expression or immediately before punctuation.
    forbidden={i for m in ZHNUM.finditer(raw) for i in range(m.start()+1,m.end())}
    cuts=[x for x in cuts if x in (0,n) or (x not in forbidden and not unicodedata.category(raw[x]).startswith('P'))]
    spans=[]
    for i,a in enumerate(cuts[:-1]):
        for j in range(i+1,len(cuts)):
            b=cuts[j]
            if b-a>maxlen: break
            if b-a>=minlen or a==0 or b==n:
                if content(raw[a:b]): spans.append((i,j,raw[a:b]))
    return cuts,spans

class Encoder:
    def __init__(self,a):
        import torch
        from sentence_transformers import SentenceTransformer
        torch.set_num_threads(a.threads)
        self.model=SentenceTransformer(MODELS.get(a.model,a.model),device='cpu',local_files_only=a.offline)
        self.model.max_seq_length=a.max_tokens
        self.batch=a.batch_size; self.cache=a.output/'embeddings'; self.cache.mkdir(exist_ok=True)
        self.key=MODELS.get(a.model,a.model)+f'|{a.max_tokens}'
    def encode(self,texts):
        import numpy as np
        key=hashlib.sha256(json.dumps([self.key,texts],ensure_ascii=False).encode()).hexdigest(); p=self.cache/(key+'.npy')
        if p.exists(): return np.load(p,allow_pickle=False)
        x=self.model.encode(texts,batch_size=self.batch,normalize_embeddings=True,convert_to_numpy=True,show_progress_bar=True)
        x=np.asarray(x,dtype=np.float32); np.save(p,x); return x

def build_features(hspans,vspans,encoder,d):
    import numpy as np
    h=encoder.encode([t for _,_,t in hspans]); v=encoder.encode([t for _,_,t in vspans]); sim=h@v.T
    hn=[nums(t,'zh') for _,_,t in hspans]; vn=[nums(t,'vi') for _,_,t in vspans]
    hg=[hv_grams(t,d) for _,_,t in hspans] if d else []; vg=[vi_grams(t) for _,_,t in vspans] if d else []
    num=np.zeros_like(sim); hv=np.zeros_like(sim)
    for i,x in enumerate(hn):
        for j,y in enumerate(vn):
            if x and y: num[i,j]=len(x&y)/len(x|y) - 0.5*bool(x-y and y-x)
            elif x or y: num[i,j]=-.15
            if d and hg[i] and vg[j]: hv[i,j]=2*len(hg[i]&vg[j])/(len(hg[i])+len(vg[j]))
    return sim,num,hv

def solve(cuts,hspans,vspans,features,preferred,variant,a,nv):
    import numpy as np
    sim,num,hv=features; nh=len(cuts)-1
    bystart=defaultdict(list); vstart=defaultdict(list)
    for k,(i,j,t) in enumerate(hspans): bystart[i].append((k,j,t))
    for k,(i,j,t) in enumerate(vspans): vstart[i].append((k,j,t))
    dp=np.full((nh+1,nv+1),-np.inf); dp[0,0]=0; prev={}
    threshold=a.threshold+(a.strict_delta if variant=='V10' else 0)
    def update(i,j,val,origin,edge):
        if val>dp[i,j]: dp[i,j]=val; prev[i,j]=(origin,edge)
    for i in range(nh+1):
        for j in range(nv+1):
            val=dp[i,j]
            if not np.isfinite(val): continue
            if i<nh: update(i+1,j,val-a.skip_han*(cuts[i+1]-cuts[i]),(i,j),('han_skip',None))
            if j<nv: update(i,j+1,val-a.skip_viet,(i,j),('vi_skip',None))
            for hi,ii,ht in bystart[i]:
                length=cuts[ii]-cuts[i]
                for vi,jj,vt in vstart[j]:
                    s=float(sim[hi,vi]); n=float(num[hi,vi]); h=float(hv[hi,vi])
                    # Threshold applies to uncalibrated similarity, not probability.
                    if s<threshold: continue
                    if variant=='V10' and n<-.25: continue
                    combined=s+(a.number_weight*n if variant!='V7' else 0)+(a.hv_weight*h if variant in ('V9','V10') else 0)
                    gain=(combined-threshold)*length-a.group_penalty*(jj-j-1)-a.boundary_penalty*(cuts[ii] not in preferred)
                    update(ii,jj,val+gain,(i,j),('match',(hi,vi,s,n,h,combined)))
    path=[]; state=(nh,nv)
    while state!=(0,0):
        origin,edge=prev[state]; path.append((origin,state,edge)); state=origin
    path.reverse(); return path,float(dp[nh,nv])

PAIR_FIELDS=['pair_id','variant','han_page_start','han_page_end','han_start','han_end','id_vi','text_zh','text_vi','embedding_score','number_score','hv_score','combined_score','han_chars']
SEG_FIELDS=['id_zh','han_page_start','han_page_end','han_start','han_end','text_zh','status']
REVIEW_FIELDS=['pair_id','han_page_start','han_page_end','han_start','han_end','id_vi','text_zh','text_vi','label','reason']

def export_path(a,variant,raw,cuts,ends,viet,path,block,offset,allpairs):
    seg=[]; align=[]; pending=None; skipped_viet=[]
    def page(x): return ends[bisect.bisect_right([e for e,_ in ends],x)][1]
    def add(i,ii,j,jj,edge):
        start,stop=cuts[i],cuts[ii]; text=raw[start:stop]
        if not text: return
        r=dict(id_zh=f'{block}-S{len(seg)+1:04}',han_page_start=page(start),han_page_end=page(stop-1),han_start=offset+start,han_end=offset+stop,text_zh=text,status='matched' if edge else 'unmatched')
        seg.append(r)
        if edge:
            _,_,s,n,h,c=edge; ids=';'.join(v['id'] for v in viet[j:jj]); vt=' '.join(v['text'] for v in viet[j:jj]); key=hashlib.sha256(json.dumps([r['han_page_start'],offset+start,offset+stop,ids,text,vt],ensure_ascii=False).encode()).hexdigest()[:24]
            x=dict(pair_id=key,variant=variant,han_page_start=r['han_page_start'],han_page_end=r['han_page_end'],han_start=offset+start,han_end=offset+stop,id_vi=ids,text_zh=text,text_vi=vt,embedding_score=s,number_score=n,hv_score=h,combined_score=c,han_chars=len(content(text)))
            allpairs.append(x); align.append(x)
    for (i,j),(ii,jj),(kind,edge) in path:
        if kind=='han_skip':
            if pending is None: pending=(i,ii)
            else: pending=(pending[0],ii)
        else:
            if pending: add(*pending,0,0,None); pending=None
            if kind=='match': add(i,ii,j,jj,edge)
            elif kind=='vi_skip': skipped_viet.extend(viet[j:jj])
    if pending: add(*pending,0,0,None)
    assert ''.join(x['text_zh'] for x in seg)==raw
    csvout(a.output/variant/'segmented'/(block+'.csv'),seg,SEG_FIELDS)
    csvout(a.output/variant/'alignment'/(block+'.csv'),align,PAIR_FIELDS)
    csvout(a.output/variant/'skipped_viet'/(block+'.csv'),skipped_viet,['id','first','last','text'])


def evaluate(output):
    rows=readcsv(output/'pairs.csv'); review={r['pair_id']:r for r in readcsv(output/'review.csv')}; meta=json.loads((output/'run.json').read_text(encoding='utf-8')); total=meta['source_chars']; result=[]
    for variant in meta['variants']:
        rs=[r for r in rows if r['variant']==variant]; labels=[review[r['pair_id']]['label'].strip() for r in rs]
        if any(x not in ('','0','1') for x in labels): raise ValueError('Labels must be blank, 0 or 1')
        correct=sum(int(r['han_chars']) for r,l in zip(rs,labels) if l=='1'); matched=sum(int(r['han_chars']) for r in rs); one=labels.count('1'); zero=labels.count('0'); pending=labels.count('')
        result.append(dict(variant=variant,pairs=len(rs),label_1=one,label_0=zero,pending=pending,reviewed_precision=one/(one+zero) if one+zero else '',matched_coverage=matched/total,verified_correct_coverage=correct/total,correct_chars=correct))
    csvout(output/'comparison.csv',result,list(result[0])); print(json.dumps(result,ensure_ascii=False,indent=2)); return result

def run(a):
    import numpy as np
    first,last=a.pages; pages=load_pages(a.han_dir,first,last); viet,maps=load_viet(a.viet_xlsx); d=hv_dictionary(a.hv_dict or (DEFAULT_DICT if DEFAULT_DICT.exists() else None))
    if not d and ('V9' in a.variants or 'V10' in a.variants): print('NOTICE: no HV dictionary; V9 identical to V8; V10 still uses stricter acceptance.')
    # One continuous block: prevents cross-block Vietnamese reuse and artificial page cuts.
    raw,preferred,ends=han_source(pages); lo,hi=window(maps,first,last,a.margin)
    v=[r for r in viet if r['first']<=hi and r['last']>=lo]
    if not v: raise ValueError('Empty Vietnamese window')
    cuts,hs=candidate_spans(raw,preferred,a.stride,a.min_han,a.max_han)
    vs=[(i,j,' '.join(r['text'] for r in v[i:j])) for i in range(len(v)) for j in range(i+1,min(len(v),i+a.max_viet_group)+1)]
    if not hs: raise ValueError('No Han candidate spans')
    if len(hs)*len(vs)>a.max_matrix_cells: raise ValueError('Candidate matrix too large: reduce pages, margin or increase stride')
    print(f'Han {len(raw)} chars, {len(cuts)} boundaries, {len(hs)} spans; Viet pages {lo}-{hi}, {len(v)} units, {len(vs)} spans',flush=True)
    a.output.mkdir(parents=True,exist_ok=True); enc=Encoder(a); f=build_features(hs,vs,enc,d); allpairs=[]; scores={}; block=f'{first:04}-{last:04}'
    for variant in a.variants:
        path,score=solve(cuts,hs,vs,f,preferred,variant,a,len(v)); scores[variant]=score
        export_path(a,variant,raw,cuts,ends,v,path,block,0,allpairs)
        print(variant, 'pairs',sum(r['variant']==variant for r in allpairs),flush=True)
    old={r['pair_id']:r for r in readcsv(a.output/'review.csv')} if (a.output/'review.csv').exists() else {}
    unique={r['pair_id']:r for r in allpairs}; reviews=[]
    for k,r in unique.items():
        x={f:r.get(f,'') for f in REVIEW_FIELDS}; x.update(label=old.get(k,{}).get('label',''),reason=old.get(k,{}).get('reason','')); reviews.append(x)
    csvout(a.output/'pairs.csv',allpairs,PAIR_FIELDS); csvout(a.output/'review.csv',reviews,REVIEW_FIELDS)
    dump(a.output/'run.json',dict(variants=a.variants,source_chars=len(content(raw)),pages=a.pages,viet_window=[lo,hi],model=a.model,han_candidates=len(hs),viet_candidates=len(vs),dictionary_entries=len(d),scores=scores,config={k:str(v) if isinstance(v,Path) else v for k,v in vars(a).items()})); evaluate(a.output)

def selftest():
    import numpy as np
    assert zhnum('一萬四千三百四十九')==14349 and nums('1 vạn 4.349 người','vi')=={14349}
    assert nums('2.727 bát','vi')=={2727} and not truth('FALSE')
    raw='天地玄黃宇宙洪荒'; cuts,hs=candidate_spans(raw,{0,4,8},1,2,8); vs=[(0,1,'a'),(1,2,'b')]
    sim=np.full((len(hs),2),-.5,dtype=np.float32)
    for k,(i,j,t) in enumerate(hs):
        if t=='天地玄黃': sim[k,0]=.9
        if t=='宇宙洪荒': sim[k,1]=.9
    a=argparse.Namespace(threshold=.4,strict_delta=.1,skip_han=.02,skip_viet=.1,number_weight=.15,hv_weight=.2,group_penalty=.2,boundary_penalty=.1)
    path,_=solve(cuts,hs,vs,(sim,np.zeros_like(sim),np.zeros_like(sim)),{0,4,8},'V7',a,2)
    assert [e[2][0] for e in path]==['match','match']
    # Explicit synthetic fixture: not model output or measured accuracy.
    print('PASS: synthetic DP, numeric normalization, boolean handling')

def main():
    p=argparse.ArgumentParser(description=__doc__); sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('install'); sub.add_parser('selftest'); e=sub.add_parser('evaluate'); e.add_argument('--output',type=Path,default=ROOT/'04_dong_hang/joint_experiments')
    a=sub.add_parser('run'); a.add_argument('--han-dir',type=Path,default=ROOT/'02_ocr_tho/Cap_01/HAN/pages'); a.add_argument('--viet-xlsx',type=Path,default=ROOT/'02_ocr_tho/Cap_01/VIET/VIET_0186-0251.xlsx'); a.add_argument('--output',type=Path,default=ROOT/'04_dong_hang/joint_experiments'); a.add_argument('--pages',nargs=2,type=int,default=[1,2]); a.add_argument('--variants',nargs='+',choices=VARIANTS,default=list(VARIANTS)); a.add_argument('--model',default='mini'); a.add_argument('--hv-dict',type=Path); a.add_argument('--offline',action='store_true')
    for key,value in [('stride',4),('min-han',5),('max-han',110),('max-viet-group',2),('margin',1),('threads',min(8,os.cpu_count() or 1)),('batch-size',16),('max-tokens',256),('max-matrix-cells',3000000)]: a.add_argument('--'+key,type=int,default=value)
    for key,value in [('threshold',.4),('strict-delta',.12),('skip-han',.015),('skip-viet',.12),('number-weight',.18),('hv-weight',.2),('group-penalty',.3),('boundary-penalty',.1)]: a.add_argument('--'+key,type=float,default=value)
    x=p.parse_args()
    if x.command=='install':
        subprocess.check_call([sys.executable,'-m','pip','install','torch','--index-url','https://download.pytorch.org/whl/cpu']); subprocess.check_call([sys.executable,'-m','pip','install','sentence-transformers','numpy','openpyxl'])
        if not DEFAULT_DICT.exists():
            from urllib.request import urlopen, Request
            import shutil
            tmp=DEFAULT_DICT.with_suffix('.tmp')
            try:
                with urlopen(Request(UNIHAN_URL,headers={'User-Agent':'HanVietResearch/1.0'}),timeout=90) as response, tmp.open('wb') as f: shutil.copyfileobj(response,f)
                with zipfile.ZipFile(tmp) as z:
                    if z.testzip() is not None: raise ValueError('Corrupt Unihan archive')
                tmp.replace(DEFAULT_DICT); print('Unihan dictionary downloaded')
            except Exception as exc:
                tmp.unlink(missing_ok=True); print(f'Unihan download failed: {exc}. Supply --hv-dict manually.')
        return
    if x.command=='selftest': selftest(); return
    if x.command=='evaluate': evaluate(x.output); return
    if not (1<=x.pages[0]<=x.pages[1] and 0<x.min_han<=x.max_han and 0<x.stride<=x.max_han and min(x.threads,x.batch_size,x.max_tokens,x.max_viet_group,x.max_matrix_cells)>0 and x.margin>=0): p.error('Invalid run parameters')
    run(x)
if __name__=='__main__': main()
