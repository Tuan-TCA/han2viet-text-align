"""Phase A only: deterministic experiments, exact-payload reuse and resume."""
import argparse
from collections import Counter
import json
import os
import re
import time

from stage04_inputs import ROOT, CAP, PAGES, load, han_unit, hashes, read_jsonl
from preprocess import write_json
from benchmark_alignment_api import Runner, URL, fingerprint
from stage04_candidates import alternatives, identity, project, reconcile
from stage04_export import measures, publish, coverage, points

OUT = ROOT / '04_dong_hang/artifacts/stage04'
SIZES = (5,10,15,20,30)


def make_job(f, stage, name, units, ids, evidence=0):
    if not units or not ids or len(set(ids)) != len(ids):
        raise ValueError('Invalid or duplicate API units')
    vi = f['vi']; raw = f['raw']
    payload = dict(han='\n'.join(u['text'] for u in units), vi='\n'.join(vi[k]['text_t1'] for k in ids))
    source = {s['id_zh']:s for u in units for s in u['sources']}
    pages = sorted({p for s in source.values() for p in range(s['page_start'],s['page_end']+1)})
    if not set(pages) <= set(PAGES) or any(not k.startswith(CAP+'-') for k in [*source,*ids]):
        raise ValueError('Outside authorized benchmark context')
    return dict(stage=stage,id=f'{stage}-{name}',strategy='S4+T1',cap=CAP,pages=pages,
                h=[u['span'] for u in units],v=list(ids),han_ids=list(source), han_ids_by_line=[u['ids'] for u in units],
                han_offsets=[u['offsets'] for u in units],payload=payload, normalized_payload=payload,
                original_payload=dict(han='\n'.join(raw[a:b] for a,b in (u['span'] for u in units)),
                                      vi='\n'.join(vi[k]['text_original'] for k in ids)),
                context_evidence=evidence,key=fingerprint([URL,payload]),repeat_of=None)


