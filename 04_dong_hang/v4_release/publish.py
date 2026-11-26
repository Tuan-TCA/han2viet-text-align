from collections import Counter
from statistics import mean,median
from experiment import *
from engine import refine,signature,mapped,conflict
from audit import review

def distribution(values):
    v=sorted(x for x in values if isinstance(x,(int,float)));return dict(n=len(v),minimum=min(v),median=median(v),mean=mean(v),maximum=max(v)) if v else {'n':0}

def measures(r,groups,vi):
    hc=Counter();vc=Counter();ids=set();pairs=[g for g in groups if mapped(g)];order={k:i for i,k in enumerate(r['ids'])}
    for g in pairs:
        hc.update(range(g['Han_Start'],g['Han_End']))
        for k,a,b in g['VI_Char_Spans']:
            vc.update((k,i) for i in range(a,b));
            if a==0 and b==len(vi[k]['text_original']):ids.add(k)
    return dict(groups=len(groups),fully_mapped=sum(g['Validation_Status']=='mapped' for g in pairs),partial=sum(g['Validation_Status']=='partial_viet' for g in pairs),unresolved=len(groups)-len(pairs),han_covered=len(hc),han_total=sum(b-a for a,b in r['han']),vi_covered=len(vc),vi_total=sum(len(vi[k]['text_original']) for k in r['ids']),han_duplicate=sum(hc.values())-len(hc),vi_duplicate=sum(vc.values())-len(vc),full_ids=len(ids),total_ids=len(r['ids']),conflict_pairs=sum(conflict(g,h,order) for i,g in enumerate(pairs) for h in pairs[i+1:]),alignment_types=dict(Counter(g['Alignment_Type'] for g in groups)),scores=distribution([g.get('API_Score') for g in groups]))

def source_export(o,r,groups,ss,raw):
    # Produce reader units from unambiguous V4 spans; fill unassigned regions
    # with original S4 cuts. Never omit a character on a failed mapping.
    cap=r['cap'];pages=r['pages'];units=[s for s in ss if s['global_raw_span'] in r['han']];mapped_spans=sorted(set((g['Han_Start'],g['Han_End']) for g in groups if mapped(g)));bounds=set(p for span in r['han'] for p in span);lo,hi=min(bounds),max(bounds)
    for a,b in mapped_spans:
        if any((x,y)!=(a,b) and x<b and y>a for x,y in mapped_spans):continue
        bounds={p for p in bounds if not a<p<b}|{a,b}
    cuts=sorted(bounds);rows=[]
    for a,b in zip(cuts,cuts[1:]):
        overlaps=[s for s in units if s['global_raw_span'][0]<b and s['global_raw_span'][1]>a];src=[(x,s) for s in overlaps for x in s['source']];ps=[]
        for s in overlaps:
            pos=s['global_raw_span'][0]
            for x in s['source']:
                stop=pos+x['file_span'][1]-x['file_span'][0];
                if pos<b and stop>a:ps.append(x['page'])
                pos=stop
        rows.append(dict(id_zh=f'{cap}-V4-{a}-{b}',page_start=min(ps),page_end=max(ps),text_zh=raw[a:b],global_raw_span=[a,b]))
    assert ''.join(u['text_zh'] for u in rows)==raw[lo:hi];export(o,cap,pages,rows);return len(rows)

