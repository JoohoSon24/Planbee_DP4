"""Plan Bee contextual work demo. Mock comparison + optional actual LLM probes.
python run_demo4.py [--live-check]
All DB work uses memory. Live probes use the configured provider/model and no plan writes.
"""
import argparse,json
from pathlib import Path
from app import store,sim,hive
from app.llm import LiveLLM
OUT=Path(__file__).resolve().parent/'eval'/'demo4_planbee'

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--live-check',action='store_true');a=ap.parse_args();OUT.mkdir(parents=True,exist_ok=True)
    comparisons=[]
    # Force the comparison to Mock even if the user's .env defaults to Live.
    import os
    previous=os.environ.get('PLANBEE_LLM');os.environ['PLANBEE_LLM']='mock'
    try:
        for pref in ['fast','fair']:
            state,metrics=sim.simulate('demo4_planbee',pref=pref)
            comparisons.append(dict(pref=pref,metrics=metrics,state=state))
            print(pref,'确认'.replace('确认','확인'),metrics['confirms'],'부담 분산',metrics['fairness']['variance'],flush=True)
    finally:
        if previous is None:os.environ.pop('PLANBEE_LLM',None)
        else:os.environ['PLANBEE_LLM']=previous
    (OUT/'comparison.json').write_text(json.dumps(comparisons,ensure_ascii=False,indent=2))
    lines=['# 데모 4 · 업무 맥락·휴가·공정성','','모든 숫자·분담·과거 작업량은 프로젝트를 소재로 만든 시연용 값이다. Mock 두 조건은 사건·카드·경력·업무량을 고정하고 후보 선택 기준만 바꿨다.','', '|기준|담당자|사람 확인|부담 분산|부담 최대-최소|제출일 초과|','|---|---|---:|---:|---:|---:|']
    for r in comparisons:
        m=r['metrics'];who=r['state']['resolved'][0]['body'].split('가 ')[0].split('이 ')[0]
        lines.append(f"|{r['pref']}|{who}|{m['confirms']}|{m['fairness']['variance']}|{m['fairness']['range']}|{m['past_deadline']}|")
    (OUT/'RESULTS.md').write_text('\n'.join(lines)+'\n')
    if not a.live_check:return
    old=store.DEMO;store.use_demo('demo4_planbee');engine=store.make_engine('sqlite://');out=[]
    try:
        llm=LiveLLM()
        with store.make_session_factory(engine)() as db:
            store.reset(db);b=store.board(db)
            for tid in ['resume','signoff']:
                before=llm.failures;t=b.tasks[tid];ans=llm.split(b.people[t.who],t,.5)
                out.append(dict(kind='split',task=tid,decision=getattr(llm,'last_split_decision',{}),split=ans.model_dump() if ans else None,failures=llm.failures-before))
                (OUT/'live_checks.json').write_text(json.dumps(out,ensure_ascii=False,indent=2));print('Live split',tid,'failures',out[-1]['failures'],flush=True)
            for pid in ['jm','jh']:
                before=llm.failures;cd=store.card(db,pid);ans=llm.interpret_card(b.people[pid],cd.note)
                out.append(dict(kind='card',person=pid,draft=ans.model_dump(),failures=llm.failures-before))
                (OUT/'live_checks.json').write_text(json.dumps(out,ensure_ascii=False,indent=2));print('Live card',pid,'failures',out[-1]['failures'],flush=True)
        (OUT/'live_meta.json').write_text(json.dumps(dict(model=llm.model,calls=llm.calls,failures=llm.failures,applied=False),ensure_ascii=False,indent=2))
    finally:engine.dispose();store.use_demo(old)
if __name__=='__main__':main()
