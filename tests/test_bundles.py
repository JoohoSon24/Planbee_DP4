"""HTTP integration tests for all-or-nothing transfers, split dependencies and consent."""
import os
os.environ['PLANBEE_DB']='sqlite://'
os.environ['PLANBEE_LLM']='mock'
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, event
from app import api, bundles, hive, store
from app.models import Card, Confirmation, Handoff, Run, Task


from run_bundle_demo import setup_board

@pytest.fixture
def c(monkeypatch):
    old=store.DEMO;engine=store.make_engine('sqlite://');factory=store.make_session_factory(engine)
    monkeypatch.setattr(api,'SessionLocal',factory)
    with factory() as db:setup_board(db)
    with TestClient(api.app) as client:yield client,factory,engine
    store.use_demo(old);engine.dispose()

SWAP={'transfers':[{'task':'x','to':'jun'},{'task':'y','to':'mia'}]}
def post(client,payload=SWAP):
    r=client.post('/bundles',json=payload);assert r.status_code==200,r.text;return r.json()
def owner(factory,tid):
    with factory() as db:return db.get(Task,tid).who

def test_swap_can_only_fit_as_a_whole_and_waits_for_everyone(c):
    client,factory,_=c
    r=client.post('/bundles/preview',json={'transfers':[SWAP['transfers'][0]]})
    assert r.status_code==409 and owner(factory,'x')=='mia'
    assert client.post('/bundles/preview',json=SWAP).status_code==200
    run=post(client);ids=run['waiting_for'];assert len(ids)==2
    assert client.post('/bundles',json=SWAP).status_code==409
    client.post(f'/confirmations/{ids[0]}',json={'ok':True})
    assert owner(factory,'x')=='mia' and owner(factory,'y')=='jun'
    client.post(f'/confirmations/{ids[1]}',json={'ok':True})
    assert owner(factory,'x')=='jun' and owner(factory,'y')=='mia'
    assert client.get(f'/bundles/{run["id"]}').json()['outcome']=='committed'
    assert client.post(f'/confirmations/{ids[1]}',json={'ok':True}).status_code==409

def test_rejection_cancels_every_transfer_and_remaining_requests(c):
    client,factory,_=c;run=post(client)
    client.post(f'/confirmations/{run["waiting_for"][0]}',json={'ok':False})
    assert client.get(f'/bundles/{run["id"]}').json()['outcome']=='cancelled'
    assert owner(factory,'x')=='mia' and owner(factory,'y')=='jun'
    with factory() as db:assert not list(db.scalars(select(Confirmation).where(Confirmation.status=='pending')))

def test_partial_many_way_split_keeps_work_and_all_parts_gate_the_consumer(c,monkeypatch):
    client,factory,_=c
    with factory() as db:setup_board(db,'split')
    payload={'transfers':[{'task':'x','to':'jun','amount':.5},{'task':'x','to':'sol','amount':.5}]}
    run=post(client,payload)
    with factory() as db:assert db.get(Task,'x').d==2
    for cid in run['waiting_for']:assert client.post(f'/confirmations/{cid}',json={'ok':True}).status_code==200
    with factory() as db:
        b=store.board(db);hive.schedule(b)
        assert b.tasks['x'].kind=='milestone' and b.tasks['x'].d==0
        parts=[t for t in b.tasks.values() if t.id.startswith('bundle_')]
        assert len(parts)==3 and sum(t.d for t in parts)==2
        assert {t.who for t in parts}=={'mia','jun','sol'}
        assert b.tasks['qa'].s>=max(t.s+t.d for t in parts)
        assert hive.gate(b)['ok'] and not hive.gate(b)['warnings']
    assert client.post('/tasks/x/move',json={'dest':'jun'}).status_code==409
    from types import SimpleNamespace
    from app import workflow
    monkeypatch.setattr(workflow,'get_llm',lambda:SimpleNamespace(reestimate=lambda *a,**kw:SimpleNamespace(task='x',days=1)))
    response=client.post('/records',json={'records':[{'src':'작업','who':'mia','text':'대기점 견적을 변경하려는 잘못된 결과'}],'auto_confirm':True})
    assert response.status_code==200
    with factory() as db:assert db.get(Task,'x').d==0

def test_incoming_authority_is_sum_of_all_received_work(c):
    client,_,_=c
    run=post(client,{'transfers':[{'task':'x','to':'sol'},{'task':'y','to':'sol'}]})
    pv=run['preview'];assert pv['incoming']['sol']==4
    assert {x['who'] for x in pv['confirmations']}=={'mia','jun','sol'}

def test_card_change_invalidates_previously_collected_consent(c):
    client,factory,_=c;run=post(client)
    client.post(f'/confirmations/{run["waiting_for"][0]}',json={'ok':True})
    assert client.put('/people/jun/card',json={'auto_days':1}).status_code==200
    client.post(f'/confirmations/{run["waiting_for"][1]}',json={'ok':True})
    assert client.get(f'/bundles/{run["id"]}').json()['outcome']=='invalidated'
    assert owner(factory,'x')=='mia' and owner(factory,'y')=='jun'

