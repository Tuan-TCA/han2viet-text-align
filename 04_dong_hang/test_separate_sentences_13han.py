#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test Kim Han Nom separate-sentences API with 13 ground-truth Han sentences concatenated.

Run:
    pip install requests
    python test_separate_sentences_13han.py

Optional authenticated endpoint:
    PowerShell: $env:SINONOM_TOKEN = 'YOUR_TOKEN'
    python test_separate_sentences_13han.py

Optional endpoint override:
    python test_separate_sentences_13han.py --url https://kimhannom.fit.hcmus.edu.vn/api/web/clc-sinonom/separate-sentences
"""
import argparse
import json
import os
import sys
from pathlib import Path

import requests

API_URL = "https://kimhannom.clc.hcmus.edu.vn/api/web/clc-sinonom/separate-sentences"
SCRIPT_DIR = Path(__file__).resolve().parent

# Original OCR DeepSeek text, exactly as provided; do NOT insert GT sentence boundaries.
HAN_TEXT = (
    "爭拘該項陋示至今有一社至十六七將陸二十餘社長而待應務者止以許知押為額目耳"
    "各馭有給夫千人免民丁雜役使之具肩阮為富祿又同拘候夫礼該礼米產借貼船歲該富春"
    "知巴丑年并奉府美濟該兵五兩米十五鉢美零例導各飛兵七陌米十五鉢記兵一貫社置把度該受"
    "各八陌米十二鉢該官正司官各一貫三陌司官一兵二陌米十五鉢首合該合"
    "各九陌米十三鉢將度七陌米十鉢社長七陌米八鉢中等記度七陌米十鉢下等記度各陌米八鉢"
    "各馭共二百七十八人納該共二百十三兵七陌米共二千七百二十七鉢"
    "其餘從富祿該例別納別兵社坊及親見丁數富祿礼該兩人三文每百人呈面米五升"
    "美該大社一陌中社三十文稍該每人七文二分"
    "巴旦弁奉府各縣屬一萬四千三百四十九人收各該共四百八十三兵三陌三十二文米共七百四十九合"
    "除產借該每一百四陌米每巴一陌不狹廣南該順化亦熟亦細碎矣"
    "順廣諸營許司吏与行各縣本堂賦色各效累該收丁該田粟其收各吏各馭不為捱矢如有受歷該并美該替恨例"
    "各營該合首合附去累簡繁省或該十三貫糴恨二窠次者該六貫恨八兩前者該三長恨"
    "壹月五該司吏二貫鎮該案該八貫覃提馭与該廵除該營該十四貫"
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Call SinoNom separate-sentences API")
    parser.add_argument("--url", default=API_URL)
    parser.add_argument("--genre", default="history")
    parser.add_argument("--punctuation-group", default="all")
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()

    payload = {
        "text": HAN_TEXT,
        "genre": args.genre,
        "punctuation_group": args.punctuation_group,
    }
    (SCRIPT_DIR / "separate_sentences_request.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/138.0.0.0 Safari/537.36",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    token = os.getenv("SINONOM_TOKEN", "").strip()
    if token:
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        headers["Authorization"] = f"Bearer {token}"

    print(f"Endpoint: {args.url}")
    print(f"Input: {len(HAN_TEXT)} Han characters; 13 GT sentences concatenated")
    print("Calling separate-sentences...")
    try:
        response = requests.post(args.url, json=payload, headers=headers, timeout=args.timeout)
    except requests.RequestException as exc:
        print(f"Network error: {exc}", file=sys.stderr)
        return 1

    print(f"HTTP: {response.status_code}")
    try:
        result = response.json()
    except ValueError:
        print("Non-JSON response:", response.text[:2000], file=sys.stderr)
        return 1

    (SCRIPT_DIR / "separate_sentences_response.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if not response.ok or result.get("is_success") is not True:
        print("API error:", json.dumps(result, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    sentences = (result.get("data") or {}).get("sentences")
    if not isinstance(sentences, str):
        print("Unexpected response: data.sentences must be a string", file=sys.stderr)
        return 1

    lines = [line.strip() for line in sentences.splitlines() if line.strip()]
    (SCRIPT_DIR / "separate_sentences_output.txt").write_text(sentences, encoding="utf-8")
    print(f"\nResult: {len(lines)} lines (Ground Truth: 13)\n")
    for idx, line in enumerate(lines, 1):
        print(f"[{idx:02d}] {line}")
    print("\nSaved: separate_sentences_request.json")
    print("Saved: separate_sentences_response.json")
    print("Saved: separate_sentences_output.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
