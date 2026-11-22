"""Whole-task decomposition with explicit parallel parts and dependency edges."""
from types import SimpleNamespace
from . import hive, store
from .llm import Allocation
from .models import Task, Handoff


def permitted(source, item, people, partition=False):
    """A cross-role scope needs an explicit task contract, never an AI claim."""
    context=source.context or {}
    who=item['who']
    if who not in people:return False
    parts=context.get('required_parts') if partition else None
    if parts:
        return any(item.get('key')==p['key'] and item['what']==p['what'] and
                   abs(item['effort']-p['effort'])<=hive.EPS and who in p['assignees'] for p in parts)
    owners=context.get('allowed_assignees')
    return who in owners if owners is not None else people[who].role==source.role


def preview(b, ctx, proposal):
    st = b.clone()
    source = st.tasks[ctx['task']]
    if source.kind in ('done', 'milestone') or source.cut:
        raise ValueError('완료·삭제·완료 장벽은 재분해할 수 없음')
    items = [Allocation(**item).model_dump() for item in proposal]
    if not items or abs(sum(a['effort'] for a in items)-source.d)>hive.EPS:
        raise ValueError('원 Task 전체 분량을 보유분까지 빠짐없이 분담해야 함')
    if len(items) == 1:
        # Whole transfer retains the original task and all its incoming/outgoing edges.
        a = items[0]
        if a['depends_on'] or not permitted(source,a,b.people):
            raise ValueError('전체 양도의 수신자·역할·의존관계가 잘못됨')
        retained = a['who']==source.who
        source.who, source.d, source.plan = a['who'], a['days'], a['days']
        source.base=a['effort']
        if not retained:source.s0 = max(b.now, source.s0)
        source.title = a['title']
        hive.schedule(st)
        return st
    if (source.context or {}).get('splittable_hint') is False:
        raise ValueError('분리 금지된 업무의 전체 재분해는 허용되지 않음')
    if len({a['what'].strip() for a in items}) != len(items):
        raise ValueError('각 조각의 구체적인 업무 범위가 중복됨')
    keys = [a['key'] or f'part_{i+1}' for i,a in enumerate(items)]
    if len(set(keys)) != len(keys):
        raise ValueError('조각 key 중복')
    required=(source.context or {}).get('required_parts')
    if required and set(keys)!={p['key'] for p in required}:
        raise ValueError('Task에 명시된 필수 분리 범위를 모두 보존해야 함')
    graph = {key:list(a['depends_on']) for key,a in zip(keys,items)}
    order=[];pending=dict(graph)
    while pending:
        ready=[key for key,deps in pending.items() if all(dep in order for dep in deps)]
        if not ready:
            raise ValueError('조각 의존관계의 순환 또는 없는 key 참조')
        for key in ready:order.append(key);pending.pop(key)
    mapping={key:f'__discussion_{i}' for i,key in enumerate(keys)}
    inbound=[h for h in b.hands.values() if h.to_task==source.id and not h.done]
    def hand(frm,to,title):
        hid=f'__partition_link_{len(st.hands)}'
        st.hands[hid]=SimpleNamespace(id=hid,from_task=frm,to_task=to,title=title,what=title,
            t=b.week_end,done=False,prop=False,agreed=True,basis='전체 업무 분해 의존관계',oi=10**6+len(st.hands))
    for i,(key,a) in enumerate(zip(keys,items)):
        if not permitted(source,a,b.people,partition=True):
            raise ValueError('전체 분담안의 담당자 또는 역할 불일치')
        x=SimpleNamespace(**{f:getattr(source,f,None) for f in hive.TASK_FIELDS})
        x.id,x.title,x.who=mapping[key],a['title'],a['who']
        x.role=b.people[a['who']].role
        x.context={**(source.context or {})}
        if required:
            contract=next(p for p in required if p['key']==key)
            x.context.update(allowed_assignees=contract['assignees'],required_parts=[],splittable_hint=False)
        x.d=x.plan=a['days'];x.base=a['effort'];x.kind='new';x.cut=False
        # Retained, already assigned work keeps its original start. Re-starting
        # it at 'now' would count elapsed work a second time and make a valid
        # parallel split appear late. Newly delegated/dependent parts start now.
        retained = a['who'] == source.who and not graph[key]
        x.s0=x.s=source.s0 if retained else max(b.now,source.s0)
        # Keeping the original start is insufficient when several tasks share
        # that start: retained work must also keep its place in the owner's lane.
        x.oi=source.oi if retained else 10**6+order.index(key)
        st.tasks[x.id]=x
        for h in inbound:hand(h.from_task,x.id,h.title)
        for dep in graph[key]:hand(mapping[dep],x.id,f'{dep} → {key}')
        hand(x.id,source.id,a['what'])
    # Existing consumers retain the original Task/Handoff IDs and due dates.
    # This zero-effort barrier only completes when every part completes.
    source.d=source.plan=source.base=0;source.kind='milestone'
    source.context={**(source.context or {}), 'completion_barrier':True}
    hive.schedule(st)
    for key,h in st.hands.items():
        if key.startswith('__partition_link_'):h.t=hive.pred(st,h)
        if st.tasks[h.to_task].s+hive.EPS < hive.pred(st,h):
            raise ValueError('선후 의존 일정이 수렴하지 않음')
    return st


def apply(db, b, ctx, proposal, st):
    source=b.tasks[ctx['task']]
    planned=st.tasks[source.id]
    if planned.kind != 'milestone':
        source.who0=source.who0 or source.who
        source.who,source.d,source.plan,source.s0=planned.who,planned.d,planned.plan,planned.s0
        source.title=planned.title
        source.base=planned.base
        source.got=True
        return
    ids={}
    for key,x in sorted(st.tasks.items(),key=lambda entry:entry[1].oi):
        if not key.startswith('__discussion_'):continue
        tid=store.next_id(db,Task,'part');ids[key]=tid
        db.add(Task(id=tid,who=x.who,title=x.title,s0=x.s0,s=x.s,d=x.d,plan=x.d,base=x.base,
            tag=source.tag,role=x.role,context={**(x.context or {}),'partition_of':source.id,
                'description':proposal[int(key.rsplit('_',1)[1])]['what'],
                'deliverable':proposal[int(key.rsplit('_',1)[1])]['what']},
            kind='new',oi=x.oi if x.oi==source.oi else store.next_oi(db,Task)))
        db.flush()
    for key,h in st.hands.items():
        if not key.startswith('__partition_link_'):continue
        db.add(Handoff(id=store.next_id(db,Handoff,'h'),from_task=ids.get(h.from_task,h.from_task),
            to_task=ids.get(h.to_task,h.to_task),title=h.title,what=h.what,t=h.t,
            agreed=True,basis=h.basis,oi=store.next_oi(db,Handoff)))
        db.flush()
    source.d=source.plan=source.base=0;source.kind='milestone'
    source.context={**(source.context or {}), 'completion_barrier':True}
