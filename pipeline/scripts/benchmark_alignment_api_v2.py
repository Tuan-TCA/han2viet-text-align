"""Replay saved Alignment API responses offline with three mapping/evaluation variants."""

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

import benchmark_alignment_api as v0


INPUT = v0.ARTIFACTS / 'alignment_benchmark'
OUTPUT = v0.ARTIFACTS / 'alignment_benchmark_offline_v2'
VERSIONS = ('V0', 'V1', 'V2')
NUMERIC_SEPARATOR = re.compile(r'(?<=[0-9]) *(?P<separator>[.,]) *(?=[0-9]{3}(?![0-9]))')
UNRESOLVED = {'untraceable', 'ambiguous'}
REJECTED = {'invalid_text', 'invalid_range', 'ambiguous', 'text_mismatch'}


def normalize_number_spacing(text):
    """Canonicalize spacing only; map each retained code point to its input index."""
    skipped = {i for m in NUMERIC_SEPARATOR.finditer(text) for i in range(*m.span())
               if i != m.start('separator')}
    offsets = [i for i in range(len(text)) if i not in skipped]
    return ''.join(text[i] for i in offsets), offsets


def resolve(texts, lo, hi, snippet):
    """Resolve to half-open offsets in the original (non-number-normalized) payload units."""
    if snippet is not None and not isinstance(snippet, str):
        return [], 'invalid_text'
    snippet = v0.normalize(snippet or '')
    valid = type(lo) is type(hi) is int and 0 <= lo <= hi < len(texts)
    if not snippet:
        if type(lo) is type(hi) is int and lo == hi == -1:
            return [], 'empty'
        if valid:
            return [(i, 0, len(texts[i])) for i in range(lo, hi + 1)], 'indices_only'
        return [], 'invalid_range'
    if not texts:
        return [], 'text_mismatch'
    units, offsets = zip(*(normalize_number_spacing(t) for t in texts))
    needle, _ = normalize_number_spacing(snippet)
    if valid and needle == ' '.join(units[lo:hi + 1]):
        return [(i, 0, len(texts[i])) for i in range(lo, hi + 1)], (
            'indices_text' if snippet == ' '.join(texts[lo:hi + 1]) else 'indices_number_spacing')

    stream = ' '.join(units)
    # An otherwise exact substring must not start/end inside an Arabic number.
    hits = []
    for match in re.finditer('(?=' + re.escape(needle) + ')', stream):
        x, y = match.start(), match.start() + len(needle)
        if ((needle[0] in '0123456789' and re.search(r'[0-9][.,]?$', stream[max(0, x-2):x]))
                or (needle[-1] in '0123456789' and re.match(r'[.,]?[0-9]', stream[y:y+2]))):
            continue
        hits.append(x)
        if len(hits) > 1:
            return [], 'ambiguous'
    if not hits:
        return [], 'text_mismatch'
    start = hits[0]
    pos, end, spans = 0, start + len(needle), []
    for i, unit in enumerate(units):
        a, b = max(0, start - pos), min(len(unit), end - pos)
        if a < b:
            spans.append((i, offsets[i][a], offsets[i][b - 1] + 1))
        pos += len(unit) + 1
    return spans, ('exact_text_fallback' if snippet in ' '.join(texts) else 'number_spacing_fallback')


def alignment_type(n_han, n_vi):
    if not n_han:
        return '0-1'
    if not n_vi:
        return '1-0'
    if n_han == 1:
        return '1-1' if n_vi == 1 else '1-N'
    return 'N-1' if n_vi == 1 else 'N-M'


def normalize_raw_offsets(text):
    # Match the whitespace-only normalization used to build the saved payload.
    indices = [i for m in re.finditer(r'\S+', text) for i in (*range(m.start(), m.end()), m.end())][:-1]
    assert len(indices) == len(v0.normalize(text))
    return indices


