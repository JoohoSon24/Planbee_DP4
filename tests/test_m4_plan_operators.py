"""Scope/coverage are code constraints, consent and PM choice are distinct."""
from copy import deepcopy
import pytest
from app import store,hive,workflow
from app.candidates import engine,plans
from app.candidates.generator import canonical

@pytest.fixture
def seeded():
    old=store.DEMO
    def make(sid):
        store.use_demo(sid);e=store.make_engine('sqlite://');db=store.make_session_factory(e)();store.reset(db)
        return e,db
    yield make
    store.use_demo(old)


def run_ready(db):
    f=store.load_yaml('feed.yaml')['issue']
    r=engine.start(db,f['task'],f['records'][0]['text'],engine.Settings(raw_limit=200,candidate_limit=12,shortlist_limit=12,max_rounds=1))
    for _ in range(40):
        if r.status!='running':break
        engine.advance(db,r)
    assert r.status=='awaiting_pm_selection'
    return r


def test_own_rescheduling_preserves_six_hours(seeded):
    e,db=seeded('m4_t1_rescheduling')
    with db:
        r=run_ready(db)
        assert r.ctx['participants']==['dev']
        assert all(next(t for t in c['board']['tasks'] if t['id']=='polish')['days']==.75 for c in r.ctx['candidates'])
        assert not any(m['requester'] in {'art','gd','qa'} for m in r.ctx['public_history'])
    e.dispose()


def test_optional_scope_is_deferred_only_after_pm_and_preserves_effort(seeded):
    e,db=seeded('m4_t3_scope_reduction')
    with db:
        r=run_ready(db);b=store.board(db)
        assert not b.tasks['advanced_effects'].cut and not b.tasks['advanced_fx'].cut
        c=next(c for c in r.ctx['candidates'] if c['id'] in r.ctx['final_candidates'])
        assert 'gd' in c['consents']
        engine.select_pm(db,r,'select',c['id'],c['plan_hash'],'테스트의 모의 PM 승인')
        for cid in r.ctx.get('waiting_for',[]):workflow.confirm(db,cid,True)
        assert r.ctx['termination']=='applied'
        b=store.board(db);hive.schedule(b)
        assert b.tasks['advanced_effects'].cut and b.tasks['advanced_effects'].d==4
        assert b.tasks['advanced_effects'].context['deferred_to']=='Beta'
        assert b.tasks['advanced_fx'].cut and b.tasks['advanced_fx'].d==.5
        assert b.tasks['advanced_fx_done'].d==1 and b.tasks['advanced_fx_done'].kind=='done'
        assert b.tasks['core_integration'].d==1 and not b.tasks['core_integration'].cut
        assert b.tasks['final_qa'].s==7 and b.tasks['final_qa'].d==2 and hive.gate(b)['ok']
    e.dispose()


def test_scope_cannot_remove_required_core_or_change_target_milestone(seeded):
    e,db=seeded('m4_t3_scope_reduction')
    with db:
        r=run_ready(db);b=store.board(db);c=r.ctx['candidates'][0]
        for change in [dict(kind='defer',task='core_integration',milestone='Beta',basis='허용되지 않은 필수 범위 삭제 시도'),dict(kind='defer',task='advanced_effects',milestone='Gamma',basis='허용되지 않은 후속 범위 변경 시도')]:
            with pytest.raises(ValueError,match='이관 권한'):plans.preview(b,r.ctx,c['allocations'],[],[change])
        assert not b.tasks['advanced_effects'].cut
    e.dispose()


def test_qa_omission_requires_own_confirm_and_rejection_rolls_back(seeded):
    e,db=seeded('m4_t4_composite')
    with db:
        r=run_ready(db);b=store.board(db)
        c=next(c for c in r.ctx['candidates'] if c['id'] in r.ctx['final_candidates'] and any(a['kind']=='omit' for a in c.get('plan_actions',[])))
        assert c['required_confirmations']==['qa'] and c['consents']['qa']['action']=='NEEDS_INPUT'
        engine.select_pm(db,r,'select',c['id'],c['plan_hash'],'테스트의 모의 PM 선택')
        assert r.status=='waiting_confirm' and not b.tasks['retest'].cut
        from app.models import Confirmation
        cf=next(db.get(Confirmation,i) for i in r.ctx['waiting_for'] if db.get(Confirmation,i).who=='qa')
        workflow.confirm(db,cf.id,False)
        assert not b.tasks['retest'].cut and b.tasks['anim_integration'].kind!='milestone'
        assert r.ctx.get('termination')!='applied'
    e.dispose()


