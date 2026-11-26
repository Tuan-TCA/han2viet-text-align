"""Release experiment and segmentation-only Stage 04 handoff."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
from statistics import mean,median
import time

from preprocess import ROOT,STAGE,read_jsonl,write_json,load_sources,normalize,viet_t1,fingerprint
from coarse_alignment import window
from api_integration import ALIGN,SEPARATE,Client,CONFIRMED
from release_segmentation import METHODS,partition
from release_audit import audit
from evaluate_pipeline import evaluate,export_stage04,workbook


class Reuse(Client):
    def __init__(self,out,cfg,live):
        super().__init__(out,cfg,live); self.old={}; self.used=[]
        for root in (STAGE/'artifacts/benchmark',STAGE/'artifacts/ablation',STAGE/'artifacts/heldout',STAGE/'artifacts/release'):
            for f in root.glob('*/cache/*.json'):
                if f.parent!=self.cache: self.old.setdefault(f.stem,f)

    def call(self,url,payload):
        k=fingerprint([url,payload]); old=self.old.get(k)
        if old and not (self.cache/(k+'.json')).exists():
            obj=json.loads(old.read_text(encoding='utf8'))
            if obj.get('endpoint')==url and obj.get('payload')==payload and obj.get('status')=='ok':
                self.hits+=1; self.used.append({'key':k,'source':str(old.relative_to(ROOT))}); return obj
        if k in self.seeds: self.used.append({'key':k,'source':'pipeline/artifacts/separate_pilot_cap01/results.json'})
        return super().call(url,payload)


def nested(viet,anchor,size):
    start=max(0,min(len(viet)-size,anchor-size//2)); return viet[start:start+size]


def corresponding(pages,maps,cap,vi):
    vp={n for v in vi for n in range(v['viet_page_start'],v['viet_page_end']+1)}
    rows=[m for m in maps if m['cap']==cap]; points=defaultdict(list)
    for m in rows:
        points[m['viet_pdf_page']].extend(a['han_pdf_page'] for a in m['verified_overlap'])
    estimated=[]
    for m in rows:
        n=m['viet_pdf_page']; bounds=m['han_search_window']
        if n not in vp or not bounds: continue
        if points[n]: estimated.extend(points[n]); continue
        anchors=sorted(k for k,v in points.items() if v)
        left=max((k for k in anchors if k<n),default=None); right=min((k for k in anchors if k>n),default=None)
        if left and right:
            y=mean(points[left])+(mean(points[right])-mean(points[left]))*(n-left)/(right-left)
            estimated.append(max(bounds[0],min(bounds[1],round(y))))
        else: estimated.extend(bounds)
    if not estimated: return None
    w=window(pages,vi,maps,cap,range(min(estimated),max(estimated)+1),viet_pages=[min(vp),max(vp)])
    w['viet']=vi; return w


def availability(w,spans,refs):
    if not refs: return []
    start=w['start']; raw=w['raw']; end=start+len(raw)
    lo=max(start,min(r['Han_Start_0'] for r in refs)); hi=min(end,max(r['Han_End_exclusive'] for r in refs))
    canonical=lambda p: start+len(raw[:p-start].rstrip())
    pred={canonical(start+b) for _,b in spans if lo<start+b<hi}
    sets={k:{canonical(r['comparison'][k+'_End']) for r in refs if lo<r['comparison'][k+'_End']<hi} for k in ('CG','DS')}
    sets['agreed']=sets['CG']&sets['DS']; rows=[]
    for name,truth in sets.items():
        hit=len(pred&truth); rec=hit/len(truth) if truth else None
        rows.append(dict(reference=name,hits=hit,total=len(truth),availability=rec,precision=hit/len(pred) if pred else None,
                         recall=rec,f1=2*hit/(len(pred)+len(truth)) if pred or truth else None,missing_raw=sorted(truth-pred),predicted=len(pred)))
    return rows


def exports(w,spans,method):
    rows=[]
    for i,(a,b) in enumerate(spans,1):
        lo,hi=w['start']+a,w['start']+b; text=w['raw'][a:b]; norm,ix=normalize(text); sources=[]
        for p in w['pages']:
            x,y=p['global_raw_span']; left,right=max(lo,x),min(hi,y)
            if left<right:
                f=p['file_text_span'][0]; sources.append({'page':p['han_pdf_page'],'file':p['source']['path'],'file_span':[f+left-x,f+right-x]})
        rows.append(dict(id_zh=f"{w['id']}-{method}-{i:04}",window=w['id'],method=method,page_start=sources[0]['page'],page_end=sources[-1]['page'],
                         global_raw_span=[lo,hi],source=sources,text_original=text,text_zh=norm,normalized_source_spans=[[lo+u,lo+v] for u,v in ix],mapping_status=w['status']))
    return rows


def t1_rows(w):
    out=[]
    for v in w['viet']:
        text=v['text_original']; sent,ix=viet_t1(text,CONFIRMED.get(v['id'],()))
        out.append(dict(vi_id=v['id'],text_original=text,text_t1=sent,normalized_source_spans=ix,source=v['source'],
                        viet_page_start=v['viet_page_start'],viet_page_end=v['viet_page_end']))
    return out


def run_case(out,client,w,name,phase,refs,common=()):
    tag=f"{phase}-{w['id']}-{len(w['viet'])}-{name}"; cp=out/'cases'/(tag+'.json')
    if cp.exists(): return json.loads(cp.read_text(encoding='utf8'))
    tick=time.monotonic(); n=client.attempts; hits=client.hits
    key,pr,status=client.separate(w['raw']); s={'case':tag,'phase':phase,'method':name,'pages':w['id'],
        'cap':w['cap'],'vi_count':len(w['viet']),'vi_ids':[v['id'] for v in w['viet']],'separate_key':key,'separate_status':status}
    data={'row':s,'boundary':[],'groups':[],'segments':[],'viet':t1_rows(w),'mapping':w['mapping']}
    if status=='ok':
        spans,conflicts=partition(w['raw'],pr,name); lengths=[b-a for a,b in spans]
        ids=set(s['vi_ids']); eligible=[r for r in refs if r['VI_ID'] in ids and w['start']<=min(r['comparison'][k+'_Start'] for k in ('CG','DS'))
                                           and max(r['comparison'][k+'_End'] for k in ('CG','DS'))<=w['start']+len(w['raw'])]
        res=client.align(tag,w['raw'],spans,w['viet']); mets,detail=evaluate(w,spans,res,eligible)
        s.update(segments=len(spans),mean_length=mean(lengths),median_length=median(lengths),max_length=max(lengths),ratio=len(spans)/len(ids) if ids else None,
                 protected_conflicts=conflicts,api_status=res['status'],alignment_key=res.get('request_key'),reference_n=len(eligible),
                 **{k:mets[k] for k in ('exact_reconstruction','missing','duplicated','han_coverage','vi_coverage','alignment_types','unresolved','references')})
        data.update(boundary=availability(w,spans,eligible),segments=exports(w,spans,name),details=detail,alignment=res)
        for g in res['groups']:
            a,b=g['Han_Start'],g['Han_End']; data['groups'].append({**g,'cap':w['cap'],'global_span':[w['start']+a,w['start']+b] if a is not None else None})
        if common:
            for ref in ('CG','DS','agreed'):
                rr=[r for r in detail if r['reference']==ref and r['pair'] in common]; s['common_'+ref]={'eligible':len(rr),'exact':sum(r['alignment_exact'] for r in rr) if res['status']=='ok' else None,
                             'iou':mean(r['iou'] for r in rr) if rr and res['status']=='ok' else None}
    else: s['api_status']='not_attempted'
    s.update(runtime_s=round(time.monotonic()-tick,3),requests=client.attempts-n,cache_hits=client.hits-hits)
    write_json(cp,data); print(tag,s['api_status'],s.get('segments'),flush=True); return data


def dump_jsonl(path,rows): path.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf8')


def publish_inputs(out,rows,contexts):
    dump_jsonl(out/'han_segments.jsonl',rows); dump_jsonl(out/'window_context.jsonl',contexts)
    workbook(out/'han_segmented.xlsx',{'Segments':[{k:v for k,v in r.items() if k!='normalized_source_spans'} for r in rows]})
    export_stage04(out,rows)


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('mode',choices=['evaluate','prepare']);p.add_argument('--run-id')
    p.add_argument('--live',action='store_true');p.add_argument('--resume',action='store_true');p.add_argument('--cap',choices=['Cap_01','Cap_02']);p.add_argument('--pages',nargs=2,type=int)
    p.add_argument('--method',choices=METHODS,default='S4'); args=p.parse_args()
    if args.mode=='prepare' and args.method!='S4': p.error('Production is frozen at S4 + T1')
    if args.mode=='prepare' and args.run_id is None:
        if args.cap or args.pages: p.error('Official preparation inventories both complete Caps; use --run-id for a separate range export')
        from production_prepare import produce
        return produce(args.live,args.resume)
    if not args.run_id or not re.fullmatch(r'[A-Za-z0-9_-]+',args.run_id): p.error('invalid run ID')
    if args.mode=='prepare' and not (args.cap and args.pages): p.error('--cap and --pages FIRST LAST required')
    cfg=json.loads((STAGE/'config/stage03_release.json').read_text(encoding='utf8')); pp,vv,mm=load_sources()
    out=STAGE/'artifacts/release'/args.run_id; out.mkdir(parents=True,exist_ok=args.resume);(out/'cases').mkdir(exist_ok=True)
    manifest={'config':cfg,'mode':args.mode,'source_hash':fingerprint([pp,vv,mm]),'method':args.method,'cap':args.cap,'pages':args.pages,
              'implementation':fingerprint([(f.name,f.read_text(encoding='utf8')) for f in sorted((STAGE/'scripts').glob('*release*.py'))])}
    mp=out/'manifest.json'
    if mp.exists() and json.loads(mp.read_text(encoding='utf8'))!=manifest: p.error('different run inputs/configuration')
    write_json(mp,manifest); client=Reuse(out,cfg,args.live)
    try:
        if args.mode=='prepare':
            first,last=args.pages; ns={p['han_pdf_page'] for p in pp if p['cap']==args.cap}
            if not 1<=first<=last<=max(ns): p.error('page range out of bounds')
            rows=[]; contexts=[]
            for n in range(first,last+1,2):
                w=window(pp,vv,mm,args.cap,list(range(n,min(last,n+1)+1)),1); key,pr,status=client.separate(w['raw'])
                context={'window':w['id'],'mapping':w['mapping'],'status':w['status'],'viet':t1_rows(w),'separate_status':status,'separate_key':key,
                         'source_pages':w['pages']}; contexts.append(context)
                if status=='ok': rows.extend(exports(w,partition(w['raw'],pr,args.method)[0],args.method))
                if client.halt: break
            publish_inputs(out,rows,contexts)
            return int(any(c['separate_status']!='ok' for c in contexts) or bool(client.halt))
        return experiments(out,client,cfg,pp,vv,mm)
    finally: client.close()


def experiments(out,client,cfg,pp,vv,mm):
    aud=audit(pp,vv,mm); workbook(out/'coarse_alignment_audit.xlsx',{'Page_Audit':aud})
    silver=read_jsonl(ROOT/'pipeline/artifacts/phase1/silver_benchmark.jsonl'); cap=cfg['benchmark_cap']; pilot=window(pp,vv,mm,cap,cfg['benchmark_pages'],viet_pages=cfg['benchmark_vi_pages'])
    cases=[run_case(out,client,pilot,m,'density',silver) for m in METHODS]; density=[c['row'] for c in cases]
    def rank(r):
        refs=r.get('references') or {}; return (r['api_status']=='ok',sum((refs.get(k,{}).get('alignment_exact') or 0) for k in ('CG','DS')),
                 sum((refs.get(k,{}).get('mean_iou') or 0) for k in ('CG','DS')),-int(r['method'][1:]))
    challenger=max((r for r in density if r['method'] in ('S5','S6','S7','S8')),key=rank)['method']; finalists=['S4',challenger]
    pool=[v for v in vv if v['cap']==cap]; center=next(i for i,v in enumerate(pool) if v['id']==pilot['viet'][len(pilot['viet'])//2]['id'])
    windows=[corresponding(pp,mm,cap,nested(pool,center,n)) for n in cfg['sizes']]
    common=[r['Pair_ID'] for r in silver if all(r['VI_ID'] in {v['id'] for v in w['viet']} and w['start']<=min(r['comparison'][k+'_Start'] for k in ('CG','DS')) and
                 max(r['comparison'][k+'_End'] for k in ('CG','DS'))<=w['start']+len(w['raw']) for w in windows)]
    for w in windows:
        for m in finalists: cases.append(run_case(out,client,w,m,'context',silver,common))
    used={(cap,n) for n in range(1,11)}|{(cap,p['han_pdf_page']) for w in windows for p in w['pages']}
    for f in (STAGE/'artifacts/heldout').glob('*/manifest.json'):
        for c,ns in json.loads(f.read_text(encoding='utf8'))['heldout']: used.update((c,n) for n in ns)
    from run_pipeline import known_used
    used.update(known_used(mm)); fresh=[]
    for c in sorted({p['cap'] for p in pp}):
        nums={r['page'] for r in aud if r['cap']==c and r['page_has_window'] and (c,r['page']) not in used}
        pairs=[n for n in sorted(nums) if n+1 in nums]; picks=[pairs[len(pairs)//3],pairs[2*len(pairs)//3]]
        for n in picks: fresh.append(window(pp,vv,mm,c,[n,n+1],1))
    freeze={'finalists':finalists,'stress_control':'S9','fresh_windows':[w['id'] for w in fresh],'common_reference_ids':common,
            'prior_pages_excluded':sorted(used),'rule':'Keep S4 unless paired downstream evidence improves without fresh reliability regression.'}
    write_json(out/'frozen.json',freeze)
    for w in fresh:
        for m in finalists+['S9']: cases.append(run_case(out,client,w,m,'fresh',[]))
    scores=[c['row'] for c in cases]; flat=[]
    for s in scores:
        row={k:v for k,v in s.items() if k!='references'}
        for k,ref in (s.get('references') or {}).items(): row.update({k+'_'+f:v for f,v in ref.items()})
        flat.append(row)
    workbook(out/'segmentation_density_comparison.xlsx',{'Density':[r for r in flat if r['phase']=='density'],'Fresh':[r for r in flat if r['phase']=='fresh']})
    workbook(out/'window_size_comparison.xlsx',{'Context':[r for r in flat if r['phase']=='context'],'Common_pairs':[{'Pair_ID':k} for k in common]})
    workbook(out/'boundary_availability.xlsx',{'Boundaries':[{'case':c['row']['case'],**b} for c in cases for b in c['boundary']]})
    unique={}
    for case in cases:
        for g in case['groups']:
            k=fingerprint([g['cap'],g['global_span'],g['VI_Char_Spans'],g['Han_Text'],g['Vietnamese_Text']]); entry=unique.setdefault(k,
               {'prediction_id':k,'cap':g['cap'],'han_global_span':g['global_span'],'han':g['Han_Text'],'vi_spans':g['VI_Char_Spans'],'vi':g['Vietnamese_Text'],
                'Label_Target':'UNKNOWN','OMISSION':None,'ADDITION':None,'MISSING':None,'occurrences':[]})
            entry['occurrences'].append([case['row']['case'],g['Validation_Status'],g['Score']])
    workbook(out/'semantic_review.xlsx',{'Unique_Predictions':unique.values()})
    publish_inputs(out,[r for c in cases if c['row']['method']=='S4' and c['row']['phase'] in ('density','fresh') for r in c['segments']],
                   [{'window':c['row']['pages'],'viet':c['viet'],'mapping':c['mapping']} for c in cases if c['row']['method']=='S4' and c['row']['phase'] in ('density','fresh')])
    write_json(out/'metrics.json',{'cases':scores,'availability':{c['row']['case']:c['boundary'] for c in cases},'unique_predictions':len(unique),
               'verified_positive':0,'verified_negative':0,'unknown':len(unique),'reuse':client.used,'frozen':freeze,'halt':client.halt,
               'requests':len(read_jsonl(out/'requests.jsonl')) if (out/'requests.jsonl').exists() else 0})
    return int(bool(client.halt))


if __name__=='__main__': raise SystemExit(main())
