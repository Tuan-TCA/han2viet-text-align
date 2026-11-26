"""Official whole-corpus S4 + T1 preparation. The manifest is the publish marker."""
from collections import Counter
import json
from pathlib import Path
import sys

from api_integration import SEPARATE
from coarse_alignment import window
from evaluate_pipeline import workbook
from preprocess import ROOT, STAGE, fingerprint, load_sources, normalize, read_jsonl, write_json
from release_audit import audit
from release_segmentation import partition
from run_release import Reuse, exports, publish_inputs, t1_rows


def read(path): return json.loads(path.read_text(encoding='utf8'))


class SeparateOnly(Reuse):
    def call(self,url,payload):
        if url!=SEPARATE: raise ValueError('Production permits Separate only')
        key=fingerprint([url,payload]); file=self.cache/(key+'.json')
        if file.exists():
            obj=read(file)
            if obj.get('endpoint')!=url or obj.get('payload')!=payload or obj.get('status')!='ok':
                raise ValueError('Production cache does not match exact request')
        if key in self.seeds:
            pilot=read(ROOT/'pipeline/artifacts/separate_pilot_cap01/results.json')
            if pilot.get('endpoint')!=url: self.seeds.pop(key)
        return super().call(url,payload)


def binding(w,cfg):
    payload={'text':w['raw'],'genre':cfg['genre'],'ocr_id':1,'punctuation_group':'all'}
    return {'window_sha256':fingerprint(w),'configuration_sha256':fingerprint(cfg),'endpoint':SEPARATE,
            'payload_key':fingerprint([SEPARATE,payload]),'method':'S4','viet_strategy':'T1'}


def process(w,client,expected,path):
    if path.exists():
        cp=read(path)
        if cp['binding']!=expected or cp['checksum']!=fingerprint(cp['data']): raise ValueError(f'Invalid checkpoint: {path}')
        if cp['data']['status']=='successful': return cp['data']
    key,projected,status=client.separate(w['raw'])
    if key!=expected['payload_key']: raise ValueError('Separate payload changed')
    data={'window':w['id'],'status':'failed','separate_status':status,'segments':[],
          'source_pages':w['pages'],'cache_key':key}
    if status=='ok':
        try:
            spans,_=partition(w['raw'],projected,'S4'); rows=exports(w,spans,'S4')
            if ''.join(r['text_original'] for r in rows)!=w['raw']: raise ValueError('reconstruction mismatch')
            data.update(status='successful',segments=rows)
        except (TypeError,KeyError,IndexError,ValueError) as exc:
            data['separate_status']='projection_error:'+type(exc).__name__
    write_json(path,{'binding':expected,'data':data,'checksum':fingerprint(data)})
    return data


def run_inventory(out,windows,client,cfg,manifest,contexts):
    folder=out/'checkpoints';folder.mkdir(exist_ok=True)
    manifest_file=out/'production_manifest.json'; data=[]
    saved={}
    for j,w in enumerate(windows):
        path=folder/(w['id']+'.json')
        if path.exists():
            cp=read(path); d=cp['data']
            if cp['binding']!=binding(w,cfg) or cp['checksum']!=fingerprint(d): raise ValueError('Invalid saved state')
            saved[w['id']]=d
            manifest['windows'][j].update(status=d['status'],separate_status=d['separate_status']); contexts[j]['processing_status']=d['status']
    write_json(manifest_file,manifest)
    for i,(w,entry) in enumerate(zip(windows,manifest['windows'])):
        if client.halt:
            data.extend(saved.get(w['id'],{}).get('segments',[])); continue
        cp=process(w,client,binding(w,cfg),folder/(w['id']+'.json'))
        entry.update(status=cp['status'],separate_status=cp['separate_status']); contexts[i]['processing_status']=cp['status']
        write_json(manifest_file,manifest); data.extend(cp['segments'])
        print(f"{i+1}/{len(windows)} {w['id']}: {cp['status']} ({cp['separate_status']}, {len(cp['segments'])} segments)",flush=True)
    return data