def window(pool, center, size):
    start = max(0,min(len(pool)-size,center-size//2))
    return pool[start:start+size]


def prior(f, units, method):
    pool = f['pool']; vi = f['vi']
    a,b = units[0]['span'][0],units[-1]['span'][1]; center = (a+b)/2
    page = next(p for p in f['pages'] if p['cap']==CAP and p['global_raw_span'][0] <= center <= p['global_raw_span'][1])
    page_no = page['han_pdf_page']
    coarse = next(r for r in f['refined'] if r['Cap']==CAP and r['Han_Page']==page_no)
    lo,hi = coarse[{'original':'Original_Candidate_Range','B1':'B1_Range','B2':'B2_Range'}[method]]
    ix = [i for i,k in enumerate(pool) if vi[k]['viet_page_start'] <= hi and vi[k]['viet_page_end'] >= lo]
    pa,pb = page['global_raw_span']; t = (center-pa)/(pb-pa)
    return ix[round((len(ix)-1)*t)]


class BenchmarkRunner(Runner):
    def __init__(self,args,token):
        super().__init__(args,token)
        # Legacy logs contain a full normalized payload and the endpoint-bound key.
        self.history = {}
        for tag in ('alignment_benchmark','alignment_benchmark_final'):
            for e in read_jsonl(ROOT / 'pipeline/artifacts' / tag / 'requests.jsonl'):
                j = e['job']; key = fingerprint([URL,j['payload']])
                if j['key']==key and e['status']=='success':
                    self.history.setdefault(key, (tag,e))

    def run(self,j):
        if not j['repeat_of'] and not any(e['job']['id']==j['id'] and e['job']['key']==j['key'] for e in self.entries):
            prior = next((e for e in reversed(self.entries) if e['job']['key']==j['key'] and
                          e['status'] in ('api_error','parse_error')),None)
            if prior is not None:
                entry = {**prior,'job':j,'cached':True,'reused_terminal_failure':True}
                self.record(entry)
                return entry
        old = self.history.get(j['key'])
        if old and not j['repeat_of'] and not any(e['job']['id']==j['id'] and e['job']['key']==j['key'] for e in self.entries):
            tag, e = old
            body = json.loads(e['raw_response']); data = body.get('data')
            if body.get('is_success') is True and isinstance(data,dict) and isinstance(data.get('result'),list):
                entry = {**e,'endpoint':URL,'id':f'{tag}/{e["id"]}','job':j,'cached':True}
                self.record(entry)
                return entry
        return super().run(j)


def preserves_global_evidence(before, after, a, b):
    """A local repair may not consume accepted evidence elsewhere in the path."""
    def footprint(groups):
        return (points([(g['Han_Start'],g['Han_End']) for g in groups]),
                {(k,n) for g in groups for k,x,y in g['VI_Char_Spans'] for n in range(x,y)})
    outside = {identity(g) for g in before if not (a <= g['Han_Start'] < g['Han_End'] <= b)}
    before_h,before_v = footprint(before); after_h,after_v = footprint(after)
    return (outside <= {identity(g) for g in after} and before_h < after_h and before_v <= after_v)


def experiment(f, runner, out):
    pool = f['pool']; raw = f['raw']; vi = f['vi']; order = {k:i for i,k in enumerate(pool)}
    hs = [han_unit(s) for s in f['han']]
    focal = next(c for c in f['contexts'] if c['window']=='Cap_01-001-002')
    original = [r['vi_id'] for r in focal['viet']]; stages = {}; jobs = {}; repairs = []; adaptive_log = []
    cp = out/'checkpoints'; cp.mkdir(exist_ok=True)

    def request(stage,name,units,ids,evidence=0):
        j = make_job(f,stage,name,units,ids,evidence)
        stages.setdefault(stage,[]); jobs.setdefault(stage,[])
        path = cp/(fingerprint([j['id'],j['key']])+'.json')
        if path.is_file():
            saved = json.loads(path.read_text(encoding='utf-8'))
        else:
            entry = runner.run(j)
            if entry is None:
                return []
            saved = dict(status=entry['status'],response=entry['id'],candidate_rows=project(j,entry,raw,vi),
                         job_id=j['id'],key=j['key'],v=j['v'],h=j['h'])
            if entry['status'] not in ('auth_or_rate_limit','transport_error','transient_http'):
                write_json(path,saved)
        jobs[stage].append({k:v for k,v in saved.items() if k!='candidate_rows'})
        stages[stage].extend(saved['candidate_rows'])
        return saved['candidate_rows']

    request('S4-T1','frozen-original',hs,original,1)
    # Same Han blocks for all prior/window treatments, with two Han units of overlap.
    blocks = [(start,hs[start:start+10]) for start in range(0,len(hs)-2,8)]
    for start,block in blocks:
        centers = {m:prior(f,block,m) for m in ('original','B1','B2')}
        for method in ('original','B1','B2'):
            request(f'{method}-10',f'{start}',block,window(pool,centers[method],10),int(method=='B2'))
        for size in SIZES:
            if size != 10:
                request(f'B2-{size}',f'{start}',block,window(pool,centers['B2'],size),1)
    # Expose matched input shapes using monotone relative positions within the original window.
    for n in (1,2,4):
        for index in range(0,len(original),n):
            lo = round((index+(n-1)/2)/(len(original)-1)*(len(hs)-1)) - n//2
            lo = max(0,min(len(hs)-n,lo))
            request(f'shape-{n}x{n}',f'{index}',hs[lo:lo+n],original[index:index+n])

    # Keep fixed-size sweeps independent. Adaptive starts from B2-10 and reacts to gaps,
    # unstable source boundaries or a context edge, testing neighboring placements.
    stages['adaptive'] = list(stages['B2-10']); jobs['adaptive'] = list(jobs['B2-10'])
    for start,block in blocks:
        center = prior(f,block,'B2'); a,b = block[0]['span'][0],block[-1]['span'][1]
        local = [g for g in stages['B2-10'] if g['Experiment_ID']==f'B2-10-{start}']
        baseline_ids = window(pool,center,10)

        def weak(groups,ids):
            valid = [g for g in groups if g['Validation_Status']=='mapped']
            ratio = coverage([(g['Han_Start'],g['Han_End']) for g in valid],[(a,b)])
            return (ratio < .90 or any(g['Validation_Status'] not in ('mapped','partial_viet') for g in groups)
                    or any(set(g['VI_IDs']) & {ids[0],ids[-1]} for g in valid)
                    or any(g['Han_Partial_Unit'] for g in valid))

        seen = {tuple(baseline_ids)}
        if weak(local,baseline_ids):
            # Direct shifts, then larger windows around independently available priors.
            nearby = [(center-3,10),(center+3,10),(center,15),(center,20),(center,30),
                      (prior(f,block,'B1'),15),(prior(f,block,'original'),20)]
            for k,(position,size) in enumerate(nearby):
                ids = window(pool,position,size)
                if tuple(ids) in seen:
                    continue
                seen.add(tuple(ids)); found = request('adaptive',f'{start}-{k}',block,ids,1 if position==center else 0)
                adaptive_log.append(dict(block=start,window_size=size,offset=position-center,weak=weak(found,ids)))
                if not weak(found,ids):
                    break

    baseline = reconcile(stages['adaptive'],order)
    stages['refinement'] = list(stages['adaptive']); jobs['refinement'] = list(jobs['adaptive'])
    for start,block in blocks:
        a,b = block[0]['span'][0], block[-1]['span'][1]
        local = [g for g in baseline['selected'] if a <= g['Han_Start'] < g['Han_End'] <= b]
        near = [g for g in stages['adaptive'] if g['Han_Start'] is not None
                and a <= g['Han_Start'] < g['Han_End'] <= b and g['Han_Partial_Unit']]
        repairs_for_block = alternatives(f['han'][start:start+len(block)], local+near,raw)
        center = prior(f,block,'B2'); ids = window(pool,center,10)
        tried = set()
        def evidence(groups):
            valid = [g for g in groups if g['Validation_Status']=='mapped']
            return (coverage([(g['Han_Start'],g['Han_End']) for g in valid],[(a,b)]),
                    sum(coverage([(x,y) for g in valid for key,x,y in g['VI_Char_Spans'] if key==k],
                                 [(0,len(vi[k]['text_original']))]) for k in ids)/len(ids))
        # One targeted hypothesis of each boundary mechanism per weak block.
        for kind, units in repairs_for_block:
            if kind in tried:
                continue
            tried.add(kind)
            before_count = len(stages['refinement'])
            before_global = reconcile(stages['refinement'],order)['selected']
            found = request('refinement',f'{start}-{kind}',units,ids,1)
            redo = reconcile(found,order); new = redo['selected']
            old_ev,new_ev = evidence(local),evidence(new)
            # Compare the same block and require coverage gains with no VI target loss.
            old_ids = {k for g in local if g['Validation_Status']=='mapped' for k in g['VI_IDs']}
            new_ids = {k for g in new if g['Validation_Status']=='mapped' for k in g['VI_IDs']}
            supported = any(any(g['Han_Start']==x['Han_Start'] and g['Han_End']==x['Han_End']
                                 and g['VI_Char_Spans']==x['VI_Char_Spans'] for x in stages['adaptive']) for g in new)
            local_improvement = bool(old_ids <= new_ids and new_ev[0] > old_ev[0] and new_ev[1] >= old_ev[1]
                                     and supported and not redo['conflict_edges'])
            after_global = reconcile(stages['refinement'],order)['selected'] if local_improvement else []
            accepted = local_improvement and preserves_global_evidence(before_global,after_global,a,b)
            if not accepted:
                del stages['refinement'][before_count:]
            repairs.append(dict(Block=start,Operation=kind,Accepted=accepted,Before=old_ev,After=new_ev,
                                Corroborated=supported, Local_Improvement=local_improvement,
                                Decision='accepted' if accepted else ('global_evidence_regressed' if local_improvement else 'local_evidence_insufficient'),
                                Old_VI_IDs=sorted(old_ids),New_VI_IDs=sorted(new_ids),
                                Han_Spans=[u['span'] for u in units],Candidates=found))
            if len(tried)==3:
                break

    resolved = {k:reconcile(v,order) for k,v in stages.items()}
    return dict(resolved=resolved,jobs=jobs,raw_groups=stages,repairs=repairs,adaptive_log=adaptive_log,
                metrics={k:measures(v,f,jobs[k]) for k,v in resolved.items()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume',action='store_true')
    args = parser.parse_args(); f = load(); start = time.monotonic()
    token = re.sub(r'^bearer\s+','',os.getenv('SINONOM_TOKEN','').strip(),flags=re.I)
    if not token:
        parser.error('Set SINONOM_TOKEN for Phase A')
    args.output,args.delay,args.timeout,args.retries,args.request_budget,args.persist_retry_after = OUT,.8,90,2,None,True
    # .gitignore is checked in ahead of the run; no other existing run may be overwritten.
    manifest_path = OUT/'production_manifest.json'
    binding = {'phase':'A','method':'S4+T1','endpoint':URL,'cap':CAP,'han_pages':PAGES,
               'sources':f['before'],'silver_source':f['silver_source']}
    if (manifest_path.exists() or (OUT/'requests.jsonl').exists()) and not args.resume:
        parser.error('Existing benchmark run: use --resume')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}
    if manifest and fingerprint(manifest['binding']) != fingerprint(binding):
        parser.error('Source snapshot differs from the checkpoint')
    if not manifest_path.exists():
        write_json(manifest_path,{'binding':binding,'status':'running'})
    args.resume = True
    runner = BenchmarkRunner(args,token)
    try:
        result = experiment(f,runner,OUT)
        elapsed = time.monotonic()-start
        elapsed += manifest.get('execution',{}).get('wall_seconds',0)
        live = [e for e in runner.entries if not e['cached']]
        repeated = len(live)-len({e['job']['key'] for e in live})
        result['execution'] = dict(status='halted' if runner.halt else 'complete',halt=runner.halt,
                                   live_requests=len(live),repeated_live_payload_attempts=repeated,
                                   cache_hits=sum(e['cached'] and e['status']=='success' for e in runner.entries),
                                   reused_terminal_failures=sum(e.get('reused_terminal_failure',False) for e in runner.entries),
                                   api_failure_rate=sum(e['status']!='success' for e in live)/len(live) if live else None,
                                   api_latency_seconds=sum(e.get('latency_ms',0) for e in live)/1000,
                                   wall_seconds=elapsed,live_statuses=dict(Counter(e['status'] for e in live)))
        unchanged = hashes(f['tracked']) == f['before']
        if not unchanged:
            raise RuntimeError('Frozen source hash changed during benchmark')
        publish(OUT,f,result)
        write_json(manifest_path,{'binding':binding,'status':result['execution']['status'],
                                  'workbooks_validated':True,'source_hashes_unchanged':unchanged,
                                  'execution':result['execution']})
    finally:
        runner.close()


if __name__ == '__main__':
    main()
