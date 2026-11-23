#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diagnose Kim Han Nom APIs using the same token, headers, and small official examples.

PowerShell:
    $env:SINONOM_TOKEN = "YOUR_TOKEN"
    python test_sinonom_endpoints.py
    python test_sinonom_endpoints.py --only separate
    python test_sinonom_endpoints.py --only alignment

Install: pip install requests

Never paste tokens in chat or commit them to version control.
"""

import argparse
import json
import os
import sys
import time
from urllib.parse import urlparse

import requests

BASE_URL = "https://kimhannom.fit.hcmus.edu.vn"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/138.0.0.0 Safari/537.36"
)

CASES = {
    "separate": {
        "endpoint": "/api/web/clc-sinonom/separate-sentences",
        "payload": {
            "text": "天地玄黃宇宙洪荒日月盈昃辰宿列張寒來暑往秋收冬藏閏餘成歲律呂調陽雲騰致雨露結為霜金生麗水玉出崑岡",
            "genre": "history",
            "punctuation_group": "all",
        },
    },
    "alignment": {
        "endpoint": "/api/web/clc-sinonom/sentence-alignment",
        "payload": {
            "han": "洪德十八年冬十二月。\n帝遣阮仁政徃福州。",
            "vi": "Tháng mười hai mùa đông năm Hồng Đức thứ 18.\nNhà vua sai Nguyễn Nhân Chính đến Phúc Châu.",
        },
    },
}


def test_one(session, name, base_url, timeout):
    case = CASES[name]
    url = base_url.rstrip("/") + case["endpoint"]
    print(f"\n===== {name.upper()} =====", flush=True)
    print("POST:", url)
    try:
        resp = session.post(url, json=case["payload"], timeout=timeout, allow_redirects=False)
    except requests.RequestException as exc:
        print("NETWORK ERROR:", type(exc).__name__, str(exc))
        return "network_error"

    print("HTTP status:", resp.status_code)
    print("User-Agent sent:", resp.request.headers.get("User-Agent"))
    authorization = resp.request.headers.get("Authorization", "")
    print("Bearer token sent:", authorization.startswith("Bearer ") and len(authorization) > 7)
    print("Content-Type sent:", resp.request.headers.get("Content-Type"))
    if 300 <= resp.status_code < 400:
        print("Redirect location:", resp.headers.get("Location", ""))

    try:
        body = resp.json()
    except ValueError:
        print("Non-JSON response (truncated):", resp.text[:1200])
        return "non_json"

    # No token, secrets, or request headers are printed.
    print("Response JSON:")
    print(json.dumps(body, ensure_ascii=False, indent=2)[:3500])
    if resp.status_code != 200:
        print("RESULT: HTTP rejected (authentication, access, redirect, or server issue).")
        return "http_error"
    if not isinstance(body, dict):
        print("RESULT: Unexpected JSON structure.")
        return "invalid_json"
    if body.get("is_success") is not True or body.get("code") != "000000":
        print("RESULT: Application-level error (the API returned a failure code).")
        return "app_error"
    print("RESULT: SUCCESS")
    return "success"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=["both", "separate", "alignment"], default="both")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--delay", type=float, default=5.0, help="Seconds between calls (default 5)")
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()
    if args.delay < 0:
        parser.error("--delay must be >= 0")
    parsed = urlparse(args.base_url)
    if parsed.scheme != "https" or not parsed.netloc:
        parser.error("--base-url must be a valid HTTPS URL")

    token = os.getenv("SINONOM_TOKEN", "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token:
        print('ERROR: Set token in PowerShell: $env:SINONOM_TOKEN = "..."', file=sys.stderr)
        return 2

    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    names = list(CASES) if args.only == "both" else [args.only]
    results = {}
    for index, name in enumerate(names):
        if index:
            print(f"\nDelaying {args.delay:g}s between API requests...")
            time.sleep(args.delay)
        results[name] = test_one(session, name, args.base_url, args.timeout)
    print("\n===== SUMMARY =====")
    for name, status in results.items():
        print(f"{name}: {status}")
    if results.get("separate") == "success" and results.get("alignment") == "app_error":
        print("Interpretation: Shared authorization/header setup works for at least one API; investigate sentence-alignment service or endpoint permissions.")
    elif results and all(status == "app_error" for status in results.values()):
        print("Interpretation: Both API calls returned application errors; check account access, quota, or backend health. Exact cause cannot be inferred from this result alone.")
    return 0 if all(s == "success" for s in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
