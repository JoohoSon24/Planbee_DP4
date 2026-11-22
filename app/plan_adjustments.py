"""Additional task moves and explicit collaboration, staged without mutation."""
from types import SimpleNamespace as NS
from . import hive,store
from .llm import ScheduleChange
from .models import Task,Handoff


def stage(b,ctx,changes):
    st=b.clone();seen=set()
    for raw in changes or []:
        c=ScheduleChange.model_validate(raw);t=st.tasks.get(c.task)
        if c.task in seen or not t or t.cut or t.kind in ('done','prop','milestone'):
            raise ValueError('일정 변경 대상이 없거나 중복·완료·가약속 업무임')
        seen.add(c.task)
        moved=c.who is not None and c.who!=t.who
        shifted=c.start is not None and abs(c.start-t.s0)>hive.EPS
        if moved or shifted:
            if t.s<b.now-hive.EPS:raise ValueError('이미 시작한 업무의 담당·시작 이동 불가')
        if shifted:
            if c.start<b.now-hive.EPS or c.start>=b.week_end-hive.EPS:raise ValueError('제출일 밖 또는 과거로 일정 이동 불가')
            t.s0=c.start
        if moved:
            if c.who not in b.people or b.people[c.who].role!=t.role:raise ValueError('다른 업무 양도의 수신자·역할 불일치')
            if c.who not in (t.context or {}).get('allowed_assignees',[c.who]):raise ValueError('Task 전담 담당자 변경 금지')
            t.who=c.who
            t.d=c.days or hive.scaled_days(b,t.d,t.tag,c.who,b.tasks[c.task].who)
            t.plan=t.d
        if c.days is not None:
            if c.task==ctx['task']:raise ValueError('원 Task의 소요량은 allocations로 제안해야 함')
            if not moved and (not c.support or not c.basis.strip()):
                raise ValueError('소요시간 변경에는 구체적 협업 지원과 단축 근거가 필요함')
            if c.days<max(0,b.now-t.s)-hive.EPS:raise ValueError('이미 경과한 업무를 과거에 완료한 것으로 단축할 수 없음')
            t.d=t.plan=c.days
        if c.support and not c.basis.strip():raise ValueError('협업의 범위·단축 근거가 필요함')
        if c.support and (t.context or {}).get('allow_collaboration') is False:raise ValueError('Task의 협업 단축 금지')
        helpers=set()
        outgoing=[h for h in b.hands.values() if h.from_task==c.task and not h.done]
        for i,part in enumerate(c.support):
            if part.who not in b.people or part.who==t.who or part.who in helpers or not part.what.strip():
                raise ValueError('협업 지원자·범위가 잘못되거나 중복됨')
            helpers.add(part.who)
            tid=f'__support_{c.task}_{i}'
            x=NS(**{f:getattr(t,f,None) for f in hive.TASK_FIELDS})
            x.id,x.who,x.title=tid,part.who,'협업 · '+t.title
            x.d=x.plan=x.base=part.days;x.s0=x.s=max(b.now,t.s0)
            x.kind='new';x.oi=10**6+len(st.tasks);x.context={'description':part.what,'collaboration_for':c.task,'basis':c.basis}
            st.tasks[tid]=x
            for h in outgoing:
                hid=tid+'_'+h.id
                st.hands[hid]=NS(id=hid,from_task=tid,to_task=h.to_task,title=x.title,what=part.what,
                    t=h.t,done=False,prop=False,agreed=True,basis=c.basis,oi=10**6+len(st.hands))
    return st


def check_support(st):
    for key,t in st.tasks.items():
        if key.startswith('__support_'):
            main=st.tasks[t.context['collaboration_for']]
            if t.s+t.d>main.s+main.d+hive.EPS:raise ValueError('협업 지원이 본 업무 완료보다 늦음: '+t.title)


def incoming(b,st,ctx,proposal,pid):
    work=[dict(title=a['title'],days=a['days'],what=a['what']) for a in proposal if a['who']==pid and pid!=b.tasks[ctx['task']].who]
    for key,t in st.tasks.items():
        if t.who==pid and (key.startswith('__support_') or (key in b.tasks and b.tasks[key].who!=pid)):
            work.append(dict(title=t.title,days=t.d,what=(t.context or {}).get('description',t.title)))
    return work


def apply(db,b,ctx,changes,st):
    for raw in changes or []:
        tid=raw['task'];t=b.tasks[tid];planned=st.tasks[tid]
        if tid!=ctx['task']:
            if t.who!=planned.who:t.who0=t.who0 or t.who;t.got=True
            t.who,t.d,t.plan,t.s0=planned.who,planned.d,planned.plan,planned.s0
        elif raw.get('start') is not None:t.s0=planned.s0
    ids={}
    for key,t in st.tasks.items():
        if not key.startswith('__support_'):continue
        tid=store.next_id(db,Task,'support');ids[key]=tid
        db.add(Task(id=tid,who=t.who,title=t.title,s0=t.s0,s=t.s,d=t.d,plan=t.d,base=t.base,
            tag=t.tag,role=b.people[t.who].role,kind='new',context=t.context,oi=store.next_oi(db,Task)))
        db.flush()
    for h in st.hands.values():
        if h.from_task not in ids:continue
        db.add(Handoff(id=store.next_id(db,Handoff,'h'),from_task=ids[h.from_task],to_task=h.to_task,
            title=h.title,what=h.what,t=h.t,agreed=True,basis=h.basis,oi=store.next_oi(db,Handoff)))
        db.flush()
