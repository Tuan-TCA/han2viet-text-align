#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compare Kim Han Nom sentence alignment for raw OCR and DeepSeek OCR.

PowerShell:
    pip install requests
    $env:SINONOM_TOKEN = "YOUR_TOKEN"
    python test_alignment_2_ocr.py

Produces:
    alignment_2_ocr_results.json  (complete request/response pairs)
    alignment_2_ocr_results.txt   (readable alignment output)

Each OCR version is sent in an independent request against the same Vietnamese
translation. The API may be designed for sentence-segmented text: results from
these unsegmented paragraphs must therefore be interpreted with care.
"""

import json
import os
import sys
from pathlib import Path

import requests

URL = "https://kimhannom.fit.hcmus.edu.vn/api/web/clc-sinonom/sentence-alignment"
OUT_DIR = Path(__file__).resolve().parent

HAN_RAW = """納承願憑示至今有一社至十六七將臣二十餘社長百得應務者正許知押為額目耳各賦有給夫干人免民丁雜役使取其齋鄉為寓祿又同納猴夫禮歲礼米雇借附船獻祕富春卯已丑年升葬府亥府成一亥五阳米十五秩黃陽刑導各年亥七門半十五年記府一貫記舉祀西讀總法夢各八內朱十二肄後官正司官各一貴三門司官一長二門米十五肄首合後合各九附米十三餘將臣七陌米十鋒社長七限米八鉢中等记函七陽米十年下等祀丞云四米八詩各聊共二百七十八人納殊共二百十三長七門米共二千七百二十七年其餘作富祿及别初荆載又社坊必抑見丁數寓祿礼侯每人主文每百人呈面米五升美味大社一陷中社三十文稱歲每人七文二分卯已丑升華府各縣屬一萬四千三百四十九人收各歲共四百八十三長三四三十六文米共七百十四升九合除產借殘每一百四防米每邑一陌不狹廣南於順化亦然亦細碎矣順廣諸當許司吏与許各縣本堂或色若效眾多按收丁歲田粟其收各吏各取不為控矣如有受惡歲并美底替限例谷宮後合首合附去緊間繁爾者或減十三貫稽限二家次者咏六賞退八兩尚者侯三長限臺刃五侯司吏二貫鎮祿案詠八貨庫提欲與疾也孫該管歲四貨"""

HAN_DEEPSEEK = """爭拘該項陋示至今有一社至十六七將陸二十餘社長而待應務者止以許知押為額目耳各馭有給夫千人免民丁雜役使之具肩阮為富祿又同拘候夫礼該礼米產借貼船歲該富春知巴丑年并奉府美濟該兵五兩米十五鉢美零例導各飛兵七陌米十五鉢記兵一貫社置把度該受各八陌米十二鉢該官正司官各一貫三陌司官一兵二陌米十五鉢首合該合各九陌米十三鉢將度七陌米十鉢社長七陌米八鉢中等記度七陌米十鉢下等記度各陌米八鉢各馭共二百七十八人納該共二百十三兵七陌米共二千七百二十七鉢其餘從富祿該例別納別兵社坊及親見丁數富祿礼該兩人三文每百人呈面米五升美該大社一陌中社三十文稍該每人七文二分巴旦弁奉府各縣屬一萬四千三百四十九人收各該共四百八十三兵三陌三十二文米共七百四十九合除產借該每一百四陌米每巴一陌不狹廣南該順化亦熟亦細碎矣順廣諸營許司吏与行各縣本堂賦色各效累該收丁該田粟其收各吏各馭不為捱矢如有受歷該并美該替恨例各營該合首合附去累簡繁省或該十三貫糴恨二窠次者該六貫恨八兩前者該三長恨壹月五該司吏二貫鎮該案該八貫覃提馭与該廵除該營該十四貫"""

VI = """tiền lĩnh bằng và tiền ngụ lộc các quan cộng là 5 quan; do đó mà mọi người tranh nhau nộp tiển lĩnh bằng, đến nay có chỗ một xã có đến 16 hay 17 tướng thần, hơn 20 xã trưởng, đều được làm việc, chỉ cho viên tri áp làm đầu mục thôi. Các chức được cấp phu bao nhiêu người được miễn dân đinh tạp dịch, cho lấy tiền thuế thân của phu Ấy làm ngụ lộc. Lại phải nộp tiền lễ, gạo lễ về phu hầu để thuê mướn người đi theo thuyền thuế chở đến Phú Xuân, như năm Kỷ Sửu, tri phủ phủ Thăng Hoa nộp tiền 1 quan 5 tiền, gạo 15 bát, tri huyện huấn đạo mỗi người 1 quan 1 tiền, gạo 15 bát, cai phủ 1 quan 7 tiền, gạo 15 bát, ký phủ 1 quan, gạo 15 bát, ký huyện, ký thuộc cai tổng, cai man, mỗi người 8 tiền, gạo mỗi người 12 bát, cai quan, chính ty trưởng, mỗi người 1 quan 3 tiền, gạo 15 bát, ty quan 1 quan 2 tiền, gạo 10 bát, thủ hợp, cai thuộc, mỗi người 9 tiền, gạo 13 bát, thủ lăng đội trưởng, từ đường thứ đội trưởng, mỗi người 1 quan, gạo 15 bát, thủ lăng thứ đội trưởng 6 tiền, gạo 10 bát, tướng thần 7 tiền, gạo 8 bát, thượng đẳng từ thừa 8 tiền, gạo 12 bát, trung đẳng từ thừa 7 tiển, gạo 10 bát, hạ đăng từ thừa 6 tiền, gạo 8 bát, các chức cộng 278 người, nộp tiển 213 quan 7 tiển, gạo cộng 2.727 bát. Ngoài ra các xã phường cấp ngụ lộc và biệt nạp biệt tái, lại cứ số định hiện có, thu tiền lễ ngụ lộc mỗi người 12 đồng, cứ 100 người thì thu gạo trình diện 5 thưng; tiền trầu thì xã lớn 1 tiền, xã vừa 30 đồng; tiền đầu quan mỗi người 7 đồng 9 phân. Như năm Kỷ Sửu các huyện thuộc phủ Thăng Hoa cộng 1 vạn 4.349 người, thu các tiển cộng 483 quan 3 tiển 36 đồng, gạo cộng 714 thưng 9 cáp, trừ tiền thuê mướn chở đi mỗi 100 quan là 4 tiển, gạo mỗi bao là 4 tiền, còn bao nhiêu thì chở nộp. Không riêng một xứ Quảng Nam, xứ Thuận Hoá cũng thế, rất là tủn mủn."""


def call_api(session: requests.Session, name: str, han: str) -> dict:
    payload = {"han": han, "vi": VI}
    record = {"name": name, "request": payload, "http_status": None, "response": None, "error": None}
    try:
        resp = session.post(URL, json=payload, timeout=120)
        record["http_status"] = resp.status_code
        try:
            record["response"] = resp.json()
        except ValueError:
            record["response"] = {"non_json_body": resp.text}
        if not resp.ok:
            record["error"] = f"HTTP {resp.status_code}"
        elif not isinstance(record["response"], dict) or record["response"].get("is_success") is not True:
            record["error"] = "API returned is_success != true"
    except requests.RequestException as exc:
        record["error"] = str(exc)
    return record


def format_record(record: dict) -> str:
    response = record.get("response")
    lines = ["=" * 76, f"TEST: {record['name']}", f"HTTP: {record['http_status']}"]
    if record["error"]:
        lines.append(f"ERROR: {record['error']}")
    results = (response.get("data") or {}).get("result") if isinstance(response, dict) else None
    if isinstance(results, list):
        lines.append(f"Alignment groups: {len(results)}")
        for i, group in enumerate(results, 1):
            lines.append(f"\n--- Group {i} ---")
            lines.append(json.dumps(group, ensure_ascii=False, indent=2))
    else:
        lines.append("No list at response.data.result; full response:")
        lines.append(json.dumps(response, ensure_ascii=False, indent=2))
    return "\n".join(lines)


def main() -> int:
    token = os.getenv("SINONOM_TOKEN", "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token:
        print('Missing token. PowerShell: $env:SINONOM_TOKEN = "YOUR_TOKEN"', file=sys.stderr)
        return 2

    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/138.0.0.0 Safari/537.36",
    })

    records = []
    try:
        for name, han in (("ocr_raw", HAN_RAW), ("ocr_deepseek", HAN_DEEPSEEK)):
            print(f"Calling {name} (Han {len(han)} chars; Vi {len(VI)} chars)...", flush=True)
            record = call_api(session, name, han)
            records.append(record)
            print(format_record(record), flush=True)
    finally:
        session.close()
        json_path = OUT_DIR / "alignment_2_ocr_results.json"
        text_path = OUT_DIR / "alignment_2_ocr_results.txt"
        json_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        text_path.write_text("\n\n".join(map(format_record, records)), encoding="utf-8")
        print(f"\nSaved: {json_path}\nSaved: {text_path}")

    return 0 if all(not item["error"] for item in records) else 1


if __name__ == "__main__":
    sys.exit(main())
