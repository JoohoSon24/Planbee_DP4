"""Candidate plans are feasible, private, versioned and never automatically applied."""
from copy import deepcopy
import json
import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import select
from app import api,store,hive,llm,prompts,workflow
from app.models import Run,Task,Confirmation,CandidateEvaluation
from app.candidates import engine,evaluation
from app.candidates.generator import snapshot,canonical


@pytest.fixture
def candidate_env(monkeypatch):
    old=store.DEMO;store.use_demo('demo5_release')
    eng=store.make_engine('sqlite://');factory=store.make_session_factory(eng)
    monkeypatch.setattr(api,'SessionLocal',factory)
    with TestClient(api.app) as client:
        yield client,factory
    store.use_demo(old);eng.dispose()


def launch(client,calls=120,candidates=6):
    result=client.post('/candidate-runs',json=dict(task_id='contract',issue='계약 검증 분담',settings=dict(
        raw_limit=100,candidate_limit=candidates,shortlist_limit=min(candidates,6),max_rounds=1,max_calls=calls,max_seconds=120)))
    assert result.status_code==200,result.text
    return result.json()


def finish(client,r):
    for _ in range(80):
        if r['status']!='running':return r
        response=client.post(f"/runs/{r['id']}/advance",json={})
        assert response.status_code==200,response.text
        r=response.json()
    pytest.fail('candidate workflow did not stop')


def test_feasible_candidates_wait_for_pm_and_persist_across_reload(candidate_env):
    c,factory=candidate_env;initial=c.get('/board').json()
    r=finish(c,launch(c))
    assert r['status']=='awaiting_pm_selection' and 1<=len(r['final_candidates'])<=3
    assert c.get('/board').json()==initial
    assert all(x['board']['gate']['ok'] for x in r['candidates'])
    assert all('milestones' in x['board'] for x in r['candidates'])
    assert r['llm_budget']['used']>0
    loaded=c.get(f"/runs/{r['id']}").json();assert loaded['final_candidates']==r['final_candidates']
    assert 'private_cards' not in loaded and 'initial_assessments' not in loaded and 'prompt_snapshot' not in loaded
    assert c.post('/candidate-runs',json=dict(task_id='contract',issue='second')).status_code==409
    with factory() as db:
        run=db.get(Run,r['id']);text=(Path(__import__('os').environ['PLANBEE_RUNS_DIR'])/run.ctx['transcript_file']).read_text()
        assert '검증된 새 milestone 후보' in text and 'PM 최종 후보와 결정' in text
        assert 'private_cards' not in text


def test_single_candidate_requires_pm_choice_then_is_idempotent(candidate_env):
    c,factory=candidate_env;r=finish(c,launch(c,candidates=1))
    assert r['status']=='awaiting_pm_selection' and len(r['final_candidates'])==1
    chosen=next(x for x in r['candidates'] if x['id']==r['final_candidates'][0])
    body=dict(action='select',candidate_id=chosen['id'],plan_hash=chosen['plan_hash'])
    response=c.post(f"/runs/{r['id']}/pm-selection",json=body);assert response.status_code==200,response.text
    r=response.json()
    for confirmation in c.get('/state').json()['pending_confirms']:
        response=c.post(f"/confirmations/{confirmation['id']}",json=dict(ok=True));assert response.status_code==200,response.text
    assert c.get(f"/runs/{r['id']}").json()['termination']=='applied'
    before=c.get('/board').json()
    assert c.post(f"/runs/{r['id']}/pm-selection",json=body).status_code==200
    assert c.get('/board').json()==before
    assert c.get('/state').json()['gate']['ok']


def test_budget_failure_is_not_applied_and_pm_has_summary(candidate_env):
    c,_=candidate_env;before=c.get('/board').json();r=finish(c,launch(c,calls=1))
    assert r['termination']=='max_llm_calls' and r['llm_budget']['used']==1
    assert c.get('/board').json()==before
    assert r['pm_handoff']['summary']['disposition'].startswith('미합의')


def test_stale_candidate_cannot_be_selected(candidate_env):
    c,factory=candidate_env;r=finish(c,launch(c))
    candidate=next(x for x in r['candidates'] if x['id']==r['final_candidates'][0])
    with factory() as db:
        db.get(Task,'contract').d+=.25;db.commit()
    result=c.post(f"/runs/{r['id']}/pm-selection",json=dict(action='select',candidate_id=candidate['id'],plan_hash=candidate['plan_hash']))
    assert result.status_code==409


