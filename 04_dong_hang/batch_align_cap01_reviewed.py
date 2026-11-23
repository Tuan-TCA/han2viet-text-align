"""Review Cap_01 Han boundaries and align against the Stage 02 workbook."""

import argparse
import csv
import json
import os
from pathlib import Path
import re
import sys
import time

from openpyxl import Workbook, load_workbook

from align_sinonom_api import call_api
from batch_han_sentence_split import content

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
HAN = ROOT / '03_text_sach/Cap_01/HAN'
VIET = ROOT / '02_ocr_tho/Cap_01/VIET/VIET_0186-0251.xlsx'
OUTPUT = HERE / 'Cap01_0001-0010_alignment_reviewed.xlsx'
LOG = HERE / 'Cap01_0001-0010_alignment_run.json'
TEMPLATE = HERE / 'Sino_Vietnamese_Sentence_Alignment_Template.xlsx'

# Internal API cuts to suppress after contextual review. Keys are (page, line).
MERGE_AFTER = {
    (1, 1), (1, 4), (1, 5), (1, 7), (1, 8), (1, 13), (1, 14),
    (2, 3), (2, 5), (2, 9),
    (3, 9), (3, 14), (4, 12), (4, 14),
    (5, 13), (5, 15), (5, 16), (5, 18),
    (6, 1), (6, 7), (6, 10), (6, 13), (6, 15),
    (7, 1), (7, 4), (7, 5), (7, 11), (7, 16),
    (8, 3), (8, 8), (9, 2), (9, 7),
    (10, 6), (10, 12), (10, 13),
}
# Insert stops within OCR chunks where both sides are identifiable.
CUT_BEFORE = {(1, 6): ('各斬，',), (10, 8): ('阮氏每',)}
# Only these individual transcriptions were corrected against the scan.
SCAN_TEXT = {
    (4, 4): '生者不計，耗者不除，舊法遂廢。',
    (4, 5): '阮氏據守廣順，傳習家久，兵民田數租稅，一遵洪德規例，非有異也。',
    (4, 6): '此法照軍項選取，可謂兵效多矣。',
    (10, 10): '諸囚徒並赦，惟故殺者不在赦例。',
}
# Overlapping Viet windows provide context at the joins. API results stay candidates.
BATCHES = ((1, 3, 186, 190), (4, 5, 190, 193), (6, 8, 192, 197), (9, 10, 196, 200))
NARROW_BATCHES = ((1, 1, 186, 187), (2, 2, 187, 189), (3, 3, 189, 190),
                  (4, 4, 190, 191), (5, 5, 191, 193), (6, 6, 192, 194),
                  (7, 7, 194, 196), (8, 8, 195, 197), (9, 9, 196, 198), (10, 10, 197, 200))

# Reviewed semantic matches with scan-backed Han and verbatim Excel spans.
# Start/end cues are inclusive. None means the entire source row.
ACCEPTED = (
    ((4, 4), '0190-004', 'người sinh ra không kể', None),
    ((4, 5), '0190-005', None, None),
    ((4, 6), '0190-006', None, None),
    ((10, 10), '0199-008', None, None),
)


