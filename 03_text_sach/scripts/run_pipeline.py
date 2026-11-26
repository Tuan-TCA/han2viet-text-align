"""Run Stage 03 segmentation and black-box downstream evaluation."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import time

from api_integration import Client
from candidate_boundaries import generate, s4
from coarse_alignment import fit_length, select_heldout, window
from evaluate_pipeline import blind_review, evaluate, export_stage04, segments, workbook
from local_repair import accept, propose, quality
from preprocess import ROOT, STAGE, fingerprint, load_sources, read_jsonl, viet_t1, write_json
from segmentation import SemanticEncoder, WEIGHTS, baseline, dynamic, lattice_points

METHODS=['M1','M2','M3','M4','M5','M6']
ABLATIONS={'no_length':('length',()),'no_semantic':('semantic',()),'no_numbers':('number',()),
           'no_entities':('entity',()),'no_direct_separate':(None,('separate',)),
           'no_separate':(None,('separate','s4')),
           'no_s4':(None,('s4',)),'no_repair':(None,())}
FILES={'benchmark':'benchmark_comparison.xlsx','ablation':'ablation_results.xlsx',
       'heldout':'heldout_comparison.xlsx','full':'han_segmented.xlsx'}


def known_used(maps):
    used=set()
    for p in (STAGE/'Cap_01/HAN/reviewed').glob('*-reviewed.csv'):
        used.add(('Cap_01',int(p.name.split('-')[0])))
    # Prior controls used unrelated VI text and the same pilot Han. Exclude
    # verified Han anchors of the control VI as a conservative additional guard.
    from benchmark_alignment_api import CONTROLS
    control_pages={int(s.rsplit('-',2)[1]) for group in CONTROLS for s in group}
    for r in maps:
        if r['cap']=='Cap_01' and r['viet_pdf_page'] in control_pages:
            used.update(('Cap_01',a['han_pdf_page']) for a in r['verified_overlap'])
    return used


def spanlist(path): return [x['han'] for x in path if x['han'][0]<x['han'][1]]


def adaptive_align(client, win, tag, spans, cfg):
    raw=win['raw']; v=win['viet']
    result=client.align(tag,raw,spans,v)
    if result['status'] not in ('api_error','parse_error') or len(win['pages'])<2 or client.halt:
        return result
    # Retry with smaller page-sized region and contextual VI subsets. Use an
    # existing sentence boundary near each page join rather than splitting a segment.
    cuts=sorted({0,len(raw)}|{min((b for _,b in spans), key=lambda x:abs(x-(p['global_raw_span'][1]-win['start'])))
                    for p in win['pages'][:-1]})
    attempts=[]; groups=[]; keys=set()
    for a,b in zip(cuts,cuts[1:]):
        pages={p['han_pdf_page'] for p in win['pages'] if p['global_raw_span'][0]<win['start']+b
               and p['global_raw_span'][1]>win['start']+a}
        relevant={m['viet_pdf_page'] for m in win['mapping'] if m['han_search_window'] and
                  any(m['han_search_window'][0]<=n<=m['han_search_window'][1] for n in pages)}
        subset=[r for r in v if any(r['viet_page_start']<=n<=r['viet_page_end'] for n in relevant)]
        if not subset: subset=v
        sub=client.align(f'{tag}:{a}-{b}',raw[a:b],[[x-a,y-a] for x,y in spans if a<=x<y<=b],subset)
        attempts.append(sub)
        if sub['status']!='ok': continue
        for g in sub['groups']:
            g=dict(g)
            if g['Han_Start'] is not None:
                g['Han_Start']+=a; g['Han_End']+=a
            ids=set(g['VI_IDs'])
            if keys&ids and g['Validation_Status']=='mapped': g['Validation_Status']='window_conflict'
            if g['Validation_Status']=='mapped': keys.update(ids)
            groups.append(g)
    return {'status':'ok' if any(a['status']=='ok' for a in attempts) else result['status'],
            'groups':groups,'original':result,'adaptive':attempts}


def run_window(win, args, cfg, fit, client, encoder, semantic_status, silver, out):
    raw=win['raw']; actual_start=win['start']; vn=[viet_t1(r['text_original'])[0] for r in win['viet']]
    page_ends=[p['global_raw_span'][1]-actual_start for p in win['pages']]
    sepkey, projected, sepstatus=client.separate(raw)
    marks=generate(raw,projected,page_ends,cfg['grid_step'])
    write_json(out/(win['id']+'.inputs.json'),{'window':win,'separate_status':sepstatus,'separate_key':sepkey,
               'projected_separate':projected,'candidates':marks})
    names=(['M5']+list(ABLATIONS) if args.mode=='ablation' else
           [args.method] if args.mode=='full' else METHODS)
    representations={}
    def semantic(removed):
        if not encoder or not vn: return None
        cuts=lattice_points(marks,removed)
        key=tuple(cuts)
        if key not in representations:
            representations[key]=encoder.lattice([raw[a:b] for a,b in zip(cuts,cuts[1:])],vn)
        return representations[key]
    rows=[]
    for name in names:
        print(f'{win["id"]} {name}',flush=True)
        t=time.monotonic(); sent=client.attempts; hits=client.hits
        base='M5' if name in ABLATIONS else name
        removed=ABLATIONS.get(name,(None,()))[1]
        weights=dict(WEIGHTS.get(base,{}))
        weights.pop(ABLATIONS.get(name,(None,()))[0],None)
        note=None
        if base=='M6': note='no_configured_offset_only_llm'
        if base=='M3' and encoder is None: note=semantic_status
        if base=='M1' and sepstatus!='ok': note=f'S4_requires_Separate:{sepstatus}'
        if note:
            rows.append({'method':name,'window':win['id'],'status':'NOT_RUN','reason':note}); continue
        if not projected and base!='M1': fallback='local_candidates_without_separate'
        else: fallback=None
        if 'semantic' in weights and encoder is None: weights.pop('semantic'); fallback=semantic_status
        path=baseline(raw,s4(raw,projected)) if base=='M1' else dynamic(raw,vn,marks,cfg,fit['ratio'],weights,
                semantic(removed) if 'semantic' in weights else None,removed)
        spans=spanlist(path)
        item=adaptive_align(client,win,name,spans,cfg)
        repair={'attempted':False,'accepted':False}
        if base=='M5' and name!='no_repair' and item['status']=='ok':
            repaired, audit=propose(raw,path,marks,item,cfg['repair_max_units'])
            if audit:
                proposal=adaptive_align(client,win,name+'-repair',repaired,cfg)
                repair={'attempted':True,'accepted':accept(item,proposal),'regions':audit,
                        'original_quality':quality(item),'proposed_quality':quality(proposal),
                        'original_alignment':item,'repair_alignment':proposal}
                if repair['accepted']:
                    path=[{**move,'han':[a,b],'kind':'repair' if [a,b]!=move['han'] else move['kind']}
                          for move in path for a,b in ([(move['han'][0],move['han'][1])] if move['han'][0]==move['han'][1]
                          else [(a,b) for a,b in repaired if move['han'][0]<=a<b<=move['han'][1]])]
                    spans=repaired; item=proposal
        metric,detail=evaluate(win,spans,item,silver)
        if not metric['exact_reconstruction']: raise ValueError('Segmentation failed partition integrity')
        score={'method':name,'window':win['id'],'status':'segmented','fallback':fallback,
               'wall_seconds':round(time.monotonic()-t,3),'api_requests':client.attempts-sent,
               'cache_hits':client.hits-hits,'repaired':repair['accepted'],**metric}
        group=[]
        for g in item['groups']:
            h=(g['Han_Start'],g['Han_End'])
            group.append({**g,'method':name,'window':win['id'],
                          'han_global_span':[actual_start+a for a in h] if h[0] is not None else None,
                          'Label_Target':'UNKNOWN','OMISSION':None,'ADDITION':None,'MISSING':None,
                          'Error_Origin':'UNKNOWN'})
        rows.append({**score,'details':detail,'alignment':item,'repair':repair,'path':path,
                     'groups':group,'han_segments':segments(win,path,marks,name)})
    return rows


def export(args, out, meta, results, client):
    metrics=[]; details=[]; groups=[]; items=[]
    for row in results:
        metrics.append({k:v for k,v in row.items() if k not in {'details','alignment','groups','han_segments','repair','path'}})
        details.extend({'method':row['method'],'window':row['window'],**r} for r in row.get('details',[]))
        items.extend(row.get('han_segments',[])); groups.extend(row.get('groups',[]))
    summary={**meta,'run_status':'halted' if client.halt else 'completed','halt':client.halt,
             'request_count':len(read_jsonl(out/'requests.jsonl')) if (out/'requests.jsonl').exists() else 0,
             'current_cache_hits':client.hits,'rows':metrics}
    write_json(out/'metrics.json',summary)
    flat=[]
    for row in metrics:
        d={k:v for k,v in row.items() if k not in {'references','uncovered_han_spans','missing_viet_ids'}}
        d.update({f'{ref}_{k}':v for ref,m in (row.get('references') or {}).items() for k,v in m.items()})
        flat.append(d)
    workbook(out/FILES[args.mode],{'Metrics':flat,'Silver_Detail':details,'Alignment_Groups':groups})
    workbook(out/'semantic_review.xlsx',{'Review':groups,'Instructions':[{'Rule':'Label 1 only after independent full semantic verification; inspect both text sides and OCR.'}]})
    workbook(out/'han_segmented.xlsx',{'Han_Segments':({k:v for k,v in r.items() if k!='normalized_source_spans'} for r in items)})
    export_stage04(out,items)
    (out/'han_segments.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in items),encoding='utf-8')
    lines=[f'# Stage 03 — {args.mode}', '', f"Requests logged: {summary['request_count']}; run {summary['run_status']}.",
           f"Length model: {meta['length_model']['ratio']:.3f} Han content characters/VI token; {len(meta['length_model']['samples'])} non-evaluation anchors.",
           f"Semantic encoder: {meta['semantic']}. Independently labelled held-out references: {meta['heldout_reference_status']}.", '',
           '| Window | Method | Alignment | Segments | Exact CG / DS / agreed | Mapped groups awaiting semantic review |',
           '|---|---|---|---:|---:|---:|']
    for row in metrics:
        refs=row.get('references') or {}; fmt=lambda r: '—' if refs.get(r,{}).get('alignment_exact') is None else f"{refs[r]['alignment_exact']}/{refs[r]['pairs']}"
        lines.append(f"| {row['window']} | {row['method']} | {row.get('api_status',row.get('reason','—'))} | {row.get('segments','—')} | {' / '.join(map(fmt,('CG','DS','agreed')))} | {row.get('semantic_unknown','—')} |")
    lines += ['', 'Exact compares one mapped alignment group per VI ID, with whitespace-equivalent edges. Mean IoU scores missing matches as zero. '
              'Boundary metrics compare segment endpoints, not final API groups. Verified positives and negatives are both zero until independent review; '
              'no verified-positive rate is estimable. Compare coverage and unresolved groups as diagnostics, not semantic quality.']
    (out/'pipeline_report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode',choices=tuple(FILES)); p.add_argument('--config',type=Path,default=STAGE/'config/stage03.json')
    p.add_argument('--run-id',required=True); p.add_argument('--live',action='store_true'); p.add_argument('--resume',action='store_true')
    p.add_argument('--no-model',action='store_true'); p.add_argument('--dry-run',action='store_true')
    p.add_argument('--method',choices=METHODS[:-1],default='M1'); p.add_argument('--release',type=Path)
    args=p.parse_args(argv)
    if not re.fullmatch(r'[a-zA-Z0-9_-]+',args.run_id): p.error('Invalid run ID')
    cfg=json.loads(args.config.read_text(encoding='utf-8'))
    pages,viet,maps=load_sources(); b=cfg['benchmark']
    excluded=known_used(maps)|{(b['cap'],n) for n in b['pages']}
    hold=select_heldout(pages,maps,cfg['heldout_page_count_per_cap'],excluded)
    fit=fit_length(pages,viet,maps,{(b['cap'],n) for n in b['pages']}|{(cap,n) for cap,ns in hold for n in ns})
    if args.mode in ('benchmark','ablation'):
        windows=[window(pages,viet,maps,b['cap'],b['pages'],viet_pages=b['viet_pages'])]
    elif args.mode=='heldout':
        windows=[window(pages,viet,maps,c,ns,cfg['context_margin']) for c,ns in hold]
    else:
        size=cfg['window_pages']; bycap={c:[s['han_pdf_page'] for s in pages if s['cap']==c] for c in sorted({s['cap'] for s in pages})}
        windows=[window(pages,viet,maps,c,nums[i:i+size],cfg['context_margin'])
                 for c,nums in bycap.items() for i in range(0,len(nums),size)]
    if args.dry_run:
        print(json.dumps({'mode':args.mode,'windows':len(windows),'pages':sum(len(w['pages']) for w in windows),
                          'unmatched':sum(not w['viet'] for w in windows),'heldout':hold})); return 0
    if args.mode=='full':
        if not args.release: p.error('full requires --release with an independently reviewed release decision')
        release=json.loads(args.release.read_text(encoding='utf-8'))
        if release.get('approved_method')!=args.method or release.get('config_sha256')!=fingerprint(cfg) or not release.get('heldout_review'):
            p.error('Release lacks matching configuration/method or documented held-out review')
    mode_dir='final' if args.mode=='full' else args.mode
    out=STAGE/'artifacts'/mode_dir/args.run_id
    out.mkdir(parents=True,exist_ok=args.resume)
    immutable={'config_sha256':fingerprint(cfg),'config':cfg,'mode':args.mode,'no_model':args.no_model,
               'method':args.method,'windows':[w['id'] for w in windows], 'heldout':hold,
               'source_sha256':fingerprint([pages,viet,maps]),'length_model':fit}
    manifest=out/'manifest.json'
    # Compare canonical forms because JSON round-trips tuples as lists.
    if manifest.exists() and fingerprint(json.loads(manifest.read_text(encoding='utf-8')))!=fingerprint(immutable):
        p.error('Cannot resume with different source or configuration')
    write_json(manifest,immutable)
    client=Client(out,cfg,args.live); results=[]; encoder=None; semantic_status='model_disabled'
    try:
        if not args.no_model and (args.mode!='full' or args.method in ('M3','M5')):
            try:
                encoder=SemanticEncoder(ROOT/cfg['semantic_model'],cfg['semantic_batch'],cfg['semantic_token_limit'])
                encoder.encode(['天地','trời đất']); semantic_status='local_omnia_align'
            except Exception as e:
                print(f'Semantic encoder unavailable: {type(e).__name__}: {e}',flush=True)
                encoder=None; semantic_status='model_unavailable:'+type(e).__name__
        silver=(read_jsonl(ROOT/'pipeline/artifacts/phase1/silver_benchmark.jsonl') if args.mode in ('benchmark','ablation') else [])
        for win in windows:
            checkpoint=out/(win['id']+'.checkpoint.json')
            saved=json.loads(checkpoint.read_text(encoding='utf-8')) if checkpoint.exists() else None
            if saved and saved['complete'] and saved['live']==args.live and saved['semantic']==semantic_status:
                rows=saved['rows']; print(f"Resume {win['id']}",flush=True)
            else:
                rows=run_window(win,args,cfg,fit,client,encoder,semantic_status,silver,out)
                write_json(checkpoint,{'complete':not client.halt,'live':args.live,'semantic':semantic_status,'rows':rows})
            results.extend(rows)
            if client.halt: break
        export(args,out,{**immutable,'semantic':semantic_status,'heldout_reference_status':'UNAVAILABLE'},results,client)
        if args.mode=='heldout': blind_review(out,windows)
    finally:
        client.close()
    print(out,flush=True)
    return int(bool(client.halt))


if __name__=='__main__': raise SystemExit(main())
