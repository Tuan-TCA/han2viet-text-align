"""Evaluate SinoNom on the positive pairs in ground_truth_draft.csv."""

import argparse
from collections import Counter, defaultdict
import csv
from difflib import SequenceMatcher
from io import BytesIO
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import unicodedata

import requests

OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(OUT.parent))
import batch_sentence_alignment as batch
from batch_han_sentence_split import URL, content, split_result
from cpu_alignment_benchmark import checked_api

ROOT = OUT.parents[1]
PAGES = (1, 2, 3)
FILES = ('summary.json', 'predictions.csv', 'pair_review.csv')


def load_viet(path):
    try:
        return batch.load_viet(path)
    except PermissionError:
        if os.name != 'nt':
            raise
        # Excel may require readers to share write/delete access to its file.
        code = ("$ErrorActionPreference='Stop'; "
                "$s=[IO.File]::Open($env:CV16_VIET_BOOK,'Open','Read',"
                "([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete)); "
                "try {$s.CopyTo([Console]::OpenStandardOutput())} finally {$s.Dispose()}")
        data = subprocess.check_output(['powershell.exe', '-NoProfile', '-Command', code],
                                       env={**os.environ, 'CV16_VIET_BOOK': str(path.resolve())})
        return batch.load_viet(BytesIO(data))


def raw_page(cap, page):
    path = ROOT / f'02_ocr_tho/Cap_{cap:02}/HAN/pages/Cap{cap:02}-{page:03}.json'
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    rows = sorted(data['rows'], key=lambda row: row['segment'])
    if (data['info']['cap'], data['info']['page']) != (f'Cap_{cap:02}', page):
        raise ValueError(f'Invalid page metadata: {path.name}')
    if [r['segment'] for r in rows] != list(range(1, len(rows) + 1)):
        raise ValueError(f'Invalid OCR segment sequence: {path.name}')
    return ''.join(''.join(r['han'].split()) for r in rows)


def segment(pages, token):
    units, logs = [], []
    with requests.Session() as session:
        session.headers.update({'Authorization': f'Bearer {token}', 'Accept': 'application/json',
                                'User-Agent': 'Mozilla/5.0'})
        for page, text in pages.items():
            if logs:
                time.sleep(0.5)
            info = {'page': page, 'status': 'failed'}
            logs.append(info)
            try:
                response = session.post(URL, json={'text': text, 'ocr_id': 1, 'genre': 'history',
                                                  'punctuation_group': 'all'}, timeout=(10, 90),
                                        allow_redirects=False)
                info['http_status'] = response.status_code
                if response.status_code in (401, 403, 429):
                    break
                body = response.json()
                info['api_code'] = body.get('code')
                if response.status_code != 200 or body.get('is_success') is not True:
                    continue
                lines = [line for line in split_result((body.get('data') or {}).get('sentences')) if content(line)]
                if not lines or content(''.join(lines)) != content(text):
                    info['status'] = 'content_mismatch'
                    continue
                units.extend(batch.Unit(f'Cap02-{page:03}-S{i:03}', page, page, line)
                             for i, line in enumerate(lines, 1))
                info.update(status='ok', units=len(lines))
            except (requests.RequestException, ValueError, AttributeError) as exc:
                info['error'] = type(exc).__name__
    return units, logs


def norm_vi(text):
    return content(unicodedata.normalize('NFC', text)).casefold()


def at(haystack, needle):
    start = haystack.find(needle)
    if needle and start >= 0 and haystack.find(needle, start + 1) < 0:
        return range(start, start + len(needle))
    return ()


def han_positions(han, raw):
    original = [(page, i) for page, text in raw.items() for i in range(len(text))]
    # A reviewed unit can cross pages. Project it to OCR coordinates without
    # treating reviewed substitutions or punctuation as source characters.
    htexts = [content(h.text) for h in han]
    joined = ''.join(htexts)
    source = ''.join(raw.values())
    mapping = {}
    for a, b, size in SequenceMatcher(None, joined, source, autojunk=False).get_matching_blocks():
        mapping.update((a + j, original[b + j]) for j in range(size))
    result, pos = [], 0
    for text in htexts:
        result.append({mapping[i] for i in range(pos, pos + len(text)) if i in mapping})
        pos += len(text)
    return result


