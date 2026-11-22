"""Integration checks using real scheduling, persistence and versioned consent."""
from copy import deepcopy

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import discussion, hive, llm, store, workflow
from app.llm import DiscussionReply
from app.models import Base, Card, Confirmation, Handoff, Meta, Person, Rule, Run, Task


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('PLANBEE_RUNS_DIR', str(tmp_path / 'runs'))
    engine = store.make_engine('sqlite://')
    with Session(engine) as db:
        for i, pid in enumerate('abc'):
            db.add(Person(id=pid, name=pid, role='dev', rec={'code': 3}, oi=i))
            db.add(Card(person_id=pid, auto_days=5, note='private-'+pid))
        db.add_all([Rule(key='rounds', label='rounds', value={'max': 10}),
                    Rule(key='weekly_cap', label='capacity', value={'days': 5}),
                    Rule(key='deadline', label='deadline', value={'week_end': 5}),
                    Meta(key='now', value={'v': 0}), Meta(key='phase', value={'v': 'run'})])
        db.add(Task(id='work', who='a', title='work', s0=0, s=0, d=4, plan=4, base=4, tag='code', role='dev', oi=0))
        db.add(Task(id='end', who='a', title='end', s0=0, s=0, d=0, plan=0, base=0, tag='code', role='dev', kind='milestone', oi=10))
        db.add(Handoff(id='h', from_task='work', to_task='end', title='deliver', what='deliver', t=5, oi=0))
        run = Run(kind='record', step='bids', auto_confirm=True, ctx=dict(
            task='work', hid='h', rebalance_reason='fairness', candidate_ids=['b','c'], round=0,
            split=dict(piece=dict(title='piece', days=2, tag='code', what='piece'), to='self')))
        db.add(run)
        db.flush()
        before = llm.get_llm()
        yield db, run
        llm.set_llm(before)
        store.mark(None, 0)
    engine.dispose()


def proposal(*parts):
    return [dict(who=pid, title=title, days=days, effort=effort, what=title) for pid,title,days,effort in parts]


class Script:
    def __init__(self, fn):
        self.fn, self.calls = fn, []

    def discuss(self, person, card, context):
        self.calls.append((person.id, deepcopy(context)))
        # Only the acting proxy's card is supplied; no other private strings in context.
        assert all('private-'+p not in str(context) for p in 'abc')
        return self.fn(person.id, card, context)


def accept(pid, card, c):
    return DiscussionReply(action='ACCEPT', reason='settings allow')


def drive(db, run):
    for _ in range(30):
        if run.step == 'bids':
            discussion.turn(db, run)
        elif run.step == 'discussion_commit':
            discussion.commit(db, run)
        else:
            break
        db.flush()
        if run.status != 'running':
            break
    return run.ctx['discussion']


def test_reject_revise_accept(env):
    db, run = env
    revised = proposal(('b','smaller execution',1.5,2))
    def fn(pid, card, c):
        if c['version'] == 1:
            return DiscussionReply(action='REJECT', reason='need narrower execution') if c['mode']=='respond' else DiscussionReply(action='COUNTER', reason='reflect rejection', allocations=revised)
        assert any(e['reason']=='need narrower execution' for e in c['history'])
        return accept(pid,card,c)
    adapter = Script(fn)
    llm.set_llm(adapter)
    state = drive(db,run)
    assert state['termination']=='agreement' and state['version']==2
    assert db.get(Task,'work').d==2
    assert any(e['response']=='REJECT' for e in state['history'])
    assert {'a','b'} <= set(state['consents'])
    assert not hive.risks(store.board(db))


def test_third_party_and_reconsent(env):
    db, run = env
    shared = proposal(('b','part one',1,1),('c','part two',1,1))
    def fn(pid, card, c):
        if pid=='a' and c['version']==1:
            return DiscussionReply(action='COUNTER', reason='share with c', allocations=shared)
        return accept(pid,card,c)
    adapter=Script(fn); llm.set_llm(adapter)
    state=drive(db,run)
    assert state['termination']=='agreement'
    assert {t.who for t in db.scalars(select(Task).where(Task.kind=='new'))}=={'b','c'}
    assert [c['version'] for pid,c in adapter.calls if pid=='b']==[1,2]
    assert set(state['consents'])=={'a','b','c'}


def test_multiple_participants_repeated_counteroffers(env):
    db,run=env
    def fn(pid, card, c):
        if c['version']<4 and c['mode']=='respond':
            return DiscussionReply(action='REJECT',reason=f'{pid} settings require revision {c["version"]}')
        if c['mode']=='revise':
            v=c['version']
            return DiscussionReply(action='COUNTER', reason=f'{pid} revised from feedback',
                allocations=proposal(('b' if v%2==0 else 'c',f'revision {v}',1+v*.1,2)))
        return accept(pid,card,c)
    llm.set_llm(Script(fn))
    state=drive(db,run)
    assert state['version']==4 and state['termination']=='agreement'
    assert len([e for e in state['history'] if e['response']=='REJECT'])==3
    assert len({e['requester'] for e in state['history'] if e['response']=='COUNTER'})>=2


