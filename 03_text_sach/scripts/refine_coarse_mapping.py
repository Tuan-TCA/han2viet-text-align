"""Stage 03B: evaluate page-context estimates without changing frozen S4/T1."""
import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
from statistics import mean, median
import time

from api_integration import ALIGN
from candidate_boundaries import entities, numbers
from evaluate_pipeline import workbook
from preprocess import ROOT, STAGE, content, fingerprint, load_sources, read_jsonl, write_json
from run_release import Reuse, dump_jsonl, nested, t1_rows

PROD = STAGE/'artifacts/production'
OUT = STAGE/'artifacts/coarse_mapping'
VERSION = 2


class CoarseClient(Reuse):
    def __init__(self,out,cfg,live):
        super().__init__(out,cfg,live)
        for f in (OUT/'pilot/cache').glob('*.json'):
            if f.parent!=self.cache: self.old.setdefault(f.stem,f)

    def call(self,url,payload):
        if url!=ALIGN: raise ValueError('Coarse mapping uses Alignment only')
        file=self.cache/(fingerprint([url,payload])+'.json')
        if file.exists():
            cached=json.loads(file.read_text(encoding='utf8'))
            if cached.get('endpoint')!=url or cached.get('payload')!=payload or cached.get('status')!='ok':
                raise ValueError('Cache provenance mismatch')
        return super().call(url,payload)


def anchors_for(rows, hidden=None):
    return {h: sorted({r['viet_pdf_page'] for r in rows for a in r['verified_overlap'] if a['han_pdf_page']==h})
            for h in {a['han_pdf_page'] for r in rows for a in r['verified_overlap']} if h!=hidden}


def interpolate(h, anchors, limits):
    knots=sorted(anchors)
    if not knots: return mean(limits)
    if h in anchors: return mean(anchors[h])
    if len(knots)==1: return mean(anchors[knots[0]])
    a,b=next(((a,b) for a,b in zip(knots,knots[1:]) if a<=h<=b),
             tuple(knots[:2] if h<knots[0] else knots[-2:]))
    y=mean(anchors[a])+(h-a)*(mean(anchors[b])-mean(anchors[a]))/(b-a)
    return max(limits[0],min(limits[1],y))


def span_for(segments, page):
    rows=[s for s in segments if s['page_start']<=page<=s['page_end']]
    origin=rows[0]['global_raw_span'][0]; raw=''.join(s['text_original'] for s in rows)
    spans=[[a-origin,b-origin] for a,b in (s['global_raw_span'] for s in rows)]
    if any(x[1]!=y[0] for x,y in zip(spans,spans[1:])) or spans[-1][1]!=len(raw): raise ValueError('S4 continuity')
    return rows,origin,raw,spans


def widths(r): return r[1]-r[0]+1 if r else None


def interval(values):
    values=list(values); return [min(values),max(values)] if values else None


def build_contexts(rows, segments, vi):
    """Direct input for the same robust Stage 04 adapter: raw, spans, viet."""
    out=[]
    for row in rows:
        cap,h=row['Cap'],row['Han_Page']; chosen=row['Selected_VI_IDs']; ss,origin,raw,spans=span_for(segments[cap],h)
        out.append(dict(cap=cap,han_page=h,mapping_status=row['Mapping_Status'],global_raw_start=origin,
                        han_ids=[s['id_zh'] for s in ss],han=ss,raw=raw,spans=spans,
                        viet=[vi[cap][k] for k in chosen],viet_t1=t1_rows({'viet':[vi[cap][k] for k in chosen]})))
    return out


def ranges(pool): return interval(n for v in pool for n in (v['viet_page_start'],v['viet_page_end']))


def take(pool, center, size):
    if not pool: return []
    return nested(pool,max(0,min(len(pool)-1,center)),size)


