"""Kiểm tra chuỗi Kim Hán Nôm OCR theo cell 8/14 của 01_nom_ocr(1).ipynb.

Điểm sửa duy nhất trong phần request: mã hóa toàn bộ multipart header thành bytes
trước khi ghép ảnh; notebook gốc ghép str + bytes gây TypeError.

Cách chạy:
  python test_kimhannom_notebook_exact.py "C:\\path\\to\\image.jpg"
  # Token đọc từ KIMHAN_NOM_API_TOKEN; nếu thiếu sẽ hỏi tương tác.
"""
import getpass
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request
import uuid

API_BASE = 'https://kimhannom.fit.hcmus.edu.vn/api/web/clc-sinonom/'
USER_AGENT = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
              'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36')
LIMITS = ((60, 25), (3600, 50), (86400, 200), (604800, 600))
WORKSPACE = Path(__file__).resolve().parent
LEDGER_FILE = WORKSPACE / '.api_requests.json'


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
    print(f'\nPOST {API_BASE + endpoint}', flush=True)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            envelope = json.loads(resp.read().decode('utf-8'))
            print('HTTP:', resp.status)
    except urllib.error.HTTPError as exc:
        print('HTTP:', exc.code)
        print(exc.read().decode('utf-8', errors='replace'))
        raise
    print('API code:', envelope.get('code') if isinstance(envelope, dict) else None)
    if not isinstance(envelope, dict) or envelope.get('code') != '000000' or envelope.get('is_success') is not True:
        raise ValueError(f'API error on {endpoint}: {envelope}')
    return envelope['data']


def upload_image(image_bytes: bytes, filename: str, token: str) -> str:
    boundary = 'nom-' + uuid.uuid4().hex
    # FIX bắt buộc: notebook gốc thiếu .encode() trên phần header multipart.
    body = (
        (f'--{boundary}\r\nContent-Disposition: form-data; '
         f'name="image_file"; filename="{filename}"\r\n'
         'Content-Type: image/jpeg\r\n\r\n').encode('utf-8')
        + image_bytes
        + f'\r\n--{boundary}--\r\n'.encode('ascii')
    )
    data = call_kim_api('image-upload', body, f'multipart/form-data; boundary={boundary}', token)
    return data['file_name']


def ocr_image(server_filename: str, token: str) -> dict:
    # 1. Structure classification (giữ nguyên hành vi tiếp tục nếu lỗi)
    cls_payload = json.dumps({'file_name': server_filename, 'ocr_id': 0, 'lang_type': 0, 'reading_direction': 0}).encode('utf-8')
    try:
        call_kim_api('structure-classification', cls_payload, 'application/json', token)
    except Exception as e:
        print(f'Structure classification warning: {e}')
    # 2. Image OCR
    ocr_payload = json.dumps({'file_name': server_filename, 'ocr_id': 1, 'lang_type': 2, 'reading_direction': 1, 'epitaph': 0, 'tag': None}).encode('utf-8')
    return call_kim_api('image-ocr', ocr_payload, 'application/json', token)


def main():
    if len(sys.argv) != 2:
        print(f'Usage: python "{Path(__file__).name}" "path/to/image.jpg"')
        return 2
    image_path = Path(sys.argv[1]).expanduser()
    if not image_path.is_file():
        print('Không tìm thấy ảnh:', image_path)
        return 2
    token = os.environ.get('KIMHAN_NOM_API_TOKEN', '').strip()
    if not token:
        token = getpass.getpass('Dán token (không hiển thị): ').strip()
    if not token:
        print('Thiếu token.')
        return 2
    server_filename = upload_image(image_path.read_bytes(), image_path.name, token)
    print('Server file_name:', server_filename)
    data = ocr_image(server_filename, token)
    out = image_path.with_name(image_path.stem + '-ocr.json')
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print('SUCCESS. Saved:', out)
    print('Response fields:', list(data) if isinstance(data, dict) else type(data).__name__)
    if isinstance(data, dict):
        details = data.get('details', {})
        boxes = details.get('details', []) if isinstance(details, dict) else []
        print('OCR boxes:', len(boxes) if isinstance(boxes, list) else 'unknown')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print('FAILED:', repr(exc))
        sys.exit(1)
