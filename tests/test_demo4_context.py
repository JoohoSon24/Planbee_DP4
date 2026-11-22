"""Task semantics, reviewed natural-language cards, availability and burden fairness."""
import os,json
os.environ['PLANBEE_DB']='sqlite://'
os.environ['PLANBEE_LLM']='mock'
from pathlib import Path
from types import SimpleNamespace as NS
import httpx,pytest
from sqlalchemy import create_engine,text,select
from fastapi.testclient import TestClient
from app import api,hive,sim,store
from app.models import Task,Card,Record
from app.llm import LiveLLM,MockLLM
from app.policies import CardPolicy


def live_reply(args,seen):
    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200,json={'choices':[{'message':{'tool_calls':[{'function':{'arguments':json.dumps(args)}}]}}]})
    return LiveLLM(client=httpx.Client(transport=httpx.MockTransport(handler)))

@pytest.fixture
def board():
    old=store.DEMO;store.use_demo('demo4_planbee');engine=store.make_engine('sqlite://')
    with store.make_session_factory(engine)() as db:
        store.reset(db);db.commit();yield db,store.board(db)
    engine.dispose();store.use_demo(old)

def test_llm_can_decline_indivisible_work_with_context(board):
    _,b=board;seen=[];llm=live_reply({'splittable':False,'rationale':'서명과 승인 기록은 같은 트랜잭션이어야 함'},seen)
    assert llm.split(b.people['yk'],b.tasks['signoff'],.5) is None
    assert '공유 키' in seen[0]['messages'][1]['content']
    assert llm.last_split_decision['splittable'] is False

def test_live_failure_does_not_force_cut_contextual_task(board):
    _,b=board;llm=LiveLLM(client=httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(500))))
    assert llm.split(b.people['yk'],b.tasks['resume'],.5) is None
    assert llm.failures==1

def test_context_and_acceptance_criteria_reach_llm(board):
    _,b=board;seen=[]
    llm=live_reply({'splittable':True,'rationale':'조회는 독립','piece':{'title':'조회','days':.5,'tag':'API','context':{'acceptance':'상태 쓰기 없음'}}},seen)
    ans=llm.split(b.people['yk'],b.tasks['resume'],.5)
    assert ans.piece.context['acceptance']=='상태 쓰기 없음'
    assert 'app/workflow.py' in seen[0]['messages'][1]['content'] and '통합 위험' in seen[0]['messages'][1]['content']

def test_card_calendar_arithmetic_is_code_not_model_guess():
    p=CardPolicy.model_validate({'source_note':'11/19~20 휴가','unavailable':[{'start':5,'end':6,'start_date':'2026-11-19','end_date_exclusive':'2026-11-21'}]})
    assert (p.unavailable[0].start,p.unavailable[0].end)==(3,5)
    assert not p.approved

def test_busy_does_not_imply_numeric_limit(board):
    _,b=board;seen=[];llm=live_reply({'source_note':'ignored','busy':True,'weekly_limit':None,'approved':True},seen)
    p=llm.interpret_card(b.people['jh'],'나 너무 바쁨')
    assert p.source_note=='나 너무 바쁨' and p.busy and p.weekly_limit is None and not p.approved
    assert '임의로 정하지' in seen[0]['messages'][1]['content']

def test_confirmed_time_off_shifts_jobs_and_reduces_capacity(board):
    _,b=board;st=b.clone();t=st.tasks['metrics'];t.kind='new';t.s0=3;t.d=1
    hive.schedule(st)
    assert t.s==5 and hive.capacity(st,'jm')==3
    assert any(w['task']=='metrics' for w in hive.gate(st)['warnings'])

def test_unapproved_time_off_has_no_scheduling_authority(board):
    _,b=board;st=b.clone();st.extra['policies']['jm']['approved']=False
    assert hive.capacity(st,'jm')==5

def test_fair_selection_uses_prior_burden_without_breaking_deadline():
    fast,mf=sim.simulate('demo4_planbee',pref='fast');fair,mb=sim.simulate('demo4_planbee',pref='fair')
    assert '주호' in fast['resolved'][0]['body'] and '정민' in fair['resolved'][0]['body']
    assert mf['past_deadline']==mb['past_deadline']==0
    assert mb['fairness']['variance']<mf['fairness']['variance']
    assert mb['fairness']['totals']=={'yk':6,'jm':3.5,'jh':10,'nj':4.5}
    assert mf['confirms']>=2 and mb['confirms']==1

def test_schema_additions_preserve_existing_rows(tmp_path):
    path=tmp_path/'old.db';old=store.DEMO;store.use_demo('demo3_cards')
    eng=store.make_engine('sqlite:///'+str(path));factory=store.make_session_factory(eng)
    with factory() as db:store.reset(db);db.commit()
    with eng.begin() as conn:
        conn.execute(text('ALTER TABLE task DROP COLUMN context'));conn.execute(text('ALTER TABLE card DROP COLUMN policy'))
    eng.dispose();eng=store.make_engine('sqlite:///'+str(path))
    with store.make_session_factory(eng)() as db:
        assert db.get(Task,'feature').title=='기능 구현' and db.get(Task,'feature').context=={}
        assert db.get(Card,'mia').policy=={}
    eng.dispose();store.use_demo(old)

def test_review_workflow_context_endpoint_and_demo_advance(monkeypatch):
    old=store.DEMO;store.use_demo('demo4_planbee');eng=store.make_engine('sqlite://');factory=store.make_session_factory(eng)
    monkeypatch.setattr(api,'SessionLocal',factory)
    try:
        with TestClient(api.app) as c:
            assert c.get('/state').json()['tasks']['resume']['context']['deliverable']
            x=c.post('/tasks/signoff/analyze-split',json={'days':.5}).json()
            assert x['mode']=='mock' and x['split'] is None and not x['applied']
            note=c.get('/cards').json()[1]['note']
            draft=c.post('/people/jm/card/interpret',json={'note':note}).json()['draft']
            assert not draft['approved']
            assert c.put('/people/jm/card',json={'policy':draft}).status_code==422
            draft['approved']=True
            assert c.put('/people/jm/card',json={'policy':draft}).status_code==200
            assert c.put('/people/jm/card',json={'note':'다음주 휴가인지 아직 모름'}).status_code==200
            from app.policies import needs_review
            with factory() as db:assert needs_review(store.card(db,'jm'))
            # Reset preserves the reviewed fixture, then execute the actual UI advance endpoint.
            c.post('/demo/select',json={'demo':'demo4_planbee'})
            r=c.post('/demo/advance',json={'auto_confirm':True})
            assert r.status_code==200,r.text
            assert '정민' in r.json()['resolved'][0]['body']
    finally:eng.dispose();store.use_demo(old)
