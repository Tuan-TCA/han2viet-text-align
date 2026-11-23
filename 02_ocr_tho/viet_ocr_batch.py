#!/usr/bin/env python3
"""Extract the embedded Vietnamese OCR, retain page spans, and export Excel."""
import argparse
import csv
import json
import re
import subprocess
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import median

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


ROOT = Path(__file__).resolve().parents[1]
CONFIG = Path(__file__).with_name('viet_han_anchors.json')
END = re.compile(r'[.?!…]+["”’»\)\]]*(?=\s|$)')
OPENERS = '\"“‘«(['
ABBR = {'tr', 'vv', 'tp', 'ts', 'gs', 'pgs', 'st', 'nxb', 'sđd', 'tk'}
MATCH_TYPES = {'van_xuoi', 'dich_tho'}
KNOWN_END_MARKER = re.compile(r'["”’»\)\]]*$')


@dataclass
class Line:
    page: int
    text: str
    x: float
    y: float
    size: float
    kind: str = 'van_xuoi'
    order: int = 0


def key(text):
    text = unicodedata.normalize('NFD', text.casefold()).replace('đ', 'd')
    return ' '.join(''.join(c for c in text if not unicodedata.combining(c)).split())


def tidy(text):
    return ' '.join(unicodedata.normalize('NFC', text).split())


def poppler(pdf, start, end, mode):
    command = ['pdftotext', mode, '-enc', 'UTF-8', '-f', str(start), '-l', str(end), str(pdf), '-']
    return subprocess.check_output(command).decode('utf-8')


def load_pages(pdf, start, end):
    raw = poppler(pdf, start, end, '-layout').split('\f')
    if raw and not raw[-1].strip():
        raw.pop()
    nodes = ET.fromstring(poppler(pdf, start, end, '-bbox-layout')).findall('.//{*}page')
    if len(raw) != len(nodes) or len(nodes) != end - start + 1:
        raise ValueError(f'Unexpected page count for {pdf}: raw={len(raw)}, layout={len(nodes)}')
    pages = {}
    for page, node, txt in zip(range(start, end + 1), nodes, raw):
        lines = []
        for line in node.findall('.//{*}line'):
            text = tidy(' '.join(word.text or '' for word in line))
            if text:
                x, y, bottom = (float(line.attrib[k]) for k in ('xMin', 'yMin', 'yMax'))
                lines.append(Line(page, text, x, y, bottom - y))
        lines.sort(key=lambda ln: (round(ln.y, 1), ln.x))
        for order, line in enumerate(lines):
            line.order = order
        pages[page] = (txt, lines, float(node.attrib['height']))
    return pages


def classify(pages, cfg):
    prev_mode = 'van_xuoi'
    for page, (_, lines, height) in pages.items():
        if not lines:
            continue
        expected = cfg['printed_start'] + page - cfg['viet_start']
        sizes = [ln.size for ln in lines if ln.y < height * .79 and len(ln.text) > 18]
        typical = median(sizes or [ln.size for ln in lines])
        mode, notes, previous = 'van_xuoi', False, None
        if prev_mode == 'dich_tho' and len(lines[0].text) <= 50 and lines[0].x > 100:
            mode = prev_mode
        for i, ln in enumerate(lines):
            label = key(ln.text)
            if ln.y > .87 * height and (ln.text == str(expected) or re.fullmatch(r'\d[\dãðõ]+|[:;.]', label)):
                ln.kind = 'so_trang'
                continue
            gap = ln.y - previous.y if previous else 0
            next_small = any(other.size < typical * .86 for other in lines[i+1:i+3])
            note_marker = re.match(r'^[^\s]{0,3}[®©†?!][^\s]{0,3}\s', ln.text)
            if ln.y > .65 * height and next_small and (ln.size < typical * .86 or
                    (gap > typical * 1.65 and (ln.size < typical * .96 or note_marker))):
                notes = True
            if notes:
                ln.kind = 'chu_thich'
            elif re.fullmatch(r'[^\w]*phien\s+am[^\w]*', label):
                ln.kind, mode = 'tieu_de', 'phien_am'
            elif re.fullmatch(r'[^(a-z]*\(?c?dich[^\w]*', label):
                ln.kind, mode = 'tieu_de', 'dich_tho'
            elif (label.startswith(('quyen v', 'nhan tai va van tho')) or label in cfg.get('heading_keys', [])
                  or re.fullmatch(r'[\W_]+|\d{1,2}', label)):
                ln.kind = 'tieu_de'
            else:
                if mode != 'van_xuoi' and len(ln.text) >= 67 and (gap > typical * 1.6 or
                        (i+1 < len(lines) and len(lines[i+1].text) >= 62)):
                    mode = 'van_xuoi'
                ln.kind = mode
            previous = ln
        prev_mode = mode