def parse_robust(job, response, raw, *, strict=False):
    if response['status'] != 'success':
        return []
    ht, vt = (job['payload'][key].split('\n') for key in ('han', 'vi'))
    offset_maps = None if 'han_offsets' in job else [normalize_raw_offsets(raw[a:b]) for a, b in job['h']]
    candidates = []
    for n, row in enumerate(json.loads(response['raw_response'])['data']['result']):
        invalid = not isinstance(row, dict)
        row = {} if invalid else row
        hs, h_status = resolve(ht, row.get('han_start'), row.get('han_end'), row.get('han_text'))
        vs, v_status = resolve(vt, row.get('vi_start'), row.get('vi_end'), row.get('vietnamese_text'))
        hb, he = None, None
        if strict and h_status == 'indices_only':
            hs, h_status = [], 'invalid_text'
        if strict and v_status == 'indices_only':
            vs, v_status = [], 'invalid_text'
        if hs:
            i, a, _ = hs[0]
            k, _, b = hs[-1]
            if offset_maps is None:
                hb = job['h'][i][0] if not a else job['han_offsets'][i][a][0]
                he = job['h'][k][1] if b == len(ht[k]) else job['han_offsets'][k][b - 1][1]
                if any(raw[x[1]:y[0]].strip() or x[1] > y[0]
                       for x, y in zip(job['h'][i:k], job['h'][i+1:k+1])):
                    hs, h_status, hb, he = [], 'invalid_range', None, None
            else:
                hb = job['h'][i][0] + (offset_maps[i][a] if a else 0)
                he = job['h'][k][0] + offset_maps[k][b - 1] + 1 if b < len(ht[k]) else job['h'][k][1]
        ids = [job['v'][i] for i, _, _ in vs]
        full_vi = all(a == 0 and b == len(vt[i]) for i, a, b in vs)
        status = ('ambiguous' if 'ambiguous' in (h_status, v_status) else
                  'untraceable' if invalid or REJECTED & {h_status, v_status} or not (hs or vs) else
                  'partial_viet' if not full_vi else 'mapped' if hs and vs else 'unpaired')
        candidates.append(dict(Han_Start=hb, Han_End=he, Han_Text=raw[hb:he] if hs else '', VI_IDs=ids,
                               Vietnamese_Text=' '.join(vt[i][a:b] for i, a, b in vs),
                               Alignment_Type=alignment_type(len(hs), len(vs)),
                               Segmentation_Strategy=job['strategy'], Experiment_ID=job['id'],
                               API_Response_ID=response['id'], Validation_Status=status,
                               Han_Resolution=h_status, VI_Resolution=v_status, Han_Units=[i for i, _, _ in hs],
                               Han_Partial_Unit=any(a or b != len(ht[i]) for i, a, b in hs),
                               VI_Char_Spans=[(job['v'][i], a, b) for i, a, b in vs],
                               Score=row.get('score'), Row=n, Source_Rows=[n],
                               **({'Original_API_Rows': [row if not invalid else json.loads(response['raw_response'])['data']['result'][n]]} if strict else {})))
    return candidates


def aggregate_candidates(candidates, raw, viet_text, *, allow_han_whitespace=False):
    """Merge only complete, continuous single-ID chains in a single response."""
    def eligible(c):
        spans = c['VI_Char_Spans']
        return (c['Validation_Status'] in {'mapped', 'partial_viet'} and len(c['VI_IDs']) == len(spans) == 1
                and spans[0][0] == c['VI_IDs'][0] and spans[0][0] in viet_text
                and 0 <= spans[0][1] < spans[0][2] <= len(viet_text[spans[0][0]])
                and c['Han_Start'] is not None and c['Han_End'] is not None
                and 0 <= c['Han_Start'] < c['Han_End'] <= len(raw))

    output, i = [], 0
    while i < len(candidates):
        first = candidates[i]
        j = i
        if eligible(first):
            key, start, end = first['VI_Char_Spans'][0]
            target = len(viet_text[key])
            if start == 0 and end < target:
                while end < target and j + 1 < len(candidates):
                    prev, nxt = candidates[j:j + 2]
                    if (not eligible(nxt) or nxt['VI_IDs'] != [key]
                            or (nxt['API_Response_ID'], nxt['Experiment_ID']) != (first['API_Response_ID'], first['Experiment_ID'])
                             or nxt['Row'] != prev['Row'] + 1
                             or (prev['Han_End'] != nxt['Han_Start'] and not (
                                 allow_han_whitespace and prev['Han_End'] < nxt['Han_Start']
                                 and not raw[prev['Han_End']:nxt['Han_Start']].strip()))
                            or nxt['VI_Char_Spans'][0][1] != end):
                        break
                    end = nxt['VI_Char_Spans'][0][2]
                    j += 1
                if j > i and end == target:
                    block = candidates[i:j + 1]
                    stop = block[-1]['Han_End']
                    units = sorted({u for c in block for u in c['Han_Units']})
                    output.append({**first, 'Han_End': stop, 'Han_Text': raw[first['Han_Start']:stop],
                                   'Han_Units': units, 'Han_Partial_Unit': any(c['Han_Partial_Unit'] for c in block),
                                   'VI_Char_Spans': [(key, 0, target)], 'Vietnamese_Text': viet_text[key],
                                   'Alignment_Type': alignment_type(len(units), 1), 'Validation_Status': 'mapped',
                                   'Han_Resolution': 'aggregated', 'VI_Resolution': 'aggregated',
                                    'Score': None, 'Source_Rows': [r for c in block for r in c['Source_Rows']],
                                    'Component_Scores': [c['Score'] for c in block],
                                    **({'Original_API_Rows': [r for c in block for r in c['Original_API_Rows']]}
                                       if 'Original_API_Rows' in first else {})})
                    i = j + 1
                    continue
        output.append(first)
        i += 1
    return output


