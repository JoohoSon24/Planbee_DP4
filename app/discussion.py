"""Versioned, persistent multilateral negotiation. No unagreed board mutations."""
from __future__ import annotations

import json
import os
from copy import deepcopy
from types import SimpleNamespace

from . import hive, store
from .prompts import read_prompt
from .llm import Allocation, DiscussionReply, ScheduleChange, LiveLLM, get_llm
from .models import Task, Handoff, Resolution


def fingerprint(proposal, scope='piece', schedule_changes=None):
    normalized = [Allocation(**a).model_dump() for a in proposal]
    return scope + ':' + json.dumps(dict(allocations=sorted(normalized, key=lambda a: (a['who'], a['title'], a['what'])),
        schedule_changes=sorted(schedule_changes or [], key=lambda x:x['task'])), sort_keys=True)


def _preview_piece(b, ctx, proposal):
    """Validate the complete allocation together, including every downstream deadline."""
    st = b.clone()
    t, h = st.tasks[ctx['task']], st.hands[ctx['hid']]
    split = ctx['split']
    if not proposal:
        raise ValueError('빈 분담안')
    items = [Allocation(**a).model_dump() for a in proposal]
    if any(a['depends_on'] for a in items):
        raise ValueError('조각 간 선후관계는 whole_task 전체 분해로 제안해야 함')
    effort = sum(a['effort'] for a in items)
    available = split['piece']['days']
    if abs(effort - available) > hive.EPS:
        raise ValueError('독립 분리한 업무 범위를 빠짐없이, 중복 없이 분담해야 함')
    if len({a['what'] for a in items}) != len(items):
        raise ValueError('중복 업무 범위')
    target = h.to_task if split.get('to') == 'downstream' else t.id
    for i, a in enumerate(items):
        if a['who'] not in b.people or a['who'] == t.who:
            raise ValueError('유효하지 않은 수신자')
        if b.people[a['who']].role != (split['piece'].get('role') or t.role):
            raise ValueError('업무 역할 불일치')
        tid = f'__discussion_{i}'
        x = SimpleNamespace(**{f: getattr(t, f, None) for f in hive.TASK_FIELDS})
        x.id, x.who, x.title = tid, a['who'], a['title']
        x.s0 = x.s = b.now
        x.d = x.plan = a['days']
        x.base, x.kind, x.oi, x.cut = a['effort'], 'new', 10**6+i, False
        st.tasks[tid] = x
        st.hands[tid] = SimpleNamespace(id=tid, from_task=tid, to_task=target,
            title=a['title'], what=a['what'], t=b.week_end, done=False,
            prop=False, agreed=True, basis='', oi=10**6+i)
    t.d = (split.get('keep') or {}).get('days') or max(0.5, t.d-effort)
    if t.d <= 0:
        raise ValueError('남은 업무 일수는 양수여야 함')
    at = b.now
    for i, part in enumerate(split.get('extra') or []):
        x = SimpleNamespace(**vars(t))
        x.id, x.title, x.d, x.s0, x.oi = f'__extra_{i}', part['title'], part.get('days') or .5, at, 10**6+len(items)+i
        if x.d <= 0:
            raise ValueError('추가 업무 일수는 양수여야 함')
        st.tasks[x.id] = x
        at += .5
    if split.get('extra'):
        t.s0 = max(t.s0, at)
    hive.schedule(st)
    # Synthetic handoffs are internal dependencies, not permission to move dates.
    for i in range(len(items)):
        x = st.tasks[f'__discussion_{i}']
        st.hands[x.id].t = h.t if split.get('to') == 'downstream' else x.s+x.d
    if hive.risks(st):
        raise ValueError('데드라인 위반: ' + ', '.join(hive.risks(st)))
    for pid in st.people:
        if hive.load_of(st, pid) > hive.capacity(st, pid)+hive.EPS:
            raise ValueError('수신자 일정 용량 초과')
    affected = {t.who, *(a['who'] for a in items)}
    for tid, old in b.tasks.items():
        new = st.tasks[tid]
        if (not old.cut and old.s + old.d <= b.week_end + hive.EPS
                and new.s + new.d > b.week_end + hive.EPS):
            raise ValueError('제출일 위반: ' + tid)
        if abs(old.s-new.s) > hive.EPS or abs(old.d-new.d) > hive.EPS:
            affected.add(old.who)
    return st, sorted(affected)


