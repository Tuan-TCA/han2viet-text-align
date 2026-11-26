"""Source projection, conservative reconciliation and local Han hypotheses."""
from collections import defaultdict

from stage04_inputs import han_unit, merge_units
from benchmark_alignment_api_v2 import aggregate_candidates, alignment_type, parse_robust
from benchmark_alignment_api_final import full_segment


def project(job, response, raw, vi):
    rows = parse_robust(job, response, raw, strict=True)
    t1 = {k: vi[k]['text_t1'] for k in job['v']}
    groups = aggregate_candidates(rows, raw, t1, allow_han_whitespace=True)
    out = []
    for c in groups:
        parts = []
        for k, a, b in c['VI_Char_Spans']:
            r = vi[k]; offsets = r['t1_offsets']
            parts.append((k, 0 if a == 0 else offsets[a][0],
                          len(r['text_original']) if b == len(offsets) else offsets[b-1][1]))
        ids = list(dict.fromkeys(h for i in c['Han_Units'] for h in job['han_ids_by_line'][i]))
        source = {k:vi[k]['text_original'] for k in c['VI_IDs']}
        status = c['Validation_Status']
        if status in ('mapped','partial_viet'):
            status = 'mapped' if all(full_segment(parts,k,source) for k in c['VI_IDs']) else 'partial_viet'
        out.append({**c,'Cap':job['cap'], 'Han_IDs':ids, 'VI_Payload_Spans':c['VI_Char_Spans'],
                    'VI_Char_Spans':parts, 'Vietnamese_Text':' '.join(source[k][a:b] for k,a,b in parts),
                    'Alignment_Type':alignment_type(len(ids),len(c['VI_IDs'])), 'Validation_Status':status,
                    'Source_Rows':[{'response':response['id'],'row':n} for n in c['Source_Rows']],
                    'VI_Source_Rows':[vi[k]['source'] for k in c['VI_IDs']], 'Request_Key':job['key'],
                    'Context_Evidence':job.get('context_evidence', 0),
                    'API_Score':c['Score'], 'Label_Target':'UNKNOWN','Review_Status':'PENDING_INDEPENDENT_REVIEW'})
    return out


def identity(c):
    return (c['Cap'],c['Han_Start'],c['Han_End'],tuple(tuple(p) for p in c['VI_Char_Spans']))


def incompatible(a,b,vi_order):
    if a['Cap'] != b['Cap']:
        return False
    if b['Han_Start'] < a['Han_Start']:
        a,b = b,a
    return (a['Han_End'] > b['Han_Start'] or
            max((vi_order[k], y) for k,_,y in a['VI_Char_Spans']) >
            min((vi_order[k], x) for k,x,_ in b['VI_Char_Spans']))


def reconcile(groups, vi_order):
    buckets = defaultdict(list); unresolved = []
    for g in groups:
        if g['Validation_Status'] not in ('mapped','partial_viet'):
            unresolved.append(g)
        else:
            buckets[identity(g)].append(g)
    unique = []
    for entries in buckets.values():
        first = entries[0]
        unique.append({**first, 'Occurrences':[{k:g[k] for k in ('Experiment_ID','API_Response_ID','Source_Rows','Request_Key','Original_API_Rows')} for g in entries],
                       'Support':len({g['Request_Key'] for g in entries}),
                       'Context_Evidence':max(g.get('Context_Evidence',0) for g in entries)})
    conflicts = []; neighbors = defaultdict(set)
    for i,a in enumerate(unique):
        for j in range(i+1,len(unique)):
            if incompatible(a, unique[j], vi_order):
                neighbors[i].add(j); neighbors[j].add(i)
    # Resolve only with a strict integrity/corroboration advantage. API score is never a tiebreaker.
    def quality(g):
        return g['Validation_Status']=='mapped', g['Support'], g['Context_Evidence']
    selected = []
    for i,g in enumerate(unique):
        rivals = neighbors[i]
        if all(quality(g) > quality(unique[j]) for j in rivals):
            selected.append(g)
        if rivals:
            conflicts.append({**g,'Disposition':'selected' if g in selected else 'alternative',
                              'Competing_Spans':[identity(unique[j]) for j in sorted(rivals)]})
        if g not in selected and not any(quality(unique[j]) > quality(g) for j in rivals):
            unresolved.append({**g,'Reason':'COMPETING_BOUNDARIES'})
    return dict(selected=sorted(selected,key=lambda g:(g['Cap'],g['Han_Start'],g['Han_End'])),
                unresolved=unresolved, conflicts=conflicts, duplicates=sum(len(v)-1 for v in buckets.values()),
                conflict_edges=sum(map(len,neighbors.values()))//2)


def alternatives(segments, groups, raw):
    """Generate reversible split/merge alternatives only near observed defects."""
    units = [han_unit(s) for s in segments]
    for i,s in enumerate(segments):
        a,b = s['global_raw_span']; local = [g for g in groups if g['Han_Start'] is not None
                                             and g['Han_Start'] < b and g['Han_End'] > a]
        if local and all(g['Validation_Status']=='mapped' and not g['Han_Partial_Unit'] for g in local):
            continue
        cuts = {p for g in local for p in (g['Han_Start'],g['Han_End']) if a < p < b}
        spans = s['normalized_source_spans']
        available = [x for x in range(1,len(spans)) if spans[x-1][1] == spans[x][0]
                     and 0 < x < len(s['text_zh']) and
                     (spans[x][0] in cuts or s['text_zh'][x-1] in '，、；：。')]
        for x in available:
            if s['text_zh'][:x].strip() and s['text_zh'][x:].strip():
                yield 'split', units[:i]+[han_unit(s,0,x),han_unit(s,x)]+units[i+1:]
        if i+1 < len(units):
            try:
                merged = merge_units(units[i],units[i+1],raw)
            except ValueError:
                continue
            yield 'merge', units[:i]+[merged]+units[i+2:]
    # A move is a merge of the right fragment of one original unit with the next.
        if available and i+1 < len(units):
            x = available[0]
            try:
                left,right = han_unit(s,0,x),han_unit(s,x)
                moved = merge_units(right,units[i+1],raw)
            except ValueError:
                continue
            yield 'move', units[:i]+[left,moved]+units[i+2:]