def evaluate(entries, raw, silver):
    runs = {version: [] for version in VERSIONS}
    for entry in entries:
        job = entry['job']
        viet_text = dict(zip(job['v'], job['payload']['vi'].split('\n'), strict=True))
        robust = parse_robust(job, entry, raw)
        variants = (v0.parse(job, entry, raw), robust, aggregate_candidates(robust, raw, viet_text))
        for version, candidates in zip(VERSIONS, variants):
            run = dict(job=job, status=entry['status'], response_id=entry['id'], candidates=candidates)
            if entry['status'] == 'success':
                run.update(v0.coverage(job, candidates))
            runs[version].append(run)
    pairs = {version: v0.evaluate(runs[version], silver)[0] for version in VERSIONS}
    return runs, pairs


def verify_baseline(runs, pairs, path):
    with (path / 'metrics.csv').open(encoding='utf-8-sig', newline='') as f:
        saved = {(r['experiment'], r['response_id']): r for r in csv.DictReader(f)}
    with (path / 'pair_comparison.csv').open(encoding='utf-8-sig', newline='') as f:
        old_pairs = {(r['Experiment_ID'], r['Pair_ID']): r for r in csv.DictReader(f)}
    for r in runs:
        old = saved[(r['job']['id'], r['response_id'])]
        for key in old.keys() - {'experiment', 'strategy'}:
            val = r.get(key)
            expected = v0.dump(val) if isinstance(val, (list, dict)) else '' if val is None else str(val)
            if old[key] != expected:
                raise ValueError(f"V0 mismatch for {r['job']['id']} / {key}")
    for p in pairs:
        old = old_pairs[(p['Experiment_ID'], p['Pair_ID'])]
        for key in ('Predicted_Span', 'Exact_ChatGPT', 'Exact_DeepSeek', 'IoU_ChatGPT', 'IoU_DeepSeek'):
            val = p[key]
            expected = v0.dump(val) if isinstance(val, list) else '' if val is None else str(val)
            if old[key] != expected:
                raise ValueError(f"V0 pair mismatch for {p['Experiment_ID']} / {p['Pair_ID']} / {key}")


