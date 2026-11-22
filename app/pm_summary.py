"""A deterministic PM handoff brief from public run facts, never private cards."""
from . import hive,store,runlogs


def build(db,run,reasons,options=None,review_required=True):
    ctx=run.ctx;state=ctx.get('discussion') or {}
    b=store.board(db).clone();hive.schedule(b)
    task=b.tasks.get(ctx.get('task'))
    current=runlogs.milestones(db)
    initial=ctx.get('initial_milestones') or {}
    earlier={h['id']:h for h in initial.get('handoffs',[])}
    impacts=[]
    for h in current.get('handoffs',[]):
        before=earlier.get(h['id'])
        if h['expected']>h['deadline']+hive.EPS or (before and before['expected']!=h['expected']):
            impacts.append(dict(title=h['title'],deadline=h['deadline_label'],expected=h['expected_label'],
                                before=before['expected_label'] if before else None))
    history=[dict(round=e['round'],version=e['version'],who=e['requester'],response=e['response'],reason=e['reason'])
             for e in state.get('history',[]) if e['response'] in ('REJECT','COUNTER','BLOCKED','PASS')][-12:]
    return dict(title=task.title if task else '업무 배분 협상',
        owner=b.people[task.who].name if task else None,
        phase=ctx.get('rebalance_reason') or 'deadline',
        round=ctx.get('round',0),max_rounds=store.rule(db,'rounds')['max'],
        llm_budget=ctx.get('llm_budget'),
        trigger=ctx.get('records') or [],reasons=list(reasons),
        termination=state.get('termination') or 'constraint_or_initial_offer_failure',
        proposal=dict(version=state.get('version'),scope=state.get('scope'),
                      allocations=state.get('proposal') or [],schedule_changes=state.get('schedule_changes') or []),
        consents=state.get('consents') or {},public_limits=state.get('public_limits') or {},history=history,impacts=impacts,
        constraints=hive.gate(b),
        disposition=('미합의 배분 변경 미적용 · 기한 회복 미완료' if review_required else
                     '미합의 변경 미적용 · 기한 충족 기준 배분 유지'),
        review_required=review_required,
        next_action='실패 사유를 검토하고 범위·일정·담당 조정 또는 라운드 확대 후 재협상' if review_required else '공정성 미합의 사실 확인 · 기한 충족 기준 배분 유지',
        options=[dict(label=o['label'],effect=o['effect']) for o in (options or [])])
