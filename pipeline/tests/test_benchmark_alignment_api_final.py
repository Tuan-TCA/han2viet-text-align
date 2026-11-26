import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import benchmark_alignment_api_final as exp


class ExperimentTests(unittest.TestCase):
    def test_protect_decimals_and_project_dotted_integers(self):
        src = '2.344; 1.234.567; 3.14; 8.456; 12.3456; 1.234,56; 9,123'
        value, offsets, changes = exp.normalize_numbers(src, ['2.344'])
        self.assertEqual(value, '2344; 1234567; 3.14; 8.456; 12.3456; 1.234,56; 9,123')
        self.assertEqual(''.join(src[i] for i in offsets), value)
        self.assertEqual([src[a:b] for a,b in (c['source_span'] for c in changes)], ['2.344','1.234.567'])

    def test_protect_numbers_when_splitting_and_restore_source_offsets(self):
        key='Cap_01-VI-0186-003'
        text='Thu 2.727 bát. Giá 3.14; còn dư.'
        fs=exp.fragments(key,text,'T3')
        self.assertEqual([f['text'] for f in fs], ['Thu 2727 bát.', 'Giá 3.14;', 'còn dư.'])
        self.assertEqual(text[fs[0]['start']:fs[0]['end']], 'Thu 2.727 bát.')
        self.assertEqual(''.join(text[i] for i in fs[0]['offsets']), 'Thu 2727 bát.')

    def test_reversal_preserves_id_and_original_text(self):
        raw='甲乙'; source={'v1':'một','v2':'hai'}
        j=exp.make_job('E08','reverse',[(0,1),(1,2)],['v2','v1'],raw,source)
        result=[dict(han_start=0,han_end=0,vi_start=1,vi_end=1,han_text='甲',vietnamese_text='một')]
        response=dict(id='R',status='success',raw_response=json.dumps({'data':{'result':result}}))
        c,=exp.project(j,response,raw,source)
        self.assertEqual(c['VI_IDs'], ['v1'])
        self.assertEqual(c['VI_Char_Spans'], [['v1',0,3]])

    def test_aggregation_allows_whitespace_only_in_both_languages(self):
        def row(i,a,b,x,y):
            return dict(Row=i, Han_Start=a,Han_End=b,VI_Char_Spans=[['v',x,y]], VI_IDs=['v'],Han_Units=[i],
                        API_Response_ID='R',Experiment_ID='E',Validation_Status='partial_viet',Score=0.5,
                        VI_Payload_Spans=[],Source_Rows=[i])
        pair=[row(0,0,1,0,1),row(1,2,3,2,3)]
        c,=exp.aggregate(pair,'甲 乙',{'v':'a b'})
        self.assertEqual(c['VI_Char_Spans'], [['v',0,3]])
        self.assertEqual(c['Source_Rows'], [0,1])
        self.assertEqual(exp.aggregate(pair,'甲，乙',{'v':'a b'}), pair)
        self.assertEqual(exp.aggregate(pair,'甲 乙',{'v':'a,b'}), pair)
        self.assertEqual(exp.aggregate(pair,'甲 乙',{'v':'a2b'}), pair)

    def test_identical_historical_payload_reused_on_first_run_and_resume(self):
        j=exp.make_job('E07','fixture',[(0,1)],['v'],'甲',{'v':'a'})
        previous={'id':'H001','job':j,'status':'success','cached':False,'raw_response':'{}','latency_ms':18}
        with tempfile.TemporaryDirectory() as temp, patch('requests.Session.post',side_effect=AssertionError('unexpected request')):
            for resume in (False,True):
                a=SimpleNamespace(output=Path(temp)/'run',resume=resume,request_budget=None,retries=0,delay=0,timeout=1)
                r=exp.Runner(a,'mock-token',{j['key']:previous})
                try:
                    result=r.run(j)
                    self.assertTrue(result['cached'])
                    self.assertEqual(result['id'],'H001')
                    self.assertEqual(len(r.entries),1)
                finally:
                    r.close()


if __name__=='__main__':
    unittest.main()