def verify(out,pp,windows,contexts):
    rows=read_jsonl(out/'han_segments.jsonl'); saved=read_jsonl(out/'window_context.jsonl')
    if len(saved)!=len(contexts): raise ValueError('Missing contexts')
    for w,c in zip(windows,saved):
        if c['window']!=w['id'] or c['viet']!=t1_rows(w) or any(not v['text_t1'] or '\n' in v['text_t1'] for v in c['viet']):
            raise ValueError('Invalid VI ID order, T1 text or original offset mapping')
    sys.path.insert(0,str(ROOT/'04_dong_hang/temp')); from batch_sentence_alignment import load_han
    result={}; ids=set(); sources={}; caprows={}
    for r in rows:
        cap=r['window'].rsplit('-',2)[0];caprows.setdefault(cap,[]).append(r)
        if r['id_zh'] in ids: raise ValueError('Duplicate segment ID')
        ids.add(r['id_zh']); pieces=[]
        for s in r['source']:
            path=s['file']; a,b=s['file_span']
            if path not in sources: sources[path]=(ROOT/path).read_bytes().decode('utf-8-sig')
            pieces.append(sources[path][a:b])
        text=''.join(pieces); norm,ix=normalize(text); lo,hi=r['global_raw_span']
        if text!=r['text_original'] or hi-lo!=len(text) or norm!=r['text_zh'] or [[lo+a,lo+b] for a,b in ix]!=r['normalized_source_spans']:
            raise ValueError('Source projection mismatch: '+r['id_zh'])
    for cap in sorted({p['cap'] for p in pp}):
        pages=[p for p in pp if p['cap']==cap]; rr=caprows.get(cap,[]); original=''.join(p['text_original'] for p in pages)
        origin=pages[0]['global_raw_span'][0]; counts=[0]*len(original); last=origin
        for r in rr:
            a,b=r['global_raw_span']
            if a<last or not origin<=a<b<=origin+len(original) or original[a-origin:b-origin]!=r['text_original']: raise ValueError('Invalid ordered offsets')
            last=b
            for i in range(a-origin,b-origin): counts[i]+=1
        missing=counts.count(0); dup=sum(max(0,n-1) for n in counts)
        # Validate each contiguous successful page range through the real reader.
        nums=sorted({n for r in rr for n in range(r['page_start'],r['page_end']+1)}); loaded=[]
        while nums:
            first=last=nums.pop(0)
            while nums and nums[0]==last+1: last=nums.pop(0)
            loaded.extend(load_han(out/'stage04'/cap/'S4',first,last))
        if [(u.id,u.text,u.first,u.last) for u in loaded]!=[(r['id_zh'],r['text_zh'],r['page_start'],r['page_end']) for r in rr]: raise ValueError('Stage 04 CSV mismatch')
        result[cap]=dict(total_pages=len(pages),segments=len(rr),source_chars=len(original),missing_chars=missing,duplicated_chars=dup,
                         exact_reconstruction=''.join(r['text_original'] for r in rr)==original,cross_page_segments=sum(r['page_start']!=r['page_end'] for r in rr))
    return result


