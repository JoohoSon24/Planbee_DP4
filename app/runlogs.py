"""Readable per-run transcripts, refreshed at each persisted conversation turn."""
from __future__ import annotations

from datetime import datetime
import os
import json
from pathlib import Path
import tempfile
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from .models import Message, Person, Run, Task, Handoff, Rule
from . import stages

ROOT = Path(__file__).resolve().parent.parent


def directory(mode=None):
    root=Path(os.environ.get('PLANBEE_RUNS_DIR', ROOT / 'runs' / 'v2'))
    return root / mode if mode in ('mock','live','mixed','unknown') else root


def ensure_metadata(run):
    from .llm import runtime_mode
    current=runtime_mode()
    ctx=run.ctx
    name=ctx.get('transcript_file')
    previous=ctx.get('llm_mode')
    if not previous and name:
        # Old records must not inherit today's configured mode when resumed.
        matches=[mode for mode in ('mock','live','mixed','unknown') if (directory(mode)/Path(name).name).exists()]
        previous=matches[0] if len(matches)==1 else 'unknown'
    modes=list(ctx.get('llm_modes') or ([previous] if previous else []))
    if current not in modes:modes.append(current)
    mode=modes[0] if len(modes)==1 else 'mixed'
    if not name:
        stamp=datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y-%m-%d_%H-%M-%S_%f')
        name=f'{stamp}_{uuid4().hex[:8]}.md'
    relative=f'{mode}/{Path(name).name}'
    origin=ctx.get('transcript_origin') or os.environ.get('PLANBEE_RUN_ORIGIN','app')
    updates=dict(llm_mode=mode,llm_modes=modes,transcript_origin=origin,transcript_file=relative)
    if ctx.get('transcript_file') and ctx['transcript_file']!=relative:
        updates['transcript_previous_file']=ctx['transcript_file']
    if any(ctx.get(k)!=v for k,v in updates.items()):run.ctx={**ctx,**updates}



def milestones(db):
    """Public milestone dates and handoff deadlines; no private delegation settings."""
    tasks = {t.id: t for t in db.scalars(select(Task).order_by(Task.oi, Task.id))}
    hands = list(db.scalars(select(Handoff).order_by(Handoff.oi, Handoff.id)))
    if db.get(Rule, 'weekly_cap') and db.get(Rule, 'deadline'):
        from . import hive, store
        b = store.board(db).clone()
        hive.schedule(b)
        tasks = b.tasks
    from .hive import when
    return {
        'milestones': [dict(id=t.id, title=t.title, owner=t.who, start=t.s,
                            end=t.s+t.d, end_label=when(t.s+t.d), removed=bool(t.cut))
                       for t in tasks.values() if t.kind == 'milestone'],
        'constraints': hive.gate(b) if db.get(Rule, 'weekly_cap') and db.get(Rule, 'deadline') else {},
        'handoffs': [dict(id=h.id, title=h.title, source=h.from_task, target=h.to_task,
                         deadline=h.t, deadline_label=when(h.t),
                         expected=tasks[h.from_task].s+tasks[h.from_task].d,
                         expected_label=when(tasks[h.from_task].s+tasks[h.from_task].d),
                         done=bool(h.done), agreed=bool(h.agreed))
                     for h in hands if h.from_task in tasks]}


def start_turn(db, run, node):
    from .models import Meta
    prior_narration = db.get(Meta, 'narr')
    last = db.scalar(select(Message.id).order_by(Message.id.desc()).limit(1)) or 0
    stage=stages.for_node(run,node)
    history=run.ctx.get('stage_history',[])
    if not history or history[-1]['key']!=stage['key']:
        history=history+[stage]
    run.ctx={**run.ctx,'workflow_stage':stage,'stage_history':history}
    from . import progress,store
    progress.publish(run,stage,store.DEMO)
    from .llm import runtime_mode
    return dict(llm_mode=runtime_mode(), stage=stage, node=node, before=run.step, status_before=run.status,
                round=run.ctx.get('round', 0), message_after=last,
                narration_before=(prior_narration.value or {}).get('v', '') if prior_narration else '',
                milestones_before=milestones(db))


