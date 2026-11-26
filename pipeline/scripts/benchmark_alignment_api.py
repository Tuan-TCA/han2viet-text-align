"""Run the Cap_01 Alignment API pilot. Silver is loaded only for evaluation."""

import argparse
import csv
import hashlib
import json
import os
import re
import statistics
import time
from email.utils import parsedate_to_datetime
from collections import Counter
from pathlib import Path

import requests

from test_separate_api import ARTIFACTS, content_offsets, load_jsonl


# Wire contract from 04_dong_hang/temp/align_sinonom_api.py. Transport here
# retains unsuccessful responses and disables redirects for the experiment log.
URL = 'https://kimhannom.fit.hcmus.edu.vn/api/web/clc-sinonom/sentence-alignment'
HALT_CODES = {'000108', '000401', '000403', '000429', '401', '403', '429'}
STAGES = [f'E{i:02}' for i in range(1, 7)]
SHAPES = [(1, 1), (2, 1), (3, 1), (4, 1), (2, 2), (4, 2), (4, 4), (8, 4)]
CONTROLS = [('Cap_01-VI-0221-001', 'Cap_01-VI-0221-002'),
            ('Cap_01-VI-0250-003', 'Cap_01-VI-0250-004')]


def dump(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, allow_nan=False)


def fingerprint(obj):
    return hashlib.sha256(dump(obj).encode('utf-8')).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, text):
    with path.open('x', encoding='utf-8', newline='') as f:
        f.write(text)


def inputs():
    pages = {r['id']: r for r in load_jsonl(ARTIFACTS / 'phase1/han_pages.jsonl')}
    raw = ''.join(pages[f'Cap_01-HAN-{i:03}']['text_original'] for i in (1, 2))
    cases = read(ARTIFACTS / 'separate_pilot_cap01/results.json')['cases']
    units = [[s for s in c['analysis']['projected_sentences']] for c in cases]
    _, offsets = content_offsets(raw)
    ends = lambda x: {s['global_raw_span'][1] for s in x}
    weak, strong = set(), set()
    for s in units[2]:
        a, b = s['global_raw_span']
        _, pos = content_offsets(raw[a:b])
        count = 0
        for ch in s['text_api']:
            count += bool(content_offsets(ch)[0])
            if ch in '，、；;：:' and 0 < count < len(pos):
                point = a + pos[count - 1] + 1
                weak.add(point)
                if ch in '；;：:':
                    strong.add(point)
    s1, s2 = ends(units[0] + units[1]), ends(units[2])
    fine = set(s2)
    for point in sorted(strong) + sorted(weak - strong):
        if min(abs(point - cut) for cut in fine | {0}) >= 12:
            fine.add(point)
    strategies = {'S0': spans({len(raw)}), 'S1': spans(s1), 'S2': spans(s2),
                  'S3': spans(s1 | s2), 'S4': spans(fine)}
    assert len(raw) == 905 and len(offsets) == 904
    for h in strategies.values():
        assert h[0][0] == 0 and h[-1][1] == len(raw) and ''.join(raw[a:b] for a, b in h) == raw
    viet = {v['id']: v for v in load_jsonl(ARTIFACTS / 'phase1/viet_segments.jsonl') if v['cap'] == 'Cap_01'}
    pilot = [k for k, v in viet.items() if v['viet_page_start'] <= 188 and v['viet_page_end'] >= 186]
    assert len(pilot) == 12 and [len(strategies[s]) for s in ('S1', 'S2')] == [24, 29]
    maps = {r['viet_pdf_page']: r['verified_overlap'] for r in load_jsonl(ARTIFACTS / 'phase1/page_mapping.jsonl')
            if r['cap'] == 'Cap_01' and r['verified_overlap']}
    assert all(maps[viet[k]['viet_page_start']][0]['han_pdf_page'] > 2 for group in CONTROLS for k in group)
    return raw, strategies, viet, pilot, weak, maps


def spans(cuts):
    cuts = [0] + sorted(set(cuts) - {0})
    return list(zip(cuts, cuts[1:]))


def normalize(s):
    return ' '.join(s.split())


def job(stage, name, strategy, h, vs, raw, viet, repeat=None):
    h = [list(x) for x in h]
    ht = [normalize(raw[a:b]) for a, b in h]
    vt = [normalize(viet[k]['text_original']) for k in vs]
    assert all(ht) and all(vt)
    payload = {'han': '\n'.join(ht), 'vi': '\n'.join(vt)}
    key = fingerprint([URL, payload])
    return dict(stage=stage, id=f'{stage}-{name}', strategy=strategy, h=h, v=list(vs),
                payload=payload, key=key, repeat_of=repeat)


