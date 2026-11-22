"""The public app uses only the five imported M4 scenarios; Live has no mock fallback."""
from copy import deepcopy
import pytest
from fastapi.testclient import TestClient
from app import api, store, llm, hive, discussion
from app.candidates import engine
from app.candidates.generator import enumerate_plans
from app.candidates.models import Assessment, Consent, ConstraintReview, Designs, Opinion, Speech
from app.llm import EstimateDecision

IDS=['m4_t1_rescheduling','m4_t2_reallocation','m4_t3_scope_reduction','m4_t4_composite','m4_t5_infeasible']

@pytest.fixture
def app_env(monkeypatch):
    old=store.DEMO;store.use_demo(IDS[0])
    eng=store.make_engine('sqlite://');factory=store.make_session_factory(eng)
    monkeypatch.setattr(api,'SessionLocal',factory)
    with TestClient(api.app) as client:yield client,factory
    store.use_demo(old);eng.dispose()


def test_only_five_published_scenarios_and_source_assets(app_env):
    c,_=app_env
    assert c.get('/demos').json()['all']==IDS
    assert [d['id'] for d in c.get('/demos').json()['catalog']]==IDS
    for sid in IDS:
        r=c.post('/demo/select',json={'demo':sid});assert r.status_code==200,r.text
        state=r.json();assert state['demo']['all']==IDS and len(state['people'])==4
        assert state['demo']['engine_support'] and state['demo']['source_task'] in state['tasks']
        initial=c.get(f'/demos/{sid}/scenario-data').json()
        assert initial['meta']['source_sha256'] and initial['meta']['normalization_note']
        assert c.get(f'/demos/{sid}/board').headers['content-type']=='image/png'
        doc=c.get(f'/demos/{sid}/scenario');assert doc.status_code==200
        for section in ['초기 milestone 보드','각자의 위임카드','각 Task 세부 description','실행 엔진 지원 범위']:
            assert section in doc.text
        assert initial['meta']['engine_support'] in doc.text
    assert (store.SEED/'demo5_release'/'team.yaml').is_file() # archived, never deleted
    assert c.get('/demos/unknown/board').status_code==404


def test_t1_exact_source_move_keeps_other_work(app_env):
    c,f=app_env
    with f() as db:
        b=store.board(db);hive.schedule(b)
        plans,_=enumerate_plans(b,dict(task='polish'),[],engine.Settings())
        move=next(p for p in plans if p['schedule_changes']==[dict(task='polish',start=5)])
        st,affected=discussion.preview(b,dict(task='polish'),move['allocations'],'whole_task',move['schedule_changes'])
        assert st.tasks['polish'].s==5 and affected==['dev']
        assert hive.gate(st)['ok']
        for tid in b.tasks:
            if tid!='polish':assert (st.tasks[tid].who,st.tasks[tid].s,st.tasks[tid].d)==(b.tasks[tid].who,b.tasks[tid].s,b.tasks[tid].d)
        with pytest.raises(ValueError):discussion.preview(b,dict(task='polish'),move['allocations'],'whole_task',[dict(task='polish',start=6)])


def test_t2_cross_role_contract_and_person_confirm(app_env):
    c,f=app_env;c.post('/demo/select',json={'demo':IDS[1]})
    result=c.post('/candidate-runs',json=dict(task_id='ui_integration',issue=store.load_yaml('feed.yaml')['issue']['records'][0]['text'])).json()
    candidate=next(p for p in result['candidates'] if {a['who'] for a in p['allocations']}=={'dev','art'})
    assert candidate['board']['gate']['ok']
    with f() as db:
        b=store.board(db);hive.schedule(b)
        wrong=deepcopy(candidate['allocations']);next(a for a in wrong if a['key']=='logic')['who']='art'
        with pytest.raises(ValueError,match='역할 불일치'):discussion.preview(b,dict(task='ui_integration'),wrong,'whole_task')
    for _ in range(80):
        if result['status']!='running':break
        result=c.post(f"/runs/{result['id']}/advance",json={}).json()
    assert result['status']=='awaiting_pm_selection'
    chosen=next(p for p in result['candidates'] if p['id']==result['final_candidates'][0])
    selected=c.post(f"/runs/{result['id']}/pm-selection",json=dict(action='select',candidate_id=chosen['id'],plan_hash=chosen['plan_hash']))
    assert selected.status_code==200,selected.text
    assert selected.json()['status']=='waiting_confirm'
    assert any(x['who']=='art' for x in c.get('/state').json()['pending_confirms'])
    for cf in c.get('/state').json()['pending_confirms']:
        assert c.post(f"/confirmations/{cf['id']}",json=dict(ok=True)).status_code==200
    state=c.get('/state').json()
    assert state['gate']['ok']
    parts=[t for t in state['tasks'].values() if t['context'].get('partition_of')=='ui_integration']
    assert {t['who'] for t in parts}=={'art','dev'}


