"""Browser-facing demo selection, all feeds and complete scenario documentation."""
import os
os.environ['PLANBEE_LLM']='mock'
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from app import api, store, llm
from app.models import Run


@pytest.fixture
def client(tmp_path, monkeypatch):
    old=store.DEMO
    monkeypatch.setenv('PLANBEE_RUNS_DIR',str(tmp_path/'runs'))
    monkeypatch.setenv('PLANBEE_LLM','mock')
    engine=store.make_engine('sqlite://');factory=store.make_session_factory(engine)
    monkeypatch.setattr(api,'SessionLocal',factory)
    with TestClient(api.app) as c:yield c,factory
    store.use_demo(old);engine.dispose()


def step(c, auto=True):
    response=c.post('/demo/advance',json={'auto_confirm':auto})
    assert response.status_code==200,response.text
    return response.json()


@pytest.mark.parametrize('demo', [d for d in store.demos() if d.startswith('demo')])
def test_every_demo_selects_runs_to_completion_and_has_full_docs(client,demo):
    c,factory=client
    response=c.post('/demo/select',json={'demo':demo});assert response.status_code==200,response.text
    state=response.json()
    assert state['feed_label'] and state['demo']['id']==demo
    assert state['gate']['ok']
    doc=c.get(f'/demos/{demo}/scenario');assert doc.status_code==200
    text=doc.text
    for section in ['초기 milestone 보드','각자의 위임카드','각 Task 세부 description','브라우저 시연 단계']:
        assert section in text
    for tid in state['tasks']:assert f'`{tid}`' in text
    for person in state['people']:assert f"`{person['id']}`" in text
    visual=c.get(f'/demos/{demo}/scenario-data');assert visual.status_code==200
    initial=visual.json()
    assert initial['gate']['ok'] and len(initial['tasks'])==len(state['tasks'])
    assert all('start_label' in t and 'context' in t for t in initial['tasks'])
    assert c.get('/state').json()['demo']['id']==demo
    executed=0
    for _ in range(15):
        if state['phase']=='end':break
        asks=[a for a in state['asks'] if a['open']]
        if asks:
            ask=asks[0]
            if ask['grants']:
                r=c.post(f"/asks/{ask['id']}/grant",json={'key':ask['grants'][0]['key']})
            else:r=c.post(f"/handoffs/{ask['hid']}/reagree",json={'auto_confirm':True})
            assert r.status_code==200,r.text
            state=r.json()
        else:
            assert state['feed_label'],state
            state=step(c);executed+=1
    assert executed and state['phase']=='end'
    assert not state['waiting'] and not state['pending_confirms']
    assert state['gate']['ok'] and not state['gate']['warnings']
    from app.runlogs import directory
    with factory() as db:
        for run in db.scalars(select(Run)):
            assert (directory()/run.ctx['transcript_file']).is_file()


def test_complex_discussion_is_real_five_rounds_and_versioned(client):
    c,_=client;c.post('/demo/select',json={'demo':'demo5_release'})
    state=step(c);d=state['negotiations'][0]['discussion']
    assert d['termination']=='agreement' and d['version']==3
    assert state['negotiations'][0]['round']==5
    assert {e['requester'] for e in d['history'] if e['response']=='REJECT'}=={'bora','chan'}
    assert {a['who'] for a in d['proposal']}=={'bora','chan'}


def test_complex_failure_leaves_board_then_atomically_splits_and_swaps(client):
    c,factory=client;original=c.post('/demo/select',json={'demo':'demo6_cross_region'}).json()
    failed=step(c);d=failed['negotiations'][0]['discussion']
    assert d['termination']=='max_rounds'
    assert any(e['response']=='BLOCKED' and '데드라인' in e['reason'] for e in d['history'])
    assert failed['tasks']==original['tasks']
    waiting=step(c,False)
    assert waiting['pending_confirms'] and waiting['tasks']==original['tasks']
    for cf in waiting['pending_confirms']:
        r=c.post(f"/confirmations/{cf['id']}",json={'ok':True});assert r.status_code==200,r.text
        state=r.json()
    assert state['phase']=='qa' and state['tasks']['ledger']['kind']=='milestone'
    assert state['tasks']['ops_a']['who']=='olin' and state['tasks']['ops_b']['who']=='noel'
    assert step(c)['phase']=='end'