def resolve(texts, lo, hi, snippet):
    """Prefer valid indices corroborated by text, else a unique exact text match.

    Normalization ignores whitespace only. Returns per-unit character positions
    in normalized payloads, preserving partial matches and rejecting ambiguity.
    """
    if snippet is not None and not isinstance(snippet, str):
        return [], 'invalid_text'
    snippet = normalize(snippet or '')
    valid = type(lo) is type(hi) is int and 0 <= lo <= hi < len(texts)
    if valid and (not snippet or snippet == ' '.join(texts[lo:hi+1])):
        return [(i, 0, len(texts[i])) for i in range(lo, hi+1)], 'indices_text' if snippet else 'indices_only'
    if type(lo) is type(hi) is int and lo == hi == -1 and not snippet:
        return [], 'empty'
    if not snippet:
        return [], 'invalid_range'
    joined = ' '.join(texts)
    starts = [m.start() for m in re.finditer('(?=' + re.escape(snippet) + ')', joined)]
    if len(starts) != 1:
        return [], 'ambiguous' if starts else 'text_mismatch'
    start, end = starts[0], starts[0] + len(snippet)
    parts, offset = [], 0
    for i, text in enumerate(texts):
        left, right = max(0, start-offset), min(len(text), end-offset)
        if left < right:
            parts.append((i, left, right))
        offset += len(text) + 1
    return parts, 'exact_text_fallback'


def parse(j, response, raw):
    if response['status'] != 'success':
        return []
    body = json.loads(response['raw_response'])
    ht, vt = (j['payload'][k].split('\n') for k in ('han', 'vi'))
    candidates = []
    for n, row in enumerate(body['data']['result']):
        invalid_row = not isinstance(row, dict)
        row = {} if invalid_row else row
        hs, hstatus = resolve(ht, row.get('han_start'), row.get('han_end'), row.get('han_text'))
        vs, vstatus = resolve(vt, row.get('vi_start'), row.get('vi_end'), row.get('vietnamese_text'))
        hp = []
        for i, left, right in hs:
            a, b = j['h'][i]
            ix = [k for m in re.finditer(r'\S+', raw[a:b]) for k in [*range(m.start(), m.end()), m.end()]][:-1]
            hp.append((a if not left else a + ix[left], b if right == len(ht[i]) else a + ix[right-1] + 1))
        start, end = (hp[0][0], hp[-1][1]) if hp else (None, None)
        ids = [j['v'][i] for i, _, _ in vs]
        full_vi = all(a == 0 and b == len(vt[i]) for i, a, b in vs)
        fail = {'invalid_text', 'invalid_range', 'ambiguous', 'text_mismatch'}
        status = ('ambiguous' if 'ambiguous' in (hstatus, vstatus) else
                  'untraceable' if invalid_row or fail & {hstatus, vstatus} or not (hs or vs) else
                  'partial_viet' if not full_vi else 'mapped' if hs and vs else 'unpaired')
        shape = ('0-1' if not hs else '1-0' if not vs else
                 ('1' if len(hs) == 1 else 'N') + '-' + ('1' if len(vs) == 1 else 'M' if len(hs) > 1 else 'N'))
        candidates.append(dict(Han_Start=start, Han_End=end, Han_Text=raw[start:end] if hp else '', VI_IDs=ids,
                               Vietnamese_Text=' '.join(vt[i][a:b] for i, a, b in vs), Alignment_Type=shape,
                               Segmentation_Strategy=j['strategy'], Experiment_ID=j['id'], API_Response_ID=response['id'],
                               Validation_Status=status, Han_Resolution=hstatus, VI_Resolution=vstatus,
                               Han_Partial_Unit=any(a or b != len(ht[i]) for i, a, b in hs),
                               VI_Char_Spans=[(j['v'][i], a, b) for i, a, b in vs], Score=row.get('score'), Row=n))
    return candidates


