from inputs import *
from stage04_candidates import reconcile,identity

def complement(start,end,spans):
    pos=start
    for a,b in sorted(spans):
        a=max(a,start);b=min(b,end)
        if a>=b:continue
        require(a>=pos,'overlapping selected source coverage');
        if a>pos:yield pos,a
        pos=b
    if pos<end:yield pos,end

def collect(out,cfg,d,windows):
    rows=[];states=[];errors=[];attempts=[]
    for w in windows:
        p=out/cfg['checkpoint_dir']/(w['id']+'.json');c=read(p) if p.exists() else {'status':'not_executed','attempts':[]};states.append({**w,'status':c['status'],'completed':c.get('complete',False)});
        for a in c['attempts']:
            attempts.append(a);rows.extend(a['groups']);
            if a.get('mapping_error'):errors.append({**a,'reason':'source_projection_error'})
    safe=[]
    for g in rows:
        if g['Validation_Status'] in ('mapped','partial_viet') and (g['Han_Start'] is None or not g['VI_Char_Spans']):
            errors.append(dict(g,reason='incomplete source projection'));continue
        safe.append(g)
    rec=reconcile(safe,d['order']);gs=rec['selected'];reject=errors+[dict(g,reason=g.get('Reason') or 'response mapping: '+g['Validation_Status']) for g in rec['unresolved']]+[dict(g,reason='competing source coverage or order') for g in rec['conflicts'] if g['Disposition']!='selected'];hsp=[];vsp={};last={};order=d['order']
    for i,g in enumerate(gs,1):
        a,b=g['Han_Start'],g['Han_End'];require(d['raw'][a:b]==g['Han_Text'],'invalid final Han projection');require(' '.join(d['vi'][k]['text_original'][x:y] for k,x,y in g['VI_Char_Spans'])==g['Vietnamese_Text'],'invalid final Vietnamese projection');cap=g['Cap'];start=min((order[k],x) for k,x,y in g['VI_Char_Spans']);end=max((order[k],y) for k,x,y in g['VI_Char_Spans']);require(cap not in last or (a>=last[cap][0] and start>=last[cap][1]),'nonmonotonic selection');last[cap]=b,end;hsp.append((a,b));g['Pair_ID']=f'P{i:07}';g['Label_Target']='UNKNOWN'
        for k,x,y in g['VI_Char_Spans']:vsp.setdefault(k,[]).append((x,y))
    uh=[];uv=[]
    for s in d['ss']:
        for a,b in complement(*s['global_raw_span'],hsp):uh.append(dict(cap=s['cap'],id_zh=s['id_zh'],pages=[s['page_start'],s['page_end']],span=[a,b],text=d['raw'][a:b],mapping_status=[d['ms'][s['cap'],p]['Mapping_Status'] for p in range(s['page_start'],s['page_end']+1)],reason='no selected source-backed pair'))
    for k,v in d['vi'].items():
        for a,b in complement(0,len(v['text_original']),vsp.get(k,[])):uv.append(dict(cap=v['cap'],id_vi=k,source=v['source'],span=[a,b],text=v['text_original'][a:b],reason='no selected source-backed pair'))
    return gs,rows,reject,uh,uv,states,dict(attempts=len(attempts),successful_responses=sum(a['status']=='success' for a in attempts),offline_cache_misses=sum(a['status']=='offline_cache_miss' for a in attempts),source_mapping_errors=len(errors),response_groups=len(rows),fully_mapped_response_groups=sum(g['Validation_Status']=='mapped' for g in rows),partial_response_groups=sum(g['Validation_Status']=='partial_viet' for g in rows),duplicates=rec['duplicates'],conflict_edges=rec['conflict_edges'])
