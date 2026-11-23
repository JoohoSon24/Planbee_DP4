"""T6 source fidelity, feasible QA split, and explicit P0 authority."""
import pytest
from tests.test_m4_catalog import app_env
from app import store

SID='m4_t6_game_demo'


@pytest.mark.parametrize('approve',[True,False])
def test_t6_assets_and_full_qa_split_wait_for_ben(app_env,monkeypatch,approve):
    c,_=app_env
    monkeypatch.setenv('PLANBEE_AUTO_CONFIRM','1')
    response=c.post('/demo/select',json={'demo':SID})
    assert response.status_code==200,response.text
    assert len(response.json()['people'])==5
    assert len(response.json()['tasks'])==13
    assert c.get(f'/demos/{SID}/board').headers['content-type']=='image/png'
    source=c.get(f'/demos/{SID}/scenario-data').json()
    assert source['meta']['source_sha256']
    issue=store.load_yaml('feed.yaml')['issue']['records'][0]['text']
    r=c.post('/candidate-runs',json={'task_id':'Q2','issue':issue}).json()
    assert r['candidates'],r.get('generation_stats',r)
    assert 'leo' in r['participants']
    assert all(x['board']['gate']['ok'] for x in r['candidates'])
    for _ in range(80):
        if r['status']!='running':break
        response=c.post(f"/runs/{r['id']}/advance",json={})
        assert response.status_code==200,response.text
        r=response.json()
    assert r['status']=='awaiting_pm_selection',r
    recommended=[x for x in r['candidates'] if x['id'] in r['final_candidates']]
    assert any(any(a['who']=='sam' for a in x['allocations']) for x in recommended)
    selected=next(x for x in r['candidates'] if x['id']==r['final_candidates'][0])
    assert {x['who'] for x in selected['allocations']}=={'ben','zoe'}
    assert sum(x['effort'] for x in selected['allocations'])==1
    assert 'ben' in selected['required_confirmations']
    response=c.post(f"/runs/{r['id']}/pm-selection",json={'action':'select','candidate_id':selected['id'],'plan_hash':selected['plan_hash']})
    assert response.status_code==200,response.text
    assert response.json()['status']=='waiting_confirm'
    pending=c.get('/state').json()['pending_confirms']
    assert any(x['who']=='ben' for x in pending)
    before=c.get('/board').json()
    if not approve:
        cf=next(x for x in pending if x['who']=='ben')
        response=c.post(f"/confirmations/{cf['id']}",json={'ok':False},headers={'X-Planbee-Role':'person:ben'})
        assert response.status_code==200,response.text
        assert c.get('/board').json()==before
        assert c.get(f"/runs/{r['id']}").json()['termination']!='applied'
        return
    for cf in pending:
        response=c.post(f"/confirmations/{cf['id']}",json={'ok':True},headers={'X-Planbee-Role':'person:'+cf['who']})
        assert response.status_code==200,response.text
    assert c.get(f"/runs/{r['id']}").json()['termination']=='applied'
    assert c.get('/state').json()['gate']['ok']


def test_t6_source_hash_and_original_assets_are_self_contained():
    import hashlib
    import yaml
    root=store.SEED/SID
    team=yaml.safe_load((root/'team.yaml').read_text())
    assert hashlib.sha256((root/'source.md').read_bytes()).hexdigest()==team['meta']['source_sha256']
    assert (root/'board.png').read_bytes().startswith(b'\x89PNG')
    assert {t['id'] for t in team['tasks']}=={'A1','A2','G1','G2','G3','S1','S2','S3','B1','B2','Q1','Q2','milestone'}
    for person in team['people']:
        assert (store.ROOT/'prompts'/'agents'/(person['notes']['prompt_role']+'.md')).is_file()
    assert '16:00' in team['meta']['normalization_note']



