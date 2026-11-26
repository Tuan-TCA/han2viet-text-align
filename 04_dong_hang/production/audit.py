import io
from inputs import *
from openpyxl import load_workbook
from benchmark_alignment_api import URL

def verify(out,d):
    gs=lines(out/'alignment_final.jsonl');uh=lines(out/'unresolved_han.jsonl');uv=lines(out/'unresolved_viet.jsonl');requests=lines(out/'requests.jsonl');keys={e['job']['key'] for e in requests if e['status']=='success' and e['job']['key']==fingerprint([URL,e['job']['payload']])};h=bytearray(len(d['raw']));vs={k:bytearray(len(v['text_original'])) for k,v in d['vi'].items()};last={}
    def mark(bits,a,b):require(0<=a<b<=len(bits) and not any(bits[a:b]),'duplicate or invalid span');bits[a:b]=b'\1'*(b-a)
    for g in gs:
        a,b=g['Han_Start'],g['Han_End'];require(g['Request_Key'] in keys and g['Label_Target']=='UNKNOWN' and d['raw'][a:b]==g['Han_Text'],'invalid final provenance');mark(h,a,b);cap=g['Cap'];prev=last.get(cap,(-1,-1));texts=[]
        for k,x,y in g['VI_Char_Spans']:
            require((d['order'][k],x)>=prev and d['vi'][k]['cap']==cap,'VI order conflict');prev=(d['order'][k],y);mark(vs[k],x,y);texts.append(d['vi'][k]['text_original'][x:y])
        last[cap]=prev;require(' '.join(texts)==g['Vietnamese_Text'],'VI reconstruction')
    for r in uh:
        a,b=r['span'];s=d['byid'][r['id_zh']];require(s['global_raw_span'][0]<=a<b<=s['global_raw_span'][1] and d['raw'][a:b]==r['text'],'invalid unresolved Han');mark(h,a,b)
    for r in uv:
        a,b=r['span'];k=r['id_vi'];require(d['vi'][k]['text_original'][a:b]==r['text'],'invalid unresolved VI');mark(vs[k],a,b)
    require(all(h) and all(all(v) for v in vs.values()),'source coverage incomplete');w=load_workbook(out/'alignment_final.xlsx');s=w['Alignment_Dataset'];t=load_workbook(io.BytesIO(template())).active;require([c.value for c in s[1]]==[c.value for c in t[1]] and s.max_row==2+len(gs),'template shape mismatch');require(all(s.cell(n,9).value is None for n in range(3,s.max_row+1)),'unverified label in Excel');require(all(sha(ROOT/k)==v for k,v in d['meta']['hashes'].items()),'input changed during run');result=dict(status='PASS',segments=len(d['ss']),pages=len(d['pages']),han_characters_accounted=len(h),vi_characters_accounted=sum(map(len,vs.values())),final_pairs=len(gs),input_hashes_unchanged=True,template_checked=True);save(out/'production_audit.json',result);return result
