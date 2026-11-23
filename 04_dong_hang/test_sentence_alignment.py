"""Kiểm tra sentence-alignment bằng cùng cơ chế gọi API của notebook 01_nom_ocr.

Chạy: python test_sentence_alignment.py
Token: biến môi trường SINONOM_TOKEN hoặc nhập khi chạy.
"""
import getpass
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request

API_BASE = 'https://kimhannom.fit.hcmus.edu.vn/api/web/clc-sinonom/'
USER_AGENT = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
              'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36')
LIMITS = ((60, 25), (3600, 50), (86400, 200), (604800, 600))
LEDGER_FILE = Path(__file__).resolve().parent / '.api_requests.json'


def get_request_events():
    if LEDGER_FILE.exists():
        try:
            return json.loads(LEDGER_FILE.read_text(encoding='utf-8'))
        except Exception:
            return []
    return []


def save_request_events(events):
    LEDGER_FILE.write_text(json.dumps(events[-1000:], indent=2), encoding='utf-8')


def wait_for_quota():
    now = time.time()
    events = [t for t in get_request_events() if t > now - 604800]
    delay = max(0.0, max(events, default=now - 2.5) + 2.5 - now)
    for window, limit in LIMITS:
        recent = sorted(t for t in events if t > now - window)
        if len(recent) >= limit:
            delay = max(delay, recent[len(recent) - limit] + window + 0.5 - now)
    if delay > 0:
        print(f'Đang chờ quota rate-limit: {delay:.1f}s...')
        time.sleep(delay)
    events.append(time.time())
    save_request_events(events)


def call_kim_api(endpoint: str, body: bytes, content_type: str, token: str) -> dict:
    wait_for_quota()
    req = urllib.request.Request(
        API_BASE + endpoint,
        data=body,
        headers={
            'User-Agent': USER_AGENT,
            'Authorization': 'Bearer ' + token,
            'Content-Type': content_type,
            'Accept': 'application/json'
        },
        method='POST'
    )
    print('POST:', API_BASE + endpoint)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode('utf-8')
            print('HTTP:', resp.status)
    except urllib.error.HTTPError as err:
        print('HTTP:', err.code)
        print('Response:', err.read().decode('utf-8', errors='replace'))
        raise
    envelope = json.loads(raw)
    print('Response:', json.dumps(envelope, ensure_ascii=False, indent=2))
    if not isinstance(envelope, dict) or envelope.get('code') != '000000' or envelope.get('is_success') is not True:
        raise ValueError(f'API error on {endpoint}: {envelope}')
    return envelope['data']


def main():
    token = os.getenv('SINONOM_TOKEN', '').strip()
    if not token:
        token = getpass.getpass('Nhập Bearer token (không hiển thị): ').strip()
    if token.lower().startswith('bearer '):
        token = token[7:].strip()
    if not token:
        raise ValueError('Thiếu token')
    # Payload chính xác theo ví dụ sentence-alignment trong PDF (trang 6).
    payload = {
        'han': '洪德十八年冬十二月。\n帝遣阮仁政徃福州。',
        'vi': 'Tháng mười hai mùa đông năm Hồng Đức thứ 18.\nNhà vua sai Nguyễn Nhân Chính đến Phúc Châu.'
    }
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    print('Payload:', json.dumps(payload, ensure_ascii=False, indent=2))
    data = call_kim_api('sentence-alignment', body, 'application/json', token)
    output = Path(__file__).resolve().parent / 'sentence_alignment_result.json'
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print('SUCCESS. Saved:', output)


if __name__ == '__main__':
    try:
        main()
    except Exception as err:
        print('FAILED:', err)
        raise SystemExit(1)
