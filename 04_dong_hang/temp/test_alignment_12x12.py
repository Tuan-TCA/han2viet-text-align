#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Clean Classical Chinese–Vietnamese 12x12 alignment test."""
import os
import json
from pathlib import Path
import requests

URL = 'https://kimhannom.fit.hcmus.edu.vn/api/web/clc-sinonom/sentence-alignment'
# Classical Chinese examples from Analects (論語), with Vietnamese translations.
PAIRS = [
    ('學而時習之，不亦說乎？', 'Học rồi thường xuyên ôn tập, chẳng vui sao?'),
    ('有朋自遠方來，不亦樂乎？', 'Có bạn từ phương xa đến, chẳng vui sao?'),
    ('人不知而不慍，不亦君子乎？', 'Người khác không hiểu mình mà không oán giận, chẳng phải là người quân tử sao?'),
    ('巧言令色，鮮矣仁。', 'Nói lời khéo léo, làm vẻ mặt lấy lòng, hiếm có lòng nhân.'),
    ('溫故而知新，可以為師矣。', 'Ôn lại điều cũ mà hiểu được điều mới, có thể làm thầy vậy.'),
    ('學而不思則罔，思而不學則殆。', 'Học mà không suy nghĩ thì mờ mịt, suy nghĩ mà không học thì nguy hại.'),
    ('知之為知之，不知為不知，是知也。', 'Biết thì nhận là biết, không biết thì nhận là không biết, đó là sự hiểu biết.'),
    ('見賢思齊焉，見不賢而內自省也。', 'Thấy người hiền thì nghĩ đến việc noi theo, thấy người không hiền thì tự xét lại mình.'),
    ('君子喻於義，小人喻於利。', 'Người quân tử hiểu rõ điều nghĩa, kẻ tiểu nhân hiểu rõ điều lợi.'),
    ('三人行，必有我師焉。', 'Ba người cùng đi, ắt có người là thầy của ta.'),
    ('己所不欲，勿施於人。', 'Điều mình không muốn thì đừng làm cho người khác.'),
    ('君子和而不同，小人同而不和。', 'Người quân tử hòa hợp mà không a dua, kẻ tiểu nhân a dua mà không hòa hợp.'),
]

def main():
    token = os.environ.get('SINONOM_TOKEN', '').strip()
    if not token:
        raise SystemExit('Set SINONOM_TOKEN before running.')
    han, vi = map(list, zip(*PAIRS))
    payload = {'han': '\n'.join(han), 'vi': '\n'.join(vi)}
    print('INPUT: 12 Han x 12 Vietnamese')
    for i, (h, v) in enumerate(PAIRS, 1):
        print(f'{i:02d}. {h}\n    {v}')
    response = requests.post(URL, json=payload, headers={
        'Authorization': 'Bearer ' + token,
        'Accept': 'application/json',
    }, timeout=(10, 120), allow_redirects=False)
    out = Path(__file__).with_name('alignment_12x12_result.json')
    try:
        body = response.json()
    except ValueError:
        body = {'raw_response': response.text}
    record = {'http': response.status_code, 'payload': payload, 'response': body}
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    response.raise_for_status()
    if body.get('is_success') is not True or body.get('code') != '000000':
        raise SystemExit(f'API error: {body}')
    rows = body['data']['result']
    exact = set()
    print('\nOUTPUT:')
    for i, row in enumerate(rows, 1):
        h, v = row.get('han_text', ''), row.get('vietnamese_text', '')
        norm = lambda s: ''.join(s.split())
        matches = [j for j, (a,b) in enumerate(PAIRS,1) if norm(h)==norm(a) and norm(v)==norm(b)]
        exact.update(matches)
        print(f"\nGROUP {i}: Han [{row.get('han_start')}:{row.get('han_end')}] | Viet [{row.get('vi_start')}:{row.get('vi_end')}] | score={row.get('score')}")
        print('HAN:', h, '\nVI :', v)
        print('Exact 1-1:', matches or 'No (inspect merged/partial group)')
    record['exact_1_to_1_ids'] = sorted(exact)
    record['exact_1_to_1_rate'] = len(exact)/len(PAIRS)
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\nExact 1-1: {len(exact)}/12 ({len(exact)/12:.2%})')
    print('This is a text-match metric, not a semantic label for merged groups.')
    print('Saved:', out)

if __name__ == '__main__':
    main()