def test_t6_live_reestimate_loads_numbered_role_prompt(app_env):
    from app import llm, prompts
    from app.llm import EstimateDecision
    c,_=app_env
    c.post('/demo/select',json={'demo':SID})
    class LiveProbe(llm.LiveLLM):
        def __init__(self): self.last_error=None
        def _ask(self,schema,instruction,facts,model=None):
            assert schema is EstimateDecision
            assert facts['역할 지침']==prompts.load_prompt('agents','t6_zoe')
            return EstimateDecision(duration_changed=False,task=None,days=None,basis='',evidence='')
    with app_env[1]() as db:
        b=store.board(db)
        LiveProbe().reestimate(b.people['zoe'],['목요일 오후 부재'],[b.tasks['Q2']])
    for invalid in ('../t6_zoe','t6/zoe','t6_zoe.md'):
        with pytest.raises(ValueError,match='Invalid prompt name'):
            prompts.load_prompt('agents',invalid)


@pytest.mark.parametrize('seed',[7,17,29])
def test_t6_search_finds_ben_and_sam_with_full_friday_move(app_env,seed):
    from app import hive
    from app.candidates.engine import Settings
    from app.candidates.generator import enumerate_plans,snapshot
    c,f=app_env;c.post('/demo/select',json={'demo':SID})
    with f() as db:
        b=store.board(db);hive.schedule(b);before=snapshot(b)
        candidates,stats=enumerate_plans(b,{'task':'Q2'},[],Settings(seed=seed))
        assert snapshot(b)==before
        ben=[x for x in candidates if any(a['who']=='ben' for a in x['allocations'])]
        sam=[x for x in candidates if any(a['who']=='sam' for a in x['allocations'])]
        assert ben and sam,stats
        assert all('sam' in x['required_confirmations'] for x in sam)
        assert any({'task':'S3','start':4.0} in x['schedule_changes'] for x in sam)
        assert all(x['board']['gate']['ok'] for x in candidates)
        assert stats['search_stop'] in ('enumerated','raw_limit')


def test_t6_sam_only_recovery_and_hard_short_deadline(app_env):
    from app import hive
    from app.candidates.engine import Settings
    from app.candidates.generator import enumerate_plans
    c,f=app_env;c.post('/demo/select',json={'demo':SID})
    with f() as db:
        b=store.board(db);hive.schedule(b)
        b.extra['policies']['ben']['unavailable']=[{'start':3.5,'end':4}]
        candidates,stats=enumerate_plans(b,{'task':'Q2'},[],Settings())
        assert candidates,stats
        assert all(any(a['who']=='sam' for a in x['allocations']) for x in candidates)
        # S17: Friday noon cannot fit the unchanged mandatory QA -> build chain.
        b.week_end=4.5
        candidates,stats=enumerate_plans(b,{'task':'Q2'},[],Settings())
        assert not candidates and stats['rejected']>0


@pytest.mark.parametrize('task,start',[('G1',2),('B2',3),('Q1',2),('Q1',2.5),('A2',4),('S3',4)])
def test_additional_documented_simple_moves_remain_feasible(app_env,task,start):
    from app import hive
    from app.candidates.engine import Settings
    from app.candidates.generator import enumerate_plans
    c,f=app_env;c.post('/demo/select',json={'demo':SID})
    with f() as db:
        b=store.board(db)
        # These are independent source cases, not concurrent S01 absence.
        b.extra['policies']['zoe']['unavailable']=[]
        b.tasks[task].context={**b.tasks[task].context,'requested_start':start,'single_actor':True}
        hive.schedule(b)
        candidates,stats=enumerate_plans(b,{'task':task},[],Settings())
        assert candidates,stats
        assert all(x['board']['gate']['ok'] for x in candidates)
        moved=[t for x in candidates for t in x['board']['tasks'] if t['id']==task]
        assert moved and all(t['start']==start for t in moved)


def test_t6_small_search_budget_is_not_reported_as_impossible(app_env):
    c,_=app_env;c.post('/demo/select',json={'demo':SID})
    r=c.post('/candidate-runs',json={'task_id':'Q2','issue':'Q2 스모크 이관','settings':{'raw_limit':1}}).json()
    assert r['termination']=='search_budget_exhausted'
    assert r['generation']['search_stop']=='raw_limit'
    assert not r['generation']['search_complete']
