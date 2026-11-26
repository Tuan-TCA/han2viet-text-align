import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from benchmark_alignment_api_v2 import aggregate_candidates, parse_robust, resolve


class ResolverTests(unittest.TestCase):
    def test_number_spacing_with_valid_indices(self):
        self.assertEqual(resolve(['Thu 4.349 quan.'], 0, 0, 'Thu 4. 349 quan.'),
                         ([(0, 0, 15)], 'indices_number_spacing'))

    def test_unique_fallback_preserves_offsets_across_original_space(self):
        text = 'Thu 4. 349 quan'
        spans, method = resolve(['Khác', text], 0, 5, '4.349')
        self.assertEqual(spans, [(1, 4, 10)])
        self.assertEqual(method, 'number_spacing_fallback')
        self.assertEqual(text[spans[0][1]:spans[0][2]], '4. 349')

    def test_wrong_but_in_range_index_falls_back_on_exact_unique_text(self):
        self.assertEqual(resolve(['abc', 'unique', 'end'], 0, 0, 'unique end'),
                         ([(1, 0, 6), (2, 0, 3)], 'exact_text_fallback'))

    def test_duplicate_after_normalizing_number_spacing_stays_ambiguous(self):
        self.assertEqual(resolve(['Thu 4.349', 'Thu 4. 349'], 2, 2, 'Thu 4.349'), ([], 'ambiguous'))

    def test_does_not_change_value_or_match_inside_another_number(self):
        for s in ('4.359', '14.349', '4,349', '4.3495', '14.349.000'):
            with self.subTest(s=s):
                self.assertEqual(resolve([s], 10, 10, '4.349'), ([], 'text_mismatch'))

    def test_disallows_invalid_indices_without_text(self):
        self.assertEqual(resolve(['abc'], False, 0, None), ([], 'invalid_range'))
        self.assertEqual(resolve(['abc'], -1, 0, ''), ([], 'invalid_range'))
        self.assertEqual(resolve(['abc'], -1, -1, ''), ([], 'empty'))

    def test_parse_projected_raw_han_and_original_vi_spans(self):
        raw = 'xa\t 4. 349 end'
        job = dict(payload={'han': 'xa 4. 349 end', 'vi': 'Thu 4. 349 quan'}, h=[[0,len(raw)]],
                   v=['v1'], strategy='S', id='E')
        item = dict(han_start=9, han_end=9, han_text='4.349', vi_start=9, vi_end=9, vietnamese_text='4.349')
        response = dict(id='R', status='success', raw_response=json.dumps({'data': {'result': [item]}}))
        c, = parse_robust(job, response, raw)
        self.assertEqual((c['Han_Start'], c['Han_End'], c['Han_Text']), (4, 10, '4. 349'))
        self.assertEqual(c['VI_Char_Spans'], [('v1', 4, 10)])


def candidate(row, ha, hb, va, vb, key='v1', **changes):
    c = dict(Row=row, Han_Start=ha, Han_End=hb, VI_Char_Spans=[(key,va,vb)], VI_IDs=[key], Han_Units=[row],
             API_Response_ID='R', Experiment_ID='E', Validation_Status='partial_viet',
             Score=0.5, Han_Partial_Unit=False, Source_Rows=[row])
    c.update(changes)
    return c


class AggregationTests(unittest.TestCase):
    raw = 'abcdefghij'
    viet = {'v1': 'abcdef', 'v2': 'uvwxyz'}

    def test_gather_three_rows_covering_entire_single_segment(self):
        items = [candidate(0,0,2,0,2), candidate(1,2,4,2,3), candidate(2,4,7,3,6)]
        merged, = aggregate_candidates(items, self.raw, self.viet)
        self.assertEqual(merged['Han_Text'], 'abcdefg')
        self.assertEqual(merged['Source_Rows'], [0,1,2])
        self.assertEqual(merged['VI_Char_Spans'], [('v1',0,6)])
        self.assertEqual(merged['Validation_Status'], 'mapped')
        self.assertEqual(merged['Alignment_Type'], 'N-1')
        self.assertEqual(items[0]['Validation_Status'], 'partial_viet')

    def test_complete_mapped_row_kept_without_merging(self):
        items = [candidate(0,0,2,0,6,Validation_Status='mapped'), candidate(1,2,4,0,6,Validation_Status='mapped')]
        self.assertEqual(aggregate_candidates(items, self.raw, self.viet), items)

    def test_rejects_gaps_overlaps_reverse_and_nonadjacent_rows(self):
        first = candidate(0,1,3,0,3)
        for label, nxt in {
            'han gap': candidate(1,4,6,3,6), 'han overlap': candidate(1,2,6,3,6),
            'han reversed': candidate(1,0,1,3,6), 'viet gap': candidate(1,3,6,4,6),
            'viet overlap': candidate(1,3,6,2,6), 'viet reversed': candidate(1,3,6,0,2),
            'viet incomplete': candidate(1,3,6,3,5), 'row skipped': candidate(2,3,6,3,6),
            'other response': candidate(1,3,6,3,6,API_Response_ID='R2'),
            'other experiment': candidate(1,3,6,3,6,Experiment_ID='E2'),
            'another ID': candidate(1,3,6,3,6,key='v2'),
            'multiple IDs': candidate(1,3,6,3,6,VI_IDs=['v1','v2'],VI_Char_Spans=[('v1',3,6),('v2',0,6)]),
            'unresolved': candidate(1,3,6,3,6,Validation_Status='untraceable'),
        }.items():
            with self.subTest(label=label):
                items = [first, nxt]
                self.assertEqual(aggregate_candidates(items, self.raw, self.viet), items)

    def test_cannot_skip_an_intervening_row_with_different_id(self):
        items = [candidate(0,0,2,0,3), candidate(1,2,4,0,6,key='v2'), candidate(2,2,6,3,6)]
        self.assertEqual(aggregate_candidates(items, self.raw, self.viet), items)


if __name__ == '__main__':
    unittest.main()