def split_spans(text):
    """Split punctuation-delimited sentences; keep a trailing fragment."""
    start = 0
    for match in END.finditer(text):
        punctuation = KNOWN_END_MARKER.sub('', match[0])
        rest = text[match.end():].lstrip().lstrip(OPENERS)
        token = re.search(r'\S+$', text[start:match.start()])
        if punctuation == '.' and token:
            word = token[0].strip(OPENERS)
            if word.casefold() in ABBR or (len(word) == 1 and word.isupper()):
                continue
            if word.isdigit() and not text[start:token.start()].strip():
                continue
        if rest and not (rest[0].isupper() or rest[0].isdigit()):
            continue
        yield start, match.end()
        start = match.end()
    if text[start:].strip():
        yield start, len(text)


def records_for(pages, cfg, cap):
    start_page, end_page = cfg['viet_start'], cfg['viet_end']
    start_cue, end_cue = key(cfg['start_cue']), key(cfg['end_cue'])
    initial = cfg.get('restore_initial', 'N' if cap == 'Cap_02' else '')
    started, ended = False, False
    buffer, spans, last = '', [], None
    records = []

    def flush():
        nonlocal buffer, spans, last
        for left, right in split_spans(buffer):
            text = buffer[left:right].strip()
            first = left + len(buffer[left:right]) - len(buffer[left:right].lstrip())
            touched = [ln for a, b, ln in spans if first < b and right > a]
            if not touched:
                continue
            p, q, kind = touched[0].page, touched[-1].page, touched[0].kind
            flags = []
            if not re.search(END.pattern + r'$', text):
                flags.append('thiếu dấu kết câu')
            if re.search(r'[�®©ðþƒ†#]|\(cid:', text, re.I):
                flags.append('ký tự OCR đáng ngờ')
            if p != q:
                flags.append('vắt trang')
            if cap == 'Cap_01' and p == start_page and key(text).startswith('nop tien linh bang'):
                flags.append('đầu đoạn cắt giữa câu')
            if initial and p == start_page and key(text).startswith(start_cue.split(',')[0]):
                text = initial + text
                flags.append(f'khôi phục chữ {initial} đầu trang từ bản in')
            records.append((p, touched[0].order, q, kind, text, '; '.join(flags)))
        buffer, spans, last = '', [], None

    for p, (_, lines, _) in pages.items():
        if p in cfg.get('paragraph_start_pages', []):
            flush()
        for ln in lines:
            if ln.kind == 'so_trang':
                continue
            # The prefix fits on one line even if the full cue wraps.
            if not started and ln.kind == 'van_xuoi' and p == start_page:
                prefix = start_cue.split(',')[0]
                at = key(ln.text).find(prefix)
                if at >= 0:
                    # Search the normalized cue via word offsets, preserving the OCR string.
                    if cap == 'Cap_01':
                        words = list(re.finditer(r'\S+', ln.text))
                        ln.text = ln.text[words[len(key(ln.text)[:at].split())].start():]
                    started = True
            if not started and ln.kind != 'tieu_de':
                continue
            if ended and ln.kind in MATCH_TYPES:
                ln.kind = 'chu_thich'
            aux = ln.kind in {'chu_thich', 'tieu_de'}
            # Notes/headings have their own rows but must not break a prose
            # sentence spanning two pages.
            if aux:
                records.append((p, ln.order, p, ln.kind, ln.text, ''))
                continue
            if last and ln.kind != last.kind:
                flush()
            if last and p == last.page and ln.y - last.y > max(24, last.size * 2.2):
                flush()
            if buffer:
                buffer += ' '
            off = len(buffer)
            buffer += ln.text
            spans.append((off, len(buffer), ln))
            last = ln
            if p == end_page and end_cue in key(buffer):
                ended = True
                flush()
    flush()
    if not (started and ended):
        raise ValueError(f'{cap}: source boundary not found (start={started}, end={ended})')
    # Aux rows can be collected ahead of cross-page prose; sequence IDs in
    # actual reading order using the first source line of each record.
    numbered, counts = [], Counter()
    for p, _, q, kind, text, flags in sorted(records, key=lambda row: row[:2]):
        counts[p] += 1
        numbered.append((f'{cap}-VI-{p:04}-{counts[p]:03}', p, q, kind, text, flags))
    return numbered


