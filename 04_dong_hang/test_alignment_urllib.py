"""Test Kim Hán Nôm sentence splitting with SINONOM_TOKEN."""
import json
import os

import requests

BASE_URL = "https://kimhannom.fit.hcmus.edu.vn"
ENDPOINT = "/api/web/clc-sinonom/separate-sentences"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/138.0.0.0 Safari/537.36"
    ),
    "Content-Type": "application/json",
    "Accept": "application/json",
}


def call_api(endpoint, payload):
    token = os.getenv('SINONOM_TOKEN', '').strip()
    if token.lower().startswith('bearer '):
        token = token[7:].strip()
    if not token:
        raise ValueError('Missing SINONOM_TOKEN environment variable')
    response = requests.post(
        BASE_URL + endpoint,
        headers={**HEADERS, 'Authorization': f'Bearer {token}'},
        data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        timeout=60,
    )
    print("HTTP:", response.status_code)
    print("Response:", response.text)
    response.raise_for_status()

    result = response.json()
    if result.get('is_success') is not True or result.get('code') != '000000':
        raise RuntimeError(f"API Error: {result.get('code')} - {result.get('message')}")
    return result['data']


if __name__ == '__main__':
    payload = {
        'text': (
            '天地玄黃宇宙洪荒日月盈昃辰宿列張'
            '寒來暑往秋收冬藏閏餘成歲律呂調陽'
            '雲騰致雨露結為霜金生麗水玉出崑岡'
        ),
        'genre': 'history',
        'punctuation_group': 'all',
    }
    try:
        data = call_api(ENDPOINT, payload)
        print('\n=== RESULT ===')
        print(json.dumps(data, ensure_ascii=False, indent=2))
        if isinstance(data, dict) and 'sentences' in data:
            print('\n=== TEXT ===')
            print(data['sentences'])
    except Exception as exc:
        print('\nERROR:', exc)
        raise SystemExit(1) from None