class LiveContract(llm.LiveLLM):
    """Exercise the Live adapter path with deterministic responses, no paid requests."""
    def __init__(self):self.last_error=None;self.seen=[]
    def _ask(self,schema,instruction,facts,model=None):
        from app.negotiation_budget import consume
        consume()
        self.seen.append((schema.__name__,deepcopy(facts)))
        if schema is EstimateDecision:
            task=facts['맡은 일'][0];tid=task['id']
            days={'ui_integration':2,'advanced_effects':4,'character_animation':4,'critical_fix':2}.get(tid)
            return EstimateDecision(duration_changed=bool(days),task=tid if days else None,days=days,basis='테스트의 명시적 견적',evidence=facts['새 기록'][0])
        if schema is Designs:return Designs(templates=[],reason='Live 계약 테스트: Task에 명시된 연산자만 사용')
        if schema is Speech:return Speech(candidate_id=facts['candidates'][0]['id'],action='PREFER',message='공개된 이전 발화를 확인하고 해당 후보를 선호합니다.')
        if schema is Consent:return Consent(action='ACCEPT',reason='동일한 후보 버전을 확인했습니다.')
        if schema is ConstraintReview:return ConstraintReview(recipient='qa' if facts['self']['id']=='dev' else 'pm',message='수정 완료 시점 뒤에 필수 QA 2영업일이 필요합니다.',required_decision='PM에게 릴리스 보류 검토를 요청합니다.')
        assert schema is Assessment
        return Assessment(opinions=[Opinion(candidate_id=x['id'],action='ACCEPT',score=80,fairness_score=80,card_fit_score=80,reason='제 카드와 일정 확인') for x in facts['candidates']],message='본인 카드로 검토했습니다.')


@pytest.mark.parametrize('sid',IDS)
def test_all_five_feed_routes_use_live_contract_and_stop(app_env,monkeypatch,sid):
    c,_=app_env;c.post('/demo/select',json={'demo':sid})
    adapter=LiveContract();llm.set_llm(adapter)
    before=c.get('/board').json()
    response=c.post('/demo/advance',json=dict(negotiation_mode='candidate_discussion',auto_confirm=False))
    assert response.status_code==200,response.text
    r=c.get('/candidate-runs').json()[0]
    assert r['task']==store.load_yaml('feed.yaml')['issue']['task']
    for _ in range(80):
        if r['status']!='running':break
        response=c.post(f"/runs/{r['id']}/advance",json={});assert response.status_code==200,response.text
        r=response.json()
    assert r['status'] in ('awaiting_pm_selection','waiting_pm')
    assert r['llm_budget']['used']<=r['llm_budget']['max']
    assert all(x['board']['gate']['ok'] for x in r['candidates'])
    assert adapter.seen[0][0]=='EstimateDecision'
    assert any(kind=='Designs' for kind,_ in adapter.seen)
    if sid==IDS[4]:
        assert r['status']=='waiting_pm' and not r['candidates']
        assert r['termination']=='search_exhausted'
        assert r['pm_handoff']
    else:
        assert r['status']=='awaiting_pm_selection'
        if sid==IDS[0]:assert r['participants']==['dev'] and not any(x['requester'] in ('art','gd','qa') for x in r['public_history'])
        if sid==IDS[1]:assert set(r['participants'])=={'dev','art'}
        if sid==IDS[2]:assert any(a['kind']=='defer' for x in r['candidates'] for a in x.get('plan_actions',[]))
        if sid==IDS[3]:assert any(a['kind']=='restructure' for x in r['candidates'] for a in x.get('plan_actions',[]))
    # Re-estimation changes observations, but no unagreed assignments are applied.
    after=c.get('/board').json()
    assert {k:v['who'] for k,v in before['tasks'].items()}=={k:v['who'] for k,v in after['tasks'].items()}