def test_deadline_violation_blocked(env):
    db,run=env
    def fn(pid,card,c):
        if c['version']==1:
            return DiscussionReply(action='COUNTER',reason='slow alternative',allocations=proposal(('b','slow',6,2)))
        return DiscussionReply(action='PASS',reason='no safer alternative')
    llm.set_llm(Script(fn))
    state=drive(db,run)
    assert state['termination']=='no_valid_alternative'
    assert any(e['response']=='BLOCKED' and '데드라인' in e['reason'] for e in state['history'])
    assert db.get(Task,'work').d==4 and len(list(db.scalars(select(Task))))==2


@pytest.mark.parametrize('limit, expected', [(1,'max_rounds'),(10,'no_valid_alternative')])
def test_failure_keeps_original(env,limit,expected):
    db,run=env
    db.get(Rule,'rounds').value={'max':limit}
    llm.set_llm(Script(lambda pid,card,c: DiscussionReply(action='REJECT' if c['mode']=='respond' else 'PASS', reason='cannot agree')))
    state=drive(db,run)
    assert state['termination']==expected
    assert db.get(Task,'work').d==4 and len(list(db.scalars(select(Task))))==2


def test_pending_confirmation_persists_and_rejection_invalidates(env):
    db,run=env
    run.auto_confirm=False
    db.get(Card,'b').auto_days=.5
    llm.set_llm(Script(accept))
    discussion.turn(db,run)
    assert run.step=='discussion_commit' and db.get(Task,'work').d==4
    db.commit()
    db.expire_all()
    run=db.get(Run,run.id)
    discussion.commit(db,run)
    assert run.status=='waiting_confirm'
    cf=db.get(Confirmation,run.ctx['waiting_for'][0])
    workflow.apply_confirm(db,cf,False)
    discussion.commit(db,run)
    assert run.ctx['discussion']['consents']=={}
    assert db.get(Task,'work').d==4


def test_api_exposes_version_history(env):
    db,run=env
    llm.set_llm(Script(accept))
    drive(db,run)
    data=store.negotiation_json(db,run)
    assert data['discussion']['termination']=='agreement'
    assert data['rounds'] and data['fairness_before'] and data['fairness_after']


def test_schedule_change_requires_fresh_consent(env):
    db,run=env
    run.auto_confirm=False
    db.get(Card,'b').auto_days=.5
    adapter=Script(accept); llm.set_llm(adapter)
    discussion.turn(db,run)
    cf=db.get(Confirmation,run.ctx['waiting_for'][0])
    workflow.apply_confirm(db,cf,True)
    db.get(Task,'work').s0=.25
    discussion.commit(db,run)
    assert run.step=='bids' and not run.ctx['discussion']['consents']
    assert db.get(Task,'work').d==4
    assert run.ctx['discussion']['history'][-1]['response']=='SCHEDULE_CHANGED'
    discussion.turn(db,run)
    assert len([c for pid,c in adapter.calls if pid=='b'])==2


def test_deadline_rejections_continue_with_all_participants(env):
    db,run=env
    workflow.patch(run, rebalance_reason='deadline', replies=[dict(who='b',type='REJECT',reason='split further')])
    assert discussion.from_rejections(db,run)
    shared=proposal(('b','first',1,1),('c','second',1,1))
    def fn(pid,card,c):
        if c['mode']=='revise':
            assert any(e['reason']=='split further' for e in c['history'])
            return DiscussionReply(action='COUNTER',reason='share with c',allocations=shared)
        return accept(pid,card,c)
    llm.set_llm(Script(fn))
    drive(db,run)
    assert run.step=='fairness_gate'
    assert run.ctx['discussion_archive'][-1]['termination']=='agreement'
    assert {x.who for x in db.scalars(select(Task).where(Task.kind=='new'))}=={'b','c'}


def test_schedule_changes_while_waiting_prevent_commit(env):
    db, run = env
    run.auto_confirm = False
    db.get(Card, 'b').auto_days = .5
    llm.set_llm(Script(accept))
    discussion.turn(db, run)
    discussion.commit(db, run)
    cf = db.get(Confirmation, run.ctx['waiting_for'][0])
    workflow.apply_confirm(db, cf, True)
    # Concurrently assigned work changes the validated schedule before consent returns.
    db.add(Task(id='urgent', who='b', title='urgent', s0=0, s=0, d=4, plan=4,
                base=4, tag='code', role='dev', oi=-1))
    db.flush()
    discussion.commit(db, run)
    assert run.ctx['discussion']['termination'].startswith('commit_validation_failed')
    assert db.get(Task, 'work').d == 4
    assert not list(db.scalars(select(Task).where(Task.kind == 'new')))


def test_live_discussion_receives_only_own_private_card(env, monkeypatch):
    db, run = env
    adapter = llm.LiveLLM(client=object())
    captured = []
    def ask(schema, instruction, facts, model):
        captured.append(deepcopy(facts))
        return llm.ConsentDecision(settings_check='compatible',settings_reason='own settings allow',max_incoming_days=None,action='ACCEPT', reason='own settings allow')
    monkeypatch.setattr(adapter, '_ask', ask)
    llm.set_llm(adapter)
    drive(db, run)
    assert captured
    for facts in captured:
        own = facts['self']['id']
        assert facts['my_delegation']['note'] == 'private-'+own
        assert all('private-'+pid not in str(facts) for pid in 'abc' if pid != own)