def test_pm_reject_does_not_change_board(candidate_env):
    c,_=candidate_env;r=finish(c,launch(c));before=c.get('/board').json()
    response=c.post(f"/runs/{r['id']}/pm-selection",json=dict(action='reject',reason='현재 배분을 유지하겠습니다'))
    assert response.status_code==200 and response.json()['termination']=='pm_rejected'
    assert c.get('/board').json()==before


def test_human_ranking_is_frozen_separate_and_no_agent_rank_is_shown(candidate_env):
    c,factory=candidate_env;r=finish(c,launch(c))
    made=c.post(f"/runs/{r['id']}/evaluations",json=dict(rubric='card_fit',person_id='bora'))
    assert made.status_code==200,made.text
    row=made.json();assert row['card']['who']=='bora'
    assert 'reference' not in row and 'consents' not in str(row)
    groups=[[x['id']] for x in row['candidates']]
    result=c.post(f"/evaluations/{row['id']}/human-ranking",json=dict(evaluation_hash=row['evaluation_hash'],ranking_groups=groups))
    assert result.status_code==200,result.text
    metric=result.json();assert metric['ce']>=0 and metric['uniform_ce']==pytest.approx(math.log(len(groups)))
    assert c.post(f"/evaluations/{row['id']}/human-ranking",json=dict(evaluation_hash=row['evaluation_hash'],ranking_groups=groups)).status_code==409
    assert c.get(f"/evaluations/{row['id']}/compare").json()['ce']==metric['ce']


def test_rank_math_ties_uniform_and_reverse():
    same=evaluation.compare([['a'],['b'],['c']],[['a'],['b'],['c']])
    reverse=evaluation.compare([['a'],['b'],['c']],[['c'],['b'],['a']])
    assert same['kl']==pytest.approx(0) and reverse['ce']>same['ce']
    assert same['kendall_tau_b']==1 and reverse['kendall_tau_b']==-1
    tied=evaluation.compare([['a','b']],[['a','b']]);assert tied['ce']==pytest.approx(math.log(2))
    assert evaluation.compare([['a']],[['a']])['ce'] is None


def test_generation_has_no_private_cards_and_each_agent_only_gets_own_card(candidate_env):
    c,factory=candidate_env;seen=[]
    class Fake(llm.MockLLM):
        def candidate_reply(self,schema,facts):
            seen.append(deepcopy(facts))
            if schema.__name__=='Designs':
                assert 'my_delegation' not in facts and 'source_note' not in json.dumps(facts)
                return dict(templates=[],reason='whole task transformations only')
            actor=facts['self']['id'];assert facts['my_delegation']['who']==actor
            if schema.__name__=='Assessment':return dict(opinions=[dict(candidate_id=x['id'],action='ACCEPT',score=50,fairness_score=50,card_fit_score=50,reason='allow') for x in facts['candidates']],message='compared')
            if schema.__name__=='Speech':return dict(candidate_id=facts['candidates'][0]['id'],action='PASS',message='no new question')
            return dict(action='ACCEPT',reason='allow')
    llm.set_llm(Fake());r=finish(c,launch(c))
    assert seen and r['status']=='awaiting_pm_selection'


def test_frontend_and_runtime_are_served(candidate_env):
    c,_=candidate_env;html=c.get('/').text
    assert '/front/planbee-app.js' in html and 'SCENES' not in html
    assert c.get('/front/planbee-app.js').status_code==200
    assert c.get('/front/evaluation.html').status_code==200
    assert c.get('/runtime').json()['llm_mode']=='mock'


def test_prompt_snapshot_is_frozen_and_canonical_ignores_arbitrary_keys(candidate_env):
    c,factory=candidate_env;r=launch(c)
    with factory() as db:
        run=db.get(Run,r['id']);frozen=run.ctx['prompt_snapshot']
        with prompts.frozen(frozen):assert prompts.read_prompt('assess')==frozen['discussion/assess.md']
    a=[dict(who='a',what='scope',title='old',effort=1,days=1,key='x',depends_on=[])]
    b=[dict(a[0],title='new',key='renamed')]
    assert canonical(a,[])==canonical(b,[])


