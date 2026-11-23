"""Dated demo issue suggestions; selecting an example never calls an LLM."""
from pathlib import Path
import yaml
from sqlalchemy import select
from . import hive
from .models import Run


def catalog():
    from . import store
    path=store.SEED/'m4_t6_game_demo'/'timeline.yaml'
    return yaml.safe_load(path.read_text())['issues']


def describe(db,b):
    from . import store
    if store.meta(db,'demo')!='m4_t6_game_demo':return None
    runs=list(db.scalars(select(Run).where(Run.kind=='candidate').order_by(Run.id)))
    handled={r.ctx.get('timeline_event') for r in runs if r.ctx.get('termination')=='applied'}
    events=[]
    for raw in catalog():
        event=dict(raw);task=b.tasks.get(event['task'])
        complete=not task or task.cut or task.kind=='done' or task.d<=hive.EPS
        reason='이미 처리한 이슈입니다.' if event['id'] in handled else '완료되었거나 현재 보드에서 실행할 수 없는 업무입니다.' if complete else '아직 해당 날짜가 아닙니다.' if b.now<event['day_from']-hive.EPS else '보고 가능 시각이 지났습니다.' if b.now>event['day_until']+hive.EPS else '앞선 기한 회복 이슈를 먼저 해결하세요.' if event.get('requires_valid_board') and not hive.gate(b)['ok'] else ''
        if not reason and 'requested_start' in event:
            trial=b.clone();trial.tasks[event['task']].s0=event['requested_start'];hive.schedule(trial)
            if not hive.gate(trial)['ok']:reason='현재 합의된 다른 업무와 충돌합니다. 다른 이슈를 선택하거나 추가 조정을 요청하세요.'
        event.update(available=not bool(reason),reason=reason)
        events.append(event)
    events.sort(key=lambda x:(not x['available'],-x.get('priority',0),x['day_from']))
    return {'events':events,'runs':[{'id':r.id,'status':r.status,'termination':r.ctx.get('termination'),
        'issue':r.ctx.get('issue',''),'day':r.ctx.get('board_snapshot',{}).get('now'),'event':r.ctx.get('timeline_event')} for r in runs]}


def apply_report(db,event_id,issue):
    from . import store
    b=store.board(db);hive.schedule(b)
    data=describe(db,b)
    event=next((e for e in (data or {}).get('events',[]) if e['id']==event_id),None)
    if not event or not event['available']:raise ValueError((event or {}).get('reason') or '현재 시나리오의 날짜별 이슈가 아닙니다.')
    base=issue.split('\n\n참조:')[0].split('\n\nReferences:')[0].strip()
    if base!=event['text']:raise ValueError('날짜별 예시 내용이 변경됐습니다. 일반 이슈로 보내 주세요.')
    if 'requested_start' in event:
        t=b.tasks[event['task']]
        if t.s<b.now-hive.EPS:raise ValueError('이미 착수한 업무는 시작 이동 예시로 바꿀 수 없습니다.')
        t.context={**(t.context or {}),'requested_start':event['requested_start'],'single_actor':True,'requested_start_only':True}
    return event
