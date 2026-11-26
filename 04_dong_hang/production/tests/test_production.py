"""Production contracts: saved real responses only; no network in this suite."""
import io,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from inputs import *
from runner import Client,execute,job
from reconcile import collect
from windows import plan
from export import publish
from audit import verify

class Production(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg=config(HERE/'config/current.json');cls.d=inventory(cls.cfg);cls.ws=plan(cls.d,cls.cfg);cls.by={w['id']:w for w in cls.ws};cls.w=cls.by['Cap_01-027-028']

    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.o=Path(tmp.name);mock=patch('requests.sessions.Session.post',side_effect=AssertionError('unexpected network'));mock.start();self.addCleanup(mock.stop)

    def test_source_inventory(self):
        self.assertEqual((len(self.d['ss']),len(self.d['raw']),len(self.d['pages'])),(2808,53328,145));self.assertEqual(len(self.d['byid']),2808)

    def test_cross_page_context_dedup(self):
        w=self.by['Cap_01-002-003'];ss=[self.d['byid'][k] for k in w['han_ids']];self.assertTrue(any(s['page_start']!=s['page_end'] for s in ss));self.assertEqual(len(ss),len(set(w['han_ids'])));self.assertTrue(set(w['han_ids'])&set(self.by['Cap_01-001-002']['han_ids']));self.assertEqual(len(w['vi_ids']),len(set(w['vi_ids'])))

    def test_unmatched_and_partial(self):
        for w in self.ws:
            if w['cap']=='Cap_02' and min(w['pages'])>=51:self.assertFalse(w['han_ids'])
        self.assertEqual(set((w['cap'],p) for w in self.ws for p in w['pages']),self.d['pages'])

    def test_offset_partitions_and_template(self):
        execute(self.o,self.cfg,self.d,[self.w],False);m=publish(self.o,self.cfg,self.d,[self.w],'offline');self.assertGreater(m['partial_response_groups'],0);self.assertEqual(m['network_requests'],0);a=verify(self.o,self.d);self.assertEqual(a['han_characters_accounted'],53328);wb=load_workbook(self.o/'alignment_final.xlsx');ws=wb.active;t=load_workbook(io.BytesIO(template())).active;self.assertEqual(ws['B3']._style,t['B3']._style);self.assertEqual(ws['I3'].value,None);self.assertEqual(ws['D3'].value,None);self.assertEqual([d.formula1 for d in ws.data_validations.dataValidation],[d.formula1 for d in t.data_validations.dataValidation]);self.assertEqual(list(ws.values)[1],list(t.values)[1]);self.assertIn('Audit',wb.sheetnames)

    def test_global_duplicates_and_conflicts(self):
        execute(self.o,self.cfg,self.d,[self.w],False);other={**self.w,'id':'overlapping-fixture'};cp=self.o/self.cfg['checkpoint_dir'];c=read(cp/(self.w['id']+'.json'));groups=c['attempts'][0]['groups'];g=next(x for x in groups if x['Validation_Status']=='mapped');rival={**g,'Han_Start':g['Han_Start']+1,'Han_Text':g['Han_Text'][1:]};c['attempts'][0]['groups']=[g,rival];save(cp/(other['id']+'.json'),c);gs,_,reject,*_,m=collect(self.o,self.cfg,self.d,[self.w,other]);self.assertGreater(m['duplicates'],0);self.assertGreater(m['conflict_edges'],0);self.assertTrue(reject);self.assertNotIn(g['VI_Char_Spans'],[x['VI_Char_Spans'] for x in gs])

    def test_resume_and_exact_cache(self):
        w2=self.by['Cap_02-009-010'];execute(self.o,self.cfg,self.d,[self.w],False);log=self.o/'requests.jsonl';old=lines(log);execute(self.o,self.cfg,self.d,[self.w,w2],False);after=lines(log);self.assertEqual(after[:len(old)],old);execute(self.o,self.cfg,self.d,[self.w,w2],False);self.assertEqual(lines(log),after);j=job(self.d,self.w,self.w['han_ids'],self.w['vi_ids'],'alias');c=Client(self.o,{**self.cfg,'seed_logs':[]},False);self.assertTrue(c.call(j)['cached']);j=job(self.d,self.w,self.w['han_ids'],self.w['vi_ids'][:-1],'shorter');self.assertEqual(c.call(j)['status'],'offline_cache_miss');c.base.close()

    def test_failed_response_checkpoint(self):
        with patch.object(Client,'call',return_value={'status':'transport_error'}):execute(self.o,self.cfg,self.d,[self.w],False)
        cp=self.o/self.cfg['checkpoint_dir']/(self.w['id']+'.json');self.assertFalse(read(cp)['complete']);self.assertFalse(read(cp)['attempts'][0]['groups']);execute(self.o,self.cfg,self.d,[self.w],False);self.assertTrue(read(cp)['complete']);self.assertEqual(read(cp)['status'],'success')

    def test_absent_expanded_never_falls_back(self):
        cfg={**config(HERE/'config/expanded.json'),'mapping_dir':str(self.o)}
        with self.assertRaisesRegex(FileNotFoundError,'expanded input unavailable'):inventory(cfg)

    def test_multiworkbook_transition_schema(self):
        # Synthetic mapping input, real eligible source rows, no synthetic API success.
        cfg={**config(HERE/'config/expanded.json'),'mapping_dir':str(self.o),'viet_segments':str(self.o/'extended.jsonl')};name=cfg['workbooks']['Cap_02'][1];wb=load_workbook(ROOT/name,read_only=True,data_only=True);it=iter(wb['CAU_VIET'].values);headers=next(it);extra=[]
        for n,row in enumerate(it,2):
            r=dict(zip(headers,row));
            if r['dung_de_ghep']:extra.append(dict(id=r['id_vi'],source=dict(path=name,row=n,sheet='CAU_VIET'),cap='Cap_02',text_original=r['text_vi'].strip()))
        wb.close();jsonl(self.o/'extended.jsonl',lines(ROOT/self.cfg['viet_segments'])+extra);ms=lines(ROOT/self.cfg['mapping_dir']/cfg['mapping_file']);cs=lines(ROOT/self.cfg['mapping_dir']/cfg['window_context']);c=next(r for r in cs if (r['cap'],r['han_page'])==('Cap_02',51));m=next(r for r in ms if (r['Cap'],r['Han_Page'])==('Cap_02',51));v=extra[0];t,sp=viet_t1(v['text_original']);c['mapping_status']=m['Mapping_Status']='VERIFIED';c['book_transition']={'fixture':True};c['viet'].append(v);c['viet_t1'].append({**v,'vi_id':v['id'],'text_t1':t,'normalized_source_spans':sp});m['Selected_VI_IDs'].append(v['id']);c['padded_context_vi_ids']=[extra[1]['id']];jsonl(self.o/cfg['mapping_file'],ms);jsonl(self.o/cfg['window_context'],cs);d=inventory(cfg);ws=plan(d,cfg);w=next(w for w in ws if w['id']=='Cap_02-050-051');self.assertTrue(w['book_transitions']);self.assertIn(extra[1]['id'],w['vi_ids']);self.assertGreater(d['order'][v['id']],d['order'][c['viet'][0]['id']]);self.assertEqual(d['meta']['vi_records'],len(self.d['vi'])+len(extra))
