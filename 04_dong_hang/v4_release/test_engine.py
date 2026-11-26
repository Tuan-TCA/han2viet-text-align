import unittest
from common import HERE,read
from engine import refine,normalize,signature,conflict
from stage04_candidates import project
from benchmark_alignment_api_v2 import resolve

def group(a,b,ids,source='r'):
    return dict(Han_Start=a,Han_End=b,Han_Text='甲乙丙丁'[a:b],VI_IDs=list(ids),VI_Char_Spans=[(i,0,1) for i in ids],Request_Key=source,Validation_Status='mapped',Vietnamese_Text=' '.join(ids),API_Score=1)
def run(groups,probes):
    r=dict(ids=list('abc'),han=[[0,3],[3,4]],baseline=groups);return refine(r,[r,*[{'baseline':p} for p in probes]],'甲乙丙丁',{k:{'text_original':k} for k in 'abc'},read(HERE/'config.json'))
class Engine(unittest.TestCase):
    def test_normalization(self):
        s='2.344 1.234.567 3.14 01.02.2020 ID-2.344';n,m=normalize(s);self.assertEqual(n,'2344 1234567 3.14 01.02.2020 ID-2.344');self.assertEqual(''.join(s[a:b] for a,b in m),s)
    def test_ambiguous_text(self):self.assertIn('ambiguous',resolve(['same','same'],None,None,'same'))
    def test_gap(self):
        g=group(2,4,'b');sel,l=run([group(0,2,'a')],[[g],[{**g,'Request_Key':'other'}]]);self.assertEqual(len(sel),2);self.assertIn(2,next(x for x in l if x['disposition']=='applied')['intra_s4'])
    def test_repeated_evidence(self):
        g=group(2,4,'b');self.assertEqual(len(run([],[[g],[g]])[0]),0)
    def test_crossing(self):self.assertTrue(conflict(group(0,2,'b'),group(2,4,'a'),{'a':0,'b':1}))
    def test_duplicates(self):
        g=group(0,2,'a');s,l=run([g,g],[]);self.assertEqual(len(s),2);self.assertIn('duplicate',l[0]['disposition'])
    def test_nm_split(self):
        parent=group(0,4,'ab');children=[group(0,2,'a'),group(2,4,'b')];s,l=run([parent],[children,[{**g,'Request_Key':'other'} for g in children]]);self.assertEqual([signature(x) for x in s],[signature(x) for x in children]);self.assertEqual(parent['Han_End'],4)
    def test_keep_nm(self):self.assertEqual(run([group(0,4,'ab')],[])[0][0]['VI_IDs'],['a','b'])
    def test_intervening_id(self):
        g=group(0,3,'ac');self.assertFalse(run([],[[g],[{**g,'Request_Key':'other'}]])[0])