def test_bundle_browser_rejection_returns_to_end_without_partial_swap(client):
    c,_=client;initial=c.post('/demo/select',json={'demo':'demo4_bundles'}).json()
    state=step(c,False)
    assert state['tasks']==initial['tasks'] and state['pending_confirms']
    response=c.post(f"/confirmations/{state['pending_confirms'][0]['id']}",json={'ok':False})
    assert response.status_code==200,response.text
    state=response.json();assert state['phase']=='end' and not state['pending_confirms']
    assert state['tasks']==initial['tasks']


def test_all_switches_reset_and_unknown_selection_does_not_change_current(client):
    c,_=client
    for entry in c.get('/demos').json()['catalog']:
        state=c.post('/demo/select',json={'demo':entry['id']}).json()
        assert state['demo']['title']==entry['title']
        assert c.get(entry['scenario_url']).status_code==200
    before=c.get('/state').json()['demo']['id']
    assert c.post('/demo/select',json={'demo':'unknown'}).status_code==404
    assert c.get('/state').json()['demo']['id']==before


def test_round_budget_can_be_increased_to_fifteen_or_fifty(client):
    c,_=client
    c.post('/demo/select',json={'demo':'demo5_release'})
    assert c.get('/state').json()['max_rounds']==15
    for n in [15,30,50]:
        assert c.put('/rules/rounds',json={'max':n}).status_code==200
        assert c.get('/state').json()['max_rounds']==n
    for n in [0,51]:assert c.put('/rules/rounds',json={'max':n}).status_code==422


def test_increased_budget_resumes_same_live_protocol_run_and_log(client,monkeypatch):
    from app.llm import MockLLM, Reestimate, DiscussionReply
    c,factory=client
    c.post('/demo/select',json={'demo':'demo5_release'})
    class Agent(MockLLM):
        repair=False
        def reestimate(self,person,records,tasks,model=None):
            return Reestimate(task='contract',days=4,basis='실제 추가 검증 작업')
        def split(self,person,task,piece_hint,model=None,feedback=None):
            from app.llm import Split,Piece,Part
            return Split(piece=Piece(title='계약 검증',days=2,tag='계약',what='계약 검증 전체'),keep=Part(title='상태 전이 코어',days=2))
        def discuss(self,person,card,context):
            if not self.repair:return DiscussionReply(action='PASS',reason='아직 대안 없음')
            if context['mode']=='revise':
                return DiscussionReply(action='COUNTER',proposal_scope='whole_task',reason='원 업무 전체 분해',allocations=[
                    dict(who='hana',title='코어',what='상태 전이 구현',days=2,effort=2,key='core'),
                    dict(who='bora',title='정상 계약',what='정상 검증',days=1,effort=1,key='normal',depends_on=['core']),
                    dict(who='chan',title='실패 계약',what='실패 검증',days=1,effort=1,key='failure',depends_on=['core'])])
            return DiscussionReply(action='ACCEPT',reason='전체 변경 동의')
    adapter=Agent();llm.set_llm(adapter)
    try:
        c.put('/rules/rounds',json={'max':2})
        failed=step(c);run=failed['negotiations'][0]
        assert run['status']=='waiting_pm'
        assert c.post(f"/negotiations/{run['id']}/retry").status_code==409
        c.put('/rules/rounds',json={'max':15});adapter.repair=True
        response=c.post(f"/negotiations/{run['id']}/retry",json={'auto_confirm':True})
        assert response.status_code==200,response.text
        state=response.json();resumed=state['negotiations'][0]
        assert resumed['status']=='done' and resumed['transcript_file']==run['transcript_file']
        assert len(state['negotiations'])==1 and state['tasks']['contract']['kind']=='milestone'
        assert state['gate']['ok'] and not state['gate']['warnings']
        assert not [a for a in state['asks'] if a['open']]
    finally:llm.set_llm(None)


