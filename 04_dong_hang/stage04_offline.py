"""Isolated S4-T1 replay and source-cue experiments; no network transport."""
from collections import Counter, defaultdict
import json
import re
import subprocess

from openpyxl import load_workbook

from stage04_inputs import ROOT, CAP, load, hashes, read_jsonl, normalize
from stage04_candidates import project, reconcile
from stage04_export import workbook
from benchmark_alignment_api_v2 import alignment_type
from preprocess import write_json


STAGE = ROOT/'04_dong_hang/artifacts'
BASE = STAGE/'stage04'
OUT = STAGE/'stage04_offline'
REVIEW = ROOT/'Semantic_Gold_Review_verified_v2.xlsx'
HAN_PDF = ROOT/'01_nguon/Cap_01/HAN.pdf'
VI_PDF = ROOT/'01_nguon/Cap_01/VIET.pdf'
EXPECTED = {'N-1':9,'1-1':4,'1-N':1,'N-M':1}

# Small, source-inspected bilingual lexicon for this experiment, not a trained
# or held-out model. Patterns include frozen OCR variants; no offsets/IDs.
STARTS = (
    ('certificate_fee', r'如有受[照憑]', r'Như có lệ nộp tiền lĩnh bằng'),
    ('seal_fee', r'有印', r'Có lệ nộp tiền ấn'),
    ('selection', r'[順慣]廣選[揚場]', r'Tuyển trường'),
    ('duy_xuyen', r'川人阮金[珠朱]', r'Người ở Duy Xuyên là Nguyễn Kim Châu'),
    ('minh_lanh', r'明[灵靈]縣人楊伯錫', r'Người huyện Minh Lành là Dương Bá Tích'),
    ('phu_chau', r'富洲人陳文[情清]', r'Người ở Phú Châu là Trần Văn Tình'),
)
ENDINGS = (('memorial_day',r'諱日亦照',r'ngày k[ỵyị] cũng thế[.!]?$'),)
CNUM = re.compile(r'[零〇一二兩三四五六七八九十百千萬]+')
VNUM = re.compile(r'\d+(?:\.\d{3})*(?![\d.,])')


def sheets(path):
    w = load_workbook(path,read_only=True,data_only=True)
    try:
        result = {}
        for s in w:
            vals = iter(s.values); fields = next(vals)
            result[s.title] = [dict(zip(fields,r)) for r in vals if any(x is not None for x in r)]
        return result
    finally:
        w.close()


def canonical(value):
    return json.loads(json.dumps(value,ensure_ascii=False))


def replay(f):
    source = [e for e in read_jsonl(BASE/'requests.jsonl') if e['job']['id']=='S4-T1-frozen-original'
              and e['status']=='success' and not e['cached']]
    if len(source)!=1:
        raise ValueError('Expected one original S4-T1 response')
    e, = source
    resolved = reconcile(project(e['job'],e,f['raw'],f['vi']),{k:i for i,k in enumerate(f['pool'])})
    api_rows = json.loads(e['raw_response'])['data']['result']
    baseline = resolved['selected']
    published = [r for r in sheets(BASE/'alignment_results.xlsx')['Alignment_Dataset'] if r['Experiment_ID']=='S4-T1']
    assert len(api_rows)==len(published)==len(baseline)==15 and not resolved['unresolved']
    for g,r in zip(baseline,published,strict=True):
        for k in ('Han_Start','Han_End','Han_Text','Vietnamese_Text','Validation_Status','Alignment_Type','API_Response_ID'):
            if g[k]!=r[k]:
                raise ValueError(f'Baseline mismatch in {r["Pair_ID"]}/{k}')
        for k in ('VI_IDs','Han_IDs','VI_Char_Spans','Source_Rows','VI_Source_Rows','Occurrences'):
            if canonical(g[k]) != json.loads(r[k]):
                raise ValueError(f'Baseline provenance mismatch in {r["Pair_ID"]}/{k}')
        assert g['Original_API_Rows']==[api_rows[x['row']] for x in g['Source_Rows']]
        a,b = g['Han_Start'],g['Han_End']
        assert f['raw'][a:b]==g['Han_Text']
        assert ' '.join(f['vi'][k]['text_original'][a:b] for k,a,b in g['VI_Char_Spans'])==g['Vietnamese_Text']
        g.update(Pair_ID=r['Pair_ID'], Original_Pair_IDs=[r['Pair_ID']], Correction_Reason='frozen S4-T1')
    assert Counter(g['Alignment_Type'] for g in baseline)==EXPECTED
    assert Counter(g['Validation_Status'] for g in baseline)=={'mapped':13,'partial_viet':2}
    return baseline,e,api_rows


def label(value):
    if isinstance(value,bool):
        return 'TRUE' if value else 'FALSE'
    return str(value or 'UNKNOWN').strip().upper()


