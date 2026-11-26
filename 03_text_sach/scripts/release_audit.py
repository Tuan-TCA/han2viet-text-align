"""Audit corpus support at page granularity, including partial two-page windows."""
from coarse_alignment import window
from preprocess import ROOT


def audit(pages,viet,maps):
    rows=[]
    for cap in sorted({p['cap'] for p in pages}):
        pp=[p for p in pages if p['cap']==cap]; refs=[m for m in maps if m['cap']==cap]
        for i in range(0,len(pp),2):
            chunk=pp[i:i+2]; nums=[p['han_pdf_page'] for p in chunk]; w=window(pages,viet,maps,cap,nums,1)
            for p in chunk:
                n=p['han_pdf_page']; source=(ROOT/p['source']['path']).read_bytes().decode('utf-8-sig'); a,b=p['file_text_span']
                assert source[a:b]==p['text_original']
                applicable=[m for m in refs if m['han_search_window'] and m['han_search_window'][0]<=n<=m['han_search_window'][1]]
                state='search_window_only' if applicable else 'no_stage02_vi_mapping'; note=''
                if any(a['han_pdf_page']==n for m in refs for a in m['verified_overlap']): state='verified_page_overlap'
                if cap=='Cap_02' and n>=51:
                    if n==51: note='Right half mapped; left starts book VI, not in current VI workbook.'
                    elif n<=87: note='Book VI in local full PDF pp.405–439; no T1 segments for this continuation in current workbook. Exact per-page pairing unverified.'
                    elif n in (88,89): note='Afterword candidate: Han 88 opening corresponds to BẠT, full PDF p.440. No verified per-page mapping.'
                    elif n==90: note='Possible duplicate Book V opening; verify scan before assigning translation.'
                    else: note='OCR fragment; translation status unknown; retain source.'
                rows.append(dict(cap=cap,page=n,window=w['id'],window_has_vi=bool(w['viet']),page_has_window=bool(applicable),
                                 status=state,evidence=note,raw_span=p['global_raw_span'],file_span=[a,b],source=p['source']['path'],
                                 raw_prefix=p['text_original'][:100],verified_vi_pages=[m['viet_pdf_page'] for m in refs if any(a['han_pdf_page']==n for a in m['verified_overlap'])]))
    return rows
