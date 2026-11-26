"""Align Stage 03 Han CSVs with a Stage 02 Vietnamese workbook."""

import argparse
from collections import Counter, defaultdict, deque
import csv
from dataclasses import dataclass
from itertools import chain
import json
import math
import os
from pathlib import Path
import re
import time

from openpyxl import Workbook, load_workbook
from align_sinonom_api import call_api, alignment_type


CLAUSE = re.compile(r';|[,:](?=\s+(?:còn|nhưng|đến|ngoài ra|duy|lại|trừ)\b)', re.I)
TEMPLATE = Path(__file__).with_name('Sino_Vietnamese_Sentence_Alignment_Template.xlsx')
MAX_VI_SPLIT_DEPTH = 2


@dataclass(frozen=True)
class Unit:
    id: str
    first: int
    last: int
    text: str


@dataclass(frozen=True)
class Span:
    row: int
    start: int
    end: int
    text: str


def load_han(folder, start, end):
    rows, ids = [], set()
    files = sorted((p for p in folder.glob('*.csv') if re.match(r'^\d+', p.name)),
                   key=lambda p: int(re.match(r'^\d+', p.name)[0]))
    covered = set()
    for path in files:
        page = int(re.match(r'^\d+', path.name)[0])
        with path.open(encoding='utf-8-sig', newline='') as src:
            for r in csv.DictReader(src):
                first = int(r.get('han_page_start') or page)
                last = int(r.get('han_page_end') or first)
                if last < start or first > end:
                    continue
                id_, text = r['id_zh'], r['text_zh']
                if first > last or not text.strip() or not id_ or id_ in ids:
                    raise ValueError(f'Invalid or duplicate Han unit in {path}: {id_}')
                rows.append(Unit(id_, first, last, text))
                ids.add(id_)
                covered.update(range(first, last + 1))
    missing = sorted(set(range(start, end + 1)) - covered)
    if missing:
        raise ValueError(f'No Han input for pages: {missing}')
    return rows


def table(wb, sheet):
    data = wb[sheet].values
    fields = next(data)
    return [dict(zip(fields, row)) for row in data]


def load_viet(path):
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        units = [Unit(r['id_vi'], r['viet_page_start'], r['viet_page_end'], r['text_vi'])
                 for r in table(wb, 'CAU_VIET') if r['dung_de_ghep'] and r['text_vi']]
        map_rows = [r for r in table(wb, 'TRANG_VIET') if isinstance(r['viet_pdf_page'], int)]
    finally:
        wb.close()
    if not units or not map_rows or len({u.id for u in units}) != len(units):
        raise ValueError('Invalid or empty Vietnamese workbook')
    return units, map_rows


def window(map_rows, first, last, margin):
    anchors = defaultdict(list)
    for r in map_rows:
        for entry in str(r.get('han_trang_co_moc') or '').split(','):
            if m := re.match(r'\s*(\d+)', entry):
                anchors[int(m[1])].append(r['viet_pdf_page'])
    pages = sorted(anchors)
    bounds = [r['viet_pdf_page'] for r in map_rows]

    def estimate(page):
        if page in anchors:
            return min(anchors[page]), max(anchors[page])
        before = max((p for p in pages if p < page), default=None)
        after = min((p for p in pages if p > page), default=None)
        if before is not None and after is not None:
            lo, hi = max(anchors[before]), min(anchors[after])
            if lo <= hi:
                x = lo + (hi - lo) * (page - before) / (after - before)
                return math.floor(x), math.ceil(x)
        possible = [r['viet_pdf_page'] for r in map_rows
                    if isinstance(r.get('han_cua_so_tu'), int) and isinstance(r.get('han_cua_so_den'), int)
                    and r['han_cua_so_tu'] <= page <= r['han_cua_so_den']]
        if not possible:
            raise ValueError(f'Vietnamese workbook has no window for Han page {page}')
        return min(possible), max(possible)

    estimates = [estimate(p) for p in range(first, last + 1)]
    return max(min(bounds), min(x[0] for x in estimates) - margin), min(max(bounds), max(x[1] for x in estimates) + margin)


def pieces(viet, lo, hi):
    for i, u in enumerate(viet):
        if u.first > hi or u.last < lo:
            continue
        start = 0
        for end in chain((m.end() for m in CLAUSE.finditer(u.text)), (len(u.text),)):
            raw = u.text[start:end]
            if raw.strip():
                left = start + len(raw) - len(raw.lstrip())
                right = left + len(raw.strip())
                yield Span(i, left, right, u.text[left:right])
            start = end