def bind_review(review,baseline):
    rows = {r['Pair_ID']:r for r in review['API_Row_Review']}
    assert len(rows)==len(baseline)==15
    for g in baseline:
        r=rows[g['Pair_ID']]
        assert [r['Han_Start'],r['Han_End']]==[g['Han_Start'],g['Han_End']]
        assert [k.strip() for k in r['VI_IDs'].split(',')]==g['VI_IDs']
        g.update(Semantic_Assessment=label(r['Proposed_Label']), Reviewer_Label=r['Reviewer_Label'],
                 Confidence=r['Confidence'], Assessment_Origin='provisional row-level review')
    return rows


def spans(g):
    return g['Han_Start'],g['Han_End']


def intervals(positions):
    out=[]
    for p in sorted(positions):
        if out and out[-1][1]==p:
            out[-1][1]+=1
        else:
            out.append([p,p+1])
    return out


def occupancy(groups,f,scope,ids):
    raw=f['raw']; vi=f['vi']; h=Counter(); v=defaultdict(Counter)
    for g in groups:
        a,b=spans(g); assert scope[0]<=a<b<=scope[1]
        h.update(range(a,b))
        for k,x,y in g['VI_Char_Spans']:
            assert k in ids and 0<=x<y<=len(vi[k]['text_original'])
            v[k].update(range(x,y))
    hg=intervals(set(range(*scope))-h.keys())
    vg={k:intervals(set(range(len(vi[k]['text_original'])))-v[k].keys()) for k in ids}
    vd=sum(max(0,n-1) for vals in v.values() for n in vals.values())
    return dict(han_chars=len(h),vi_chars=sum(map(len,v.values())), han_duplicate_chars=sum(max(0,n-1) for n in h.values()),
                vi_duplicate_chars=vd,han_gaps=[{'span':[a,b],'text':raw[a:b]} for a,b in hg],
                vi_gaps={k:[{'span':[a,b],'text':vi[k]['text_original'][a:b]} for a,b in ranges] for k,ranges in vg.items() if ranges})


def row_refs(chain):
    return sorted({(r['response'],r['row']) for g in chain for r in g['Source_Rows']})


def continuity(chain,raw):
    if not chain or any(a>=b for a,b in map(spans,chain)) or any(not g['Source_Rows'] for g in chain):
        return 'INVALID_SPAN'
    refs=row_refs(chain)
    if len({r for r,_ in refs})!=1 or [n for _,n in refs]!=list(range(refs[0][1],refs[-1][1]+1)):
        return 'SKIPPED_OR_DIFFERENT_API_ROW'
    if any(max(n for _,n in row_refs([a]))>=min(n for _,n in row_refs([b])) for a,b in zip(chain,chain[1:])):
        return 'REVERSED_OR_REPEATED_API_ROW'
    for a,b in zip(chain,chain[1:]):
        x,y=a['Han_End'],b['Han_Start']
        if x>y:
            return 'HAN_OVERLAP'
        if raw[x:y].strip():
            return 'MEANINGFUL_HAN_GAP'
    return None


def make_group(f,a,b,parts,chain,reason):
    vi=f['vi']; raw=f['raw']; hs=[s for s in f['han'] if s['global_raw_span'][0]<b and s['global_raw_span'][1]>a]
    assert hs and a<b and hs[0]['global_raw_span'][0]<=a and b<=hs[-1]['global_raw_span'][1]
    ids=list(dict.fromkeys(k for k,_,_ in parts))
    original_ids=list(dict.fromkeys(k for g in chain for k in g['Original_Pair_IDs']))
    def vn(k,x,y):
        return intervals(i for i,(lo,hi) in enumerate(vi[k]['t1_offsets']) if lo<y and hi>x)
    assert all(k in vi and 0<=x<y<=len(vi[k]['text_original']) for k,x,y in parts)
    return dict(Pair_ID=f'offline:{a}-{b}:'+','.join(ids),Original_Pair_IDs=original_ids,Cap=CAP,Han_Start=a,Han_End=b,
                Han_Text=raw[a:b],Han_IDs=[s['id_zh'] for s in hs],Han_Source_Spans=[{
                    'id':s['id_zh'],'raw_span':[max(a,s['global_raw_span'][0]),min(b,s['global_raw_span'][1])],
                    'normalized_index_spans':intervals(i for i,(x,y) in enumerate(s['normalized_source_spans']) if x<b and y>a),
                    'source':s['source']} for s in hs],
                VI_IDs=ids,VI_Char_Spans=parts,VI_Normalized_Spans=[(k,vn(k,x,y)) for k,x,y in parts],
                VI_Source_Rows=[vi[k]['source'] for k in ids],Vietnamese_Text=' '.join(vi[k]['text_original'][x:y] for k,x,y in parts),
                Alignment_Type=alignment_type(len(hs),len(ids)),Validation_Status='offline_source_backed',
                Source_Rows=[{'response':r,'row':n} for r,n in row_refs(chain)],Correction_Reason=reason,
                Semantic_Assessment='UNKNOWN',Confidence='STRUCTURAL CUE ONLY',Reviewer_Label=None,
                Assessment_Origin='changed group; no independently adjudicated semantic label')