def reviewed_han():
    target = HAN / 'reviewed'
    target.mkdir(exist_ok=True)
    units = []
    pending = []
    used_edits = set()
    for page in range(1, 11):
        with (HAN / 'segmented' / f'{page:04}-sentences.csv').open(encoding='utf-8-sig', newline='') as file:
            rows = list(csv.DictReader(file))
        for n, row in enumerate(rows, 1):
            key = page, n
            raw = row['text_zh']
            text = SCAN_TEXT.get(key, raw)
            parts = [text]
            for cue in CUT_BEFORE.get(key, ()):
                left, sep, right = parts.pop().partition(cue)
                if not sep or not content(left) or not content(right):
                    raise ValueError(f'Unknown cut {key}: {cue}')
                parts.extend((left.rstrip('，、； ') + '。', sep + right))
            for i, part in enumerate(parts):
                pending.append((page, key, row['id_zh'], part))
                if i == len(parts) - 1 and key in MERGE_AFTER:
                    used_edits.add(key)
                    continue
                start = pending[0][0]
                text = ''.join(p[3].rstrip('。！？') if j < len(pending)-1 else p[3]
                               for j, p in enumerate(pending))
                units.append({'id_zh': f'Cap01-R{start:03}-{len(units)+1:03}',
                              'han_page_start': start, 'han_page_end': page, 'text_zh': text,
                              'source_ids': ' '.join(dict.fromkeys(p[2] for p in pending)),
                              'review': 'scan_verified' if len(parts) == len(pending) == 1 and key in SCAN_TEXT
                              else 'boundary_review',
                              'key': pending[0][1]})
                pending.clear()
    if pending or used_edits != MERGE_AFTER:
        raise ValueError('Incomplete Han boundary edits')
    fields = ['id_zh', 'han_page_start', 'han_page_end', 'text_zh', 'source_ids', 'review']
    for page in range(1, 11):
        with (target / f'{page:04}-reviewed.csv').open('w', encoding='utf-8-sig', newline='') as file:
            writer = csv.DictWriter(file, fields, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(u for u in units if u['han_page_start'] == page)
    return units


def viet_rows():
    with VIET.open('rb') as source:
        workbook = load_workbook(source, read_only=True, data_only=True)
        rows = list(workbook['CAU_VIET'].values)
        workbook.close()
    return {r[0]: (r[1], r[2], r[4]) for r in rows[1:] if r[5] and isinstance(r[4], str)}


def clauses(rows, lo, hi):
    for id_, (first, last, text) in rows.items():
        if first > hi or last < lo:
            continue
        # Preserve commas inside money lists and split at clear clause boundaries.
        ends = [m.end() for m in re.finditer(r';|[:,](?=\s+(?:còn|nhưng|đến|ngoài ra|duy|lại)\b)', text, re.I)]
        start = 0
        for end in [*ends, len(text)]:
            trimmed = text[start:end].strip()
            if trimmed:
                left = start + len(text[start:end]) - len(text[start:end].lstrip())
                yield (id_, left, left + len(trimmed), trimmed)
            start = end


def api_steps(run):
    """Map text back to source when the API resegments an input line."""
    result = run['response']['data']['result']
    han, vi = run['han'], run['vi']
    vtext = ' '.join(v[3] for v in vi)
    offsets = []
    pos = 0
    for v in vi:
        offsets.append(pos)
        pos += len(v[3]) + 1
    steps = []
    for item in result:
        source_h = ' '.join((item.get('han_text') or '').split())
        source_v = ' '.join((item.get('vietnamese_text') or '').split())
        hs, he = item.get('han_start'), item.get('han_end')
        h = []
        if type(hs) is int and type(he) is int and 0 <= hs <= he < len(han):
            h = list(range(hs, he + 1))
            if source_h and content(source_h) != content(''.join(han[j]['text_zh'] for j in h)):
                h = []
        spans = []
        if source_v:
            start = vtext.find(source_v)
            if start >= 0 and vtext.find(source_v, start + 1) < 0:
                end = start + len(source_v)
                for pos, (id_, left, _, text) in zip(offsets, vi):
                    a, b = max(0, start - pos), min(len(text), end - pos)
                    if a < b:
                        spans.append((id_, left + a, left + b, text[a:b]))
        if h and spans:
            steps.append({'h': h, 'spans': spans, 'score': item.get('score')})
    run['unmapped_api_rows'] = len(result) - len(steps)
    return steps


def export(units, rows, runs):
    out = Workbook()
    labels = out.active
    labels.title = 'Alignment_Dataset'
    template = load_workbook(TEMPLATE, read_only=True)
    labels.append(next(template.active.values))
    template.close()
    candidates = out.create_sheet('API_Candidates')
    candidates.append(['batch', 'han_ids', 'vie_spans', 'chinese', 'vietnamese', 'api_score', 'review_status'])
    proven = set()
    for key, vi, start_cue, end_cue in ACCEPTED:
        h = next(u for u in units if u['key'] == key and u['review'] == 'scan_verified')
        id_ = 'Cap_01-VI-' + vi
        p, q, text = rows[id_]
        start = text.index(start_cue) if start_cue else 0
        end = text.index(end_cue, start) + len(end_cue) if end_cue else len(text)
        labels.append([f'C{h["han_page_start"]:03}_V{p:03}_{key[1]:03}', h['text_zh'], text[start:end],
                       0, 0, 0, '1-1', 0, 1, None,
                       f'{h["id_zh"]}; {id_}[{start}:{end}]; Hán so ảnh. Việt trích nguyên OCR.'])
        proven.add(h['id_zh'])
    for i, run in enumerate(runs, 1):
        for step in run.get('steps', []):
            han = [run['han'][j] for j in step['h']]
            vi = step['spans'] if 'spans' in step else [run['vi'][j] for j in step['v']]
            candidates.append([i, ' '.join(u['id_zh'] for u in han),
                               ' '.join(f'{v[0]}[{v[1]}:{v[2]}]' for v in vi),
                               '\n'.join(u['text_zh'] for u in han), '\n'.join(v[3] for v in vi), step['score'],
                               'has_reviewed_Han' if any(u['id_zh'] in proven for u in han) else 'pending'])
    for sheet in out:
        for row in sheet:
            for cell in row:
                if cell.data_type == 'f':
                    cell.data_type = 's'
        sheet.auto_filter.ref = sheet.dimensions
        sheet.freeze_panes = 'B2'
    out.save(OUTPUT)
    return len(proven), candidates.max_row - 1


def main():
    sys.stdout.reconfigure(errors='backslashreplace')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from-log', action='store_true', help='Rebuild Excel without calling the API')
    parser.add_argument('--narrow', action='store_true', help='Use one Han page per batch after a gateway timeout')
    args = parser.parse_args()
    rows = viet_rows()
    units = reviewed_han()
    batches = NARROW_BATCHES if args.narrow else BATCHES
    if args.from_log:
        runs = json.loads(LOG.read_text(encoding='utf-8'))['runs']
    else:
        runs = []
        token = os.getenv('SINONOM_TOKEN')
        previous = json.loads(LOG.read_text(encoding='utf-8')) if args.narrow and LOG.exists() else {}
        earlier = previous.get('earlier_errors', []) + [
            {'han_pages': r['han_pages'], 'error': r['error']} for r in previous.get('runs', []) if 'error' in r]
        for first, last, lo, hi in batches:
            if runs:
                time.sleep(0.5)
            h = [u for u in units if first <= u['han_page_start'] <= last]
            v = list(clauses(rows, lo, hi))
            run = {'han_pages': [first, last], 'vi_pages': [lo, hi], 'han': h, 'vi': v}
            runs.append(run)
            try:
                run['response'] = call_api([u['text_zh'] for u in h], [r[3] for r in v], token,
                                           timeout=45, retries=0)
                run['steps'] = api_steps(run)
                print(f'Han {first}-{last}: {len(run["steps"])} traceable API candidates', flush=True)
            except (RuntimeError, ValueError) as exc:
                run['error'] = str(exc)
                print(f'Han {first}-{last}: {exc}', flush=True)
                if 'HTTP 401' in str(exc) or 'HTTP 403' in str(exc) or not args.narrow:
                    break
        LOG.write_text(json.dumps({'planned_batches': len(batches), 'earlier_errors': earlier, 'runs': runs},
                                  ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    accepted, pending = export(units, rows, runs)
    print(f'{len(units)} Han units, {accepted} verified pairs, {pending} API candidate rows')
    attempted_pages = {page for run in runs for page in range(run['han_pages'][0], run['han_pages'][1] + 1)}
    return int(attempted_pages != set(range(1, 11)) or any('error' in run for run in runs))


if __name__ == '__main__':
    raise SystemExit(main())
