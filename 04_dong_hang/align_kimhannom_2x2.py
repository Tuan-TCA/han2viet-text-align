#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test Kim Han Nom API: first TWO Han sentences vs consecutive TWO-Viet windows.

No local alignment model or algorithm is used. Each request is independent.

PowerShell:
    $env:SINONOM_TOKEN = "YOUR_TOKEN"
    python align_kimhannom_2x2.py 1 12 20 22
    python align_kimhannom_2x2.py 1 12 20 22 --max-requests 3

For 189 Vietnamese fragments, this produces up to 95 requests:
    Han[0:2] vs Viet[0:2], Han[0:2] vs Viet[2:4], ...
A trailing single Vietnamese sentence is skipped (never silently duplicated).

Output: JSONL log of requests and raw API responses, plus a JSON summary.
Install: pip install requests pandas
"""

import argparse
import json
import os
import time
from pathlib import Path

from align_kimhannom_api import load_inputs, URL, SCRIPT_DIR
import requests


def call_api(han_two: list[str], vi_two: list[str], token: str, timeout: int = 120) -> dict:
    token = token.strip().removeprefix("Bearer ").strip()
    if not token:
        raise ValueError('Missing token. PowerShell: $env:SINONOM_TOKEN = "YOUR_TOKEN"')
    payload = {"han": "\n".join(han_two), "vi": "\n".join(vi_two)}
    response = requests.post(
        URL, json=payload, timeout=timeout,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/138.0.0.0 Safari/537.36",
        },
    )
    response.raise_for_status()
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(f"Non-JSON response: {response.text[:500]}") from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cap", type=int)
    parser.add_argument("page", type=int)
    parser.add_argument("vi_start", type=int, nargs="?", default=None)
    parser.add_argument("vi_end", type=int, nargs="?", default=None)
    parser.add_argument("--base-dir", type=Path, default=SCRIPT_DIR.parent)
    parser.add_argument("--output-dir", type=Path, default=SCRIPT_DIR)
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds between API calls")
    parser.add_argument("--max-requests", type=int, default=None, help="Limit calls during testing")
    args = parser.parse_args()
    if args.delay < 0 or (args.max_requests is not None and args.max_requests < 1):
        parser.error("--delay must be >= 0 and --max-requests must be >= 1")

    han, vi = load_inputs(args.cap, args.page, args.vi_start, args.vi_end, args.base_dir)
    if len(han) < 2 or len(vi) < 2:
        raise ValueError("At least 2 Han and 2 Vietnamese sentences are required")

    BATCH_SIZE = 4

    han_two = han[:BATCH_SIZE]
    vi_windows = [
        (i, vi[i:i+BATCH_SIZE])
        for i in range(0, len(vi) - BATCH_SIZE + 1, BATCH_SIZE)
    ]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"Cap{args.cap:02d}_Trang{args.page}_first2Han"
    log_path = args.output_dir / f"{stem}_api_calls.jsonl"
    summary_path = args.output_dir / f"{stem}_summary.json"
    token = os.getenv("SINONOM_TOKEN", "")
    print(f"Han: {len(han)} sentences (using first 2). Viet: {len(vi)} fragments.")
    print(f"Requests: {len(vi_windows)} (fixed Han 1-2, Viet in consecutive pairs).")
    if len(vi) % 2:
        print(f"Last Vietnamese fragment #{len(vi)} is unpaired and will not be sent.")

    success = failed = 0
    with log_path.open("w", encoding="utf-8") as log:
        for req_no, (start, vi_two) in enumerate(vi_windows, 1):
            row = {
                "request": req_no,
                "han_indices_1based": [1, 2],
                "vi_indices_1based": [start + 1, start + 2],
                "payload": {"han": "\n".join(han_two), "vi": "\n".join(vi_two)},
            }
            try:
                envelope = call_api(han_two, vi_two, token)
                row["response"] = envelope
                row["ok"] = envelope.get("is_success") is True and envelope.get("code") == "000000"
                if row["ok"]:
                    success += 1
                else:
                    failed += 1
                    row["error"] = envelope.get("message")
            except (requests.RequestException, RuntimeError, ValueError) as exc:
                row["ok"] = False
                row["error"] = str(exc)
                failed += 1
            log.write(json.dumps(row, ensure_ascii=False) + "\n")
            log.flush()  # Keep results even if the script is interrupted
            print(f"[{req_no}/{len(vi_windows)}] Han 1-2 / Viet {start+1}-{start+2}: "
                  f"{'OK' if row['ok'] else 'FAILED'}")
            if req_no < len(vi_windows):
                time.sleep(args.delay)

    summary = {"han_used": han_two, "total_vi_fragments": len(vi),
               "requests": len(vi_windows), "successful": success, "failed": failed,
               "unpaired_vi_fragment": vi[-1] if len(vi) % 2 else None,
               "log_file": str(log_path)}
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Done: {success} OK, {failed} FAILED")
    print(f"Raw results: {log_path}\nSummary: {summary_path}")


if __name__ == "__main__":
    main()
