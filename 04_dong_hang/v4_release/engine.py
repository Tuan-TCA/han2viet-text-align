"""Conservative multi-context repair. No reference groups enter the decoder."""
from collections import defaultdict
import re

def normalize(text):
    """Canonicalize isolated VI thousands tokens; preserve all source slices."""
    dots=set()
    for m in re.finditer(r'(?<![\w.,/:-])\d{1,3}(?:\.\d{3})+(?![\w/:-]|[.,]\d)',text):dots.update(i for i in range(*m.span()) if text[i]=='.')
    ix=[i for i in range(len(text)) if i not in dots];ranges=list(zip(ix,ix[1:]+[len(text)]));assert ''.join(text[a:b] for a,b in ranges)==text
    return ''.join(text[i] for i in ix),ranges

def signature(g):return g['Han_Start'],g['Han_End'],tuple(tuple(x) for x in g['VI_Char_Spans'])
def mapped(g):return g['Validation_Status'] in ('mapped','partial_viet') and g['Han_Start'] is not None and bool(g['VI_Char_Spans'])
def conflict(g,h,order):
    if h['Han_Start']<g['Han_Start']:g,h=h,g
    return g['Han_End']>h['Han_Start'] or max((order[k],b) for k,a,b in g['VI_Char_Spans'])>min((order[k],a) for k,a,b in h['VI_Char_Spans'])

def refine(primary,probes,raw,vi,config):
    order={k:i for i,k in enumerate(primary['ids'])};bounds={p for span in primary['han'] for p in span};weights=config['weights'];pool=defaultdict(list);ledger=[]
    chosen=list(primary['baseline']);numerals='零〇一二三四五六七八九十百千萬億兩壹貳參肆伍陸柒捌玖拾佰仟'
    for r in probes:
        for g in r['baseline']:
            if mapped(g) and set(g['VI_IDs'])<=order.keys():pool[signature(g)].append(g)
    proposals=[]
    for key,rows in pool.items():
        g=rows[0];a,b,parts=key;keys=sorted({x['Request_Key'] for x in rows});ids=g['VI_IDs'];txt=normalize(g['Vietnamese_Text'])[0];h=raw[a:b];nums=set(re.findall(r'\d+',txt))&set(re.findall(r'\d+',h));entities=set(re.findall('[A-Z][a-zA-Z]+',txt))&set(re.findall('[A-Z][a-zA-Z]+',h));edges=sum(p in bounds for p in (a,b));rank=weights['context_support']*len(keys)+weights['aligned_boundary']*edges+weights['shared_numeric']*bool(nums)+weights['shared_entity']*bool(entities)+weights['api_score']*(g.get('API_Score') or 0)
        protected=any(p not in bounds and 0<p<len(raw) and ((raw[p-1] in numerals and raw[p] in numerals) or (raw[p-1:p+1].isascii() and raw[p-1:p+1].isalnum())) for p in (a,b));reason=None
        if g['Validation_Status']!='mapped' or h!=g['Han_Text'] or not all(vi[k]['text_original'][x:y]==vi[k]['text_original'] for k,x,y in parts):reason='partial or inconsistent source'
        elif [order[k] for k in ids]!=list(range(order[ids[0]],order[ids[-1]]+1)):reason='intervening VI ID'
        elif protected:reason='protected expression'
        elif len(keys)<config['minimum_distinct_payloads']:reason='single payload'
        proposals.append((rank,key,g,keys,reason))
    # Split a complete N-M block only when corroborated partitions tile BOTH
    # axes exactly. Alternate partitions are left for review instead of taking
    # whichever request happened to finish first.
    eligible=[p for p in proposals if p[-1] is None];starts=defaultdict(list)
    for p in eligible:starts[p[1][0]].append(p)
    for parent in list(chosen):
        if not mapped(parent) or len(parent['VI_IDs'])<2:continue
        a,b,target=signature(parent);paths=[]
        def walk(pos,i,path):
            if pos==b and i==len(target):
                if len(path)>1:paths.append(path)
                return
            for p in starts[pos]:
                x,y,parts=p[1];n=len(parts)
                if pos<y<=b and parts==target[i:i+n] and p[1]!=(a,b,target) and len(paths)<2:walk(y,i+n,path+[p])
        walk(a,0,[])
        if len(paths)==1 and not any(x is not parent and mapped(x) and conflict(parent,x,order) for x in chosen):
            chosen.remove(parent)
            for rank,key,g,keys,_ in paths[0]:
                chosen.append({**g,'Correction_Type':'split'});ledger.append(dict(operation='split',before=[signature(parent)],after=key,distinct_requests=keys,rank=rank,intra_s4=[p for p in key[:2] if p not in bounds],disposition='applied',Label_Target='UNKNOWN'))
    for rank,key,g,keys,reason in sorted(proposals,key=lambda x:(-x[0],x[1])):
        rivals=[x for x in chosen if mapped(x) and conflict(g,x,order)];same=[x for x in rivals if signature(x)==key];op='gap_recovery' if not rivals else 'boundary_or_vi_reassignment';a,b,_=key
        if same:reason='already present' if len(rivals)==1 else 'duplicate or order conflict; keep alternatives'
        if not reason and rivals:
            # Keep every meaningful character and VI fragment already assigned.
            spans=sorted((x['Han_Start'],x['Han_End']) for x in rivals)
            if any(x<a or y>b for x,y in spans) or any(y>x2 or raw[y:x2].strip() for (_,y),(x2,_) in zip(spans,spans[1:])):reason='would cross gap, overlap or displace text'
            elif not all(set(x['VI_IDs'])<=set(g['VI_IDs']) for x in rivals):reason='would displace Vietnamese source'
            elif any(x['Validation_Status']=='mapped' for x in rivals):reason='competing full mapping; abstain'
        if not reason:
            chosen=[x for x in chosen if x not in rivals]+[{**g,'Correction_Type':op}]
        ledger.append(dict(operation=op,before=[signature(x) for x in rivals],after=key,distinct_requests=keys,rank=rank,intra_s4=[p for p in (a,b) if p not in bounds],disposition=reason or 'applied',Label_Target='UNKNOWN'))
    chosen.sort(key=lambda x:(x['Han_Start'] is None,x['Han_Start'] or 0));return chosen,ledger
