from email.utils import formatdate
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from stage04_benchmark import preserves_global_evidence, window
from stage04_export import measures
from benchmark_alignment_api import Runner, fingerprint, retry_deadline, URL


def pair(a,b,vi):
    return {'Cap':'Cap_01','Han_Start':a,'Han_End':b,'VI_IDs':[vi],'VI_Char_Spans':[(vi,0,1)],
            'Validation_Status':'mapped','Alignment_Type':'1-1'}


class BenchmarkTests(unittest.TestCase):
    def test_window_shifts_without_truncation_or_duplicate_vi_ids(self):
        pool=list(range(40))
        self.assertEqual(window(pool,0,10),pool[:10])
        self.assertEqual(window(pool,38,10),pool[-10:])
        self.assertEqual(window(pool,20,5),pool[18:23])

    def test_reject_local_repair_that_loses_global_evidence(self):
        before=[pair(0,2,'v1'),pair(10,12,'v2')]
        self.assertFalse(preserves_global_evidence(before,[pair(0,8,'v1')],0,10))
        self.assertTrue(preserves_global_evidence(before,[pair(0,8,'v1'),before[1]],0,10))

    def test_complete_nm_group_scored_as_union_of_references(self):
        vi={'v1':{'text_original':'a'},'v2':{'text_original':'b'}}
        silver=[dict(Pair_ID=k,VI_ID=k,Boundary_Agreement='SAME',comparison={f'{model}_han_link':{'global_raw_span':s}
                 for model in ('chatgpt','deepseek')}) for k,s in [('v1',[0,2]),('v2',[2,4])]]
        c={**pair(0,4,'v1'),'VI_IDs':['v1','v2'],'VI_Char_Spans':[('v1',0,1),('v2',0,1)],'Alignment_Type':'N-M'}
        m=measures(dict(selected=[c],unresolved=[],duplicates=0,conflict_edges=0),
                   dict(raw='甲乙丙丁',silver=silver,vi=vi,han=[{'global_raw_span':[0,4]}]),[])
        self.assertEqual((m['refs']['agreed']['exact'],m['mapped_vi'],m['verified_semantic_positive_rate']),(2,2,None))

    def test_retry_after_seconds_and_http_date(self):
        self.assertEqual(retry_deadline('30',100),130)
        self.assertEqual(retry_deadline(formatdate(140,usegmt=True),100),140)
        self.assertIsNone(retry_deadline('junk',100))

    def test_resume_honors_server_deadline_and_reuses_success_without_network(self):
        temp = Path(os.environ['TEMP'])/'opencode'
        self.assertTrue(temp.is_dir())
        with TemporaryDirectory(dir=temp) as directory:
            args=SimpleNamespace(output=Path(directory),resume=True,retries=0,delay=0,timeout=1,
                                 request_budget=None,persist_retry_after=True)
            def make(name,vi):
                payload={'han':'甲','vi':vi}
                return dict(id=name,payload=payload,key=fingerprint([URL,payload]),repeat_of=None)
            first,second=make('first','một'),make('second','hai')
            success=SimpleNamespace(status_code=200,headers={},text='{"is_success":true,"data":{"result":[]}}')
            limited=SimpleNamespace(status_code=429,headers={'Retry-After':'3600'},text='{"code":"429"}')
            with patch('benchmark_alignment_api.requests.Session.post',side_effect=[success,limited]) as post:
                run=Runner(args,'example-token')
                try:
                    self.assertEqual(run.run(first)['status'],'success')
                    self.assertEqual(run.run(second)['status'],'auth_or_rate_limit')
                finally:
                    run.close()
                self.assertEqual(post.call_count,2)
            with patch('benchmark_alignment_api.requests.Session.post',side_effect=AssertionError('Unexpected network')):
                run=Runner(args,'example-token')
                try:
                    self.assertEqual(run.run(first)['status'],'success')
                    self.assertIsNone(run.run(second))
                    self.assertEqual(run.halt,'server_retry_after')
                finally:
                    run.close()
