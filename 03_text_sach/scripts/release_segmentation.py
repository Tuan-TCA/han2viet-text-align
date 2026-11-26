"""Density variants use raw Unicode code-point cuts. No evaluation references here."""
import re
import unicodedata
from candidate_boundaries import ENTITIES,HAN_NUM,s4
from preprocess import content, audit_partition

METHODS=('S4','S5','S6','S7','S8','S9')


def partition(raw, projected, method):
    if method not in METHODS or not projected: raise ValueError('Method and verified Separate response required')
    ends={0,len(raw)}; punctuation={}; conflicts=[]
    for row in projected:
        a,b=row['global_raw_span']; ends.add(b)
        idx=[i for i in range(a,b) if content(raw[i])]; n=0
        if content(row['text_api'])!=content(raw[a:b]): raise ValueError('Projection mismatch')
        for ch in row['text_api']:
            if content(ch): n+=1
            elif n and unicodedata.category(ch).startswith('P'):
                punctuation.setdefault(idx[n-1]+1,set()).add(ch)
    protected={i for match in HAN_NUM.finditer(raw) for i in range(match.start()+1,match.end())}
    for term in ENTITIES:
        for match in re.finditer(term,raw): protected.update(range(match.start()+1,match.end()))
    if method=='S4': cuts=set(s4(raw,projected))
    elif method in ('S5','S6'):
        cuts=set(ends); gap={'S5':8,'S6':5}[method]
        strong={p for p,marks in punctuation.items() if marks&set('；;：:')}
        weak={p for p,marks in punctuation.items() if marks&set('，、；;：:')}
        for p in sorted(strong)+sorted(weak-strong):
            if p not in protected and min(abs(p-q) for q in cuts)>=gap: cuts.add(p)
    elif method=='S9': cuts=ends|set(range(5,len(raw),5))
    else:
        cuts=ends|set(punctuation)
        if method=='S8':
            extra={m.start() for m in re.finditer('於是|其後|然則|故曰|乃曰|至於|若夫',raw)}
            for term in ENTITIES:
                for m in re.finditer(term,raw): extra.update(m.span())
            for m in HAN_NUM.finditer(raw):
                if len(m[0])>=2: extra.update(m.span())
            cuts.update(extra-protected)
    cuts=sorted(cuts|ends); spans=list(map(list,zip(cuts,cuts[1:])))
    audit=audit_partition(raw,spans)
    if not audit['exact_reconstruction']: raise ValueError('Raw partition integrity failed')
    return spans,sorted(set(cuts)&protected)
