"""Checked plan operators for scoped deferral, covered checks and staged deliverables.

An LLM may suggest an operator. A Task's explicit public contract determines whether
it is legal. These previews never grant consent or PM approval.
"""
from copy import deepcopy
from types import SimpleNamespace as NS
from sqlalchemy import delete
from .models import PlanAction
from .. import hive, discussion, plan_adjustments, task_partition, store
from ..models import Task,Handoff,HandoffEvent


def _link(st,source,target,what,due,basis):
    key='__action_link_'+str(len(st.hands))
    st.hands[key]=NS(id=key,from_task=source,to_task=target,title=what,what=what,t=due,
        done=False,prop=False,agreed=True,basis=basis,oi=10**6+len(st.hands))


def actions(st,raw_actions):
    seen=set();authorizers=set();confirm=set();pm_scope=False
    for raw in raw_actions or []:
        action=PlanAction.model_validate(raw);t=st.tasks.get(action.task)
        if not t or t.cut or t.kind in ('done','milestone','prop') or t.id in seen:
            raise ValueError('계획 연산의 대상이 없거나 완료·중복·분해 장벽임')
        seen.add(t.id);ctx=t.context or {}
        if t.s<st.now-hive.EPS:raise ValueError('이미 시작된 업무의 범위 이관·단계별 재구조화 금지')
        if action.kind=='defer':
            option=ctx.get('defer_option') or {}
            if not option or action.milestone!=option.get('milestone'):
                raise ValueError('이 Task의 범위 이관 권한이 명시되지 않음')
            targets=[t.id]+option.get('with_tasks',[])
            for tid in targets:
                x=st.tasks.get(tid)
                if not x or x.kind in ('done','milestone') or x.cut:raise ValueError('동반 이관 대상이 없거나 완료됨')
                if tid!=t.id and not (x.context or {}).get('deferred_with')==t.id:
                    raise ValueError('동반 이관 범위가 Task 계약과 다름')
                allowed={(v['from'],v['to']) for v in option.get('alpha_dependencies',[])}
                for h in st.hands.values():
                    if h.from_task==tid and not st.tasks[h.to_task].cut and (h.from_task,h.to_task) not in allowed and h.to_task not in targets:
                        raise ValueError('필수 후속 산출물이 있어 임의 이관 불가')
                # cut means absent from this milestone, not discarded effort. Preserve it
                # verbatim in the backlog with the approved target and effort provenance.
                x.cut=True;x.s0=x.s=max(st.week_end,x.s0)
                x.context={**(x.context or {}),'deferred_to':action.milestone,'deferred_from':'current',
                    'deferred_effort':x.d,'scope_basis':action.basis}
            authorizers.update(option.get('authorizers',[]));pm_scope=True
        elif action.kind=='omit':
            covered=ctx.get('covered_by');target=st.tasks.get(covered)
            coverage=set(ctx.get('coverage',[]))
            if not ctx.get('optional') or not target or target.cut or not coverage or not coverage<=set((target.context or {}).get('coverage',[])):
                raise ValueError('선택 검증의 동일 범위 대체 검증이 증명되지 않음')
            if target.d+ hive.EPS < (target.context or {}).get('minimum_days',target.d):
                raise ValueError('대체 검증의 필수 소요량 축소 금지')
            who=ctx.get('omit_requires_confirm')
            if who not in st.people:raise ValueError('검증 생략의 본인 확인 담당자 누락')
            confirm.add(who);t.cut=True
            t.context={**ctx,'omitted_in_favor_of':covered,'scope_basis':action.basis}
        else:
            contract=ctx.get('required_parts') or []
            if ctx.get('splittable_hint') is not True or not contract:raise ValueError('단계별 분해 계약이 없음')
            if {p.key for p in action.parts}!={p['key'] for p in contract} or len(action.parts)!=len(contract):
                raise ValueError('단계별 분해는 명시된 모든 범위를 보존해야 함')
            if abs(sum(p.effort for p in action.parts)-t.d)>hive.EPS:raise ValueError('단계별 분량 보존 위반')
            mapping={p.key:'__stage_'+t.id+'_'+p.key for p in action.parts}
            incoming=[h for h in st.hands.values() if h.to_task==t.id]
            routes=ctx.get('inbound_scope',{})
            def route(h):
                # A route is a list of part keys, or {parts, due}: the contract may name a
                # later promise for one inbound deliverable (never earlier than the original).
                r=routes[h.from_task]
                if isinstance(r,dict):return list(r.get('parts',[])),max(h.t,float(r.get('due',h.t)))
                return list(r),h.t
            for h in incoming:
                if h.from_task not in routes:raise ValueError('선행 산출물의 분해 범위 매핑 누락')
                del st.hands[h.id]
            for part in action.parts:
                ref=next(p for p in contract if p['key']==part.key)
                if part.what!=ref['what'] or abs(part.effort-ref['effort'])>hive.EPS or t.who not in ref['assignees']:
                    raise ValueError('단계별 범위·분량·담당 권한 위반')
                if set(part.depends_on)!=set(ref.get('depends_on',[])):
                    raise ValueError('단계별 필수 선후관계 변경 금지')
                x=NS(**{f:deepcopy(getattr(t,f,None)) for f in hive.TASK_FIELDS})
                x.id=mapping[part.key];x.title=part.title;x.d=x.plan=x.base=part.effort;x.kind='new'
                x.s0=x.s=max(st.now,t.s0,part.start if part.start is not None else t.s0)
                x.oi=10**6+len(st.tasks)
                x.context={**ctx,'required_parts':[],'splittable_hint':False,'partition_of':t.id,
                    'description':part.what,'deliverable':part.what}
                st.tasks[x.id]=x
                for dep in part.depends_on:
                    if dep not in mapping:raise ValueError('단계별 의존 범위가 없음')
                    _link(st,mapping[dep],x.id,'단계 선후관계',st.week_end,action.basis)
                for h in incoming:
                    keys,due=route(h)
                    if part.key in keys:_link(st,h.from_task,x.id,h.what,due,action.basis)
                _link(st,x.id,t.id,part.what,st.week_end,action.basis)
            # Keep the existing consumer edges and original Task ID as completion barrier.
            t.d=t.plan=t.base=0;t.kind='milestone';t.context={**ctx,'completion_barrier':True}
    return authorizers,confirm,pm_scope