def test_three_way_plans_keep_effort_and_invalid_deadlines_are_filtered(candidate_env):
    from app.candidates.generator import enumerate_plans
    from app.candidates.models import Transformation,Part
    c,factory=candidate_env
    with factory() as db:
        b=store.board(db);hive.schedule(b);before=snapshot(b)
        template=Transformation(title='병렬 검증',basis='서로 다른 검증 산출물을 병렬로 만들고 원 완료 장벽에서 통합한다.',parts=[
            Part(key='core',title='상태 전이 코어',what='상태 전이 코어 구현',effort=2),
            Part(key='normal',title='정상 경로',what='독립 정상 경로 픽스처와 검증',effort=.5),
            Part(key='failure',title='실패 경로',what='독립 실패 경로 픽스처와 검증',effort=.5)])
        found,stats=enumerate_plans(b,dict(task='contract'),[template],engine.Settings(raw_limit=500,candidate_limit=100))
        assert found and stats['rejected']>0
        assert snapshot(b)==before
        assert all(x['board']['gate']['ok'] and abs(sum(a['effort'] for a in x['allocations'])-3)<1e-9 for x in found)
        assert any(len({a['who'] for a in x['allocations']})>=3 for x in found)


def test_pm_revise_keeps_budget_and_uses_new_pool_revision(candidate_env):
    c,factory=candidate_env;r=finish(c,launch(c));used=r['llm_budget']['used']
    result=c.post(f"/runs/{r['id']}/pm-selection",json=dict(action='revise',reason='다른 업무 이동도 비교하고 싶습니다'))
    assert result.status_code==200,result.text
    changed=result.json();assert changed['status']=='running' and not changed['final_candidates']
    assert changed['pool_revision']==r['pool_revision']+1 and changed['llm_budget']['used']==used
    stale=next(x for x in r['candidates'] if x['id']==r['final_candidates'][0])
    assert c.post(f"/runs/{r['id']}/pm-selection",json=dict(action='select',candidate_id=stale['id'],plan_hash=stale['plan_hash'])).status_code==409


def test_confirmation_rejection_never_applies_the_chosen_candidate(candidate_env):
    c,factory=candidate_env;r=finish(c,launch(c));before=c.get('/board').json()
    chosen=next((x for x in r['candidates'] if x['id'] in r['final_candidates'] and any(a['action']=='NEEDS_INPUT' for a in x.get('consents',{}).values())),None)
    if chosen is None:
        # Explicitly require human authority for an otherwise agreed exact version.
        with factory() as db:
            raw=db.get(Run,r['id']);chosen=deepcopy(next(x for x in raw.ctx['candidates'] if x['id']==raw.ctx['final_candidates'][0]))
            pid=chosen['affected'][0];chosen['consents'][pid]=dict(action='NEEDS_INPUT',reason='본인 확인')
            engine.patch(raw,candidates=[chosen if x['id']==chosen['id'] else x for x in raw.ctx['candidates']]);db.commit()
    result=c.post(f"/runs/{r['id']}/pm-selection",json=dict(action='select',candidate_id=chosen['id'],plan_hash=chosen['plan_hash']))
    assert result.status_code==200,result.text
    pending=c.get('/state').json()['pending_confirms'];assert pending
    assert c.post(f"/confirmations/{pending[0]['id']}",json=dict(ok=False)).status_code==200
    assert c.get('/board').json()==before
    assert c.get(f"/runs/{r['id']}").json()['status'] in ('awaiting_pm_selection','waiting_pm')


def test_new_default_run_directory_is_v2_and_mode_separated(monkeypatch):
    from app import runlogs
    monkeypatch.delenv('PLANBEE_RUNS_DIR',raising=False)
    assert runlogs.directory('live')==store.ROOT/'runs'/'v2'/'live'
    assert runlogs.directory('mock')==store.ROOT/'runs'/'v2'/'mock'


def test_model_failure_is_distinct_from_search_exhaustion(candidate_env):
    c,factory=candidate_env
    class Offline(llm.LiveLLM):
        def __init__(self):self.last_error=dict(type='HTTPStatusError',status=503)
        def _ask(self,*args,**kw):return None
        def reestimate(self,*args,**kw):return None
    llm.set_llm(Offline())
    r=launch(c)
    assert r['termination']=='model_unavailable'
    assert not r['candidates'] and r['status']=='waiting_pm'


