"""Multiple boundary proposals and protected Han expressions."""
import re
from collections import defaultdict
import cn2an
from preprocess import content

HAN_NUM = re.compile(r'[零〇一二兩两三四五六七八九十百千萬万億亿廿卅卌壹貳參肆伍陸柒捌玖拾佰仟0-9]+')
VI_NUM = re.compile(r'(?<![\w.,])[0-9]+(?:[.,]\s*[0-9]+)*(?!\w)')
# Conservative domain lexicon. Matches serve as weak anchors, not OCR corrections.
ENTITIES = {'順化':'thuận hoá','廣南':'quảng nam','順廣':'thuận quảng','富春':'phú xuân','升華':'thăng hoa',
            '洪德':'hồng đức','黎朝':'lê triều','乂安':'nghệ an','高平':'cao bằng','河內':'hà nội',
            '知府':'tri phủ','知縣':'tri huyện','社長':'xã trưởng','進士':'tiến sĩ','巡源':'tuần nguồn',
            '端陽':'đoan dương','嘉隆':'gia long','阮氏':'nguyễn thị','書記':'thư ký','將臣':'tướng thần'}
SOURCE_WEIGHTS = {'separate': 0.55, 's4': 0.36, 'strong': 0.4, 'weak': 0.18,
                  'grammar': 0.14, 'grid': 0.04, 'page': 0.16, 'edge': 0.0, 'entity_end': 0.08}


def numbers(text, han):
    out = set()
    for m in (HAN_NUM if han else VI_NUM).finditer(text):
        s = m[0]
        try:
            if han:
                s = s.translate(str.maketrans('兩两萬億〇','二二万亿零')).replace('廿','二十').replace('卅','三十').replace('卌','四十')
                n = int(s) if s.isascii() and s.isdecimal() else int(cn2an.cn2an(s, 'smart'))
            else:
                if re.fullmatch(r'\d{1,3}(?:\.\s*\d{3})+',s):
                    # Soft feature only; outgoing T1 does not remove unconfirmed single dots.
                    n = int(re.sub(r'\D','',s))
                else:
                    n = int(s)
            if n > 0: out.add(n)
        except (TypeError, ValueError, OverflowError, KeyError):
            continue
    return out


def entities(text, han):
    from unicodedata import normalize
    fold = lambda s: ''.join(c for c in normalize('NFD',s.lower()) if not '\u0300'<=c<='\u036f').replace('đ','d')
    vi = fold(text) if not han else ''
    return {h for h,v in ENTITIES.items() if (h in text if han else bool(re.search(r'(?<!\w)'+re.escape(fold(v))+r'(?!\w)',vi)))}


def s4(raw, projected):
    ends = {s['global_raw_span'][1] for s in projected}
    weak, strong = set(), set()
    for s in projected:
        a,b = s['global_raw_span']
        idx = [i for i in range(a,b) if content(raw[i])]
        count = 0
        for ch in s['text_api']:
            count += bool(content(ch))
            if ch in '，、；;：:' and 0<count<len(idx):
                p = idx[count-1]+1
                weak.add(p)
                if ch in '；;：:': strong.add(p)
    ends.add(len(raw))
    for p in sorted(strong)+sorted(weak-strong):
        if min(abs(p-q) for q in ends|{0})>=12: ends.add(p)
    return sorted(ends|{0})


def generate(raw, projected, page_ends, grid):
    marks = defaultdict(set)
    def add(p, source):
        if 0 <= p <= len(raw): marks[p].add(source)
    for p in (0,len(raw)): add(p,'edge')
    for p in s4(raw,projected): add(p,'s4')
    for s in projected: add(s['global_raw_span'][1],'separate')
    for p in page_ends: add(p,'page')
    for m in re.finditer(r'[。！？!?；;]+|[，、,:：]+',raw):
        add(m.end(),'strong' if m[0][0] in '。！？!?；;' else 'weak')
    for m in re.finditer(r'於是|又曰|乃曰|是以|故曰|其後|凡若|至於|蓋|然則|若夫',raw): add(m.start(),'grammar')
    protected = [(m.start(),m.end(),'number') for m in HAN_NUM.finditer(raw) if len(m[0])>1]
    for e in ENTITIES:
        for m in re.finditer(e,raw):
            protected.append((m.start(),m.end(),'entity')); add(m.end(),'entity_end')
    for p in range(grid,len(raw),grid): add(p,'grid')
    return {p:{'sources':sorted(ss),'blocked':[label for a,b,label in protected if a<p<b],
               'score':sum(SOURCE_WEIGHTS[s] for s in ss)} for p,ss in sorted(marks.items())}