def test_refusal_duplicate_excess_started_and_invalid_quantities_are_rejected(c):
    client,factory,_=c
    for changes in [
        {'transfers':[{'task':'x','to':'jun','amount':3}]},
        {'transfers':[{'task':'x','to':'jun'},{'task':'x','to':'jun'}]},
        {'transfers':[{'task':'x','to':'ara'}]},
    ]:assert client.post('/bundles',json=changes).status_code==409
    for amount in [0,.25,'NaN','Infinity']:
        assert client.post('/bundles',json={'transfers':[{'task':'x','to':'jun','amount':amount}]}).status_code==422
    client.put('/people/jun/card',json={'refuse_tags':['개발']})
    assert client.post('/bundles',json=SWAP).status_code==409
    client.put('/people/jun/card',json={'refuse_tags':[]})
    with factory() as db:store.set_meta(db,'now',1);db.commit()
    assert client.post('/bundles',json=SWAP).status_code==409

def test_late_split_and_dependency_cycles_are_rejected_without_changes(c):
    client,factory,_=c
    with factory() as db:
        setup_board(db,'split');db.get(Handoff,'h').t=2;db.commit()
    payload={'transfers':[{'task':'x','to':'jun','amount':1},{'task':'x','to':'sol','amount':1}]}
    assert client.post('/bundles',json=payload).status_code==409
    with factory() as db:
        setup_board(db)
        db.add(Handoff(id='cycle',from_task='qa',to_task='x',title='cycle',what='',t=5));db.commit()
    assert client.post('/bundles',json=SWAP).status_code==409
    assert owner(factory,'x')=='mia'

def test_pending_state_survives_new_session_and_explicit_cancel(c):
    client,factory,_=c;run=post(client)
    with factory() as db:
        persisted=db.get(Run,run['id']);assert persisted.ctx['waiting_for']==run['waiting_for']
    assert client.post(f'/bundles/{run["id"]}/cancel').json()['outcome']=='cancelled'
    assert client.post(f'/bundles/{run["id"]}/cancel').status_code==409
    assert owner(factory,'x')=='mia'

def test_write_failure_rolls_back_final_consent_and_all_task_writes(c):
    client,factory,engine=c;run=post(client);a,b=run['waiting_for']
    client.post(f'/confirmations/{a}',json={'ok':True})
    def fail(conn,cursor,statement,params,context,many):
        if statement.startswith('UPDATE task SET'):raise RuntimeError('simulated disk write failure')
    event.listen(engine,'before_cursor_execute',fail)
    try:
        with pytest.raises(RuntimeError,match='simulated disk'):
            client.post(f'/confirmations/{b}',json={'ok':True})
    finally:event.remove(engine,'before_cursor_execute',fail)
    assert owner(factory,'x')=='mia' and owner(factory,'y')=='jun'
    with factory() as db:assert db.get(Confirmation,b).status=='pending'
    client.post(f'/confirmations/{b}',json={'ok':True})
    assert owner(factory,'x')=='jun' and owner(factory,'y')=='mia'

def test_three_way_exchange_commits_all_three_owners(c):
    client,factory,_=c
    with factory() as db:
        db.add(Task(id='z',who='sol',title='z',s0=0,s=0,d=2,base=2,plan=2,role='개발',tag='개발',oi=9));db.commit()
    run=post(client,{'transfers':[{'task':'x','to':'jun'},{'task':'y','to':'sol'},{'task':'z','to':'mia'}]})
    for cid in run['waiting_for']:client.post(f'/confirmations/{cid}',json={'ok':True})
    assert [owner(factory,t) for t in ['x','y','z']]==['jun','sol','mia']

def test_concurrent_confirmations_are_serialized_without_partial_commit(tmp_path,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    old=store.DEMO;engine=store.make_engine('sqlite:///'+str(tmp_path/'concurrent.db'));factory=store.make_session_factory(engine)
    monkeypatch.setattr(api,'SessionLocal',factory)
    try:
        with factory() as db:setup_board(db)
        with TestClient(api.app) as client:
            run=post(client)
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses=list(pool.map(lambda cid:client.post(f'/confirmations/{cid}',json={'ok':True}),run['waiting_for']))
            assert all(r.status_code==200 for r in responses)
            assert client.get(f'/bundles/{run["id"]}').json()['outcome']=='committed'
            assert owner(factory,'x')=='jun' and owner(factory,'y')=='mia'
    finally:engine.dispose();store.use_demo(old)

def test_documented_demo4_can_be_selected_and_swapped_through_http(c):
    client,_,_=c
    assert client.post('/demo/select',json={'demo':'demo4_bundles'}).status_code==200
    run=post(client)
    for cid in run['waiting_for']:client.post(f'/confirmations/{cid}',json={'ok':True})
    assert client.get(f'/bundles/{run["id"]}').json()['outcome']=='committed'

def test_receiving_duration_uses_skill_and_retains_source_estimate_basis(c):
    from app.models import Person
    client,factory,_=c
    with factory() as db:
        db.get(Person,'mia').rec={'개발':5};db.get(Person,'sol').rec={'개발':0}
        db.get(Handoff,'h').t=3;db.get(Task,'qa').s0=3
        hive.schedule(store.board(db));db.commit()
    run=post(client,{'transfers':[{'task':'x','to':'sol'}]})
    assert run['preview']['incoming']['sol']==3
    for cid in run['waiting_for']:client.post(f'/confirmations/{cid}',json={'ok':True})
    with factory() as db:
        t=db.get(Task,'x');assert t.d==3 and t.base==2 and t.who0=='mia'
