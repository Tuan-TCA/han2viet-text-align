"""Whole S4 units; B2 primary, adjacent B2 and B1 ranges for recovery."""
from inputs import require
def supported(status):return not any(v in status.upper() for v in ('UNMATCH','PARTIAL','UNSUPPORTED','MISSING'))
def plan(d,cfg):
    size=cfg['window']['pages'];stride=cfg['window']['stride'];require(size>1 and 0<stride<size,'Han windows must overlap');windows=[]
    for cap in sorted(d['meta']['caps']):
        last=d['meta']['caps'][cap]['total_pages'];cs=d['cs'];ms=d['ms'];vi=d['vi']
        for start in range(1,last+1,stride):
            pages=list(range(start,min(last,start+size-1)+1));good=[n for n in pages if supported(ms[cap,n]['Mapping_Status'])];hs=[s['id_zh'] for s in d['ss'] if s['cap']==cap and any(s['page_start']<=n<=s['page_end'] for n in good) and all(supported(ms[cap,i]['Mapping_Status']) for i in range(s['page_start'],s['page_end']+1))];ids={v['id'] for n in good for v in cs[cap,n]['viet']}|{k for n in good for k in ms[cap,n]['Selected_VI_IDs']};adj=set(ids)
            for n in good:
                # V2 exposes the full physical-page envelopes separately from
                # the shorter IDs returned by the winning coarse probe.
                for field in ('b2_range_vi_ids','b1_fallback_vi_ids','padded_context_vi_ids'):
                    ids.update(cs[cap,n].get(field,[]))
                adj.update(ids)
                for near in (n-1,n+1):
                    if (cap,near) in cs and supported(ms[cap,near]['Mapping_Status']):adj.update(v['id'] for v in cs[cap,near]['viet'])
                ran=ms[cap,n].get('B1_Range');
                if ran and all(isinstance(i,int) for i in ran):adj.update(k for k,v in vi.items() if v['cap']==cap and v['viet_page_start']<=ran[1] and v['viet_page_end']>=ran[0])
            windows.append(dict(id=f'{cap}-{start:03}-{pages[-1]:03}',cap=cap,pages=pages,page_status=[ms[cap,n]['Mapping_Status'] for n in pages],book_transitions=[cs[cap,n]['book_transition'] for n in pages if 'book_transition' in cs[cap,n]],han_ids=hs,vi_ids=sorted(ids,key=d['order'].__getitem__),expanded_ids=sorted(adj,key=d['order'].__getitem__),policy='partial/unmatched pages withheld pending supported sub-page evidence'))
            if pages[-1]==last:break
    return windows