def test_duplicate_counter_is_blocked(env):
    db, run = env
    def fn(pid, card, c):
        return DiscussionReply(action='COUNTER', reason='same proposal', allocations=c['proposal'])
    llm.set_llm(Script(fn))
    state = drive(db, run)
    assert state['termination'] == 'no_valid_alternative'
    assert any(e['response'] == 'BLOCKED' and '동일' in e['reason'] for e in state['history'])
    assert db.get(Task, 'work').d == 4


def test_multiple_rounds_are_driven_by_each_actors_delegation(env):
    db, run = env
    db.get(Card, 'b').auto_days = .75
    db.get(Card, 'c').auto_days = .5
    def fn(pid, card, c):
        mine = [a for a in c['proposal'] if a['who'] == pid]
        if c['mode'] == 'respond':
            if sum(a['days'] for a in mine) > card.auto_days:
                return DiscussionReply(action='REJECT', reason=f'{pid}: my delegated limit is {card.auto_days}')
            return accept(pid, card, c)
        # Each actor sizes only its own contribution from its private setting.
        # Others' limits are learned only through the public rejection feedback.
        if pid == 'b' and c['version'] == 1:
            return DiscussionReply(action='COUNTER', reason='I can do .75; ask c for the rest',
                allocations=proposal(('b','first',card.auto_days,1),('c','second',1.25,1)))
        if pid == 'c' and c['version'] == 2:
            assert any('c: my delegated limit' in e['reason'] for e in c['history'])
            revised = deepcopy(c['proposal'])
            next(a for a in revised if a['who'] == pid)['days'] = card.auto_days
            return DiscussionReply(action='COUNTER', reason='I can execute my share in .5', allocations=revised)
        return DiscussionReply(action='PASS', reason='no further alternative from my settings')
    llm.set_llm(Script(fn))
    state = drive(db, run)
    assert state['termination'] == 'agreement' and state['version'] == 3
    assert run.ctx['round'] == 5
    assert {e['requester'] for e in state['history'] if e['response'] == 'REJECT'} == {'b','c'}
    assert {e['requester'] for e in state['history'] if e['response'] == 'COUNTER'} == {'b','c'}


def test_run_transcript_refreshes_each_message_and_resumes_same_file(env, tmp_path):
    from pathlib import Path
    import re
    db, run = env
    filename = run.ctx['transcript_file']
    assert re.fullmatch(r'mock/\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_\d{6}_[a-f0-9]{8}\.md', filename)
    path = tmp_path / 'runs' / filename
    assert path.exists()
    store.mark(1)
    store.say(db, 'a', 'REQUEST', [store.F('first request')], to='b', run_id=run.id)
    assert 'a (a) → b (b)' in path.read_text() and 'first request' in path.read_text()
    store.say(db, 'b', 'REJECT', [store.F('second reply')], to='a', run_id=run.id)
    transcript = path.read_text()
    assert transcript.index('first request') < transcript.index('second reply')
    db.commit()
    db.expire_all()
    resumed = db.get(Run, run.id)
    assert resumed.ctx['transcript_file'] == filename
    store.hive_say(db, 'deadline validation completed', run_id=run.id)
    assert 'Hive → 전체 참여자' in path.read_text()
    assert 'deadline validation completed' in path.read_text()
    assert len(list((tmp_path / 'runs').rglob('*.md'))) == 1
    assert all('private-'+pid not in path.read_text() for pid in 'abc')


def test_run_transcript_includes_hive_turns_and_milestone_changes(env, tmp_path):
    db, run = env
    workflow.patch(run, split={**run.ctx['split'], 'keep': {'title':'remaining','days':1}})
    llm.set_llm(Script(accept))
    workflow.drive(db, run)
    assert run.status == 'done'
    transcript = (tmp_path / 'runs' / run.ctx['transcript_file']).read_text()
    assert '초기 milestone' in transcript and '현재 / 최종 milestone' in transcript
    assert '이 턴 이후 milestone' in transcript
    assert 'discussion_commit · Hive' in transcript
    assert run.ctx['execution_turns'][-1]['status_after'] == 'done'
    assert run.ctx['initial_milestones']['milestones'][0]['end'] == 4
    from app.runlogs import milestones
    assert milestones(db)['milestones'][0]['end'] == 3
    assert '"deadline": 5' in transcript
    assert '상태: done · 단계: done' in transcript


def test_reset_run_ids_do_not_overwrite_existing_transcript(env, tmp_path):
    db, run = env
    first = run.ctx['transcript_file']
    db.delete(run)
    db.flush()
    another = Run(id=run.id, kind='record', step='bids', ctx={})
    db.add(another)
    db.flush()
    assert another.ctx['transcript_file'] != first
    assert len(list((tmp_path / 'runs').rglob('*.md'))) == 2


def whole_partition():
    return [dict(who='a',title='상태 전이 코어',days=2,effort=2,what='상태 전이 구현',key='core',depends_on=[]),
            dict(who='b',title='정상 계약 검증',days=1,effort=1,what='정상 경로 검증',key='normal',depends_on=['core']),
            dict(who='c',title='실패 계약 검증',days=1,effort=1,what='실패 경로 검증',key='failure',depends_on=['core'])]


