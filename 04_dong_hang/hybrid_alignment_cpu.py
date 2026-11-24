#!/usr/bin/env python3
"""CPU-only API-guided joint segmentation/alignment. Requires the three existing
scripts experiment_seg_align.py, joint_seg_align_cpu.py, batch_sentence_alignment.py
and their existing align_sinonom_api.py dependency beside this file.
No automatic semantic labels. Character offsets exclude whitespace/punctuation.
"""
import argparse, bisect, math, os, re, sys, subprocess, urllib.request
from pathlib import Path
from collections import Counter, defaultdict

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent if HERE.name=='04_dong_hang' else HERE
VARIANTS=['V18','V19','V20','V21','V22','V23']
DICT=HERE/'Unihan.zip'

def install():
    subprocess.check_call([sys.executable,'-m','pip','install','requests','openpyxl'])
    if not DICT.exists():
        tmp=DICT.with_suffix('.download')
        urllib.request.urlretrieve('https://www.unicode.org/Public/UCD/latest/ucd/Unihan.zip',tmp)
        tmp.replace(DICT)
    print('Installed. No torch or GPU required.')

def key(r): return (r['h0'],r['h1'],tuple(tuple(x) for x in r['v']))
def vstart(r): return (r['v'][0][0],r['v'][0][1])
def vend(r): return (r['v'][-1][0],r['v'][-1][2])

def select(rows):
    """Exact max-weight monotone chain over candidate intervals, with free skips."""
    rows=sorted((r for r in rows if r['weight']>0),key=lambda r:(r['h1'],r['h0'],vstart(r)))
    dp=[]; prev=[]
    for i,r in enumerate(rows):
        best=0.; parent=-1
        for j,s in enumerate(rows[:i]):
            if s['h1']<=r['h0'] and vend(s)<=vstart(r) and dp[j]>best:
                best=dp[j]; parent=j
        dp.append(best+r['weight']); prev.append(parent)
    if not dp:return []
    i=max(range(len(dp)),key=dp.__getitem__); out=[]
    while i>=0:out.append(rows[i]);i=prev[i]
    return out[::-1]

def tokens(s):
    import joint_seg_align_cpu as j
    return re.findall(r'\w+',j.norm(s))

def features(h,v,d,idf):
    import joint_seg_align_cpu as j
    ht=[j.norm(d[c]) if c in d else '\0' for c in h]
    vt=tokens(v)
    def grams(ts,n):return Counter(tuple(ts[i:i+n]) for i in range(len(ts)-n+1) if '\0' not in ts[i:i+n])
    def f(n):
        a,b=grams(ht,n),grams(vt,n)
        w=lambda g: idf.get(g,1.0)
        inter=sum(c*w(g) for g,c in (a&b).items())
        den=sum(c*w(g) for g,c in a.items())+sum(c*w(g) for g,c in b.items())
        return 2*inter/den if den else 0.
    phrase=.25*f(1)+.5*f(2)+.25*f(3)
    hn,vn=j.nums(h,'zh'),j.nums(v,'vi')
    num=(len(hn&vn)/len(hn|vn)-.5*bool(hn-vn and vn-hn)) if hn and vn else 0.
    return phrase,num

def idf_for(viet):
    df=Counter()
    for u in viet:
        t=tokens(u.text); df.update({tuple(t[i:i+n]) for n in (1,2,3) for i in range(len(t)-n+1)})
    return {g:1+math.log((len(viet)+1)/(c+1)) for g,c in df.items()}

def full_viet(r,viet):
    return [(i,0,len(viet[i].text)) for i in range(r['v'][0][0],r['v'][-1][0]+1)]

def safe_viet(r,viet):
    # Reject boundary inside digit strings, including thousands separators.
    for i,a,b in r['v']:
        t=viet[i].text
        for m in re.finditer(r'\d+(?:[.,]\d+)+|\d+',t):
            if m.start()<a<m.end() or m.start()<b<m.end():return False
    return True

