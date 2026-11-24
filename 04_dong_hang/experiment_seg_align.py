"""Compare Han segmentation + SinoNom alignment, using identical page blocks.
Place beside batch_sentence_alignment.py and align_sinonom_api.py, or use --module-dir.
No semantic labels are inferred from API scores. Review CSV, then run `evaluate`.
"""
import argparse, bisect, csv, hashlib, importlib, json, math, os, re, sys, time, unicodedata
from pathlib import Path
from collections import defaultdict
from types import SimpleNamespace
import requests

URL = 'https://kimhannom.fit.hcmus.edu.vn/api/web/clc-sinonom/separate-sentences'
VARIANTS = ('V0','V1','V2','V3','V4','V5','V6')

def content(s):
    return ''.join(c for c in s if not c.isspace() and not unicodedata.category(c).startswith('P'))

def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')

def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w=csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)

def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as f: return list(csv.DictReader(f))

def digest(obj):
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

class Client:
    def __init__(self, args, alignment):
        self.a=args; self.alignment=alignment; self.calls=0; self.hits=0
        self.token=os.environ.get('SINONOM_TOKEN','').strip()
        if self.token.lower().startswith('bearer '): self.token=self.token[7:].strip()
        if not self.token: raise ValueError('Set SINONOM_TOKEN')
        self.session=requests.Session()
        self.session.headers.update({'Authorization':f'Bearer {self.token}', 'Accept':'application/json',
             'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/138.0.0.0 Safari/537.36'})
    def cached(self, kind, payload, fn):
        path=self.a.output/'cache'/f'{kind}_{digest(payload)}.json'
        if path.exists(): self.hits+=1; return json.loads(path.read_text(encoding='utf-8'))
        if self.calls>=self.a.max_calls: raise BudgetError('Global API call budget exhausted')
        if self.calls: time.sleep(self.a.delay)
        self.calls+=1
        result=fn(); dump(path,result); return result
    def punctuate(self, text):
        payload={'text':text,'ocr_id':1,'genre':'history','punctuation_group':'all'}
        def request():
            r=self.session.post(URL,json=payload,timeout=(10,self.a.timeout),allow_redirects=False)
            r.raise_for_status(); body=r.json()
            if body.get('is_success') is not True or str(body.get('code'))!='000000':
                raise RuntimeError(f'Segmentation API: {body.get("code")}')
            return body
        body=self.cached('split',payload,request)
        s=body['data']['sentences']
        if isinstance(s,str) and s.lstrip().startswith('{'): s=json.loads(s)['sentences']
        if not isinstance(s,str) or content(s)!=content(text):
            raise ValueError('Segmentation changed OCR content; response rejected')
        return s.strip()
    def align(self,h,v):
        def request():
            r=self.alignment.call_api(h,v,self.token,timeout=self.a.timeout,retries=0)
            if not isinstance(r,dict) or not isinstance((r.get('data') or {}).get('result'),list):
                raise ValueError('Missing alignment data.result')
            if r.get('is_success') is False: raise ValueError('Alignment API unsuccessful')
            return r
        return self.cached('align',{'han':h,'viet':v},request)

class BudgetError(RuntimeError): pass

def load_pages(folder, first, last):
    found={}
    for p in folder.glob('*.json'):
        d=json.loads(p.read_text(encoding='utf-8-sig'))
        if not isinstance(d,dict) or 'rows' not in d or 'info' not in d: continue
        page=int(d['info']['page'])
        if not first<=page<=last: continue
        if page in found: raise ValueError(f'Duplicate page {page}')
        rows=sorted(d['rows'],key=lambda r:r['segment'])
        if [r['segment'] for r in rows]!=list(range(1,len(rows)+1)): raise ValueError(f'Bad segments: {p}')
        s=''.join(''.join(r['han'].split()) for r in rows)
        if not content(s): raise ValueError(f'Empty page {page}')
        found[page]=s
    return [(p,found[p]) for p in range(first,last+1)]