def resolve(texts, start, end, snippet):
    """Find exact returned text and retain offsets, even after API resegmentation."""
    positions = []
    for raw in texts:
        pos = [i for m in re.finditer(r'\S+', raw) for i in chain(range(m.start(), m.end()), (m.end(),))]
        positions.append(pos[:-1])
    texts = [' '.join(t.split()) for t in texts]
    text = ' '.join(texts)
    substring = ' '.join((snippet or '').split())
    start_at = None
    if type(start) is int and type(end) is int and 0 <= start <= end < len(texts):
        if substring == ' '.join(texts[start:end + 1]):
            start_at = sum(len(t) + 1 for t in texts[:start])
    if start_at is None and substring:
        found = text.find(substring)
        if found >= 0 and text.find(substring, found + 1) == -1:
            start_at = found
    if start_at is None:
        return []
    stop, pos = start_at + len(substring), 0
    result = []
    for i, text in enumerate(texts):
        a, b = max(0, start_at - pos), min(len(text), stop - pos)
        if a < b:
            result.append((i, positions[i][a], positions[i][b - 1] + 1))
        pos += len(text) + 1
    return result


def links(response, batch, han, spans):
    htexts = [' '.join(han[i].text.split()) for i in batch]
    vtexts = [s.text for s in spans]
    for row in response['data']['result']:
        hs = resolve(htexts, row.get('han_start'), row.get('han_end'), row.get('han_text'))
        vs = resolve(vtexts, row.get('vi_start'), row.get('vi_end'), row.get('vietnamese_text'))
        intact = hs and all(a == 0 and b == len(htexts[i]) for i, a, b in hs)
        vi_only = row.get('han_start') == row.get('han_end') == -1 and not row.get('han_text')
        if vs and (intact or vi_only):
            score = row.get('score')
            yield {'han': [batch[i] for i, _, _ in hs],
                   'vi': [Span(spans[i].row, spans[i].start + a, spans[i].start + b,
                               spans[i].text[a:b]) for i, a, b in vs],
                   'score': score if isinstance(score, (float, int)) and math.isfinite(score) else None}


def select(candidates):
    """Keep a monotone set of non-overlapping bilingual source ranges."""
    chosen = []
    for link in sorted((r for r in candidates if r['han']),
                       key=lambda r: (-(r['score'] if r['score'] is not None else -1),
                                      -len(r['han']), r['han'][0])):
        h, v = link['han'], link['vi']
        key = (h[0], h[-1], (v[0].row, v[0].start), (v[-1].row, v[-1].end))
        if all((key[1] < k[0] and key[3] <= k[2]) or (k[1] < key[0] and k[3] <= key[2]) for k, _ in chosen):
            chosen.append((key, link))
    return [link for _, link in sorted(chosen)]


def run(han, viet, map_rows, args, api=call_api):
    queue = deque((list(range(i, min(i + args.batch_size, len(han)))), None, 0, None)
                  for i in range(0, len(han), args.batch_size))
    candidates, attempts = [], []
    while queue and len(attempts) < args.max_calls:
        batch, spans, depth, parent = queue.popleft()
        if spans is None:
            first, last = han[batch[0]].first, max(han[i].last for i in batch)
            lo, hi = window(map_rows, first, last, args.margin)
            spans = list(pieces(viet, lo, hi))
            # Center the capped window within the inferred Vietnamese range.
            if len(spans) > args.max_viet_units:
                i = (len(spans) - args.max_viet_units) // 2
                spans = spans[i:i + args.max_viet_units]
        if not spans:
            continue
        if attempts:
            time.sleep(args.delay)
        record = {'han_ids': [han[i].id for i in batch],
                  'viet_pages': [min(viet[s.row].first for s in spans), max(viet[s.row].last for s in spans)],
                  'vi_split_depth': depth, 'parent_attempt': parent,
                  'viet_spans': [[viet[s.row].id, s.start, s.end] for s in spans]}
        attempts.append(record)
        try:
            response = api([' '.join(han[i].text.split()) for i in batch], [s.text for s in spans],
                           os.getenv('SINONOM_TOKEN'), timeout=args.timeout, retries=0)
            record['response'] = response
            kept = list(links(response, batch, han, spans))
            record['traceable_pairs'] = sum(bool(r['han']) for r in kept)
            candidates.extend(kept)
        except (RuntimeError, ValueError) as exc:
            message = str(exc)
            record['error'] = message
            if re.search(r'HTTP (?:401|403|429)|(?:401|403|429) Client Error|00040[13]|000429|Thiếu token', message):
                break
            if '000500' in message and len(spans) > 1 and depth < MAX_VI_SPLIT_DEPTH:
                mid = len(spans) // 2
                # Give all initial batches a turn before any retry.
                queue.extend((batch, part, depth + 1, len(attempts)) for part in (spans[:mid], spans[mid:]))
    return candidates, attempts


