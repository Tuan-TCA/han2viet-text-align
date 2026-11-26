"""Compare SinoNom, CPU BertAlign, and API-first fallback on the same text."""

import argparse
import csv
from dataclasses import replace
import json
import os
from pathlib import Path
import re
import sys
from time import perf_counter
from unittest.mock import patch

import batch_sentence_alignment as batch
from batch_han_sentence_split import content, load_page

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def norm(text):
    return ' '.join(text.split())


def vi_sentences(viet):
    from underthesea import sent_tokenize

    result = []
    for unit in viet:
        text = norm(unit.text)
        parts = sent_tokenize(text)
        if not parts or norm(' '.join(parts)) != text:
            result.append(unit)
        else:
            result.extend(replace(unit, id=f'{unit.id}.U{i}', text=part)
                          for i, part in enumerate(parts, 1))
    return result


def jiayan_sentences(model_dir, first, last):
    from jiayan import CRFPunctuator, load_lm
    from opencc import OpenCC

    model = CRFPunctuator(load_lm(str(model_dir / 'jiayan.klm')), str(model_dir / 'cut_model'))
    model.load(str(model_dir / 'punc_model'))
    converter = OpenCC('t2s')
    result = []
    for page in range(first, last + 1):
        _, _, source = load_page(page)
        raw = content(source)
        simple = converter.convert(raw)
        if len(simple) != len(raw):
            raise ValueError(f'OpenCC changed text length on page {page}')
        punctuated = model.punctuate(simple)
        if content(punctuated) != simple:
            raise ValueError(f'Jiayan changed source characters on page {page}')
        start = end = 0
        for part in re.findall(r'[^。？！!?]+[。？！!?]*', punctuated):
            end += len(content(part))
            if start < end:
                result.append(batch.Unit(f'J-{page:04}-{start}', page, page, raw[start:end]))
            start = end
        if end != len(raw):
            raise ValueError(f'Jiayan segmentation lost source characters on page {page}')
    return result


def checked_api(han, viet, token, **kwargs):
    payload = batch.call_api(han, viet, token, **kwargs)
    rows = payload['data']['result']
    # Some responses mix usable links with malformed rows. Reuse the project's
    # exact-text/offset resolver for the rows that can actually be traced.
    good = [r for r in rows if isinstance(r, dict) and
            all(r.get(key) is None or isinstance(r[key], str)
                for key in ('han_text', 'vietnamese_text'))]
    return {**payload, 'malformed_rows': len(rows) - len(good),
            'data': {**payload['data'], 'result': good}}


def bert_links(han, spans, source_dir, threads):
    os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
    if not (source_dir / 'bertalign' / 'aligner.py').is_file():
        raise FileNotFoundError(f'BertAlign source not found at {source_dir}')
    if not han or not spans:
        return []
    import torch

    torch.set_num_threads(threads)
    sys.path.insert(0, str(source_dir.resolve()))
    from bertalign import aligner as core

    # The Reference fork calls Google even with is_split=True. These language
    # codes only label the two already-segmented inputs in this code path.
    with patch.object(core, 'detect_lang', side_effect=['zh', 'vi']):
        aligner = core.Bertalign('\n'.join(norm(h.text) for h in han),
                                 '\n'.join(s.text for s in spans),
                                 is_split=True, top_k=min(3, len(spans)))
    aligner.align_sents()
    return [{'han': h, 'vi': [spans[i] for i in v], 'score': None}
            for h, v in aligner.result if len(h) and len(v)]


def hybrid_links(api, bert):
    # API links are already monotone; higher priority is only a selection flag.
    selected = batch.select([dict(r, score=1) for r in api] +
                            [dict(r, score=0) for r in bert])
    originals = {link_key(r): r for r in bert + api}
    return [originals[link_key(r)] for r in selected]


def link_key(r):
    return tuple(r['han']), tuple((s.row, s.start, s.end) for s in r['vi'])


