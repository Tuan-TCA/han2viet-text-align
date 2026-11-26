"""E07–E11 Alignment API pilot; benchmark boundaries are experiment inputs only."""

import argparse
import json
import math
import os
import re
import statistics as stats
from collections import Counter, defaultdict
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

import benchmark_alignment_api as base
import benchmark_alignment_api_v2 as robust


ROOT = base.ARTIFACTS
OUT = ROOT / 'alignment_benchmark_final'
# Source-reviewed dotted integers, not a general rule for single-dot decimals.
CONFIRMED = {'Cap_01-VI-0186-003': ['2.727'], 'Cap_01-VI-0187-002': ['4.349']}
NUM = re.compile(r'(?<![\w.,])[0-9]+(?:[.,][ \t]*[0-9]+)+(?!\w)')
GROUPED = re.compile(r'[0-9]{1,3}(?:\.[ \t]*[0-9]{3})+')
MIN_COMMA = 55


def normalize_numbers(text, confirmed=()):
    """Preserve decimal commas, ambiguous single dots and ungrouped decimals."""
    deleted, changes = set(), []
    for m in NUM.finditer(text):
        value = m[0]
        if GROUPED.fullmatch(value) and (value.count('.') >= 2 or value in confirmed):
            new = ''.join(c for c in value if c.isascii() and c.isdigit())
            deleted.update(i for i in range(*m.span()) if text[i] not in '0123456789')
            changes.append({'source_span': list(m.span()), 'old': value, 'new': new})
    offsets = [i for i in range(len(text)) if i not in deleted]
    return ''.join(text[i] for i in offsets), offsets, changes


def cut_points(text, strategy):
    if strategy == 'T1':
        return [0, len(text)]
    protected = {i for m in NUM.finditer(text) for i in range(*m.span())}
    marks = '.' if strategy == 'T2' else '.;'
    cuts = [0, *(i+1 for i,c in enumerate(text) if c in marks and i not in protected), len(text)]
    if strategy != 'T4':
        return sorted(set(cuts))
    extra = []
    for lo, hi in zip(cuts, cuts[1:]):
        start = lo
        for i in range(lo, hi):
            if (text[i] == ',' and i not in protected and len(text[start:i+1].strip()) >= MIN_COMMA
                    and len(text[i+1:hi].strip()) >= MIN_COMMA):
                extra.append(i+1)
                start = i+1
    return sorted(set(cuts + extra))


def fragments(key, text, strategy='T1', normalize=True):
    cuts = cut_points(text, strategy)
    output = []
    for a,b in zip(cuts,cuts[1:]):
        chunk = text[a:b]
        start = a + len(chunk) - len(chunk.lstrip())
        chunk = chunk.strip()
        if not chunk:
            continue
        value, idx, changes = (normalize_numbers(chunk, CONFIRMED.get(key, ())) if normalize else
                               (chunk, list(range(len(chunk))), []))
        assert base.normalize(value) == value, 'Source preprocessing expected normalized workbook whitespace'
        output.append(dict(id=f'{key}@{start}:{start+len(chunk)}', vi_id=key, text=value,
                           start=start, end=start+len(chunk), offsets=[start+i for i in idx],
                           changes=[{**c, 'source_span':[start+i for i in c['source_span']]} for c in changes]))
    return output


def whitespace_gap(text, a, b):
    return 0 <= a <= b <= len(text) and not text[a:b].strip()


def union_parts(parts, source):
    """Join same-ID spans within a row across only whitespace, retaining gaps otherwise."""
    result = []
    for key,a,b in parts:
        if result and result[-1][0] == key and whitespace_gap(source[key], result[-1][2],a):
            result[-1] = [key,result[-1][1],b]
        else:
            result.append([key,a,b])
    return result


def full_segment(parts, key, source):
    spans = [(a,b) for k,a,b in parts if k==key]
    return (len(spans)==1 and whitespace_gap(source[key],0,spans[0][0])
            and whitespace_gap(source[key],spans[0][1],len(source[key])))


def project(job, entry, raw, source):
    rows = robust.parse_robust(job, entry, raw)
    meta = {f['id']:f for f in job['fragments']}
    for row in rows:
        payload_parts = row['VI_Char_Spans']
        original = []
        for frag,a,b in payload_parts:
            f = meta[frag]
            original.append([f['vi_id'], f['offsets'][a], f['offsets'][b-1]+1])
        parts = union_parts(original, source)
        ids = list(dict.fromkeys(k for k,_,_ in parts))
        row.update(VI_Char_Spans=parts, VI_IDs=ids, VI_Payload_Spans=payload_parts,
                   Vietnamese_Text=' '.join(source[k][a:b] for k,a,b in parts),
                   Alignment_Type=robust.alignment_type(len(row['Han_Units']), len(ids)))
        if row['Validation_Status'] in {'partial_viet','mapped'}:
            row['Validation_Status'] = ('unpaired' if row['Han_Start'] is None or not ids else
                                        'mapped' if all(full_segment(parts,k,source) for k in ids) else 'partial_viet')
    return rows


