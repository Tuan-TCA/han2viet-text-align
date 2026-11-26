"""Bounded, source-preserving repair proposals and downstream acceptance."""
from statistics import median


def quality(result):
    if result.get('status')!='ok': return None
    valid=[r for r in result['groups'] if r['Validation_Status']=='mapped']
    spans=sorted((r['Han_Start'],r['Han_End']) for r in valid)
    vi=[k for r in valid for k in r['VI_IDs']]
    covered=end=0
    for a,b in spans:
        covered+=max(0,b-max(end,a)); end=max(end,b)
    overlap=sum(b-a for a,b in spans)-covered
    duplicated=len(vi)-len(set(vi))
    unresolved=len(result['groups'])-len(valid)
    return {'overlap':overlap,'duplicate_vi':duplicated,'unresolved':unresolved,
            'han_covered':covered,'vi_covered':len(set(vi)),
            'merges':sum(r['Alignment_Type']=='N-M' for r in valid)}


def propose(raw, path, marks, result, maximum):
    spans=[tuple(x['han']) for x in path if x['han'][0]<x['han'][1]]
    mapped=[r for r in result.get('groups',[]) if r['Validation_Status']=='mapped']
    scores=[r['Score'] for r in mapped if isinstance(r['Score'],(int,float))]
    threshold=median(scores)*0.75 if len(scores)>2 else -1
    proposed=set(a for a,_ in spans)|{len(raw)}
    problems=[]
    for a,b in spans:
        hits=[r for r in mapped if r['Han_Start']<b and r['Han_End']>a]
        if not hits or any(r['Alignment_Type']=='N-M' or isinstance(r['Score'],(int,float)) and r['Score']<threshold for r in hits):
            options=[(m['score'], -abs(p-(a+b)/2), p) for p,m in marks.items() if not m['blocked'] and a+8<=p<=b-8]
            if options: problems.append((max(options),[a,b]))
    audit=[]
    for (_,_,p), span in sorted(problems,reverse=True)[:maximum]:
        proposed.add(p); audit.append({'region':span,'new_boundary':p})
    ordered=sorted(proposed)
    return list(map(list,zip(ordered,ordered[1:]))),audit


def accept(before, after):
    a,b=quality(before),quality(after)
    return bool(a and b and not b['overlap'] and not b['duplicate_vi']
                and b['unresolved']<=a['unresolved'] and b['vi_covered']>=a['vi_covered']
                and b['han_covered']>=a['han_covered'] and b['merges']<=a['merges']
                and b!=a)