def summarize(runs, pairs):
    succeeded = [r for r in runs if r['status'] == 'success']
    candidates = [c for r in succeeded for c in r['candidates']]
    h_input = sum(b - a for r in succeeded for a, b in r['job']['h'])
    v_input = sum(len(t) for r in succeeded for t in r['job']['payload']['vi'].split('\n'))
    h_covered = sum(round(r['han_coverage'] * sum(b-a for a,b in r['job']['h'])) for r in succeeded)
    v_covered = sum(round(r['vi_character_coverage'] * sum(len(t) for t in r['job']['payload']['vi'].split('\n')))
                    for r in succeeded)
    full, full_unique, all_ids = 0, 0, set()
    for r in succeeded:
        lengths = dict(zip(r['job']['v'], map(len, r['job']['payload']['vi'].split('\n')), strict=True))
        hits = Counter(k for c in r['candidates'] if c['Validation_Status'] == 'mapped' and c['Han_Start'] is not None
                       for k, a, b in c['VI_Char_Spans'] if a == 0 and b == lengths[k])
        full += len(hits)
        full_unique += sum(n == 1 for n in hits.values())
        all_ids.update(hits)
    n = len(pairs)
    return dict(responses=len(runs), successful_responses=len(succeeded), candidates=len(candidates),
                unresolved_rows=sum(c['Validation_Status'] in UNRESOLVED for c in candidates),
                partial_viet_rows=sum(c['Validation_Status'] == 'partial_viet' for c in candidates),
                aggregated_groups=sum(len(c.get('Source_Rows', [])) > 1 for c in candidates),
                han_covered_chars=h_covered, han_input_chars=h_input, vi_covered_chars=v_covered, vi_input_chars=v_input,
                han_coverage=h_covered / h_input if h_input else None, vi_coverage=v_covered / v_input if v_input else None,
                han_duplicate_chars=sum(r['han_duplicate_chars'] for r in succeeded),
                vi_duplicate_chars=sum(r['vi_duplicate_chars'] for r in succeeded),
                full_vi_response_id_pairs=full, unique_full_vi_response_id_pairs=full_unique,
                distinct_full_vi_ids=len(all_ids), silver_eligible=n,
                exact_chatgpt=sum(p['Exact_ChatGPT'] for p in pairs), exact_deepseek=sum(p['Exact_DeepSeek'] for p in pairs),
                agreed_eligible=sum(p['Agreed_Reference'] for p in pairs),
                exact_agreed=sum(p['Agreed_Reference'] and p['Exact_ChatGPT'] for p in pairs),
                mean_han_iou_chatgpt=sum(p['IoU_ChatGPT'] for p in pairs) / n if n else None,
                mean_han_iou_deepseek=sum(p['IoU_DeepSeek'] for p in pairs) / n if n else None)


def scoped_metrics(runs, pairs):
    scopes = ['ALL', *v0.STAGES, *(r['job']['id'] for r in runs['V0'] if r['job']['stage'] == 'E01')]
    result = {}
    for scope in scopes:
        result[scope] = {}
        for version in VERSIONS:
            group = [r for r in runs[version] if scope in {'ALL', r['job']['stage'], r['job']['id']}]
            ids = {r['job']['id'] for r in group}
            result[scope][version] = summarize(group, [p for p in pairs[version] if p['Experiment_ID'] in ids])
    return result


def candidate_cells(c):
    if c is None:
        return [''] * 10
    return [c['Validation_Status'], c['Han_Start'], c['Han_End'], c['Han_Text'], c['VI_IDs'],
            c['Vietnamese_Text'], c['VI_Char_Spans'], c['Han_Resolution'], c['VI_Resolution'],
            c.get('Source_Rows', [c['Row']])]


