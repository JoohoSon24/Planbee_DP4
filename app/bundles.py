"""Atomic, explicit multi-task transfers. No LLM: propose -> all consent -> revalidate -> commit.
amount is effort in the source owner's current estimate; omitted means the whole task.
Partial/multi-target splits retain the original task ID as a zero-duration completion barrier.
"""
from __future__ import annotations
import hashlib
import json
import math
from types import SimpleNamespace
from uuid import uuid4
from sqlalchemy import select, update
from . import hive, store
from .policies import needs_review
from .models import Card, Confirmation, Handoff, Meta, Person, Rule, Run, Task


def lock(db):
    # A common write lock serializes HTTP mutations, including card changes and confirmations.
    # SQLite obtains its writer lock here; other SQL databases lock this metadata row.
    db.execute(update(Meta).where(Meta.key == 'demo').values(value=Meta.value))


def fingerprint(db):
    data={m.__tablename__:[{c.name:getattr(x,c.name) for c in m.__table__.columns}
          for x in db.scalars(select(m).order_by(*m.__table__.primary_key.columns))]
          for m in (Person,Card,Task,Handoff,Rule)}
    data['now']=store.meta(db,'now'); data['demo']=store.meta(db,'demo')
    return hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def _acyclic(b):
    ids={k for k,t in b.tasks.items() if not t.cut};edges={k:set() for k in ids}
    for h in b.hands.values():
        if h.from_task in ids and h.to_task in ids:edges[h.from_task].add(h.to_task)
    for pid in b.people:
        lane=sorted((t for t in b.tasks.values() if t.id in ids and t.who==pid and t.kind!='milestone'),key=lambda t:(t.s0,t.oi))
        for a,c in zip(lane,lane[1:]):edges[a.id].add(c.id)
    deg={k:0 for k in ids}
    for v in edges.values():
        for k in v:deg[k]+=1
    todo=[k for k in ids if deg[k]==0];count=0
    while todo:
        k=todo.pop();count+=1
        for c in edges[k]:
            deg[c]-=1
            if deg[c]==0:todo.append(c)
    if count!=len(ids):raise ValueError('작업 의존관계와 담당자 순서에 순환이 생김')


def plan(db,transfers,prefix='__preview_bundle'):
    if not 1<=len(transfers)<=32:raise ValueError('묶음 이동은 1~32개')
    b=store.board(db);st=b.clone();groups={};seen=set();incoming={};owners=set()
    for raw in transfers:
        tid,to=raw.get('task'),raw.get('to');t=b.tasks.get(tid)
        if not t or t.cut or t.kind in ('done','prop','milestone') or t.s<b.now-hive.EPS:
            raise ValueError('아직 시작하지 않은 일반 작업만 옮길 수 있음')
        if to not in b.people or to==t.who or b.people[to].role!=t.role:raise ValueError('수신자 또는 역할이 잘못됨')
        if (tid,to) in seen:raise ValueError('같은 작업·수신자의 중복 이동')
        seen.add((tid,to));amount=t.d if raw.get('amount') is None else raw['amount']
        if not isinstance(amount,(float,int)) or not math.isfinite(amount) or amount<=0 or abs(amount*2-round(amount*2))>hive.EPS:
            raise ValueError('amount는 유한한 양수, 0.5일 단위여야 함')
        if t.tag in (store.card(db,to).refuse_tags or []):raise ValueError(f'{b.people[to].name}의 카드가 {t.tag} 업무를 거부함')
        days=hive.scaled_days(b,amount,t.tag,to,t.who)
        groups.setdefault(tid,[]).append(dict(to=to,amount=float(amount),days=days))
        incoming[to]=incoming.get(to,0)+days;owners.add(t.who)
    next_oi=max((t.oi for t in b.tasks.values()),default=0)+1
    next_hi=max((h.oi for h in b.hands.values()),default=0)+1
    def hand(frm,to,title,at):
        nonlocal next_hi
        hid=f'{prefix}_h{next_hi}';next_hi+=1
        if hid in st.hands:raise ValueError('생성 ID 충돌')
        st.hands[hid]=SimpleNamespace(id=hid,from_task=frm,to_task=to,title=title,what=title,t=at,done=False,prop=False,agreed=True,basis='묶음 분배 의존관계',oi=next_hi)
    for tid,parts in groups.items():
        src=b.tasks[tid];t=st.tasks[tid];total=sum(x['amount'] for x in parts)
        if total>src.d+hive.EPS:raise ValueError('분배량 합계가 원래 작업량보다 큼')
        if len(parts)==1 and abs(total-src.d)<=hive.EPS:
            t.who0=src.who;t.who=parts[0]['to'];t.d=t.plan=parts[0]['days'];t.base=src.d;t.kind='new';t.got=True
            continue
        # Each part can proceed independently; all original consumers wait at the original ID.
        # Milestones do not consume a person's resource lane.
        remainder=src.d-total
        allocations=parts+([dict(to=src.who,amount=remainder,days=remainder)] if remainder>hive.EPS else [])
        t.d=t.plan=t.base=0;t.kind='milestone'
        t.context={**(src.context or {}), 'completion_barrier':True}
        inbound=[h for h in b.hands.values() if h.to_task==tid and not h.done]
        deadlines=[h.t for h in b.hands.values() if h.from_task==tid and not h.done]
        deadline=min(deadlines,default=b.week_end)
        for i,a in enumerate(allocations):
            new=f'{prefix}_{tid}_{i}'
            if new in st.tasks:raise ValueError('생성 ID 충돌')
            vals={f:getattr(src,f) for f in hive.TASK_FIELDS}
            vals.update(id=new,title=f'{src.title} · 조각 {i+1}',who=a['to'],who0=src.who,d=a['days'],plan=a['days'],base=a['amount'],kind='new',got=True,oi=next_oi,cut_options=[])
            next_oi+=1;st.tasks[new]=SimpleNamespace(**vals)
            for h in inbound:hand(h.from_task,new,h.title,h.t)
            hand(new,tid,vals['title']+' 완료',deadline)
    _acyclic(st);hive.schedule(st)
    gate=hive.gate(st)
    if gate['violations'] or gate['warnings']:
        raise ValueError('묶음 전체 일정 검사 실패: '+'; '.join(x['text'] for x in gate['violations']+gate['warnings']))
    for h in st.hands.values():
        if st.tasks[h.to_task].s+hive.EPS<hive.pred(st,h):raise ValueError('의존관계 계산이 수렴하지 않음')
    required={pid:[] for pid in owners}
    for pid in owners:required[pid].append('내 작업을 넘기는 데 동의')
    for pid,days in incoming.items():
        if days>store.card(db,pid).auto_days+hive.EPS or needs_review(store.card(db,pid)):required.setdefault(pid,[]).append(f'받는 일 합계 {days:g}일의 권한 또는 바쁨 메모 확인')
    return st,dict(transfers=transfers,fairness=hive.fairness(st),loads={pid:hive.load_of(st,pid) for pid in st.people},incoming=incoming,
                   confirmations=[dict(who=k,reasons=v) for k,v in sorted(required.items())],
                   tasks=[{f:getattr(t,f) for f in hive.TASK_FIELDS} for t in st.tasks.values()],
                   handoffs=[{f:getattr(h,f) for f in hive.HAND_FIELDS} for h in st.hands.values()])