def split_marks(s, marks):
    # Attach punctuation to the preceding text; newline is a boundary, not content.
    parts=re.split('(['+re.escape(marks)+r']+[」』”’）】]*)',s)
    out=[]; current=''
    for i,x in enumerate(parts):
        current+=x
        if i%2 and content(current): out.append(current.strip()); current=''
    if content(current): out.append(current.strip())
    elif current.strip() and out: out[-1]+=current.strip()
    return out

SENT='。！？!?\r\n'; SEMI=SENT+'；;'; FINE=SEMI+'，,、：:'

def boundaries(parts):
    ends=[0]
    for p in parts:
        if content(p): ends.append(ends[-1]+len(content(p)))
    return ends

def resegment(parts, cuts):
    text=''.join(parts); n=len(content(text)); cuts=sorted(set(cuts)|{0,n})
    # Map character-content offset to raw string offset; attach punctuation left.
    loc=[i for i,c in enumerate(text) if content(c)]
    pos=[0]+loc[1:]+[len(text)]
    return [text[pos[a]:pos[b]].strip() for a,b in zip(cuts,cuts[1:]) if a<b]

def local_long(parts, limit):
    out=[]
    for p in parts:
        if len(content(p))<=limit: out.append(p); continue
        chunks=split_marks(p,FINE); buf=''
        for c in chunks:
            if buf and len(content(buf+c))>limit: out.append(buf); buf=''
            buf+=c
        if buf: out.append(buf)
    return out

def locate_han(texts, row):
    """Resolve returned Han snippet by source content, not by score or index alone."""
    units=[content(t) for t in texts]; ends=boundaries(units); full=''.join(units)
    q=content(row.get('han_text') or '')
    if not q: return None
    a,b=row.get('han_start'),row.get('han_end')
    if type(a) is int and type(b) is int and 0<=a<=b<len(units):
        region=full[ends[a]:ends[b+1]]; i=region.find(q)
        if i>=0 and region.find(q,i+1)<0: return ends[a]+i,ends[a]+i+len(q)
    i=full.find(q)
    if i>=0 and full.find(q,i+1)<0: return i,i+len(q)
    return None

def locate_viet(spans,row,mod):
    res=mod.resolve([s.text for s in spans],row.get('vi_start'),row.get('vi_end'),row.get('vietnamese_text'))
    if not res: return None
    return [(spans[i].row,spans[i].start+a,spans[i].start+b) for i,a,b in res]

def choose(rows):
    # Maximum covered Han characters under monotone, non-overlapping source ranges.
    # Secondary tie breaker: prefer fewer groups (stable across segmentation sizes).
    rows=sorted(rows,key=lambda r:(r['h1'],r['h0'],r['v'][0],r['v'][-1]))
    dp=[]; prev=[]
    for i,r in enumerate(rows):
        w=r['h1']-r['h0']; best=(w,-1); parent=-1
        for j,s in enumerate(rows[:i]):
            if s['h1']<=r['h0'] and (s['v'][-1][0],s['v'][-1][2]) <= (r['v'][0][0],r['v'][0][1]):
                val=(dp[j][0]+w,dp[j][1]-1)
                if val>best: best,parent=val,j
        dp.append(best); prev.append(parent)
    if not dp: return []
    i=max(range(len(dp)),key=dp.__getitem__); out=[]
    while i>=0: out.append(rows[i]); i=prev[i]
    return out[::-1]

def parse_links(response, parts, spans, mod):
    out=[]
    for r in response['data']['result']:
        if not isinstance(r,dict): continue
        h=locate_han(parts,r); v=locate_viet(spans,r,mod)
        if h and v:
            score=r.get('score'); score=score if type(score) in (int,float) and math.isfinite(score) else None
            out.append({'h0':h[0],'h1':h[1],'v':v,'score':score})
    return out

def feedback(parts, links, merge=False, threshold=None):
    cuts=set(boundaries(parts))
    for r in choose([r for r in links if threshold is None or (r['score'] is not None and r['score']>=threshold)]):
        a,b=r['h0'],r['h1']
        if merge: cuts={x for x in cuts if not a<x<b}
        cuts.update((a,b))
    return resegment(parts,cuts)

