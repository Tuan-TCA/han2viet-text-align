import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from stage04_candidates import alternatives, project, reconcile
from benchmark_alignment_api_v2 import parse_robust, aggregate_candidates


def response(*rows):
    return dict(id='r',status='success',raw_response=json.dumps({'data':{'result':rows}}))


def row(h,v,hs=0,he=0,vs=0,ve=0):
    return dict(han_text=h,vietnamese_text=v,han_start=hs,han_end=he,vi_start=vs,vi_end=ve,score=0.9)


def job(han='甲\n乙',vi='two\nthree'):
    return dict(id='e',cap='c',key='key',strategy='S4',h=[[0,1],[2,3]],v=['v1','v2'],
                han_offsets=[[[0,1]],[[2,3]]],han_ids_by_line=[['h1'],['h2']],payload={'han':han,'vi':vi})


class CandidateTests(unittest.TestCase):
    def test_blank_text_cannot_validate_wrong_in_range_index(self):
        c,=parse_robust(job(),response(row('', 'two')),'甲 乙',strict=True)
        self.assertEqual((c['Validation_Status'],c['Han_Start']),('untraceable',None))

    def test_multiunit_continuity_and_whitespace(self):
        for raw,status in [('甲 乙','mapped'),('甲丙乙','untraceable')]:
            c,=parse_robust(job(),response(row('甲 乙','two three',he=1,ve=1)),raw,strict=True)
            self.assertEqual(c['Validation_Status'],status)
            if status=='mapped': self.assertEqual(c['Alignment_Type'],'N-M')

    def test_whitespace_chain_retains_original_rows_and_blocks_content_gaps(self):
        j=job(vi='abcd\nother'); r=response(row('甲','ab'),row('乙','cd',hs=1,he=1))
        for raw,n in [('甲 乙',1),('甲丙乙',2)]:
            items=parse_robust(j,r,raw,strict=True)
            merged=aggregate_candidates(items,raw,{'v1':'abcd','v2':'other'},allow_han_whitespace=True)
            self.assertEqual(len(merged),n)
            if n==1:
                self.assertEqual(merged[0]['Source_Rows'],[0,1])
                self.assertEqual(len(merged[0]['Original_API_Rows']),2)

    def test_project_full_normalized_number_to_workbook_text(self):
        vi={'v1':dict(text_t1='2344',text_original='2.344',t1_offsets=[[0,1],[2,3],[3,4],[4,5]],source={'row':2}),
            'v2':dict(text_t1='other',text_original='other',t1_offsets=[[i,i+1] for i in range(5)],source={'row':3})}
        c,=project(job(vi='2344\nother'),response(row('甲','2344')),'甲 乙',vi)
        self.assertEqual((c['VI_Char_Spans'],c['Vietnamese_Text'],c['Label_Target']),([('v1',0,5)],'2.344','UNKNOWN'))

    def test_conflict_tie_and_exact_payload_not_extra_support(self):
        first=dict(Cap='c',Han_Start=0,Han_End=1,VI_Char_Spans=[('v1',0,4)],Validation_Status='mapped',
                   Experiment_ID='a',API_Response_ID='r',Source_Rows=[],Request_Key='1',Original_API_Rows=[],Score=.1)
        second={**first,'VI_Char_Spans':[('v2',0,4)],'Request_Key':'2','Score':.99}
        variants=[first,{**first,'API_Response_ID':'r2'},second]
        r=reconcile(variants,{'v1':0,'v2':1})
        self.assertEqual((len(r['selected']),r['duplicates'],r['conflict_edges']),(0,1,1))
        r=reconcile([*variants,{**first,'Request_Key':'3'}],{'v1':0,'v2':1})
        self.assertEqual(r['selected'][0]['VI_Char_Spans'],first['VI_Char_Spans'])

    def test_repairs_split_merge_and_move_at_source_backed_cut(self):
        segments=[dict(id_zh='h1',text_zh='甲，乙',global_raw_span=[0,3],normalized_source_spans=[[0,1],[1,2],[2,3]]),
                  dict(id_zh='h2',text_zh='丙',global_raw_span=[3,4],normalized_source_spans=[[3,4]])]
        variants={kind:units for kind,units in alternatives(segments,[],'甲，乙丙')}
        self.assertEqual(set(variants),{'split','merge','move'})
        self.assertEqual([u['span'] for u in variants['split']],[[0,2],[2,3],[3,4]])
        self.assertEqual(variants['move'][1]['ids'],['h1','h2'])