def gold_positions(row, raw, vtext):
    page = int(row['han_page'])
    a, b = int(row['han_start']), int(row['han_end'])
    h = content(row['han_ocr'])
    # Some draft offsets count spaces; require the OCR text to verify the range.
    hs = range(a, b) if raw[page][a:b] == h else at(raw[page], h)
    ids = re.findall(r'Cap_\d+-VI-\d+-\d+', row['vi_ids'])
    if not ids or any(i not in vtext for i in ids):
        return {(page, i) for i in hs}, set()
    vi_index = [(key, i) for key in ids for i in range(len(vtext[key]))]
    vs = at(''.join(vtext[key] for key in ids), norm_vi(row['vi_ocr']))
    return {(page, i) for i in hs}, {vi_index[i] for i in vs}


def vi_positions(viet, spans):
    return {(viet[i].id, j) for i, a, b in spans
            for j in range(len(norm_vi(viet[i].text[:a])), len(norm_vi(viet[i].text[:b])))}


def compare(gh, gv, predictions):
    nearby = [(pid, h, v) for pid, h, v in predictions if gh & h and gv & v]
    exact = [p for p, h, v in nearby if gh == h and gv == v]
    if exact:
        return 'exact', exact
    merged = [p for p, h, v in nearby if gh <= h and gv <= v]
    if merged:
        return 'boundary_merge_candidate', merged
    inside = [(p, h, v) for p, h, v in nearby if h <= gh and v <= gv]
    if inside and set.union(*(h for _, h, _ in inside)) == gh and set.union(*(v for _, _, v in inside)) == gv:
        return 'boundary_split_candidate', [p for p, _, _ in inside]
    return ('partial_overlap' if nearby else 'not_recovered'), [p for p, _, _ in nearby]


