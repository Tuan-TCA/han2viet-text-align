#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test Kim Han Nom sentence-alignment API with the documented 2-sentence example.

PowerShell:
    $env:SINONOM_TOKEN = "YOUR_TOKEN"
    python test_sinonom_api.py

Requires: pip install requests
"""

import json
import os
import sys
import requests

URL = "https://kimhannom.fit.hcmus.edu.vn/api/web/clc-sinonom/sentence-alignment"
PAYLOAD = {
    "han": "洪德十八年冬十二月。\n帝遣阮仁政徃福州。",
    "vi": "Tháng mười hai mùa đông năm Hồng Đức thứ 18.\nNhà vua sai Nguyễn Nhân Chính đến Phúc Châu.",
}


def main():
    token = os.getenv("SINONOM_TOKEN", "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token:
        print('Missing token. PowerShell: $env:SINONOM_TOKEN = "YOUR_TOKEN"')
        return 2

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/138.0.0.0 Safari/537.36"
        ),
    }
    try:
        response = requests.post(URL, headers=headers, json=PAYLOAD, timeout=60)
    except requests.RequestException as exc:
        print("Network error:", exc)
        return 1

    print("Endpoint:", URL)
    print("User-Agent sent:", response.request.headers.get("User-Agent"))
    print("Authorization header present:", bool(response.request.headers.get("Authorization")))
    print("HTTP status:", response.status_code)
    try:
        data = response.json()
        print("Response JSON:")
        print(json.dumps(data, ensure_ascii=False, indent=2))
    except ValueError:
        print("Non-JSON response (first 1500 characters):")
        print(response.text[:1500])
        return 1

    if response.status_code != 200:
        print("RESULT: HTTP failure")
        return 1
    if data.get("is_success") is not True:
        print("RESULT: API returned application-level failure")
        return 1

    results = (data.get("data") or {}).get("result")
    print(f"RESULT: SUCCESS, {len(results) if isinstance(results, list) else 'unknown'} alignment groups")
    return 0


if __name__ == "__main__":
    sys.exit(main())