def test_role_guards_pm_and_each_person_confirmation(app_env):
    c,_=app_env;c.post('/demo/select',json={'demo':IDS[1]})
    issue=store.load_yaml('feed.yaml')['issue']['records'][0]['text']
    body=dict(task_id='ui_integration',issue=issue,settings=dict(raw_limit=60,candidate_limit=3,shortlist_limit=3,max_rounds=1))
    assert c.post('/candidate-runs',json=body,headers={'X-Planbee-Role':'person:art'}).status_code==403
    assert c.get('/candidate-runs').json()==[]
    response=c.post('/candidate-runs',json=body,headers={'X-Planbee-Role':'person:dev'});assert response.status_code==200,response.text
    r=response.json()
    for _ in range(80):
        if r['status']!='running':break
        r=c.post(f"/runs/{r['id']}/advance",json={}).json()
    assert r['status']=='awaiting_pm_selection'
    candidate=next(p for p in r['candidates'] if p['id']==r['final_candidates'][0])
    select=dict(action='select',candidate_id=candidate['id'],plan_hash=candidate['plan_hash'])
    assert c.post(f"/runs/{r['id']}/pm-selection",json=select,headers={'X-Planbee-Role':'person:dev'}).status_code==403
    assert c.post(f"/runs/{r['id']}/pm-selection",json=select,headers={'X-Planbee-Role':'pm'}).status_code==200
    confirms=c.get('/state').json()['pending_confirms'];art=next(x for x in confirms if x['who']=='art')
    for wrong in ('pm','person:dev','person:qa'):
        assert c.post(f"/confirmations/{art['id']}",json=dict(ok=True),headers={'X-Planbee-Role':wrong}).status_code==403
    assert c.post(f"/confirmations/{art['id']}",json=dict(ok=True),headers={'X-Planbee-Role':'person:art'}).status_code==200
    for cf in confirms:
        if cf['who']!='art':assert c.post(f"/confirmations/{cf['id']}",json=dict(ok=True),headers={'X-Planbee-Role':'person:'+cf['who']}).status_code==200
    assert c.get(f"/runs/{r['id']}").json()['termination']=='applied'


def test_generator_schema_repair_uses_actual_errors_once(app_env):
    c,_=app_env
    class RepairOnce(LiveContract):
        def __init__(self):super().__init__();self.design_calls=[]
        def _ask(self,schema,instruction,facts,model=None):
            if schema is Designs:
                self.design_calls.append((instruction,deepcopy(facts)))
                if len(self.design_calls)==1:
                    from app.negotiation_budget import consume
                    consume();self.last_error={'type':'ValidationError','fields':[{'path':'templates.0.plan_actions.0.kind','type':'literal_error'}]}
                    return None
            return super()._ask(schema,instruction,facts,model)
    adapter=RepairOnce();llm.set_llm(adapter)
    r=c.post('/candidate-runs',json=dict(task_id='polish',issue=store.load_yaml('feed.yaml')['issue']['records'][0]['text'])).json()
    assert r['status']=='running' and r['candidates']
    assert len(adapter.design_calls)==2
    assert r['llm_budget']['used']==3 # estimate + invalid design + repaired design all count
    assert adapter.design_calls[0][0]!=adapter.design_calls[1][0]
    assert adapter.design_calls[1][1]['format_errors']['fields'][0]['path']=='templates.0.plan_actions.0.kind'
    assert 'my_delegation' not in adapter.design_calls[1][1]
    assert any(e['response']=='SCHEMA_REPAIR' for e in r['public_history'])


def test_repeated_schema_error_stops_and_does_not_apply(app_env):
    c,_=app_env
    class AlwaysBad(LiveContract):
        def __init__(self):super().__init__();self.design_calls=0
        def _ask(self,schema,instruction,facts,model=None):
            if schema is Designs:
                from app.negotiation_budget import consume
                consume();self.design_calls+=1;self.last_error={'type':'ValidationError','fields':[{'path':'templates.0.parts.0.effort','type':'less_than_equal'}]}
                return None
            return super()._ask(schema,instruction,facts,model)
    adapter=AlwaysBad();llm.set_llm(adapter);before=c.get('/board').json()
    r=c.post('/candidate-runs',json=dict(task_id='polish',issue=store.load_yaml('feed.yaml')['issue']['records'][0]['text'])).json()
    assert r['status']=='waiting_pm' and r['termination']=='model_output_invalid'
    assert adapter.design_calls==2 and not r['candidates']
    assert c.get('/board').json()==before