def aggregate(rows, raw, source):
    def eligible(c):
        return (c['Validation_Status'] in {'mapped','partial_viet'} and len(c['VI_Char_Spans'])==1
                and c['Han_Start'] is not None and c['Han_Start'] < c['Han_End'])

    out, i = [], 0
    while i < len(rows):
        first = rows[i]
        j = i
        if eligible(first):
            vi, start, end = first['VI_Char_Spans'][0]
            text = source[vi]
            if whitespace_gap(text,0,start) and not whitespace_gap(text,end,len(text)):
                while j+1 < len(rows) and not whitespace_gap(text,end,len(text)):
                    prev, nxt = rows[j:j+2]
                    if (not eligible(nxt) or nxt['VI_IDs'] != [vi] or nxt['Row'] != prev['Row']+1
                            or any(nxt[k] != first[k] for k in ('API_Response_ID','Experiment_ID'))
                            or not whitespace_gap(raw,prev['Han_End'],nxt['Han_Start'])
                            or not whitespace_gap(text,end,nxt['VI_Char_Spans'][0][1])):
                        break
                    end = nxt['VI_Char_Spans'][0][2]
                    j += 1
                if j > i and whitespace_gap(text,end,len(text)):
                    block = rows[i:j+1]
                    stop = block[-1]['Han_End']
                    units = sorted({n for c in block for n in c['Han_Units']})
                    out.append({**first,'Han_End':stop,'Han_Text':raw[first['Han_Start']:stop], 'Han_Units':units,
                                'VI_Char_Spans':[[vi,0,len(text)]], 'Vietnamese_Text':text,
                                'VI_Payload_Spans':[p for c in block for p in c['VI_Payload_Spans']],
                                'Validation_Status':'mapped', 'Alignment_Type':robust.alignment_type(len(units),1),
                                'Score':None,'Source_Rows':[c['Row'] for c in block],
                                'Component_Scores':[c['Score'] for c in block], 'VI_Resolution':'whitespace_aggregation'})
                    i = j+1
                    continue
        out.append(first)
        i += 1
    return out


def make_job(stage, name, h, vids, raw, source, strategy='T1', norm=True, **meta):
    fs = [f for vi in vids for f in fragments(vi,source[vi],strategy,norm)]
    job = base.job(stage,name,strategy,h,[f['id'] for f in fs],raw,
                   {f['id']:{'text_original':f['text']} for f in fs},repeat=meta.get('repeat_of'))
    job.update(fragments=fs,source_vi=list(vids),**{k:v for k,v in meta.items() if k!='repeat_of'})
    return job


def fixture():
    raw, strategies, viet, _, _, maps = base.inputs()
    source = {k:r['text_original'] for k,r in viet.items()}
    silver = base.load_jsonl(ROOT/'phase1/silver_benchmark.jsonl')
    h = [r['han_link']['global_raw_span'] for r in silver]
    v = [r['VI_ID'] for r in silver]
    assert len(silver)==12 and all(raw[a:b]==s['Chinese'] and source[k]==s['Vietnamese'] for (a,b),s,k in zip(h,silver,v))
    return raw, strategies, source, silver, h, v, maps


def jobs(fix):
    raw, strategies, source, silver, h, v, maps = fix
    # Three adjacent swaps within the same passage. Each pair describes distinct content.
    hard = {0:(1,'individual village clerks vs exemption and head-tax provisions'),
            1:(0,'exemption and head-tax provisions vs individual village clerks'),
            4:(5,'Thang Hoa levy figures vs brief Thuận Hóa generalization'),
            5:(4,'brief Thuận Hóa generalization vs Thang Hoa levy figures'),
            8:(9,'seal and betel payments vs stipends for inner-palace women and ministry posts'),
            9:(8,'stipends for inner-palace women and ministry posts vs seal and betel payments')}
    far = iter(('Cap_01-VI-0221-001','Cap_01-VI-0250-003','Cap_01-VI-0221-002',
                'Cap_01-VI-0250-004','Cap_01-VI-0250-002','Cap_01-VI-0251-001'))
    for i,r in enumerate(silver):
        p = r['Pair_ID']
        yield make_job('E07',f'corresponding-{i+1:02}',[h[i]],[v[i]],raw,source, kind='corresponding',
                       pair=p, provisional=r['Label_Target']==1, basis='Silver candidate')
        if i in hard:
            k, basis = hard[i]
            kind, neg = 'hard', v[k]
        else:
            kind, neg = 'distant', next(far)
            page = int(neg.split('-')[-2])
            anchor = maps[page][0]['han_pdf_page']
            assert anchor > 2
            basis = f'Vietnamese PDF p.{page} is anchored at Han p.{anchor}, outside Han 001–002'
        yield make_job('E07',f'{kind}-{i+1:02}',[h[i]],[neg],raw,source,kind=kind,pair=p,
                       provisional=r['Label_Target']==1,basis=basis)
    for i in (0,8):
        for reverse in (False,True):
            yield make_job('E08',f'{i+1:02}-{i+2:02}-'+('reverse' if reverse else 'normal'),h[i:i+2],
                           v[i:i+2][::-1] if reverse else v[i:i+2],raw,source,window=i,reverse=reverse)
    for i in (2,4):
        for norm in (False,True):
            yield make_job('E09',f'{i+1:02}-{i+2:02}-'+('normalized' if norm else 'source'),h[i:i+2],v[i:i+2],
                           raw,source,norm=norm,window=i,normalized=norm)
    for t in ('T1','T2','T3','T4'):
        yield make_job('E10',t,strategies['S4'],v,raw,source,strategy=t)
    yield make_job('E11','12x12',h,v,raw,source,context='Silver boundaries, all 12 pairs')
    for i in range(0,12,2):
        yield make_job('E11',f'2x2-{i+1:02}-{i+2:02}',h[i:i+2],v[i:i+2],raw,source,context='normalized 2x2 baseline')