def participants(b,st,ctx,allocations,extra=()):
    involved={b.tasks[ctx['task']].who,*(a['who'] for a in allocations),*extra}
    partition_parents={(t.context or {}).get('partition_of') for t in b.tasks.values() if (t.context or {}).get('partition_of')}
    for tid,old in b.tasks.items():
        new=st.tasks[tid]
        # For imported commitment-based scenarios, restoring a downstream task's
        # promised start is not a new condition requiring that person's consent.
        committed_part=(old.context or {}).get('partition_of') or tid in partition_parents
        expected=old.s0 if (b.tasks[ctx['task']].context or {}).get('active_participants_only') and not committed_part else old.s
        if (old.who,expected,old.d,old.cut,old.kind)!=(new.who,new.s,new.d,new.cut,new.kind):
            involved.update([old.who,new.who])
    for tid,t in st.tasks.items():
        if tid not in b.tasks:involved.add(t.who)
    return sorted(involved)


def preview(b,ctx,allocations,changes=None,plan_actions=None):
    if (b.tasks[ctx['task']].context or {}).get('requested_start_only') and any(a.get('task')==ctx['task'] and a.get('kind') in ('defer','omit') for a in plan_actions or []):
        raise ValueError('이 이슈는 요청 시각으로의 이동이며 업무 이관·생략을 허용하지 않습니다.')
    allowed=(b.tasks[ctx['task']].context or {}).get('allowed_change_tasks')
    if allowed is not None and any(c['task'] not in allowed for c in (changes or [])+(plan_actions or [])):
        raise ValueError('이 이슈에서 변경할 수 없는 무관한 업무')
    if not plan_actions:
        result,affected=discussion.preview(b,ctx,allocations,'whole_task',changes)
        source=b.tasks[ctx['task']]
        if (source.context or {}).get('active_participants_only'):affected=participants(b,result,ctx,allocations)
        if (source.context or {}).get('single_actor'):
            if abs(result.tasks[source.id].s-(source.context or {})['requested_start'])>hive.EPS:
                raise ValueError('요청한 일정 이동이 후보에 반영되지 않음')
            if set(affected)-{source.who}:raise ValueError('단독 일정 이동은 다른 당사자 변경을 포함할 수 없음')
        required=set((source.context or {}).get('transfer_requires_confirm',[])) & {a['who'] for a in allocations if a['who']!=source.who}
        return result,affected,sorted(required),False
    staged=plan_adjustments.stage(b,ctx,changes)
    st=task_partition.preview(staged,ctx,allocations)
    authorizers,confirm,pm_scope=actions(st,plan_actions)
    hive.schedule(st);plan_adjustments.check_support(st)
    # The issue task's contract may allow named handoff promises to move, up to a stated time,
    # when a plan needs it (e.g. G2 may receive A1's final art by Thu AM). Never earlier, never past it.
    for hid,due in ((b.tasks[ctx['task']].context or {}).get('repromise') or {}).items():
        h=st.hands.get(hid)
        if h and h.t+hive.EPS<hive.pred(st,h)<=float(due)+hive.EPS:h.t=hive.pred(st,h)
    if not hive.gate(st)['ok']:
        gate=hive.gate(st)
        raise ValueError('변경 계획 전체 제약 위반: '+'; '.join(v['text'] for v in gate['violations']+gate['warnings']))
    for h in st.hands.values():
        if h.id.startswith('__action_link_') and h.what=='단계 선후관계':h.t=hive.pred(st,h)
    affected=participants(b,st,ctx,allocations,authorizers|confirm)
    return st,affected,sorted(confirm),pm_scope


