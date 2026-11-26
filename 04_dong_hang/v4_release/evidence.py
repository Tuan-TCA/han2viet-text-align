"""Evidence crosswalk. Development-only checks, never decoder inputs."""
import csv, re, zipfile
from common import *

def crosswalk(out,results):
    check=read(D/'source_integrity_report.json'); hashes=read(out/'source_integrity.json')['checked_sha256'];assert set(check['hashes'].values())<=set(hashes.values())
    seg=lines(I/'han_segments_full.jsonl');raw=''.join(s['text_original'] for s in seg);pilot=lines(I/'han_segments_pilot_2pages.jsonl');save(out/'pilot_input_audit.json',dict(pilot_records=len(pilot),exact_full_records=sum(s in seg for s in pilot),use='historical fixture only; global offsets from full release'))
    fixture=read(D/'v4_candidate_extended.json')['groups'];sheet=table(D/'v4_candidate_extended.xlsx','V4_Candidate_Alignment');assert [(g['Han_Start'],g['Han_End']) for g in fixture]==[(g['Han_Start'],g['Han_End']) for g in sheet];assert all(raw[g['Han_Start']:g['Han_End']]==g['Han_Text'] for g in fixture)
    exts=read(D/'page3_4_candidate_extension.json')['groups'];assert [g['han_text'] for g in exts]==[x['Han_Text'] for x in table(D/'page3_4_candidate_extension.xlsx','Candidate_Groups')];assert [g['Han_Text'] for g in table(PACK/'previous_v4/v4_alignment.xlsx','V4_Alignment')]==[g['Han_Text'] for g in read(PACK/'previous_v4/v4_alignment.json')['groups']]
    seeds=lines(D/'fresh_benchmark_seed.jsonl');xl=table(D/'fresh_benchmark_seed.xlsx','Manifest');
    with (D/'fresh_benchmark_candidates.csv').open(encoding='utf-8-sig',newline='') as f:cs=list(csv.DictReader(f))
    for s,x,c in zip(seeds,xl,cs,strict=True):assert s['window']==x['Window_ID']==c['Window_ID'] and len(s['ordered_unique_vi_ids'])==x['VI_ID_Count']==int(c['VI_ID_Count'])
    workbooks={};page_anchors={}
    for cap in ['Cap_01','Cap_02']:
        p=next(I.glob('VIET_'+cap.replace('_','')+'*'));workbooks[cap]={r['id_vi']:r['text_vi'] for r in table(p,'CAU_VIET')};page_anchors[cap]={r['viet_pdf_page']:r for r in table(p,'TRANG_VIET')}
    traces=[]
    for s in seeds:
        for v in s['ordered_unique_viet']:
            assert v['text_original']==workbooks[s['cap']][v['id']];traces.append(dict(window=s['window'],id=v['id'],source=v['source'],anchor=page_anchors[s['cap']].get(v['viet_page_start'])))
    pdf=(PACK/'evidence/VIET_pdf_pages_189_190_text.txt').read_text(encoding='utf8');han=(PACK/'evidence/HAN_Cap01_pages_002_004_OCR.txt').read_text(encoding='utf8');assert 'printed footer page 192' in pdf and 'printed footer page 193' in pdf
    replay=read(I/'baseline_reconstruction.json');offline=table(I/'stage04_offline_comparison.xlsx','Responses');reqs=lines(out/'requests.jsonl');shared=sum(any((r['Han_Payload'],r['VI_Payload'])==(e['job']['payload']['han'],e['job']['payload']['vi']) for r in offline) for e in reqs);refs=[]
    for g in fixture:
        for method in ['baseline','v4']:
            # Only compare where the complete reference is inside request scope.
            for r in results:
                if r['window']!='continuation' or not r['full'] or not r['han'][0][0]<=g['Han_Start']<g['Han_End']<=r['han'][-1][1]:continue
                refs.append(dict(group=g['Candidate_ID'],method=method,exact=any((h['Han_Start'],h['Han_End'])==(g['Han_Start'],g['Han_End']) and h['VI_IDs']==g['VI_IDs'] for h in r[method]),span=[g['Han_Start'],g['Han_End']]))
    historical=[dict(version=v,groups=len(groups)) for v,groups in read(I/'refined_alignment.json')['variants'].items()];archive=PACK/'previous_v4/Stage04_V4_Package.zip'
    with zipfile.ZipFile(archive) as z:archive_members=z.namelist()
    save(out/'evidence_crosswalk.json',dict(stage03_identity=read(I/'production_manifest.json')['identity'],production_reader_verified=read(I/'production_audit.json')['stage04_reader_match'],seed_source_traces=traces,extended_fixture_checks=refs,pilot_archive_members=archive_members,prior_v4_comparison=table(PACK/'previous_v4/v4_comparison.xlsx','V0_V3_V4'),offline_variants=historical,offline_replay_exact=replay['exact_replay'],offline_comparison_payload_matches=shared,prior_correction_cases=read(I/'correction_log.json')['case_checks'],extracted_ocr_chars=len(han),printed_page_extract_chars=len(pdf)))