def _preview_allocation(b, ctx, proposal, scope='piece'):
    if scope == 'piece':
        return _preview_piece(b, ctx, proposal)
    from . import task_partition
    st = task_partition.preview(b, ctx, proposal)
    if hive.risks(st):
        raise ValueError('데드라인 위반: '+', '.join(hive.risks(st)))
    gate = hive.gate(st)
    if gate['violations'] or gate['warnings']:
        raise ValueError('전체 분담 일정 검증 실패: '+'; '.join(x['text'] for x in gate['violations']+gate['warnings']))
    affected = {b.tasks[ctx['task']].who, *(a['who'] for a in proposal)}
    for key,old in b.tasks.items():
        new=st.tasks[key]
        if old.s != new.s or old.d != new.d or old.kind != new.kind:
            affected.add(old.who)
    return st, sorted(affected)


def preview(b, ctx, proposal, scope='piece', schedule_changes=None):
    from . import plan_adjustments
    staged=plan_adjustments.stage(b,ctx,schedule_changes)
    st,affected=_preview_allocation(staged,ctx,proposal,scope)
    plan_adjustments.check_support(st)
    gate=hive.gate(st)
    if not gate['ok']:
        raise ValueError('전체 제약 검증 실패: '+'; '.join(v['text'] for v in gate['violations']+gate['warnings']))
    affected=set(affected)
    for tid,old in b.tasks.items():
        new=st.tasks[tid]
        if (old.who,old.s,old.s0,old.d)!=(new.who,new.s,new.s0,new.d):
            affected.update([old.who,new.who])
    for key,t in st.tasks.items():
        if key.startswith('__support_'):affected.add(t.who)
    return st,sorted(affected)


def begin_whole(db, run):
    from .workflow import patch
    b=store.board(db);t=b.tasks[run.ctx['task']]
    ids=[p.id for p in b.people.values() if p.role==t.role and p.id!=t.who]
    proposal=[dict(who=t.who,title=t.title,days=t.d,effort=t.d,what=t.title)]
    split=dict(piece=dict(title=t.title,days=min(5,t.d),tag=t.tag,what=t.title))
    patch(run, split=split, candidate_ids=ids, discussion=dict(version=1, scope='whole_task',
        proposal=proposal,proposer=t.who,consents={},history=[],seen=[fingerprint(proposal,'whole_task')],
        rejected=True,participants=[t.who]+ids,termination=None))
    return True


def schedule_signature(b):
    return {tid: [x.who, x.s, x.d, x.s0] for tid, x in b.tasks.items() if not x.cut}


def _event(db, run, state, requester, recipient, action, reason, proposal=None, schedule_changes=None, proposal_scope=None):
    from .workflow import patch
    event = dict(round=run.ctx['round'], version=state['version'], requester=requester,
                 recipient=recipient, proposal=proposal or state['proposal'], schedule_changes=(schedule_changes if schedule_changes is not None else state.get('schedule_changes',[])), response=action,
                 reason=reason, proposal_scope=proposal_scope or state.get('scope','piece'),
                 proposed_version=state['version']+1 if action=='COUNTER' else None,
                 llm_budget=deepcopy(run.ctx.get('llm_budget')),
                 phase=run.ctx.get('rebalance_reason'), agreement=dict(state['consents']))
    state['history'].append(event)
    phase = '마감 복구' if run.ctx.get('rebalance_reason') == 'deadline' else '공정성 협상'
    scope = '원 Task 전체 양도·재분해' if event['proposal_scope'] == 'whole_task' else '독립 조각 분담'
    detail = f"{run.ctx['round']}라운드 · v{state['version']} · {phase} · {scope}"
    if action in ('BLOCKED', 'END', 'AGREED', 'SCHEDULE_CHANGED', 'FINAL_CONSTRAINT_CHECK', 'MODEL_UNAVAILABLE', 'MODEL_OUTPUT_INVALID','STRATEGY_CHANGE'):
        event['requester'] = 'hive'
        event['actor'] = 'Hive'
        store.hive_say(db, detail+' · '+action+' · '+reason+' · '+json.dumps(dict(allocations=event['proposal'],schedule_changes=event['schedule_changes']),ensure_ascii=False),
                       hid=run.ctx['hid'],run_id=run.id)
    else:
        store.say(db, requester, action, [store.F(detail), store.F(reason), store.F(json.dumps(dict(allocations=event['proposal'],schedule_changes=event['schedule_changes']), ensure_ascii=False))],
                  to=recipient, hid=run.ctx['hid'], run_id=run.id)
    patch(run, discussion=state)