def export(path, han, viet, candidates):
    selected = select(candidates)
    wb = Workbook()
    ws = wb.active
    ws.title = 'Alignment_Dataset'
    with TEMPLATE.open('rb') as f:
        template = load_workbook(f, read_only=True)
        headers = next(template['Alignment_Dataset'].values)
        template.close()
    ws.append(headers)
    cs = wb.create_sheet('API_Candidates')
    cs.append(['Han_IDs', 'Viet_Spans', 'Score', 'Status', 'Chinese', 'Vietnamese'])
    covered = {i for r in selected for i in r['han']}
    counts = Counter()

    def desc(r):
        return '; '.join(f'{viet[s.row].id}[{s.start}:{s.end}]' for s in r['vi'])

    for r in candidates:
        status = 'selected' if r in selected else 'viet_only_context' if not r['han'] else 'alternative'
        cs.append(['; '.join(han[i].id for i in r['han']), desc(r), r['score'], status,
                   ' '.join(han[i].text for i in r['han']), ' '.join(s.text for s in r['vi'])])
    rows = [*selected, *({'han': [i], 'vi': [], 'score': None} for i in range(len(han)) if i not in covered)]
    for r in sorted(rows, key=lambda r: r['han'][0]):
        h, v = r['han'], r['vi']
        hp = f'C{han[h[0]].first:03}'
        vp = f'V{viet[v[0].row].first:03}' if v else 'VX'
        counts[hp, vp] += 1
        note = (f'Hán: {", ".join(han[i].id for i in h)}; Việt: {desc(r)}; API score={r["score"]}; chưa duyệt ý'
                if v else f'Hán: {han[h[0]].id}; chưa có vế Việt truy được về nguồn')
        ws.append([f'{hp}_{vp}_{counts[hp, vp]:03}', ' '.join(han[i].text for i in h),
                   ' '.join(s.text for s in v) if v else None, None, None, 0 if v else 1,
                   alignment_type(h, v), None, None, None, note])
    for sheet in wb:
        sheet.freeze_panes = 'A2'
        sheet.auto_filter.ref = sheet.dimensions
        for row in sheet:
            for cell in row:
                if cell.data_type == 'f':
                    cell.data_type = 's'
    wb.save(path)
    return {'han_units': len(han), 'matched_han_units': len(covered), 'selected_pairs': len(selected),
            'unmatched_han_units': len(han) - len(covered), 'api_candidates': len(candidates),
            'label_1': 0}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--han-dir', type=Path, required=True)
    p.add_argument('--viet-xlsx', type=Path, required=True)
    p.add_argument('--pages', nargs=2, type=int, metavar=('FIRST', 'LAST'), required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--batch-size', type=int, default=8, help='Han units per request')
    p.add_argument('--margin', type=int, default=1, help='Extra Viet pages around inferred window')
    p.add_argument('--max-viet-units', type=int, default=16)
    p.add_argument('--max-calls', type=int, default=24)
    p.add_argument('--delay', type=float, default=0.5)
    p.add_argument('--timeout', type=float, default=45)
    a = p.parse_args()
    if not (0 < a.pages[0] <= a.pages[1] and min(a.batch_size, a.max_calls, a.max_viet_units, a.timeout) > 0
            and a.delay >= 0 and a.margin >= 0):
        p.error('Invalid pages or API limits')
    if not os.getenv('SINONOM_TOKEN', '').strip():
        p.error('Set SINONOM_TOKEN before running alignment')
    if not a.output.parent.is_dir() or a.output.suffix.lower() != '.xlsx':
        p.error('The output must be an .xlsx file in an existing directory')
    han = load_han(a.han_dir, *a.pages)
    viet, page_map = load_viet(a.viet_xlsx)
    candidates, attempts = run(han, viet, page_map, a)
    summary = export(a.output, han, viet, candidates)
    summary.update(api_calls=len(attempts), api_errors=sum('error' in r for r in attempts),
                   api_responses_without_pairs=sum('response' in r and not r['traceable_pairs'] for r in attempts))
    log = a.output.with_name(a.output.stem + '_run.json')
    log.write_text(json.dumps({'han_dir': str(a.han_dir), 'viet_workbook': str(a.viet_xlsx), 'pages': a.pages,
                               'summary': summary, 'attempts': attempts}, ensure_ascii=False, indent=2) + '\n',
                   encoding='utf-8')
    print(json.dumps(summary))
    return 0 if summary['selected_pairs'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
