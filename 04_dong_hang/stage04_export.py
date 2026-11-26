"""Group-aware structural evaluation and template-compatible review exports."""
from collections import Counter
import json

from openpyxl import Workbook, load_workbook
from preprocess import write_json
from stage04_candidates import identity


def points(spans):
    return {n for a,b in spans for n in range(a,b)}


def coverage(predicted, target):
    gold = points(target)
    return len(points(predicted)&gold)/len(gold) if gold else 0


def measures(resolved,f,jobs):
    selected = resolved['selected']; silver = {r['VI_ID']:r for r in f['silver']}; vi = f['vi']
    mapped = {k for g in selected for k in g['VI_IDs'] if k in silver}
    vid_cov = [coverage([(a,b) for g in selected for k,a,b in g['VI_Char_Spans'] if k==key],
                         [(0,len(vi[key]['text_original']))]) for key in silver]
    models = {}
    for name in ('chatgpt','deepseek','agreed'):
        refs = {k:r['comparison'][f'{"chatgpt" if name=="agreed" else name}_han_link']['global_raw_span']
                for k,r in silver.items() if name!='agreed' or r['Boundary_Agreement']=='SAME'}
        rows = {k:dict(VI_ID=k,Pair_ID=silver[k]['Pair_ID'],Reference=span,Exact=False,IoU=0,Status='NO_PREDICTION')
                for k,span in refs.items()}
        for g in selected:
            keys = [k for k in g['VI_IDs'] if k in rows]
            if not keys:
                continue
            comparable = len(keys)==len(g['VI_IDs'])
            expected = points([refs[k] for k in keys]); a,b = g['Han_Start'],g['Han_End']; pred = set(range(a,b))
            # Treat whitespace between consecutive reference components as part of the envelope.
            envelope = range(min(expected),max(expected)+1)
            expected |= {x for x in envelope if f['raw'][x].isspace()}
            full = g['Validation_Status']=='mapped'
            exact = comparable and full and pred==expected
            iou = len(pred&expected)/len(pred|expected) if comparable else None
            for k in keys:
                old = rows[k]
                if old['Status']=='NO_PREDICTION' or (iou or 0) > (old['IoU'] or 0):
                    rows[k].update(Exact=exact,IoU=iou,Status='COMPARABLE' if comparable else 'GROUP_OUTSIDE_REFERENCE',
                                   Predicted_Group=[a,b],Predicted_VI_IDs=g['VI_IDs'])
        scored = [r['IoU'] for r in rows.values() if r['IoU'] is not None]
        models[name] = dict(total=len(rows),exact=sum(r['Exact'] for r in rows.values()),
                            mean_iou=sum(scored)/len(scored) if scored else None,
                            not_comparable=sum(r['IoU'] is None for r in rows.values()),pairs=list(rows.values()))
    return dict(refs=models, han_coverage=coverage([(g['Han_Start'],g['Han_End']) for g in selected],
                         [s['global_raw_span'] for s in f['han']]),vi_coverage=sum(vid_cov)/len(silver),
                mapped_vi=len(mapped),mapping_success_rate=len(mapped)/len(silver),
                missing_vi_ids=list(silver.keys()-mapped), unresolved=len(resolved['unresolved']),
                duplicates=resolved['duplicates'],conflicts=resolved['conflict_edges'],
                alignment_types=dict(Counter(g['Alignment_Type'] for g in selected)),jobs=len(jobs),
                request_status=dict(Counter(j['status'] for j in jobs)),semantic_verified=0,semantic_positives=0,
                verified_semantic_positive_rate=None,unknown=len(selected),unknown_rate=1.0 if selected else None)


TEMPLATE = ['Pair_ID','Chinese','Vietnamese','OMISSION','ADDITION','MISSING','Alignment_Type',
            'Punct_Anchor_Match','Label_Target','OCR_Conf_Min','Note']
FIELDS = TEMPLATE + ['Experiment_ID','API_Response_ID','Cap','Han_IDs','VI_IDs','Han_Text','Vietnamese_Text',
                     'Han_Start','Han_End','VI_Char_Spans','API_Score','Validation_Status','OCR_Uncertainty',
                     'Review_Status','Source_Rows','VI_Source_Rows','Support','Occurrences']


def tab(wb, name, fields, rows):
    ws = wb.create_sheet(name); ws.append(fields)
    for row_number,r in enumerate(rows,2):
        for i,k in enumerate(fields,1):
            value = r.get(k)
            if isinstance(value,(dict,list,tuple)):
                value = json.dumps(value,ensure_ascii=False)
            if isinstance(value,str) and len(value)>32767:
                value = value[:32690]+' … full record in results.json'
            cell = ws.cell(row_number,i,value)
            if isinstance(value,str):
                cell.data_type = 's'
    ws.freeze_panes='A2'; ws.auto_filter.ref=ws.dimensions