def test_entire_original_task_can_be_repartitioned_and_dependency_dates_preserved(env):
    db,run=env
    db.get(Handoff,'h').t=3
    workflow.patch(run,rebalance_reason='deadline',replies=[dict(who='b',type='REJECT',reason='원 업무 전체를 다시 나누자')])
    discussion.from_rejections(db,run)
    def fn(pid,card,c):
        if c['mode']=='revise':
            assert c['original_task']['days']==4 and c['phase']=='deadline'
            return DiscussionReply(action='COUNTER',proposal_scope='whole_task',allocations=whole_partition(),reason='코어 2일 뒤 정상/실패 검증을 병렬 실행')
        assert c['proposal_scope']=='whole_task'
        return accept(pid,card,c)
    llm.set_llm(Script(fn));drive(db,run)
    assert run.step=='fairness_gate'
    state=run.ctx['discussion_archive'][-1]
    assert state['scope']=='whole_task' and state['termination']=='agreement'
    assert db.get(Task,'work').kind=='milestone' and db.get(Task,'work').d==0
    assert db.get(Handoff,'h').t==3
    b=store.board(db);hive.schedule(b)
    chunks={t.title:t for t in b.tasks.values() if t.kind=='new'}
    assert chunks['정상 계약 검증'].s==chunks['실패 계약 검증'].s==2
    assert hive.pred(b,b.hands['h'])==3 and not hive.risks(b)
    assert run.ctx['feasible_baseline']['tasks']['work']['kind']=='milestone'
    assert sum(t.base for t in chunks.values())==4


def test_whole_task_scope_rejects_missing_work_and_cyclic_parts(env):
    db,run=env;b=store.board(db)
    missing=whole_partition();missing[0]['effort']=1
    with pytest.raises(ValueError,match='전체 분량'):
        discussion.preview(b,run.ctx,missing,'whole_task')
    cyclic=whole_partition();cyclic[0]['depends_on']=['normal']
    with pytest.raises(ValueError,match='순환'):
        discussion.preview(b,run.ctx,cyclic,'whole_task')
    assert db.get(Task,'work').d==4


def test_more_than_five_rounds_can_reach_agreement(env):
    db,run=env;db.get(Rule,'rounds').value={'max':15}
    def fn(pid,card,c):
        if c['version']>=6:return accept(pid,card,c)
        if c['mode']=='respond':return DiscussionReply(action='REJECT',reason=f'조건 {c["version"]} 수정 필요')
        return DiscussionReply(action='COUNTER',reason='피드백을 반영한 다음 범위',allocations=proposal(('b',f'범위 {c["version"]}',1+c['version']*.05,2)))
    llm.set_llm(Script(fn));state=drive(db,run)
    assert state['termination']=='agreement' and run.ctx['round']==11


def test_deadline_repair_precedes_fairness_and_freezes_agreed_baseline(env):
    db,run=env;db.get(Handoff,'h').t=3
    class Agent(llm.MockLLM):
        def discuss(self,person,card,c):
            if c['mode']=='revise':return DiscussionReply(action='COUNTER',proposal_scope='whole_task',allocations=whole_partition(),reason='원 업무를 코어와 병렬 검증으로 분해')
            return DiscussionReply(action='ACCEPT',reason='내 역할과 일정에 동의')
    llm.set_llm(Agent());workflow.patch(run,who='a',records=['분담 논의'],phase_after='end')
    run.step='ingest';workflow.drive(db,run)
    nodes=[t['node'] for t in run.ctx['execution_turns']]
    assert nodes.index('discussion_commit')<nodes.index('fairness_gate')
    assert run.ctx['feasible_baseline'] and run.status=='done'
    assert not hive.risks(store.board(db))


def test_fairness_failure_cannot_destroy_agreed_deadline_solution(env):
    db,run=env;db.get(Handoff,'h').t=3
    workflow.patch(run,rebalance_reason='deadline',replies=[dict(who='b',type='REJECT',reason='전체 재분해 필요')])
    discussion.from_rejections(db,run)
    def fn(pid,card,c):
        if c['mode']=='revise':return DiscussionReply(action='COUNTER',proposal_scope='whole_task',allocations=whole_partition(),reason='코어·정상·실패 분해')
        return accept(pid,card,c)
    llm.set_llm(Script(fn));drive(db,run)
    before={t.id:(t.who,t.d,t.s0,t.kind) for t in db.scalars(select(Task))}
    db.add(Rule(key='fairness',label='모든 부담 검토',value={'min_range':0,'min_gap':.5}));db.flush()
    class NoAgreement(llm.MockLLM):
        def discuss(self,person,card,context):
            return DiscussionReply(action='PASS' if context['mode']=='revise' else 'REJECT',reason='새 변경에 동의하지 않음')
    llm.set_llm(NoAgreement());workflow.drive(db,run)
    assert run.status=='done' and run.ctx['discussion']['termination']=='no_valid_alternative'
    assert {t.id:(t.who,t.d,t.s0,t.kind) for t in db.scalars(select(Task))}==before
    assert not hive.risks(store.board(db))


def test_partial_piece_dependency_is_never_silently_ignored(env):
    db,run=env;parts=proposal(('b','first',1,1),('c','second',1,1))
    parts[0]['key']='first';parts[1]['depends_on']=['first']
    with pytest.raises(ValueError,match='whole_task'):
        discussion.preview(store.board(db),run.ctx,parts)


