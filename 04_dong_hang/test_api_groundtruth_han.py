#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test Kim Han Nom sentence-alignment API with GT-based Han segmentation.

- Two separate requests: OCR Raw and OCR DeepSeek.
- Han is split into 10 segments corresponding to GT pairs P186_01..P186_10.
- Vietnamese input stays EXACTLY as originally provided (one uninterrupted string).
- OCR characters are not corrected. Raw boundaries are manually projected to the
  nearest matching content boundaries because its text differs from DeepSeek/GT.
- P186_11..P186_13 are excluded because no corresponding Vietnamese translation
  was supplied in the test input.

PowerShell:
    pip install requests
    $env:SINONOM_TOKEN = "YOUR_TOKEN"
    python test_api_groundtruth_han.py
"""

import json
import os
from pathlib import Path

import requests

URL = "https://kimhannom.fit.hcmus.edu.vn/api/web/clc-sinonom/sentence-alignment"
OUT_DIR = Path(__file__).resolve().parent

# Ground Truth P186_01..P186_10; unchanged OCR DeepSeek characters.
HAN_DEEPSEEK_SEGMENTS = [
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
]

# OCR Raw split at the closest corresponding GT semantic positions.
# IMPORTANT: do not replace Raw OCR with GT/DeepSeek text: that would invalidate
# the comparison between OCR engines.
HAN_RAW_SEGMENTS = [
    "納承願憑示至今有一社至十六七將臣二十餘社長百得應務者正許知押為額目耳",
    "各賦有給夫干人免民丁雜役使取其齋鄉為寓祿又",
    "同納猴夫禮歲礼米雇借附船獻祕富春卯已丑年升葬府亥府成一亥",
    "五阳米十五秩黃陽刑導各年亥七門半十五年記府一貫記舉祀西讀總法夢",
    "各八內朱十二肄後官正司官各一貴三門司官一長二門米十五肄首合後合",
    "各九附米十三餘將臣七陌米十鋒社長七限米八鉢中等记函七陽米十年下等祀丞云四米八詩",
    "各聊共二百七十八人納殊共二百十三長七門米共二千七百二十七年",
    "其餘作富祿及别初荆載又社坊必抑見丁數寓祿礼侯每人主文每百人呈面米五升美味大社一陷中社三十文稱歲每人七文二分",
    "卯已丑升華府各縣屬一萬四千三百四十九人收各歲共四百八十三長三四三十六文米共七百十四升九合",
    "除產借殘每一百四防米每邑一陌不狹廣南於順化亦然亦細碎矣",
]

# Original Vietnamese input: kept unchanged, including punctuation and typos.
VI_TEXT = (
    "tiền lĩnh bằng và tiền ngụ lộc các quan cộng là 5 quan; do đó mà mọi người tranh nhau nộp tiển lĩnh bằng, đến nay có chỗ một xã có đến 16 hay 17 tướng thần, hơn 20 xã trưởng, đều được làm việc, chỉ cho viên tri áp làm đầu mục thôi. "
    "Các chức được cấp phu bao nhiêu người được miễn dân đinh tạp dịch, cho lấy tiền thuế thân của phu Ấy làm ngụ lộc. "
    "Lại phải nộp tiền lễ, gạo lễ về phu hầu để thuê mướn người đi theo thuyền thuế chở đến Phú Xuân, như năm Kỷ Sửu, tri phủ phủ Thăng Hoa nộp tiền 1 quan 5 tiền, gạo 15 bát, tri huyện huấn đạo mỗi người 1 quan 1 tiền, gạo 15 bát, cai phủ 1 quan 7 tiền, gạo 15 bát, ký phủ 1 quan, gạo 15 bát, ký huyện, ký thuộc cai tổng, cai man, mỗi người 8 tiền, gạo mỗi người 12 bát, cai quan, chính ty trưởng, mỗi người 1 quan 3 tiền, gạo 15 bát, ty quan 1 quan 2 tiền, gạo 10 bát, thủ hợp, cai thuộc, mỗi người 9 tiền, gạo 13 bát, thủ lăng đội trưởng, từ đường thứ đội trưởng, mỗi người 1 quan, gạo 15 bát, thủ lăng thứ đội trưởng 6 tiền, gạo 10 bát, tướng thần 7 tiền, gạo 8 bát, thượng đẳng từ thừa 8 tiền, gạo 12 bát, trung đẳng từ thừa 7 tiển, gạo 10 bát, hạ đăng từ thừa 6 tiền, gạo 8 bát, các chức cộng 278 người, nộp tiển 213 quan 7 tiển, gạo cộng 2.727 bát. "
    "Ngoài ra các xã phường cấp ngụ lộc và biệt nạp biệt tái, lại cứ số định hiện có, thu tiền lễ ngụ lộc mỗi người 12 đồng, cứ 100 người thì thu gạo trình diện 5 thưng; tiền trầu thì xã lớn 1 tiền, xã vừa 30 đồng; tiền đầu quan mỗi người 7 đồng 9 phân. "
    "Như năm Kỷ Sửu các huyện thuộc phủ Thăng Hoa cộng 1 vạn 4.349 người, thu các tiển cộng 483 quan 3 tiển 36 đồng, gạo cộng 714 thưng 9 cáp, trừ tiền thuê mướn chở đi mỗi 100 quan là 4 tiển, gạo mỗi bao là 4 tiền, còn bao nhiêu thì chở nộp. "
    "Không riêng một xứ Quảng Nam, xứ Thuận Hoá cũng thế, rất là tủn mủn."
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)


def call_api(name: str, segments: list[str], token: str) -> dict:
    payload = {"han": "\n".join(segments), "vi": VI_TEXT}
    print(f"\n{'=' * 70}\nTEST: {name} | Han: {len(segments)} lines | Vi: unchanged")
    try:
        response = requests.post(
            URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
            json=payload,
            timeout=120,
        )
        try:
            body = response.json()
        except ValueError:
            body = {"non_json_response": response.text[:3000]}
        print("HTTP:", response.status_code)
        result = (body.get("data") or {}).get("result") if isinstance(body, dict) else None
        if isinstance(result, list):
            print("Alignment groups:", len(result))
            for i, group in enumerate(result, 1):
                print(f"\n--- Group {i} ---")
                print(json.dumps(group, ensure_ascii=False, indent=2))
        else:
            print("Response:", json.dumps(body, ensure_ascii=False, indent=2))
        return {"name": name, "payload": payload, "http_status": response.status_code, "response": body}
    except requests.RequestException as exc:
        print("Request failed:", exc)
        return {"name": name, "payload": payload, "error": str(exc)}


def main() -> None:
    token = os.getenv("SINONOM_TOKEN", "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token:
        raise SystemExit('Missing token. PowerShell: $env:SINONOM_TOKEN = "YOUR_TOKEN"')

    assert len(HAN_RAW_SEGMENTS) == len(HAN_DEEPSEEK_SEGMENTS) == 10
    inputs = {
        "ocr_raw": {"han_segments": HAN_RAW_SEGMENTS, "han": "\n".join(HAN_RAW_SEGMENTS), "vi": VI_TEXT},
        "ocr_deepseek": {"han_segments": HAN_DEEPSEEK_SEGMENTS, "han": "\n".join(HAN_DEEPSEEK_SEGMENTS), "vi": VI_TEXT},
    }
    (OUT_DIR / "gt_han_test_inputs.json").write_text(json.dumps(inputs, ensure_ascii=False, indent=2), encoding="utf-8")
    results = [
        call_api("ocr_raw", HAN_RAW_SEGMENTS, token),
        call_api("ocr_deepseek", HAN_DEEPSEEK_SEGMENTS, token),
    ]
    result_file = OUT_DIR / "gt_han_test_results.json"
    result_file.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved inputs: {OUT_DIR / 'gt_han_test_inputs.json'}")
    print(f"Saved results: {result_file}")


if __name__ == "__main__":
    main()