def view(run):
    return dict(id=run.id,status=run.status,outcome=run.ctx.get('outcome','pending'),
                error=run.ctx.get('error'),preview=run.ctx['preview'],waiting_for=run.ctx.get('waiting_for',[]))


def propose(db,transfers):
    from . import workflow
    lock(db)
    if db.scalars(select(Run).where(Run.status.in_(['waiting_confirm','waiting_pm']))).first():raise ValueError('진행 중인 협상을 먼저 마쳐야 함')
    prefix='bundle_'+uuid4().hex[:12]
    _,pv=plan(db,transfers,prefix)
    store.snap(db)
    run=Run(kind='bundle',step='bundle_wait',status='waiting_confirm',auto_confirm=False,
            ctx=dict(demo_step=store.meta(db,"demo_step",None),prefix=prefix,transfers=transfers,preview=pv,fingerprint=fingerprint(db),waiting_for=[]))
    db.add(run);db.flush();ids=[]
    for c in pv['confirmations']:
        cf=workflow.ask_person(db,run,c['who'],'묶음 전체에 동의하나요? '+ ' / '.join(c['reasons']),
                               '묶음 이동 전체에 동의',None,'bundle');ids.append(cf.id)
    run.ctx={**run.ctx,'waiting_for':ids}
    store.hive_say(db,f'묶음 {run.id} 제안 · {len(transfers)}개 이동 · 아직 작업 배정은 변경하지 않음',run_id=run.id)
    db.flush()
    return run


def cancel(db,run,error='당사자가 묶음 전체를 거절함',outcome='cancelled'):
    for c in db.scalars(select(Confirmation).where(Confirmation.run_id==run.id,Confirmation.status=='pending')):c.status='cancelled'
    run.ctx={**run.ctx,'outcome':outcome,'error':error};run.status='done';run.step='done'
    store.hive_say(db,f'묶음 {run.id} {outcome} · 배정 변경 없음 · {error}',run_id=run.id);db.flush()
    return run


def _resume(db,run):
    from . import workflow
    lock(db)
    cs=list(db.scalars(select(Confirmation).where(Confirmation.run_id==run.id)))
    if any(c.status=='rejected' for c in cs):return cancel(db,run)
    if any(c.status=='pending' for c in cs):run.status='waiting_confirm';return run
    if not cs or any(c.status!='confirmed' for c in cs):return cancel(db,run,'동의 기록이 완전하지 않음','invalidated')
    db.flush();db.expire_all()
    if fingerprint(db)!=run.ctx['fingerprint']:return cancel(db,run,'일정·카드·규칙이 바뀌어 다시 제안해야 함','invalidated')
    try:_,pv=plan(db,run.ctx['transfers'],run.ctx['prefix'])
    except ValueError as e:return cancel(db,run,str(e),'invalidated')
    # Both task/handoff writes and outcome become visible only at the outer DB commit.
    # Savepoint also protects callers that catch a write failure and keep their Session alive.
    with db.begin_nested():
        for vals in pv['tasks']:
            row=db.get(Task,vals['id'])
            if row:
                for k,v in vals.items():setattr(row,k,v)
            else:db.add(Task(**vals))
        db.flush()
        for vals in pv['handoffs']:
            row=db.get(Handoff,vals['id'])
            if row:
                for k,v in vals.items():setattr(row,k,v)
            else:db.add(Handoff(**vals))
        run.ctx={**run.ctx,'outcome':'committed'};run.status='done';run.step='done'
        store.add_record(db,'PM',f'묶음 {run.id} · {len(run.ctx["transfers"])}개 이동 전체 확정')
        store.hive_say(db,f'묶음 {run.id} 전체 확정 · 부분 적용 없음',run_id=run.id)
        db.flush()
    return run


def resume(db, run):
    from . import runlogs
    turn = runlogs.start_turn(db, run, 'bundle_wait')
    result = _resume(db, run)
    if run.status == 'done' and run.ctx.get('phase_after'):
        store.set_meta(db, 'phase', run.ctx['phase_after'])
    db.flush()
    runlogs.finish_turn(db, run, turn)
    db.flush()
    return result