def test_unsplittable_task_can_be_transferred_whole_after_all_party_agreement(env):
    db,run=env
    source=db.get(Task,'work');source.context={'splittable_hint':False}
    db.get(Handoff,'h').t=3
    workflow.patch(run,rebalance_reason='deadline')
    assert discussion.begin_whole(db,run)
    def fn(pid,card,c):
        if c['mode']=='revise':
            return DiscussionReply(action='COUNTER',proposal_scope='whole_task',reason='분해 없이 전부 담당',
                allocations=proposal(('b','전체 구현',3,4)))
        return accept(pid,card,c)
    adapter=Script(fn);llm.set_llm(adapter);drive(db,run)
    state=run.ctx['discussion_archive'][-1]
    assert state['termination']=='agreement' and {'a','b'}<=set(state['consents'])
    assert source.who=='b' and source.d==3 and source.kind!='milestone'
    assert db.get(Handoff,'h').from_task=='work' and db.get(Handoff,'h').t==3
    assert not list(db.scalars(select(Task).where(Task.id.like('part%'))))
    assert any(e['response']=='FINAL_CONSTRAINT_CHECK' and e['requester']=='hive' for e in state['history'])


def test_schedule_counter_reorders_tasks_and_requires_other_affected_owners(env):
    db,run=env
    db.get(Handoff,'h').t=4
    db.add(Task(id='busy',who='b',title='기존 작업',s0=0,s=0,d=3,plan=3,base=3,tag='code',role='dev',oi=1))
    db.add(Task(id='docs',who='c',title='문서',s0=1,s=1,d=.5,plan=.5,base=.5,tag='code',role='dev',oi=2))
    db.flush()
    changes=[dict(task='busy',start=2),dict(task='docs',start=2)]
    def fn(pid,card,c):
        if c['mode']=='revise':
            return DiscussionReply(action='COUNTER',reason='마감 유지하며 기존 작업 순서 조정',schedule_changes=changes)
        assert c['schedule_changes']==changes
        return accept(pid,card,c)
    adapter=Script(fn);llm.set_llm(adapter);state=drive(db,run)
    assert state['termination']=='agreement' and state['version']==2
    assert next(e for e in state['history'] if e['response']=='COUNTER')['schedule_changes']==changes
    assert {'a','b','c'}<=set(state['consents'])
    assert any(pid=='c' for pid,_ in adapter.calls)
    b=store.board(db);hive.schedule(b)
    assert b.tasks['busy'].s0==b.tasks['docs'].s0==2
    assert hive.pred(b,b.hands['h'])==4 and hive.gate(b)['ok']
    events=[e['response'] for e in state['history']]
    assert events.index('FINAL_CONSTRAINT_CHECK')<events.index('AGREED')


def test_invalid_schedule_move_or_failed_consent_never_applies(env):
    db,run=env
    db.add(Task(id='later',who='b',title='later',s0=1,s=1,d=1,plan=1,base=1,tag='code',role='dev',oi=1))
    db.flush();b=store.board(db);hive.schedule(b)
    for start in [-1,5,float('inf')]:
        with pytest.raises(ValueError):
            discussion.preview(b,run.ctx,proposal(('b','piece',1,2)),schedule_changes=[dict(task='later',start=start)])
    db.get(Rule,'rounds').value={'max':2}
    def fn(pid,card,c):
        if c['mode']=='respond':return DiscussionReply(action='REJECT',reason='일정 변경 동의 안함')
        return DiscussionReply(action='COUNTER',reason='시간 이동',schedule_changes=[dict(task='later',start=2)])
    llm.set_llm(Script(fn));state=drive(db,run)
    assert state['termination']=='max_rounds'
    assert db.get(Task,'later').s0==1 and db.get(Task,'work').d==4


def test_schedule_only_change_clears_prior_acceptance_and_invites_affected_owner(env):
    db,run=env
    db.add(Task(id='docs',who='c',title='docs',s0=1,s=1,d=.5,plan=.5,base=.5,tag='code',role='dev',oi=1));db.flush()
    def fn(pid,card,c):
        if c['version']==1 and pid=='a':
            return DiscussionReply(action='COUNTER',reason='문서 순서까지 새 합의',schedule_changes=[dict(task='docs',start=2)])
        return accept(pid,card,c)
    adapter=Script(fn);llm.set_llm(adapter);state=drive(db,run)
    assert state['termination']=='agreement'
    assert [c['version'] for pid,c in adapter.calls if pid=='b']==[1,2]
    assert {e['requester'] for e in state['history'] if e['version']==2 and e['response']=='ACCEPT'}=={'a','b','c'}


