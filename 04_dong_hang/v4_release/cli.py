import argparse
from experiment import *
from audit import audit,review

def freeze(out):
    paths=[HERE/f for f in ('engine.py','experiment.py','common.py','config.json','fresh.py')]+[HERE.parent/f for f in ('stage04_benchmark.py','stage04_inputs.py','stage04_candidates.py')]+[ROOT/'pipeline/scripts'/f for f in ('benchmark_alignment_api.py','benchmark_alignment_api_v2.py','benchmark_alignment_api_final.py')];identity={str(p.relative_to(ROOT)):digest(p) for p in paths};p=out/'freeze.json'
    if p.exists() and read(p)!=identity:raise RuntimeError('Frozen code changed: use a new run ID')
    if not p.exists():save(p,identity)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('action',choices=['all','continuation','benchmark','publish','consume']);ap.add_argument('run_id');ap.add_argument('cap',nargs='?');ap.add_argument('pages',type=int,nargs='*');a=ap.parse_args();o=output(a.run_id)
    if a.action in ('all','continuation'):
        c=run(o,'continuation');audit(o,c);review(o,[])
    if a.action in ('all','benchmark'):freeze(o);run(o,'benchmark')
    if a.action in ('all','publish'):
        from publish import publish
        freeze(o);publish(o)
    if a.action=='consume':
        us=load_han(o/'stage04'/a.cap/'V4',*a.pages);print(f'{len(us)} Han units; {us[0].id} through {us[-1].id}')
