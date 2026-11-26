import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from stage04_inputs import load, han_unit, merge_units, viet_t1


class InputsTests(unittest.TestCase):
    def test_frozen_inventory_and_source_backed_silver(self):
        f=load()
        self.assertEqual(len(f['silver']),12)
        self.assertEqual(len(f['han']),40)
        self.assertGreater(len(f['vi']),1019)
        self.assertEqual([r['Han_Page'] for r in f['unsupported']],list(range(52,93)))
        self.assertTrue(all(r['Han_Text'] and r['Han_IDs'] for r in f['unsupported']))

    def test_number_normalization_is_reversible_and_leaves_decimals(self):
        original = '  2.344; 1.234.567; 12.34; 2,344; 7.456  '
        text, spans = viet_t1(original,('2.344',))
        self.assertEqual(text,'2344; 1234567; 12.34; 2,344; 7.456')
        self.assertEqual(original[spans[0][0]:spans[3][1]],'2.344')
        self.assertEqual(original[spans[6][0]:spans[12][1]],'1.234.567')

    def test_temp_units_keep_original_id_and_compose_offsets(self):
        s=dict(id_zh='s',text_zh='甲 乙',global_raw_span=[0,4],normalized_source_spans=[[0,1],[1,3],[3,4]])
        a,b=han_unit(s,0,1),han_unit(s,2)
        combined=merge_units(a,b,'甲  乙')
        self.assertEqual((combined['span'],combined['ids'],combined['offsets']),([0,4],['s'],[[0,1],[1,3],[3,4]]))
        with self.assertRaises(ValueError):
            merge_units(a,b,'甲丙 丁')