def number_keys(text, han=False):
    if not han:
        return set(re.findall(r'(?<!\d)\d+(?:\.\d{3})+(?!\d)', text.replace(',', '.')))
    digits = dict(zip('零一二三四五六七八九', range(10))) | {'〇': 0, '兩': 2}
    small = {'十': 10, '百': 100, '千': 1000}
    hits = set()
    for seq in re.findall(r'[零〇一二兩三四五六七八九十百千万萬千]+', text):
        total = group = digit = 0
        for c in seq:
            if c in digits:
                digit = digits[c]
            elif c in small:
                group += (digit or 1) * small[c]
                digit = 0
            else:
                total += (group + digit or 1) * 10000
                group = digit = 0
        value = total + group + digit
        if value >= 1000:
            hits.add(f'{value:,}'.replace(',', '.'))
    return hits


def page_mapping(cap, pages, cfg):
    han_start, han_end = cfg.get('han_start', 1), cfg['han_end']
    regions = {page: cfg[f'han_{side}_region'] for page, side in [(han_start, 'start'), (han_end, 'end')]
               if f'han_{side}_region' in cfg}
    anchors = defaultdict(list)
    candidates = defaultdict(list)
    for viet, han, cue, note in cfg['anchors']:
        if not han_start <= han <= han_end:
            raise ValueError(f'{cap}: anchor Hán {han} outside {han_start}–{han_end}')
        if key(cue) not in key(pages[viet][0]):
            raise ValueError(f'{cap}: missing anchor on Viet {viet}: {cue}')
        anchors[viet].append((han, cue, note))
    # Only use a cleaned Hán page automatically if it shares at least two
    # distinctive figures with exactly one Vietnamese page.
    vn = {p: number_keys(txt) for p, (txt, _, _) in pages.items()}
    for path in sorted((ROOT / '03_text_sach' / cap / 'HAN').glob('[0-9][0-9][0-9][0-9]-cleaned.csv')):
        han = int(path.name[:4])
        if not han_start <= han <= han_end or han in regions:
            continue
        with path.open(encoding='utf-8-sig', newline='') as src:
            nums = number_keys(' '.join(r['text_zh'] for r in csv.DictReader(src)), han=True)
        hits = [(p, sorted(nums & vk)) for p, vk in vn.items() if len(nums & vk) >= 2]
        if len(hits) == 1:
            p, terms = hits[0]
            candidates[p].append((han, ', '.join(terms)))

    result = {}
    for p in pages:
        before = max((v for v in anchors if v < p), default=None)
        after = min((v for v in anchors if v > p), default=None)
        lo = min(a[0] for a in anchors[before]) if before else han_start
        hi = max(a[0] for a in anchors[after]) if after else han_end
        exact = anchors.get(p, [])
        evidence = ' | '.join(f'Hán {h}: {cue} — {note}' for h, cue, note in exact)
        verified = ', '.join(f'{h} ({regions[h]})' if h in regions else str(h) for h in sorted({a[0] for a in exact}))
        if cfg.get('han_start_region') and lo == han_start:
            evidence = ' | '.join(filter(None, [evidence, f'Giới hạn đầu: Hán {han_start} ({regions[han_start]})']))
        suggested = [(h, terms) for h, terms in candidates.get(p, []) if lo <= h <= hi]
        if suggested:
            evidence = ' | '.join(filter(None, [evidence, *(f'Ứng viên Hán {h} (số liệu: {terms})' for h, terms in suggested)]))
        status = 'đã xác minh mốc' if exact else 'ứng viên theo nội dung' if suggested else 'chưa xác minh'
        result[p] = (verified, ', '.join(str(h) for h, _ in suggested), lo, hi, status, evidence)
    return result


