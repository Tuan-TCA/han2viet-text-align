"""Boundary/reference metrics and reviewable, source-linked exports."""
from collections import Counter
import csv
import json
from statistics import mean

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.utils import get_column_letter

from local_repair import quality
from preprocess import audit_partition, normalize, suspicious


def ratio(a,b): return a/b if b else None


def iou(a,b):
    return max(0,min(a[1],b[1])-max(a[0],b[0]))/(max(a[1],b[1])-min(a[0],b[0]))


def evaluate(win, spans, result, silver):
    raw,start=win['raw'],win['start']
    q=quality(result)
    pairs=[g for g in result['groups'] if g['Validation_Status']=='mapped']
    metrics={**audit_partition(raw,spans),'segments':len(spans),'api_status':result['status'],
             'han_coverage':ratio(q['han_covered'],len(raw)) if q else None,
             'vi_coverage':ratio(q['vi_covered'],len(win['viet'])) if q else None,
             'unresolved':q['unresolved'] if q else None,'overlap_chars':q['overlap'] if q else None,
             'missing_viet_ids':sorted({v['id'] for v in win['viet']}-{k for g in pairs for k in g['VI_IDs']}),
             'alignment_types':dict(Counter(g['Alignment_Type'] for g in pairs)),
             'verified_positive':0,'verified_negative':0,'semantic_unknown':len(pairs),
             'verified_positive_rate':None,'verified_review_coverage':0.0 if pairs else None}
    metrics['uncovered_han_spans']=[]
    end=0
    for a,b in sorted((g['Han_Start'],g['Han_End']) for g in pairs):
        if a>end: metrics['uncovered_han_spans'].append([start+end,start+a])
        end=max(end,b)
    if end<len(raw): metrics['uncovered_han_spans'].append([start+end,start+len(raw)])
    if not silver:
        metrics['references']=None
        return metrics,[]
    def canon(p): return p-len(raw[:p-start])+len(raw[:p-start].rstrip())
    variants={'CG':[],'DS':[],'agreed':[]}
    for row in silver:
        comparison=row['comparison']
        cg=[comparison['CG_Start'],comparison['CG_End']]; ds=[comparison['DS_Start'],comparison['DS_End']]
        variants['CG'].append((row,cg)); variants['DS'].append((row,ds))
        if cg==ds: variants['agreed'].append((row,cg))
    edge0=min(r['Han_Start_0'] for r in silver); edge1=max(r['Han_End_exclusive'] for r in silver)
    predicted={canon(start+b) for _,b in spans if edge0<canon(start+b)<edge1}
    details=[]; metrics['references']={}
    for name,rows in variants.items():
        gold={canon(x) for _,s in rows for x in s if edge0<canon(x)<edge1}
        hit=len(predicted&gold)
        ious=[]; exact=0; seg_exact=0
        for r,ref in rows:
            matches=[g for g in pairs if g['VI_IDs']==[r['VI_ID']]]
            pred=[start+matches[0][k] for k in ('Han_Start','Han_End')] if len(matches)==1 else None
            same=bool(pred and list(map(canon,pred))==list(map(canon,ref)))
            seg=any(list(map(canon,(start+a,start+b)))==list(map(canon,ref)) for a,b in spans)
            score=iou(pred,ref) if pred else 0.
            exact+=same; seg_exact+=seg; ious.append(score)
            details.append({'reference':name,'pair':r['Pair_ID'],'vi_id':r['VI_ID'],'reference_span':ref,
                            'mapped_span':pred,'alignment_exact':same,'segment_exact':seg,'iou':score})
        metrics['references'][name]={'boundary_precision':ratio(hit,len(predicted)), 'boundary_recall':ratio(hit,len(gold)),
             'boundary_f1':ratio(2*hit,len(predicted)+len(gold)), 'boundary_hits':hit,
             'boundary_predicted':len(predicted),'boundary_reference':len(gold),
             'alignment_exact':exact if q else None,'segment_exact':seg_exact,'pairs':len(rows),
             'mean_iou':mean(ious) if q and ious else None}
    return metrics,details


