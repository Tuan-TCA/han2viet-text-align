import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from production_prepare import binding,run_inventory


class ProductionTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(dir=Path(__file__).parent);self.addCleanup(tmp.cleanup);self.out=Path(tmp.name)
        self.cfg={'genre':'history'};self.client=Mock(halt=None)
        self.ws=[]
        for i,raw in enumerate(('甲乙','丙丁')):
            self.ws.append({'id':f'Cap_01-{i*2+1:03}-{i*2+2:03}','start':2*i,'raw':raw,'viet':[],'status':'unmatched',
                'pages':[{'han_pdf_page':2*i+j+1,'global_raw_span':[2*i+j,2*i+j+1],'file_text_span':[10*j,10*j+1],
                          'source':{'path':'fixture.txt'}} for j in range(2)]})

    def answer(self,w): return binding(w,self.cfg)['payload_key'],[{'text_api':w['raw']+'。','global_raw_span':[0,2]}],'ok'

    def execute(self):
        self.man={'windows':[{'status':'pending'} for w in self.ws]}
        return run_inventory(self.out,self.ws,self.client,self.cfg,self.man,[{} for _ in self.ws])

    def test_interrupt_resume_and_cross_page(self):
        self.client.separate.side_effect=[self.answer(self.ws[0]),KeyboardInterrupt()]
        with self.assertRaises(KeyboardInterrupt): self.execute()
        self.assertEqual([e['status'] for e in json.loads((self.out/'production_manifest.json').read_text())['windows']],['successful','pending'])
        self.client.separate.reset_mock(); self.client.separate.side_effect=[self.answer(self.ws[1])]
        rows=self.execute(); self.client.separate.assert_called_once_with('丙丁')
        self.assertEqual(''.join(r['text_original'] for r in rows),'甲乙丙丁'); self.assertEqual([r['page_end']-r['page_start'] for r in rows],[1,1]); self.assertEqual(rows[0]['source'][1]['file_span'],[10,11])

    def test_failed_separate_keeps_evidence_and_retries_only_failed(self):
        self.client.separate.side_effect=[(binding(self.ws[0],self.cfg)['payload_key'],[],'api_error'),self.answer(self.ws[1])]
        rows=self.execute(); self.assertEqual(len(rows),1); self.assertEqual(self.man['windows'][0]['status'],'failed')
        cp=json.loads(next((self.out/'checkpoints').glob('*001-002.json')).read_text(encoding='utf8'))
        self.assertEqual(cp['data']['source_pages'],self.ws[0]['pages']); self.assertEqual(cp['data']['segments'],[])
        self.client.separate.reset_mock();self.client.separate.side_effect=[self.answer(self.ws[0])];self.execute();self.client.separate.assert_called_once_with('甲乙')