def _end(db, run, state, reason):
    from .workflow import patch, done
    if reason=='no_valid_alternative' and state.get('model_errors'):
        reason='model_unavailable' if any(e['type'] not in ('ValidationError','JSONDecodeError') for e in state['model_errors']) else 'model_output_invalid'
    state['termination'] = reason
    _event(db, run, state, state['proposer'], None, 'END', reason)
    patch(run, discussion=state, fairness_after=hive.fairness(store.board(db)))
    budget=run.ctx.get('llm_budget') or {}
    usage=f" · 모델 호출 {budget['used']}/{budget['max']}회" if budget else ''
    store.hive_say(db, f'협상 종료 · {reason}{usage} · 미합의 변경 미적용', hid=run.ctx['hid'], run_id=run.id)
    if run.ctx.get('rebalance_reason') == 'deadline':
        run.step = 'ask'
    else:
        notice='협상 실패 → PM에게 전달됨 · 공정성 미합의 · 기존 합의 배분 유지'
        from .pm_summary import build as pm_brief
        patch(run,pm_handoff=dict(message=notice,review_required=False,reasons=[reason],
                                 summary=pm_brief(db,run,[reason],review_required=False)))
        store.hive_say(db,notice,hid=run.ctx['hid'],run_id=run.id)
        done(db, run, notice)


def from_rejections(db, run):
    """Continue a deadline repair discussion with the feedback already obtained."""
    from .workflow import patch
    b, ctx = store.board(db), run.ctx
    t, piece = b.tasks[ctx['task']], ctx['split']['piece']
    replies = ctx.get('replies') or []
    pid = next((r['who'] for r in replies), None)
    if not pid:
        return False
    proposal = [dict(who=pid, title=piece['title'], days=piece['days'],
                     effort=piece['days'], what=piece.get('what') or piece['title'])]
    state = dict(version=1, scope='piece', proposal=proposal, proposer=t.who, consents={}, history=[],
                 seen=[fingerprint(proposal)], rejected=True,
                 participants=list(dict.fromkeys([t.who]+[r['who'] for r in replies])), termination=None)
    for r in replies:
        requested = [dict(proposal[0], who=r['who'], days=r.get('days') or piece['days'])]
        state['history'].append(dict(round=ctx.get('round',0), version=1, requester=r['who'],
            recipient=t.who, proposal=requested, response=r['type'], reason=r['reason'],
            condition=r.get('cond'), condition_response=r.get('help_reason'), agreement={}))
    for response in (ctx.get('recv') or {}).values():
        state['history'].append(dict(round=ctx.get('round',0), version=1,
            requester=b.tasks[b.hands[ctx['hid']].to_task].who, recipient=t.who,
            proposal=proposal, response=response['state'], reason=response['reason'], agreement={}))
    patch(run, discussion=state)
    return True


