"""Unmodified endpoint contracts, per-payload cache, and existing Stage 04 mapping."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import os
import re
import time

import requests
from preprocess import ROOT, fingerprint, viet_t1, write_json
from benchmark_alignment_api import URL as ALIGN
from benchmark_alignment_api_final import CONFIRMED, aggregate, project
from test_separate_api import URL as SEPARATE, analyze, parse_sentences


def retry_seconds(value):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        try: return max(0, (parsedate_to_datetime(value)-datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError): return None


class Client:
    def __init__(self, folder, cfg, live):
        self.folder,self.cfg,self.live = folder,cfg,live
        self.token = re.sub(r'^bearer\s+', '',os.getenv('SINONOM_TOKEN','').strip(),flags=re.I).strip()
        self.session = requests.Session()
        self.session.headers.update({'Authorization': f'Bearer {self.token}', 'Accept':'application/json',
            'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/138.0.0.0 Safari/537.36'})
        self.cache=folder/'cache'; self.cache.mkdir(exist_ok=True)
        self.last=0.; self.halt=None; self.attempts=0; self.hits=0
        self.seeds={}
        path=ROOT/'pipeline/artifacts/separate_pilot_cap01/results.json'
        if path.is_file():
            for row in json.loads(path.read_text(encoding='utf-8'))['cases']:
                if row['status']=='ok': self.seeds[fingerprint([SEPARATE,row['payload']])]=row['raw_response']

    def close(self): self.session.close()

    def call(self, url, payload):
        key=fingerprint([url,payload]); file=self.cache/(key+'.json')
        if file.is_file() or key in self.seeds:
            self.hits+=1
            return (json.loads(file.read_text(encoding='utf-8')) if file.is_file() else
                    {'status':'ok','body':json.loads(self.seeds[key]),'origin':'prior_separate','key':key})
        if self.halt or not self.live or not self.token:
            return {'status':self.halt or ('offline' if not self.live else 'no_token'),'key':key}
        for i in range(self.cfg['api_retries']+1):
            time.sleep(max(0,self.cfg['api_delay']-(time.monotonic()-self.last)))
            t=time.monotonic(); self.attempts+=1
            result={'endpoint':url,'key':key,'payload':payload,'attempt':i+1}
            try:
                r=self.session.post(url,json=payload,timeout=(10,self.cfg['api_timeout']),allow_redirects=False)
                raw=r.text.replace(self.token,'[REDACTED]')
                try: body=json.loads(raw)
                except ValueError: body=None
                code=str(body.get('code')) if isinstance(body,dict) else ''
                headers={k.lower():v.replace(self.token,'[REDACTED]') for k,v in r.headers.items()
                         if re.search('rate.?limit|quota|retry-after|^x-request-id$',k,re.I)}
                result.update(http=r.status_code,api_code=code,headers=headers,raw_response=raw,body=body)
                if r.status_code in (401,403,429) or code in {'000401','000403','000429','401','403','429'}:
                    self.halt='authorization_or_rate_limit'
                if any('remaining' in k and v.strip()=='0' for k,v in headers.items()): self.halt='quota_exhausted'
                seconds=retry_seconds(headers.get('retry-after'))
                if seconds is not None and r.status_code in (429,503):
                    self.halt='server_retry_after'
                    result['retry_after_seconds']=seconds
                status=('ok' if r.status_code==200 and isinstance(body,dict) and body.get('is_success') is True else
                        'transient' if r.status_code in (408,500,502,503,504) else 'api_error')
            except requests.RequestException as e:
                result['exception']=type(e).__name__; status='transport_error'
            self.last=time.monotonic()
            result.update(status=status,latency_ms=round(1000*(self.last-t)))
            with (self.folder/'requests.jsonl').open('a',encoding='utf-8') as f:
                f.write(json.dumps(result,ensure_ascii=False)+'\n')
            print(f"  {url.rsplit('/',1)[-1]} #{self.attempts} {status} {result.get('api_code','')}",flush=True)
            if status=='ok':
                write_json(file,result); return result
            if self.halt or status not in ('transient','transport_error'): break
            if i<self.cfg['api_retries']: time.sleep(1+i)
        return result

    def separate(self, text):
        payload={'text':text,'ocr_id':1,'genre':self.cfg['genre'],'punctuation_group':'all'}
        request=self.call(SEPARATE,payload)
        if request['status']=='ok':
            try:
                parts,lines=parse_sentences(request['body'])
                metrics=analyze(text,0,parts,lines)
                if metrics['projected_sentences'] is not None:
                    return request['key'],metrics['projected_sentences'],'ok'
                return request['key'],[],'content_mismatch'
            except (TypeError,ValueError,KeyError): return request['key'],[],'parse_error'
        return request['key'],[],request['status']

    def align(self, key, raw, spans, viet):
        if not viet or not spans: return {'status':'unmatched','groups':[]}
        source={v['id']:v['text_original'] for v in viet}
        fragments=[]
        for vi,s in source.items():
            value,offsets=viet_t1(s,CONFIRMED.get(vi,()))
            if value: fragments.append({'id':vi,'vi_id':vi,'text':value,'offsets':[a for a,_ in offsets],
                                         'offset_ranges':offsets})
        payload={'han':'\n'.join(' '.join(raw[a:b].split()) for a,b in spans),
                 'vi':'\n'.join(f['text'] for f in fragments)}
        job={'id':key,'strategy':'T1','h':spans,'v':[f['id'] for f in fragments],'payload':payload,'fragments':fragments}
        req=self.call(ALIGN,payload)
        result={'status':req['status'],'request_key':req['key'],'input':job,'groups':[]}
        if req['status']=='ok':
            body=req['body']
            if not isinstance(body.get('data'),dict) or not isinstance(body['data'].get('result'),list):
                result['status']='parse_error'; return result
            try:
                # Legacy projection uses offsets[a] and offsets[b-1]+1. Use its
                # row resolution, then adjust endpoints using normalized grapheme spans.
                from benchmark_alignment_api_final import union_parts, full_segment
                entry={'id':req['key'],'raw_response':req['raw_response'],'status':'success'}
                rows=project(job,entry,raw,source)
                frags={f['id']:f for f in fragments}
                for row in rows:
                    payload_parts=row['VI_Payload_Spans']
                    parts=union_parts([[vi,frags[vi]['offset_ranges'][a][0],frags[vi]['offset_ranges'][b-1][1]]
                                       for vi,a,b in payload_parts],source)
                    row.update(VI_Char_Spans=parts,Vietnamese_Text=' '.join(source[k][a:b] for k,a,b in parts))
                    if row['Validation_Status'] in ('mapped','partial_viet'):
                        row['Validation_Status']='mapped' if all(full_segment(parts,k,source) for k in row['VI_IDs']) else 'partial_viet'
                result['groups']=aggregate(rows,raw,source)
            except (ValueError,TypeError,KeyError,IndexError) as e:
                result.update(status='mapping_error',error=type(e).__name__)
        return result