def coverage(j, cs):
    good = [c for c in cs if c['Validation_Status'] in {'mapped', 'partial_viet', 'unpaired'}]
    paired = [c for c in good if c['Han_Start'] is not None and c['VI_IDs']]
    hc = Counter(k for c in paired for k in range(c['Han_Start'], c['Han_End']))
    vc = Counter((k, x) for c in paired for k, a, b in c['VI_Char_Spans'] for x in range(a, b))
    n = sum(len(t) for t in j['payload']['vi'].split('\n'))
    miss = [k for a, b in j['h'] for k in range(a, b) if not hc[k]]
    gaps = []
    for k in miss:
        if gaps and gaps[-1][1] == k:
            gaps[-1][1] += 1
        else:
            gaps.append([k, k+1])
    vi_order = {k: i for i, k in enumerate(j['v'])}
    order = [(c['Han_Start'], vi_order[c['VI_IDs'][0]], c['VI_Char_Spans'][0][1]) for c in paired]
    return dict(paired=len(paired), han_coverage=len(hc)/sum(b-a for a,b in j['h']), vi_character_coverage=len(vc)/n,
                han_duplicate_chars=sum(v > 1 for v in hc.values()), vi_duplicate_chars=sum(v > 1 for v in vc.values()),
                unaligned_han=gaps, unaligned_vi=[k for k in j['v'] if not any(key == k for key, _ in vc)],
                order_violations=sum(1 for i, a in enumerate(order) for b in order[i+1:]
                                     if a[0] > b[0] or a[1:] > b[1:] or (a[0] < b[0] and a[1:] > b[1:])),
                explicit_unpaired=sum(c['Validation_Status'] == 'unpaired' for c in good),
                partial_han_pairs=sum(c['Han_Partial_Unit'] for c in paired),
                unresolved_rows=sum(c['Validation_Status'] in {'untraceable', 'ambiguous'} for c in cs),
                nm_pairs=sum(c['Alignment_Type'] == 'N-M' for c in paired))


def crop(seq, length, center):
    length = min(length, len(seq))
    start = max(0, min(len(seq)-length, round(center * len(seq) - length / 2)))
    return seq[start:start+length]


def retry_deadline(value, now):
    try:
        return now + max(0, int(value))
    except (TypeError, ValueError):
        try:
            stamp = parsedate_to_datetime(value)
            return max(now, stamp.timestamp()) if stamp.tzinfo else None
        except (TypeError, ValueError, OverflowError):
            return None


class Runner:
    def __init__(self, args, token):
        self.args, self.token, self.root = args, token, args.output
        self.root.mkdir(parents=True, exist_ok=args.resume)
        (self.root / 'cache').mkdir(exist_ok=args.resume)
        self.log = self.root / 'requests.jsonl'
        self.entries = load_jsonl(self.log) if self.log.exists() else []
        self.halt = None
        if getattr(args, 'persist_retry_after', False):
            deadline = max((e.get('retry_until',0) for e in self.entries), default=0)
            if deadline > time.time():
                self.halt = 'server_retry_after'
        self.last = 0
        self.session = requests.Session()
        self.session.headers.update({'Authorization': f'Bearer {token}', 'Accept': 'application/json', 'User-Agent': 'Mozilla/5.0'})

    def close(self):
        self.session.close()

    def record(self, item):
        with self.log.open('a', encoding='utf-8') as f:
            f.write(dump(item) + '\n')
        self.entries.append(item)

    def run(self, j):
        prior = [e for e in self.entries if e['job']['id'] == j['id'] and e['job']['key'] == j['key']]
        if prior and prior[-1]['status'] not in {'transport_error', 'auth_or_rate_limit', 'transient_http'}:
            return prior[-1]
        if self.halt:
            return None
        if not j['repeat_of']:
            cache = self.root / 'cache' / (j['key'] + '.json')
            if cache.exists():
                e = {**read(cache), 'job': j, 'cached': True}
                self.record(e)
                return e
        for retry in range(self.args.retries + 1):
            sent = sum(not r['cached'] for r in self.entries)
            if self.args.request_budget is not None and sent >= self.args.request_budget:
                self.halt = 'client_request_budget'
                return None
            time.sleep(max(0, self.args.delay - (time.monotonic() - self.last)))
            start = time.perf_counter()
            entry = dict(id=f'R{sent+1:04}', job=j, cached=False, attempt=retry+1)
            if getattr(self.args, 'persist_retry_after', False):
                entry['endpoint'] = URL
            try:
                resp = self.session.post(URL, json=j['payload'], timeout=(10, self.args.timeout), allow_redirects=False)
                raw_response = resp.text.replace(self.token, '[REDACTED]')
                headers = {k.lower(): v.replace(self.token, '[REDACTED]') for k,v in resp.headers.items()
                           if re.search('rate.?limit|quota|retry-after|^x-request-id$', k, re.I)}
                try:
                    body = json.loads(raw_response)
                except ValueError:
                    body = None
                code = body.get('code') if isinstance(body, dict) else None
                data = body.get('data') if isinstance(body, dict) else None
                entry.update(raw_response=raw_response, http=resp.status_code, headers=headers, code=code)
                if resp.status_code in {401, 403, 429} or str(code) in HALT_CODES:
                    entry['status'] = self.halt = 'auth_or_rate_limit'
                elif resp.status_code in {408, 500, 502, 503, 504}:
                    entry['status'] = 'transient_http'
                elif resp.status_code == 200 and isinstance(body, dict) and body.get('is_success') is True:
                    entry['status'] = 'success' if isinstance(data, dict) and isinstance(data.get('result'), list) else 'parse_error'
                elif body is None and resp.status_code == 200:
                    entry['status'] = 'parse_error'
                else:
                    entry['status'] = 'api_error'
                if any(v.strip() == '0' for k, v in headers.items() if 'remaining' in k):
                    self.halt = 'server_quota_exhausted'
                if resp.status_code in {503, 429} and 'retry-after' in headers:
                    self.halt = 'server_retry_after'
                    if getattr(self.args, 'persist_retry_after', False):
                        deadline = retry_deadline(headers['retry-after'], time.time())
                        if deadline is not None:
                            entry['retry_until'] = deadline
            except requests.RequestException as exc:
                entry.update(status='transport_error', error=type(exc).__name__)
            self.last = time.monotonic()
            entry['latency_ms'] = round((time.perf_counter() - start)*1000)
            self.record(entry)
            print(f"{entry['id']} {j['id']} {entry['status']} {entry.get('code')}", flush=True)
            if entry['status'] == 'success':
                cache = self.root / 'cache' / (j['key'] + '.json')
                if not j['repeat_of'] and not cache.exists():
                    write(cache, dump(entry) + '\n')
            if self.halt or entry['status'] not in {'transport_error', 'transient_http'} or retry == self.args.retries:
                return entry
            time.sleep(1 + retry)