def workbook(out,name,sheets):
    w = Workbook(); w.remove(w.active)
    for sheet,fields,rows in sheets:
        tab(w,sheet,fields,rows)
    path=out/name; tmp=path.with_name(path.stem+'.tmp.xlsx'); w.save(tmp); w.close()
    check=load_workbook(tmp,read_only=True,data_only=False)
    try:
        for sheet,fields,rows in sheets:
            s=check[sheet]; actual=list(s.values)
            if list(actual[0])!=fields or len(actual)!=len(rows)+1:
                raise ValueError(f'Invalid generated workbook {name}/{sheet}')
            if any(c.data_type=='f' for row in s for c in row):
                raise ValueError(f'Unexpected formula in {name}/{sheet}')
    finally:
        check.close()
    tmp.replace(path)


def as_row(g,pair):
    return {**g,'Pair_ID':pair,'Chinese':g['Han_Text'],'Vietnamese':g['Vietnamese_Text']}


def gaps(f,chosen):
    han = points([(c['Han_Start'],c['Han_End']) for c in chosen])
    for s in f['han']:
        a,b = s['global_raw_span']; start = None
        for i in range(a,b+1):
            if i<b and i not in han:
                start = i if start is None else start
            elif start is not None:
                yield dict(Cap='Cap_01',Han_IDs=[s['id_zh']],Han_Start=start,Han_End=i,Han_Text=f['raw'][start:i],Reason='UNCOVERED_HAN')
                start = None
    for row in f['silver']:
        k = row['VI_ID']; text=f['vi'][k]['text_original']
        covered = points([(a,b) for c in chosen for key,a,b in c['VI_Char_Spans'] if key==k])
        start = None
        for i in range(len(text)+1):
            if i<len(text) and i not in covered:
                start = i if start is None else start
            elif start is not None:
                yield dict(Cap='Cap_01',VI_IDs=[k],VI_Char_Spans=[(k,start,i)],Vietnamese_Text=text[start:i],Reason='UNCOVERED_VI')
                start = None


def publish(out,f,data):
    resolved = data['resolved']; metric = data['metrics']; prod = resolved['refinement']; chosen = prod['selected']
    all_rows = [as_row({**g,'Experiment_ID':stage,'Origin_Experiment_ID':g['Experiment_ID']},f'{stage}-{i:03}')
                for stage,r in resolved.items() for i,g in enumerate(r['selected'],1)]
    review = {}; all_review = ['ChatGPT_Judgment','ChatGPT_Evidence','DeepSeek_Judgment','DeepSeek_Evidence','Independent_Adjudication']
    for stage,r in resolved.items():
        for g in r['selected']+r['conflicts']:
            key = identity(g)
            if key not in review:
                review[key] = as_row(g,f'S04-{len(review)+1:04}')
                review[key]['Review_Experiments'] = []
            if stage not in review[key]['Review_Experiments']:
                review[key]['Review_Experiments'].append(stage)
    unresolved = prod['unresolved'] + list(gaps(f,chosen)) + f['unsupported']
    comparisons = [{**r,'Experiment_ID':stage,'Reference_Model':model} for stage,m in metric.items()
                   for model,z in m['refs'].items() for r in z['pairs']]
    workbook(out,'alignment_results.xlsx', [('Alignment_Dataset',FIELDS+['Origin_Experiment_ID'],all_rows),
             ('Boundary_Evaluation',['Experiment_ID','Reference_Model','Pair_ID','VI_ID','Reference','Predicted_Group',
                                    'Predicted_VI_IDs','Exact','IoU','Status'],comparisons)])
    workbook(out,'semantic_review.xlsx',[('Alignment_Dataset',FIELDS+['Review_Experiments']+all_review,list(review.values()))])
    workbook(out,'unresolved.xlsx',[('Unresolved',['Reason','Han_Page']+FIELDS,unresolved)])
    workbook(out,'conflicts.xlsx',[('Conflicts',['Evaluation_Experiment','Disposition','Competing_Spans']+FIELDS,
                                   [{**g,'Evaluation_Experiment':s} for s,r in resolved.items() for g in r['conflicts']])])
    workbook(out,'boundary_repairs.xlsx',[('Repairs',['Block','Operation','Accepted','Before','After','Corroborated',
                                         'Local_Improvement','Decision','Old_VI_IDs','New_VI_IDs','Han_Spans','Candidates'],data['repairs'])])
    data['provenance'] = {'han':f['han'],'vi':{k:v for k,v in f['vi'].items() if k in f['pool']},'silver':f['silver']}
    data['unresolved_source'] = unresolved
    data['review_groups'] = list(review.values())
    write_json(out/'results.json',data)
    write_json(out/'metrics.json',{'execution':data['execution'],'experiments':metric,
                                    'deduplicated_review':{'groups':len(review),'verified_positive':0,'unknown':len(review)}})
    report(out,data,f)


