import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from preprocess import ROOT
from benchmark_alignment_api import inputs
from release_segmentation import METHODS,partition
from run_release import availability,nested


class ReleaseTests(unittest.TestCase):
    def test_baseline_parity_and_mandatory_ends(self):
        raw,strats,*_=inputs()
        p=json.loads((ROOT/'pipeline/artifacts/separate_pilot_cap01/results.json').read_text(encoding='utf8'))['cases'][2]['analysis']['projected_sentences']
        mandatory={r['global_raw_span'][1] for r in p}
        for name in METHODS:
            spans,_=partition(raw,p,name); self.assertTrue(mandatory <= {b for a,b in spans})
            self.assertEqual(''.join(raw[a:b] for a,b in spans),raw)
            if name=='S4': self.assertEqual([tuple(x) for x in spans],strats[name])

    def test_added_entity_edges_and_conflicting_punctuation(self):
        raw='甲知府乙十七丙';p=[{'global_raw_span':[0,len(raw)],'text_api':'甲知，府乙十七丙。'}]
        cuts,conflicts=partition(raw,p,'S8'); ends={b for a,b in cuts}
        self.assertIn(2,conflicts); self.assertTrue({1,2,3,4,6}<=ends); self.assertNotIn(5,ends)

    def test_availability_does_not_reward_excess_cuts(self):
        w={'raw':'甲乙丙丁戊己','start':50}; refs=[{'Han_Start_0':a,'Han_End_exclusive':b,'comparison':{'CG_End':b,'DS_End':b}} for a,b in ((50,52),(52,56))]
        row=availability(w,[[0,1],[1,2],[2,6]],refs)[0]
        self.assertEqual((row['hits'],row['total'],row['availability'],row['precision']),(1,1,1,0.5))
        self.assertTrue(set(nested(list(range(40)),8,5))<=set(nested(list(range(40)),8,30)))
