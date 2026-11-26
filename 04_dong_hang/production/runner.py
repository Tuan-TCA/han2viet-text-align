import os,re,time
from types import SimpleNamespace
from inputs import *
from benchmark_alignment_api import Runner,URL
from stage04_candidates import project

def job(d,w,hs,vs,tag):
    units=[d['byid'][k] for k in hs];payload={'han':'\n'.join(s['text_zh'] for s in units),'vi':'\n'.join(d['vi'][k]['text_t1'] for k in vs)}
    return dict(id=w['id']+'-'+tag,strategy='S4+T1',cap=w['cap'],pages=w['pages'],key=fingerprint([URL,payload]),h=[s['global_raw_span'] for s in units],han_offsets=[s['normalized_source_spans'] for s in units],han_ids_by_line=[[k] for k in hs],v=vs,payload=payload,repeat_of=None,context_evidence=int('VERIFIED' in w['page_status']))

class Client:
    def __init__(self,out,cfg,live):
        self.live=live;self.cache=out/cfg['cache_dir'];self.cache.mkdir(exist_ok=True);self.history={};token=re.sub(r'^bearer\s+','',os.getenv('SINONOM_TOKEN','').strip(),flags=re.I) if live else 'offline';require(token,'missing SINONOM_TOKEN');self.base=Runner(SimpleNamespace(output=out,resume=True,request_budget=None,persist_retry_after=True,**cfg['api']),token);self.base.log.touch(exist_ok=True)
        for path in [*(ROOT/p for p in cfg['seed_logs']),self.base.log]:
            if not path.exists():continue
            for e in lines(path):
                j=e.get('job',{});p=j.get('payload');k=j.get('key');
                if e.get('status')=='success' and e.get('endpoint',URL)==URL and fingerprint([URL,p])==k:self.history[k]=e
    def call(self,j):
        key=j['key'];p=self.cache/(key+'.json');old=read(p) if p.exists() else self.history.get(key)
        if old:
            require(old['job']['payload']==j['payload'] and old['job']['key']==key and old.get('endpoint',URL)==URL and old['status']=='success','cache identity mismatch');e={**old,'origin_job':old['job']['id'],'cached':True,'job':j,'endpoint':URL};self.base.record(e)
        elif self.live:
            e=self.base.run(j)
            if not e:return dict(status=self.base.halt or 'interrupted',job=j)
        else:
            e=dict(job=j,status='offline_cache_miss',cached=False,network=False,endpoint=URL);self.base.record(e)
        if e['status']=='success':
            self.history[key]=e
            if not p.exists():save(p,e)
        return e

def execute(out,cfg,d,windows,live):
    client=Client(out,cfg,live);cp=out/cfg['checkpoint_dir'];cp.mkdir(exist_ok=True);done=0
    try:
        for w in windows:
            path=cp/(w['id']+'.json');
            if path.exists() and read(path)['complete']:done+=1;continue
            attempts=[];hs=w['han_ids'];vs=w['vi_ids']
            def attempt(h,v,tag):
                j=job(d,w,h,v,tag);e=client.call(j);gs=[];status=e['status'];error=None
                if status=='success':
                    try:gs=project(j,e,d['raw'],d['vi'])
                    except (TypeError,IndexError,ValueError,KeyError) as exc:error=f'{type(exc).__name__}: {exc}'
                attempts.append(dict(job=j['id'],key=j['key'],status=status,mapping_error=error,groups=gs));return gs
            if hs and vs:
                gs=attempt(hs,vs,'full');used={k for g in gs if g['Validation_Status']=='mapped' for k in g['Han_IDs']};need=[k for k in hs if k not in used];expanded=w['expanded_ids'];status=attempts[0]['status']
                if need and not client.base.halt and status not in ('offline_cache_miss','auth_or_rate_limit'):
                    # Retry contiguous runs separately; never concatenate disjoint holes.
                    from itertools import groupby
                    for n,(_,grp) in enumerate(groupby(enumerate(hs),lambda item:item[1] in used)):
                        gap=[k for _,k in grp if k not in used]
                        if gap and (gap!=hs or expanded!=vs):attempt(gap,expanded,f'recover-{n}')
                        if client.base.halt:break
            transient=any(a['status'] in ('auth_or_rate_limit','transport_error','transient_http','server_retry_after','server_quota_exhausted') for a in attempts);complete=not transient and not client.base.halt
            save(path,dict(window=w['id'],complete=complete,status='unsupported' if not attempts else attempts[0]['status'],attempts=attempts));done+=int(complete);save(out/'progress.json',dict(completed=done,total=len(windows),last_window=w['id'],halt=client.base.halt))
            if client.base.halt:break
    finally:client.base.close()