def _ask_with_repairs(db, run, b, state, pid, public):
    """Model protocol errors get bounded, visible feedback to the same speaker.

    Mock scripts keep their deterministic turns. Live/custom capable adapters can
    repair a malformed proposal without spending another entire discussion round.
    """
    from .negotiation_contract import feedback
    adapter=get_llm()
    attempts=3 if getattr(adapter,'supports_discussion_repair',False) else 1
    context=public
    prior_codes = None
    stop_reason='제안 검증 복구 한도 도달 · 다른 참여자의 대안 필요'
    for attempt in range(attempts):
        from .negotiation_budget import bound, consume
        with bound(run.ctx['llm_budget']):
            if not isinstance(adapter, LiveLLM):
                consume()
            ans=DiscussionReply.model_validate(adapter.discuss(b.people[pid],store.card(db,pid),context))
        if ans.max_new_days is not None:
            state.setdefault('public_limits',{})[pid]=ans.max_new_days
            _event(db,run,state,pid,state['proposer'],'CONDITION',f'본인이 공개한 새 업무량 상한 {ans.max_new_days:g}일')
        error=getattr(adapter,'last_discussion_error',None)
        if error:
            state.setdefault('model_errors',[]).append(dict(who=pid,round=run.ctx['round'],**error))
            malformed=error['type'] in ('ValidationError','JSONDecodeError')
            _event(db,run,state,'hive',pid,'MODEL_OUTPUT_INVALID' if malformed else 'MODEL_UNAVAILABLE',
                   ('모델 출력 형식 오류' if malformed else '모델 호출 불가')+' · 당사자 거절·대안 소진과 구분 · '+json.dumps(error))
            error_key=json.dumps(dict(who=pid,type=error['type'],fields=error.get('fields',[])),sort_keys=True)
            errors=state.setdefault('failed_outputs',[])
            repeated=error_key in errors
            if not repeated:errors.append(error_key)
            if malformed and not repeated and attempt+1<attempts:
                context={**public,'validation_feedback':[dict(code='MODEL_OUTPUT_FORMAT',fields=error.get('fields',[]),
                    message=read_prompt("format_repair"))],
                    'repair_attempt':attempt+1,'history':state['history']}
                _event(db,run,state,state['proposer'],pid,'REPAIR_REQUEST','모델 출력 형식 복구 요청 · '+json.dumps(error))
                continue
            return ans
        state['model_errors']=[e for e in state.get('model_errors',[]) if e['who']!=pid]
        issues=feedback(b,run.ctx,state,ans,public['mode']) if attempts>1 else []
        if attempts>1 and ans.action=='COUNTER' and public['mode']=='revise':
            changes=[c.model_dump(exclude_defaults=True) for c in (ans.schedule_changes or [])]
            strategy=public['recovery_strategy']
            moved=any(c['task']!=run.ctx['task'] and c['task'] in b.tasks and (
                c.get('who') is not None and c['who']!=b.tasks[c['task']].who or
                c.get('start') is not None and abs(c['start']-b.tasks[c['task']].s0)>hive.EPS)
                for c in changes)
            missing=(strategy=='whole_transfer' and ans.proposal_scope!='whole_task'
                or strategy=='move_other_work' and not moved
                or strategy=='collaborate' and not any(c.get('support') and c.get('basis') for c in changes))
            if missing:
                issues.append(dict(code='STRATEGY_NOT_APPLIED',strategy=strategy,
                    message=read_prompt("strategy_feedback")))
        if not issues:return ans
        _event(db,run,state,pid,state['proposer'],ans.action,ans.reason,
               [a.model_dump() for a in ans.allocations] if ans.allocations else None,
               schedule_changes=[c.model_dump(exclude_defaults=True) for c in (ans.schedule_changes or [])],proposal_scope=ans.proposal_scope)
        _event(db,run,state,'hive',pid,'BLOCKED',json.dumps(issues,ensure_ascii=False))
        codes=sorted({i['code'] for i in issues})
        # Strategy labels cannot reset a known failure of the exact same plan.
        substantive=[i for i in issues if i['code']!='STRATEGY_NOT_APPLIED']
        failed_key=json.dumps(dict(who=pid,proposal=ans.model_dump(exclude={'reason'}),
            issues=substantive or issues),sort_keys=True,ensure_ascii=False)
        failures=state.setdefault('failed_proposals',[])
        repeated=failed_key in failures or codes==prior_codes
        if failed_key not in failures:failures.append(failed_key)
        if repeated:
            stop_reason='동일 오류 반복 · 복구 호출 조기 중단 · 다른 참여자/전략으로 진행'
            _event(db,run,state,'hive',pid,'BLOCKED',stop_reason)
            break
        prior_codes=codes
        if attempt+1<attempts:
            _event(db,run,state,state['proposer'],pid,'REPAIR_REQUEST',
                   '반려 사유의 분량·범위·역할·선후 관계를 수정해 새 제안을 제시: '+json.dumps(issues,ensure_ascii=False))
            context={**public,'validation_feedback':issues,'previous_response':ans.model_dump(),
                     'repair_attempt':attempt+1,'history':state['history']}
    return DiscussionReply(action='PASS' if public['mode']=='revise' else 'REJECT',
                           reason=stop_reason)


