"""One entry point; only run/resume in an approved expanded live run use network."""
import argparse,re
from inputs import *
from windows import plan
from runner import execute
from export import publish
from audit import verify

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices='validate plan dry-run run resume export audit'.split());p.add_argument('--config',type=Path,default=HERE/'config/current.json');p.add_argument('--run-id');p.add_argument('--approve-live',action='store_true');args=p.parse_args();cfg=config(args.config);d=inventory(cfg);windows=plan(d,cfg);act=args.action
    if act=='validate':print(dump(dict(status='compatible',**d['meta'])));return
    if act=='plan' and not args.run_id:
        for w in windows:print(dump(w))
        return
    require(args.run_id and re.fullmatch('[A-Za-z0-9_-]+',args.run_id),'--run-id required');out=ROOT/cfg['output']/args.run_id;mp=out/'production_manifest.json';new=act in ('dry-run','run','plan');mode=('live' if act=='run' else 'offline') if new else read(mp)['mode'];live=mode=='live' and act in ('run','resume');require(not live or (cfg['profile']=='expanded' and args.approve_live),'live execution requires expanded mapping and --approve-live');ident=fingerprint([cfg,d['meta'],{p.name:sha(p) for p in HERE.glob('*.py')}]);
    if new:
        out.mkdir(parents=True,exist_ok=False);save(mp,dict(mode=mode,identity=ident,config=cfg,input_audit=d['meta'],windows=len(windows),run_id=args.run_id));jsonl(out/'window_manifest.jsonl',windows)
        if act=='plan':return
    else:require(read(mp)['identity']==ident,'input/config/code mismatch; use a new run ID')
    if act in ('run','resume','dry-run'):
        execute(out,cfg,d,windows,live)
    if act!='audit':publish(out,cfg,d,windows,mode)
    print(dump(verify(out,d)))
    if act in ('run','resume') and read(out/'metrics.json')['completed']<len(windows):raise SystemExit('Incomplete run; see progress.json and resume after service recovery')

if __name__=='__main__':
    try:main()
    except (ValueError,FileNotFoundError,FileExistsError) as e:raise SystemExit(str(e))