def viet_window(mod,viet,mapping,first,last,args):
    lo,hi=mod.window(mapping,first,last,args.margin)
    if args.viet_mode=='clause': spans=list(mod.pieces(viet,lo,hi))
    else: spans=[mod.Span(i,0,len(u.text),u.text) for i,u in enumerate(viet) if u.first<=hi and u.last>=lo]
    if not spans: raise ValueError('Empty Viet window')
    if args.max_viet_units and len(spans)>args.max_viet_units:
        raise ValueError(f'Viet window {len(spans)} exceeds cap; reduce block/margin or increase cap (no silent truncation)')
    return spans

def run(args):
    sys.path.insert(0,str(args.module_dir.resolve())); mod=importlib.import_module('batch_sentence_alignment')
    pages=load_pages(args.han_dir,*args.pages)
    from openpyxl import load_workbook
    wb=load_workbook(args.viet_xlsx,read_only=True,data_only=True)
    try:
        def enabled(x):
            return x is True or x==1 or (isinstance(x,str) and x.strip().lower() in ('true','1'))
        viet=[mod.Unit(r['id_vi'],r['viet_page_start'],r['viet_page_end'],r['text_vi']) for r in mod.table(wb,'CAU_VIET') if enabled(r['dung_de_ghep']) and r['text_vi']]
        mapping=[r for r in mod.table(wb,'TRANG_VIET') if isinstance(r['viet_pdf_page'],int)]
    finally: wb.close()
    if not viet or not mapping or len({u.id for u in viet})!=len(viet): raise ValueError('Invalid Viet workbook')
    args.output.mkdir(parents=True,exist_ok=True)
    client=Client(args,mod); reviews={}; results=[]; failures=[]; stats=[]
    review_path=args.output/'review.csv'
    old={r['pair_id']:r for r in read_csv(review_path)} if review_path.exists() else {}
    offset=0
    needed=set(args.variants)
    for start in range(0,len(pages),args.block_pages):
        block=pages[start:start+args.block_pages]; first,last=block[0][0],block[-1][0]
        raw=''.join(t for _,t in block); n=len(content(raw)); page_ends=boundaries([t for _,t in block]); block_id=f'{first:04}-{last:04}'
        try:
            spans=viet_window(mod,viet,mapping,first,last,args)
            vtexts=[s.text for s in spans]
        except Exception as e:
            failures.append({'block':block_id,'variant':'ALL','error':str(e)}); offset+=n; continue
        perpage=None; variants={}; aligned={}
        try:
            if needed-{'V4'}:
                perpage=[client.punctuate(t) for _,t in block]
                for name,marks in [('V0',SENT),('V1',SEMI),('V2',FINE)]:
                    variants[name]=[p for t in perpage for p in split_marks(t,marks)]
                variants['V3']=local_long(variants['V0'],args.long_chars)
        except Exception as e: failures.append({'block':block_id,'variant':'page_segmentation','error':str(e)})
        if 'V4' in needed:
            try: variants['V4']=split_marks(client.punctuate(raw),SENT)
            except Exception as e: failures.append({'block':block_id,'variant':'V4','error':str(e)})
        def alignment(parts):
            h=[' '.join(t.split()) for t in parts]
            response=client.align(h,vtexts)
            return parse_links(response,h,spans,mod)
        for name,base,merge in [('V5','V0',False),('V6','V2',True)]:
            if name not in needed or base not in variants: continue
            try:
                aligned[base]=alignment(variants[base])
                variants[name]=feedback(variants[base],aligned[base],merge,args.feedback_min_score)
            except Exception as e: failures.append({'block':block_id,'variant':name,'error':str(e)})
        for name in args.variants:
            try:
                parts=variants[name]
                if content(''.join(parts))!=content(raw): raise ValueError('Content preservation failed')
                ends=boundaries(parts); cuts=set(ends)
                units=[]
                for j,(a,b) in enumerate(zip(ends,ends[1:])):
                    p0=block[bisect.bisect_right(page_ends,a)-1][0]
                    p1=block[bisect.bisect_left(page_ends,b)-1][0]
                    units.append({'id_zh':f'{block_id}-S{j+1:04}','text_zh':parts[j], 'han_page_start':p0,'han_page_end':p1,'char_start':offset+a,'char_end':offset+b})
                write_csv(args.output/name/'segmented'/f'{block_id}.csv',units,['id_zh','text_zh','han_page_start','han_page_end','char_start','char_end'])
                links=aligned[name] if name in aligned else alignment(parts)
                strict=[r for r in links if r['h0'] in cuts and r['h1'] in cuts]
                selected=choose(strict); covered=0; out=[]; cursor=0
                for r in selected:
                    a,b=r['h0'],r['h1']; covered+=b-a
                    h=''.join(parts[ends.index(a):ends.index(b)])
                    v=' '.join(viet[i].text[x:y] for i,x,y in r['v'])
                    vr=[[viet[i].id,x,y] for i,x,y in r['v']]
                    key=digest([block_id,offset+a,offset+b,content(h),vr,v])[:24]
                    row={'variant':name,'block':block_id,'pair_id':key,'han_start':offset+a,'han_end':offset+b,'han_chars':b-a,'text_zh':h,'text_vi':v,'viet_spans':json.dumps(vr,ensure_ascii=False),'api_score':r['score'],'status':'matched'}
                    out.append(row); results.append(row)
                    if key not in reviews:
                        reviews[key]={'pair_id':key,'block':block_id,'text_zh':h,'text_vi':v,'viet_spans':row['viet_spans'],'variants':name,'label':old.get(key,{}).get('label',''),'note':old.get(key,{}).get('note','')}
                    else: reviews[key]['variants']+=';'+name
                for a,b in zip(ends,ends[1:]):
                    if not any(r['h0']<=a and b<=r['h1'] for r in selected):
                        out.append({'variant':name,'block':block_id,'pair_id':'','han_start':offset+a,'han_end':offset+b,'han_chars':b-a,'text_zh':parts[ends.index(a)],'text_vi':'','viet_spans':'','api_score':None,'status':'unmatched'})
                write_csv(args.output/name/'alignment'/f'{block_id}.csv',sorted(out,key=lambda r:r['han_start']),RESULT_FIELDS)
                stats.append({'variant':name,'block':block_id,'source_chars':n,'han_units':len(parts),'selected_pairs':len(selected),'matched_chars':covered,'partial_candidates':len(links)-len(strict)})
                print(f'{block_id} {name}: {len(parts)} units, {len(selected)} pairs, {covered}/{n} chars',flush=True)
            except Exception as e:
                failures.append({'block':block_id,'variant':name,'error':str(e)})
                print(f'{block_id} {name}: FAILED {e}',flush=True)
        offset+=n
        write_csv(review_path,list(reviews.values()),REVIEW_FIELDS)
        write_csv(args.output/'pairs.csv',results,RESULT_FIELDS)
        dump(args.output/'run.json',{'stats':stats,'failures':failures,'source_chars':offset,'api_calls':client.calls,'cache_hits':client.hits,'variants':args.variants,'viet_mode':args.viet_mode})
    # Resolve overlapping Viet windows globally, not just inside each block.
    vi_index={u.id:i for i,u in enumerate(viet)}
    keep=set()
    for name in args.variants:
        candidates=[]
        for r in results:
            if r['variant']!=name: continue
            candidates.append({'h0':r['han_start'],'h1':r['han_end'],'v':[(vi_index[i],a,b) for i,a,b in json.loads(r['viet_spans'])],'key':r['pair_id']})
        keep.update((name,r['key']) for r in choose(candidates))
    results=[r for r in results if (r['variant'],r['pair_id']) in keep]
    for key in list(reviews):
        names=[n for n in args.variants if (n,key) in keep]
        if names: reviews[key]['variants']=';'.join(names)
        else: del reviews[key]
    for st in stats:
        name,bid=st['variant'],st['block']
        selected=[r for r in results if r['variant']==name and r['block']==bid]
        st['selected_pairs']=len(selected); st['matched_chars']=sum(r['han_chars'] for r in selected)
        out=list(selected)
        for u in read_csv(args.output/name/'segmented'/f'{bid}.csv'):
            a,b=int(u['char_start']),int(u['char_end'])
            if not any(r['han_start']<=a and b<=r['han_end'] for r in selected):
                out.append({'variant':name,'block':bid,'pair_id':'','han_start':a,'han_end':b,'han_chars':b-a,'text_zh':u['text_zh'],'text_vi':'','viet_spans':'','api_score':None,'status':'unmatched'})
        write_csv(args.output/name/'alignment'/f'{bid}.csv',sorted(out,key=lambda r:r['han_start']),RESULT_FIELDS)
    # Also writes a valid empty report if all blocks failed before alignment.
    write_csv(review_path,list(reviews.values()),REVIEW_FIELDS); write_csv(args.output/'pairs.csv',results,RESULT_FIELDS)
    dump(args.output/'run.json',{'stats':stats,'failures':failures,'source_chars':offset,'api_calls':client.calls,'cache_hits':client.hits,'variants':args.variants,'viet_mode':args.viet_mode})
    evaluate(args.output)