def history():
    records = {}
    sources = [('alignment_benchmark/requests.jsonl',base.load_jsonl(ROOT/'alignment_benchmark/requests.jsonl'))]
    for name in ('silver_2x2_pilot','silver_2x2_numbers_pilot'):
        path = name+'/results.json'
        sources.append((path,[r['response'] for r in base.read(ROOT/path)['tests']]))
    for path, rows in sources:
        for r in rows:
            if r and r['status'] not in {'transport_error','auth_or_rate_limit','transient_http'} and 'raw_response' in r:
                key = base.fingerprint([base.URL,r['job']['payload']])
                records.setdefault(key,{**r,'id':f"H:{path}:{r['id']}", 'historical_source':path})
    return records


class Runner(base.Runner):
    def __init__(self,args,token,prior):
        super().__init__(args,token)
        self.prior = prior

    def run(self, job):
        if not job['repeat_of'] and job['key'] in self.prior:
            p = self.root/'cache'/(job['key']+'.json')
            if not p.exists():
                base.write(p,base.dump(self.prior[job['key']])+'\n')
        before = len(self.entries)
        result = super().run(job)
        if result is None:
            print(f"{job['id']} paused: {self.halt}",flush=True)
        elif result['cached'] or len(self.entries)==before:
            print(f"{job['id']} {result['status']} reused {result['id']}",flush=True)
        return result


def score_list(entry):
    if entry['status'] != 'success':
        return []
    return [r['score'] for r in json.loads(entry['raw_response'])['data']['result'] if isinstance(r,dict)
            and type(r.get('score')) in (float,int) and math.isfinite(r['score'])
            and r.get('han_start') != -1 and r.get('vi_start') != -1]


def run_one(runner, job, raw, source):
    entry = runner.run(job)
    if entry is None:
        return None
    candidates = project(job,entry,raw,source)
    rows = aggregate(candidates,raw,source)
    paired = [c for c in rows if c['Validation_Status'] in {'mapped','partial_viet'} and c['VI_IDs'] and c['Han_Start'] is not None]
    score = score_list(entry)
    whole = [c['Score'] for c in paired if c['Validation_Status']=='mapped' and type(c['Score']) in (float,int)
             and math.isfinite(c['Score']) and c['Han_Start']==job['h'][0][0] and c['Han_End']==job['h'][-1][1]
             and set(c['VI_IDs']) == set(job['source_vi'])]
    hc = Counter(k for c in paired for k in range(c['Han_Start'],c['Han_End']))
    vc = Counter((key,k) for c in paired for key,a,b in c['VI_Char_Spans'] for k in range(a,b))
    hi, vi = sum(b-a for a,b in job['h']), sum(len(source[k]) for k in set(job['source_vi']))
    body = json.loads(entry['raw_response']) if entry['status']=='success' else {}
    api = body.get('data',{}).get('result',[])
    changes = [c for f in job['fragments'] for c in f['changes']]
    metrics = dict(response_id=entry['id'],status=entry['status'],latency_ms=entry['latency_ms'],cached=entry['cached'],
                   raw_bilingual_score_max=max(score,default=None), full_window_score=whole[0] if len(whole)==1 else None,
                   han_chars=hi,vi_chars=vi,han_covered=len(hc),vi_covered=len(vc),
                   han_coverage=len(hc)/hi if entry['status']=='success' else None,
                   vi_coverage=len(vc)/vi if entry['status']=='success' else None,
                   han_duplicate_chars=sum(n>1 for n in hc.values()),vi_duplicate_chars=sum(n>1 for n in vc.values()),
                   unresolved=sum(c['Validation_Status'] in robust.UNRESOLVED for c in candidates),
                   fallback_rows=sum('fallback' in c['VI_Resolution'] for c in candidates),
                   whitespace_aggregations=sum(len(c['Source_Rows'])>1 for c in rows),
                   fragment_count=len(job['fragments']), number_changes=len(changes),
                   invalid_vi_index=0, number_cut_count=0, groups=dict(Counter(c['Alignment_Type'] for c in paired)))
    texts = job['payload']['vi'].split('\n')
    for item in api:
        if not isinstance(item,dict):
            continue
        a,b = item.get('vi_start'),item.get('vi_end')
        if not (type(a) is type(b) is int and (a==b==-1 or 0<=a<=b<len(texts))):
            metrics['invalid_vi_index'] += 1
        # The old whitespace-only resolver may recognize clipped tokens that
        # robust mapping deliberately rejects; this is diagnostic only.
        proj, _ = base.resolve(texts,a,b,item.get('vietnamese_text'))
        metrics['number_cut_count'] += sum(any(t.start()<edge<t.end() for edge in (x,y))
                                            for i,x,y in proj for t in NUM.finditer(texts[i]))
    return dict(job=job, metrics=metrics, candidates=rows, api_rows=candidates, raw_scores=score, status=entry['status'])