def collect(client,mod,parts,spans,off,tag,pool,logs,viet):
    import experiment_seg_align as e
    if not parts or not spans:return
    rec={'tag':tag,'han_units':len(parts),'viet_units':len(spans)}; logs.append(rec)
    try:
        h=[' '.join(t.split()) for t in parts]; response=client.align(h,[s.text for s in spans])
        links=e.parse_links(response,h,spans,mod); rec['traceable']=len(links); rec['ok']=True
        for r in links:
            r['h0']+=off;r['h1']+=off
            if not safe_viet(r,viet):continue
            k=key(r)
            if k not in pool:pool[k]={**r,'votes':set()}
            pool[k]['votes'].add(e.digest([h,[s.text for s in spans]]))
            if r['score'] is not None and (pool[k]['score'] is None or r['score']>pool[k]['score']):pool[k]['score']=r['score']
    except Exception as exc:rec['error']=str(exc);print(tag,'FAILED',exc,flush=True)

def run(a):
    import experiment_seg_align as e
    import joint_seg_align_cpu as j
    import batch_sentence_alignment as mod
    a.output.mkdir(parents=True,exist_ok=True)
    pages=e.load_pages(a.han_dir,*a.pages)
    raw=''.join(e.content(t) for _,t in pages); n=len(raw)
    pagecuts=e.boundaries([t for _,t in pages])
    vv,mapping=j.load_viet(a.viet_xlsx)
    viet=[mod.Unit(u['id'],u['first'],u['last'],u['text']) for u in vv]
    d=j.hv_dictionary(a.dictionary); idf=idf_for(viet)
    client=e.Client(a,mod); pool={}; logs=[]; base={}; preferred={0,n}; blocks=[]; successful=set()
    for start in range(0,len(pages),a.block_pages):
        block=pages[start:start+a.block_pages]; off=pagecuts[start]; end=pagecuts[start+len(block)]
        text=''.join(t for _,t in block); bid=f'{block[0][0]:04}-{block[-1][0]:04}'; blocks.append((off,end,bid))
        try: punct=client.punctuate(text)
        except Exception as exc:
            logs.append({'tag':bid+':split','error':str(exc)}); print('Segmentation failed:',exc,flush=True); continue
        coarse=e.split_marks(punct,e.SENT); fine=e.split_marks(punct,e.FINE)
        successful.add(bid)
        preferred.update(off+x for x in e.boundaries(coarse)); preferred.update(off+x for x in e.boundaries(fine))
        def window(margin):
            lo,hi=j.window(mapping,block[0][0],block[-1][0],margin)
            return [mod.Span(i,0,len(u.text),u.text) for i,u in enumerate(viet) if u.first<=hi and u.last>=lo]
        # Adaptive first pass: retry wider only if no traceable pair. No splitting Vietnamese numbers.
        for margin in sorted({0,a.margin}):
            spans=window(margin)
            if len(spans)>a.max_viet_units:
                logs.append({'tag':bid+':window','error':'Vietnamese window exceeds limit'});continue
            collect(client,mod,coarse,spans,off,bid+f':coarse:{margin}',base,logs,viet)
            if any(off<=r['h0']<end for r in base.values()):break
        for parts,kind in [(coarse,'coarse'),(fine,'fine')]:
            for margin in sorted({0,a.margin}):
                spans=window(margin)
                if len(spans)>a.max_viet_units:continue
                collect(client,mod,parts,spans,off,bid+f':{kind}:{margin}',pool,logs,viet)
    for k,r in base.items():
        if k in pool:pool[k]['votes'].update(r['votes'])
        else:pool[k]=r
    print('API candidates:',len(pool),'calls:',client.calls,'cache hits:',client.hits,flush=True)
    def vt(r):return ' '.join(viet[i].text[x:y] for i,x,y in r['v'])
    def enrich(r):
        p,num=features(raw[r['h0']:r['h1']],vt(r),d,idf)
        return {**r,'phrase':p,'number':num}
    initial=[enrich(r) for r in base.values()]; multi=[enrich(r) for r in pool.values()]
    # Refine only near API proposals, including expansion to intact Vietnamese rows.
    refined=dict((key(r),r) for r in multi)
    forbidden={i for m in j.ZHNUM.finditer(raw) for i in range(m.start()+1,m.end())}
    for r in multi:
        left,right=r['h0'],r['h1']; block=next((b for b in blocks if b[0]<=left<b[1]),None)
        if not block:continue
        lo,hi,_=block; local=[]
        for vv in [r['v'],full_viet(r,viet)]:
            for x in range(max(lo,left-a.radius),min(hi,left+a.radius)+1):
                for y in range(max(lo,right-a.radius),min(hi,right+a.radius)+1):
                    if x in forbidden or y in forbidden or y-x<2:continue
                    z={**r,'h0':x,'h1':y,'v':vv,'score':None,'votes':set(),'parent_votes':len(r['votes']),'distance':abs(x-left)+abs(y-right)}
                    if key(z) in refined:continue
                    z=enrich(z);local.append(z)
        # Local lexical pruning only; these variants are not API-confirmed.
        local.sort(key=lambda z:(z['phrase']+.15*z['number']-.003*z['distance']),reverse=True)
        for z in local[:a.top_refine]:refined.setdefault(key(z),z)
    print('Refined candidates:',len(refined),flush=True)
    def score(r,name):
        votes=len(r['votes']); api=r['score']; api=0. if api is None else max(0.,min(1.,api))
        # API score scale is not calibrated; bounded heuristic only.
        consensus=min(votes,4)/4; prior=.30*bool(votes)+.15*consensus+.05*api
        dist=r.get('distance',0); phrase=r['phrase']; num=r['number']
        if name=='V18':s=.30+.05*api
        elif name=='V19':s=prior
        elif name=='V20':s=prior+.45*phrase-.005*dist
        elif name=='V21':s=prior+.85*phrase-.005*dist
        else:s=prior+.85*phrase+.20*num-.005*dist
        if not votes and name in ('V20','V21','V22','V23'):
            # A refined proposal has no direct API vote. Require lexical evidence.
            s+=.12*min(r.get('parent_votes',0),4)/4
            if phrase<a.refine_min:return -1.
        return s-(a.threshold if name=='V23' else .10)
    old={r['pair_id']:r for r in e.read_csv(a.output/'review.csv')} if (a.output/'review.csv').exists() else {}
    reviews={}; results=[]; stats=[]; candidate_rows=[]
    for name in VARIANTS:
        source=initial if name=='V18' else multi if name=='V19' else list(refined.values())
        rr=[{**r,'weight':score(r,name)} for r in source]; chosen=select(rr)
        for r in rr:
            candidate_rows.append(dict(variant=name,han_start=r['h0'],han_end=r['h1'],text_zh=raw[r['h0']:r['h1']],text_vi=vt(r),api_votes=len(r['votes']),api_score=r['score'],phrase_f1=r['phrase'],number_score=r['number'],weight=r['weight'],selected=int(r in chosen)))
        for lo,hi,bid in blocks:
            selected=[r for r in chosen if lo<=r['h0']<hi]; cuts={lo,hi}
            for r in selected:cuts.update((r['h0'],r['h1']))
            for x in preferred:
                if lo<x<hi and not any(r['h0']<x<r['h1'] for r in selected):cuts.add(x)
            cuts=sorted(cuts); units=[]; out=[]
            for i,(x,y) in enumerate(zip(cuts,cuts[1:])):
                units.append(dict(id_zh=f'{bid}-S{i+1:04}',text_zh=raw[x:y],han_page_start=pages[bisect.bisect_right(pagecuts,x)-1][0],han_page_end=pages[bisect.bisect_left(pagecuts,y)-1][0],char_start=x,char_end=y))
                if not any(r['h0']<=x and y<=r['h1'] for r in selected):out.append(dict(variant=name,block=bid,pair_id='',han_start=x,han_end=y,han_chars=y-x,text_zh=raw[x:y],text_vi='',viet_spans='',api_score=None,status='unmatched'))
            assert ''.join(u['text_zh'] for u in units)==raw[lo:hi]
            for r in selected:
                x,y=r['h0'],r['h1']; h=raw[x:y];v=vt(r); spans=[[viet[i].id,s,t] for i,s,t in r['v']]; k=e.digest([a.pages,x,y,h,spans,v])[:24]
                row=dict(variant=name,block=bid,pair_id=k,han_start=x,han_end=y,han_chars=y-x,text_zh=h,text_vi=v,viet_spans=e.json.dumps(spans,ensure_ascii=False),api_score=r['score'],status='matched')
                out.append(row);results.append(row)
                if k not in reviews:reviews[k]=dict(pair_id=k,block=bid,text_zh=h,text_vi=v,viet_spans=row['viet_spans'],variants=name,label=old.get(k,{}).get('label',''),note=old.get(k,{}).get('note',''))
                else:reviews[k]['variants']+=';'+name
            e.write_csv(a.output/name/'segmented'/f'{bid}.csv',units,list(units[0]))
            e.write_csv(a.output/name/'alignment'/f'{bid}.csv',sorted(out,key=lambda r:r['han_start']),e.RESULT_FIELDS)
            stats.append(dict(variant=name,block=bid,source_chars=(hi-lo if bid in successful and any(t.get('ok') and t['tag'].startswith(bid+':') for t in logs) else 0),han_units=len(units),matched_chars=sum(r['h1']-r['h0'] for r in selected)))
        print(name,len(chosen),'pairs',flush=True)
    e.write_csv(a.output/'pairs.csv',results,e.RESULT_FIELDS);e.write_csv(a.output/'review.csv',list(reviews.values()),e.REVIEW_FIELDS)
    if candidate_rows:e.write_csv(a.output/'candidates.csv',candidate_rows,list(candidate_rows[0]))
    e.dump(a.output/'run.json',dict(variants=VARIANTS,stats=stats,source_chars=n,api_calls=client.calls,cache_hits=client.hits,attempts=logs,failures=[r for r in logs if 'error' in r],dictionary_entries=len(d)))
    e.evaluate(a.output)

