"""Bounded experiments on handoff windows; retain the exact frozen S4/T1 projection."""
import argparse, csv, os, re
from types import SimpleNamespace
from common import *
from stage04_benchmark import BenchmarkRunner, URL, fingerprint
from stage04_candidates import project
from batch_sentence_alignment import load_han

def inputs():
    ss=lines(I/'han_segments_full.jsonl'); ctx=lines(I/'window_context_refined.jsonl'); raw=''.join(s['text_original'] for s in ss)
    vi={v['vi_id']:{**v,'t1_offsets':v['normalized_source_spans']} for c in ctx for v in c['viet_t1']};return ss,ctx,raw,vi

def run(out,phase):
    ss,ctx,raw,vi=inputs(); maprows=lines(I/'page_mapping_refined.jsonl');seeds=lines(D/'fresh_benchmark_seed.jsonl'); excluded=read(D/'benchmark_exclusions.json')['excluded_pages']
    token=re.sub(r'^bearer\s+','',os.environ['SINONOM_TOKEN'].strip(),flags=re.I)
    runner=BenchmarkRunner(SimpleNamespace(output=out,resume=True,retries=1,timeout=90,delay=.3,request_budget=None,persist_retry_after=True),token)
    for p in (ROOT/'04_dong_hang/artifacts').glob('stage04/**/requests.jsonl'):
        for e in lines(p):
            j=e.get('job',{});k=fingerprint([URL,j.get('payload')]);
            if e.get('status')=='success' and j.get('key')==k:runner.history[k]=(str(p.relative_to(ROOT)),e)
    from fresh import check
    fresh=phase=='benchmark';windows=check(out) if fresh else [dict(cap='Cap_01',window='continuation',han_pages=[2,3,4])];results=[]
    for w in windows:
        cap=w['cap'];pages=w['han_pages'];name=w['window'];cx=[c for c in ctx if c['cap']==cap and c['han_page'] in pages]; units=[s for s in ss if s['id_zh'].startswith(cap+'-') and s['page_start']<=max(pages) and s['page_end']>=min(pages)]
        ids=w.get('ordered_unique_vi_ids') or sorted({v['id'] for c in cx for v in c['viet']});ids=sorted(ids,key=lambda k:vi[k]['source']['row']); anchors=[v['id'] for c in cx if any(m['Cap']==cap and m['Han_Page']==c['han_page'] and m['Mapping_Status']=='VERIFIED' for m in maprows) for v in c['viet'] if v['id'] in ids];center=ids.index(anchors[len(anchors)//2]) if anchors else len(ids)//2
        if fresh:
            assert not set(pages)&set(excluded[cap]);assert [c['raw'] for c in cx]==[c['raw'] for c in w['page_contexts']]
        for size in dict.fromkeys(min(len(ids),x) for x in (10,5,15,len(ids))):
            a=max(0,min(len(ids)-size,center-size//2));vs=ids[a:a+size];payload={'han':'\n'.join(s['text_zh'] for s in units),'vi':'\n'.join(vi[k]['text_t1'] for k in vs)};key=fingerprint([URL,payload]);tag=f'{name}-{size}'
            j=dict(id=tag,key=key,repeat_of=None,strategy='S4+T1',cap=cap,pages=pages,h=[s['global_raw_span'] for s in units],han_offsets=[s['normalized_source_spans'] for s in units],han_ids_by_line=[[s['id_zh']] for s in units],v=vs,payload=payload,context_evidence=int(bool(anchors)))
            e=runner.run(j);r=dict(window=name,cap=cap,pages=pages,context=size,full=size==len(ids),ids=vs,han=j['h'],key=key,status=e['status'] if e else runner.halt,baseline=[])
            if e and e['status']=='success':r['baseline']=project(j,e,raw,vi)
            results.append(r);save(out/'checkpoints'/f'{tag}.json',r)
        if fresh:export(out,cap,pages,units)
    runner.close();save(out/(phase+'.json'),results);return results

def export(out,cap,pages,units):
    folder=out/'stage04'/cap/'V4';folder.mkdir(parents=True,exist_ok=True);p=folder/f'{min(pages):04}-{max(pages):04}-segments.csv'
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['id_zh','han_page_start','han_page_end','text_zh','global_raw_start','global_raw_end']);w.writerows([[s['id_zh'],s['page_start'],s['page_end'],s['text_zh'],*s['global_raw_span']] for s in units])
    got=load_han(folder,min(pages),max(pages));assert [(u.id,u.text) for u in got]==[(s['id_zh'],s['text_zh']) for s in units]

def output(run_id):
    if not re.fullmatch(r'[\w-]+',run_id):raise ValueError('Invalid run id')
    p=HERE.parent/'artifacts/v4_pipeline_release'/run_id;(p/'checkpoints').mkdir(parents=True,exist_ok=True);return p
