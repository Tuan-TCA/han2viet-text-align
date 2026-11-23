#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test Kim Han Nom: 13 Han GT lines -> Vietnamese clusters.

PowerShell:
    pip install requests
    $env:SINONOM_TOKEN = "YOUR_TOKEN"
    python test_api_13_han_vi_clusters.py

Han: EXACTLY 13 GT segments, separated by newline.
Vi: one continuous paragraph made by concatenating the 13 supplied GT Vietnamese spans.
The API may segment Vietnamese internally; this script does not pre-segment it.
"""

import json
import os
import sys
from pathlib import Path

import requests

URL = "https://kimhannom.fit.hcmus.edu.vn/api/web/clc-sinonom/sentence-alignment"
OUT_DIR = Path(__file__).resolve().parent

HAN_SEGMENTS = [
    "爭拘該項陋示至今有一社至十六七將陸二十餘社長而待應務者止以許知押為額目耳",
    "各馭有給夫千人免民丁雜役使之具肩阮為富祿又",
    "同拘候夫礼該礼米產借貼船歲該富春知巴丑年并奉府美濟該兵",
    "五兩米十五鉢美零例導各飛兵七陌米十五鉢記兵一貫社置把度該受",
    "各八陌米十二鉢該官正司官各一貫三陌司官一兵二陌米十五鉢首合該合",
    "各九陌米十三鉢將度七陌米十鉢社長七陌米八鉢中等記度七陌米十鉢下等記度各陌米八鉢",
    "各馭共二百七十八人納該共二百十三兵七陌米共二千七百二十七鉢",
    "其餘從富祿該例別納別兵社坊及親見丁數富祿礼該兩人三文每百人呈面米五升美該大社一陌中社三十文稍該每人七文二分",
    "巴旦弁奉府各縣屬一萬四千三百四十九人收各該共四百八十三兵三陌三十二文米共七百四十九合",
    "除產借該每一百四陌米每巴一陌不狹廣南該順化亦熟亦細碎矣",
    "順廣諸營許司吏与行各縣本堂賦色各效累該收丁該田粟其收各吏各馭不為捱矢如有受歷該并美該替恨例",
    "各營該合首合附去累簡繁省或該十三貫糴恨二窠次者該六貫恨八兩前者該三長恨",
    "壹月五該司吏二貫鎮該案該八貫覃提馭与該廵除該營該十四貫",
]

# Vietnamese passages copied from supplied Ground Truth, in original order.
# This list is ONLY for constructing a single combined Vietnamese paragraph.
# These individual passages are NOT sent separately to the API.
VI_SPANS = [
    "tiền lĩnh bằng và tiền ngụ lộc các quan cộng là 5 quan; do đó mà mọi người tranh nhau nộp tiển lĩnh bằng, đến nay có chỗ một xã có đến 16 hay 17 tướng thần, hơn 20 xã trưởng, đều được làm việc, chỉ cho viên tri áp làm đầu mục thôi.",
    "Các chức được cấp phu bao nhiêu người được miễn dân đinh tạp dịch, cho lấy tiền thuế thân của phu Ấy làm ngụ lộc.",
    "Lại phải nộp tiền lễ, gạo lễ về phu hầu để thuê mướn người đi theo thuyền thuế chở đến Phú Xuân, như năm Kỷ Sửu,",
    "tri phủ phủ Thăng Hoa nộp tiền 1 quan 5 tiền, gạo 15 bát, tri huyện huấn đạo mỗi người 1 quan 1 tiền, gạo 15 bát,",
    "cai phủ 1 quan 7 tiền, gạo 15 bát, ký phủ 1 quan, gạo 15 bát, ký huyện, ký thuộc cai tổng, cai man, mỗi người 8 tiền, gạo mỗi người 12 bát,",
    "cai quan, chính ty trưởng, mỗi người 1 quan 3 tiền, gạo 15 bát, ty quan 1 quan 2 tiền, gạo 10 bát, thủ hợp, cai thuộc, mỗi người 9 tiền, gạo 13 bát, thủ lăng đội trưởng, từ đường thứ đội trưởng, mỗi người 1 quan, gạo 15 bát, thủ lăng thứ đội trưởng 6 tiền, gạo 10 bát, tướng thần 7 tiền, gạo 8 bát,",
    "thượng đẳng từ thừa 8 tiền, gạo 12 bát, trung đẳng từ thừa 7 tiển, gạo 10 bát, hạ đăng từ thừa 6 tiền, gạo 8 bát, các chức cộng 278 người, nộp tiển 213 quan 7 tiển, gạo cộng 2.727 bát.",
    "Ngoài ra các xã phường cấp ngụ lộc và biệt nạp biệt tái, lại cứ số định hiện có, thu tiền lễ ngụ lộc mỗi người 12 đồng, cứ 100 người thì thu gạo trình diện 5 thưng; tiền trầu thì xã lớn 1 tiền, xã vừa 30 đồng; tiền đầu quan mỗi người 7 đồng 9 phân.",
    "Như năm Kỷ Sửu các huyện thuộc phủ Thăng Hoa cộng 1 vạn 4.349 người, thu các tiển cộng 483 quan 3 tiển 36 đồng, gạo cộng 714 thưng 9 cáp,",
    "trừ tiền thuê mướn chở đi mỗi 100 quan là 4 tiển, gạo mỗi bao là 4 tiền, còn bao nhiêu thì chở nộp. Không riêng một xứ Quảng Nam, xứ Thuận Hoá cũng thế, rất là tủn mủn.",
    "Các dinh ở Thuận Quảng đặt ty lại và chức sắc bản đường các phủ huyện, số người rất nhiều, khiến họ thu tiền thóc đình điền, lấy ở các lại các chức cũng không phải nhẹ. Như có lệ nộp tiền lĩnh bằng, tiền trầu và tiền thế bạc thì ở các định,",
    "cai hợp, thủ hợp tuỳ chỗ nhiều việc ít việc, chỗ nhiều việc thì hoặc tiền là 13 quan, bạc lá để 2 hốt, chỗ vừa thì tiền 6 quan, bạc 8 lạng,",
    "chỗ ít thì tiển 2 quan bạc 1 lạng 10 đồng cân, ty lại 2 quan, cai án trấn 8 quan, đề lĩnh kho và cai quan trấn tuần nguồn 14 quan,",
]


def main() -> int:
    token = os.getenv("SINONOM_TOKEN", "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token:
        print('Missing token. PowerShell: $env:SINONOM_TOKEN = "YOUR_TOKEN"')
        return 2

    assert len(HAN_SEGMENTS) == len(VI_SPANS) == 13
    han = "\n".join(HAN_SEGMENTS)
    vi = " ".join(VI_SPANS)
    payload = {"han": han, "vi": vi}

    input_path = OUT_DIR / "gt13_api_input.json"
    result_path = OUT_DIR / "gt13_api_response.json"
    clusters_path = OUT_DIR / "gt13_api_clusters.txt"
    input_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/138.0.0.0 Safari/537.36",
    }
    print(f"Han lines: {len(HAN_SEGMENTS)} | Vi paragraphs sent: 1 | Vi chars: {len(vi)}")
    print(f"POST {URL}")
    try:
        response = requests.post(URL, headers=headers, json=payload, timeout=120)
        print("HTTP:", response.status_code)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        print("API/JSON error:", exc)
        return 1

    result_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    if data.get("is_success") is not True or data.get("code") != "000000":
        print("API application error:", json.dumps(data, ensure_ascii=False, indent=2))
        return 1

    groups = (data.get("data") or {}).get("result")
    if not isinstance(groups, list):
        print("Missing/invalid data.result; see", result_path)
        return 1

    lines = [f"ALIGNMENT GROUPS: {len(groups)}", ""]
    for i, g in enumerate(groups, 1):
        a, b = g.get("han_start"), g.get("han_end")
        x, y = g.get("vi_start"), g.get("vi_end")
        pair_range = f"P186_{a+1:02d}..P186_{b+1:02d}" if isinstance(a, int) and isinstance(b, int) else "?"
        lines.extend([
            f"=== GROUP {i} | HAN [{a}:{b}] ({pair_range}) | VI [{x}:{y}] | score={g.get('score')} ===",
            "HAN: " + str(g.get("han_text", "")),
            "VI : " + str(g.get("vietnamese_text", "")),
            "",
        ])
    report = "\n".join(lines)
    print("\n" + report)
    clusters_path.write_text(report, encoding="utf-8")
    print("Saved:", input_path.name, result_path.name, clusters_path.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