def publish(o):
    ss,ctx,raw,vi=inputs();bench=read(o/'benchmark.json');cont=read(o/'continuation.json');requests=lines(o/'requests.jsonl');cfg=read(HERE/'config.json');extra=[];comp=[];decisions=[];result=[];counts={};totals={};refs=[]
    for rs in (cont,bench):
        for r in rs:
            probes=[p for p in rs if p['window']==r['window']];v4,ledger=refine(r,probes,raw,vi,cfg);decisions.extend([dict(window=r['window'],context=r['context'],**l) for l in ledger]);result.append({**r,'v4':v4,'provenance':ledger});
            for method,gs in [('S4+T1',r['baseline']),('V4',v4)]:
                m=measures(r,gs,vi);comp.append(dict(window=r['window'],context=r['context'],full=r['full'],method=method,**m));extra.extend((method,r,g) for g in gs)
                if rs is bench and r['full']:
                    tot=totals.setdefault(method,Counter());tot.update({k:x for k,x in m.items() if isinstance(x,int)})
                if rs is cont and r['full']:
                    for g in read(D/'page3_4_candidate_extension.json')['groups']:
                        a,b=g['start'],g['end'];paired=[h for h in gs if mapped(h)];iou=lambda h:max(0,min(b,h['Han_End'])-max(a,h['Han_Start']))/(max(b,h['Han_End'])-min(a,h['Han_Start']));best=max(paired,key=iou,default=None);refs.append(dict(method=method,candidate=g['id'],best_iou=iou(best) if best else 0,exact_span=any((h['Han_Start'],h['Han_End'])==(a,b) for h in paired),full_id_at_best=bool(best and iou(best)>0 and best['VI_IDs']==g['vi_ids'] and best['Validation_Status']=='mapped')))
            if rs is bench and r['full']:counts[r['window']]=source_export(o,r,v4,ss,raw)
    from evidence import crosswalk
    crosswalk(o,result)
    review(o,extra);save(o/'results.json',result);live=[e for e in requests if not e['cached']]
    metrics=dict(primary='six full-context windows; paired full or partial mappings only',baseline=dict(totals['S4+T1']),v4=dict(totals['V4']),fresh_windows=len(counts),stage04_verified=counts,requests=len(live),cache_hits=len(requests)-len(live),failures=sum(e['status']!='success' for e in live),latency_ms=distribution([e['latency_ms'] for e in live]),fresh_applied=sum(l['disposition']=='applied' for r in result if r['full'] and r['window']!='continuation' for l in r['provenance']),correction_precision=None,false_correction_rate=None,human_adjudicated=0,semantic_accuracy='NOT MEASURED',fresh_reference_pairs=0,reference_comparison=refs,window_metrics=comp,release='retain S4+T1; V4 experimental')
    save(o/'metrics.json',metrics);book(o/'comparison.xlsx',{'Window metrics':comp,'Continuation reference':refs,'Correction ledger':decisions,'Stage04 reader':[dict(window=k,units=v) for k,v in counts.items()]});gold=read(o/'gold_status.json')
    summary=[f'# Stage04 release: {o.name}','',f"**Decision: {metrics['release']}.** Independent Gold: 0. Semantic accuracy: NOT MEASURED.",'','## Fresh primary comparison (full context)','', '|Metric|S4+T1|V4|','|---|---:|---:|']+[f"|{k}|{metrics['baseline'][k]}|{metrics['v4'][k]}|" for k in metrics['baseline']]+['',f"API: {len(live)} new requests, {metrics['cache_hits']} cache hits, {metrics['failures']} failures. {sum(counts.values())} CSV units verified in {len(counts)} windows. {gold['unique_blind_rows']} blind records. No fresh reference spans; fresh exact accuracy, IoU, correction precision and false-correction rate unavailable.",'','Full context is primary. Sensitivity rows share Han input and differ in recorded VI context. V4 uses corroboration across contexts. Partial coverage is not a complete translation. See comparison.xlsx for per-context scores, alignment types, and rejected alternatives.','', 'All package hashes and S4 source slices checked. The fee case crosses a Han page and a Vietnamese ID boundary. The four-copy register case has a plausible earlier start. Candidate agreement is descriptive, not Gold.','', '## Commands (repository root)', '```powershell',f'python -B 04_dong_hang/v4_release/cli.py all {o.name}',f'python -B 04_dong_hang/v4_release/cli.py consume {o.name} Cap_01 27 28','```','Same run ID resumes. See manifest.json for file inventory and freeze.json for decoder identity.']
    (o/'report.md').write_text('\n'.join(summary)+'\n',encoding='utf8');save(o/'manifest.json',dict(run_id=o.name,freeze=read(o/'freeze.json'),source_sha256=digest(PACK/'source_manifest.json'),files={str(p.relative_to(o)):digest(p) for p in sorted(o.rglob('*')) if p.is_file() and p.name!='manifest.json'},code_files={str(p.relative_to(ROOT)):digest(p) for p in sorted(HERE.glob('*')) if p.is_file()}))