def turn(db, run):
    from .workflow import patch, ask_person
    b, ctx = store.board(db), run.ctx
    hive.schedule(b)
    t = b.tasks[ctx['task']]
    state = deepcopy(ctx.get('discussion'))
    if state is None:
        piece = ctx['split']['piece']
        ids = ctx.get('candidate_ids') or []
        if not ids:
            run.step = 'ask'
            return
        # Fairness metrics only seed the request; they never choose an agreement.
        hint = ctx.get('fairness_recipient')
        pid = hint if hint in ids else ids[0]
        proposal = [dict(who=pid, title=piece['title'], days=hive.scaled_days(b, piece['days'], piece['tag'], pid, t.who),
                         effort=piece['days'], what=piece.get('what') or piece['title'])]
        state = dict(version=1, scope='piece', proposal=proposal, proposer=t.who, consents={}, history=[],
                     seen=[fingerprint(proposal)], rejected=False, participants=[t.who, pid], termination=None)
        patch(run, fairness_before=ctx.get('fairness_before') or hive.fairness(b))
    if ctx.get('round', 0) >= store.rule(db, 'rounds')['max']:
        return _end(db, run, state, 'max_rounds')
    if 'llm_budget' not in run.ctx:
        configured=store.rule(db,'rounds').get('max_llm_calls') or os.environ.get('PLANBEE_MAX_NEGOTIATION_CALLS','40')
        patch(run,llm_budget=dict(used=0,max=max(1,int(configured))))
    if run.ctx['llm_budget']['used']>=run.ctx['llm_budget']['max']:
        return _end(db,run,state,'max_llm_calls')
    rnd = ctx.get('round', 0)+1
    patch(run, round=rnd, discussion=state)
    store.mark(rnd, ctx.get('attempt', 0))
    try:
        st, affected = preview(b, ctx, state['proposal'], state.get('scope','piece'), state.get('schedule_changes'))
        valid = True
    except (ValueError, KeyError, TypeError) as e:
        valid, affected = False, list(state['participants'])
        state['rejected'] = True
        _event(db, run, state, t.who, state['proposer'], 'BLOCKED', str(e))
    for pid in affected:
        if pid not in state['participants']:
            state['participants'].append(pid)
    mode = 'revise' if state['rejected'] else 'respond'
    strategies=['independent_split','whole_transfer','move_other_work','collaborate']
    if (t.context or {}).get('splittable_hint') is False or ctx.get('no_split'):
        strategies=strategies[1:]
    strategy=strategies[min(state.get('strategy_cursor',0),len(strategies)-1)]
    consulted=state.setdefault('revision_consulted',[])
    speakers = [p for p in state['participants'] if p not in consulted] if mode == 'revise' else [p for p in affected if p not in state['consents']]
    # Receive the request first, then obtain the source/affected parties' consent.
    speakers.sort(key=lambda p: p == state['proposer'])
    changed = False
    workload_patterns=None
    for pid in speakers:
        from .negotiation_contract import public_contract,normalize_changes
        public = dict(mode=mode, phase=ctx.get('rebalance_reason'),recovery_strategy=strategy,
            proposal_scope=state.get('scope','piece'),
            original_task=dict(id=t.id,title=t.title,days=t.d,role=t.role,context=t.context or {}),
            piece_effort=ctx['split']['piece']['days'],
            proposal_contract=public_contract(b,ctx),
            strategy_requirement={
                'independent_split':read_prompt("strategy_independent_split"),
                'whole_transfer':read_prompt("strategy_whole_transfer"),
                'move_other_work':read_prompt("strategy_move_other_work"),
                'collaborate':read_prompt("strategy_collaborate")}[strategy],
            deadlines=[dict(id=h.id,source=h.from_task,target=h.to_task,due=h.t) for h in b.hands.values() if not h.done],
            proposal=state['proposal'], schedule_changes=state.get('schedule_changes',[]), version=state['version'],
            history=state['history'], tag=ctx['split']['piece']['tag'], now=b.now,
            public_limits=state.get('public_limits',{}),
            load=hive.load_of(b, pid), cap=hive.capacity(b, pid), fairness=hive.fairness(b),
            proposed_fairness=hive.fairness(st) if valid else None,
            proposed_load=hive.load_of(st,pid) if valid else None,
            proposed_schedule=schedule_signature(st) if valid else None,
            source=t.who, remaining_days=(sum(a['days'] for a in state['proposal'] if a['who']==t.who)
                if state.get('scope')=='whole_task' else st.tasks[t.id].d) if valid else None,
            people=[dict(id=p.id, name=p.name, role=p.role, load=hive.load_of(b,p.id),
                         capacity=hive.capacity(b,p.id),experience=p.rec or {},
                         unavailable=[dict(start=w['start'],end=w['end']) for w in hive.policy(b,p.id).get('unavailable',[])]) for p in b.people.values()],
            tasks=[dict(id=x.id, who=x.who, title=x.title, days=x.d, start=x.s, planned_start=x.s0,role=x.role,context=x.context or {}) for x in b.tasks.values() if not x.cut])
        if valid:
            from .plan_adjustments import incoming
            public['my_new_work']=incoming(b,st,ctx,state['proposal'],pid)
        if mode=='revise' and getattr(get_llm(),'supports_discussion_repair',False):
            from .negotiation_options import patterns
            if workload_patterns is None:workload_patterns=patterns(b,ctx,state.get('public_limits'))
            public['schedule_workload_patterns']=dict(
                meaning='공개 일정상 가능한 독립 분량의 참고 예시. 실제 분리 가능성·범위·선후관계는 LLM이 설계하고 재검증해야 함. 자동 선택·당사자 동의가 아님.',
                patterns=workload_patterns)
        _event(db, run, state, state['proposer'], pid, 'REQUEST' if mode == 'respond' else 'REVISE_REQUEST', '공개 피드백과 현재 제안을 검토 · 중점 전략 '+strategy)
        from . import progress,stages
        progress.publish(run,stages.for_node(run,'bids'),store.DEMO)
        from .negotiation_budget import CallBudgetExceeded
        try:
            ans = _ask_with_repairs(db,run,b,state,pid,public)
        except CallBudgetExceeded:
            return _end(db,run,state,'max_llm_calls')
        if mode=='revise':consulted.append(pid)
        _event(db, run, state, pid, state['proposer'], ans.action, ans.reason,
               [a.model_dump() for a in ans.allocations] if ans.allocations else None,
               schedule_changes=([a.model_dump(exclude_defaults=True) for a in (ans.schedule_changes or [])] if ans.action=='COUNTER' else None),
               proposal_scope=ans.proposal_scope)
        if ans.action == 'COUNTER' and (ans.allocations or ans.schedule_changes is not None):
            proposal = [a.model_dump() for a in ans.allocations] if ans.allocations else state['proposal']
            changes = normalize_changes(b,[a.model_dump(exclude_defaults=True) for a in (ans.schedule_changes or [])])
            scope = ans.proposal_scope or state.get('scope','piece')
            key = fingerprint(proposal, scope, changes)
            if key in state['seen']:
                _event(db, run, state, pid, None, 'BLOCKED', '이미 검토한 동일 제안')
                if mode == 'respond':
                    state['rejected'] = True
                    break
                continue
            state['seen'].append(key)
            state.update(proposal=proposal, schedule_changes=changes, scope=scope, proposer=pid, version=state['version']+1,
                         consents={}, rejected=False, revision_consulted=[])
            for a in proposal:
                if a['who'] in b.people and a['who'] not in state['participants']:
                    state['participants'].append(a['who'])
            for change in changes:
                target=b.tasks.get(change['task'])
                if target and target.who not in state['participants']:
                    state['participants'].append(target.who)
            changed = True
            break
        if mode == 'respond':
            if ans.action == 'ACCEPT':
                state['consents'][pid] = 'accepted'
            elif ans.action == 'NEEDS_INPUT':
                state['consents'][pid] = 'needs_input'
            else:
                state['rejected'] = True
                break
    patch(run, discussion=state)
    if changed or (mode == 'respond' and state['rejected']):
        run.step = 'bids'
        return
    if mode == 'revise':
        # Exhausting the initial pair is not exhausting the team. Invite one
        # unconsulted candidate at a time; their actual response gets its own turn.
        candidates=ctx.get('candidate_ids') or [p.id for p in b.people.values() if p.role==t.role]
        remaining=[pid for pid in candidates if pid not in state['participants']]
        if remaining:
            pid=remaining[0]
            state['participants'].append(pid)
            _event(db,run,state,state['proposer'],pid,'INVITE',
                   '기존 참여자의 대안 소진 · 공개 거절·검증 피드백을 바탕으로 새 분담 대안 요청')
            patch(run,discussion=state)
            run.step='bids'
            return
        cursor=state.get('strategy_cursor',0)
        if cursor+1<len(strategies):
            state.update(strategy_cursor=cursor+1,revision_consulted=[])
            _event(db,run,state,'hive',None,'STRATEGY_CHANGE',
                   '앞 전략의 대안 소진 · 다음 전략 '+strategies[cursor+1]+'을 당사자들에게 요청')
            patch(run,discussion=state)
            run.step='bids'
            return
        return _end(db, run, state, 'no_valid_alternative')
    # All approvals are tied to this exact version. Human approval may be required.
    waiting = []
    for pid in affected:
        from .plan_adjustments import incoming
        days = sum(a['days'] for a in incoming(b,st,ctx,state['proposal'],pid))
        cd = store.card(db, pid)
        from .policies import needs_review
        if state['consents'].get(pid) == 'needs_input' or days > cd.auto_days or needs_review(cd):
            waiting.append(ask_person(db, run, pid, f"제안 v{state['version']} 전체 분담안에 동의하나요?",
                json.dumps(dict(allocations=state['proposal'],schedule_changes=state.get('schedule_changes',[])), ensure_ascii=False), ctx['hid'], 'discussion'))
    state['schedule_signature'] = schedule_signature(st)
    state['confirmed_version'] = state['version']
    patch(run, discussion=state, waiting_for=[c.id for c in waiting])
    run.step = 'discussion_commit'