def excel_sheet(ws, headers, widths, rows):
    ws.append(headers)
    for row in rows:
        ws.append(row)
        for cell in ws[ws.max_row]:
            if cell.data_type == 'f':
                cell.data_type = 's'
            cell.alignment = Alignment(vertical='top', wrap_text=True)
    for i, width in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = width
    for cell in ws[1]:
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = PatternFill('solid', fgColor='23466A')
    ws.freeze_panes = 'D2'
    ws.auto_filter.ref = ws.dimensions


def run(cap, cfg):
    start, end = cfg['viet_start'], cfg['viet_end']
    pair = cfg.get('pair', cap)
    base = ROOT / '02_ocr_tho' / pair / 'VIET'
    raw_dir = base / 'raw' / 'pdftotext'
    pdf = ROOT / cfg.get('viet_pdf', f'01_nguon/{pair}/VIET.pdf')
    pages = load_pages(pdf, start, end)
    mapping = page_mapping(pair, pages, cfg)
    classify(pages, cfg)
    records = records_for(pages, cfg, cap)
    raw_dir.mkdir(parents=True, exist_ok=True)
    for p, (raw, _, _) in pages.items():
        (raw_dir / f'{p:04}_page_text.txt').write_text(raw, encoding='utf-8')

    counts = Counter(p for _, left, right, kind, _, _ in records if kind in MATCH_TYPES for p in range(left, right + 1))
    book = Workbook()
    sents = book.active
    sents.title = 'CAU_VIET'
    excel_sheet(sents, ['id_vi', 'viet_page_start', 'viet_page_end', 'loai', 'text_vi', 'dung_de_ghep', 'co_ra_soat'],
                [27, 19, 19, 18, 115, 17, 34],
                ((id_, p, q, kind, text, kind in MATCH_TYPES, flags) for id_, p, q, kind, text, flags in records))
    excel_sheet(book.create_sheet('TRANG_VIET'),
                ['viet_pdf_page', 'trang_in', 'so_muc_ghep_cham_trang', 'han_trang_co_moc', 'han_trang_ung_vien',
                 'han_cua_so_tu', 'han_cua_so_den', 'trang_thai_moc', 'can_cu'],
                [17, 12, 26, 23, 24, 16, 16, 25, 105],
                ((p, cfg['printed_start'] + p - start, counts[p], *mapping[p]) for p in pages))
    out = base / f'VIET_{start:04}-{end:04}.xlsx'
    book.save(out)
    print(f'{out.relative_to(ROOT)}: {len(pages)} pages, {sum(r[3] in MATCH_TYPES for r in records)} alignment units, '
          f'{sum(r[1] != r[2] for r in records)} cross-page units, '
          f'{sum(bool(row[0]) for row in mapping.values())} pages with verified anchors')


def main():
    config = json.loads(CONFIG.read_text(encoding='utf-8'))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cap', choices=['all', *config], default='all')
    args = parser.parse_args()
    for cap in config if args.cap == 'all' else [args.cap]:
        run(cap, config[cap])


if __name__ == '__main__':
    main()