def aggregate(f,chain):
    issue=continuity(chain,f['raw'])
    if issue:
        return None,issue
    parts=[p for g in chain for p in g['VI_Char_Spans']]
    ks={k for k,_,_ in parts}
    if len(chain)<2 or len(ks)!=1:
        return None,'MIXED_OR_AMBIGUOUS_VI_IDS'
    key=next(iter(ks)); text=f['vi'][key]['text_original']
    if any(not 0<=a<b<=len(text) for _,a,b in parts):
        return None,'INVALID_VI_SPAN'
    for (_,a,b),(_,x,y) in zip(parts,parts[1:]):
        if b>x or text[b:x].strip():
            return None,'VI_OVERLAP_OR_MEANINGFUL_GAP'
    if text[:parts[0][1]].strip() or text[parts[-1][2]:].strip():
        return None,'INCOMPLETE_VI_UNIT'
    return make_group(f,chain[0]['Han_Start'],chain[-1]['Han_End'],[(key,0,len(text))],chain,
                      'Consecutive API rows cover the same VI segment and have no meaningful gap'),None


def chinese_int(text):
    digits=dict(zip('零一二三四五六七八九',range(10)))|{'〇':0,'兩':2}
    units={'十':10,'百':100,'千':1000}; total=partial=0; digit=None
    for c in text:
        if c in digits:
            digit=digits[c]
        elif c in units:
            partial+=(1 if digit is None else digit)*units[c]; digit=None
        elif c=='萬':
            total+=(partial+(digit or 0) or 1)*10000; partial=0; digit=None
    return total+partial+(digit or 0)


def totals(han,viet):
    # Matching an Arabic transcription to an explicit Han sum cue is only a boundary feature.
    v=list(VNUM.finditer(viet)); target={int(m[0].replace('.','')) for m in v[-6:]}
    return sorted({chinese_int(m[0]) for m in CNUM.finditer(han) if chinese_int(m[0])>=100}&target)


def vi_whole(f,k):
    return [(k,0,len(f['vi'][k]['text_original']))]


def lex_hits(han,offset,viet,patterns=STARTS):
    found=[]
    for name,h,v in patterns:
        if not re.search(v,viet.strip(),re.I):
            continue
        for m in re.finditer(h,han):
            # OCR omitted the first character of this place name in some sources.
            a=m.start()
            if name=='duy_xuyen' and a and han[a-1] in '濰雜潍維':
                a-=1
            found.append((offset+a,offset+m.end(),name))
    return found


def recovery(f,left,right):
    raw=f['raw']; a,b=spans(left); c,d=spans(right)
    if b>=c or not raw[b:c].strip():
        return []
    found=[]; adjacent=row_refs((left,right))
    if len(adjacent)!=2 or adjacent[0][0]!=adjacent[1][0] or adjacent[1][1]!=adjacent[0][1]+1:
        return []
    if len(left['VI_IDs'])==1 and left['Validation_Status']=='mapped':
        matches=totals(raw[b:c],left['Vietnamese_Text'])
        if '共' in raw[b:c] and len(matches)>=2 and not any(n in totals(raw[b:c],right['Vietnamese_Text']) for n in matches):
            found.append(('recover_suffix',make_group(f,a,c,left['VI_Char_Spans'],[left,right],f'Adjacent uncovered totals match VI numbers {matches}')))
    if len(right['VI_IDs'])==1 and right['Validation_Status']=='mapped':
        cues=lex_hits(raw[b:c],b,right['Vietnamese_Text']); starts=[name for x,_,name in cues if x==b]
        if len(cues)==len(starts)==1:
            found.append(('recover_prefix',make_group(f,b,d,right['VI_Char_Spans'],[left,right],f'Adjacent uncovered prefix has bilingual opening cue: {starts[0]}')))
    return found


def split_candidates(f,left,right):
    """Transfer a prefix only if each adjacent translation has a unique boundary cue."""
    a,b=spans(left); c,d=spans(right)
    if b!=c or len(left['VI_IDs'])!=1 or len(right['VI_IDs'])!=1 or continuity([left,right],f['raw']):
        return []
    if left['VI_IDs']==right['VI_IDs']:
        return []
    raw=f['raw']; result=[]
    ending=lex_hits(raw[c:d],c,left['Vietnamese_Text'],ENDINGS)
    if len(ending)==1 and ending[0][0]==c and ending[0][1]<d:
        _,cut,name=ending[0]
        opens=lex_hits(raw[cut:d],cut,right['Vietnamese_Text'])
        if len(opens)==1 and opens[0][0]==cut:
            result.append((cut,f'{name} closes preceding VI; {opens[0][2]} opens following VI'))
    opening=lex_hits(raw[c:d],c,right['Vietnamese_Text'])
    if len(opening)==1 and c<opening[0][0]<d:
        cut,_,name=opening[0]
        # Cross-boundary repeated phrases are weak unless the right start is diagnostic.
        if '各船社坊' in raw[c:cut] and re.search('các thuy[ềể]n',left['Vietnamese_Text'],re.I):
            result.append((cut,f'{name} marks the following fee; boats/certificates close the previous fee'))
    return [(make_group(f,a,cut,left['VI_Char_Spans'],[left,right],why),
             make_group(f,cut,d,right['VI_Char_Spans'],[right],why)) for cut,why in result]


