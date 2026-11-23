import os
import sys

import requests

response = requests.post(
    "https://kimhannom.fit.hcmus.edu.vn/api/web/clc-sinonom/separate-sentences",
    headers={
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/138.0.0.0 Safari/537.36"
        ),
        "Authorization": f"Bearer {os.environ['SINONOM_TOKEN'].strip()}",
        "Accept": "application/json",
    },
    json={
        "text": "孟子曰魚我所欲也熊掌亦我所欲也二者不可得兼舍魚而取熊掌者也生亦我所欲也義亦我所欲也二者不可得兼舍生而取義者也生亦我所欲所欲有甚於生者故不為苟得也死亦我所惡所惡有甚於死者故患有所不辟也如使人之所欲莫甚於生則凡可以得生者何不用也使人之所惡莫甚於死者則凡可以辟患者何不為也由是則生而有不用也由是則可以辟患而有不為也是故所欲有甚於生者所惡有甚於死者非獨賢者有是心也人皆有之賢者能勿喪耳一簞食一豆羹得之則生弗得則死嘑爾而與之行道之人弗受蹴爾而與之乞人不屑也萬鍾則不辯禮義而受之萬鍾於我何加焉為宮室之美為妻妾之奉為所識窮乏者得我與鄉為身死而不受今為宮室之美為之鄉為身死而不受今為妻妾之奉為之鄉為身死而不受今為所識窮乏者得我而為之是亦不可以已乎此之謂失其本心",
        "ocr_id": 1,
    },
    timeout=120,
)

sys.stdout.buffer.write(response.content)