def apply(db,b,st,ctx=None,allocations=None):
    """Persist an already validated board diff in the caller's transaction."""
    mapping={}
    for tid,t in st.tasks.items():
        if tid.startswith('__discussion_') and ctx and allocations:
            item=allocations[int(tid.rsplit('_',1)[1])]
            t.context={**(t.context or {}),'partition_of':ctx['task'],'description':item['what'],'deliverable':item['what']}
        if tid in b.tasks:row=b.tasks[tid]
        else:
            key=store.next_id(db,Task,'part');mapping[tid]=key
            row=Task(id=key,who=t.who,title=t.title,s0=t.s0,s=t.s,d=t.d,plan=t.plan,base=t.base,
                tag=t.tag,role=t.role,oi=t.oi if t.oi<10**6 else store.next_oi(db,Task));db.add(row);db.flush()
        if row.who!=t.who:row.who0=row.who0 or row.who;row.got=True
        for field in ('who','title','s0','s','d','plan','base','tag','role','kind','cut','context'):
            setattr(row,field,deepcopy(getattr(t,field)))
    for hid in set(b.hands)-set(st.hands):
        db.execute(delete(HandoffEvent).where(HandoffEvent.handoff_id==hid))
        db.delete(b.hands[hid])
    for hid,h in st.hands.items():
        if hid in b.hands:row=b.hands[hid]
        else:
            row=Handoff(id=store.next_id(db,Handoff,'h'),from_task=mapping.get(h.from_task,h.from_task),to_task=mapping.get(h.to_task,h.to_task),
                title=h.title,what=h.what,t=h.t,oi=store.next_oi(db,Handoff));db.add(row);db.flush()
        for field in ('title','what','t','done','prop','agreed','basis'):
            setattr(row,field,getattr(h,field))
        row.from_task=mapping.get(h.from_task,h.from_task);row.to_task=mapping.get(h.to_task,h.to_task)