def finish_turn(db, run, turn):
    from .models import Meta
    # Narration includes Hive actions that do not emit a conversation message.
    narration = db.get(Meta, 'narr')
    current_narration = (narration.value or {}).get('v', '') if narration else ''
    changed_narration = current_narration if current_narration != turn.pop('narration_before', '') else ''
    turn.update(after=run.step, status_after=run.status, round=run.ctx.get('round', 0),
                llm_budget=dict(run.ctx['llm_budget']) if run.ctx.get('llm_budget') else None,
                message_through=db.scalar(select(Message.id).order_by(Message.id.desc()).limit(1)) or 0,
                milestones_after=milestones(db),
                action=changed_narration or f"{turn['node']} 실행 · 다음 단계 {run.step}")
    turn['actor'] = 'Proxy / Hive' if turn['node'] in ('ingest', 'help', 'bids','candidate_input','candidate_generate','candidate_assess','candidate_discuss','candidate_rank') else 'Hive'
    run.ctx = {**run.ctx, 'workflow_stage':stages.for_node(run,run.step),
               'execution_turns': run.ctx.get('execution_turns', [])+[turn]}
    from . import progress,store
    progress.publish(run,run.ctx['workflow_stage'],store.DEMO)


def _snapshot(title, value, level=2):
    return [f'{"#"*level} {title}', '', '```json', json.dumps(value, ensure_ascii=False, indent=2), '```', '']