def test_staged_integration_and_qa_covered_scope_commit_atomically(seeded):
    e,db=seeded('m4_t4_composite')
    with db:
        r=run_ready(db)
        c=next(c for c in r.ctx['candidates'] if c['id'] in r.ctx['final_candidates'] and any(a['kind']=='omit' for a in c.get('plan_actions',[])))
        engine.select_pm(db,r,'select',c['id'],c['plan_hash'],'테스트의 모의 PM 선택')
        for cid in r.ctx.get('waiting_for',[]):workflow.confirm(db,cid,True)
        assert r.ctx['termination']=='applied'
        b=store.board(db);hive.schedule(b)
        staged=[t for t in b.tasks.values() if (t.context or {}).get('partition_of')=='anim_integration']
        assert sorted(t.d for t in staged)==[.25,.75]
        final=next(t for t in staged if t.d==.25)
        assert final.s>=b.tasks['fx_assets'].s+b.tasks['fx_assets'].d
        assert b.tasks['retest'].cut and b.tasks['retest'].context['omitted_in_favor_of']=='final_qa'
        assert b.tasks['final_qa'].d==2 and b.tasks['final_qa'].s==7
        assert b.tasks['critical_fix'].d==1 and hive.gate(b)['ok']
        assert any(h.to_task==final.id and h.from_task=='fx_assets' for h in b.hands.values())
        assert not any(h.to_task=='anim_integration' and h.from_task=='fx_assets' for h in b.hands.values())
    e.dispose()


def test_coverage_and_exact_partitions_cannot_be_forged(seeded):
    e,db=seeded('m4_t4_composite')
    with db:
        r=run_ready(db);b=store.board(db)
        c=next(c for c in r.ctx['candidates'] if any(a['kind']=='omit' for a in c.get('plan_actions',[])))
        bad=deepcopy(c['plan_actions']);next(a for a in bad if a['kind']=='restructure')['parts'][0]['effort']=.5
        with pytest.raises(ValueError,match='분량 보존'):plans.preview(b,r.ctx,c['allocations'],c['schedule_changes'],bad)
        ctx=b.tasks['final_qa'].context;b.tasks['final_qa'].context={**ctx,'coverage':[]}
        with pytest.raises(ValueError,match='대체 검증'):plans.preview(b,r.ctx,c['allocations'],c['schedule_changes'],c['plan_actions'])
        assert not b.tasks['retest'].cut
    e.dispose()


def test_changed_scope_has_new_hash(seeded):
    e,db=seeded('m4_t4_composite')
    with db:
        r=run_ready(db);c=next(c for c in r.ctx['candidates'] if any(a['kind']=='omit' for a in c.get('plan_actions',[])))
        one=canonical(c['allocations'],c['schedule_changes'],c['plan_actions'])
        keep=[a for a in c['plan_actions'] if a['kind']!='omit']
        assert one!=canonical(c['allocations'],c['schedule_changes'],keep)
    e.dispose()


def test_live_same_six_hour_estimate_does_not_round_up():
    import httpx,json
    from types import SimpleNamespace as NS
    from app.llm import LiveLLM
    from app.negotiation_budget import bound
    def response(request):
        value=dict(duration_changed=True,task='polish',days=.75,basis='같은 6h 소요량',evidence='소요량은 6h 그대로입니다')
        return httpx.Response(200,json={'choices':[{'message':{'tool_calls':[{'function':{'arguments':json.dumps(value)}}]}}]})
    llm=LiveLLM(client=httpx.Client(transport=httpx.MockTransport(response)))
    t=NS(id='polish',title='Polish',d=.75,tag='polish',context={'time_quantum':.25})
    p=NS(id='dev',name='Dev',notes={'prompt_role':'dev'})
    with bound(dict(used=0,max=2)):
        answer=llm.reestimate(p,['Polish를 옮기고 싶습니다. 소요량은 6h 그대로입니다'],[t])
    assert answer is None


def test_schedule_only_intent_ignores_contradictory_number():
    import httpx,json
    from types import SimpleNamespace as NS
    from app.llm import LiveLLM
    from app.negotiation_budget import bound
    def response(request):
        value=dict(duration_changed=False,task='polish',days=1,basis='일정 이동만 요청했으므로 소요량은 유지',evidence='6h 그대로')
        return httpx.Response(200,json={'choices':[{'message':{'tool_calls':[{'function':{'arguments':json.dumps(value)}}]}}]})
    llm=LiveLLM(client=httpx.Client(transport=httpx.MockTransport(response)))
    t=NS(id='polish',title='Polish',d=.75,tag='polish',context={'time_quantum':.25})
    with bound(dict(used=0,max=2)):
        ans=llm.reestimate(NS(id='dev',name='Dev',notes={}),['Polish 이동, 6h 그대로'],[t])
    assert ans is None


def test_effective_schedule_is_unique_even_with_noop_release_hints(seeded):
    e,db=seeded('m4_t2_reallocation')
    with db:
        r=run_ready(db)
        # release Bug Fix at 5, 5.75 or 6 still executes it at 6 after UI logic.
        signatures=[]
        for c in r.ctx['candidates']:
            signatures.append(tuple(sorted((t['id'],t['who'],t['start'],t['days'],t['kind']) for t in c['board']['tasks'])))
        assert len(signatures)==len(set(signatures))
        assert len(r.ctx['candidates'])==1
    e.dispose()