def page_window(pool, y, size=10, shift=0):
    near=min(range(len(pool)),key=lambda i:abs(mean((pool[i]['viet_page_start'],pool[i]['viet_page_end']))-y))
    lo,hi=near,near
    while lo and pool[lo-1]['viet_page_start']==pool[near]['viet_page_start']: lo-=1
    while hi+1<len(pool) and pool[hi+1]['viet_page_start']==pool[near]['viet_page_start']: hi+=1
    return take(pool,(lo+hi)//2+shift,size)


def collect(result, clip, origin, submitted, y, prior, raw):
    pool={v['id']:v for v in submitted}; index={k:i for i,k in enumerate(pool)}
    a,b=[p-origin for p in clip]; hset=set(); vid=set(); whole=set(); links=[]; active=0; overlaps=0; inversions=0; last=-1
    number_hits=entity_hits=duplicate_vi=0; scores=[]; unresolved=0; vi_positions=defaultdict(set)
    for g in result.get('groups',[]):
        x,z=g['Han_Start'],g['Han_End']; ids=[k for k in g['VI_IDs'] if k in pool]
        if g['Validation_Status'] not in ('mapped','partial_viet') or x is None or not ids:
            unresolved+=1; continue
        whole.update(ids)
        l,r=max(a,x),min(b,z)
        if l>=r: continue
        active+=1; span=set(range(l,r)); overlaps+=len(span&hset); hset.update(span)
        where=min(index[k] for k in ids); inversions+=where<last; last=max(last,where); vid.update(ids)
        for k,i,j in g.get('VI_Char_Spans',[]):
            if k in pool:
                chars=set(range(i,j)); duplicate_vi+=len(vi_positions[k]&chars); vi_positions[k].update(chars)
        hs=raw[l:r]; vs=g['Vietnamese_Text']; number_hits+=len(numbers(hs,True)&numbers(vs,False)); entity_hits+=len(entities(hs,True)&entities(vs,False))
        if isinstance(g['Score'],(float,int)) and math.isfinite(g['Score']): scores.append(max(0,min(1,g['Score'])))
        links.append([origin+l,origin+r,ids])
    ids=[k for k in pool if k in vid]; match_range=ranges([pool[k] for k in ids]); submitted_range=ranges(submitted)
    hc=len(hset)/(b-a); vc=len(whole)/len(pool); mean_score=mean(scores) if scores else 0
    if match_range:
        diff=abs(mean(match_range)-y)
        outside=prior and (match_range[1]<prior[0] or match_range[0]>prior[1])
        score=(2.4*hc+.32*vc+.08*min(active,5)+.19*min(number_hits,4)+.46*min(entity_hits,4)+.12*mean_score
               -.13*unresolved-.7*inversions-.8*overlaps/(b-a)-.05*min(duplicate_vi,20)-.12*diff-.28*bool(outside)-.09*max(0,widths(match_range)-3))
    else: score=-1.35
    return dict(range=match_range,submitted_range=submitted_range,ids=ids,submitted_ids=list(pool),han_coverage=hc,vi_coverage=vc,
                missing_han=b-a-len(hset),duplicate_han=overlaps,duplicate_vi=duplicate_vi,unresolved=unresolved,order_violations=inversions,mapped_groups=active,
                number_hits=number_hits,entity_hits=entity_hits,weak_api_score=mean_score,links=links,score=score,
                status=result['status'],request_key=result.get('request_key'))


def agreement(probes):
    for x in probes:
        xx=set(x['ids']); support=[]
        for y in probes:
            yy=set(y['ids'])
            if x is not y and xx and yy and x['request_key']!=y['request_key']:
                support.append(len(xx&yy)/len(xx|yy))
        x['agreement']=max(support,default=0.)
        x['adjusted']=x.get('anchor_adjusted',x['score'])+.38*x['agreement']


def transition(a,b):
    if not a or not b: return 0.
    if b[0]<a[0] or b[1]<a[1]: return -math.inf
    return -.22*max(0,b[0]-a[1]-1)-.16*max(0,a[1]-b[0])-.09*max(0,mean(b)-mean(a)-3)


def reconcile(options):
    # Keep the last placed interval as state across deferred pages; skipping a
    # page cannot reset monotonicity. Need only the best path per last interval.
    states={None:(0.,[])}
    for page in options:
        nxt={}
        for key,(score,path) in states.items():
            for x in page:
                r=x['range']; k=tuple(r) if r else key
                v=score+x['adjusted']+transition(key,r)
                if math.isfinite(v) and (k not in nxt or v>nxt[k][0]): nxt[k]=(v,path+[x])
        if not nxt: raise ValueError('No monotone path through anchors')
        states=nxt
    return max(states.values(),key=lambda x:x[0])[1]


def source_inputs():
    tracked=[PROD/n for n in ('han_segments.jsonl','window_context.jsonl','production_audit.json','production_manifest.json')]
    xlsx=PROD/'coarse_alignment_audit.xlsx'
    try: xlsx.read_bytes(); tracked.append(xlsx)
    except PermissionError: print('Audit workbook is locked; checking its machine-readable production audit and page context.',flush=True)
    import hashlib
    digest=lambda: {str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in tracked}
    before=digest(); pp,vv,mm=load_sources(); seg=defaultdict(list); support={}; vi=defaultdict(dict)
    if json.loads(tracked[3].read_text(encoding='utf8'))['release_status']!='complete': raise ValueError('Expected completed production')
    for s in read_jsonl(tracked[0]): seg[s['window'].rsplit('-',2)[0]].append(s)
    for w in read_jsonl(tracked[1]):
        if w['processing_status']!='successful': raise ValueError('Incomplete production')
        support.update({(w['cap'],int(k)):v for k,v in w['page_mapping_status'].items()})
    for v in vv: vi[v['cap']][v['id']]=v
    if dict(Counter(support.values()))!=json.loads(tracked[2].read_text(encoding='utf8'))['page_mapping']:
        raise ValueError('Stage 03 audit disagrees')
    if xlsx in tracked:
        from openpyxl import load_workbook
        x=load_workbook(xlsx,read_only=True,data_only=True)
        records=iter(x['Page_Audit'].values); fields=next(records)
        for vals in records:
            row=dict(zip(fields,vals))
            if support[row['cap'],row['page']]!=row['mapping_availability']: raise ValueError('Stage 03 audit disagrees')
        x.close()
    for cap,rows in seg.items():
        if ''.join(r['text_original'] for r in rows)!=''.join(p['text_original'] for p in pp if p['cap']==cap): raise ValueError('S4 reconstruction')
    return pp,mm,seg,support,vi,before,digest


class Evaluation:
    def __init__(self,out,client,cfg,seg,identity):
        self.out=out;self.client=client;self.cfg=cfg;self.seg=seg;self.identity=identity

    def probe(self,p,pool,y,prior,tag):
        ss,origin,raw,spans=span_for(self.seg[p['cap']],p['han_pdf_page']); key=fingerprint([tag,p['id'],[v['id'] for v in pool],self.identity])
        file=self.out/'checkpoints'/(key+'.json')
        if file.exists(): return json.loads(file.read_text(encoding='utf8'))
        result=self.client.align(tag+'-'+p['id'],raw,spans,pool)
        row=collect(result,p['global_raw_span'],origin,pool,y,prior,raw)
        row.update(cap=p['cap'],han_page=p['han_pdf_page'],purpose=tag,han_ids=[s['id_zh'] for s in ss]);
        if result['status'] not in ('offline','no_token','transient','transport_error') and not self.client.halt: write_json(file,row)
        return row

    def refine(self,p,pool,y,prior,anchor,tag):
        attempts=[]; seen=set()
        def check(yy,size,shift=0):
            v=page_window(pool,yy,size,shift); ids=tuple(x['id'] for x in v)
            if ids in seen or self.client.halt: return
            seen.add(ids); attempts.append(self.probe(p,v,y,prior,tag))
        check(y,10); check(y,10,5 if p['han_pdf_page']%2 else -5)
        def best():
            agreement(attempts); return max(attempts,key=lambda q:q['adjusted']) if attempts else None
        x=best()
        if not x or x['han_coverage']<.75 or x['agreement']<.34 or not x['range']:
            check(y,16,-4 if p['han_pdf_page']%2 else 4); x=best()
        if not x or x['han_coverage']<.45 or not x['range']:
            check(max(pool[0]['viet_page_start'],y-2),12); check(min(pool[-1]['viet_page_end'],y+2),12)
        elif x['order_violations'] or x['unresolved']>=3:
            check(mean(x['range']),7)
        for x in attempts:
            if anchor and x['range'] and not (x['range'][0]<=min(anchor) and x['range'][1]>=max(anchor)):
                x['anchor_adjusted']=x['score']-.85
        agreement(attempts);return attempts


def choices(probes,pool,y,anchor):
    if anchor:
        selected=[v['id'] for v in pool if v['viet_page_start']<=max(anchor) and v['viet_page_end']>=min(anchor)]
        return [{'range':interval(anchor),'ids':selected,'adjusted':1.8,'kind':'anchor'}]
    best={}
    for x in probes:
        if x['range'] and x['han_coverage']>=.18 and x['order_violations']<=1:
            k=tuple(x['range']); opt={**x,'kind':'api'}
            if k not in best or x['adjusted']>best[k]['adjusted']: best[k]=opt
    prior=page_window(pool,y,10); lo,hi=ranges(prior)
    k=(lo,hi)
    if k not in best: best[k]={'range':[lo,hi],'ids':[v['id'] for v in prior],'adjusted':-.45,'kind':'interpolation'}
    return [*best.values(),{'range':None,'ids':[],'adjusted':-.80,'kind':'defer'}]


def prior_for(h,rows):
    return interval(r['viet_pdf_page'] for r in rows if r['han_search_window'] and
                    r['han_search_window'][0]<=h<=r['han_search_window'][1])


def original_evidence(h,rows):
    return [{'page':r['viet_pdf_page'],'source':r['source'],'note':r['can_cu'],'qualifier':a.get('qualifier')}
            for r in rows for a in r['verified_overlap'] if a['han_pdf_page']==h]


def summarizes_probe(x):
    return {k:x.get(k) for k in ('kind','range','adjusted','status','han_coverage','vi_coverage','agreement','number_hits','entity_hits',
                                  'mapped_groups','unresolved','duplicate_han','order_violations','request_key')}


def selection(cap,details,solver,support):
    result=[]
    for (p,orig,y,base,probes,opts,evidence),z in zip(details,solver):
        n=p['han_pdf_page']; flags=support[cap,n]; anchor=[e['page'] for e in evidence]
        local=max(opts,key=lambda x:x['adjusted']); alternatives=sorted([o for o in opts if o is not z and o['range']],key=lambda x:x['adjusted'],reverse=True)
        alt=alternatives[0] if alternatives else None
        close=bool(z['range'] and alt and z['adjusted']-alt['adjusted']<.5 and any(abs(a-b)>=2 for a,b in zip(z['range'],alt['range'])))
        proxy=None if z['kind']!='api' else round(max(0.,min(1.,.5*z['han_coverage']+.35*z['agreement']+.08*min(z['entity_hits'],2)+.04*min(z['number_hits'],2)-.08*z['order_violations'])),3)
        if flags=='unmatched': status='UNMATCHED'
        elif flags=='partial': status='PARTIAL'
        elif anchor: status='VERIFIED'
        elif not z['range'] or close: status='AMBIGUOUS'
        elif proxy is not None and proxy>=.78 and z['agreement']>=.55 and z['han_coverage']>=.8 and not z['duplicate_han'] and not z['order_violations']: status='HIGH_CONFIDENCE_ESTIMATED'
        else: status='LOW_CONFIDENCE_ESTIMATED'
        lo,hi=z['range'] or (None,None); ids=z['ids']
        note={'UNMATCHED':'No supported processed Vietnamese context; translation absence not inferred.',
              'PARTIAL':'Verified evidence only for the supported part of the page; inspect cross-page spans.',
              'VERIFIED':'Independently established overlaps; listed range is an envelope of observed anchors, not verified completeness.',
              'AMBIGUOUS':'Competing or deferred estimate. Review alternatives before using as fixed context.',
              'LOW_CONFIDENCE_ESTIMATED':'Candidate context only; inspect original prior and source before official alignment.',
              'HIGH_CONFIDENCE_ESTIMATED':'Supported by overlapping probes; still an estimate.'}[status]
        result.append(dict(Cap=cap,Han_Page=n,Original_Verified_VI_Pages=sorted(set(anchor)),Original_Candidate_Range=orig,
                           Interpolated_VI_Page=y,Predicted_VI_Page_Start=lo,Predicted_VI_Page_End=hi,
                           Predicted_VI_ID_Start=ids[0] if ids else None,Predicted_VI_ID_End=ids[-1] if ids else None,
                           Han_Coverage=z.get('han_coverage'),VI_Coverage=z.get('vi_coverage'),Mapping_Status=status,
                           Confidence_Proxy=proxy,Evidence={'anchors':evidence,'chosen':summarizes_probe(z)},
                           Alternative_Candidates=[summarizes_probe(x) for x in alternatives],Review_Note=note,
                           Selected_VI_IDs=ids,B1_Range=ranges(base),Local_Range=local['range'],B2_Range=z['range'],
                           Probes=len(probes)))
    return result


def loo(ev,work,cap,rows,pool):
    all_anchors=anchors_for(rows); limits=ranges(pool); by_h={p['han_pdf_page']:p for p in work}; data=[]
    for target,truth in sorted(all_anchors.items()):
        train=anchors_for(rows,target)
        if target not in by_h or len(train)<2: continue
        y=interpolate(target,train,limits); base=page_window(pool,y,10)
        probes=ev.refine(by_h[target],pool,y,None,[],f'loo-{target}')
        options=[]
        for p in work:
            h=p['han_pdf_page']; yy=interpolate(h,train,limits)
            options.append(choices(probes if h==target else [],pool,yy,train.get(h)))
        z=reconcile(options)[next(i for i,p in enumerate(work) if p['han_pdf_page']==target)]
        r={'cap':cap,'hidden_han':target,'heldout_vi':truth,'training_han':sorted(train),'B0_range':prior_for(target,rows),
           'B1_range':ranges(base),'B2_range':z['range'],'B2_kind':z['kind'],'B2_local_range':max(choices(probes,pool,y,[]),key=lambda x:x['adjusted'])['range'],
           'B0_independent':False,'probes':probes}
        for k in ('B0','B1','B2'):
            q=r[k+'_range']; r[k+'_recovered']=sum(q[0]<=n<=q[1] for n in truth) if q else 0
            r[k+'_distance']=mean(max(q[0]-p,p-q[1],0) for p in truth) if q else None
        data.append(r)
    return data


def structural(rows,key):
    indexed=[(r['Han_Page'],r[key]) for r in rows if r[key]]; vals=[v for _,v in indexed]
    pairs=[(a,b) for (i,a),(j,b) in zip(indexed,indexed[1:]) if j==i+1]
    return {'ranges':len(vals),'mean_width':mean(map(widths,vals)) if vals else None,'median_width':median(map(widths,vals)) if vals else None,
            'backward':sum(b[0]<a[0] or b[1]<a[1] for a,b in pairs),'gap_pages':sum(max(0,b[0]-a[1]-1) for a,b in pairs),
            'overlap_beyond_shared_endpoint':sum(max(0,a[1]-b[0]) for a,b in pairs)}


def downstream(ev,work,rows,pool):
    chosen={r['Han_Page']:r for r in rows}; lookup={v['id']:v for v in pool}; out=[]
    for p in work:
        h=p['han_pdf_page']; r=chosen[h]
        if not r['B2_Range'] or not r['Original_Candidate_Range'] or r['Interpolated_VI_Page'] is None: continue
        # Independently formatted comparisons preserve all VI segments touching
        # each proposed range, exercising downstream input choice, not probe ranking.
        for k in ('B0','B1','B2'):
            q=r[{'B0':'Original_Candidate_Range','B1':'B1_Range','B2':'B2_Range'}[k]]
            if not q: continue
            vs=[v for v in pool if q[0]<=v['viet_page_end'] and v['viet_page_start']<=q[1]]
            if not vs: continue
            if k=='B0' and len(vs)>30: vs=page_window(vs,mean(q),30)
            if ev.client.halt: return out
            item=ev.probe(p,vs,r['Interpolated_VI_Page'],None,'downstream-'+k); item=dict(item,approach=k,requested_range=q,
                                                                                     vi_count=len(vs)); out.append(item)
    return out


def silver_check(checks,pages):
    """Compare endpoints only for references fully inside a tested Han page."""
    refs=read_jsonl(ROOT/'pipeline/artifacts/phase1/silver_benchmark.jsonl'); result=[]
    for p in pages:
        cap=p['cap']; h=p['han_pdf_page']; a,b=p['global_raw_span']
        if cap!='Cap_01': continue
        group=[x for x in checks if x['cap']==cap and x['han_page']==h]
        if len(group)!=3 or any(x['status']!='ok' for x in group): continue
        for row in refs:
            c=row['comparison']; cg=[c['CG_Start'],c['CG_End']]; ds=[c['DS_Start'],c['DS_End']]
            if min(cg[0],ds[0])<a or max(cg[1],ds[1])>b: continue
            for x in group:
                # Repeated exact spans within a response are deduplicated. A
                # multi-ID group or several disjoint links is not an exact pair.
                spans={tuple(z[:2]) for z in x['links'] if z[2]==[row['VI_ID']]}
                pred=list(next(iter(spans))) if len(spans)==1 else None
                def overlap(ref):
                    return max(0,min(ref[1],pred[1])-max(ref[0],pred[0]))/(max(ref[1],pred[1])-min(ref[0],pred[0])) if pred else 0.
                result.append(dict(han_page=h,pair=row['Pair_ID'],approach=x['approach'],vi_id=row['VI_ID'],predicted=pred,
                                   CG_exact=pred==cg,DS_exact=pred==ds,CG_iou=overlap(cg),DS_iou=overlap(ds),agreed=cg==ds))
    return result


def main():
    args=argparse.ArgumentParser(description=__doc__);args.add_argument('--pilot',action='store_true');args.add_argument('--resume',action='store_true');args.add_argument('--live',action='store_true'); args=args.parse_args()
    started=time.monotonic(); pp,mm,seg,support,vi,before,digest=source_inputs()
    cfg=json.loads((STAGE/'config/stage03_release.json').read_text(encoding='utf8'))
    out=OUT/'pilot' if args.pilot else OUT;out.mkdir(parents=True,exist_ok=args.resume or (not args.pilot and not (out/'manifest.json').exists()));(out/'checkpoints').mkdir(exist_ok=True)
    identity=fingerprint([{k:v for k,v in before.items() if not k.endswith('.xlsx')},mm,vi,VERSION,cfg]); manifest=out/'manifest.json'
    if manifest.exists() and json.loads(manifest.read_text(encoding='utf8'))['identity']!=identity: raise ValueError('Inputs changed')
    write_json(manifest,{'identity':identity,'version':VERSION,'production_sha256':before,'pilot':args.pilot})
    client=CoarseClient(out,cfg,args.live); ev=Evaluation(out,client,cfg,seg,identity); final=[]; all_probes=[]; validation=[]; checks=[]
    try:
        for cap,vi_map in vi.items():
            pool=list(vi_map.values()); maps=[m for m in mm if m['cap']==cap]; anchors=anchors_for(maps); limits=ranges(pool); options=[]; detail=[]
            pages=[p for p in pp if p['cap']==cap and (not args.pilot or p['han_pdf_page'] in ({1,2,3,25,26,27} if cap=='Cap_01' else {1,2,3,25,26,27,51}))]
            work=[p for p in pages if support[cap,p['han_pdf_page']]!='unmatched']
            for p in pages:
                h=p['han_pdf_page']; orig=prior_for(h,maps); evidence=original_evidence(h,maps)
                if support[cap,h]=='unmatched':
                    options.append([{'range':None,'ids':[],'adjusted':0.,'kind':'defer'}]);detail.append((p,orig,None,[],[],options[-1],evidence));continue
                y=interpolate(h,anchors,limits); base=page_window(pool,y); probes=ev.refine(p,pool,y,orig,anchors.get(h),'production'); all_probes.extend(probes)
                opts=choices(probes,pool,y,anchors.get(h));options.append(opts);detail.append((p,orig,y,base,probes,opts,evidence))
                print(f'{cap} {h:03d}: {len(probes)} probes; {len(opts)} options; {client.attempts} live so far',flush=True)
            chosen=selection(cap,detail,reconcile(options),support); final.extend(chosen)
            if not args.pilot and not client.halt: validation.extend(loo(ev,work,cap,maps,pool))
            # Preregistered small mapping-context comparison per Cap: endpoints,
            # first available unanchored page and interior anchor neighborhoods.
            if not client.halt:
                hn={w['han_pdf_page'] for w in work}
                sample={min(hn),min(hn)+1,sorted(hn)[len(hn)//3],sorted(hn)[2*len(hn)//3]}
                checks.extend(downstream(ev,[p for p in work if p['han_pdf_page'] in sample],chosen,pool))
        if not args.pilot and len(final)!=145: raise ValueError('Missing Han pages')
        if digest()!=before: raise ValueError('Frozen production changed')
        contexts=build_contexts(final,seg,vi); dump_jsonl(out/'page_mapping_refined.jsonl',final);dump_jsonl(out/'window_context_refined.jsonl',contexts)
        workbook(out/'page_mapping_refined.xlsx',{'Refined':final}); workbook(out/'mapping_candidates.xlsx',{'Production':all_probes,'LOO_Probes':[p for r in validation for p in r['probes']]})
        workbook(out/'uncertain_pages.xlsx',{'Review':[r for r in final if r['Mapping_Status'] not in ('VERIFIED','HIGH_CONFIDENCE_ESTIMATED')]})
        stats={}
        for cap in vi:
            sub=[r for r in final if r['Cap']==cap and r['Mapping_Status']!='UNMATCHED']; stats[cap]={k:structural(sub,f) for k,f in [('B0','Original_Candidate_Range'),('B1','B1_Range'),('B2','B2_Range'),('local','Local_Range')]}
        validflat=[{k:v for k,v in r.items() if k!='probes'} for r in validation]
        tab=[dict(cap=cap,approach=k,**v) for cap,x in stats.items() for k,v in x.items()]
        silver=silver_check(checks,pp)
        workbook(out/'mapping_comparison.xlsx',{'Structural':tab,'Hidden_Anchors':validflat,'Downstream':checks,'Silver_Proxy':silver})
        if not (out/'requests.jsonl').exists(): (out/'requests.jsonl').touch()
        log=read_jsonl(out/'requests.jsonl'); status=dict(Counter(r['Mapping_Status'] for r in final)); elapsed=time.monotonic()-started
        score={'statuses':status,'structural':stats,'validation':validflat,'downstream':checks,'silver_proxy':silver,'request_count':len(log),
               'requests_this_execution':client.attempts,'cache_hits_this_execution':client.hits,'wall_seconds_this_execution':round(elapsed,2),'halt':client.halt,
               'production_pages_attempted':len({(r['cap'],r['han_page']) for r in all_probes if r['request_key']}),
               'probe_statuses':dict(Counter(r['status'] for r in all_probes)),'local_global_differing_pages':sum(r['Local_Range']!=r['B2_Range'] for r in final)}
        write_json(out/'metrics.json',score); make_report(out,score,args.pilot)
    finally: client.close()
    return int(bool(client.halt))


def make_report(out,score,pilot):
    lines=['# Stage 03B — Coarse page mapping'+(' pilot' if pilot else ''),'',f"Page statuses: `{score['statuses']}`. Alignment attempts logged: **{score['request_count']}**. This execution: {score['wall_seconds_this_execution']} seconds, {score['cache_hits_this_execution']} exact-cache hits.",'',
           '| Cap | Method | Ranges | Mean width | Backward transitions | Gap pages | Excess overlap |','|---|---|---:|---:|---:|---:|---:|']
    for cap,stats in score['structural'].items():
        for k,v in stats.items():
            w=v['mean_width']; lines.append(f"| {cap} | {k} | {v['ranges']} | {w:.2f} | {v['backward']} | {v['gap_pages']} | {v['overlap_beyond_shared_endpoint']} |" if w else f"| {cap} | {k} | 0 | — | — | — | — |")
    val=score['validation']; lines+=['',f"Global choices differed from independent local choices on **{score['local_global_differing_pages']}** pages. Gap/overlap are geometric proxies over reported intervals, not independently adjudicated omissions.",'','## Hidden anchors','']
    if val:
        n=sum(len(v['heldout_vi']) for v in val)
        for k in ('B0','B1','B2'):
            v=[r[k+'_distance'] for r in val if r[k+'_distance'] is not None];lines.append(f"- {k}: {sum(r[k+'_recovered'] for r in val)}/{n} anchor overlaps recovered, mean distance {mean(v):.2f} VI pages over {len(v)}/{len(val)} folds." if v else f'- {k}: unavailable.')
        lines.append('B0 is descriptive because workbook windows were constructed with source anchors. B1 and B2 do not consume workbook priors in held-out folds; B2 probes the hidden page, with nonhidden anchors and interpolation-only neighbors. Any quality claim on this small sample is provisional.')
    else: lines.append('No held-out anchor evaluation in this execution.')
    lines+=['','## Downstream context comparison','']
    q=score['downstream']; ok={(r['cap'],r['han_page']) for r in q if sum(x['cap']==r['cap'] and x['han_page']==r['han_page'] and x['status']=='ok' for x in q)==3}
    for k in ('B0','B1','B2'):
        a=[x for x in q if x['approach']==k and (x['cap'],x['han_page']) in ok]
        if a: lines.append(f"- {k}: {len(a)} matched successful pages; mean Han/VI coverage {mean(r['han_coverage'] for r in a):.3f}/{mean(r['vi_coverage'] for r in a):.3f}; unresolved rows {sum(r['unresolved'] for r in a)}.")
    lines+=['','B0 downstream probes use at most 30 original VI segments centered in the original candidate range; B1/B2 use all eligible segments touching the proposed range. The comparison measures operational mapping, not semantic truth. Same-payload responses may be reused.']
    for k in ('B0','B1','B2'):
        a=[x for x in score['silver_proxy'] if x['approach']==k]
        if a: lines.append(f"- Silver endpoint proxy {k}: {len(a)} single-page pairs; exact CG {sum(r['CG_exact'] for r in a)}/{len(a)}, DS {sum(r['DS_exact'] for r in a)}/{len(a)}; mean IoU {mean(r['CG_iou'] for r in a):.3f}/{mean(r['DS_iou'] for r in a):.3f}.")
    lines+=['','The Silver proxy excludes references spanning two Han pages and uses focal-page-clipped output. It is a small structural comparison, not independently verified translation quality.',
            '', '## Handoff and limitations','',
            'Use `window_context_refined.jsonl` by page, then pass `raw`, `spans`, and `viet` to the existing Stage 04 adapter. `han` and `viet_t1` preserve original IDs, pages, raw spans and T1 projections. Adjacent page rows can share whole cross-page S4 segments; reconcile overlap by ID. Retain candidate ranges or request human review for ambiguous pages rather than treating estimates as fixed anchors.',
            'Cap_02 page 051 is partial. Pages 052–092 remain unmatched for processed Vietnamese context. No translation absence or semantic label is inferred. No official alignment was started.',
            f"Service halt: `{score['halt']}`. Probe statuses: `{score['probe_statuses']}`."]
    (out/'coarse_mapping_report.md').write_text('\n'.join(lines)+'\n',encoding='utf8')


if __name__=='__main__': raise SystemExit(main())
