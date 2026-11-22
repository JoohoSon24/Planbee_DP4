"""Public, numeric proposal requirements and actionable feedback for an agent.

This does not choose allocations or read anyone else's private delegation card.
"""
from collections import defaultdict
from . import hive


def public_contract(b, ctx):
    source=b.tasks[ctx['task']]
    split=ctx['split']
    piece=split['piece']
    retained=(split.get('keep') or {}).get('days')
    if retained is None:retained=max(0,source.d-piece['days'])
    hand=b.hands[ctx['hid']]
    return dict(
        piece=dict(required_effort=piece['days'], retained_owner=source.who,
                   retained_days=retained, owner_allocations_allowed=False,
                   role=piece.get('role') or source.role),
        whole_task=dict(required_effort=source.d, include_owner_retained_work=True,
                        role=source.role, decomposition_allowed=(source.context or {}).get('splittable_hint') is not False),
        handoff=dict(mode=split.get('to','self'),deadline=hand.t,now=b.now,
                     self_meaning='helper finishes before retained work starts',
                     downstream_meaning='independent retained and delegated work join at the consumer'),
        work_to_delegate=piece,retained_work=split.get('keep') or {},
        rule='effort preserves scope; days estimates actual duration; distinct what must identify distinct deliverables')


def normalize_changes(b, changes):
    # An explicitly unchanged start is not a new schedule proposal.
    return [c for c in changes if c['task'] not in b.tasks or c.get('who') or c.get('days') is not None or c.get('support') or
            (c.get('start') is not None and abs(c['start']-b.tasks[c['task']].s0)>hive.EPS)]


def feedback(b, ctx, state, ans, mode):
    if mode=='revise' and ans.action not in ('COUNTER','PASS'):
        return [dict(code='REVISION_ACTION',message='This is a revision request, not an incoming work request. Propose a concrete COUNTER, or PASS if no alternative remains.')]
    if ans.action!='COUNTER':return []
    if not ans.allocations and ans.schedule_changes is None:
        return [dict(code='EMPTY_COUNTER',message='COUNTER에는 새 전체 allocations 또는 명시적 schedule_changes가 필요합니다. 이유만 반복하지 마세요.')]
    proposal=[a.model_dump() for a in ans.allocations] if ans.allocations else state['proposal']
    scope=ans.proposal_scope or state.get('scope','piece')
    changes=normalize_changes(b,[c.model_dump(exclude_defaults=True) for c in (ans.schedule_changes or [])])
    contract=public_contract(b,ctx)
    expected=contract[scope]['required_effort']
    actual=sum(a['effort'] for a in proposal)
    issues=[]
    for pid,limit in state.get('public_limits',{}).items():
        incoming=sum(a['days'] for a in proposal if a['who']==pid) if pid!=b.tasks[ctx['task']].who else 0
        if incoming>limit+hive.EPS:
            issues.append(dict(code='PUBLIC_LIMIT',who=pid,limit=limit,proposed=incoming,
                message='당사자가 공개한 새 업무량 상한을 초과합니다. 다른 동료와 실제 범위를 나누거나 원 담당자 보유분을 조정하세요.'))
    if abs(actual-expected)>hive.EPS:
        issues.append(dict(code='EFFORT_SUM',expected=expected,actual=actual,missing=expected-actual,
            message='Include every unit exactly once. In whole_task include the original owner retained scope; days and effort are different quantities.'))
    groups=defaultdict(list)
    for i,a in enumerate(proposal):
        groups[a['what'].strip()].append(i)
        person=b.people.get(a['who'])
        if not person or person.role!=contract[scope]['role']:
            issues.append(dict(code='ROLE',index=i,who=a['who'],required_role=contract[scope]['role'],
                message='Use a participant with the public required role; changing a title does not grant another role.'))
        if scope=='piece' and a['who']==b.tasks[ctx['task']].who:
            issues.append(dict(code='OWNER_IN_PIECE',index=i,retained_days=contract['piece']['retained_days'],
                message='Owner retained work is outside piece. Use whole_task and include all original work, or keep owner allocations out of piece.'))
    for what,indices in groups.items():
        if len(indices)>1:issues.append(dict(code='DUPLICATE_SCOPE',indices=indices,what=what,
            message='Define genuinely different sub-deliverables, e.g. distinct normal/failure paths or distinct regions. Renaming keys alone does not split work.'))
    if scope=='whole_task' and len(proposal)>1 and not contract['whole_task']['decomposition_allowed']:
        issues.append(dict(code='UNSPLITTABLE',message='The source forbids decomposition. A single whole-task transfer is permitted; splitting is not.'))
    if issues:return issues
    from .discussion import fingerprint,preview
    if fingerprint(proposal,scope,changes) in state['seen']:
        return [dict(code='DUPLICATE_PROPOSAL',message=(
            '현재 제안과 동일한 COUNTER는 새 대안이 아닙니다. respond에서는 현재 제안이 본인 설정에 맞으면 ACCEPT, '
            '안 맞으면 구체적 이유와 REJECT로 답하세요. 수정이 필요하면 실제 범위·담당·의존성·시각을 바꾸세요.'
            if mode=='respond' else '이미 검토한 동일 제안입니다. 실제 범위·담당·의존성·시각을 바꾼 COUNTER 또는 대안이 없으면 PASS로 답하세요.'))]
    try:preview(b,ctx,proposal,scope,changes)
    except (ValueError,KeyError,TypeError) as exc:
        return [dict(code='SCHEDULE_OR_DEPENDENCY',message=str(exc),handoff=contract['handoff'],
            owner_retained_days=contract['piece']['retained_days'],
            guidance='Use whole_task for a parallel DAG when a self handoff serializes all retained work. Keep deadlines fixed and preserve scope. Do not move already started work into the past.')]
    return []