RESULT_FIELDS=['variant','block','pair_id','han_start','han_end','han_chars','text_zh','text_vi','viet_spans','api_score','status']
REVIEW_FIELDS=['pair_id','block','text_zh','text_vi','viet_spans','variants','label','note']

def evaluate(folder):
    report=json.loads((folder/'run.json').read_text(encoding='utf-8'))
    labels={r['pair_id']:r['label'].strip() for r in read_csv(folder/'review.csv')}
    if any(x not in ('','0','1') for x in labels.values()): raise ValueError('Review labels must be blank, 0 or 1')
    pairs=read_csv(folder/'pairs.csv'); rows=[]; total=report['source_chars']
    for name in report['variants']:
        ss=[r for r in report['stats'] if r['variant']==name]; pp=[r for r in pairs if r['variant']==name]
        yes=[r for r in pp if labels.get(r['pair_id'])=='1']; no=[r for r in pp if labels.get(r['pair_id'])=='0']; pending=len(pp)-len(yes)-len(no)
        good=sum(int(r['han_chars']) for r in yes); matched=sum(r['matched_chars'] for r in ss); processed=sum(r['source_chars'] for r in ss)
        rows.append({'variant':name,'complete':processed==total and total>0,'source_chars':total,'processed_chars':processed,'han_units':sum(r['han_units'] for r in ss),'pairs':len(pp),'label_1':len(yes),'label_0':len(no),'pending':pending,'reviewed_precision':len(yes)/(len(yes)+len(no)) if yes or no else '', 'matched_char_coverage':matched/total if total else '', 'verified_correct_char_coverage':good/total if total else '', 'correct_chars':good})
    write_csv(folder/'comparison.csv',rows,list(rows[0]) if rows else ['variant'])
    print(json.dumps(rows,ensure_ascii=False,indent=2))

