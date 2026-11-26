"""Read-only binding of frozen segmentation, source workbooks and Silver."""
import csv
import hashlib
from pathlib import Path
import sys
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / '03_text_sach/artifacts/production'
COARSE = PROD.parent / 'coarse_mapping/page_mapping_refined.jsonl'
sys.path.insert(0, str(ROOT / '03_text_sach/scripts'))
from preprocess import load_sources, normalize, read_jsonl, viet_t1
import normalize_phase1 as phase1
from benchmark_alignment_api_final import CONFIRMED

CAP = 'Cap_01'
PAGES = (1, 2)


def hashes(paths):
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def load():
    inventory = [PROD / p for p in ('han_segments.jsonl', 'production_manifest.json', 'window_context.jsonl')]
    csvs = sorted((PROD / 'stage04').glob('*/S4/*-segments.csv'))
    workbooks = [ROOT / f'02_ocr_tho/{cap}/VIET/VIET_{lo:04}-{hi:04}.xlsx'
                 for cap, (_, lo, hi) in phase1.INPUTS.items()]
    supplemental = ROOT / '02_ocr_tho/Cap_02/VIET/VIET_0405-0439.xlsx'
    ocr = [ROOT / f'02_ocr_tho/{cap}/{cap}_HAN_all_pages.txt' for cap in phase1.INPUTS]
    tracked = [*inventory, *csvs, *workbooks, *ocr, COARSE]
    if supplemental.is_file():
        tracked.append(supplemental)
    before = hashes(tracked)
    pages, viet, mapping = load_sources()
    raw = ''.join(p['text_original'] for p in pages)
    segments = read_jsonl(inventory[0]); by_id = {s['id_zh']: s for s in segments}
    if len(by_id) != len(segments):
        raise ValueError('Duplicate frozen Han ID')
    cursor = 0
    for s in segments:
        a, b = s['global_raw_span']; spans = s['normalized_source_spans']
        if not (s['method'] == 'S4' and a == cursor < b and raw[a:b] == s['text_original']
                and len(spans) == len(s['text_zh']) and all(a <= x < y <= b for x, y in spans)):
            raise ValueError(f'Invalid frozen Han payload: {s["id_zh"]}')
        cursor = b
    seen = set(); csv_pages = defaultdict(set)
    for file in csvs:
        cap, page = file.parent.parent.name, int(file.name.split('-')[0])
        with file.open(encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                key = row['id_zh']; s = by_id[key]; seen.add(key); csv_pages[key].add(page)
                if (not key.startswith(cap) or row['text_zh'] != s['text_zh']
                    or [int(row[k]) for k in ('global_raw_start','global_raw_end')] != s['global_raw_span']
                    or not s['page_start'] <= page <= s['page_end']):
                    raise ValueError(f'S4 export disagrees: {file.name}/{key}')
    if (seen != by_id.keys() or cursor != len(raw) or any(
            s['page_start'] not in csv_pages[k] for k,s in by_id.items())):
        raise ValueError('Incomplete frozen source inventory')
    vi = {}
    for row in viet:
        key, text = row['id'], row['text_original']
        if key in vi:
            raise ValueError(f'Duplicate VI ID {key}')
        t1, offsets = viet_t1(text, CONFIRMED.get(key, ()))
        if not t1 or '\n' in t1 or len(t1) != len(offsets):
            raise ValueError(f'Invalid T1 line {key}')
        vi[key] = {**row, 'VI_ID': key, 'text_t1': t1, 't1_offsets': offsets}
    old_root = phase1.ROOT
    try:
        phase1.ROOT = ROOT
        silver, _ = phase1.load_silver(pages, viet)
        source = ROOT / phase1.BENCHMARK
    except PermissionError:
        source = ROOT / 'pipeline/artifacts/phase1/silver_benchmark.jsonl'
        silver = read_jsonl(source)
    finally:
        phase1.ROOT = old_root
    tracked.append(source)
    for row in silver:
        c = row['comparison']
        for model, field in [('chatgpt','ChatGPT_Han'), ('deepseek','DeepSeek_Han')]:
            a,b = c[f'{model}_han_link']['global_raw_span']
            if raw[a:b] != c[field]:
                raise ValueError(f'Silver Han span mismatch {row["Pair_ID"]}')
        if phase1.nfc(row['Vietnamese']) != vi[row['VI_ID']]['text_nfc'] or c['VI_ID'] != row['VI_ID']:
            raise ValueError(f'Silver VI text mismatch {row["Pair_ID"]}')
    if len(silver) != 12 or len({r['VI_ID'] for r in silver}) != 12:
        raise ValueError('Expected 12 distinct Silver pairs')
    contexts = read_jsonl(inventory[2]); refined = read_jsonl(COARSE)
    unsupported = []
    for p in pages:
        if p['cap'] != 'Cap_02' or p['han_pdf_page'] < 52:
            continue
        a,b = p['global_raw_span']
        unsupported.append({'Cap':'Cap_02','Han_Page':p['han_pdf_page'],'Reason':'PROCESSED_VI_UNAVAILABLE',
                            'Han_Start':a,'Han_End':b,'Han_Text':raw[a:b],
                            'Han_IDs':[s['id_zh'] for s in segments if s['global_raw_span'][0]<b and s['global_raw_span'][1]>a]})
    return dict(raw=raw, pages=pages, han=[s for s in segments if s['window']=='Cap_01-001-002'],
                vi=vi, pool=[k for k,r in vi.items() if r['cap']==CAP], silver=silver,
                silver_source=str(source.relative_to(ROOT)), tracked=tracked, before={**before, **hashes([source])},
                contexts=contexts, refined=refined, mapping=mapping, unsupported=unsupported)


def han_unit(s, lo=None, hi=None):
    """Compose normalization projections; optional cuts are in frozen text coordinates."""
    lo = 0 if lo is None else lo
    hi = len(s['text_zh']) if hi is None else hi
    spans = s['normalized_source_spans'][lo:hi]
    if not 0 <= lo < hi <= len(s['text_zh']):
        raise ValueError('Invalid temporary Han boundary')
    text, offsets = normalize(s['text_zh'][lo:hi]); a,b = s['global_raw_span']
    if not text:
        raise ValueError('Empty temporary Han input')
    return dict(text=text, span=[a if lo == 0 else spans[0][0], b if hi == len(s['text_zh']) else spans[-1][1]],
                offsets=[[spans[x][0],spans[y-1][1]] for x,y in offsets], ids=[s['id_zh']], sources=[s])


def merge_units(left, right, raw):
    a,b = left['span']; c,d = right['span']
    if b > c or raw[b:c].strip():
        raise ValueError('Non-contiguous temporary Han merge')
    gap = raw[b:c]
    return dict(text=left['text']+(' ' if gap else '')+right['text'], span=[a,d],
                offsets=left['offsets']+([[b,c]] if gap else [])+right['offsets'],
                ids=list(dict.fromkeys(left['ids']+right['ids'])), sources=left['sources']+right['sources'])
