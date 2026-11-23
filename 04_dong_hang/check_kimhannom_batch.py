r"""Replay saved Kim Hán Nôm responses and print the first candidate payload.

From the repo root: .\.venv\Scripts\python.exe -B 04_dong_hang/check_kimhannom_batch.py
Use --details for per-link provenance. No API client is used.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
CAP = ROOT / '03_text_sach/Cap_01'
LOG = Path(__file__).with_name('Cap01_Trang1_first2Han_api_calls.jsonl')


def compact(text):
    return ''.join(text.split())


def historical_sources(han, records):
    h = [(key, len(text)-len(text.lstrip()), text.strip()) for key, text in han]
    v = []
    for rec in records:
        text = rec['text_vi']
        stripped = text.strip()
        offset = len(text) - len(text.lstrip())
        for piece in re.split(r'(?<=[.;?!,])\s+', stripped):
            if piece:
                start = text.index(piece, offset)
                v.append((rec['id_vi'], start, piece))
                offset = start + len(piece)
    return {'han': h, 'vi': v}


def locate_payload(text, source):
    """Require a unique exact sequence of submitted lines in the source."""
    lines = text.splitlines()
    matches = []
    candidates = [t for _, _, t in source]
    for i in range(len(source)-len(lines)+1):
        if lines and candidates[i:i+len(lines)] == lines:
            matches.append(i)
    if len(matches) != 1:
        return None, 'ambiguous_payload' if matches else 'payload_not_found'
    i = matches[0]
    return source[i:i+len(lines)], None


def source_spans(positions):
    spans = []
    for key, offset in positions:
        if spans and key == spans[-1]['id']:
            spans[-1]['end'] = offset+1
        else:
            spans.append(dict(id=key, start=offset, end=offset+1))
    return spans


def map_side(payload, source, returned):
    submitted, issue = locate_payload(payload, source)
    if issue:
        return [dict(status=issue, spans=[]) for _ in returned], None
    chars, positions = [], []
    for key, start, text in submitted:
        for i, c in enumerate(text, start):
            if not c.isspace():
                chars.append(c)
                positions.append((key, i))
    full = ''.join(chars)
    groups = [compact(t) if isinstance(t, str) else None for t in returned]
    complete = all(g is not None for g in groups) and ''.join(groups) == full
    cursor, results = 0, []
    for group in groups:
        if group is None:
            results.append(dict(status='invalid_text_field', spans=[]))
        elif not group:
            results.append(dict(status='empty_side', spans=[]))
        else:
            # Complete reconstruction fixes each boundary, including repeated
            # punctuation. Otherwise require a unique match after the last
            # verified span, and allow unconsumed source text for review.
            first = cursor if complete else full.find(group, cursor)
            if first < 0:
                results.append(dict(status='returned_text_not_found', spans=[]))
            elif not complete and full.find(group, first+1) >= 0:
                results.append(dict(status='ambiguous_returned_text', spans=[]))
            else:
                cursor = first+len(group)
                results.append(dict(status='mapped', spans=source_spans(positions[first:cursor])))
    return results, complete


def replay(log, source, details=False):
    counts, coverage, review = Counter(), Counter(), []
    requests = links = 0
    with log.open(encoding='utf-8-sig') as f:
        for line in f:
            if not line.strip():
                continue
            req = json.loads(line)
            requests += 1
            number = req['request']
            envelope = req.get('response') or {}
            groups = (envelope.get('data') or {}).get('result')
            if not req.get('ok') or not isinstance(groups, list) or not groups:
                review.append(dict(request=number, reasons=['no_successful_result']))
                continue
            mapped = {}
            reasons = []
            for lang, field in (('han', 'han_text'), ('vi', 'vietnamese_text')):
                mapped[lang], complete = map_side(req['payload'][lang], source[lang],
                                                  [g.get(field) for g in groups])
                if complete:
                    coverage[lang] += 1
                else:
                    reasons.append(f'{lang}_response_does_not_reconstruct_payload')
            for i, group in enumerate(groups):
                links += 1
                h, v = mapped['han'][i], mapped['vi'][i]
                status = 'mapped' if h['status'] == v['status'] == 'mapped' else 'review'
                counts[status] += 1
                if details or status == 'review':
                    yield dict(request=number, link=i+1, status=status, han=h, vi=v,
                               score=group.get('score'))
            if reasons:
                review.append(dict(request=number, reasons=reasons))
    yield dict(requests=requests, links=links, mapped_links=counts['mapped'],
               links_needing_review=counts['review'], fully_reconstructed=dict(coverage),
               requests_needing_coverage_review=review)


def first_payload(han, records, clauses, planner, model_dir):
    score = planner.scores(han, records, clauses, model_dir)
    path = planner.landmarks(score)
    batch = next(planner.batches(han, records, clauses, score, path, 4))
    by_han = dict(han)
    by_vi = {r['id_vi']: r['text_vi'] for r in records}
    v = batch['vi']
    if not v:
        return {'batch': batch, 'payload': None}
    return dict(batch=batch, payload={'han': '\n'.join(by_han[i] for i in batch['han']),
                                    'vi': '\n'.join(by_vi[q['id_vi']][q['start']:q['end']] for q in v)})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--details', action='store_true', help='Include every replayed link and source span')
    p.add_argument('--model-dir', type=Path, default=ROOT/'OmniAlign/OmniAlign')
    args = p.parse_args()
    os.environ['HF_HUB_OFFLINE'] = os.environ['TRANSFORMERS_OFFLINE'] = '1'
    import plan_alignment_batches as planner

    han, records, clauses = planner.load(CAP)
    *findings, summary = replay(LOG, historical_sources(han, records), args.details)
    first = first_payload(han, records, clauses, planner, args.model_dir)
    # Preserve accented text on Unicode terminals; escape it on legacy pipes.
    unicode_stdout = (sys.stdout.encoding or '').lower().startswith('utf')
    print(json.dumps(dict(replay=summary, links=findings, first_candidate=first),
                     indent=2, ensure_ascii=not unicode_stdout))


if __name__ == '__main__':
    main()