def test_live_style_scope_and_duplicate_errors_are_repaired_before_version_acceptance(env):
    """Replay the malformed partial-as-whole/duplicate descriptions in the Live logs."""
    db,run=env
    store.set_meta(db,'now',2);db.get(Handoff,'h').t=3
    workflow.patch(run,rebalance_reason='deadline')
    fixed=[dict(who='a',title='기존 코어',what='기존 상태 전이 코어',days=3,effort=3,key='core'),
           dict(who='b',title='정상 샘플',what='독립 정상 경로 픽스처',days=.5,effort=.5,key='normal'),
           dict(who='c',title='실패 샘플',what='독립 실패 경로 픽스처',days=.5,effort=.5,key='failure')]
    def fn(pid,card,c):
        if c['mode']=='respond':return accept(pid,card,c)
        assert c['proposal_contract']['whole_task']['required_effort']==4
        if not c.get('validation_feedback'):
            return DiscussionReply(action='COUNTER',proposal_scope='whole_task',reason='기존 Live 응답 재현',allocations=[
                dict(who='a',title='검증',what='동일 검증 작업',days=1,effort=1),
                dict(who='b',title='검증',what='동일 검증 작업',days=1,effort=1)])
        codes={x['code'] for x in c['validation_feedback']}
        assert {'EFFORT_SUM','DUPLICATE_SCOPE'}<=codes
        return DiscussionReply(action='COUNTER',proposal_scope='whole_task',reason='보유분과 독립 범위 복구',allocations=fixed,
                               schedule_changes=[dict(task='work',start=0)])
    adapter=Script(fn);adapter.supports_discussion_repair=True;llm.set_llm(adapter)
    drive(db,run);state=run.ctx['discussion_archive'][-1]
    assert state['termination']=='agreement' and state['version']==2
    assert any(e['response']=='REPAIR_REQUEST' for e in state['history'])
    b=store.board(db);hive.schedule(b)
    chunks=[t for t in b.tasks.values() if t.kind=='new']
    assert next(t for t in chunks if t.who=='a').s0==0
    assert all(t.s0>=2 for t in chunks if t.who!='a')
    assert hive.pred(b,b.hands['h'])==3 and hive.gate(b)['ok']
    assert set(state['consents'])=={'a','b','c'}


def test_protocol_repairs_are_bounded_and_do_not_invent_a_valid_allocation(env):
    db,run=env
    def fn(pid,card,c):
        if c['mode']=='respond':return DiscussionReply(action='REJECT',reason='수정 필요')
        return DiscussionReply(action='COUNTER',reason='잘못된 분량',allocations=proposal(('b','조각',1,1)))
    adapter=Script(fn);adapter.supports_discussion_repair=True;llm.set_llm(adapter)
    state=drive(db,run)
    assert state['termination']=='no_valid_alternative'
    revise=[c for _,c in adapter.calls if c['mode']=='revise']
    # Repeating the same error stops before a third attempt.
    from collections import Counter
    counts=Counter((pid,c['recovery_strategy']) for pid,c in adapter.calls if c['mode']=='revise')
    assert max(counts.values())<=2 and max(c.get('repair_attempt',0) for c in revise)==1
    assert {c['recovery_strategy'] for c in revise}=={'independent_split','whole_transfer','move_other_work','collaborate'}
    assert db.get(Task,'work').d==4 and state['version']==1 and not state['consents']


def test_independent_downstream_part_must_meet_original_handoff_deadline(env):
    db,run=env
    store.set_meta(db,'now',1);db.get(Handoff,'h').t=3
    workflow.patch(run,split={**run.ctx['split'],'to':'downstream'})
    b=store.board(db);hive.schedule(b)
    with pytest.raises(ValueError,match='데드라인'):
        discussion.preview(b,run.ctx,proposal(('b','늦은 독립 조각',2.5,2)))


def test_pm_handoff_summary_is_public_and_includes_failure_and_last_proposal(env):
    db,run=env
    llm.set_llm(Script(lambda pid,card,c: DiscussionReply(action='REJECT' if c['mode']=='respond' else 'PASS',reason='분담 합의 안됨')))
    drive(db,run)
    summary=run.ctx['pm_handoff']['summary']
    assert summary['title']=='work' and summary['termination']=='no_valid_alternative'
    assert summary['proposal']['allocations'] and summary['history']
    assert not summary['review_required'] and '기한 충족' in summary['disposition']
    assert all('private-'+p not in str(summary) for p in 'abc')
    from app.runlogs import directory
    transcript=(directory()/run.ctx['transcript_file']).read_text()
    assert 'PM 전달 · 현재 상황 summary' in transcript


def test_pm_ask_api_exposes_summary_and_supports_older_requests(env):
    from app.models import Ask
    db,run=env
    ask=Ask(hid='h',run_id=run.id,why=['합의 실패'],grants=[dict(key='retry',label='재협상',effect='라운드 확대')])
    db.add(ask);db.flush()
    summary=store.ask_json(ask,db)['summary']
    assert summary['review_required'] and summary['reasons']==['합의 실패']
    assert summary['options'][0]['label']=='재협상'
    assert 'private-' not in str(summary)
    workflow.patch(run,pm_handoff=dict(summary={**summary,'termination':'max_rounds'}))
    assert store.ask_json(ask,db)['summary']['termination']=='max_rounds'