def write_csv(name, rows, fields):
    with (OUT / name).open('x', encoding='utf-8-sig', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    if any((OUT / name).exists() for name in FILES):
        raise SystemExit('Output already exists; preserve it before rerunning.')
    token = os.getenv('SINONOM_TOKEN', '').strip()
    if token.lower().startswith('bearer '):
        token = token[7:].strip()
    if not token:
        raise SystemExit('Set SINONOM_TOKEN.')
    with (ROOT / 'ground_truth_draft.csv').open(encoding='utf-8-sig', newline='') as file:
        draft = list(csv.DictReader(file))
    assert len({r['pair_id'] for r in draft}) == len(draft)
    positives = [r for r in draft if r['label'] == 'TRUE']
    assert len(positives) == 21

    result = {'model': 'SinoNom', 'draft_labels': Counter(r['label'] for r in draft), 'caps': {}}
    reviews, exported = [], []
    for cap in (1, 2):
        pages = {p: raw_page(cap, p) for p in PAGES}
        raw = {p: content(text) for p, text in pages.items()}
        viet_dir = ROOT / f'02_ocr_tho/Cap_{cap:02}/VIET'
        book = viet_dir / {1: 'VIET_0186-0251.xlsx', 2: 'VIET_0001-0105.xlsx'}[cap]
        viet, mapping = load_viet(book)
        vtext = {u.id: norm_vi(u.text) for u in viet}
        split_log = []
        if cap == 1:
            han = batch.load_han(ROOT / '03_text_sach/Cap_01/HAN/reviewed', 1, 3)
        else:
            han, split_log = segment(pages, token)
        # Drop missing pages from the projection, not from the gold reference.
        hp = han_positions(han, {p: raw[p] for p in PAGES if cap == 1 or
                                any(log['page'] == p and log['status'] == 'ok' for log in split_log)})
        h_by_id = {u.id: hp[i] for i, u in enumerate(han)}
        v_by_id = {u.id: i for i, u in enumerate(viet)}
        opts = argparse.Namespace(batch_size=8, margin=1, max_viet_units=16, max_calls=12, delay=.5, timeout=22)
        run_error = None
        try:
            candidates, attempts = batch.run(han, viet, mapping, opts, api=checked_api)
        except ValueError as exc:
            candidates, attempts, run_error = [], [], str(exc)
        evaluated = []
        for i, row in enumerate(batch.select(candidates), 1):
            pid = f'C{cap:02}-P{i:03}'
            spans = [(s.row, s.start, s.end) for s in row['vi']]
            evaluated.append((pid, set.union(*(hp[j] for j in row['han'])), vi_positions(viet, spans)))
            exported.append({'prediction_id': pid, 'cap': cap,
                             'han_ids': ' '.join(han[j].id for j in row['han']),
                             'viet_spans': json.dumps([(viet[j].id, a, b) for j, a, b in spans]),
                             'han_text': ' '.join(han[j].text for j in row['han']),
                             'viet_text': ' '.join(s.text for s in row['vi']), 'score': row['score']})
        request_regions = []
        for attempt in attempts:
            attempt.pop('response', None)
            ah = set.union(*(h_by_id[i] for i in attempt['han_ids']))
            av = vi_positions(viet, [(v_by_id[i], a, b) for i, a, b in attempt['viet_spans']])
            request_regions.append((ah, av, 'error' not in attempt))
        statuses, visibility = defaultdict(Counter), Counter()
        annotations = defaultdict(list)
        for row in (r for r in draft if int(r['cap']) == cap and r['han_page'] and
                    r['han_ocr'] and r['vi_ocr'] and r['label'] in ('TRUE', 'UNCERTAIN')):
            gh, gv = gold_positions(row, raw, vtext)
            sent = [(h, v, ok) for h, v, ok in request_regions if gh & h and gv & v]
            successful = [(h, v) for h, v, ok in sent if ok]
            if not gh or not gv:
                status, pids, access = 'reference_unmapped', [], 'reference_unmapped'
            else:
                status, pids = compare(gh, gv, evaluated)
                if not sent:
                    access = 'not_co_exposed'
                elif not successful:
                    access = 'api_error_only'
                elif gh <= set.union(*(h for h, _ in successful)) and gv <= set.union(*(v for _, v in successful)):
                    access = 'full_in_successful_requests'
                else:
                    access = 'partial_in_successful_requests'
            statuses[row['label']][status] += 1
            if row['label'] == 'TRUE':
                visibility[access] += 1
            reviews.append({**row, 'result': status, 'request_coverage': access, 'prediction_ids': ' '.join(pids)})
            for pid in pids:
                annotations[pid].append(f"{row['pair_id']}:{row['label']}:{status}")
        for item in exported:
            if item['cap'] == cap:
                item['draft_overlap'] = ' '.join(annotations[item['prediction_id']]) or 'unverified'
        result['caps'][str(cap)] = {'han_units': len(han), 'predictions': len(evaluated),
                                   'split_calls': len(split_log), 'split_log': split_log,
                                   'alignment_calls': len(attempts), 'alignment_errors': sum('error' in a for a in attempts),
                                   'alignment_run_error': run_error, 'attempts': attempts,
                                   'draft_results': statuses, 'true_request_coverage': visibility}

    assert {r['pair_id'] for r in reviews if r['label'] == 'TRUE'} == {r['pair_id'] for r in positives}
    assert sum(c['split_calls'] for c in result['caps'].values()) <= 3
    assert sum(c['alignment_calls'] for c in result['caps'].values()) <= 24
    result['true_results'] = Counter(r['result'] for r in reviews if r['label'] == 'TRUE')
    write_csv('predictions.csv', exported, ['prediction_id', 'cap', 'han_ids', 'viet_spans', 'han_text',
                                           'viet_text', 'score', 'draft_overlap'])
    write_csv('pair_review.csv', reviews, [*draft[0], 'result', 'request_coverage', 'prediction_ids'])
    with (OUT / 'summary.json').open('x', encoding='utf-8') as file:
        json.dump(result, file, ensure_ascii=False, indent=2)
        file.write('\n')
    print(json.dumps({cap: {k: v for k, v in item.items() if k != 'attempts'}
                      for cap, item in result['caps'].items()}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
