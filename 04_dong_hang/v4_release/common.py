from pathlib import Path
import hashlib, json, sys
from openpyxl import Workbook, load_workbook

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]; PACK=ROOT/'Stage04_V4_Handoff'; I=PACK/'inputs'; D=PACK/'candidate_data'
sys.path.insert(0,str(HERE.parent)); sys.path.insert(0,str(HERE.parent/'temp'))
def read(p): return json.loads(p.read_text(encoding='utf-8-sig'))
def lines(p):
    with p.open(encoding='utf-8-sig') as f: return [json.loads(s) for s in f if s.strip()]
def save(p,obj):
    temp=p.with_suffix(p.suffix+'.tmp');temp.write_text(json.dumps(obj,ensure_ascii=False,indent=1),encoding='utf8');temp.replace(p)
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def table(p,s):
    w=load_workbook(p,read_only=True,data_only=True);it=iter(w[s].values);h=next(it);r=[dict(zip(h,x)) for x in it];w.close();return r
def book(p,sheets):
    w=Workbook();w.remove(w.active)
    for name,rows in sheets.items():
        ws=w.create_sheet(name);rows=list(rows);keys=list(dict.fromkeys(k for r in rows for k in r));ws.append(keys)
        for r in rows:ws.append([json.dumps(r[k],ensure_ascii=False) if isinstance(r.get(k),(list,dict,tuple)) else r.get(k) for k in keys]);
        ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions
    w.save(p)
