"""Audit historical Stage04 material separately from Stage03 mapping probes."""
import re
from collections import defaultdict
from common import *

def check(out):
    ctx=lines(I/'window_context_refined.jsonl');idx=defaultdict(set);hits=defaultdict(set);inventory=[]
    for c in ctx:
        for s in c['han']:
            t=''.join(s['text_zh'].split());
            for i in range(len(t)-11):idx[t[i:i+12]].add((c['cap'],c['han_page']))
    def visit(x,p):
        if isinstance(x,list):
            for item in x:visit(item,p)
        elif isinstance(x,dict):
            for k,v in x.items():
                if k in ('han','han_text','Han_Text','text_zh') and isinstance(v,str):
                    t=''.join(v.split());
                    for i in range(len(t)-11):
                        for page in idx.get(t[i:i+12],()):hits[page].add(p)
                elif k in ('han_ids','Han_IDs','id_zh'):
                    for cap,a,b in re.findall(r'(Cap_\d+)-(\d{3})-(\d{3})-S4',str(v)):
                        for n in range(int(a),int(b)+1):hits[cap,n].add(p)
                elif isinstance(v,(list,dict)):visit(v,p)
    roots=[ROOT/'04_dong_hang/artifacts/stage04',ROOT/'04_dong_hang/artifacts/stage04_offline',*[p for p in (ROOT/'pipeline/artifacts').iterdir() if any(t in p.name for t in ('align','silver_2x2'))]]
    for folder in roots:
        for f in folder.rglob('*'):
            if f.suffix not in ('.json','.jsonl'):continue
            p=str(f.relative_to(ROOT));inventory.append(p);visit(lines(f) if f.suffix=='.jsonl' else read(f),p)
    seeds=lines(D/'fresh_benchmark_seed.jsonl');used=read(D/'benchmark_exclusions.json')['excluded_pages'];selected=[];reserved={(s['cap'],n) for s in seeds for n in s['han_pages']};lookup={(c['cap'],c['han_page']):c for c in ctx};subs=[]
    for s in seeds:
        cap=s['cap'];pages=s['han_pages'];bad=[p for p in pages if hits[cap,p] or p in used[cap]]
        if bad:
            start=next(n for n in sorted(range(1,max(c['han_page'] for c in ctx if c['cap']==cap)),key=lambda n:(abs(n-pages[0]),n)) if all((cap,p) not in reserved and not hits[cap,p] and p not in used[cap] and lookup.get((cap,p),{}).get('viet') for p in [n,n+1]));pages=[start,start+1];cx=[lookup[cap,n] for n in pages];reserved.update((cap,n) for n in pages);name=f'{cap}-{start:03}-{start+1:03}';subs.append(dict(original=s['window'],replacement=name,evidence={n:sorted(hits[cap,n]) for n in bad}));s={**s,'window':name,'han_pages':pages,'page_contexts':cx,'ordered_unique_vi_ids':sorted({v['id'] for c in cx for v in c['viet']})}
        selected.append(s)
    save(out/'freshness.json',dict(inventory=inventory,method='Stage04 payload/source 12-character overlap or S4 window ID plus published exclusions; coarse Stage03 context is not a Stage04 evaluation',substitutions=subs,selected=[s['window'] for s in selected]));return selected
