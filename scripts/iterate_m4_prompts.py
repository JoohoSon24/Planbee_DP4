"""Run a frozen prompt version against all five M4 issues, with bounded real calls.

No PM selection or personal confirmation is simulated in Live experiments.
"""
from pathlib import Path
import argparse
from datetime import datetime
from hashlib import sha256
import json
import os
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
p=argparse.ArgumentParser();p.add_argument('--version',type=Path,required=True);p.add_argument('--llm',choices=['mock','live'],required=True)
p.add_argument('--scenario',action='append');p.add_argument('--max-calls',type=int,default=40)
p.add_argument('--seed',type=int,default=17);p.add_argument('--rounds',type=int,default=2);p.add_argument('--candidate-limit',type=int,default=4)
a=p.parse_args()
os.environ['PLANBEE_LLM']=a.llm;os.environ['PLANBEE_RUN_ORIGIN']='prompt_iteration'
os.environ.setdefault('PLANBEE_RUNS_DIR',str(ROOT/'runs'/'v2'))
from app import store,llm
from app.candidates import engine
from scripts.check_m4_results import checks

version=a.version.resolve();manifest=json.loads((version/'manifest.json').read_text())
def verify():
    for rel,expected in manifest['prompt_hashes'].items():
        if sha256((ROOT/'prompts'/rel).read_bytes()).hexdigest()!=expected:raise RuntimeError('프롬프트 변경됨: 새 버전을 snapshot하세요: '+rel)
    for rel,expected in manifest.get('code_hashes',{}).items():
        if sha256((ROOT/rel).read_bytes()).hexdigest()!=expected:raise RuntimeError('코드 변경됨: 새 버전을 snapshot하세요: '+rel)

stamp=datetime.now().astimezone().strftime('%Y-%m-%d_%H-%M-%S_%f')
out=version/'experiments'/(stamp+'_'+a.llm);out.mkdir(parents=True,exist_ok=False)
results=[]
for sid in a.scenario or store.service_demos():
    verify();store.use_demo(sid);dbengine=store.make_engine('sqlite://');started=time.monotonic()
    with store.make_session_factory(dbengine)() as db:
        store.reset(db);f=store.load_yaml('feed.yaml')['issue'];adapter=llm.get_llm()
        print('START',sid,a.llm,flush=True)
        r=engine.start(db,f['task'],f['records'][0]['text'],engine.Settings(seed=a.seed,max_calls=a.max_calls,max_seconds=600,max_rounds=a.rounds,raw_limit=200,candidate_limit=a.candidate_limit,shortlist_limit=min(a.candidate_limit,6)))
        for step in range(80):
            if r.status!='running':break
            engine.advance(db,r)
            print('STEP',sid,r.step,r.status,r.ctx['llm_budget']['used'],flush=True)
        db.commit();public=engine.response(r)
        report=dict(scenario=sid,seed=a.seed,version=manifest['version'],llm_mode=a.llm,model=getattr(adapter,'model',None),duration_seconds=round(time.monotonic()-started,2),
            logical_llm_calls=getattr(adapter,'calls',None),output_failures=getattr(adapter,'failures',None),schema_repairs=sum(e['response']=='SCHEMA_REPAIR' for e in r.ctx.get('public_history',[])),
            status=r.status,termination=r.ctx.get('termination'),llm_budget=r.ctx['llm_budget'],transcript_file=r.ctx.get('transcript_file'),
            prompt_hashes=r.ctx['prompt_hashes'],model_error=r.ctx.get('model_error'),checks=checks(sid,public))
        (out/(sid+'.json')).write_text(json.dumps(dict(report=report,public_run=public),ensure_ascii=False,indent=2),encoding='utf-8')
        results.append(report);(out/'summary.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        print('RESULT',json.dumps({k:v for k,v in report.items() if k!='prompt_hashes'},ensure_ascii=False),flush=True)
    dbengine.dispose()
print('EXPERIMENT',out,flush=True)
