"""In-memory runnable swap / parallel split / three-way cycle / rejection examples.
python run_bundle_demo.py --case all
"""
import argparse
import json
from pathlib import Path
from sqlalchemy import delete, select
from app import bundles, hive, store, workflow
from app.models import Confirmation, Handoff, Task

def setup_board(db,mode='swap'):
    store.use_demo('demo3_cards');store.reset(db)
    db.execute(delete(Handoff));db.execute(delete(Task));store.set_meta(db,'now',0)
    for pid in ['mia','jun','sol']:store.card(db,pid).auto_days=2
    def task(id,who,d,s0=0):
        return Task(id=id,who=who,title=id,s0=s0,s=s0,d=d,base=d,plan=d,role='테스트' if who=='ara' else '개발',tag='테스트' if who=='ara' else '개발',oi=len(db.new))
    ts=[task('x','mia',2),task('a_other','mia',3,2)]
    if mode=='swap':ts += [task('y','jun',2),task('b_other','jun',3,2),task('qa','ara',1,2)];at=2
    else:ts += [task('b_other','jun',3),task('c_other','sol',3),task('qa','ara',1,4)];at=4
    db.add_all(ts);db.flush()
    db.add(Handoff(id='h',from_task='x',to_task='qa',title='완료본',what='빌드',t=at,oi=0));db.flush()
    hive.schedule(store.board(db));db.commit()


def run_case(case):
    old=store.DEMO;engine=store.make_engine("sqlite://")
    try:
        with store.make_session_factory(engine)() as db:
            setup_board(db,"split" if case=="split" else "swap")
            if case=="chain":
                db.add(Task(id="z",who="sol",title="z",s0=0,s=0,d=2,base=2,plan=2,role="개발",tag="개발",oi=9));db.flush()
            operations=([dict(task="x",to="jun",amount=.5),dict(task="x",to="sol",amount=.5)] if case=="split" else
                        [dict(task="x",to="jun"),dict(task="y",to="sol"),dict(task="z",to="mia")] if case=="chain" else
                        [dict(task="x",to="jun"),dict(task="y",to="mia")])
            before=store.state_json(db)
            run=bundles.propose(db,operations);db.commit()
            proposed=store.state_json(db)
            snapshots=[]
            for i,cid in enumerate(run.ctx['waiting_for']):
                workflow.confirm(db,cid,ok=not(case=="reject" and i==1));db.commit()
                snapshots.append(store.state_json(db))
                if run.status=="done":break
            after=store.state_json(db)
            return dict(case=case,transfers=operations,result=bundles.view(run),before=before,proposed=proposed,confirmation_steps=snapshots,after=after)
    finally:
        engine.dispose();store.use_demo(old)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--case',choices=['swap','split','chain','reject','all'],default='all');args=ap.parse_args()
    out=Path(__file__).resolve().parent/'eval'/'bundles';out.mkdir(parents=True,exist_ok=True)
    cases=['swap','split','chain','reject'] if args.case=='all' else [args.case];results=[]
    for case in cases:
        r=run_case(case);results.append(r)
        (out/(case+'.json')).write_text(json.dumps(r,ensure_ascii=False,indent=2))
        print(case,r['result']['outcome'],'사람 확인',len(r['result']['waiting_for']),'전체 규칙 검사',r['after']['gate']['ok'])
    if args.case=='all':
        (out/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
        lines=['# 묶음 이동 실행 결과','','메모리 DB에서 실제 구현을 실행한 결과. 자동 제안 생성이나 Live LLM 비교가 아니다.','', '|사례|결과|사람 확인|규칙 통과|','|---|---|---:|---|']
        for r in results:lines.append(f"|{r['case']}|{r['result']['outcome']}|{len(r['result']['waiting_for'])}|{r['after']['gate']['ok']}|")
        (out/'RESULTS.md').write_text('\n'.join(lines)+'\n')
if __name__=='__main__':main()
