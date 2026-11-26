from collections import Counter
import re
from common import *

def audit(out,continuation):
    manifest=read(PACK/'source_manifest.json');checked={e['path']:digest(PACK/e['path']) for e in manifest['files']};assert all(checked[e['path']]==e['sha256'] for e in manifest['files'])
    raw='';files={};page_counts={};segs=lines(I/'han_segments_full.jsonl')
    for p in sorted(I.glob('*_HAN_all_pages.txt')):
        cap=p.name[:6];text=files[cap]=p.read_text(encoding='utf-8-sig');pages=re.split(r'(?m)^=== '+cap+r' \| PAGE \d+ ===\s*\n',text)[1:];raw+=''.join(x.strip() for x in pages);page_counts[cap]=len(pages)
    for s in segs:
        a,b=s['global_raw_span'];assert raw[a:b]==s['text_original']==''.join(files[s['id_zh'][:6]][slice(*x['file_span'])] for x in s['source'])
    original=read(D/'source_integrity_report.json');assert original['cap_page_counts']==page_counts
    save(out/'source_integrity.json',dict(checked_sha256=checked,segments=len(segs),characters=len(raw),pages=page_counts,global_mismatches=0,file_mismatches=0,stage03_release=read(I/'production_audit.json')['release_status']))
    ext=read(D/'page3_4_candidate_extension.json')['groups'];vf=next(I.glob('VIET_Cap01*'));vt={r['id_vi']:r for r in table(vf,'CAU_VIET')};anchors=table(vf,'TRANG_VIET');obs=[
        'Han p2 last column introduces two names after the preceding 664 total. P3 opens with their promotion. Printed 192 continues the fee list across the workbook break; its total is 277 quan 1 tien 45 dong. One passage/two fragments preferred; no internal Han split evidenced. OCR amounts differ from print.',
        'Next name on p3 is the Minh Linh official; printed 192 changes subject after the 277 total and ends his account at 165 quan 2 tien 15 dong.',
        'Phu Chau/Tran Van opens the next account. Printed 192 ends mid-total; printed 193 opens with 82 quan 4 tien 30 dong. Keep page continuation.',
        'Five-person aggregate 1466/3/21 is separate from the preceding individual total on both scans.',
        'Hong Duc reign introduces register rules, three/six-year cycle and household classifications. Last clause before four copies is difficult: scan appears to read 各社 at transition; OCR segmentation may leave 社 on wrong side.',
        'Printed 193 starts Mỗi xã khai bốn bản sổ; Han p4 right leaf lists four copies and destinations. Topic break at 1404 is plausible but 各社 may start before 1404; retain earlier start as alternative, not exact Gold.',
        'Canh Tri introduces changed census procedure; end at abandonment of old method before Nguyen genealogy.',
        'Nguyen rule in Thuan Quang and continuation of Hong Duc practice close this candidate. Following military-selection sentence belongs to later material.']
    comps=[];records=[]
    for g,note in zip(ext,obs):
        a,b=g['start'],g['end'];assert raw[a:b]==g['han_text'];assert all(vt[v['vi_id']]['text_vi']==v['text_vi'] for v in g['vi_sources']);records.append({**g,'scan_review':note,'page_anchors':[r for r in anchors if r['viet_pdf_page'] in g['source_pdf_pages']]})
        for r in continuation:
            overlaps=[]
            for j,h in enumerate(r['baseline']):
                x,y=h['Han_Start'],h['Han_End'];
                if x is not None and y is not None and x<b and y>a:overlaps.append(dict(api_row=j,span=[x,y],ids=h['VI_IDs'],iou=(min(y,b)-max(a,x))/(max(y,b)-min(a,x)),exact=(x,y)==(a,b),full_ids=h['VI_IDs']==g['vi_ids'] and h['Validation_Status']=='mapped'))
            comps.append(dict(candidate=g['id'],context=r['context'],reference=[a,b],expected_ids=g['vi_ids'],overlaps=overlaps,best_iou=max((h['iou'] for h in overlaps),default=0),exact_pair=any(h['exact'] and h['full_ids'] for h in overlaps)))
    save(out/'page3_4_alignment.json',dict(groups=records,api_comparison=comps,status='source-backed hypotheses; boundaries not adjudicated'));book(out/'source_continuation_audit.xlsx',{'Source review':records});book(out/'page3_4_api_comparison.xlsx',{'Candidate overlap':comps,'API groups':[{'context':r['context'],**g} for r in continuation for g in r['baseline']]})

def review(out,extra):
    rows=[]
    def add(origin,h,v,loc):
        key=hashlib.sha256((h+'\0'+v).encode()).hexdigest()[:20];rows.append(dict(blind_id=key,Han=h,Vietnamese=v,origin=origin,location=loc,Label_Target='UNKNOWN'))
    for r in table(D/'Stage04_V4_Handoff_Review_Pack.xlsx','Blind_Review'):add('supplied blind',str(r['Han_Text'] or ''),str(r['Vietnamese_Text'] or ''),r['Review_ID'])
    for r in read(I/'baseline_reconstruction.json')['groups']:add('baseline',r['Han_Text'],r['Vietnamese_Text'],[r['Han_Start'],r['Han_End']])
    for r in read(PACK/'previous_v4/v4_alignment.json')['groups']:add('pilot V4',r['Han_Text'],r['VI_Text'],r['V4_ID'])
    for r in read(D/'page3_4_candidate_extension.json')['groups']:add('continuation',r['han_text'],' '.join(v['text_vi'] for v in r['vi_sources']),r['id'])
    for method,r,g in extra:
        src=g.get('Original_API_Rows') or [{}];add(method,g.get('Han_Text') or ' '.join(x.get('han_text','') for x in src),g.get('Vietnamese_Text') or ' '.join(x.get('vietnamese_text','') for x in src),[r['window'],r['context'],g['Han_Start'],g['Han_End'],g['VI_IDs']])
    # Strip embedded source identifiers from supplied display strings on blind sheet.
    blind={r['blind_id']:{'blind_id':r['blind_id'],'Han':r['Han'],'Vietnamese':re.sub(r'\[Cap_\d+-VI-[\d-]+\]\s*','',r['Vietnamese']),'Reviewer_Label':None,'Reviewer_Notes':None} for r in rows};blind=[blind[k] for k in sorted(blind)]
    old=table(I/'Semantic_Gold_Review_verified_v2.xlsx','API_Row_Review');old2=table(I/'Stage04_Gold_Review_Pack.xlsx','Blind_Review');assert not any(r['Reviewer_Label'] for r in old+old2)
    status=dict(proposals=dict(Counter(r['Proposed_Label'] for r in old)),readme_discrepancy='5/8/2',prior_review_sizes=[len(old),len(old2)],human_adjudicated=0,unique_blind_rows=len(blind),semantic_accuracy='NOT MEASURED',independent_model_pair='not configured')
    book(out/'gold_review_packet.xlsx',{'Blind review':blind});book(out/'semantic_review.xlsx',{'Source key':rows,'Unresolved adjudication':blind});save(out/'gold_status.json',status);save(out/'unresolved_adjudication.json',[r['blind_id'] for r in blind])