def evaluate(runs, silver):
    scope = []
    for r in runs:
        j,m = r['job'],r['metrics']
        if r['status']=='success' and not (j['stage']=='E07' and j.get('kind')!='corresponding'):
            scope.append(dict(job={**j,'v':j['source_vi']}, status=r['status'], candidates=r['candidates']))
    pairs, _ = base.evaluate(scope,silver)
    counters = defaultdict(list)
    for p in pairs:
        counters[p['Experiment_ID']].append(p)
    for r in runs:
        rows = counters[r['job']['id']]
        m = r['metrics']
        m.update(eligible=len(rows), exact_cg=sum(p['Exact_ChatGPT'] for p in rows),
                 exact_ds=sum(p['Exact_DeepSeek'] for p in rows),
                 agreed_eligible=sum(p['Agreed_Reference'] for p in rows),
                 exact_agreed=sum(p['Agreed_Reference'] and p['Exact_ChatGPT'] for p in rows),
                 iou_cg=stats.mean(p['IoU_ChatGPT'] for p in rows) if rows else None,
                 iou_ds=stats.mean(p['IoU_DeepSeek'] for p in rows) if rows else None)
    return pairs


def describe(values):
    return dict(n=len(values),min=min(values,default=None),max=max(values,default=None),
                median=stats.median(values) if values else None,values=values)


def discrimination(runs, score_key):
    main = [r for r in runs if r['job']['stage']=='E07' and not r['job']['repeat_of']]
    pos = {r['job']['pair']:r for r in main if r['job']['kind']=='corresponding'}
    results = {}
    for group in ('hard','distant','all_negatives'):
        neg = [n for n in main if n['job']['kind'] in ({'hard','distant'} if group=='all_negatives' else {group})]
        matched=[]
        for n in neg:
            p = pos.get(n['job']['pair'])
            if p:
                a,b = (r['metrics'][score_key] for r in (p,n))
                matched.append(dict(pair=n['job']['pair'],kind=n['job']['kind'],positive=a,negative=b,
                                    provisional=p['job']['provisional'],vi_lengths=[p['metrics']['vi_chars'],n['metrics']['vi_chars']],
                                    outcome=('missing' if a is None or b is None else 'win' if a>b else 'loss' if a<b else 'tie')))
        pp = [m['positive'] for m in matched if m['positive'] is not None]
        nn = [m['negative'] for m in matched if m['negative'] is not None]
        auc = stats.mean((p>n)+0.5*(p==n) for p in pp for n in nn) if pp and nn else None
        results[group] = dict(corresponding=describe(pp),negative=describe(nn),auc_descriptive=auc,
                              within_han=dict(Counter(m['outcome'] for m in matched)),matched=matched,
                              provisional_only=dict(Counter(m['outcome'] for m in matched if m['provisional'])),
                              matched_length_subset=dict(Counter(m['outcome'] for m in matched
                                                        if max(m['vi_lengths'])/min(m['vi_lengths']) <= 1.5)))
    return results


def order_summary(runs, h, v):
    out=[]
    for r in runs:
        j=r['job']
        if j['stage']!='E08':
            continue
        i=j['window']; semantic=0; positional=0
        for c in r['candidates']:
            if c['Validation_Status']!='mapped' or len(c['VI_IDs'])!=1:
                continue
            span = [c['Han_Start'],c['Han_End']]
            if span in h[i:i+2]:
                k = h[i:i+2].index(span)
                semantic += c['VI_IDs'][0]==v[i+k]
                positional += c['VI_IDs'][0]==j['source_vi'][k]
        out.append(dict(job=j['id'],reverse=j['reverse'],reference_id_matches=semantic,positional_matches=positional,
                        groups=r['metrics']['groups'],score=r['raw_scores'],han_coverage=r['metrics']['han_coverage'],
                        vi_coverage=r['metrics']['vi_coverage'],status=r['status']))
    return out


def context_summary(runs):
    summary={}
    for k in ('12x12','2x2'):
        variants=[r for r in runs if r['job']['id'].startswith('E11-'+k) and r['status']=='success']
        counts=Counter()
        for r in variants:
            counts.update(r['metrics']['groups'])
        summary[k]=dict(windows=len(variants), groups=dict(counts),
                        nm_fraction=counts['N-M']/sum(counts.values()) if counts else None,
                        exact_cg=sum(r['metrics']['exact_cg'] for r in variants),exact_ds=sum(r['metrics']['exact_ds'] for r in variants),
                        eligible=sum(r['metrics']['eligible'] for r in variants))
    return summary


