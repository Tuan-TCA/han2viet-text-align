"""Run the three-request Cap_01 Separate API pilot against Phase 1 artifacts."""

import argparse
import json
import os
import re
import time
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

import requests


ARTIFACTS = Path(__file__).resolve().parents[1] / 'artifacts'
URL = 'https://kimhannom.fit.hcmus.edu.vn/api/web/clc-sinonom/separate-sentences'
AUTH_CODES = {'000108', '000401', '000403', '401', '403'}
SENTENCE = re.compile(r'[^。！？!?\r\n]+(?:[。！？!?]+[」』”’）】]*)?')


def load_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def content_offsets(text):
    offsets = [i for i, c in enumerate(text)
               if not c.isspace() and not unicodedata.category(c).startswith('P')]
    return ''.join(text[i] for i in offsets), offsets


def parse_sentences(body):
    value = body.get('data')
    for _ in range(4):
        if isinstance(value, dict):
            value = value.get('sentences')
        elif isinstance(value, str) and value.lstrip().startswith(('{', '[', '"')):
            value = json.loads(value)
        else:
            break
    if isinstance(value, str):
        parts = [value]
    elif isinstance(value, list) and all(isinstance(item, str) for item in value):
        parts = value
    else:
        raise ValueError('Missing or unsupported data.sentences')
    lines = [s.strip() for part in parts for s in SENTENCE.findall(part)
             if content_offsets(s)[0]]
    if not lines:
        raise ValueError('No sentences with text in API result')
    return parts, lines


def analyze(raw, start, parts, lines):
    original, index = content_offsets(raw)
    returned, _ = content_offsets(''.join(parts))
    same = original == returned
    changes = []
    for op, a, b, c, d in SequenceMatcher(None, original, returned, autojunk=False).get_opcodes():
        if op == 'equal':
            continue
        left = index[a] if a < len(index) else len(raw)
        right = index[b - 1] + 1 if b > a else left
        changes.append({'operation': op, 'source': original[a:b], 'api': returned[c:d],
                        'global_raw_span': [start + left, start + right],
                        'source_content_span': [a, b], 'api_content_span': [c, d]})
    metrics = {'same_content': same, 'source_content_chars': len(original),
               'api_content_chars': len(returned), 'edits': changes,
               'same_character_counts_but_different_order': not same and Counter(original) == Counter(returned),
               'parsed_preserves_api_content': content_offsets(''.join(lines))[0] == returned,
               'sentences': lines, 'projected_sentences': None}
    if same and metrics['parsed_preserves_api_content']:
        projected = []
        cursor = 0
        for line in lines:
            begin = index[cursor]
            cursor += len(content_offsets(line)[0])
            projected.append({'text_api': line, 'global_raw_span': [start + begin, start + index[cursor - 1] + 1]})
        metrics['projected_sentences'] = projected
    return metrics


def call(session, record, token):
    start = time.perf_counter()
    try:
        response = session.post(URL, json=record['payload'], timeout=(10, 90), allow_redirects=False)
        record['latency_ms'] = round((time.perf_counter() - start) * 1000)
    except requests.RequestException as exc:
        record.update(status='transport_error', error=type(exc).__name__,
                      latency_ms=round((time.perf_counter() - start) * 1000))
        return False
    encoding = response.encoding or 'utf-8'
    raw = response.content.decode(encoding, errors='replace')
    record.update(http_status=response.status_code, raw_response=raw.replace(token, '[REDACTED]'))
    try:
        body = json.loads(record['raw_response'])
    except ValueError:
        body = None
    code = body.get('code') if isinstance(body, dict) else None
    record['api_code'] = code if isinstance(code, (str, int)) else None
    if response.status_code in {401, 403, 429} or str(code) in AUTH_CODES | {'429', '000429'}:
        record['status'] = 'auth_or_rate_limit'
        return True
    if response.status_code != 200 or not isinstance(body, dict) or body.get('is_success') is not True:
        record['status'] = 'api_error'
        return False
    try:
        parts, lines = parse_sentences(body)
    except ValueError:
        record['status'] = 'parse_error'
        return False
    record['analysis'] = analyze(record['payload']['text'], record['global_raw_span'][0], parts, lines)
    metrics = record['analysis']
    record['status'] = ('ok' if metrics['projected_sentences'] is not None else
                        'parser_content_mismatch' if metrics['same_content'] else 'content_mismatch')
    return False


