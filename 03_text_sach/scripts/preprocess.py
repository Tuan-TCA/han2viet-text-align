"""Source loading and reversible normalization (Unicode code-point offsets)."""
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata

import regex

STAGE = Path(__file__).resolve().parents[1]
ROOT = STAGE.parent
LEGACY = ROOT / 'pipeline/scripts'
sys.path.insert(0, str(LEGACY))
from normalize_phase1 import INPUTS, load_han, load_viet
import normalize_phase1 as phase1
from benchmark_alignment_api_final import normalize_numbers


def load_sources():
    # The original loader's relative paths were authored for the project root.
    old = phase1.ROOT
    phase1.ROOT = ROOT
    try:
        pages, viet, maps = [], [], []
        offset = nfc_offset = 0
        for cap, (count, lo, hi) in INPUTS.items():
            folder = Path('02_ocr_tho') / cap
            h, offset, nfc_offset = load_han(cap, folder / f'{cap}_HAN_all_pages.txt', count, offset, nfc_offset)
            v, m, _ = load_viet(cap, folder / 'VIET' / f'VIET_{lo:04d}-{hi:04d}.xlsx', count, lo, hi)
            pages.extend(h)
            viet.extend(r for r in v if r['dung_de_ghep'])
            maps.extend(m)
        return pages, viet, maps
    finally:
        phase1.ROOT = old


def normalize(text):
    """Return NFC + collapsed whitespace, with a source interval per code point."""
    out, spans = [], []
    for m in regex.finditer(r'\s+|\X', text):
        s = m[0]
        if s.isspace():
            if out and m.end() < len(text):
                out.append(' ')
                spans.append(list(m.span()))
        else:
            nfc = unicodedata.normalize('NFC', s)
            out.extend(nfc)
            spans.extend([list(m.span()) for _ in nfc])
    return ''.join(out), spans


def viet_t1(text, confirmed=()):
    normalized, spans = normalize(text)
    sent, indices, _ = normalize_numbers(normalized, confirmed)
    return sent, [spans[i] for i in indices]


def suspicious(text):
    return [{'span': list(m.span()), 'text': m[0]} for m in
            regex.finditer(r'[A-Za-z]+[0-9]*|[\uFFFD□�]|[\p{Co}\p{Cf}]', text)]


def content(text):
    return ''.join(c for c in text if not c.isspace() and not unicodedata.category(c).startswith('P'))


def fingerprint(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def read_jsonl(path):
    return [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines() if s.strip()]


def write_json(path, obj):
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)


def audit_partition(raw, spans):
    counts = [0] * len(raw)
    last = 0
    ordered = True
    for a, b in spans:
        if not 0 <= a < b <= len(raw):
            raise ValueError(f'Invalid source span: {(a,b)}')
        ordered &= a == last
        last = b
        for i in range(a, b):
            counts[i] += 1
    return {'missing': counts.count(0), 'duplicated': sum(max(0, x-1) for x in counts),
            'exact_reconstruction': ordered and last == len(raw)}
