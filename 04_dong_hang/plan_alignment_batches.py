r"""Offline passage selection for Kim Han Nom. Prints JSON; never sends requests.

Run from repo root: .\.venv\Scripts\python.exe -B 04_dong_hang/plan_alignment_batches.py
Offsets are zero-based Unicode character positions in the original CSV field,
end exclusive. Core ranges are candidates, not final sentence alignments.
"""
import argparse
import csv
import json
import math
import os
import re
from collections import Counter
from pathlib import Path

import numpy as np
from cn2an import cn2an
from align_v16_fixed import OmniEncoder, get_sino_tokens, word_tokens

ROOT = Path(__file__).resolve().parents[1]


def rows(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        yield from csv.DictReader(f)


def load(cap_dir):
    han, records, clauses = [], [], []
    files = [(int(p.name.split('-')[0]), p) for p in (cap_dir / 'HAN').glob('*-cleaned.csv')
             if p.name.split('-')[0].isdigit()]
    for page, path in sorted(files):
        for r in rows(path):
            if r['text_zh'].strip():
                han.append((f"{cap_dir.name}/{page:04d}:{r['id_zh']}", r['text_zh']))
    for r in rows(cap_dir / 'VIET/vi_cleaned.csv'):
        text = r['text_vi']
        if not text.strip():
            continue
        idx = len(records)
        records.append(r)
        pos = 0
        for sep in re.finditer(r'(?<=[.,;:?!…])\s+|\Z', text):
            start = pos + len(text[pos:sep.start()]) - len(text[pos:sep.start()].lstrip())
            end = len(text[:sep.start()].rstrip())
            if start < end:
                clauses.append((idx, start, end, text[start:end]))
            pos = sep.end()
    if not han or not clauses:
        raise ValueError('Need nonempty Hán and Vietnamese inputs')
    if len(set(h for h, _ in han)) != len(han) or len({r['id_vi'] for r in records}) != len(records):
        raise ValueError('Duplicate source ID')
    return han, records, clauses


def features(text, han=False):
    tokens = get_sino_tokens(text) if han else word_tokens(text)
    keys = {tuple(tokens[i:i+k]) for k in (2, 3) for i in range(len(tokens)-k+1)}
    if han:
        for num in re.findall('[零〇一二兩两三四五六七八九十百千万萬億卅]+', text):
            try:
                keys.add(('#', str(cn2an(num.replace('卅', '三十'), 'smart'))))
            except (ValueError, KeyError):  # OCR or a range such as 十六七
                continue
    else:
        keys.update(('#', s.replace('.', '')) for s in re.findall(r'\d+(?:\.\d{3})*', text))
    return keys


def scores(han, records, clauses, model_dir):
    # The model retrieves records; rare shared readings/numbers localize clauses.
    if not (model_dir / 'model.safetensors').is_file():
        raise ValueError(f'Missing local OmniAlign checkpoint: {model_dir}')
    os.environ['HF_HUB_OFFLINE'] = os.environ['TRANSFORMERS_OFFLINE'] = '1'
    model = OmniEncoder(model_dir.resolve())
    v = model.encode([r['text_vi'] for r in records], batch_size=4)
    h = model.encode([text for _, text in han])
    sem = (h @ v.T)[:, [c[0] for c in clauses]]
    vf = [features(c[3]) for c in clauses]
    freq = Counter(k for group in vf for k in group)
    weight = {k: math.log((len(vf)+1)/(n+1)) * (0.45 if k[0] == '#' else 1)
              for k, n in freq.items()}
    score = sem.astype(float) - .30  # heuristic neutral cosine, not a probability
    for i, (_, text) in enumerate(han):
        hf = features(text, han=True)
        for j, group in enumerate(vf):
            hits = sorted((weight[k] for k in hf & group), reverse=True)
            score[i, j] += .08 * sum(hits[:3])
    return score


def landmarks(score):
    """Best ordered clause landmarks. Rows can abstain or share a clause.

    State 0 means no landmark yet. Free ends, modest internal distance cost;
    prefix maxima find the best previous clause in O(H*V) time.
    """
    n, m = score.shape
    dp = np.full(m+1, -np.inf)
    dp[0] = 0
    parent = np.zeros((n, m+1), dtype=int)
    used = np.zeros_like(parent, dtype=bool)
    for i, line in enumerate(score):
        prev = dp.copy()
        best, at = -np.inf, 0
        for j, value in enumerate(line, 1):
            best -= .018
            if prev[j] >= best:
                best, at = prev[j], j
            base, source = (best, at) if best > prev[0] else (prev[0], 0)
            hit = base + value - .17
            if hit > prev[j] and value > .17:
                dp[j], parent[i, j], used[i, j] = hit, source, True
            else:
                parent[i, j] = j
    j = int(dp.argmax())
    path = [None] * n
    for i in reversed(range(n)):
        if used[i, j]:
            path[i] = j - 1
        j = parent[i, j]
    return path


def batches(han, records, clauses, score, path, size):
    def span(j, core):
        r, start, end, _ = clauses[j]
        rec = records[r]
        return dict(id_vi=rec['id_vi'], pages=[rec['page_start'], rec['page_end']],
                    start=start, end=end, context=not core)

    for a in range(0, len(han), size):
        b = min(a + size, len(han))
        hits = [(i, path[i]) for i in range(a, b) if path[i] is not None]
        flags, vi = [], []
        if len(hits) < b-a:
            flags.append('unlocated_han_rows')
        if hits:
            lo, hi = hits[0][1], hits[-1][1]
            # Estimate boundaries between neighboring landmarks; never fill a
            # long unsupported interval merely to cover the Vietnamese pool.
            left = next((j for j in reversed(path[:a]) if j is not None), None)
            right = next((j for j in path[b:] if j is not None), None)
            if left is not None and lo-left <= 12:
                lo = min(lo, (left+lo)//2+1)
            if right is not None and right-hi <= 12:
                hi = (hi+right)//2
            if any(y-x > 12 for (_, x), (_, y) in zip(hits, hits[1:])):
                flags.append('large_internal_gap')
            local = np.array([score[i, j] for i, j in hits])
            if np.median(local) < .35:
                flags.append('weak_evidence')
            # A distant competing region needs support from multiple rows.
            for k in range(0, len(clauses), max(4, hi-lo+1)):
                stop = min(len(clauses), k+max(4, hi-lo+1))
                if stop > lo-4 and k <= hi+4:
                    continue
                votes = sum(score[i, k:stop].max() >= s-.05 for (i, _), s in zip(hits, local))
                if votes >= math.ceil(len(hits)*.6):
                    flags.append('competing_passage')
                    break
            vi = [span(j, lo <= j <= hi) for j in range(max(0, lo-1), min(len(clauses), hi+2))]
        yield dict(han=[h for h, _ in han[a:b]], vi=vi, review_reasons=flags)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cap', type=int, default=1)
    p.add_argument('--sizes', nargs='+', type=int, default=[4, 8])
    p.add_argument('--model-dir', type=Path, default=ROOT/'OmniAlign/OmniAlign')
    args = p.parse_args()
    if min(args.sizes) < 1:
        p.error('batch sizes must be positive')
    han, records, clauses = load(ROOT/'03_text_sach'/f'Cap_{args.cap:02d}')
    score = scores(han, records, clauses, args.model_dir)
    path = landmarks(score)
    print(json.dumps({size: list(batches(han, records, clauses, score, path, size))
                      for size in args.sizes}, indent=2))


if __name__ == '__main__':
    main()