def segments(win, path, marks, method):
    out=[]; raw=win['raw']; start=win['start']
    for move in path:
        a,b=move['han']; j,k=move['vi']
        if a==b: continue
        normalized,offsets=normalize(raw[a:b]); global_span=[start+a,start+b]
        source=[]
        for p in win['pages']:
            pa,pb=p['global_raw_span']; lo,hi=max(pa,global_span[0]),min(pb,global_span[1])
            if lo<hi:
                source.append({'page':p['han_pdf_page'],'file':p['source']['path'],
                               'file_span':[p['file_text_span'][0]+lo-pa,p['file_text_span'][0]+hi-pa]})
        out.append({'id_zh':f"{win['id']}-{method}-{len(out)+1:04d}",'method':method,'window':win['id'],
                    'global_raw_span':global_span,'text_original':raw[a:b],'text_zh':normalized,
                    'normalized_source_spans':[[start+a+i,start+a+l] for i,l in offsets],
                    'page_start':source[0]['page'],'page_end':source[-1]['page'],'source':source,
                    'ocr_flags':suspicious(raw[a:b]),'kind':move['kind'],'boundary':marks[b],
                    'confidence_proxy':marks[b]['score'],'transition_score':move['score'],
                    'signals':move['signals'],'vi_ids':[r['id'] for r in win['viet'][j:k]],
                    'vi_context_ids':[r['id'] for r in win['viet']]})
    return out


def workbook(path, sheets):
    wb=Workbook(); wb.remove(wb.active)
    for title,rows in sheets.items():
        ws=wb.create_sheet(title); rows=list(rows)
        if not rows:
            ws.append(['No data']); continue
        keys=list(dict.fromkeys(k for r in rows for k in r))
        ws.append(keys); ws.freeze_panes='A2'
        for row in rows:
            ws.append([None if row.get(k) is None else row[k] if isinstance(row[k],(int,float)) else
                       ILLEGAL_CHARACTERS_RE.sub('',row[k] if isinstance(row[k],str) else json.dumps(row[k],ensure_ascii=False))[:32767]
                       for k in keys])
            for c in ws[ws.max_row]:
                if c.data_type=='f': c.data_type='s'
        ws.auto_filter.ref=ws.dimensions
        for i,k in enumerate(keys,1): ws.column_dimensions[get_column_letter(i)].width=min(56,max(16,len(k)+3))
    tmp=path.with_name(path.stem+'.tmp.xlsx'); wb.save(tmp); tmp.replace(path)


def export_stage04(folder, items):
    batches = {}
    for row in items:
        cap = row['window'].rsplit('-',2)[0]
        batches.setdefault((cap,row['method'],row['page_start']),[]).append(row)
    for (cap,method,page),rows in batches.items():
        target = folder/'stage04'/cap/method
        target.mkdir(parents=True,exist_ok=True)
        path = target/f'{page:04d}-segments.csv'
        temp = path.with_suffix('.tmp')
        with temp.open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.writer(f)
            w.writerow(['id_zh','text_zh','han_page_start','han_page_end','global_raw_start','global_raw_end'])
            for row in rows:
                if row['text_zh']:
                    w.writerow([row['id_zh'],row['text_zh'],row['page_start'],row['page_end'],*row['global_raw_span']])
        temp.replace(path)


def blind_review(folder, windows):
    sources=[]; context=[]
    for win in windows:
        for page in win['pages']:
            sources.append({'Window':win['id'],'HanPage':page['han_pdf_page'],
                            'GlobalRawStart':page['global_raw_span'][0],'Source':page['source']['path'],
                            'HanFromOCR':page['text_original']})
        context.extend({'Window':win['id'],'VI_ID':row['id'],'Vietnamese':row['text_original'],
                        'Source':row['source']} for row in win['viet'])
    workbook(folder/'heldout_reference_packet.xlsx',{'Han':sources,'Vietnamese_Context':context,
        'Reference_Form':[{'Window':w['id'],'Han_Start_Global':None,'Han_End_Exclusive':None,'VI_IDs':None,
                           'Source_Evidence':None,'Reviewer':None,'Label_Target':None} for w in windows]})