def export_excel(path, entries, runs, pairs, silver, scopes):
    wb = Workbook()
    wb.remove(wb.active)

    def sheet(title, headers, rows):
        ws = wb.create_sheet(title)
        ws.append(headers)
        for r in rows:
            ws.append([v0.dump(c) if isinstance(c, (tuple, list, dict)) else c for c in r])
            for c in ws[ws.max_row]:
                if c.data_type == 'f':
                    c.data_type = 's'
        ws.freeze_panes = 'D2' if len(headers) > 3 else 'A2'
        ws.auto_filter.ref = ws.dimensions
        for c in ws[1]:
            c.fill = PatternFill('solid', fgColor='203A56')
            c.font = Font(color='FFFFFF', bold=True)
            c.alignment = Alignment(wrap_text=True, vertical='center')
            wide = any(s in c.value for s in ('Text', 'Payload', 'JSON'))
            ws.column_dimensions[get_column_letter(c.column)].width = 48 if wide else max(13, min(len(c.value)+1, 27))
        ws.row_dimensions[1].height = 30
        return ws

    cols = list(scopes['ALL']['V0'])
    sheet('Summary', ['Scope', 'Version', *cols], ([s, version, *(m[k] for k in cols)]
          for s, group in scopes.items() for version, m in group.items()))
    fields = ['Response_ID', 'Experiment_ID', 'Strategy', 'Status', 'API_Code', 'Han_Payload', 'VI_Payload',
              'Han_Input_Spans', 'VI_Input_IDs', 'Raw_Response_JSON']
    sheet('Responses', fields, ([e['id'], e['job']['id'], e['job']['strategy'], e['status'], e.get('code'),
          e['job']['payload']['han'], e['job']['payload']['vi'], e['job']['h'], e['job']['v'], e['raw_response']] for e in entries))

    row_cols = ['Status', 'Han_Start', 'Han_End', 'Han_Text', 'VI_IDs', 'VI_Text', 'VI_Char_Spans',
                'Han_Resolution', 'VI_Resolution', 'Source_Rows']
    def response_rows():
        for e, r0, r1, r2 in zip(entries, *(runs[v] for v in VERSIONS), strict=True):
            if e['status'] != 'success':
                continue
            old, new = [{c['Row']: c for c in r['candidates']} for r in (r0, r1)]
            aggregated = {n: c for c in r2['candidates'] for n in c['Source_Rows']}
            for n, item in enumerate(json.loads(e['raw_response'])['data']['result']):
                raw_row = item if isinstance(item, dict) else {}
                yield [e['job']['id'], e['id'], n, raw_row.get('han_text'), raw_row.get('vietnamese_text'),
                       [raw_row.get('han_start'), raw_row.get('han_end')], [raw_row.get('vi_start'), raw_row.get('vi_end')],
                       *candidate_cells(old[n]), *candidate_cells(new[n]), *candidate_cells(aggregated[n])]
    rw = sheet('Mapping rows', ['Experiment_ID', 'Response_ID', 'API_Row_0', 'API_Han_Text', 'API_VI_Text',
               'API_Han_Indices', 'API_VI_Indices', *(f'{v}_{k}' for v in VERSIONS for k in row_cols)], response_rows())

    lookup = {v: {(p['Experiment_ID'], p['Pair_ID']): p for p in pairs[v]} for v in VERSIONS}
    comparison_fields = ['Predicted_Span', 'Predicted_Han', 'Predicted_Vietnamese', 'Exact_ChatGPT', 'Exact_DeepSeek',
                         'IoU_ChatGPT', 'IoU_DeepSeek', 'Overlapping_VI_Predictions']
    def comparison_rows():
        for p in pairs['V0']:
            key = p['Experiment_ID'], p['Pair_ID']
            yield [*key, p['VI_ID'], p['Vietnamese'], p['Silver_Han'], p['Silver_DeepSeek_Han'],
                   p['ChatGPT_Span'], p['DeepSeek_Span'], p['Agreed_Reference'], p['Provisional_Label'],
                   *(lookup[v][key][k] for v in VERSIONS for k in comparison_fields)]
    pc = sheet('Silver comparison', ['Experiment_ID', 'Pair_ID', 'VI_ID', 'Silver_VI_Text', 'ChatGPT_Han_Text',
               'DeepSeek_Han_Text', 'ChatGPT_Span', 'DeepSeek_Span', 'Agreed', 'Provisional_Label',
               *(f'{v}_{k}' for v in VERSIONS for k in comparison_fields)], comparison_rows())
    sheet('Silver references', ['Pair_ID', 'VI_ID', 'VI_Text', 'ChatGPT_Han_Text', 'DeepSeek_Han_Text',
          'ChatGPT_Span', 'DeepSeek_Span', 'Provisional_Label'], ([s['Pair_ID'], s['VI_ID'], s['Vietnamese'],
          s['Chinese'], s['comparison']['DeepSeek_Han'], s['han_link']['global_raw_span'],
          s['comparison']['deepseek_han_link']['global_raw_span'], s['Label_Target']] for s in silver))
    assert rw.max_row - 1 == scopes['ALL']['V0']['candidates']
    assert pc.max_row - 1 == scopes['ALL']['V0']['silver_eligible']
    wb.save(path)