def followups(runs, fix):
    """Test whether a ranking inversion survives another call, and add a reversal if needed."""
    raw,_,source,_,h,v,_=fix
    findings=discrimination(runs,'full_window_score')['all_negatives']['matched']
    losses=[m for m in findings if m['outcome']=='loss']
    if losses:
        loss=max(losses,key=lambda m:m['negative']-m['positive'])
        for r in runs:
            j=r['job']
            if j['stage']=='E07' and j['pair']==loss['pair'] and j['kind'] in ('corresponding',loss['kind']):
                yield {**j,'id':j['id']+'-repeat','repeat_of':j['id']}
    rev=[o for o in order_summary(runs,h,v) if o['reverse'] and o['status']=='success']
    if rev and any(o['reference_id_matches'] != 2 for o in rev):
        for reverse in (False,True):
            yield make_job('E08','07-08-'+('reverse' if reverse else 'normal'),h[6:8],v[6:8][::-1] if reverse else v[6:8],
                           raw,source,window=6,reverse=reverse)
    if sum(discrimination(runs,'full_window_score')['all_negatives']['matched_length_subset'].values()) < 6:
        # Additional length-controlled hard probes, reported separately.
        for i,k,reason in ((3,4,'fixed allowances and taxes versus Thang Hoa levy totals'),
                           (4,3,'Thang Hoa levy totals versus fixed allowances and taxes'),
                           (7,8,'license and related payments versus seal/office payments'),
                           (8,7,'seal/office payments versus license and related payments')):
            yield make_job('E07',f'length-probe-{i+1:02}',[h[i]],[v[k]],raw,source,kind='length_probe',
                           pair=f'PILOT-{i+1:03}',basis=reason)


def repeat_probe_inversion(runs):
    pos={r['job']['pair']:r for r in runs if r['job'].get('kind')=='corresponding' and not r['job']['repeat_of']}
    for r in runs:
        j=r['job']
        if j.get('kind')!='length_probe' or j['repeat_of']:
            continue
        p=pos[j['pair']]
        a,b=p['metrics']['full_window_score'],r['metrics']['full_window_score']
        if a is not None and b is not None and b>a:
            for original in (p['job'],j):
                yield {**original,'id':original['id']+'-repeat','repeat_of':original['id']}
            return


def worksheet(wb,name,headers,rows):
    ws=wb.create_sheet(name)
    ws.append(headers)
    for row in rows:
        ws.append([base.dump(x) if isinstance(x,(tuple,list,dict)) else x for x in row])
        for c in ws[ws.max_row]:
            if c.data_type=='f':
                c.data_type='s'
    ws.freeze_panes='C2' if len(headers)>2 else 'A2'
    ws.auto_filter.ref=ws.dimensions
    for c in ws[1]:
        c.font=Font(bold=True,color='FFFFFF'); c.fill=PatternFill('solid',fgColor='203A56')
        ws.column_dimensions[get_column_letter(c.column)].width=48 if any(k in c.value.lower() for k in ('text','payload','basis')) else min(28,max(12,len(c.value)+2))
    return ws


def export(out,runs,pairs,source,silver):
    wb=Workbook(); wb.remove(wb.active)
    keys=list(dict.fromkeys(k for r in runs for k in r['metrics']))
    worksheet(wb,'Requests',['Job','Stage','Kind','Silver_Han_Query','Basis','Han_Payload','VI_Payload','Input_VI_IDs',*keys],
              ([j['id'],j['stage'],j.get('kind'),j.get('pair'),j.get('basis'),j['payload']['han'],j['payload']['vi'],j['source_vi'],
                *(r['metrics'].get(k) for k in keys)] for r in runs for j in (r['job'],)))
    pair_keys=list(dict.fromkeys(k for p in pairs for k in p)) if pairs else ['Experiment_ID','Pair_ID','VI_ID','Predicted_Han','Vietnamese']
    worksheet(wb,'Boundary comparison',pair_keys,([p.get(k) for k in pair_keys] for p in pairs))
    worksheet(wb,'VI Fragments',['Job','ID','VI_ID','Start','End','Payload_Text','Source_Text','Number_Changes'],
              ([r['job']['id'],f['id'],f['vi_id'],f['start'],f['end'],f['text'],source[f['vi_id']][f['start']:f['end']],f['changes']]
               for r in runs for f in r['job']['fragments']))
    candidate_keys=['Experiment_ID','API_Response_ID','Row','Source_Rows','Validation_Status','Alignment_Type','Score',
                    'Han_Start','Han_End','Han_Text','VI_IDs','VI_Char_Spans','Vietnamese_Text','Han_Resolution','VI_Resolution']
    all_candidates=[c for r in runs for c in r['candidates']]
    worksheet(wb,'Output groups',candidate_keys,([c.get(k) for k in candidate_keys] for c in all_candidates))
    worksheet(wb,'Silver references',['Pair_ID','VI_ID','Han_Text','VI_Text','ChatGPT_Span','DeepSeek_Span','Provisional_Label'],
              ([s['Pair_ID'],s['VI_ID'],s['Chinese'],s['Vietnamese'],s['han_link']['global_raw_span'],
                s['comparison']['deepseek_han_link']['global_raw_span'],s['Label_Target']] for s in silver))
    wb.save(out/'comparison.xlsx')

    wb=Workbook(); wb.remove(wb.active)
    # Deduplicate the actual review text/spans. Keep provenance on a separate
    # worksheet so reviewers working from their own sheet aren't shown scores.
    review, provenance = {},[]
    for c in all_candidates:
        if c['Validation_Status'] in robust.UNRESOLVED:
            continue
        key=base.dump([c['Han_Start'],c['Han_End'],c['VI_Char_Spans']])
        ref=review.setdefault(key, (f'REVIEW-{len(review)+1:03}',c))
        provenance.append([ref[0],c['Experiment_ID'],c['API_Response_ID'],c['Source_Rows'],c['Score'],c['Validation_Status']])
    cols=['Review_ID','Han_Text','Vietnamese_Text','Han_Start','Han_End','VI_IDs','VI_Char_Spans','Alignment_Type',
          'OMISSION','ADDITION','MISSING','OCR_Uncertainty','Label_Target','Notes']
    for reviewer in ('ChatGPT','DeepSeek'):
        worksheet(wb,reviewer,cols,([ref,c['Han_Text'],c['Vietnamese_Text'],c['Han_Start'],c['Han_End'],c['VI_IDs'],
                                    c['VI_Char_Spans'],c['Alignment_Type'],None,None,None,None,None,None] for ref,c in review.values()))
    worksheet(wb,'Provenance',['Review_ID','Job','Response_ID','API_Rows','Score','Mapping_Status'],provenance)
    wb.save(out/'semantic_review.xlsx')
    return len(review)


