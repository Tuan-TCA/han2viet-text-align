import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import stage04_offline as offline


def group(n,a,b,parts):
    return dict(Han_Start=a,Han_End=b,VI_Char_Spans=parts,VI_IDs=list(dict.fromkeys(k for k,_,_ in parts)),
                Source_Rows=[{'response':'r','row':n}],Original_Pair_IDs=[str(n)])


class OfflineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.f=offline.load()
        cls.base,cls.response,cls.rows=offline.replay(cls.f)
        offline.bind_review(offline.sheets(offline.REVIEW),cls.base)
        cls.scope=[0,905]; cls.ids=cls.response['job']['v']
        cls.outputs,cls.log=offline.variants(cls.f,cls.base,cls.scope)

    def fixture(self):
        return dict(raw='甲 乙丙',han=[dict(id_zh='h1',global_raw_span=[0,2],normalized_source_spans=[[0,1]],source=[]),
                                     dict(id_zh='h2',global_raw_span=[2,4],normalized_source_spans=[[2,3],[3,4]],source=[])],
                    vi={'v':dict(text_original='a b',t1_offsets=[[0,1],[1,2],[2,3]],source={'row':2})})

    def test_baseline_exact_with_original_api_row_provenance(self):
        self.assertEqual(len(self.base),15)
        self.assertEqual([g['Source_Rows'] for g in self.base],
                         [[{'response':self.response['id'],'row':i}] for i in range(15)])
        self.assertEqual([g['Original_API_Rows'][0] for g in self.base],self.rows)

    def test_contiguous_aggregation_preserves_whitespace_offsets_and_rows(self):
        f=self.fixture(); first=group(0,0,1,[('v',0,1)]); second=group(1,2,4,[('v',2,3)])
        out,why=offline.aggregate(f,[first,second])
        self.assertIsNone(why)
        self.assertEqual((out['Han_Text'],out['VI_Char_Spans'],out['VI_Normalized_Spans']),('甲 乙丙',[('v',0,3)],[('v',[[0,3]])]))
        self.assertEqual(out['Source_Rows'],first['Source_Rows']+second['Source_Rows'])
        self.assertEqual(out['Semantic_Assessment'],'UNKNOWN')

    def test_reject_han_gap_overlap_skipped_row_and_vi_overlap(self):
        f=self.fixture(); first=group(0,0,1,[('v',0,2)])
        for second,expected in [(group(1,3,4,[('v',2,3)]),'MEANINGFUL_HAN_GAP'),
                                (group(1,0,4,[('v',2,3)]),'HAN_OVERLAP'),
                                (group(2,2,4,[('v',2,3)]),'SKIPPED_OR_DIFFERENT_API_ROW'),
                                (group(1,2,4,[('v',1,3)]),'VI_OVERLAP_OR_MEANINGFUL_GAP')]:
            with self.subTest(expected=expected):
                self.assertEqual(offline.aggregate(f,[first,second]),(None,expected))

    def test_protect_multilingual_group_without_unique_splitting_evidence(self):
        old=next(g for g in self.base if g['Alignment_Type']=='N-M')
        self.assertIsNone(offline.split_mixed(self.f,old))
        self.assertIn(old,self.outputs['V1']); self.assertIn(old,self.outputs['V2'])

    def test_missing_span_detection_and_numeric_recovery(self):
        missing=offline.occupancy(self.base,self.f,self.scope,self.ids)['han_gaps']
        self.assertEqual([g['span'] for g in missing],[[166,213],[372,396]])
        recovered=next(g for g in self.outputs['V3'] if offline.spans(g)==(55,213))
        self.assertIn('2727',recovered['Correction_Reason'])

    def test_case_d_split_keeps_frozen_boundary_and_records_both_rows(self):
        old=self.base[10:12]; left,right=offline.split_candidates(self.f,*old)[0]
        self.assertEqual(offline.spans(old[0]),(664,727))
        self.assertEqual(offline.spans(left),(664,731)); self.assertEqual(right['Han_Start'],731)
        self.assertTrue(left['Han_Text'].endswith('諱日亦照'))
        self.assertEqual(left['Source_Rows'],old[0]['Source_Rows']+old[1]['Source_Rows'])
        self.assertEqual(right['Source_Rows'],old[1]['Source_Rows'])
        self.assertEqual(left['Semantic_Assessment'],'UNKNOWN')

    def test_reassignment_requires_successor_cue_and_preserves_continuation(self):
        out=self.outputs['V3'][-1]
        self.assertEqual(offline.spans(out),(731,893))
        self.assertEqual(out['VI_IDs'],self.base[11]['VI_IDs'])
        self.assertEqual([r['row'] for r in out['Source_Rows']],[11,12,13,14])
        cov=offline.occupancy(self.outputs['V3'],self.f,self.scope,self.ids)
        self.assertEqual(cov['han_gaps'][0]['span'],[893,905])
        self.assertEqual(set(cov['vi_gaps']),set(self.response['job']['v'][-4:]))
        chain=[offline.split_candidates(self.f,*self.base[10:12])[0][1],*self.base[12:]]
        raw=self.f['raw']; modified={**self.f,'raw':raw[:893]+'甲'*12+raw[905:]}
        self.assertEqual(offline.reassign(modified,chain,self.scope),(None,'NO_UNIQUE_SUCCESSOR_ENTITY'))

    def test_all_variants_preserve_every_aligned_or_unresolved_character_once(self):
        for variant,rows in self.outputs.items():
            with self.subTest(variant=variant):
                cov=offline.occupancy(rows,self.f,self.scope,self.ids)
                self.assertEqual((cov['han_duplicate_chars'],cov['vi_duplicate_chars']),(0,0))
                offline.conservation(rows,self.f,self.scope,self.ids,cov)
