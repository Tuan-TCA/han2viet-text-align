"""Try two consecutive Han units against two traceable Vietnamese spans."""

import argparse
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import re
import time
import unicodedata

from batch_sentence_alignment import call_api, export, links, load_han, load_viet, pieces, select, window


NAMES = {'順化': 'thuan hoa', '廣順': 'thuan quang', '順廣': 'thuan quang',
         '廣南': 'quang nam', '富春': 'phu xuan', '升華': 'thang hoa', '富洲': 'phu chau',
         '明靈': 'minh lanh', '海陵': 'hai lang', '登昌': 'dang xuong', '富安': 'phu yen',
         '廣義': 'quang ngai', '洪德': 'hong duc', '景治': 'canh tri', '阮氏': 'ho nguyen',
         '戶部': 'ho bo', '吏部': 'lai bo', '禮部': 'le bo', '吏': 'lai', '故殺': 'co sat',
         '甲申': 'giap than', '甲子': 'giap ty', '庚申': 'canh than', '丙戌': 'binh tuat',
         '己丑': 'ky suu'}
DIGITS = dict(zip('零一二三四五六七八九', range(10))) | {'兩': 2}
UNITS = {'十': 10, '百': 100, '千': 1000, '萬': 10000}


def norm(text):
    return ''.join(c for c in unicodedata.normalize('NFD', text.lower().replace('đ', 'd'))
                   if not unicodedata.combining(c))


def han_numbers(text):
    for match in re.findall(r'[零一二三四五六七八九兩十百千萬]+', text):
        total = section = digit = 0
        for c in match:
            if c in DIGITS:
                digit = DIGITS[c]
            elif c == '萬':
                total += (section + digit or 1) * 10000
                section = digit = 0
            else:
                section += (digit or 1) * UNITS[c]
                digit = 0
        yield total + section + digit


def evidence(han, vi):
    vi = norm(vi)
    numbers = {int(s.replace('.', '')) for s in re.findall(r'\d+(?:\.\d{3})*', vi)}
    return (sum(2 if n >= 100 else 0.7 if n >= 10 else 0.12 for n in set(han_numbers(han)) & numbers)
            + sum((1.7 if len(k) > 1 else .2) for k, v in NAMES.items()
                  if k in han and re.search(rf'\b{v}\b', vi)))


