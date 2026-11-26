"""Validate released inputs against source files before planning any network work."""
import hashlib,json,sys,subprocess
from pathlib import Path
from openpyxl import load_workbook
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];sys.path.insert(0,str(HERE.parent))
from stage04_inputs import CONFIRMED,viet_t1
from preprocess import normalize
from benchmark_alignment_api import fingerprint

def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def lines(p):
    with p.open(encoding='utf-8-sig') as f:return [json.loads(x) for x in f if x.strip()]
def dump(x):return json.dumps(x,ensure_ascii=False,separators=(',',':'))
def write(p,data):
    tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(data,encoding='utf8');tmp.replace(p)
def save(p,obj):write(p,dump(obj)+'\n')
def jsonl(p,rows):write(p,''.join(dump(x)+'\n' for x in rows))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def require(ok,msg):
    if not ok:raise ValueError(msg)
def config(p):
    d=read(p);return {**(config(p.parent/d['extends']) if 'extends' in d else {}),**d}
def template():return subprocess.check_output(['git','show','HEAD:04_dong_hang/Sino_Vietnamese_Sentence_Alignment_Template.xlsx'],cwd=ROOT)

def inventory(cfg):
    m=ROOT/cfg['mapping_dir'];h=ROOT/cfg['han_dir'];mp=m/cfg['mapping_file'];cp=m/cfg['window_context'];vp=ROOT/cfg['viet_segments'];paths=[mp,cp,vp,*[h/n for n in ['production_manifest.json','production_audit.json','han_segments.jsonl']]]
    for p in paths:
        if not p.is_file():raise FileNotFoundError(f"{cfg['profile']} input unavailable: {p}")
    manifest=read(paths[3]);audit=read(paths[4]);ss=lines(paths[5]);ms={(r['Cap'],r['Han_Page']):r for r in lines(mp)};cs={(r['cap'],r['han_page']):r for r in lines(cp)};pages={(r['cap'],n) for r in manifest['windows'] for n in r['pages']};require(pages==ms.keys()==cs.keys(),'mapping pages differ from production manifest');raw=''.join(s['text_original'] for s in ss);ocr={};caps={};pos=0;byid={}
    for s in ss:
        k=s['id_zh'];cap=s['source'][0]['file'].split('/')[1];s['cap']=cap;a,b=s['global_raw_span'];require(s['method']=='S4' and k not in byid and a==pos<b and raw[a:b]==s['text_original'],'invalid S4 partition: '+k);byid[k]=s;pos=b;chunks=[]
        for x in s['source']:
            p=ROOT/x['file'];
            if p not in ocr:ocr[p]=p.read_text(encoding='utf-8-sig');paths.append(p)
            chunks.append(ocr[p][slice(*x['file_span'])]);require((cap,x['page']) in pages,'unknown Han source page')
        require(''.join(chunks)==raw[a:b] and len(s['normalized_source_spans'])==len(s['text_zh']) and all(a<=u<v<=b for u,v in s['normalized_source_spans']),'Han projection: '+k)
        text,sp=normalize(raw[a:b]);require(text==s['text_zh'] and [[a+x,a+y] for x,y in sp]==s['normalized_source_spans'],'non-reversible Han projection: '+k)
    for cap,expected in audit['caps'].items():
        arr=[s for s in ss if s['cap']==cap];caps[cap]=dict(total_pages=sum(c==cap for c,n in pages),segments=len(arr),source_chars=sum(len(s['text_original']) for s in arr));require(all(expected[k]==v for k,v in caps[cap].items()),'manifest/audit mismatch')
    require((caps['Cap_01']['total_pages'],caps['Cap_02']['total_pages'],len(ss),pos)==(53,92,2808,53328),'unexpected frozen release inventory');require(manifest['release_status']=='complete','Stage03 release incomplete')
    vi={};source_ids={};bookorder={}
    for cap,files in cfg['workbooks'].items():
        for idx,name in enumerate(files):
            p=ROOT/name;paths.append(p);bookorder[name]=idx;w=load_workbook(p,read_only=True,data_only=True);rows=iter(w['CAU_VIET'].values);fields=next(rows)
            for n,row in enumerate(rows,2):
                r=dict(zip(fields,row));k=r['id_vi'];t=r['text_vi'];
                if not r['dung_de_ghep'] or not k or not t:continue
                require(k not in vi,'duplicate VI ID '+str(k));t=str(t).strip();norm,sp=viet_t1(t,CONFIRMED.get(k,()));vi[k]=dict(id=k,cap=cap,text_original=t,text_t1=norm,t1_offsets=sp,source={'path':name,'sheet':'CAU_VIET','row':n},viet_page_start=r['viet_page_start'],viet_page_end=r['viet_page_end']);source_ids[name,n]=k
            w.close()
    def check(v,k):
        z=vi.get(k);src=v['source'];require(z and source_ids.get((src['path'],src['row']))==k and z['text_original']==v['text_original'],'VI source mismatch: '+str(k));return z
    seen=set()
    for v in lines(vp):
        z=check(v,v['id']);require(v['id'] not in seen,'duplicate VI segment');seen.add(v['id'])
        if 'text_t1' in v:require(z['text_t1']==v['text_t1'] and list(map(list,z['t1_offsets']))==v['normalized_source_spans'],'extended segment T1 mismatch')
    require(seen==vi.keys(),'VI segment file does not inventory all eligible workbook rows')
    for key,c in cs.items():
        require(c['mapping_status']==ms[key]['Mapping_Status'],'context/mapping status disagreement');require(all(k in byid and byid[k]['cap']==key[0] for k in c['han_ids']),'unknown Han context');
        for v in c['viet']:require(check(v,v['id'])['cap']==key[0],'cross-Cap VI context')
        for v in c['viet_t1']:
            z=check(v,v['vi_id']);require(z['text_t1']==v['text_t1'] and list(map(list,z['t1_offsets']))==v['normalized_source_spans'],'T1 projection mismatch: '+v['vi_id'])
        ids=set(ms[key]['Selected_VI_IDs']);require(ids=={v['id'] for v in c['viet']}=={v['vi_id'] for v in c['viet_t1']},'inconsistent context VI inventory')
        for field in ('b2_range_vi_ids','b1_fallback_vi_ids','padded_context_vi_ids'):ids.update(c.get(field,[]))
        require(all(k in vi and vi[k]['cap']==key[0] for k in ids),'unknown selected VI ID')
    if cfg['profile']=='expanded':
        books={vi[k]['source']['path'] for c in cs.values() for k in [v['id'] for v in c['viet']]};require(all(name in books for files in cfg['workbooks'].values() for name in files),'expanded mapping lacks context for a configured workbook')
    hashes={str(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p):sha(p) for p in paths};meta=dict(caps=caps,segments=len(ss),raw_chars=pos,vi_records=len(vi),hashes=hashes,template_sha256=hashlib.sha256(template()).hexdigest(),method='S4+T1',profile=cfg['profile']);return dict(ss=ss,byid=byid,raw=raw,vi=vi,ms=ms,cs=cs,pages=pages,meta=meta,order={k:i for i,k in enumerate(vi)})