def test_historical_haru_approval_is_blocked_by_hive_before_fairness(client, monkeypatch):
    """Reproduce the old 2026-11-19 Run's M4 owner without changing its log/DB."""
    from app.models import Task
    from app.llm import MockLLM
    c,factory=client
    c.post('/demo/select',json={'demo':'demo5_release'})
    with factory() as db:
        db.get(Task,'release_gate').who='haru'
        db.commit()
    class Spy(MockLLM):
        calls=0
        def discuss(self,*args,**kwargs):
            self.calls+=1
            return super().discuss(*args,**kwargs)
    spy=Spy();llm.set_llm(spy)
    try:
        state=step(c)
        assert not state['gate']['ok']
        assert state['tasks']['release_gate']['s']==5
        assert state['hand']['final_ready']['state']=='risk'
        assert state['hand']['final_ready']['t']==4.5
        run=state['negotiations'][0]
        assert run['status']=='waiting_pm' and run['discussion'] is None
        assert not state['resolved'] and spy.calls==0
        detail=c.get(f"/negotiations/{run['id']}").json()
        gate=detail['constraint_evaluation']
        assert not gate['ok'] and gate['adjustments'][0]['who']=='haru'
        assert any(v['code']=='HANDOFF_LATE' and v['hid']=='final_ready' for v in gate['violations'])
        ask=next(a for a in state['asks'] if a['open'])
        assert any('하루' in reason and '승인' in reason for reason in ask['why'])
        from app.runlogs import directory
        transcript=(directory()/run['transcript_file']).read_text()
        assert '제약 평가 · 하루 · M4 릴리스 승인' in transcript
        assert 'MILESTONE_AVAILABILITY' in transcript and 'HANDOFF_LATE' in transcript
    finally:llm.set_llm(None)


def test_capacity_violation_without_late_handoff_is_blocked_not_success(client):
    from app.models import Card
    c,factory=client
    c.post('/demo/select',json={'demo':'demo5_release'})
    with factory() as db:
        cd=db.get(Card,'haru')
        cd.policy={**cd.policy,'weekly_limit':0}
        db.commit()
    state=step(c)
    assert not state['gate']['ok']
    assert state['negotiations'][0]['status']=='blocked'
    assert not state['resolved']
    assert '검증 실패' in state['narr']


def test_workflow_stages_and_demo_steps_are_separate_and_transcript_is_sectioned(client):
    c,factory=client
    initial=c.post('/demo/select',json={'demo':'demo5_release'}).json()
    assert initial['workflow_progress']['status']=='ready'
    state=step(c)
    progress=state['workflow_progress']
    assert progress['current']['id']=='03'
    assert {s['id'] for s in progress['visited']}=={'01','03'}  # No deadline repair was needed.
    assert progress['round']==5
    assert state['demo_step']['index']==1 and state['demo_step']['total']==3
    response=c.get('/workflow/progress')
    assert response.status_code==200 and response.json()['current']['id']=='03'
    assert 'private' not in response.text and 'proposal' not in response.text
    from app.runlogs import directory
    run=state['negotiations'][0]
    transcript=(directory()/run['transcript_file']).read_text()
    assert '\n## 01 · 입력·재견적\n' in transcript
    assert '\n## 03 · 공정성 협상\n' in transcript
    assert '데모 시연 1/3' in transcript
    assert transcript.index('## 01 ·')<transcript.index('## 03 ·')
    ids=[int(line.split(' · 메시지: ')[1]) for line in transcript.splitlines() if ' · 메시지: ' in line]
    assert ids==sorted(set(ids))
    recovered=step(c)
    assert recovered['demo_step']['index']==2
    assert '02' in {s['id'] for s in recovered['workflow_progress']['visited']}
    run=recovered['negotiations'][-1]
    transcript=(directory()/run['transcript_file']).read_text()
    assert '\n## 02 · 기한 회복\n' in transcript
    assert '데모 시연 2/3' in transcript


def test_progress_endpoint_reports_real_stage_while_llm_call_is_in_flight(client):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from app.llm import MockLLM
    c,_=client;c.post('/demo/select',json={'demo':'demo5_release'})
    entered,release=Event(),Event()
    class Slow(MockLLM):
        def discuss(self,person,card,context):
            entered.set()
            assert release.wait(5),'test release not received'
            return super().discuss(person,card,context)
    llm.set_llm(Slow())
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            response=pool.submit(c.post,'/demo/advance',json={'auto_confirm':True})
            try:
                assert entered.wait(5)
                progress=c.get('/workflow/progress').json()
                assert progress['status']=='running' and progress['current']['id']=='03'
                assert progress['round']==1
                assert set(progress)=={'demo','run_id','current','status','round','demo_step'}
            finally:release.set()
            assert response.result(timeout=10).status_code==200
    finally:llm.set_llm(None)