def summarize(runs, entries, halt, fix, review_n):
    raw,_,_,_,h,v,_=fix
    stages={}
    for stage in ('E07','E08','E09','E10','E11'):
        rr=[r for r in runs if r['job']['stage']==stage]
        sent=[e for e in entries if not e['cached'] and e['job']['stage']==stage]
        stages[stage]=dict(jobs=len(rr), statuses=dict(Counter(r['status'] for r in rr)), requests=len(sent),
                           cached=sum(r['metrics']['cached'] for r in rr),
                           live_median_ms=stats.median(e['latency_ms'] for e in sent) if sent else None)
    numeric=[{'job':r['job']['id'],**r['metrics']} for r in runs if r['job']['stage']=='E09']
    seg=[{'job':r['job']['id'],**r['metrics']} for r in runs if r['job']['stage']=='E10']
    repeat=[{'job':r['job']['id'],'original':r['job']['repeat_of'],'score':r['metrics']['full_window_score'],
             'original_score':next((a['metrics']['full_window_score'] for a in runs if a['job']['id']==r['job']['repeat_of']),None)}
            for r in runs if r['job']['repeat_of']]
    pos={r['job']['pair']:r['metrics'] for r in runs if r['job'].get('kind')=='corresponding'}
    length_probes=[]
    for r in runs:
        if r['job'].get('kind')=='length_probe' and not r['job']['repeat_of']:
            m=pos[r['job']['pair']]; a=m['full_window_score']; b=r['metrics']['full_window_score']
            length_probes.append(dict(pair=r['job']['pair'], candidate=a, negative=b,
                                      length_ratio=max(m['vi_chars'],r['metrics']['vi_chars'])/min(m['vi_chars'],r['metrics']['vi_chars']),
                                      outcome='missing' if a is None or b is None else 'win' if a>b else 'loss' if a<b else 'tie'))
    return dict(requests=sum(not e['cached'] for e in entries),halt=halt,stages=stages,review_groups=review_n,
                primary_discrimination=discrimination(runs,'full_window_score'),
                raw_score_sensitivity=discrimination(runs,'raw_bilingual_score_max'), order=order_summary(runs,h,v),
                numbers=numeric,segmentation=seg,context=context_summary(runs),repeated=repeat,length_probes=length_probes,
                score_definition='Primary: one traceable, full-window bilingual output with an API score; missing otherwise.',
                semantic_review_complete=False)