def _commit(db, run):
    from .workflow import wait_confirms, patch, done
    state = deepcopy(run.ctx['discussion'])
    result, c = wait_confirms(db, run)
    if result == 'pending':
        return
    if result == 'rejected':
        from sqlalchemy import select
        from .models import Confirmation
        for cf in db.scalars(select(Confirmation).where(Confirmation.id.in_(run.ctx['waiting_for']), Confirmation.status == 'pending')):
            cf.status = 'withdrawn'
        state['rejected'], state['consents'] = True, {}
        _event(db, run, state, c.who, state['proposer'], 'REJECT', '본인 확인에서 거절')
        patch(run, waiting_for=[], discussion=state)
        run.status, run.step = 'running', 'bids'
        return
    b = store.board(db)
    hive.schedule(b)
    try:
        st, affected = preview(b, run.ctx, state['proposal'], state.get('scope','piece'), state.get('schedule_changes'))
    except (ValueError, KeyError, TypeError) as e:
        return _end(db, run, state, f'commit_validation_failed: {e}')
    if state.get('schedule_signature') != schedule_signature(st):
        state['consents'] = {}
        state['rejected'] = False
        _event(db, run, state, b.tasks[run.ctx['task']].who, None,
               'SCHEDULE_CHANGED', '대기 중 일정 변경 · 동일 제안이라도 전원 재동의 필요')
        patch(run, discussion=state, waiting_for=[])
        run.status, run.step = 'running', 'bids'
        return
    if state['confirmed_version'] != state['version'] or any(p not in state['consents'] for p in affected):
        return _end(db, run, state, 'missing_version_consent')
    from sqlalchemy import select
    from .models import Confirmation
    for cf in db.scalars(select(Confirmation).where(Confirmation.id.in_(run.ctx.get('waiting_for', [])))):
        if cf.status == 'confirmed':
            state['consents'][cf.who] = 'accepted_human'
    _event(db, run, state, 'hive', None, 'FINAL_CONSTRAINT_CHECK',
           '동일 버전 당사자 동의 확인 · 최신 일정의 마감·용량·가용 시간·선후 관계 검증 통과')
    t, h = b.tasks[run.ctx['task']], b.hands[run.ctx['hid']]
    split = run.ctx['split']
    if state.get('scope','piece') == 'whole_task':
        from . import task_partition
        task_partition.apply(db,b,run.ctx,state['proposal'],st)
    else:
        for i, a in enumerate(state['proposal']):
            x = st.tasks[f'__discussion_{i}']
            tid = store.next_id(db, Task, 'piece')
            db.add(Task(id=tid, who=a['who'], title=a['title'], s0=b.now, s=x.s,
                d=a['days'], plan=a['days'], base=a['effort'], tag=split['piece']['tag'],
                role=split['piece'].get('role') or t.role, context=split['piece'].get('context') or t.context,
                kind='new', oi=store.next_oi(db, Task)))
            db.flush()
            db.add(Handoff(id=store.next_id(db, Handoff, 'h'), from_task=tid,
                to_task=h.to_task if split.get('to') == 'downstream' else t.id,
                title=a['title'], what=a['what'], t=x.s+x.d, agreed=True, oi=store.next_oi(db, Handoff)))
            db.flush()
        for key, x in st.tasks.items():
            if key.startswith('__extra_'):
                db.add(Task(id=store.next_id(db, Task, 'part'), who=t.who, title=x.title,
                    s0=x.s0, s=x.s, d=x.d, plan=x.d, base=x.d, tag=t.tag, role=t.role,
                    kind='new', oi=store.next_oi(db, Task)))
                db.flush()
        t.d = t.plan = t.base = st.tasks[t.id].d
        t.s0 = st.tasks[t.id].s0
        if (split.get('keep') or {}).get('title'):
            t.title = split['keep']['title']
        if split.get('rename_handoff'):
            h.title = split['rename_handoff']
    from . import plan_adjustments
    plan_adjustments.apply(db,b,run.ctx,state.get('schedule_changes',[]),st)
    h.basis = ''
    hive.schedule(store.board(db))
    state['termination'] = 'agreement'
    _event(db, run, state, state['proposer'], None, 'AGREED', '전체 당사자 버전별 동의 완료')
    patch(run, discussion=state, waiting_for=[], fairness_after=hive.fairness(store.board(db)))
    store.hive_say(db, f"협상 합의 · v{state['version']} · {run.ctx['round']}라운드 · 당사자 전체 동의", hid=h.id, run_id=run.id)
    db.add(Resolution(hid=h.id, body='다자간 업무 분담 합의', why=f"v{state['version']} · 당사자 전체 동의 · 데드라인 검증 통과"))
    if run.ctx.get('rebalance_reason') == 'deadline':
        from .workflow import record_feasible_baseline
        record_feasible_baseline(db,run)
        patch(run, discussion_archive=run.ctx.get('discussion_archive', [])+[state],
              discussion=None, round=0, fairness_reviewed=True)
        run.step = 'fairness_gate'
    else:
        done(db, run, '공정성 협상 완료 · 합의된 분담 적용')


def commit(db, run):
    """Apply all parts atomically, and verify the actual persisted ordering too."""
    prior = deepcopy(run.ctx['discussion'])
    archive_count = len(run.ctx.get('discussion_archive', []))
    try:
        with db.begin_nested():
            _commit(db, run)
            applied = ((run.ctx.get('discussion') or {}).get('termination') == 'agreement'
                       or len(run.ctx.get('discussion_archive', [])) > archive_count)
            if applied:
                current = store.board(db)
                hive.schedule(current)
                if not hive.gate(current)['ok']:
                    raise ValueError('최종 배분 일정 검증 실패')
    except ValueError as exc:
        _end(db, run, prior, f'commit_validation_failed: {exc}')
