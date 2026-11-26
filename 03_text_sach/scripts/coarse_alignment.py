"""Page-anchored windows; experiment scopes are configuration, not algorithm rules."""
from statistics import median
import re
from preprocess import content, suspicious


def units(text):
    return len(re.findall(r'\w+', text))


def window(pages, viet, maps, cap, nums, margin=0, viet_pages=None):
    nums = sorted(nums)
    h = [r for r in pages if r['cap'] == cap and r['han_pdf_page'] in nums]
    if [r['han_pdf_page'] for r in h] != list(range(nums[0], nums[-1]+1)):
        raise ValueError('Window must cover contiguous existing Han pages')
    lo, hi = nums[0], nums[-1]
    def gap(r):
        a, b = r['han_search_window'] or (float('inf'), float('-inf'))
        return max(a-hi, lo-b, 0)
    candidates = [r for r in maps if r['cap'] == cap and gap(r) <= margin]
    exact = [r for r in candidates if any(lo <= a['han_pdf_page'] <= hi for a in r['verified_overlap'])]
    # Prefer anchors, admitting context near verified Vietnamese pages; otherwise
    # rank broad windows by distance from their interpolated Vietnamese position.
    anchors = sorted((a['han_pdf_page'], r['viet_pdf_page']) for r in maps if r['cap']==cap for a in r['verified_overlap'])
    center = (lo+hi)/2
    left = max((p for p in anchors if p[0]<=center), default=None)
    right = min((p for p in anchors if p[0]>=center), default=None)
    target = ((left[1]+(right[1]-left[1])*(center-left[0])/(right[0]-left[0]))
              if left and right and left[0]!=right[0] else (left or right or (0,0))[1])
    if viet_pages:
        selected = set(range(viet_pages[0], viet_pages[1]+1))
    elif exact:
        verified = [r['viet_pdf_page'] for r in exact]
        selected = {r['viet_pdf_page'] for r in candidates
                    if min(verified)-margin <= r['viet_pdf_page'] <= max(verified)+margin}
    else:
        supported = [r for r in candidates if gap(r)==0]
        selected = {r['viet_pdf_page'] for r in sorted(supported, key=lambda r:
                    (abs(r['viet_pdf_page']-target), r['viet_pdf_page']))[:2*len(nums)+2*margin]}
    v = [r for r in viet if r['cap']==cap and any(r['viet_page_start']<=n<=r['viet_page_end']
                                                for n in selected)]
    return {'id': f'{cap}-{lo:03d}-{hi:03d}', 'cap': cap, 'pages': h, 'viet': v,
            'raw': ''.join(r['text_original'] for r in h), 'start': h[0]['global_raw_span'][0],
            'mapping': [r for r in candidates if r['viet_pdf_page'] in selected],
            'status': 'anchored' if exact else 'uncertain' if v else 'unmatched'}


def fit_length(pages, viet, maps, excluded):
    # Fit only unambiguous reciprocal page anchors, excluding evaluation pages.
    pairs = {}
    for m in maps:
        for ref in m['verified_overlap']:
            k = (m['cap'], ref['han_pdf_page'])
            if len(m['verified_overlap'])==1 and not ref.get('qualifier') and k not in excluded:
                pairs.setdefault(k, []).append(m['viet_pdf_page'])
    ratios = []
    for h in pages:
        key = h['cap'], h['han_pdf_page']
        nums = pairs.get(key)
        if not nums:
            continue
        count = sum(units(v['text_nfc']) for v in viet if v['cap']==key[0]
                    and v['viet_page_start'] in nums and v['viet_page_end'] in nums)
        if count:
            ratios.append({'cap': key[0], 'page': key[1], 'ratio': len(content(h['text_original']))/count})
    if not ratios:
        raise ValueError('No eligible training anchors for the length model')
    med = median(r['ratio'] for r in ratios)
    return {'ratio': med, 'samples': ratios}


def select_heldout(pages, maps, count, used):
    """Select contiguous pairs where possible plus extremes, using source metadata only."""
    output = []
    for cap in sorted({p['cap'] for p in pages}):
        remaining = count
        supported = {n for m in maps if m['cap']==cap and m['han_search_window']
                     for n in range(m['han_search_window'][0],m['han_search_window'][1]+1)}
        pool = {p['han_pdf_page']: p for p in pages if p['cap']==cap
                and (cap,p['han_pdf_page']) not in used and p['han_pdf_page'] in supported}
        def features(n):
            s = pool[n]['text_original']
            return len(s), len(re.findall(r'[一二三四五六七八九十百千萬兩0-9]',s))/len(s), len(suspicious(s)), len(re.findall(r'[府縣官臣侯司郡]',s))
        # Two distinct adjacent windows, prioritizing numeral density and titles.
        for feature in (1, 3):
            if remaining < 2:
                break
            adjacent = [n for n in pool if n+1 in pool]
            if not adjacent:
                break
            n = max(adjacent, key=lambda k: (sum(features(i)[feature] for i in (k,k+1)), -k))
            output.append((cap,[n,n+1]))
            del pool[n],pool[n+1]
            remaining -= 2
        for _ in range(remaining):
            if pool:
                n = min(pool, key=lambda k: (features(k)[0],-features(k)[2],k))
                output.append((cap,[n])); del pool[n]
    return output