def split_mixed(f,g):
    """Protect valid N–M: split only at unique, ordered bilingual opening anchors for every VI unit."""
    ids=g['VI_IDs']; a,b=spans(g); h=f['raw'][a:b]
    if len(ids)<2 or [tuple(p) for p in g['VI_Char_Spans']] != [vi_whole(f,k)[0] for k in ids]:
        return None
    found=[lex_hits(h,a,f['vi'][k]['text_original']) for k in ids]
    if any(len(hits)!=1 for hits in found):
        return None
    cuts=[hits[0][0] for hits in found]+[b]
    if cuts[0]!=a or any(x>=y for x,y in zip(cuts,cuts[1:])):
        return None
    return [make_group(f,x,y,vi_whole(f,k),[g],'Unique ordered bilingual entry anchors')
            for k,x,y in zip(ids,cuts,cuts[1:])]


def reassign(f,chain,scope):
    issue=continuity(chain,f['raw'])
    if issue:
        return None,issue
    start=chain[0]; a=start['Han_Start']; b=chain[-1]['Han_End']; raw=f['raw']
    if len(start['VI_IDs'])!=1 or start['Validation_Status'] not in ('partial_viet','offline_source_backed'):
        return None,'NO_UNAMBIGUOUS_PARTIAL_START'
    key,=start['VI_IDs']; kindex=f['pool'].index(key); vi=f['vi']; text=vi[key]['text_original']
    if key not in chain[1]['VI_IDs'] or not re.search(r'\bcộng\b',text,re.I):
        return None,'NO_REPEATED_TARGET_OR_CLOSING_TOTAL'
    starts=lex_hits(raw[a:b],a,text)
    if len(starts)!=1 or starts[0][0]!=a:
        return None,'NO_UNIQUE_TARGET_OPENING'
    if any(f['pool'].index(k)<kindex for g in chain for k in g['VI_IDs']):
        return None,'VI_ORDER_CONFLICT'
    next_key=f['pool'][kindex+1]
    next_hits=lex_hits(raw[a:b],a,vi[next_key]['text_original'])
    if len(next_hits)!=1 or not a<next_hits[0][0]<b:
        return None,'NO_UNIQUE_SUCCESSOR_ENTITY'
    cut,_,cue=next_hits[0]
    ending=raw[max(a,cut-35):cut]; nums=totals(ending,text)
    if not nums or '共' not in ending or cut<=chain[-1]['Han_Start']:
        return None,'NO_CLOSING_TOTAL_AT_TRANSITION'
    if b!=scope[1]:
        return None,'SUCCESSOR_SCOPE_NOT_ESTABLISHED'
    group=make_group(f,a,cut,vi_whole(f,key),chain,
                     f'Contiguous fragments; opening, closing total {nums}, and distinct following entity ({cue})')
    return group,None


def variants(f,base,scope):
    log=[]; all_variants={'V0':base}

    def record(variant,operation,old,new,reason):
        log.append(dict(Variant=variant,Operation=operation,Decision='selected' if new else 'rejected',
                        Reason=reason,Original=[x['Pair_ID'] for x in old],Source_Rows=row_refs(old),Candidates=new))

    for variant in ('V1','V2','V3'):
        groups=list(base)
        if variant=='V3':
            for i in range(len(groups)-1):
                a,b=groups[i:i+2]
                if a['Han_End']>=b['Han_Start']:
                    continue
                found=recovery(f,a,b)
                if len(found)==1:
                    op,g=found[0]; groups[i+(op=='recover_prefix')]=g
                    record(variant,op,[a,b],[g],g['Correction_Reason'])
                else:
                    record(variant,'recover_gap',[a,b],[],'NO_UNIQUE_SOURCE_CUE')
        if variant in ('V2','V3'):
            for i in range(len(groups)-1):
                a,b=groups[i:i+2]; found=split_candidates(f,a,b)
                if len(found)==1:
                    groups[i:i+2]=found[0]
                    record(variant,'split_transfer',[a,b],list(found[0]),found[0][0]['Correction_Reason'])
                elif len(found)>1:
                    record(variant,'split_transfer',[a,b],[],'AMBIGUOUS_CUT; alternatives retained')
                    log[-1]['Rejected_Alternatives']=found
            rewritten=[]
            for g in groups:
                if len(g['VI_IDs'])>1:
                    new=split_mixed(f,g)
                    record(variant,'split_mixed',[g],new or [],'UNIQUE_ORDERED_OPENINGS' if new else 'NO_SAFE_CUT; group retained')
                    rewritten.extend(new or [g])
                else:
                    rewritten.append(g)
            groups=rewritten
        if variant in ('V1','V3'):
            i=0
            while i+1<len(groups):
                key=groups[i]['VI_IDs']
                if len(key)!=1 or key[0] not in groups[i+1]['VI_IDs']:
                    i+=1; continue
                end=i+2
                while end<len(groups) and key[0] in groups[end]['VI_IDs']:
                    end+=1
                old=groups[i:end]; new,why=aggregate(f,old)
                record(variant,'aggregate',old,[new] if new else [],why or new['Correction_Reason'])
                if new:
                    groups[i:end]=[new]; i+=1
                    continue
                if variant=='V3' and end<len(groups):
                    old=groups[i:]; fixed,why=reassign(f,old,scope)
                    record(variant,'aggregate_reassign',old,[fixed] if fixed else [],why or fixed['Correction_Reason'])
                    if fixed:
                        groups[i:]=[fixed]
                i=end
        all_variants[variant]=groups
    return all_variants,log


