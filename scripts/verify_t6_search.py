"""Repeat isolated T6 generation/discussion checks; --live uses configured paid LLM.
Never selects a PM plan or approves for a person. Production DB is untouched.
"""
from pathlib import Path
import argparse,json,os,sys
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--repeats',type=int,default=3)
    args=parser.parse_args()
    os.environ['PLANBEE_LLM']='live' if args.live else 'mock'
    os.environ['PLANBEE_RUN_ORIGIN']='t6_search_validation'
    from app import store,llm,hive
    from app.candidates import engine
    from app.candidates.generator import enumerate_plans
    store.use_demo('m4_t6_game_demo')
    results=[]
    for i in range(args.repeats):
        dbengine=store.make_engine('sqlite://')
        with store.make_session_factory(dbengine)() as db:
            store.reset(db);llm.set_llm(None)
            cfg=engine.Settings(seed=17+i)
            b=store.board(db);hive.schedule(b)
            candidates,stats=enumerate_plans(b,{'task':'Q2'},[],cfg)
            assert any(any(a['who']=='ben' for a in c['allocations']) for c in candidates),stats
            assert any(any(a['who']=='sam' for a in c['allocations']) for c in candidates),stats
            issue=store.load_yaml('feed.yaml')['issue']['records'][0]['text']
            run=engine.start(db,'Q2',issue,cfg,reporter='person:zoe')
            for _ in range(100):
                if run.status!='running':break
                engine.advance(db,run)
                print(json.dumps(dict(progress=run.step,round=run.ctx.get('round'),calls=run.ctx['llm_budget']['used']),ensure_ascii=False),flush=True)
            result=dict(iteration=i+1,mode=os.environ['PLANBEE_LLM'],status=run.status,termination=run.ctx.get('termination'),
                rounds=run.ctx.get('round'),budget=run.ctx['llm_budget'],generation=run.ctx.get('generation'),
                final_candidates=run.ctx.get('final_candidates',[]),deterministic_search=stats,transcript=run.ctx.get('transcript_file'))
            results.append(result);print(json.dumps(result,ensure_ascii=False),flush=True)
            db.commit()
        dbengine.dispose()
    target=store.ROOT/'eval'/'t6_search';target.mkdir(parents=True,exist_ok=True)
    file=target/(datetime.now().strftime('%Y-%m-%d_%H-%M-%S')+('_live' if args.live else '_mock')+'.json')
    file.write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
    if any(r['status']!='awaiting_pm_selection' or not r['final_candidates'] for r in results):raise SystemExit(1)

if __name__=='__main__':main()