def test_exhausted_initial_pair_invites_third_agent_before_giving_up(env):
    db,run=env
    def respond(pid,card,c):
        if c['mode']=='respond':
            return DiscussionReply(action='REJECT' if c['version']==1 else 'ACCEPT',reason='최초 분량 거절' if c['version']==1 else '새 전체 배분 동의')
        if pid!='c':return DiscussionReply(action='PASS',reason='두 사람만으로 대안 없음')
        assert any(e['response']=='INVITE' for e in c['history'])
        assert any(e['reason']=='최초 분량 거절' for e in c['history'])
        return DiscussionReply(action='COUNTER',proposal_scope='whole_task',reason='제3자도 독립 검증 분담',
            allocations=proposal(('a','코어',2,2),('b','정상 검증',1,1),('c','실패 검증',1,1)))
    adapter=Script(respond);llm.set_llm(adapter)
    state=drive(db,run)
    assert state['termination']=='agreement' and set(state['consents'])=={'a','b','c'}
    assert [pid for pid,c in adapter.calls if c['mode']=='revise'].count('b')==1
    assert [pid for pid,c in adapter.calls if c['mode']=='revise'].count('a')==1
    b=store.board(db);hive.schedule(b)
    assert hive.gate(b)['ok']


def test_retained_core_keeps_lane_priority_in_preview_and_commit(env):
    db,run=env
    db.add(Task(id='later',who='a',title='후속 독립 업무',s0=0,s=0,d=1,plan=1,base=1,tag='code',role='dev',oi=1))
    db.get(Handoff,'h').t=3
    workflow.patch(run,rebalance_reason='deadline')
    def respond(pid,card,c):
        if c['mode']=='respond' and c['version']>1:return DiscussionReply(action='ACCEPT',reason='코어 우선 순서 보존 동의')
        if c['mode']=='respond':return DiscussionReply(action='REJECT',reason='전체 재분해 필요')
        return DiscussionReply(action='COUNTER',proposal_scope='whole_task',reason='코어와 독립 검증 병렬',
            allocations=proposal(('a','코어',3,3),('b','독립 검증',1,1)))
    llm.set_llm(Script(respond));drive(db,run)
    state=run.ctx.get('discussion') or run.ctx['discussion_archive'][-1]
    assert state['termination']=='agreement'
    b=store.board(db);hive.schedule(b)
    core=next(t for t in b.tasks.values() if t.title=='코어')
    assert core.s==0 and b.tasks['later'].s==3
    assert hive.pred(b,b.hands['h'])==3 and hive.gate(b)['ok']


def test_transport_failure_is_not_reported_as_exhausted_negotiation(env):
    db,run=env
    adapter=Script(lambda pid,card,c: DiscussionReply(action='REJECT' if c['mode']=='respond' else 'PASS',reason='모델 호출 불가'))
    adapter.last_discussion_error={'type':'HTTPStatusError','status':503}
    llm.set_llm(adapter);state=drive(db,run)
    assert state['termination']=='model_unavailable'
    assert any(e['response']=='MODEL_UNAVAILABLE' for e in state['history'])
    assert not state['consents'] and db.get(Task,'work').d==4


def test_public_limits_constrain_reference_patterns_without_selecting_a_plan(env):
    from app.negotiation_options import patterns
    from app.negotiation_contract import feedback
    db,run=env;b=store.board(db);hive.schedule(b)
    before=discussion.schedule_signature(b)
    options=patterns(b,run.ctx,{'b':.5,'c':.75})
    assert options and discussion.schedule_signature(b)==before
    for option in options:
        assert sum(a['effort'] for a in option)==4
        assert all(a['days']<={'b':.5,'c':.75}.get(a['who'],10) for a in option)
    state={'proposal':proposal(('b','조각',2,2)),'scope':'piece','seen':[], 'public_limits':{'b':.5}}
    issues=feedback(b,run.ctx,state,DiscussionReply(action='COUNTER',allocations=state['proposal'],reason='기존 안 반복'),'revise')
    assert any(i['code']=='PUBLIC_LIMIT' for i in issues)


def test_unsplittable_whole_transfer_can_move_another_task_with_all_owners_consent(env):
    db,run=env
    db.get(Task,'work').context={'splittable_hint':False,'description':'원자적 계약 검증'}
    db.get(Handoff,'h').t=4
    db.add(Task(id='busy',who='b',title='다른 업무',s0=0,s=0,d=3,plan=3,base=3,tag='code',role='dev',oi=1))
    def respond(pid,card,c):
        assert c['original_task']['context']['description']=='원자적 계약 검증'
        if c['mode']=='respond' and c['version']>1:return accept(pid,card,c)
        if c['mode']=='respond':return DiscussionReply(action='REJECT',reason='분할 대신 다른 업무를 옮겨 전체 양도')
        return DiscussionReply(action='COUNTER',proposal_scope='whole_task',reason='기존 업무 이동과 원자적 양도',
            allocations=proposal(('b','원자적 계약 검증',4,4)),schedule_changes=[dict(task='busy',who='c')])
    llm.set_llm(Script(respond));state=drive(db,run)
    assert state['termination']=='agreement' and set(state['consents'])=={'a','b','c'}
    assert db.get(Task,'busy').who=='c' and db.get(Task,'work').who=='b'
    b=store.board(db);hive.schedule(b);assert hive.gate(b)['ok']