def report(data):
    scopes = data['metrics']
    whole = scopes['ALL']
    lines = ['# Đánh giá lại Alignment API (offline)', '',
             f"Đọc lại **{data['responses_replayed']}** phản hồi gốc; bỏ {data['cached_log_entries_excluded']} lượt dùng cache. "
             'Chạy lại V0 bằng logic cũ và đối chiếu trực tiếp các dòng metrics/cặp Silver lưu từ lần trước. Không gọi API.', '',
             '| Chỉ số | V0 | V1 | V2 |', '|---|---:|---:|---:|']
    for label, formatter in [
        ('Dòng chưa ánh xạ được', lambda m: m['unresolved_rows']),
        ('Nhóm gộp', lambda m: m['aggregated_groups']),
        ('VI_ID đầy đủ theo phản hồi', lambda m: m['full_vi_response_id_pairs']),
        ('VI_ID đầy đủ duy nhất theo phản hồi', lambda m: m['unique_full_vi_response_id_pairs']),
        ('VI_ID đầy đủ khác nhau toàn pilot (kể cả đối chứng)', lambda m: m['distinct_full_vi_ids']),
        ('Exact ChatGPT', lambda m: f"{m['exact_chatgpt']}/{m['silver_eligible']}"),
        ('Exact DeepSeek', lambda m: f"{m['exact_deepseek']}/{m['silver_eligible']}"),
        ('Exact đồng thuận', lambda m: f"{m['exact_agreed']}/{m['agreed_eligible']}"),
        ('IoU Hán trung bình (CG / DS)', lambda m: f"{m['mean_han_iou_chatgpt']:.3f} / {m['mean_han_iou_deepseek']:.3f}"),
        ('Độ phủ ký tự Hán / Việt', lambda m: f"{m['han_coverage']:.2%} / {m['vi_coverage']:.2%}"),
        ('Ký tự Hán / Việt bị phủ trùng', lambda m: f"{m['han_duplicate_chars']} / {m['vi_duplicate_chars']}"),
    ]:
        lines.append(f'| {label} | ' + ' | '.join(str(formatter(whole[v])) for v in VERSIONS) + ' |')
    lines += ['', '“VI_ID đầy đủ” tính một lần cho mỗi cặp (phản hồi, VI_ID) có toàn bộ đoạn nằm trong một '
              'ứng viên Hán–Việt ánh xạ được; chỉ số “duy nhất” loại các trường hợp có nhiều ứng viên cùng phủ hết ID. '
              'Độ phủ/trùng tính bên trong từng phản hồi thành công rồi cộng, không coi việc chạy lại hay cửa sổ chồng lấn là lỗi. '
              'Silver dùng cùng mẫu số cho ba phiên bản và không dùng điều khiển mapping/gộp; IoU bằng 0 nếu không có một '
              'dự đoán duy nhất cho cả đoạn Việt. Đây là số liệu đồng thuận ranh giới, không phải xác nhận nghĩa.', '',
              '## Direct S4', '', '| Phiên bản | Exact CG / DS | Exact đồng thuận | IoU CG / DS |', '|---|---:|---:|---:|']
    for v, m in scopes['E01-S4'].items():
        lines.append(f"| {v} | {m['exact_chatgpt']}/{m['silver_eligible']} / {m['exact_deepseek']}/{m['silver_eligible']} | "
                     f"{m['exact_agreed']}/{m['agreed_eligible']} | {m['mean_han_iou_chatgpt']:.3f} / {m['mean_han_iou_deepseek']:.3f} |")
    lines += ['', '## Thay đổi thực tế', '',
              f"- V1 khôi phục {data['rescued_rows']} dòng chưa ánh xạ ở V0; "
              f"{data['newly_unresolved_rows']} dòng đi theo chiều ngược lại. "
              'Fallback không chấp nhận cắt giữa một số, ví dụ chỉ trả `727 bát` trong khi `727` là phần cuối của số nguồn.',
              f"- V2 tạo {len(data['aggregation_examples'])} nhóm liên tục, đủ đoạn. "
              'Không tự nối qua khoảng trống, overlap hay dòng của một VI_ID khác.']
    for g in data['aggregation_examples'][:8]:
        lines.append(f"  - {g['experiment']} / {g['response']}: {g['vi_id']}, dòng API {g['rows']}; Hán {g['han_span']}.")
    for g in data['adjacent_chain_breaks'][:8]:
        lines.append(f"  - Không gộp {g['experiment']} / {g['vi_id']}, dòng {g['rows']}: "
                     f"điểm nối Hán {g['han_join']}, điểm nối Việt {g['vi_join']}. Hai đầu phải bằng nhau ở cả hai vế.")
    if data['v1_unresolved_causes']:
        reasons = ', '.join(f"`{k}`: {n}" for k,n in data['v1_unresolved_causes'].items())
        lines += ['', 'Trạng thái ánh xạ Hán / Việt của các dòng còn lại ở V1: ' + reasons + '.']
    lines += ['', 'Workbook `comparison.xlsx`: `Mapping rows` giữ từng dòng API và kết quả V0/V1/V2; '
              'V2 lặp span nhóm trên các dòng nguồn trong bảng truy vết, nhưng mỗi nhóm chỉ tính một lần trong metrics. '
              '`Silver comparison` hiển thị ba dự đoán và hai tham chiếu trên cùng dòng.']
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=INPUT)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output exists; choose a new directory')
    sources = [args.input / p for p in ('requests.jsonl', 'metrics.csv', 'pair_comparison.csv')]
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    all_entries = v0.load_jsonl(sources[0])
    entries = [e for e in all_entries if not e['cached']]
    if not entries or len({e['id'] for e in entries}) != len(entries) or any('raw_response' not in e for e in entries):
        raise ValueError('Every real response needs a unique ID and a stored raw response')
    raw, _, viet_source, *_ = v0.inputs()
    silver = v0.load_jsonl(v0.ARTIFACTS / 'phase1/silver_benchmark.jsonl')
    if any(v0.normalize(raw[a:b]) != unit for e in entries for (a,b), unit in
           zip(e['job']['h'], e['job']['payload']['han'].split('\n'), strict=True)):
        raise ValueError('Source OCR and saved payload do not match')
    if any(viet_source[key]['text_original'] != unit for e in entries for key, unit in
           zip(e['job']['v'], e['job']['payload']['vi'].split('\n'), strict=True)):
        raise ValueError('Saved Vietnamese units must match source to report original VI offsets')
    runs, pairs = evaluate(entries, raw, silver)
    verify_baseline(runs['V0'], pairs['V0'], args.input)
    transitions = Counter((a['Validation_Status'] in UNRESOLVED, b['Validation_Status'] in UNRESOLVED)
                          for x, y in zip(runs['V0'], runs['V1'])
                          for a, b in zip(x['candidates'], y['candidates'], strict=True))
    examples = [dict(experiment=c['Experiment_ID'], response=c['API_Response_ID'], vi_id=c['VI_IDs'][0],
                     rows=c['Source_Rows'], han_span=[c['Han_Start'], c['Han_End']])
                for r in runs['V2'] for c in r['candidates'] if len(c['Source_Rows']) > 1]
    chain_breaks = []
    for r in runs['V1']:
        for a, b in zip(r['candidates'], r['candidates'][1:]):
            if (len(a['VI_IDs']) != 1 or a['VI_IDs'] != b['VI_IDs'] or a['Han_End'] is None or b['Han_Start'] is None
                    or {a['Validation_Status'], b['Validation_Status']} - {'mapped', 'partial_viet'}):
                continue
            han_join = [a['Han_End'], b['Han_Start']]
            vi_join = [a['VI_Char_Spans'][0][2], b['VI_Char_Spans'][0][1]]
            if han_join[0] != han_join[1] or vi_join[0] != vi_join[1]:
                chain_breaks.append(dict(experiment=r['job']['id'], vi_id=a['VI_IDs'][0], rows=[a['Row'],b['Row']],
                                         han_join=han_join, vi_join=vi_join))
    unresolved = Counter(f"{c['Han_Resolution']} / {c['VI_Resolution']}" for r in runs['V1'] for c in r['candidates']
                         if c['Validation_Status'] in UNRESOLVED)
    data = dict(responses_replayed=len(entries), cached_log_entries_excluded=len(all_entries)-len(entries),
                source_sha256=hashes, api_requests=0, baseline_verified=True,
                rescued_rows=transitions[(True,False)], newly_unresolved_rows=transitions[(False,True)],
                aggregation_examples=examples, adjacent_chain_breaks=chain_breaks, v1_unresolved_causes=dict(unresolved),
                metrics=scoped_metrics(runs,pairs))
    args.output.mkdir(parents=True, exist_ok=False)
    export_excel(args.output/'comparison.xlsx', entries, runs, pairs, silver, data['metrics'])
    v0.write(args.output/'metrics.json', json.dumps(data, ensure_ascii=False, indent=2)+'\n')
    v0.write(args.output/'report.md', report(data))
    print(f"Replayed {len(entries)} saved responses; API requests: 0; output: {args.output}")


if __name__ == '__main__':
    main()