def main():
    p=argparse.ArgumentParser(description=__doc__); s=p.add_subparsers(dest='command',required=True)
    s.add_parser('install');s.add_parser('selftest');r=s.add_parser('run');ev=s.add_parser('evaluate')
    default=HERE/'hybrid_experiments';ev.add_argument('--output',type=Path,default=default)
    r.add_argument('--output',type=Path,default=default);r.add_argument('--han-dir',type=Path,default=ROOT/'02_ocr_tho/Cap_01/HAN/pages');r.add_argument('--viet-xlsx',type=Path,default=ROOT/'02_ocr_tho/Cap_01/VIET/VIET_0186-0251.xlsx');r.add_argument('--pages',nargs=2,type=int,default=[1,2]);r.add_argument('--dictionary',type=Path,default=DICT)
    for name,default in [('block-pages',2),('margin',1),('max-viet-units',40),('max-calls',40),('radius',3),('top-refine',8)]:r.add_argument('--'+name,type=int,default=default)
    for name,default in [('delay',1.),('timeout',90.),('threshold',.45),('refine-min',.05)]:r.add_argument('--'+name,type=float,default=default)
    a=p.parse_args()
    if a.command=='install':install();return
    if a.command=='selftest':
        def r(x,y,i,w):return dict(h0=x,h1=y,v=[(i,0,3)],weight=w)
        assert select([r(0,8,0,1),r(0,4,0,.7),r(4,8,1,.7)])==[r(0,4,0,.7),r(4,8,1,.7)]
        assert not select([r(0,2,0,-1)])
        assert len(select([r(0,2,0,1),r(2,4,0,1)]))==1
        print('DP selftest PASS');return
    if a.command=='evaluate':
        import experiment_seg_align as e;e.evaluate(a.output);return
    if not (0<a.pages[0]<=a.pages[1] and min(a.block_pages,a.max_calls,a.max_viet_units,a.top_refine,a.timeout)>0 and min(a.radius,a.margin,a.delay)>=0):p.error('Invalid limits')
    run(a)
if __name__=='__main__':main()
