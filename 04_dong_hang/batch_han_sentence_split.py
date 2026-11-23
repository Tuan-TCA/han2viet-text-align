"""Split the first ten Cap_01 OCR pages with SinoNom's sentence API."""

import argparse
import csv
import json
import os
from pathlib import Path
import re
import time
import unicodedata

import requests


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / '02_ocr_tho/Cap_01/HAN/pages'
OUTPUT = ROOT / '03_text_sach/Cap_01/HAN/segmented'
URL = 'https://kimhannom.fit.hcmus.edu.vn/api/web/clc-sinonom/separate-sentences'
RETRYABLE = {408, 429, 500, 502, 503, 504}


def content(text):
    """Ignore punctuation and whitespace, but retain OCR letters and numbers."""
    return ''.join(c for c in text if not c.isspace() and not unicodedata.category(c).startswith('P'))


def load_page(page):
    src = SOURCE / f'Cap01-{page:03}.json'
    data = json.loads(src.read_text(encoding='utf-8-sig'))
    rows = sorted(data['rows'], key=lambda row: row['segment'])
    if (data['info']['cap'] != 'Cap_01' or data['info']['page'] != page
            or [row['segment'] for row in rows] != list(range(1, len(rows) + 1))):
        raise ValueError(f'Invalid page or segment sequence: {src.name}')
    text = ''.join(''.join(row['han'].split()) for row in rows)
    if not content(text):
        raise ValueError(f'Empty OCR page: {src.name}')
    return src, rows, text


def split_result(result):
    if not isinstance(result, str):
        return []
    if result.lstrip().startswith('{'):
        try:
            wrapped = json.loads(result)
        except ValueError:
            return []
        result = wrapped.get('sentences') if isinstance(wrapped, dict) else None
        if not isinstance(result, str):
            return []
    return [line.strip() for line in re.findall(r'[^。！？!?\r\n]+(?:[。！？!?]+[」』”’）】]*)?', result)
            if line.strip()]


def write_page(page, text, lines, record):
    output = OUTPUT / f'{page:04}-sentences.csv'
    with output.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['id_zh', 'text_zh'])
        writer.writerows((f'Cap01-{page:03}-S{i:03}', line) for i, line in enumerate(lines, 1))
    same_content = content(''.join(lines)) == content(text)
    record.update(status='ok' if same_content else 'content_mismatch',
                  sentence_count=len(lines), output=output.name)


def reparse_saved(pages):
    """Recover responses stored as literal JSON wrapper rows by an earlier run."""
    report_path = OUTPUT / 'run_summary.json'
    report = json.loads(report_path.read_text(encoding='utf-8'))
    updates = []
    for record in report['pages']:
        if record['status'] != 'content_mismatch' or 'output' not in record:
            continue
        with (OUTPUT / record['output']).open(encoding='utf-8-sig', newline='') as f:
            result = '\n'.join(row['text_zh'] for row in csv.DictReader(f))
        if result.lstrip().startswith('{') and (lines := split_result(result)):
            updates.append((record['page'], pages[record['page'] - 1][2], lines, record))
    for args in updates:
        write_page(*args)
    report_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return 0 if all(row['status'] == 'ok' for row in report['pages']) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--delay', type=float, default=0.5, help='Seconds between pages')
    parser.add_argument('--reparse-saved', action='store_true', help='Recover saved JSON wrapper rows without API calls')
    args = parser.parse_args()
    if args.delay < 0:
        parser.error('--delay must be nonnegative')
    pages = [load_page(page) for page in range(1, 11)]
    if args.reparse_saved:
        return reparse_saved(pages)
    token = os.environ.get('SINONOM_TOKEN', '').strip()
    if token.lower().startswith('bearer '):
        token = token[7:].strip()
    if not token:
        parser.error('Set SINONOM_TOKEN before running the batch')

    OUTPUT.mkdir(exist_ok=True)
    summary = []
    with requests.Session() as session:
        session.headers.update({
            'Authorization': f'Bearer {token}',
            'Accept': 'application/json',
            'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                           'AppleWebKit/537.36 Chrome/138.0.0.0 Safari/537.36'),
        })
        for page, (src, rows, text) in enumerate(pages, 1):
            if page > 1:
                time.sleep(args.delay)
            record = {'page': page, 'source': src.name, 'ocr_segments': len(rows),
                      'input_chars': len(text), 'attempts': [], 'status': 'failed'}
            summary.append(record)
            stop = False
            for attempt in range(2):
                try:
                    response = session.post(URL, json={
                        'text': text, 'ocr_id': 1, 'genre': 'history', 'punctuation_group': 'all',
                    }, timeout=(10, 90), allow_redirects=False)
                except (requests.ConnectionError, requests.Timeout) as exc:
                    record['attempts'].append({'error': type(exc).__name__})
                    if not attempt:
                        time.sleep(2)
                        continue
                    break

                status = response.status_code
                info = {'http_status': status}
                record['attempts'].append(info)
                try:
                    body = response.json()
                except ValueError:
                    body = {}
                if not isinstance(body, dict):
                    body = {}
                code = body.get('code')
                if isinstance(code, (int, str)):
                    info['api_code'] = code
                if status in (401, 403) or str(code) in {'000108', '000401', '000403', '401', '403'}:
                    stop = True
                    break
                if status == 429 and attempt:
                    stop = True
                    break
                if status in RETRYABLE and not attempt:
                    retry_after = response.headers.get('Retry-After')
                    if retry_after and (not retry_after.isdecimal() or int(retry_after) > 30):
                        stop = True
                        break
                    time.sleep(max(2, int(retry_after or 0)))
                    continue
                if status != 200 or body.get('is_success') is not True:
                    break
                data = body.get('data')
                result = data.get('sentences') if isinstance(data, dict) else None
                lines = split_result(result)
                if not lines:
                    info['error'] = 'Missing data.sentences'
                    break
                write_page(page, text, lines, record)
                break
            print(f'Page {page:02}: {record["status"]} ({record.get("sentence_count", 0)} sentences), '
                  f'{record["attempts"]}', flush=True)
            if stop:
                summary.extend({'page': remaining, 'status': 'not_attempted'} for remaining in range(page + 1, 11))
                break

    report = {'endpoint': URL, 'delay_seconds': args.delay,
              'requests': sum(len(row.get('attempts', [])) for row in summary), 'pages': summary}
    (OUTPUT / 'run_summary.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return 0 if all(row['status'] == 'ok' for row in summary) else 1


if __name__ == '__main__':
    raise SystemExit(main())