def produce(live,resume):
    out=STAGE/'artifacts/production';out.mkdir(parents=True,exist_ok=resume)
    cfg=read(STAGE/'config/stage03_release.json'); pp,vv,mm=load_sources(); auditrows=audit(pp,vv,mm)
    for row in auditrows:
        row['mapping_availability']=('partial' if (row['cap'],row['page'])==('Cap_02',51) else 'supported' if row['page_has_window'] else 'unmatched')
    windows=[]; contexts=[]; entries=[]
    for cap in sorted({p['cap'] for p in pp}):
        nums=[p['han_pdf_page'] for p in pp if p['cap']==cap]
        for i in range(0,len(nums),2):
            group=nums[i:i+2]; w=window(pp,vv,mm,cap,group,1); windows.append(w)
            mapping={r['page']:r['mapping_availability'] for r in auditrows if r['cap']==cap and r['page'] in group}
            states=set(mapping.values()); state=states.pop() if len(states)==1 else 'partial'
            entry={'window':w['id'],'pages':group,'cap':cap,'mapping_status':state,'page_mapping_status':mapping,'status':'pending'}
            contexts.append({**entry,'processing_status':'pending','source_pages':w['pages'],'mapping':w['mapping'],'viet':t1_rows(w)}); contexts[-1].pop('status')
            entries.append(entry)
    identity={'source_sha256':fingerprint([pp,vv,mm]),'config':cfg,'method':'S4','vi':'T1','endpoint':SEPARATE,
              'code_sha256':fingerprint([(p.name,p.read_text(encoding='utf8')) for p in sorted((STAGE/'scripts').glob('*.py'))])}
    mp=out/'production_manifest.json'
    if mp.exists() and read(mp)['identity']!=identity: raise ValueError('Existing run identity mismatch')
    manifest={'identity':identity,'release_status':'preparing','windows':entries}
    workbook(out/'coarse_alignment_audit.xlsx',{'Page_Audit':auditrows}); client=SeparateOnly(out,cfg,live)
    try: rows=run_inventory(out,windows,client,cfg,manifest,contexts)
    finally: client.close()
    publish_inputs(out,rows,contexts); checked=verify(out,pp,windows,contexts)
    pages_by_status={s:[f"{e['cap']}:{n:03d}" for e in entries if e['status']==s for n in e['pages']] for s in ('successful','failed','pending')}
    complete=len(pages_by_status['successful'])==len(pp) and all(v['exact_reconstruction'] for v in checked.values())
    status='complete' if complete else 'incomplete'; mapping_counts=dict(Counter(r['mapping_availability'] for r in auditrows))
    log=out/'requests.jsonl'; log.touch(exist_ok=True); requests=read_jsonl(log)
    if any(r['endpoint']!=SEPARATE for r in requests): raise ValueError('Unexpected endpoint in production log')
    summary={'release_status':status,'caps':checked,'page_counts':{k:len(v) for k,v in pages_by_status.items()},'pages_by_status':pages_by_status,
             'page_mapping':mapping_counts,'window_mapping':dict(Counter(e['mapping_status'] for e in entries)),
             'windows':dict(Counter(e['status'] for e in entries)),'separate_network_attempts':len(requests),'alignment_network_attempts':0,
             'stage04_reader_match':True,'unique_ids':True,'ordered_offsets':True,'t1_verified':True,'halt':client.halt}
    write_json(out/'production_audit.json',summary)
    lines=['# Stage 03 production completion', '',f'**{status.upper()}** — S4 + T1; {len(pp)} pages, {len(windows)} windows.','',
           '| Cap | Pages | Segments | Cross-page | Source characters | Missing | Duplicated | Exact reconstruction |','|---|---:|---:|---:|---:|---:|---:|---|']
    for cap,x in checked.items(): lines.append('| '+' | '.join(str(v) for v in [cap,*[x[k] for k in ('total_pages','segments','cross_page_segments','source_chars','missing_chars','duplicated_chars','exact_reconstruction')]])+' |')
    lines+=['',f"Page processing counts: {summary['page_counts']}. Page mapping: {mapping_counts}.",f"Failed pages: {pages_by_status['failed'] or 'none'}. Pending pages: {pages_by_status['pending'] or 'none'}.",
            f"Separate network attempts: {len(requests)}. Alignment calls: 0. Unique IDs, ordered offsets, T1 source projections and real Stage 04 CSV reader verified for exported rows.",
            'Cap_02 page 051 is partially supported; 052–092 have no supported processed VI mapping. These source pages are retained. Translation absence is not inferred.',
            'The manifest records processing and mapping independently. See production_audit.json for exact page lists and README.md for the Stage 04 contract.']
    (out/'stage03_completion_report.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    manifest['release_status']=status;write_json(mp,manifest);print(summary['page_counts'],status,flush=True)
    return int(not complete)