def test_unsplittable_work_can_shorten_with_explicit_consented_support(env):
    db,run=env;db.get(Handoff,'h').t=3
    db.get(Task,'work').context={'splittable_hint':False}
    def respond(pid,card,c):
        if c['mode']=='respond' and c['version']>1:return accept(pid,card,c)
        if c['mode']=='respond':return DiscussionReply(action='REJECT',reason='분리하지 않고 공동 검토로 단축')
        return DiscussionReply(action='COUNTER',proposal_scope='whole_task',reason='검증 책임 유지·독립 지원',
            allocations=proposal(('a','원자적 검증',3,4)),schedule_changes=[dict(task='work',basis='지원자가 재현 환경을 준비해 주 담당의 반복 검증 시간을 줄임',support=[dict(who='b',days=.5,what='재현 환경 준비와 공동 리뷰')])])
    llm.set_llm(Script(respond));drive(db,run)
    state=run.ctx.get('discussion') or run.ctx['discussion_archive'][-1]
    assert state['termination']=='agreement' and set(state['consents'])=={'a','b'}
    assert db.get(Task,'work').d==3 and db.get(Task,'work').base==4
    b=store.board(db);hive.schedule(b)
    helpers=[t for t in b.tasks.values() if (t.context or {}).get('collaboration_for')=='work']
    assert len(helpers)==1 and helpers[0].who=='b' and helpers[0].d==.5 and hive.gate(b)['ok']


def test_unsupported_duration_reduction_and_late_help_are_blocked(env):
    db,run=env;b=store.board(db);hive.schedule(b)
    with pytest.raises(ValueError,match='소요량은 allocations'):
        discussion.preview(b,run.ctx,proposal(('b','조각',2,2)),schedule_changes=[dict(task='work',days=1)])
    with pytest.raises(ValueError,match='협업 지원이 본 업무 완료보다 늦음'):
        discussion.preview(b,run.ctx,proposal(('a','원자적 검증',1,4)),'whole_task',
            [dict(task='work',basis='지원',support=[dict(who='b',days=2,what='너무 늦은 지원')])])


def test_call_budget_stops_mid_round_without_applying_unagreed_work(env):
    db,run=env
    workflow.patch(run,llm_budget=dict(used=0,max=2))
    adapter=Script(lambda pid,card,c: DiscussionReply(action='REJECT',reason='try another plan'))
    llm.set_llm(adapter)
    state=drive(db,run)
    assert state['termination']=='max_llm_calls'
    assert len(adapter.calls)==2 and run.ctx['llm_budget']==dict(used=2,max=2)
    assert db.get(Task,'work').d==4
    assert run.ctx['pm_handoff']['summary']['llm_budget']['used']==2
    assert store.negotiation_json(db,run)['llm_budget']['max']==2


@pytest.mark.parametrize('strategy', ['whole_transfer','move_other_work','collaborate'])
def test_strategy_change_cannot_relabel_the_same_piece_offer(env,strategy):
    db,run=env
    workflow.patch(run,llm_budget=dict(used=0,max=20))
    state=dict(version=1,scope='piece',proposal=proposal(('b','piece',2,2)),
               proposer='a',consents={},history=[],seen=[])
    adapter=Script(lambda pid,card,c: DiscussionReply(action='COUNTER',reason='unchanged split',
                                                     allocations=proposal(('b','smaller',1.5,2))))
    adapter.supports_discussion_repair=True;llm.set_llm(adapter)
    answer=discussion._ask_with_repairs(db,run,store.board(db),state,'b',dict(
        mode='revise',recovery_strategy=strategy))
    assert answer.action=='PASS' and len(adapter.calls)==2
    assert any('STRATEGY_NOT_APPLIED' in e['reason'] for e in state['history'])
    assert any('조기 중단' in e['reason'] for e in state['history'])
    assert db.get(Task,'work').d==4


def test_budget_persists_between_turns_and_still_allows_final_commit(env):
    db,run=env
    workflow.patch(run,llm_budget=dict(used=0,max=2))
    adapter=Script(accept);llm.set_llm(adapter)
    state=drive(db,run)
    assert state['termination']=='agreement'
    assert len(adapter.calls)==2 and run.ctx['llm_budget']['used']==2


@pytest.mark.parametrize('strategy',['whole_transfer','move_other_work','collaborate'])
def test_valid_strategy_mechanics_are_allowed(env,strategy):
    db,run=env
    workflow.patch(run,llm_budget=dict(used=0,max=20))
    db.add(Task(id='other',who='b',title='other',s0=0,s=0,d=.5,plan=.5,base=.5,tag='code',role='dev',oi=2))
    db.flush()
    state=dict(version=1,scope='piece',proposal=proposal(('b','piece',2,2)),
               proposer='a',consents={},history=[],seen=[])
    changes=[]
    if strategy=='move_other_work':changes=[dict(task='other',who='c')]
    if strategy=='collaborate':changes=[dict(task='work',basis='독립 준비와 검토 지원',support=[dict(who='b',days=.5,what='환경 준비')])]
    answer=DiscussionReply(action='COUNTER',reason='actual strategy',proposal_scope='whole_task',
        allocations=proposal(('a','retained work',3,4)) if strategy=='collaborate' else proposal(('b','whole work',4,4)),
        schedule_changes=changes)
    adapter=Script(lambda *args:answer);adapter.supports_discussion_repair=True;llm.set_llm(adapter)
    result=discussion._ask_with_repairs(db,run,store.board(db),state,'b',dict(mode='revise',recovery_strategy=strategy))
    assert result.action=='COUNTER' and len(adapter.calls)==1
    assert not state['history']
