import csv,io
from copy import copy
from openpyxl import Workbook,load_workbook
from inputs import *
from reconcile import collect

def publish(out,cfg,d,windows,mode):
    gs,raw,rejected,uh,uv,states,m=collect(out,cfg,d,windows)
    # These are review flags, not claims that T1 caused the mismatch.
    jobs={e['job']['key']:e['job'] for e in lines(out/'requests.jsonl')};norm_fail=[]
    for g in rejected:
        key=g.get('Request_Key',g.get('key'));j=jobs.get(key,{})
        changed=[k for k in j.get('v',[]) if d['vi'][k]['text_t1']!=d['vi'][k]['text_original']]
        if changed and (g.get('mapping_error') or g.get('VI_Resolution') not in ('indices_text','aggregated')):norm_fail.append(dict(key=key,source_rows=g.get('Source_Rows'),vi_resolution=g.get('VI_Resolution'),normalized_ids=changed,reason=g['reason']))
    jsonl(out/'normalization_review.jsonl',norm_fail)
    for name,rows in [('alignment_final',gs),('alignment_raw',raw),('unresolved_han',uh),('unresolved_viet',uv),('rejected_candidates',rejected),('window_manifest',states)]:jsonl(out/(name+'.jsonl'),rows)
    wb=load_workbook(io.BytesIO(template()));ws=wb['Alignment_Dataset'];header=[c.value for c in ws[1]];styles=[copy(c._style) for c in ws[3]];height=ws.row_dimensions[3].height;ws.delete_rows(3,ws.max_row-2);review=Workbook();rs=review.active;rs.title='Review';au=wb.create_sheet('Audit');fields=['Pair_ID','Cap','Han_Start','Han_End','VI_IDs','Validation_Status','Label_Target','Review_Status','Request_Key'];au.append(fields);rs.append(fields+['Chinese','Vietnamese','Reviewer_Label','Reviewer_Notes'])
    with (out/'alignment_final.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=header);writer.writeheader()
        for i,g in enumerate(gs,3):
            row=dict(Pair_ID=g['Pair_ID'],Chinese=g['Han_Text'],Vietnamese=g['Vietnamese_Text'],Alignment_Type=g['Alignment_Type'],Note='Pending independent review');writer.writerow(row);ws.append([row.get(k) for k in header]);ws.row_dimensions[i].height=height
            for c,s in zip(ws[i],styles):
                c._style=s
                if isinstance(c.value,str):c.data_type='s'
            vals=[dump(g[k]) if isinstance(g[k],list) else g[k] for k in fields];au.append(vals);rs.append(vals+[g['Han_Text'],g['Vietnamese_Text'],None,None])
    for dv in ws.data_validations.dataValidation:
        dv.sqref=str(dv.sqref).replace('100',str(max(100,ws.max_row)))
    wb.save(out/'alignment_final.xlsx');review.save(out/'semantic_review.xlsx');log=lines(out/'requests.jsonl');live=sum(not e.get('cached') and e.get('network',True) for e in log);m.update(mode=mode,windows=len(windows),completed=sum(s['completed'] for s in states),selected=len(gs),han_total=len(d['raw']),han_unresolved=sum(len(r['text']) for r in uh),vi_total=sum(len(v['text_original']) for v in d['vi'].values()),vi_unresolved=sum(len(r['text']) for r in uv),network_requests=live,exact_cache_hits=sum(bool(e.get('cached')) for e in log),human_labels=0,semantic_accuracy='NOT MEASURED');m.update(han_aligned=m['han_total']-m['han_unresolved'],vi_aligned=m['vi_total']-m['vi_unresolved']);save(out/'metrics.json',m)
    if cfg.get('experimental_v4'):
        sys.path.insert(0,str(HERE.parent/'v4_release'));from engine import refine
        alt=[]
        for s in states:
            arr=[g for g in raw if g['Experiment_ID']==s['id']+'-full'];p=dict(ids=s['vi_ids'],han=[d['byid'][k]['global_raw_span'] for k in s['han_ids']],baseline=arr);_,ledger=refine(p,[p],d['raw'],d['vi'],read(HERE.parent/'v4_release/config.json'));alt.append(dict(window=s['id'],experimental_only=ledger))
        jsonl(out/'experimental_v4.jsonl',alt)
    (out/'production_report.md').write_text(f"# Stage04 {mode}: {out.name}\n\nMethod: S4+T1. Profile: {cfg['profile']}.\n\nExecution: {m['completed']}/{len(windows)} windows checkpointed; {live} network requests; {m['successful_responses']} successful response uses; {m['offline_cache_misses']} offline misses (unevaluated). Unsupported and partial pages without supported source boundaries are withheld.\n\nSource mapping: {m['fully_mapped_response_groups']} full and {m['partial_response_groups']} partial of {len(raw)} response groups. Global reconciliation selected {len(gs)} pairs. Han: {m['han_aligned']}/{m['han_total']} characters aligned; Vietnamese: {m['vi_aligned']}/{m['vi_total']}. All remaining characters are listed in unresolved ledgers.\n\nIndependent semantic labels: 0. Semantic accuracy: NOT MEASURED. Structural gaps carry no omission/addition labels.\n",encoding='utf8');return m