def experiments(runner, raw, strategies, viet, pilot, weak, maps):
    runs, all_candidates = [], []

    def run(stage, name, s, h, v, repeat=None):
        j = job(stage, name, s, h, v, raw, viet, repeat)
        response = runner.run(j)
        if response is None:
            return None
        cs = parse(j, response, raw)
        run = dict(job=j, status=response['status'], response_id=response['id'], candidates=cs)
        if response['status'] == 'success':
            run.update(coverage(j, cs))
        runs.append(run)
        all_candidates.extend(cs)
        return run

    for s, hs in strategies.items():
        run('E01', s, s, hs, pilot)
    # Rank the starter strategy by parsability and integrity, not Silver.
    direct = [r for r in runs if r['status'] == 'success' and r['job']['strategy'] != 'S0']
    def quality(r):
        return (-r['unresolved_rows'], -r['han_duplicate_chars']-r['vi_duplicate_chars'],
                -r['order_violations'], bool(r['paired']), r['job']['strategy'] == 'S2')
    preferred = max(direct, key=quality)['job']['strategy'] if direct else 'S2'
    h = strategies[preferred]
    for i, (nh, nv) in enumerate(SHAPES):
        # Source order for coarse position. Vietnamese anchors 186/187/188
        # overlap Han page 1 / both / 2; never use Silver spans.
        frac = (0.24, 0.50, 0.76)[i % 3]
        hs = crop(h, nh, frac)
        ref_pages = {1 if a < 446 else 2 for a, _ in hs} | {1 if b <= 446 else 2 for _, b in hs}
        pool = [k for k in pilot if any(p['han_pdf_page'] in ref_pages
                                        for p in maps.get(viet[k]['viet_page_start'], []))]
        if len(pool) < nv:
            pool = pilot
        vc = 0.5 if pool != pilot else frac
        run('E02', f'{nh}x{nv}', preferred, hs, crop(pool, nv, vc))
    for i in range(0, len(h)-3, 2):
        frac = (i+2)/len(h)
        hs = h[i:i+4]
        for shift in (-1, 0, 1) if i in {len(h)//4*2, 2} else (0,):
            j = max(0, min(len(pilot)-4, round(frac*len(pilot)-2)+shift))
            run('E03', f'h{i:02}-v{j:02}-s{shift:+}', preferred, hs, pilot[j:j+4])
    for i, vs in enumerate(CONTROLS):
        run('E04', f'negative-{i+1}', preferred, crop(h, 2, 0.2+0.6*i), vs)
    successful = [r for r in runs if r['status'] == 'success' and r['job']['stage'] in {'E01','E02','E03'}]
    for stage in ('E01','E03'):
        options = [r for r in successful if r['job']['stage'] == stage]
        if options:
            old = max(options, key=quality)['job']
            run('E05', stage, old['strategy'], old['h'], old['v'], old['id'])
    # Pick problem windows from output defects or a failed API request, never Silver.
    local = [r for r in runs if r['job']['stage'] in {'E02','E03'} and len(r['job']['h']) >= 2]
    def defect(r):
        return (r['status'] != 'success', r.get('unresolved_rows',0), r.get('han_duplicate_chars',0),
                r.get('vi_duplicate_chars',0), len(r.get('unaligned_han',[])))
    distinct = set()
    for old in sorted(local, key=defect, reverse=True):
        if defect(old) == (False, 0, 0, 0, 0) or len(distinct) >= 3:
            break
        j = old['job']
        a,b = j['h'][0][0], j['h'][-1][1]
        if (a,b) in distinct:
            continue
        distinct.add((a,b))
        run('E06', j['id']+'-merge', preferred+'-merge', [(a,b)], j['v'])
        extra = {p for p in weak if a+5 < p < b-5 and all(abs(p-end) >= 6 for _,end in j['h'])}
        if extra:
            borders = [a] + sorted(set(x[1] for x in j['h']) | extra)
            run('E06', j['id']+'-split', preferred+'-split', list(zip(borders,borders[1:])), j['v'])
        p = pilot.index(j['v'][0]); q = p+len(j['v'])
        expanded = pilot[max(0,p-1):min(len(pilot),q+1)]
        if expanded != j['v']:
            run('E06', j['id']+'-context', preferred, j['h'], expanded)
    return runs, all_candidates, preferred


def iou(a, b):
    intersection = max(0, min(a[1], b[1])-max(a[0], b[0]))
    return intersection / (a[1]-a[0]+b[1]-b[0]-intersection)


def evaluate(runs, silver):
    end = max(s['Han_End_exclusive'] for s in silver)
    pairs = []
    for run in runs:
        j = run['job']
        if run['status'] != 'success':
            continue
        mapped = [c for c in run['candidates'] if c['Validation_Status'] == 'mapped']
        run['out_of_scope_han_paired'] = len({k for c in run['candidates'] if c['Validation_Status'] in
                                              {'mapped', 'partial_viet'} for k in range(max(end,c['Han_Start']), c['Han_End'])})
        if j['stage'] == 'E04':
            continue
        own = []
        for s in silver:
            if s['VI_ID'] not in j['v']:
                continue
            cg = s['han_link']['global_raw_span']
            ds = s['comparison']['deepseek_han_link']['global_raw_span']
            # Require both possible reference spans in the input window; don't
            # penalize a deliberately unavailable reference in a local test.
            if not (j['h'][0][0] <= min(cg[0],ds[0]) and max(cg[1],ds[1]) <= j['h'][-1][1]):
                continue
            matches = [c for c in mapped if c['VI_IDs'] == [s['VI_ID']]]
            c = matches[0] if len(matches) == 1 else None
            pred = [c['Han_Start'],c['Han_End']] if c else None
            own.append(dict(Experiment_ID=j['id'], Pair_ID=s['Pair_ID'], VI_ID=s['VI_ID'],
                            Provisional_Label=s['Label_Target'], ChatGPT_Span=cg, DeepSeek_Span=ds,
                            Agreed_Reference=cg==ds, Silver_Han=s['Chinese'], Silver_DeepSeek_Han=s['comparison']['DeepSeek_Han'],
                            Vietnamese=s['Vietnamese'], Predicted_Span=pred, Predicted_Han=c['Han_Text'] if c else '',
                            Predicted_Vietnamese=c['Vietnamese_Text'] if c else '',
                            Viet_Exact_Unique=bool(c), Exact_ChatGPT=pred==cg, Exact_DeepSeek=pred==ds,
                            IoU_ChatGPT=iou(pred,cg) if pred else 0, IoU_DeepSeek=iou(pred,ds) if pred else 0,
                            Overlapping_VI_Predictions=[dict(span=[x['Han_Start'],x['Han_End']],
                                                            ids=x['VI_IDs'], han=x['Han_Text'],
                                                            vi=x['Vietnamese_Text'], status=x['Validation_Status'])
                                                        for x in run['candidates'] if s['VI_ID'] in x['VI_IDs']]))
        pairs.extend(own)
        run.update(silver_eligible=len(own), silver_unique_vi=sum(p['Viet_Exact_Unique'] for p in own),
                   exact_cg=sum(p['Exact_ChatGPT'] for p in own), exact_ds=sum(p['Exact_DeepSeek'] for p in own),
                   agreed_eligible=sum(p['Agreed_Reference'] for p in own),
                   agreed_exact=sum(p['Agreed_Reference'] and p['Exact_ChatGPT'] for p in own),
                   iou_cg=statistics.mean(p['IoU_ChatGPT'] for p in own) if own else None,
                   iou_ds=statistics.mean(p['IoU_DeepSeek'] for p in own) if own else None)
    return pairs, end


def signature(r, include_score=False):
    return sorted(dump([c['Han_Start'], c['Han_End'], c['VI_Char_Spans'], c['Han_Text'], c['Vietnamese_Text'],
                        c['Validation_Status']] + ([c['Score']] if include_score else [])) for c in r['candidates'])


def summary(runs, entries, halt, preferred, end):
    sent = [r for r in entries if not r['cached']]
    phases = {}
    for stage in STAGES:
        rr = [r for r in runs if r['job']['stage']==stage]
        calls = [r for r in sent if r['job']['stage']==stage]
        phases[stage] = dict(jobs=len(rr), requests=len(calls), statuses=dict(Counter(r['status'] for r in rr)),
                             error_rate=sum(r['status']!='success' for r in calls)/len(calls) if calls else None,
                             latency_ms_median=statistics.median(r['latency_ms'] for r in calls) if calls else None)
    known = {r['job']['id']: r for r in runs}
    stability = []
    for r in runs:
        parent = known.get(r['job']['repeat_of'])
        if parent and r['status']==parent['status']=='success':
            stability.append(dict(comparison=[parent['job']['id'],r['job']['id']],
                                  same_groups_spans=signature(r)==signature(parent),
                                  same_including_scores=signature(r, True)==signature(parent, True),
                                  row_counts=[len(parent['candidates']),len(r['candidates'])]))
    # A full Vietnamese ID can be reused across windows. Count the distinct Han
    # spans actually proposed for it, rather than assuming all overlaps are errors.
    proposals = {}
    for r in runs:
        if r['job']['stage']=='E03':
            for c in r['candidates']:
                if c['Validation_Status']=='mapped' and len(c['VI_IDs'])==1:
                    proposals.setdefault(c['VI_IDs'][0], []).append([c['Han_Start'],c['Han_End']])
    return dict(requests=len(sent), cached_routes=sum(r['cached'] for r in entries),
                halt=halt, preferred_for_windows=preferred, phases=phases, stability=stability,
                sliding_single_vi_proposals=proposals, silver_end_exclusive=end,
                quota_headers=[{'response': r['id'], **r['headers']} for r in sent if r.get('headers')],
                semantic_verification='not_performed',
                raw_http_error_count=sum(r['status']!='success' for r in sent))


def write_csv(path, rows, fields):
    with path.open('x', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fields, extrasaction='ignore')
        w.writeheader()
        w.writerows({k:dump(v) if isinstance(v,(list,dict)) else v for k,v in r.items()} for r in rows)


def publish(out, runs, candidates, pairs, result):
    fields = ['Han_Start','Han_End','Han_Text','VI_IDs','Vietnamese_Text','Alignment_Type','Segmentation_Strategy',
              'Experiment_ID','API_Response_ID','Validation_Status','Han_Resolution','VI_Resolution','Han_Partial_Unit',
              'VI_Char_Spans','Score','Row']
    write(out/'candidates.jsonl', ''.join(dump(c)+'\n' for c in candidates))
    write_csv(out/'predictions.csv', candidates, fields)
    write_csv(out/'pair_comparison.csv', pairs, ['Experiment_ID','Pair_ID','VI_ID','Vietnamese','Silver_Han',
              'Silver_DeepSeek_Han','ChatGPT_Span','DeepSeek_Span','Provisional_Label','Agreed_Reference',
              'Predicted_Span','Predicted_Han','Predicted_Vietnamese','Viet_Exact_Unique','Exact_ChatGPT',
              'Exact_DeepSeek','IoU_ChatGPT','IoU_DeepSeek','Overlapping_VI_Predictions'])
    metric_rows = [dict(**{k:v for k,v in r.items() if k not in {'job','candidates'}},
                        experiment=r['job']['id'], strategy=r['job']['strategy']) for r in runs]
    metrics = ['experiment','strategy','status','response_id','paired','explicit_unpaired','partial_han_pairs',
               'nm_pairs','unresolved_rows','han_coverage','vi_character_coverage','han_duplicate_chars',
               'vi_duplicate_chars','order_violations','unaligned_han','unaligned_vi','out_of_scope_han_paired',
               'silver_eligible','silver_unique_vi','exact_cg','exact_ds','agreed_eligible','agreed_exact','iou_cg','iou_ds']
    write_csv(out/'metrics.csv', metric_rows, metrics)
    write(out/'results.json', json.dumps({**result, 'experiments': metric_rows}, ensure_ascii=False, indent=2)+'\n')
    lines = ['# Benchmark Alignment API — Cap_01', '',
             f"**{result['requests']} request thực tế**, {result['cached_routes']} lần dùng cache. "
             f"Trạng thái dừng: {result['halt'] or 'hoàn tất tập thử nghiệm khả thi'}.", '',
             'Hán gửi nguyên `[0, 905)` trong direct; `[893, 905)` được theo dõi ngoài phạm vi Silver. '
             'Không gán OMISSION/ADDITION/MISSING tự động. S1–S4 thay biên trên chữ OCR gốc để cô lập tác động của segmentation.', '',
             '| Thí nghiệm | Job có kết quả | Request thực | Trạng thái job | Lỗi theo request | Latency trung vị (ms) |',
             '|---|---:|---:|---|---:|---:|']
    for e, p in result['phases'].items():
        lines.append(f"| {e} | {p['jobs']} | {p['requests']} | {p['statuses']} | {p['error_rate']} | {p['latency_ms_median']} |")
    lines += ['', '## E01 — direct, cùng phạm vi đầu vào', '',
              '| Cấu hình | Trạng thái | Cặp truy được | Exact CG / DS | Exact đồng thuận | IoU CG / DS |',
              '|---|---|---:|---:|---:|---:|']
    for r in metric_rows:
        if r['experiment'].startswith('E01'):
            lines.append(f"| {r['strategy']} | {r['status']} | {r.get('paired','—')} | "
                         f"{r.get('exact_cg','—')} / {r.get('exact_ds','—')} | "
                         f"{r.get('agreed_exact','—')}/{r.get('agreed_eligible','—')} | "
                         f"{r.get('iou_cg','—')} / {r.get('iou_ds','—')} |")
    controls = [r for r in metric_rows if r['experiment'].startswith('E04')]
    lines += ['', '## Diễn giải', '',
              '- **Cách API trả kết quả:** request `han`/`vi` là hai chuỗi phân dòng; response dự kiến '
              '`data.result` chứa các nhóm chỉ số inclusive. Script đối chiếu văn bản nếu API trả văn bản, '
              'và cho phép ánh xạ substring duy nhất để phát hiện biên trong đơn vị.',
              f"- **Segmentation:** chiến lược dùng cho cửa sổ: {result['preferred_for_windows']} "
              '(chọn theo lỗi cấu trúc direct, không dựa vào Silver). Bảng direct so ảnh hưởng đến độ đồng thuận, chưa xác minh nghĩa.',
              '- **Direct / sliding:** đối chiếu từng cặp ở `pair_comparison.csv`; tập tham chiếu từng cửa sổ có thể khác nhau. '
              'Các đề xuất sliding chưa được hợp nhất thành một dự đoán toàn pilot.',
              '- **Đối chứng âm:** Việt 221 (thống kê Phú Châu/Tịch Tượng, có mốc Hán 027) và Việt 250 '
              '(lệ lính cắt cỏ voi/ngựa, có mốc Hán 052) nằm ngoài vùng Hán 001–002 theo nguồn độc lập Silver. '
              'Số cặp truy được: '+(', '.join(f"{r['experiment']}={r.get('paired','—')} ({r['status']})" for r in controls) or 'chưa có')+'.',
              f"- **N–M:** {sum(r.get('nm_pairs',0) for r in metric_rows)} lượt nhóm N–M truy được trên các job "
              '(có thể trùng do cửa sổ chồng lấn/lượt lặp). Đây là dấu hiệu hỗ trợ cấu trúc, không phải xác minh nghĩa.',
              f"- **Stability:** {result['stability'] or 'chưa có hai phản hồi thành công để so sánh'}.",
              '- **Post-processing:** kiểm tra trùng ký tự, đảo thứ tự, thiếu phủ, biên nội đơn vị và cả đoạn ngoài phạm vi; '
              'xem `metrics.csv` và `error_analysis.md`.',
              '- **Consensus / DP:** dữ liệu pilot chỉ đủ nhận diện lỗi cấu trúc và đưa ra giả thuyết; cần rà nghĩa '
              'và xác nhận trên vùng mới trước khi chọn kiến trúc.', '',
              'Mẫu số exact/IoU: chỉ cặp Silver có đủ cả vế Việt và hai span tham chiếu trong input. '
              'Một dự đoán hợp lệ phải phủ đúng một VI_ID đầy đủ và duy nhất; thiếu/không duy nhất nhận IoU 0 theo quy ước '
              'đối chiếu, không phải nhãn sai nghĩa. Mẫu số direct thành công là 12.']
    write(out/'report.md', '\n'.join(lines)+'\n')
    errors = ['# Phân tích lỗi Alignment API', '',
              'Lỗi dưới đây là lỗi API, mapping hoặc khác biệt với ứng viên Silver, không phải nhãn lỗi ngữ nghĩa.', '']
    for r in metric_rows:
        if r['status']!='success':
            errors.append(f"- `{r['experiment']}` / `{r['response_id']}`: {r['status']}; xem request và raw response.")
        elif any(r.get(k) for k in ('unresolved_rows','unaligned_han','unaligned_vi','han_duplicate_chars','vi_duplicate_chars','order_violations','out_of_scope_han_paired')):
            keys = ('unresolved_rows','unaligned_han','unaligned_vi','han_duplicate_chars','vi_duplicate_chars',
                    'order_violations','out_of_scope_han_paired')
            errors.append(f"- `{r['experiment']}`: "+'; '.join(f'{k}={r[k]}' for k in keys if r.get(k))+'.')
    errors += ['', '## Sai khác biên direct với cả hai đề xuất Silver', '']
    for p in pairs:
        if p['Experiment_ID'].startswith('E01') and not (p['Exact_ChatGPT'] or p['Exact_DeepSeek']):
            errors.append(f"- `{p['Experiment_ID']}` / `{p['Pair_ID']}`: dự đoán {p['Predicted_Span']}; "
                          f"CG {p['ChatGPT_Span']}; DS {p['DeepSeek_Span']}.")
    write(out/'error_analysis.md', '\n'.join(errors)+'\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ARTIFACTS/'alignment_benchmark')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--request-budget', type=int, help='Optional cumulative cap including retries; default unlimited')
    parser.add_argument('--delay', type=float, default=0.8)
    parser.add_argument('--timeout', type=float, default=35)
    parser.add_argument('--retries', type=int, default=1)
    args = parser.parse_args()
    if args.delay < 0 or args.timeout <= 0 or args.retries < 0 or (args.request_budget is not None and args.request_budget <= 0):
        parser.error('Invalid delay, timeout, request budget or retry count')
    fixture = inputs()
    raw, strategies, viet, pilot, _, _ = fixture
    if args.dry_run:
        for s, h in strategies.items():
            j = job('E01',s,s,h,pilot,raw,viet)
            print(s, len(h), 'Han units', len(pilot), 'Viet units, hash', j['key'][:12])
        print('Dry-run: no request sent; later phases based on observed E01 results.')
        return 0
    if args.output.exists() and not args.resume:
        parser.error('Output exists; choose a new directory or use --resume')
    token = os.environ.get('SINONOM_TOKEN','').strip()
    if token.lower().startswith('bearer '):
        token = token[7:].strip()
    if not token:
        parser.error('Set SINONOM_TOKEN')
    runner = Runner(args, token)
    try:
        runs, candidates, preferred = experiments(runner, *fixture)
    finally:
        runner.close()
    pairs, end = evaluate(runs, load_jsonl(ARTIFACTS/'phase1/silver_benchmark.jsonl'))
    result = summary(runs, runner.entries, runner.halt, preferred, end)
    out = args.output
    if any((out/p).exists() for p in ('candidates.jsonl','predictions.csv','metrics.csv','pair_comparison.csv',
                                       'results.json','report.md','error_analysis.md')):
        out = out/f'resume-{time.time_ns()}'
        out.mkdir()
    publish(out, runs, candidates, pairs, result)
    print(f"{out}: {result['requests']} real requests; halt={runner.halt}")
    return int(bool(runner.halt))


if __name__ == '__main__':
    raise SystemExit(main())