def build_report(data):
    f=lambda x: '—' if x is None else f'{x:.3f}'
    lines=['# Alignment API experiment E07–E11', '',
           f"**{data['requests']} live requests.** Status: {data['halt'] or 'completed planned pilot and applicable follow-ups'}.", '',
           '| Experiment | Jobs | Live requests | Reused | Status | Median live latency (ms) |', '|---|---:|---:|---:|---|---:|']
    for k,m in data['stages'].items():
        lines.append(f"| {k} | {m['jobs']} | {m['requests']} | {m['cached']} | {m['statuses']} | {m['live_median_ms']} |")
    lines += ['', '## E07 — Can score separate corresponding and non-corresponding inputs?', '',
              'Primary score is available only if a unique scored output covers both full inputs. Missing scores are not zero. '
              'Scores below compare Silver candidate pairings, not semantically verified labels. AUC is descriptive, with half credit for ties.', '',
              '| Mismatches | Candidate / negative medians | Candidate / negative ranges | AUC | Within same Han | Provisional positives only |',
              '|---|---|---|---:|---|---|']
    for k,m in data['primary_discrimination'].items():
        a,b=m['corresponding'],m['negative']
        lines.append(f"| {k} | {f(a['median'])} / {f(b['median'])} | {f(a['min'])}–{f(a['max'])} / {f(b['min'])}–{f(b['max'])} | "
                     f"{f(m['auc_descriptive'])} | {m['within_han']} | {m['provisional_only']} |")
    raw=data['raw_score_sensitivity']['all_negatives']; m=data['primary_discrimination']['all_negatives']
    lines += ['', f"Raw max-score sensitivity: AUC {f(raw['auc_descriptive'])}, within-Han {raw['within_han']}. "
              f"Primary subset with Vietnamese length ratio ≤1.5: {m['matched_length_subset']}. This is a sensitivity check, not causal length control.",
              f"Additional length-matched hard probes: {dict(Counter(p['outcome'] for p in data['length_probes']))}. "
              'Reported separately from the original 24 requests; see the individual scores and length ratios in `metrics.json`.',
              f"Deliberate repeats: {data['repeated'] or 'none'}. See `metrics.json` for all individual scores and missing values.", '',
              '## E08 — Sensitivity to Vietnamese order', '',
              '| Job | Matches by original VI ID | Matches by input position | Groups | Scores | Han / VI coverage |',
              '|---|---:|---:|---|---|---:|']
    for r in data['order']:
        lines.append(f"| {r['job']} | {r['reference_id_matches']} | {r['positional_matches']} | {r['groups']} | "
                     f"{r['score']} | {f(r['han_coverage'])} / {f(r['vi_coverage'])} |")
    lines += ['', '## E09 — Number normalization', '',
              '| Job | Invalid VI indices | Text fallback rows | Unresolved rows | Number cuts detected | Groups |',
              '|---|---:|---:|---:|---:|---|']
    for r in data['numbers']:
        lines.append(f"| {r['job']} | {r['invalid_vi_index']} | {r['fallback_rows']} | {r['unresolved']} | {r['number_cut_count']} | {r['groups']} |")
    lines += ['', 'Only source-confirmed single-dot thousands and unambiguous dot grouping are removed in the outgoing payload. '
              'Decimals and ambiguous single-dot tokens are preserved. Invalid VI indices are measured against submitted lines. '
              'Detected number cuts are a lower bound from matchable snippets; altered whitespace can prevent exact detection.', '',
              '## E10 — Vietnamese segmentation, Han fixed at S4', '',
              '| Strategy | Fragments | Status | Exact CG / DS | Agreed | IoU CG / DS | Han / VI coverage | Unresolved |',
              '|---|---:|---|---:|---:|---:|---:|---:|']
    for r in data['segmentation']:
        lines.append(f"| {r['job']} | {r['fragment_count']} | {r['status']} | {r['exact_cg']}/{r['eligible']} / {r['exact_ds']}/{r['eligible']} | "
                     f"{r['exact_agreed']}/{r['agreed_eligible']} | {f(r['iou_cg'])} / {f(r['iou_ds'])} | "
                     f"{f(r['han_coverage'])} / {f(r['vi_coverage'])} | {r['unresolved']} |")
    lines += ['', 'Fragments are projected back to source IDs before evaluation. Single-ID chains may cross whitespace-only gaps. '
              'The scorecard does not mark a mapped N–M group wrong in meaning merely because it differs from individual Silver references.', '',
              '## E11 — Context and merging', '', '| Input | Successful windows | Groups | N–M share | Exact CG / DS |',
              '|---|---:|---|---:|---:|']
    for k,r in data['context'].items():
        lines.append(f"| {k} | {r['windows']} | {r['groups']} | {f(r['nm_fraction'])} | {r['exact_cg']}/{r['eligible']} / {r['exact_ds']}/{r['eligible']} |")
    common=data['context_common_12x12']; numeric={r['job']:r for r in data['numbers']}
    old=[v for k,v in numeric.items() if k.endswith('-source') and v['status']=='success']
    new=[v for k,v in numeric.items() if k.endswith('-normalized') and v['status']=='success']
    viable=[r for r in data['segmentation'] if r.get('iou_cg') is not None and r.get('iou_ds') is not None]
    ranking=sorted(viable,key=lambda r:(-(r['iou_cg']+r['iou_ds']),r['fragment_count']))
    pref=ranking[0]['job'] if ranking else 'undetermined'
    lines += ['', 'The 2×2 context baseline uses historical payloads with identical number normalization, including the paired E09 runs.',
              f"On the {common['n']} references available under both sizes, 12×12 has {common['exact_cg']} CG / {common['exact_ds']} DS exact matches. "
              'This compares one long context to six particular windows; it is not a claim about all larger inputs.', '',
              '## Findings and design decisions', '',
              f"1. **Score discrimination:** {m['within_han']} in the main paired test; descriptive AUC {f(m['auc_descriptive'])}. "
              f"Length-controlled follow-ups produced {dict(Counter(p['outcome'] for p in data['length_probes']))}. "
              'Score overlap and Silver uncertainty rule out adopting a universal threshold from this pilot.',
              f"2. **Numbers:** out-of-range VI index rows {sum(r['invalid_vi_index'] for r in old)} → "
              f"{sum(r['invalid_vi_index'] for r in new)}; text fallback rows {sum(r['fallback_rows'] for r in old)} → "
              f"{sum(r['fallback_rows'] for r in new)} across the paired controls. The observed alignment group types stayed the same.",
              f"3. **Default Vietnamese segmentation:** {pref} by mean reference IoU (ties broken by fewer fragments). "
              'Additional segmentation is an option for local repair, rather than a default meant to maximize raw coverage.',
              '4. **Order:** inspect original VI_ID, not position. Reversed windows returned joint groups rather than recovering '
              'singleton crossings in the observed successful reversals. A joint group can retain high coverage and a high score while '
              'hiding which individual passages correspond. This does not by itself establish semantic error for the whole group.',
              '5. **DP:** do not use the raw score as the sole transition cost or compare 1–1 and N–M scores as if calibrated. '
              'If used at all initially, compare a score-free baseline to a modest score feature normalized within transition shape and length.',
              '6. **Pipeline:** use page-anchored windows, Hán S4 as an initial baseline, source Vietnamese IDs, number protection, '
              'reversible mapping, multiple candidate boundaries, and monotone alignment with explicit skip and N–M transitions. '
              'Review counterexamples and low-confidence outputs before scaling.', '',
              '## DP and pipeline decision', '',
              'Preserve source text; use protected number normalization and reversible fragment offsets. Generate local candidates from '
              'page anchors and multiple Hán boundaries, then apply mapping integrity checks, monotonicity and no-overlap checks. '
              'Keep N–M and skip transitions available. Treat the API score as a candidate feature only until it shows reliable '
              'within-passage ranking against independently reviewed negatives and against simpler baselines. Never infer a semantic label '
              f"from API success, score or reference boundary match. `semantic_review.xlsx` has {data['review_groups']} distinct review groups; labels are blank."]
    return '\n'.join(lines)+'\n'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,default=OUT)
    p.add_argument('--dry-run',action='store_true'); p.add_argument('--resume',action='store_true')
    p.add_argument('--delay',type=float,default=0.8); p.add_argument('--timeout',type=float,default=40)
    p.add_argument('--retries',type=int,default=1)
    a=p.parse_args(); a.request_budget=None
    if a.delay<0 or a.timeout<=0 or a.retries<0:
        p.error('Invalid delay, timeout or retry count')
    fix=fixture(); raw,_,source,silver,*_=fix
    work=list(jobs(fix)); old=history()
    if a.dry_run:
        for j in work:
            print(j['id'],len(j['h']),len(j['v']),'cached' if j['key'] in old else 'planned')
        print('No requests sent.')
        return 0
    if a.output.exists() and not a.resume:
        p.error('Output exists; use --resume or choose a new directory')
    token=os.getenv('SINONOM_TOKEN','').strip()
    if token.lower().startswith('bearer '): token=token[7:].strip()
    if not token: p.error('Set SINONOM_TOKEN')
    runner=Runner(a,token,old); runs=[]
    try:
        for j in work:
            r=run_one(runner,j,raw,source)
            if r: runs.append(r)
            if runner.halt: break
        if not runner.halt:
            for j in list(followups(runs,fix)):
                r=run_one(runner,j,raw,source)
                if r: runs.append(r)
                if runner.halt: break
        if not runner.halt:
            for j in list(repeat_probe_inversion(runs)):
                r=run_one(runner,j,raw,source)
                if r: runs.append(r)
                if runner.halt: break
    finally:
        runner.close()
    pairs=evaluate(runs,silver)
    for pair in pairs:
        key=pair['Pair_ID']
        if pair['Experiment_ID']=='E11-12x12':
            pair['Available_in_2x2'] = any(p['Pair_ID']==key and p['Experiment_ID'].startswith('E11-2x2') for p in pairs)
    # Resume keeps append-only request data, regenerating derived workbooks/report.
    review_n=export(a.output,runs,pairs,source,silver)
    data=summarize(runs,runner.entries,runner.halt,fix,review_n)
    common=[p for p in pairs if p.get('Available_in_2x2')]
    data['context_common_12x12']=dict(n=len(common),exact_cg=sum(p['Exact_ChatGPT'] for p in common),
                                      exact_ds=sum(p['Exact_DeepSeek'] for p in common))
    for f,obj in [('results.json',{'runs':runs,'pair_comparison':pairs}),('metrics.json',data),('report.md',None)]:
        path=a.output/f; tmp=path.with_suffix('.tmp')
        tmp.write_text(build_report(data) if obj is None else json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        tmp.replace(path)
    print(f"{a.output}: {data['requests']} live requests; halt={data['halt']}")
    return int(bool(runner.halt))


if __name__=='__main__':
    raise SystemExit(main())