def compare(records, silver, raw, join):
    def content_pos(raw_offset):
        return len(content_offsets(raw[:raw_offset])[0])

    start = min(r['han_link']['global_raw_span'][0] for r in silver)
    end = max(r['han_link']['global_raw_span'][1] for r in silver)
    lo, hi = content_pos(start), content_pos(end)
    # Common reference: same end boundary in both Silver proposals, excluding pilot edges.
    references = {'agreed': set(), 'chatgpt': set(), 'deepseek': set()}
    for row in silver:
        comp = row['comparison']
        cg = content_pos(comp['chatgpt_han_link']['global_raw_span'][1])
        ds = content_pos(comp['deepseek_han_link']['global_raw_span'][1])
        for key, pos in [('chatgpt', cg), ('deepseek', ds), ('agreed', cg if cg == ds else None)]:
            if pos is not None and lo < pos < hi:
                references[key].add(pos)

    def evaluate(group):
        if any(r['status'] != 'ok' for r in group):
            return None
        projected = [s for r in group for s in r['analysis']['projected_sentences']]
        boundary_positions = {content_pos(s['global_raw_span'][1]) for s in projected[:-1]}
        return {'interior_boundaries_in_silver_scope': sorted(p for p in boundary_positions if lo < p < hi),
                'found': {k: len(positions & boundary_positions) for k, positions in references.items()},
                'boundary_at_page_join': content_pos(join) in boundary_positions,
                'cross_page_sentences': [s for s in projected if s['global_raw_span'][0] < join < s['global_raw_span'][1]]}

    return {'scope_global_raw_span': [start, end], 'page_join_global_raw_offset': join,
            'reference_content_offsets': {k: sorted(v) for k, v in references.items()},
            'pages_separate': evaluate(records[:2]), 'pages_joined': evaluate(records[2:])}


