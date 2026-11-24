"""Replay alignment requests and isolate pacing and payload effects."""

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
from statistics import median
import time

import requests

from align_sinonom_api import API_URL
from batch_sentence_alignment import load_han, load_viet


HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'Cap01_0001-0010_alignment_auto_run.json'
OUTPUT = HERE / 'sentence_alignment_diagnostics.json'


def reconstruct(path):
    source = json.loads(path.read_text(encoding='utf-8'))
    han = {u.id: ' '.join(u.text.split()) for u in load_han(Path(source['han_dir']), *source['pages'])}
    vi = {u.id: u.text for u in load_viet(Path(source['viet_workbook']))[0]}
    result = []
    for n, r in enumerate(source['attempts'], 1):
        result.append({'number': n, 'original_ok': 'response' in r, 'viet_pages': r['viet_pages'],
                       'han': [han[k] for k in r['han_ids']], 'vi': [vi[k][a:b] for k, a, b in r['viet_spans']]})
    return result


def features(han, vi):
    h, v = len('\n'.join(han)), len('\n'.join(vi))
    return {'han_lines': len(han), 'vi_lines': len(vi), 'han_chars': h, 'vi_chars': v,
            'vi_han_ratio': round(v / h, 2), 'max_han_line': max(map(len, han)),
            'max_vi_line': max(map(len, vi))}


def trials(original):
    bad, good = original[0], original[11]
    assert not bad['original_ok'] and good['original_ok']
    for name, pause, sequence in [('slow_a', 4, (good, bad)), ('fast_a', .5, (good, bad)),
                                   ('fast_b', .5, (bad, good)), ('slow_b', 4, (bad, good))]:
        for i, original_case in enumerate(sequence):
            yield name, 'unchanged', original_case, original_case['han'], original_case['vi'], pause if i else 4
    for original_case in (bad, original[1]):
        h, v = original_case['han'], original_case['vi']
        middle = len(v) // 2
        for variant, hp, vp in [('vi_front', h, v[:middle]), ('vi_back', h, v[middle:]),
                                ('han_front', h[:len(h)//2], v), ('han_back', h[len(h)//2:], v)]:
            assert (hp == h) != (vp == v)
            yield 'payload', variant, original_case, hp, vp, 4


def probe(payload, token, timeout):
    before = time.perf_counter()
    try:
        # Start a new connection per call, matching the production API wrapper.
        with requests.Session() as session:
            response = session.post(API_URL, json=payload, timeout=(10, timeout), allow_redirects=False,
                                    headers={'Authorization': f'Bearer {token}', 'Accept': 'application/json',
                                             'User-Agent': 'Mozilla/5.0'})
    except requests.RequestException as exc:
        return {'seconds': round(time.perf_counter() - before, 3), 'error': type(exc).__name__, 'ok': False}
    try:
        body = response.json()
    except ValueError:
        body = None
    data = body if isinstance(body, dict) else {}
    info = data.get('message') if isinstance(data.get('message'), dict) else {}
    debug = info.get('debug_msg')
    try:
        nested = json.loads(debug) if isinstance(debug, str) else None
    except ValueError:
        nested = None
    matched = (data.get('data') or {}).get('result') if isinstance(data.get('data'), dict) else None
    headers = {k: v for k, v in response.headers.items()
               if k.lower() in {'retry-after', 'x-request-id', 'server', 'cf-ray'}}
    return {'seconds': round(time.perf_counter() - before, 3), 'http_status': response.status_code,
            'api_code': data.get('code'), 'inner_code': nested.get('code') if isinstance(nested, dict) else None,
            'debug': debug, 'headers': headers, 'ok': response.ok and data.get('is_success') is True and isinstance(matched, list),
            'result_rows': len(matched) if isinstance(matched, list) else None}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, default=SOURCE)
    p.add_argument('--out', type=Path, default=OUTPUT)
    p.add_argument('--dry-run', action='store_true')
    a = p.parse_args()
    old = reconstruct(a.source)
    profiles = [{'number': r['number'], 'original_ok': r['original_ok'], **features(r['han'], r['vi'])} for r in old]
    results = {'source': a.source.name, 'original_profiles': profiles, 'trials': []}
    for ok in (True, False):
        group = [r for r in profiles if r['original_ok'] == ok]
        print(('OLD OK' if ok else 'OLD ERROR'), len(group), {k: median(r[k] for r in group) for k in features(old[0]['han'], old[0]['vi'])})
    plan = list(trials(old))
    assert len(plan) == 16
    if a.dry_run:
        for name, variant, record, h, v, delay in plan:
            print(name, record['number'], variant, delay, len(h), len(v))
        return 0
    token = os.getenv('SINONOM_TOKEN', '').strip()
    if token.lower().startswith('bearer '):
        token = token[7:].strip()
    if not token or not a.out.parent.is_dir():
        p.error('Set SINONOM_TOKEN and choose an existing output parent')
    ended = None
    counts = Counter()
    for name, variant, record, h, v, delay in plan:
        if ended is not None:
            time.sleep(delay)
        idle = round(time.perf_counter() - ended, 3) if ended is not None else None
        payload = {'han': '\n'.join(h), 'vi': '\n'.join(v)}
        digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()
        r = probe(payload, token, timeout=22)
        ended = time.perf_counter()
        r.update(group=name, variant=variant, source_number=record['number'], idle_seconds=idle,
                 sha256=digest, same_han=h == record['han'], same_vi=v == record['vi'], **features(h, v))
        results['trials'].append(r)
        counts['ok' if r['ok'] else str(r.get('api_code') or r.get('http_status') or r.get('error'))] += 1
        results['counts'] = dict(counts)
        a.out.write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(len(results['trials']), name, record['number'], variant, idle, r.get('http_status'),
              r.get('api_code'), r['ok'], r['seconds'], flush=True)
        if r.get('http_status') in {401, 403, 429} or str(r.get('api_code')) in {'000401', '000403', '000429', '429'}:
            break
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