def audit_sample(han):
    pages = sorted({u.first for u in han})
    result = []
    for page in pages:
        ids = [u.id for u in han if u.first == page]
        if len(ids) < 2:
            raise ValueError(f'Need at least two units on Han page {page} for the fixed sample')
        result.extend(ids[i] for i in (len(ids) // 3, len(ids) * 2 // 3))
    if len(result) != len(set(result)):
        raise ValueError('Duplicate audit unit')
    return result


def groups(n):
    if n < 2:
        raise ValueError('2×2 needs at least two Han units')
    return [[min(i, n - 2), min(i + 1, n - 1)] for i in range(0, n, 2)]


def rank_windows(han, viet, page_map, group):
    first, last = han[group[0]].first, han[group[1]].last
    lo, hi = window(page_map, first, last, 2)
    spans = list(pieces(viet, lo, hi))
    target_l, target_h = window(page_map, first, last, 0)
    on_page = [i for i, u in enumerate(han) if first <= u.first <= last]
    fraction = sum(on_page.index(i) / max(1, len(on_page) - 1) for i in group) / 2
    target = target_l - .5 + (target_h - target_l + 1) * fraction
    scored = []
    for i, (a, b) in enumerate(zip(spans, spans[1:])):
        v = (a.text, b.text)
        ords = [j for j, s in enumerate(spans) if viet[s.row].first == viet[a.row].first]
        within = ords.index(i) / max(1, len(ords) - 1) - .5
        location = viet[a.row].first + within
        score = (sum(evidence(han[j].text, s) for j, s in zip(group, v))
                 + .25 * evidence(' '.join(han[j].text for j in group), ' '.join(v))
                 - 1.35 * abs(target - location))
        scored.append((score, i, [a, b]))
    return sorted(scored, key=lambda item: (-item[0], item[1]))


def run(han, viet, page_map, retries, delay, api=call_api):
    attempts, candidates, fallback = [], [], []
    stopped = False

    def send(group, choice, previous=None):
        nonlocal stopped
        rank, _, spans = choice
        h, v = [' '.join(han[i].text.split()) for i in group], [s.text for s in spans]
        if len(h) != 2 or len(v) != 2 or not all(h + v) or any('\n' in line or '\r' in line for line in h + v):
            raise ValueError('Invalid 2×2 input')
        record = {'han_ids': [han[i].id for i in group], 'viet_spans': [asdict(s) | {'id': viet[s.row].id} for s in spans],
                  'window_score': rank, 'retry_of': previous}
        if attempts:
            time.sleep(delay)
        attempts.append(record)
        try:
            result = api(h, v, os.getenv('SINONOM_TOKEN'), timeout=22, retries=0)
            record['response'] = result
            found = list(links(result, group, han, spans))
            candidates.extend(found)
            valid = [r for r in found if r['han']]
            record['traceable_pairs'] = len(valid)
            covered = len({i for r in valid for i in r['han']})
            score = min((r['score'] or 0.0 for r in valid), default=0.0)
            return (2 - covered) + int(score < .15)
        except (RuntimeError, ValueError) as exc:
            record['error'] = str(exc)
            stopped = bool(re.search(r'(?<!\d)(?:401|403|429|000401|000403|000429)(?!\d)', str(exc)))
            return 4

    for group in groups(len(han)):
        options = rank_windows(han, viet, page_map, group)
        if not options:
            continue
        priority = send(group, options[0])
        if stopped:
            break
        if priority and len(options) > 1:
            neighbor = next((x for x in options[1:] if abs(x[1] - options[0][1]) == 1), options[1])
            fallback.append((priority, len(attempts), group, neighbor))
    if not stopped:
        for _, parent, group, choice in sorted(fallback, key=lambda r: (-r[0], r[1]))[:retries]:
            send(group, choice, parent)
            if stopped:
                break
    return candidates, attempts


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--han-dir', type=Path, required=True)
    ap.add_argument('--viet-xlsx', type=Path, required=True)
    ap.add_argument('--pages', type=int, nargs=2, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--retries', type=int, default=24)
    ap.add_argument('--delay', type=float, default=.5)
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    if not (0 <= a.retries <= 24 and a.delay >= .5 and 0 < a.pages[0] <= a.pages[1]):
        ap.error('Invalid retry budget, delay or page range')
    han = load_han(a.han_dir, *a.pages)
    viet, page_map = load_viet(a.viet_xlsx)
    sample = audit_sample(han)
    if a.dry_run:
        print(json.dumps({'groups': len(groups(len(han))), 'audit_sample': sample}))
        assert all(rank_windows(han, viet, page_map, g) for g in groups(len(han)))
        return
    if not a.output.parent.is_dir() or a.output.suffix.lower() != '.xlsx' or not os.getenv('SINONOM_TOKEN', '').strip():
        ap.error('Need SINONOM_TOKEN and an .xlsx output in an existing directory')
    log = a.output.with_name(a.output.stem + '_run.json')
    report = {'pages': a.pages, 'viet_workbook': str(a.viet_xlsx), 'audit_sample': sample, 'attempts': []}
    log.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    candidates, attempts = run(han, viet, page_map, a.retries, a.delay)
    unique = {(tuple(r['han']), tuple(r['vi'])): r for r in sorted(candidates, key=lambda x: x['score'] or 0)}
    chosen = select(list(unique.values()))
    summary = export(a.output, han, viet, list(unique.values()))
    summary.update(api_calls=len(attempts), api_errors=sum('error' in r for r in attempts),
                   retry_calls=sum(r['retry_of'] is not None for r in attempts))
    report.update(summary=summary, attempts=attempts,
                  selected=[{'han_ids': [han[i].id for i in r['han']], 'score': r['score'],
                             'viet': [asdict(s) | {'id': viet[s.row].id} for s in r['vi']]} for r in chosen])
    log.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