def report(out,d,f):
    m=d['metrics']; e=d['execution']
    lines=['# Stage 04 — Phase A benchmark','',f"**Execution: {e['status']}**. Live requests: {e['live_requests']}; cache hits: {e['cache_hits']}; "
           f"live failures: {e['api_failure_rate']}; summed live latency: {e['api_latency_seconds']:.2f}s; "
           f"measured benchmark wall time: {e['wall_seconds']:.2f}s.",
           f"Repeated live payload attempts in the initial sweep: {e['repeated_live_payload_attempts']}. "
           'Terminal API and parse failures now reuse the recorded outcome within a run.', '',f"Silver input: `{f['silver_source']}`. "
           'Three historical positive labels are provisional and not inherited.','',
           '| Experiment | Exact CG / DS / agreed | Mean IoU CG / DS / agreed | Han / VI cov. | VI mapped | Unresolved | Duplicates | Conflicts | N–M / groups | Jobs |',
           '|---|---|---|---|---:|---:|---:|---:|---|---:|']
    for stage,x in m.items():
        refs=list(x['refs'].values()); exact=' / '.join(f"{r['exact']}/{r['total']}" for r in refs)
        iou=' / '.join('n/a' if r['mean_iou'] is None else f"{r['mean_iou']:.3f}" for r in refs)
        types=x['alignment_types']
        lines.append(f"| {stage} | {exact} | {iou} | {x['han_coverage']:.3f} / {x['vi_coverage']:.3f} | "
                     f"{x['mapped_vi']}/12 | {x['unresolved']} | {x['duplicates']} | {x['conflicts']} | "
                     f"{types.get('N-M',0)} / {sum(types.values())} | {x['jobs']} |")
    lines += ['', '### Interpretation', '',
              '- Exact match and IoU evaluate the union of references for each complete predicted group, rather than forcing 1–1. '
              'Groups containing out-of-scope VI IDs are flagged not comparable; exact uses the full reference denominator, and mean IoU excludes these groups but counts absent predictions as zero.',
              '- Han coverage uses the frozen benchmark window; VI coverage averages original-character coverage across the 12 VI IDs. Conflicts count overlapping or order-incompatible candidate pairs.',
              '- No independently verified semantic positives or negatives. The verified positive rate is undefined; every exported review group is UNKNOWN.',
              '- Cap_02 pages 052–092 are unresolved because processed Vietnamese context is unavailable. No translation absence is inferred.']
    if e['status']=='complete':
        best=max((f'B2-{s}' for s in (5,10,15,20,30)),key=lambda k:m[k]['refs']['agreed']['mean_iou'] or 0)
        lines += [f"- Best observed fixed-size B2 window by agreed-reference mean IoU: **{best}** (ties follow size order).",
                  '- Compare `original-10`, `B1-10`, and `B2-10` at fixed size; these two anchored pages cannot establish a corpus-wide prior ranking.',
                  f"- Adaptive search explored {len(d['adaptive_log'])} alternative placements; boundary repair accepted {sum(r['Accepted'] for r in d['repairs'])}/{len(d['repairs'])} hypotheses. See the table for structural deltas."]
        lines.append('- The first repair pass improved local coverage but dropped accepted evidence after global reconciliation. The final pass also requires a strict global Han coverage gain, no VI coverage loss, and unchanged selections outside the repaired block.')
        if d['repairs'] and {r['Operation'] for r in d['repairs']} == {'merge'}:
            lines.append('- Only merge repairs were exercised live: these blocks offered no internal punctuation or API-backed Han cut. Split and move mechanisms are covered by unit tests, not benchmark results.')
    else:
        lines.append(f"- Service halt (`{e['halt']}`); incomplete experiments do not support window or prior rankings.")
    reasons = Counter((g['Han_Resolution'],g['VI_Resolution']) for groups in d['raw_groups'].values() for g in groups
                      if g['Validation_Status'] not in ('mapped','partial_viet'))
    lines += ['', '### Counterexamples and gate', '', '- Full VI coverage is not boundary accuracy: the 1×1 probes mapped all 12 VI IDs but matched zero exact boundaries.',
              f'- Unresolved API row observations across treatments by (Han, VI) resolver result: `{dict(reasons)}`. Conflicting group boundaries and partial VI matches remain available for review.',
              '- Historical reversed-order API probes returned high-scoring N–M groups at full coverage.',
              '- See `conflicts.xlsx` for competing boundaries and `unresolved.xlsx` for uncovered source. A valid end-to-end grouping still requires semantic review.',
              '- **Not ready for full production.** This benchmark has only 12 references from Cap_01 and does not establish semantic accuracy. Phase B requires explicit approval.']
    (out/'alignment_report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