def report(results):
    rows, comparisons = results['cases'], results['boundary_comparison']
    lines = ['# Pilot Separate API — Cap_01, Hán 001–002', '',
             '| Input | HTTP | Mã API | Thời gian (ms) | Ký tự nguồn → API* | Số câu | Trạng thái |',
             '|---|---:|---|---:|---:|---:|---|']
    for row in rows:
        a = row.get('analysis', {})
        sizes = f"{a['source_content_chars']} → {a['api_content_chars']}" if a else '—'
        lines.append(f"| {row['id']} | {row.get('http_status', '—')} | {row.get('api_code') or '—'} | "
                     f"{row.get('latency_ms', '—')} | {sizes} | {len(a['sentences']) if a else '—'} | {row['status']} |")
    lines += ['', '\\* Không tính dấu câu và khoảng trắng; so chuỗi theo đúng thứ tự ký tự.', '',
              '## Kiểm tra ký tự', '']
    for row in rows:
        a = row.get('analysis')
        if a is None:
            lines.append(f"- **{row['id']}**: chưa có kết quả phân tích (`{row['status']}`{', ' + row['error'] if 'error' in row else ''}).")
        elif a['same_content']:
            lines.append(f"- **{row['id']}**: chuỗi ký tự giữ nguyên thứ tự.")
        else:
            lines.append(f"- **{row['id']}**: {len(a['edits'])} vùng sai khác. Không dùng biên từ kết quả này.")
            if a['same_character_counts_but_different_order']:
                lines.append('  - Tần suất ký tự giữ nguyên nhưng thứ tự thay đổi.')
            for e in a['edits'][:8]:
                lines.append(f"  - `{e['operation']}` tại `{e['global_raw_span']}`: `{e['source'][:30]}` → `{e['api'][:30]}`.")
    lines += ['', '## Ranh giới và câu vắt trang', '',
              'Chỉ so các ranh giới nằm bên trong phạm vi Silver; bỏ biên cuối phạm vi. '
              'Offset được so trên luồng ký tự nội dung, để dấu câu và khoảng trắng không làm lệch vị trí. '
              'Đây là đối chiếu biên cụm dóng hàng Silver, không phải độ chính xác tách câu hay khớp nghĩa.', '']
    refs = comparisons['reference_content_offsets']
    for key, label in [('pages_separate', 'Từng trang'), ('pages_joined', 'Ghép hai trang')]:
        metrics = comparisons[key]
        if metrics is None:
            lines.append(f'- **{label}:** không đủ kết quả ánh xạ được về OCR để so sánh.')
            continue
        hits = ', '.join(f"{name}: {metrics['found'][name]}/{len(refs[name])}"
                         for name in ('agreed', 'chatgpt', 'deepseek'))
        lines.append(f"- **{label}:** {len(metrics['interior_boundaries_in_silver_scope'])} biên nội vùng; "
                     f"trùng Silver ({hits}); {len(metrics['cross_page_sentences'])} câu vắt trang; "
                     f"{'có' if metrics['boundary_at_page_join'] else 'không có'} biên tại điểm nối.")
        for s in metrics['cross_page_sentences']:
            lines.append(f"  - Span `{s['global_raw_span']}`: {s['text_api']}")
    lines += ['', '`agreed` = biên cuối được cả hai nguồn Silver chọn. Với cách tách riêng, biên tại điểm nối là do cách chia input.', '']
    if comparisons['pages_joined'] and comparisons['pages_joined']['cross_page_sentences']:
        lines.append('**Nhận xét:** Ghép trang giữ được ngữ cảnh vắt trang trong pilot. '
                     'Nên đưa cách này vào test Alignment API; chưa thể kết luận chất lượng dóng hàng chỉ từ biên câu.')
    elif comparisons['pages_joined'] and comparisons['pages_separate']:
        lines.append('**Nhận xét:** Ghép trang giữ được ký tự nhưng pilot không cho thấy câu vắt trang trong output. '
                     'Chưa đủ bằng chứng chọn cách ghép là tốt hơn.')
    else:
        lines.append('**Nhận xét:** Chưa đủ dữ liệu so hai chiến lược. Chỉ dùng biên của các kết quả kiểm tra được toàn vẹn ký tự.')
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ARTIFACTS / 'separate_pilot_cap01')
    parser.add_argument('--genre', choices=('history', 'culture'), default='history')
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f'Output already exists: {args.output}')
    token = os.environ.get('SINONOM_TOKEN', '').strip()
    if token.lower().startswith('bearer '):
        token = token[7:].strip()
    if not token:
        parser.error('Set SINONOM_TOKEN before running the pilot')

    pages = load_jsonl(ARTIFACTS / 'phase1/han_pages.jsonl')
    page_by_id = {page['id']: page for page in pages}
    first, second = (page_by_id[f'Cap_01-HAN-{n:03d}'] for n in (1, 2))
    assert first['global_raw_span'][0] == 0 and first['global_raw_span'][1] == second['global_raw_span'][0]
    silver = load_jsonl(ARTIFACTS / 'phase1/silver_benchmark.jsonl')
    records = []
    for group in ([first], [second], [first, second]):
        records.append({'id': '+'.join(f"{p['han_pdf_page']:03d}" for p in group),
                        'global_raw_span': [group[0]['global_raw_span'][0], group[-1]['global_raw_span'][1]],
                        'payload': {'text': ''.join(p['text_original'] for p in group),
                                    'ocr_id': 1, 'genre': args.genre, 'punctuation_group': 'all'},
                        'status': 'not_attempted'})
    args.output.mkdir(parents=True, exist_ok=False)
    with requests.Session() as session:
        session.headers.update({'Authorization': f'Bearer {token}', 'Accept': 'application/json',
                                'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                                               'AppleWebKit/537.36 Chrome/138.0.0.0 Safari/537.36')})
        for i, record in enumerate(records):
            if i:
                time.sleep(0.5)
            if call(session, record, token):
                break
    result = {'endpoint': URL, 'requests': sum(r['status'] != 'not_attempted' for r in records), 'cases': records,
              'boundary_comparison': compare(records, silver, records[2]['payload']['text'], second['global_raw_span'][0])}
    with (args.output / 'results.json').open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write('\n')
    with (args.output / 'report.md').open('x', encoding='utf-8') as f:
        f.write(report(result))
    print(f"{args.output}: " + ', '.join(f"{r['id']}={r['status']}" for r in records))
    return 0 if all(r['status'] == 'ok' for r in records) else 1


if __name__ == '__main__':
    raise SystemExit(main())