def refs_from(review,f,scope):
    # Do not select among competing proposed boundaries. These are provisional
    # source-candidate references linked to whole VI workbook rows, not gold.
    refs={}
    for r in review['Corrected_Groups']:
        text=r['Candidate_Han_Span'] or ''
        m=re.fullmatch(r'\s*\[(\d+),\s*(\d+)\)\s*(?:candidate)?\s*',text)
        k=r['VI_ID']
        if not m or k not in f['vi']:
            continue
        a,b=map(int,m.groups())
        if not scope[0]<=a<b<=scope[1]:
            raise ValueError(f'Candidate reference outside scope: {k}')
        refs[k]={'Han':[a,b],'VI':[0,len(f['vi'][k]['text_original'])],'Assessment':r['Assessment']}
    return refs


def score(f,groups,refs,scope,ids):
    cov=occupancy(groups,f,scope,ids); total_h=scope[1]-scope[0]; total_v=sum(len(f['vi'][k]['text_original']) for k in ids)
    rows=[]
    for key,ref in refs.items():
        matching=[g for g in groups if key in g['VI_IDs']]; a,b=ref['Han']; x,y=ref['VI']
        hs={n for g in matching for n in range(*spans(g))}; vs={n for g in matching for k,c,d in g['VI_Char_Spans'] if k==key for n in range(c,d)}
        htarget=set(range(a,b)); vtarget=set(range(x,y))
        rows.append(dict(VI_ID=key,Reference_Han=ref['Han'],Reference_VI=ref['VI'],Target_Type='provisional whole VI workbook segment',
                         Han_Exact=hs==htarget and all(g['VI_IDs']==[key] for g in matching),VI_Exact=vs==vtarget,
                         Han_IoU=len(hs&htarget)/len(hs|htarget),VI_IoU=len(vs&vtarget)/len(vs|vtarget),
                         Han_Predicted=intervals(hs),VI_Predicted=intervals(vs)))
    labels=Counter(g['Semantic_Assessment'] for g in groups)
    return dict(**cov,groups=len(groups),mapping_status=dict(Counter(g['Validation_Status'] for g in groups)),
                han_coverage=cov['han_chars']/total_h,vi_coverage=cov['vi_chars']/total_v,
                uncovered_han_chars=total_h-cov['han_chars'],uncovered_vi_chars=total_v-cov['vi_chars'],
                alignment_types=dict(Counter(g['Alignment_Type'] for g in groups)),
                provisional_semantic={s:labels[s] for s in ('TRUE','FALSE','UNKNOWN')},
                unknown_rate=labels['UNKNOWN']/len(groups), verified_semantic_matches=None, verified_semantic_accuracy=None,
                incorrect_automatic_corrections=None, changed_groups=sum(g['Validation_Status']=='offline_source_backed' for g in groups),
                reference_count=len(rows),han_exact=sum(r['Han_Exact'] for r in rows),vi_exact=sum(r['VI_Exact'] for r in rows),
                han_mean_iou=sum(r['Han_IoU'] for r in rows)/len(rows),vi_mean_iou=sum(r['VI_IoU'] for r in rows)/len(rows),references=rows)


def pdf_text(path,first,last):
    data=subprocess.check_output(['pdftotext','-f',str(first),'-l',str(last),'-enc','UTF-8',str(path),'-'])
    return data.decode('utf-8')