@pytest.mark.parametrize('demo',store.demos())
def test_v2_demo_feeds_do_not_call_the_scripted_frontend_or_hang(candidate_env,monkeypatch,demo):
    c,_=candidate_env;monkeypatch.setenv('PLANBEE_NEGOTIATION_MODE','candidate_discussion')
    assert c.post('/demo/select',json=dict(demo=demo)).status_code==200
    for _ in range(12):
        state=c.get('/state').json()
        if state['phase']=='end':break
        if not state['feed_label']:pytest.fail(f"{demo}: feed stuck at {state['phase']}")
        response=c.post('/demo/advance',json=dict(auto_confirm=False));assert response.status_code==200,response.text
        runs=c.get('/candidate-runs').json()
        if not runs:continue
        r=finish(c,runs[0])
        if r['status']=='awaiting_pm_selection':
            selected=next(x for x in r['candidates'] if x['id']==r['final_candidates'][0])
            chosen=c.post(f"/runs/{r['id']}/pm-selection",json=dict(action='select',candidate_id=selected['id'],plan_hash=selected['plan_hash']))
            assert chosen.status_code==200,chosen.text
            for cf in c.get('/state').json()['pending_confirms']:
                answer=c.post(f"/confirmations/{cf['id']}",json=dict(ok=True));assert answer.status_code==200,answer.text
        r=c.get(f"/runs/{r['id']}").json()
        if r['status']=='waiting_pm':assert c.post(f"/runs/{r['id']}/close",json={}).status_code==200
    assert c.get('/state').json()['phase']=='end'


def test_live_transport_uses_frozen_md_and_separate_role_facts(candidate_env):
    import httpx
    c,_=candidate_env;requests=[]
    def handler(request):
        body=json.loads(request.content);requests.append(body)
        properties=body['tools'][0]['function']['parameters']['properties']
        content=body['messages'][1]['content'];facts=json.loads(content.rsplit('\n\n',1)[1])
        if 'templates' in properties:
            assert 'my_delegation' not in facts and 'source_note' not in content
            answer=dict(templates=[],reason='whole task plus side moves')
        elif 'opinions' in properties:
            assert facts['my_delegation']['who']==facts['self']['id']
            assert '다른 사람' in body['messages'][0]['content'] or '다른 참여자' in body['messages'][0]['content']
            answer=dict(opinions=[dict(candidate_id=x['id'],action='ACCEPT',score=50,fairness_score=50,card_fit_score=50,reason='조건 확인') for x in facts['candidates']],message='비교 완료')
        elif 'candidate_id' in properties:
            answer=dict(candidate_id=facts['candidates'][0]['id'],action='PASS',message='추가 쟁점 없음')
        elif 'task' in properties:
            answer=dict(duration_changed=False,task=None,days=None,basis='',evidence='')
        else:answer=dict(action='ACCEPT',reason='해당 버전 동의')
        return httpx.Response(200,json={'choices':[{'message':{'tool_calls':[{'function':{'arguments':json.dumps(answer)}}]}}]})
    adapter=llm.LiveLLM(client=httpx.Client(transport=httpx.MockTransport(handler)));llm.set_llm(adapter)
    r=finish(c,launch(c))
    assert r['status']=='awaiting_pm_selection'
    assert r['llm_budget']['used']==len(requests)
    assert r['prompt_hashes']['discussion/assess.md']


def test_assessment_advances_one_person_at_a_time_and_logs_stages(candidate_env):
    c,factory=candidate_env;r=launch(c)
    assert r['step']=='candidate_assess'
    response=c.post(f"/runs/{r['id']}/advance",json={});assert response.status_code==200,response.text
    one=response.json();assert one['step']=='candidate_assess'
    assert one['assessment_progress']==dict(completed=1,total=8,stage='initial')
    with factory() as db:
        saved=db.get(Run,r['id']);assert len(saved.ctx['initial_assessments'])==1
        assert [t['stage']['id'] for t in saved.ctx['execution_turns']][:3]==['01','02','03']
