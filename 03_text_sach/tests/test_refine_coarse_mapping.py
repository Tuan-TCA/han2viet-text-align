import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from refine_coarse_mapping import Evaluation, anchors_for, interpolate, reconcile, span_for


class CoarseMappingTests(unittest.TestCase):
    def test_hidden_anchor_does_not_affect_interpolation(self):
        rows=[{'viet_pdf_page':v,'verified_overlap':[{'han_pdf_page':h}]} for h,v in [(1,10),(2,15),(3,14)]]
        self.assertEqual(interpolate(2,anchors_for(rows,2),(10,20)),12)
        rows[1]['viet_pdf_page']=18
        self.assertEqual(interpolate(2,anchors_for(rows,2),(10,20)),12)

    def test_deferred_page_cannot_reset_monotonicity(self):
        first=[{'range':[12,13],'adjusted':3.}]; mid=[{'range':None,'adjusted':0.}]
        later=[{'range':[10,11],'adjusted':20.},{'range':[13,14],'adjusted':1.}]
        self.assertEqual(reconcile([first,mid,later])[-1]['range'],[13,14])

    def test_cross_page_segment_kept_and_checkpoint_reused(self):
        ss=[{'id_zh':'across','page_start':1,'page_end':2,'global_raw_span':[9,14],'text_original':'甲乙丙丁戊'},
            {'id_zh':'end','page_start':2,'page_end':2,'global_raw_span':[14,15],'text_original':'己'}]
        self.assertEqual(span_for(ss,2)[1:],(9,'甲乙丙丁戊己',[[0,5],[5,6]]))
        p={'cap':'Cap_01','han_pdf_page':2,'id':'p2','global_raw_span':[11,15]}
        v=[{'id':'v','viet_page_start':1,'viet_page_end':1}]
        client=Mock(halt=None);client.align.return_value={'status':'ok','request_key':'exact','groups':[]}
        with TemporaryDirectory(dir=Path(__file__).parent) as t:
            out=Path(t); (out/'checkpoints').mkdir(); e=Evaluation(out,client,{}, {'Cap_01':ss},'fixture')
            r=e.probe(p,v,1,None,'check');self.assertEqual(r,e.probe(p,v,1,None,'check'))
            self.assertEqual(r['missing_han'],4); self.assertEqual(r['han_ids'],['across','end']);client.align.assert_called_once()