def case_checks(f,base,variants_):
    """Forensic checks; case coordinates are diagnostics only, never rule inputs."""
    raw=f['raw']; pdf=normalize(pdf_text(VI_PDF,186,190))[0]; pdf188=normalize(pdf_text(VI_PDF,188,188))[0]
    p3=next(p for p in f['pages'] if p['cap']==CAP and p['han_pdf_page']==3)
    assert not pdf_text(HAN_PDF,1,3).strip(), 'Han text-layer assumptions changed'
    by_id={g['Pair_ID']:g for g in base}; vi=f['vi']
    repeats=[]
    for n in (8,9):
        g=by_id[f'S4-T1-{n:03}']; k,=g['VI_IDs']; text=vi[k]['text_original']
        m=re.search(r'các thuy[ềể]n.*?đổi bằng mới[^.]+\.',text,re.I)
        assert m
        hit=list(re.finditer(re.escape(m[0]),pdf188)); assert len(hit)==1
        repeats.append(dict(VI_ID=k,Workbook_span=list(m.span()),Workbook_row=vi[k]['source'],
                            PDF_page=188,PDF_normalized_span=list(hit[0].span()),Text=m[0]))
    distinct=repeats[0]['PDF_normalized_span'][1]<repeats[1]['PDF_normalized_span'][0]
    assert distinct
    assert 'ngày ky cũng thế.' in pdf and raw[727:731]=='諱日亦照'
    # Locate next cases by PDF text and raw OCR markers; the numerical text starts on Han p.3.
    continuation=[]
    for name,h,v in STARTS[-3:]:
        m=re.search(h,raw[881:p3['global_raw_span'][1]]); n=re.search(v,pdf,re.I)
        assert m and n
        a=881+m.start(); a-=int(name=='duy_xuyen' and raw[a-1] in '濰雜潍維')
        continuation.append(dict(Cue=name,Han_Start=a,Han_Page=2 if a<p3['global_raw_span'][0] else 3,
                                 Han_Text=raw[a:881+m.end()],VI_PDF_normalized_span=list(n.span()),VI_Text=n[0]))
    def candidate(k):
        return [list(spans(g)) for g in variants_['V3'] if g['VI_IDs']==[k]]
    ids=lambda n:by_id[f'S4-T1-{n:03}']['VI_IDs'][0]
    return [dict(Case='A',Result=f'Detected and proposed {candidate(ids(3))}; totals 278, 213, 2727 support the continuation.',
                 Han_Intervals=[[55,166],[166,213]],Han_Evidence=raw[166:213],Semantic_Assessment='UNKNOWN'),
            dict(Case='B',Result=f'Proposed {candidate(ids(8))}. Scan/OCR places 有印 at 545; 547 cuts after 有印 inside the next seal-fee opening. The repeated tail and OCR prevent semantic adjudication.',
                 Han_Intervals=[[372,396],[531,545],[545,547]],Han_Evidence=raw[531:558],Semantic_Assessment='UNKNOWN'),
            dict(Case='C',Result='Two distinct matches on the same VI PDF page under different fee descriptions; not a duplicate workbook offset or segmentation overlap. Their Han allocation and completeness remain uncertain.',
                 PDF_Matches=repeats,Semantic_Assessment='UNKNOWN'),
            dict(Case='D',Result=f'Baseline [664,727) preserved. Separate candidate {candidate(ids(11))}; the scan puts the memorial-day clause immediately before the selection passage.',
                 Han_Intervals=[[664,727],[727,731]],Han_Evidence='諱日亦照',VI_Evidence='ngày ky cũng thế.',Semantic_Assessment='UNKNOWN'),
            dict(Case='E',Result=f'Combined proposal {candidate(ids(12))}; [893,905) starts a new case. The shared closing total is structural evidence; component OCR amounts still require adjudication.',
                 Han_Intervals=[[731,893],[893,905]],Han_Evidence=raw[881:905],Semantic_Assessment='UNKNOWN'),
            dict(Case='F',Result='Scan and OCR show Duy Xuyên/Đông Xuân continuing on page 3, then Minh Lành and Phú Châu. Do not align these VI rows wholly to Han pages 1–2.',
                 Continuation=continuation,Han_Page_3_Span=p3['global_raw_span'],Han_Evidence=raw[905:950],Semantic_Assessment='UNKNOWN')]


def comparison(base, variant_groups, rows):
    by_id={g['Pair_ID']:g for g in base}; out=[]
    for variant,groups in variant_groups.items():
        for g in groups:
            old=[by_id[k] for k in g['Original_Pair_IDs']]
            out.append(dict(Variant=variant,Original_Pair_IDs=g['Original_Pair_IDs'],
                Original_Han='\n'.join(x['Han_Text'] for x in old),
                Original_Vietnamese='\n'.join(x['Vietnamese_Text'] for x in old),Original_Han_Spans=[spans(x) for x in old],
                Original_VI_IDs=[x['VI_IDs'] for x in old],Original_VI_Spans=[x['VI_Char_Spans'] for x in old],
                Original_Alignment_Types=[x['Alignment_Type'] for x in old],Original_Source_Rows=[x['Source_Rows'] for x in old],
                Original_Mapping_Status=[x['Validation_Status'] for x in old],Original_Proposed_Labels=[rows[x['Pair_ID']]['Proposed_Label'] for x in old],
                Refined_Pair_ID=g['Pair_ID'],Refined_Han=g['Han_Text'],Refined_Vietnamese=g['Vietnamese_Text'],Refined_Han_Span=spans(g),
                Refined_VI_IDs=g['VI_IDs'],Refined_VI_Spans=g['VI_Char_Spans'],Refined_Alignment_Type=g['Alignment_Type'],
                Refined_Mapping_Status=g['Validation_Status'],Source_Rows=g['Source_Rows'],Correction_Reason=g['Correction_Reason'],
                Semantic_Assessment=g['Semantic_Assessment'],Assessment_Origin=g['Assessment_Origin'],
                Confidence=g['Confidence'],Reviewer_Label=g['Reviewer_Label']))
    return out