def export(db, run):
    """Write the complete ordered conversation atomically, including resumed turns."""
    name = run.ctx.get('transcript_file')
    if not name:
        return
    people = {p.id: p.name for p in db.scalars(select(Person))}
    def person(pid, fallback):
        return f'{people.get(pid, pid)} ({pid})' if pid else fallback
    lines = [f'# Run {run.id} · {run.kind}', '',
             f'- 파일: {name}', '- 시간대: Asia/Seoul',
             f"- LLM 모드: {run.ctx.get('llm_mode','unknown')}",
             f"- 실행 출처: {run.ctx.get('transcript_origin','app')}",
             f'- 상태: {run.status} · 단계: {run.step}', '',
             '대화는 메시지 발생 순서대로 기록됩니다. 진행 중 제안과 동의도 포함합니다.', '']
    if run.ctx.get('pm_handoff'):
        notice=run.ctx['pm_handoff']
        lines += [f"- PM 전달: {notice['message']}",'- PM 결정 필요: '+('예' if notice['review_required'] else '아니오 · 기존 합의 배분 유지'),'']
        if notice.get('summary'):
            lines += _snapshot('PM 전달 · 현재 상황 summary',notice['summary'])
    if run.ctx.get('llm_budget'):
        budget=run.ctx['llm_budget']
        lines += [f"- Discussion 모델 호출: {budget['used']}/{budget['max']}회 (Live 전송 재시도 포함)", '']
    lines += _snapshot('초기 milestone', run.ctx.get('initial_milestones', {}))
    if run.kind == 'candidate':
        lines += _snapshot('초기 보드',run.ctx.get('initial_board',{}))
        lines += _snapshot('후보 생성 · Hive 검증',run.ctx.get('generation',{}))
        lines += _snapshot('검증된 새 milestone 후보',run.ctx.get('candidates',[]))
        lines += _snapshot('PM 최종 후보와 결정',dict(options=run.ctx.get('final_candidates',[]),selection=run.ctx.get('pm_selection'),status=run.status))
        lines += _snapshot('사용 프롬프트 버전',run.ctx.get('prompt_hashes',{}))
    demo_step=run.ctx.get('demo_step')
    if demo_step:
        lines += [f"데모 시연 {demo_step['index']}/{demo_step['total']} · {demo_step['label']}", '']
    lines += ['01·02·03은 처리 단계이며 협상 라운드와 별개입니다. 단계 재진입은 발생 순서대로 별도 섹션에 기록합니다.', '']
    messages=list(db.scalars(select(Message).where(Message.run_id==run.id).order_by(Message.id)))
    cursor=0
    def message_lines(number,m):
        sender=person(m.frm if m.k=='proxy' else m.who,
                      {'hive':'Hive','pm':'PM','person':'사람'}.get(m.k,'Proxy'))
        recipient=person(m.to,'전체 참여자')
        body=' · '.join(str(f.get('t','')) for f in (m.fields or [])) if m.k=='proxy' else m.text
        result=[f"#### 대화 {number}. {sender} → {recipient}",'',
            f"- 라운드: {m.round or 0} · 시도: {m.attempt} · 메시지: {m.id}",
            f"- 종류: {m.act or m.k} · 시각: {m.t}",'',body or '','']
        for label,value in [('사유',m.basis),('참고',m.pref),('발언',m.say)]:
            if value:result += [f'{label}: {value}','']
        return result
    stage_key=None
    for number,turn in enumerate(run.ctx.get('execution_turns',[]),1):
        stage=turn.get('stage') or stages.for_node(run,turn['node'])
        if stage_key!=stage['key']:
            lines += [f"## {stage['id']} · {stage['title']}",'']
            stage_key=stage['key']
        lines += [f"### 실행 턴 {number} · {turn['node']} · {turn['actor']}",'',
            f"- 라운드: {turn['round']} · {turn['before']} → {turn['after']}",
            f"- 상태: {turn['status_before']} → {turn['status_after']}",
            f"- 작업: {turn['action']}",
            f"- 대화 메시지 범위: {turn['message_after']} 초과 ~ {turn['message_through']} 이하",'']
        if turn.get('llm_budget'):
            budget=turn['llm_budget']
            lines += [f"- 누적 Discussion 모델 호출: {budget['used']}/{budget['max']}회", '']
        while cursor<len(messages) and messages[cursor].id<=turn['message_through']:
            lines += message_lines(cursor+1,messages[cursor]);cursor+=1
        lines += _snapshot('이 턴 이후 milestone',turn['milestones_after'],level=4)
    if cursor<len(messages):
        stage=run.ctx.get('workflow_stage') or stages.for_node(run,run.step)
        if stage_key!=stage['key']:
            lines += [f"## {stage['id']} · {stage['title']}",'']
        lines += ['### 추가 대화·사람 확인','']
        while cursor<len(messages):
            lines += message_lines(cursor+1,messages[cursor]);cursor+=1
    state = run.ctx.get('discussion') or {}
    if state.get('termination'):
        lines.extend([f"종료 사유: {state['termination']}", ''])
    if run.kind=='candidate' and run.ctx.get('termination'):
        lines += [f"종료 사유: {run.ctx['termination']}", '']
    lines += _snapshot('현재 / 최종 milestone', milestones(db))
    target_dir = directory(run.ctx.get('llm_mode','unknown'))
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / Path(name).name
    # Readers never see a half-written transcript.
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target_dir, delete=False) as tmp:
        temp_path = Path(tmp.name)
        tmp.write('\n'.join(lines))
    try:
        os.replace(temp_path, target)
        old_name=run.ctx.get('transcript_previous_file')
        if old_name:
            old=directory()/old_name
            if old.resolve().is_relative_to(directory().resolve()) and old.resolve()!=target.resolve():
                old.unlink(missing_ok=True)
    finally:
        temp_path.unlink(missing_ok=True)


@event.listens_for(Session, 'before_flush')
def collect(db, flush_context, instances):
    pending = db.info.setdefault('transcript_pending', {})
    for obj in list(db.new) + list(db.dirty):
        if isinstance(obj, Run):
            ensure_metadata(obj)
            pending[('run', id(obj))] = obj
        elif isinstance(obj, Message) and obj.run_id:
            pending[('id', obj.run_id)] = obj.run_id


@event.listens_for(Session, 'after_flush_postexec')
def refresh(db, flush_context):
    pending = db.info.pop('transcript_pending', {})
    runs = {}
    for item in pending.values():
        run = item if isinstance(item, Run) else db.get(Run, item)
        if run is not None:
            runs[run.id] = run
    for run in runs.values():
        ensure_metadata(run)
        if 'initial_milestones' not in run.ctx:
            run.ctx = {**run.ctx, 'initial_milestones': milestones(db)}
        export(db, run)