def main():
    p=argparse.ArgumentParser(description=__doc__); sub=p.add_subparsers(dest='command',required=True)
    r=sub.add_parser('run'); r.add_argument('--han-dir',type=Path,required=True); r.add_argument('--viet-xlsx',type=Path,required=True); r.add_argument('--output',type=Path,required=True); r.add_argument('--pages',nargs=2,type=int,required=True); r.add_argument('--module-dir',type=Path,default=Path(__file__).resolve().parent)
    r.add_argument('--variants',nargs='+',choices=VARIANTS,default=list(VARIANTS)); r.add_argument('--block-pages',type=int,default=2); r.add_argument('--long-chars',type=int,default=45); r.add_argument('--margin',type=int,default=1); r.add_argument('--max-viet-units',type=int,default=0); r.add_argument('--viet-mode',choices=['sentence','clause'],default='sentence'); r.add_argument('--feedback-min-score',type=float,default=None); r.add_argument('--max-calls',type=int,default=100); r.add_argument('--delay',type=float,default=0.5); r.add_argument('--timeout',type=float,default=90)
    e=sub.add_parser('evaluate'); e.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.command=='evaluate': evaluate(a.output); return
    if not (0<a.pages[0]<=a.pages[1] and min(a.block_pages,a.long_chars,a.max_calls,a.timeout)>0 and min(a.margin,a.max_viet_units,a.delay)>=0): p.error('Invalid limits')
    a.variants=list(dict.fromkeys(a.variants)); run(a)

if __name__=='__main__': main()