def conservation(groups,f,scope,ids,cov):
    """Every in-scope original character appears once, aligned or explicitly unresolved."""
    h=Counter(); v=defaultdict(Counter)
    for g in groups:
        a,b=spans(g); h.update(range(a,b)); assert g['Han_Text']==f['raw'][a:b]
        text=[]
        for k,x,y in g['VI_Char_Spans']:
            text.append(f['vi'][k]['text_original'][x:y]); v[k].update(range(x,y))
        assert ' '.join(text)==g['Vietnamese_Text']
    for gap in cov['han_gaps']:
        a,b=gap['span']; h.update(range(a,b)); assert gap['text']==f['raw'][a:b]
    for k,gaps in cov['vi_gaps'].items():
        for gap in gaps:
            a,b=gap['span']; v[k].update(range(a,b)); assert gap['text']==f['vi'][k]['text_original'][a:b]
    if h!=Counter(range(*scope)) or any(v[k]!=Counter(range(len(f['vi'][k]['text_original']))) for k in ids):
        raise ValueError('Source conservation failed')


def report(path,metrics,cases,readme):
    m=metrics['variants']; n=m['V0']['reference_count']
    lines=['# Stage 04 — Offline Semantic Alignment Experiment','',
           'The 15 published S4-T1 groups were replayed exactly from the original saved response, including spans, text, VI assignments, mapping states and API-row provenance. No API access or resegmentation was used. The workbook and frozen source hashes passed the before/after check.','',
           f'Row-level provisional labels: **5 TRUE, 7 FALSE, 3 UNKNOWN**. All 15 reviewer labels are blank. The review Readme instead says “{readme}” This discrepancy was retained.','',
           '| Variant | Groups | Han / VI coverage | Uncovered Han / VI chars | Duplicate Han / VI chars | Han / VI exact | Han / VI mean IoU | TRUE / FALSE / UNKNOWN | Selected / rejected operations |',
           '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for key,v in m.items():
        t=v['provisional_semantic']
        lines.append(f"| {key} | {v['groups']} | {v['han_coverage']:.1%} / {v['vi_coverage']:.1%} | "
                     f"{v['uncovered_han_chars']} / {v['uncovered_vi_chars']} | {v['han_duplicate_chars']} / {v['vi_duplicate_chars']} | "
                     f"{v['han_exact']}/{n} / {v['vi_exact']}/{n} | {v['han_mean_iou']:.3f} / {v['vi_mean_iou']:.3f} | "
                     f"{t['TRUE']} / {t['FALSE']} / {t['UNKNOWN']} | {v['correction_operations']} / {v['rejected_corrections']} |")
    lines+=['','V1 = aggregation alone; V2 = splitting and boundary transfer; V3 = both, with the E02 uncovered-span recovery cues enabled. '
            'The V3 delta therefore includes gap recovery; it is not attributable to aggregation alone. Selected operations can be intermediate steps; `changed_groups` counts final changed groups.',
            '',f'Boundary metrics use {n} single, parseable proposed Han spans from `Corrected_Groups` and full original VI workbook slices. Ambiguous alternatives and cross-window references are excluded. '
            'Per-ID IoU unions the covered code points; Han exact also rejects extra VI IDs. VI exact measures character coverage of that ID, not whether the Han assignment is correct. '
            'Han denominator: the frozen two-page OCR window. VI denominator: all original VI IDs submitted in the frozen API request, including the four continuation IDs.',
            '', 'Alignment types, mapping status and UNKNOWN proportions:']
    for key,v in m.items():
        lines.append(f"- **{key}**: types `{v['alignment_types']}`; mapping `{v['mapping_status']}`; UNKNOWN {v['unknown_rate']:.1%}.")
    lines+=['','## Cases A–F','']
    lines += [f"- **{x['Case']}.** {x['Result']}" for x in cases]
    lines+=['','Han PDF scans 1–3 were rendered and visually inspected locally. Scan evidence establishes ordering and visible transitions; OCR remains the offset authority and numerical readings are not independently adjudicated. '
            'Vietnamese evidence uses the PDF text layer (physical pp. 186–190) and exact slices from `CAU_VIET`; stored PDF offsets refer to whitespace-normalized extraction, not PDF byte coordinates.',
            '','## What the experiment established','',
            '1. **Detection is deterministic; attribution is not.** The baseline gaps are visible without labels. Matching the adjacent totals makes Case A a strong recovery hypothesis; a gap alone could be genuine source-only text.',
            '2. **Source cues can propose local splits.** Case D has corroboration on both sides. Case B has a fee-transition cue at 545, but the competing 547 reference and repeated content prevent treating either boundary as verified. The original group was never overwritten.',
            '3. **Aggregation alone could not repair Case E.** Consecutive Han rows were insufficient: the API introduced additional VI IDs. The combined method used the opening, total and successor name to propose one N–1 passage and kept the residual Han and VI text in the unresolved ledger.',
            '4. **N–M shape is not evidence of an error.** The mixed-group splitter abstained when it could not trace a unique ordered opening for every VI segment. The terminal N–M group was changed only after a separate source-backed reassignment hypothesis; the code has no general semantic N–M discriminator.',
            '5. **Coverage trade-off.** V3 gains in-window Han coverage but reduces aligned Vietnamese coverage when it releases page-3 continuation IDs. Exact reconstruction of aligned plus unresolved text passed; the lower VI coverage is an explicit abstention, not deletion.',
            '6. **Semantic improvement and incorrect-correction rates are undetermined.** Original provisional assessments are carried only for unchanged groups. Every new group is UNKNOWN; a drop in provisional FALSE counts is not a gain in semantic accuracy.',
            '7. **Production recommendation.** Consider the deterministic provenance, gap/duplicate inventory, and continuity validators after review. Keep boundary proposals, entity/number checks and reassignment in review mode. The small bilingual cue list was written after inspecting these pages, so these are diagnostic, in-sample results.',
            '8. **Before a corpus run**, obtain independent group-level reviews of both original and changed passages, adjudicate OCR quantities (particularly Cases A and E) and the seal-fee boundary, and test on held-out pages from both Caps with valid N–M examples and cross-page continuations.',
            '', 'Finished at the offline experiment gate; no production integration.']
    path.write_text('\n'.join(lines)+'\n',encoding='utf-8')


def main():
    f=load()
    files=[REVIEW,HAN_PDF,VI_PDF,BASE/'requests.jsonl',BASE/'alignment_results.xlsx',
           ROOT/'02_ocr_tho/Cap_01/HAN/pages/Cap01-003.json']
    tracked=[*f['tracked'],*files]; before=hashes(tracked)
    if any(before[k]!=v for k,v in f['before'].items()):
        raise ValueError('Source changed while binding inputs')
    base,e,api_rows=replay(f); reviews=sheets(REVIEW); review_rows=bind_review(reviews,base)
    baseline_labels=Counter(g['Semantic_Assessment'] for g in base)
    assert baseline_labels=={'TRUE':5,'FALSE':7,'UNKNOWN':3} and all(g['Reviewer_Label'] is None for g in base)
    readme=next(r['Description'] for r in reviews['Readme'] if r['Item']=='API-row summary')
    scope=[e['job']['h'][0][0],e['job']['h'][-1][1]]; ids=e['job']['v']
    all_variants,log=variants(f,base,scope); refs=refs_from(reviews,f,scope)
    cases=case_checks(f,base,all_variants); scores={}
    for key,groups in all_variants.items():
        s=score(f,groups,refs,scope,ids); conservation(groups,f,scope,ids,s)
        s['correction_operations']=sum(x['Variant']==key and x['Decision']=='selected' for x in log)
        s['rejected_corrections']=sum(x['Variant']==key and x['Decision']=='rejected' for x in log)
        scores[key]=s
    detail=comparison(base,all_variants,review_rows); review_export=[r for r in detail if r['Variant'] in ('V0','V3')]
    case_fields=list(dict.fromkeys(k for r in cases for k in r)); log_fields=['Variant','Operation','Decision','Reason','Original','Source_Rows','Candidates','Rejected_Alternatives']
    boundary=[{'Variant':k,**r} for k,s in scores.items() for r in s['references']]
    unresolved=[dict(Variant=k,Side='Han',**g) for k,s in scores.items() for g in s['han_gaps']]
    unresolved.extend(dict(Variant=k,Side='VI',VI_ID=i,**g) for k,s in scores.items() for i,gs in s['vi_gaps'].items() for g in gs)
    workbook(OUT,'comparison.xlsx',[('Comparison',list(detail[0]),detail),('Boundary_Evaluation',list(boundary[0]),boundary),
             ('Correction_Log',log_fields,log),('Unresolved',['Variant','Side','VI_ID','span','text'],unresolved)])
    workbook(OUT,'semantic_review.xlsx',[('Semantic_Review',list(detail[0])+['Reviewer_Notes'],review_export),
             ('Cases_A_to_F',case_fields,cases),('Original_Source_Checks',list(reviews['Source_Checks'][0]),reviews['Source_Checks']),
             ('Review_Readme',['Item','Description'],reviews['Readme'])])
    if hashes(tracked)!=before:
        raise RuntimeError('An original input changed during the experiment')
    meta=dict(scope=scope,vi_ids=ids,input_sha256=before,hashes_unchanged=True,offline=True,
              baseline_response=e['id'],review_readme_tally=readme,baseline_provisional_labels=dict(baseline_labels))
    write_json(OUT/'baseline_reconstruction.json',{**meta,'groups':base,'original_api_rows':api_rows,'exact_replay':True})
    write_json(OUT/'refined_alignment.json',{**meta,'variants':all_variants,'source_checks':cases,
                 'unresolved':{k:{field:s[field] for field in ('han_gaps','vi_gaps')} for k,s in scores.items()}})
    write_json(OUT/'correction_log.json',{'operations':log,'case_checks':cases})
    metrics={**meta,'variants':scores,'workbooks_validated':True,'source_conservation_validated':True}
    write_json(OUT/'metrics.json',metrics)
    report(OUT/'report.md',metrics,cases,readme)
    print(f'Offline replay verified: {len(base)} groups; {len(log)} operations evaluated; outputs at {OUT.relative_to(ROOT)}')


if __name__=='__main__':
    main()