def test_approval_answer_does_not_regenerate_plan(app_env):
    c,_=app_env;c.post('/demo/select',json={'demo':IDS[2]})
    class ApprovalAnswer(LiveContract):
        def _ask(self,schema,instruction,facts,model=None):
            if schema is Speech:
                from app.negotiation_budget import consume
                consume()
                return Speech(candidate_id=facts['candidates'][0]['id'],action='ANSWER',message='기존 이관안에 동의하며 PM 승인을 기다립니다.',condition='PM 최종 선택 필요',requires_new_candidate=True)
            return super()._ask(schema,instruction,facts,model)
    llm.set_llm(ApprovalAnswer())
    r=c.post('/candidate-runs',json=dict(task_id='advanced_effects',issue=store.load_yaml('feed.yaml')['issue']['records'][0]['text'],settings=dict(candidate_limit=4,shortlist_limit=4,max_rounds=1))).json()
    for _ in range(40):
        if r['status']!='running':break
        r=c.post(f"/runs/{r['id']}/advance",json={}).json()
    assert r['status']=='awaiting_pm_selection'
    assert not any(m['response']=='SUPPLEMENT' for m in r['public_history'])
    assert any('PM 최종 선택 필요' in m['reason'] for m in r['public_history'])


def test_failed_supplement_preserves_pool_and_reassesses_conditions(app_env):
    c,_=app_env;c.post('/demo/select',json={'demo':IDS[2]})
    class FailedSupplement(LiveContract):
        def _ask(self,schema,instruction,facts,model=None):
            if schema is Designs and facts.get('public_conditions'):
                from app.negotiation_budget import consume
                consume();self.last_error={'type':'ValidationError','fields':[{'path':'templates.0.parts','type':'too_short'}]};return None
            if schema is Speech:
                from app.negotiation_budget import consume
                consume();return Speech(candidate_id=facts['candidates'][0]['id'],action='CONDITION',message='새 범위 확인을 요청합니다.',condition='기존 후보의 필수 Core 보존을 다시 확인',requires_new_candidate=True)
            return super()._ask(schema,instruction,facts,model)
    llm.set_llm(FailedSupplement())
    r=c.post('/candidate-runs',json=dict(task_id='advanced_effects',issue=store.load_yaml('feed.yaml')['issue']['records'][0]['text'],settings=dict(candidate_limit=4,shortlist_limit=4,max_rounds=1))).json()
    original={p['plan_hash'] for p in r['candidates']}
    for _ in range(40):
        if r['status']!='running':break
        r=c.post(f"/runs/{r['id']}/advance",json={}).json()
    assert r['status']=='awaiting_pm_selection'
    assert original=={p['plan_hash'] for p in r['candidates']}
    assert r['supplement_error'] and any(m['response']=='SUPPLEMENT_FAILED' for m in r['public_history'])
    assert any(m['response']=='RANK' for m in r['public_history'])
    assert not c.get('/state').json()['tasks']['advanced_effects']['cut']

@pytest.mark.parametrize('always_invalid',[False,True])
def test_assessment_bad_ids_get_one_bounded_feedback_retry(app_env,always_invalid):
    c,_=app_env
    class BadIds(LiveContract):
        def __init__(self):super().__init__();self.assessment_calls=0;self.repaired=False
        def _ask(self,schema,instruction,facts,model=None):
            result=super()._ask(schema,instruction,facts,model)
            if schema is Assessment:
                self.assessment_calls+=1
                if facts.get('assessment_feedback'):
                    self.repaired=True
                    assert facts['assessment_feedback']['missing_ids']
                if always_invalid or self.assessment_calls==1:
                    result.opinions[0].candidate_id='unknown_candidate'
            return result
    c.post('/demo/select',json={'demo':'m4_t1_rescheduling'})
    adapter=BadIds();llm.set_llm(adapter)
    c.post('/demo/advance',json=dict(negotiation_mode='candidate_discussion',auto_confirm=False))
    r=c.get('/candidate-runs').json()[0]
    for _ in range(50):
        if r['status']!='running':break
        r=c.post(f"/runs/{r['id']}/advance",json={}).json()
    assert adapter.repaired
    assert r['llm_budget']['used']==len(adapter.seen)
    if always_invalid:
        assert adapter.assessment_calls==2
        assert r['termination']=='model_output_invalid'
    else:assert r['status']=='awaiting_pm_selection'
    assert r.get('termination')!='applied'