def gold_labels(path):
    if not path:
        return {}
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    labels = {}
    try:
        for sheet in wb:
            rows = iter(sheet.values)
            cols = next(rows, ())
            if not {'Chinese', 'Vietnamese', 'Label_Target'}.issubset(cols):
                continue
            h, v, label = [cols.index(key) for key in ('Chinese', 'Vietnamese', 'Label_Target')]
            for row in rows:
                if row[h] and row[v] and str(row[label]).strip() in ('0', '1'):
                    key = norm(str(row[h])), norm(str(row[v]))
                    labels.setdefault(key, set()).add(int(row[label]))
    finally:
        wb.close()
    return {key: next(iter(values)) for key, values in labels.items() if len(values) == 1}


def export(out, variant, han, viet, predictions, gold):
    fields = ['method', 'han_ids', 'viet_spans', 'Chinese', 'Vietnamese', 'score', 'Label_Target']
    stats = {}
    with (out / f'{variant}_review.csv').open('w', encoding='utf-8-sig', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for method, pairs in predictions.items():
            seen, positives = set(), set()
            reviewed = 0
            for pair in pairs:
                h, v = pair['han'], pair['vi']
                chinese, vietnamese = norm(' '.join(han[i].text for i in h)), norm(' '.join(s.text for s in v))
                key = link_key(pair)
                if key in seen:
                    continue
                seen.add(key)
                label = gold.get((chinese, vietnamese))
                reviewed += label is not None
                if label == 1:
                    positives.add((chinese, vietnamese))
                writer.writerow(dict(method=method, han_ids=' '.join(han[i].id for i in h),
                                     viet_spans=json.dumps([[viet[s.row].id, s.start, s.end] for s in v]),
                                     Chinese=chinese, Vietnamese=vietnamese, score=pair['score'],
                                     Label_Target=label))
            stats[method] = {'proposals': len(seen), 'exact_review_matches': reviewed,
                             'confirmed_label_1': len(positives) if reviewed else None,
                             'unreviewed': len(seen) - reviewed,
                             'covered_han_units': len({i for h, _ in seen for i in h})}
    stats['bert_additions_to_api'] = len({link_key(r) for r in predictions['hybrid']} -
                                       {link_key(r) for r in predictions['api']})
    return stats


def selftest():
    han = [batch.Unit(str(i), 1, 1, x) for i, x in enumerate(['甲', '乙'])]
    vi = [batch.Span(i, 0, 3, x) for i, x in enumerate(['Một', 'Hai'])]
    result = {'data': {'result': [dict(han_start=99, han_end=99, han_text='甲',
                                      vi_start=99, vi_end=99, vietnamese_text='Một'),
                                 dict(han_text='không có', vietnamese_text='Hai')]}}
    good = list(batch.links(result, [0, 1], han, vi))
    assert len(good) == 1 and link_key(good[0]) == ((0,), ((0, 0, 3),))
    recovered = {'han': [1], 'vi': [vi[1]], 'score': None}
    overlaps = {'han': [0, 1], 'vi': vi, 'score': None}
    assert hybrid_links(good, [overlaps, recovered]) == good + [recovered]
    with patch.object(batch, 'call_api', return_value={'data': {'result': [None, {'han_text': 7}, {}]}}):
        assert checked_api([], [], 'test')['malformed_rows'] == 2
    print('Self-test passed: malformed rows, exact re-anchoring, and API-first monotone fallback.')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--self-test', action='store_true')
    p.add_argument('--han-dir', type=Path, default=ROOT / '03_text_sach/Cap_01/HAN/reviewed')
    p.add_argument('--viet-xlsx', type=Path, default=ROOT / '02_ocr_tho/Cap_01/VIET/VIET_0186-0251.xlsx')
    p.add_argument('--gold', type=Path, default=HERE / 'Cap01_0001-0010_alignment_reviewed.xlsx')
    p.add_argument('--pages', type=int, nargs=2, default=(1, 2))
    p.add_argument('--output', type=Path)
    p.add_argument('--bert-source', type=Path, default=HERE / '.venv_cpu_benchmark/bert_base_vn_deploy-master')
    p.add_argument('--jiayan-models', type=Path)
    p.add_argument('--threads', type=int, default=4)
    p.add_argument('--max-calls', type=int, default=12, help='API budget across all input variants')
    args = p.parse_args()
    if args.self_test:
        return selftest()
    if args.output is None or args.pages[0] < 1 or args.pages[1] < args.pages[0] or args.max_calls < 0:
        p.error('Provide --output, a valid --pages range, and a non-negative --max-calls')
    han = batch.load_han(args.han_dir, *args.pages)
    viet, mapping = batch.load_viet(args.viet_xlsx)
    lo, hi = batch.window(mapping, *args.pages, margin=0)
    viet = [u for u in viet if u.first <= hi and u.last >= lo]
    gold = gold_labels(args.gold)
    report = {'han_pages': args.pages, 'viet_pages': [lo, hi], 'reviewed_reference_pairs': len(gold),
              'segmentation': {}, 'variants': {}}
    variants = {'reviewed': (han, viet)}
    started = perf_counter()
    try:
        vi_split = vi_sentences(viet)
        report['segmentation']['underthesea'] = {'seconds': round(perf_counter() - started, 3),
                                                'before': len(viet), 'after': len(vi_split)}
        if [u.text for u in vi_split] != [norm(u.text) for u in viet]:
            variants['underthesea'] = (han, vi_split)
    except Exception as exc:
        report['segmentation']['underthesea'] = {'error': str(exc)}
    if args.jiayan_models:
        started = perf_counter()
        try:
            jiayan = jiayan_sentences(args.jiayan_models, *args.pages)
            variants['jiayan'] = (jiayan, viet)
            report['segmentation']['jiayan'] = {'seconds': round(perf_counter() - started, 3), 'han_units': len(jiayan)}
        except Exception as exc:
            report['segmentation']['jiayan'] = {'error': str(exc)}
    else:
        report['segmentation']['jiayan'] = {'status': 'not run', 'reason': 'Set --jiayan-models and install KenLM'}
    args.output.mkdir(parents=True, exist_ok=False)
    remaining = args.max_calls
    for n, (variant, (h, v)) in enumerate(variants.items()):
        options = argparse.Namespace(batch_size=8, margin=0, max_viet_units=16,
                                     max_calls=remaining // (len(variants) - n), delay=.5, timeout=22)
        started = perf_counter()
        candidates, attempts = batch.run(h, v, mapping, options, api=checked_api)
        t_api = perf_counter() - started
        remaining -= len(attempts)
        api = batch.select(candidates)
        started = perf_counter()
        bert_error = None
        try:
            bert = bert_links(h, list(batch.pieces(v, lo, hi)), args.bert_source, args.threads)
        except Exception as exc:
            bert, bert_error = [], f'{type(exc).__name__}: {exc}'
        t_bert = perf_counter() - started
        predictions = {'api': api, 'bertalign': bert, 'hybrid': hybrid_links(api, bert)}
        stats = export(args.output, variant, h, v, predictions, gold)
        for attempt in attempts:
            body = attempt.pop('response', {})
            attempt['malformed_rows'] = body.get('malformed_rows', 0)
            attempt['returned_rows'] = len(body.get('data', {}).get('result', [])) + attempt['malformed_rows']
        stats.update(han_units=len(h), viet_units=len(v), api_seconds=round(t_api, 3),
                     bertalign_seconds=round(t_bert, 3), bertalign_error=bert_error,
                     api_calls=len(attempts), api_errors=sum('error' in a for a in attempts), api_attempts=attempts)
        report['variants'][variant] = stats
        print(variant, {k: v for k, v in stats.items() if k != 'api_attempts'}, flush=True)
        (args.output / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
