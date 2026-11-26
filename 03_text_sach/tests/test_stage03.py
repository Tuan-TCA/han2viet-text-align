import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from api_integration import ALIGN, Client, retry_seconds
from benchmark_alignment_api import inputs as legacy_inputs
from candidate_boundaries import generate, numbers, s4
from local_repair import accept, quality
from preprocess import ROOT, STAGE, audit_partition, normalize, viet_t1
from segmentation import dynamic, lattice_points

CFG=json.loads((STAGE/'config/stage03.json').read_text(encoding='utf-8'))


class Stage03Tests(unittest.TestCase):
    def test_reversible_normalization_and_t1(self):
        original='  a\u0301\t\n  1.234.567 và 1.234  '
        text,spans=normalize(original)
        self.assertEqual(text,'á 1.234.567 và 1.234')
        self.assertEqual(original[slice(*spans[0])],'a\u0301')
        self.assertEqual(original[slice(*spans[1])],'\t\n  ')
        t,ix=viet_t1(original)
        self.assertEqual(t,'á 1234567 và 1.234')
        self.assertEqual([original[slice(*s)] for s in ix[2:9]],list('1234567'))

    def test_protected_candidates(self):
        marks=generate('文十七知府。故曰可',[],[],1)
        self.assertEqual(marks[2]['blocked'],['number'])
        self.assertEqual(marks[4]['blocked'],['entity'])
        self.assertNotIn(2,lattice_points(marks))
        self.assertIn('grammar',marks[6]['sources'])
        self.assertIn(17,numbers('十七',True))

    def test_legacy_s4_exact_parity(self):
        raw,strats,*_=legacy_inputs()
        fixture=ROOT/'pipeline/artifacts/separate_pilot_cap01/results.json'
        projected=json.loads(fixture.read_text(encoding='utf-8'))['cases'][2]['analysis']['projected_sentences']
        cuts=s4(raw,projected)
        self.assertEqual(list(zip(cuts,cuts[1:])),strats['S4'])

    def test_dp_preserves_han_and_monotonic_viet(self):
        raw='文書明。國家治。'
        marks=generate(raw,[],[len(raw)],2)
        path=dynamic(raw,['văn chương','quốc gia'],marks,CFG,1.5,{'length':1})
        self.assertEqual(''.join(raw[a:b] for a,b in (p['han'] for p in path)),raw)
        self.assertEqual([j for x in path for j in range(*x['vi'])],[0,1])
        self.assertTrue(all(x['han'][1]==y['han'][0] and x['vi'][1]==y['vi'][0] for x,y in zip(path,path[1:])))
        no_vi=dynamic(raw,[],marks,CFG,1.5,{'length':1})
        self.assertTrue(all(x['kind']=='skip_han' for x in no_vi))

    def test_partition_detects_loss_and_duplicate(self):
        self.assertEqual(audit_partition('abcd',[(0,2),(2,4)]),{'missing':0,'duplicated':0,'exact_reconstruction':True})
        self.assertEqual(audit_partition('abcd',[(0,2),(1,3)]),{'missing':1,'duplicated':1,'exact_reconstruction':False})

    def test_coverage_and_repair_reject_overlaps(self):
        def result(ranges):
            return {'status':'ok','groups':[{'Validation_Status':'mapped','Han_Start':a,'Han_End':b,
                    'VI_IDs':[str(i)],'Alignment_Type':'1-1'} for i,(a,b) in enumerate(ranges)]}
        a,b=result([(0,10),(2,3),(5,12)]),result([(0,6),(6,12),(12,16)])
        self.assertEqual(quality(a)['overlap'],6)
        self.assertTrue(accept(a,b))
        self.assertFalse(accept(b,a))

    def test_resume_cache_and_server_pause(self):
        with TemporaryDirectory(dir=STAGE/'tests') as tmp:
            f=Path(tmp); cfg={**CFG,'api_delay':0}
            c=Client(f,cfg,True); c.token='fake_test_token'
            reply=Mock(status_code=200,text='{"is_success":true,"code":"000000","data":{"result":[]}}',headers={})
            c.session.post=Mock(return_value=reply)
            payload={'han':'文','vi':'văn'}
            self.assertEqual(c.call(ALIGN,payload)['status'],'ok')
            self.assertEqual(c.attempts,1)
            c.close()
            resumed=Client(f,cfg,False)
            self.assertEqual(resumed.call(ALIGN,payload)['status'],'ok')
            self.assertEqual(resumed.attempts,0)
            resumed.live=True; resumed.token='fake_test_token'
            resumed.session.post=Mock(return_value=Mock(status_code=429,text='{}',headers={'Retry-After':'60'}))
            resumed.call(ALIGN,{'han':'書','vi':'thư'})
            self.assertEqual(resumed.halt,'server_retry_after')
            self.assertEqual(resumed.call(ALIGN,{'han':'地','vi':'đất'})['status'],'server_retry_after')
            resumed.session.post.assert_called_once()
            resumed.close()
        self.assertEqual(retry_seconds('60'),60)
