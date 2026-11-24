"""AI defines semantic scopes; deterministic bounded enumeration checks schedules."""
from copy import deepcopy
from hashlib import sha256
from itertools import product
import json
import random
from .models import Transformation, Part, PlanAction, ScheduledPart
from . import plans
from .. import hive, discussion


def digest(value):
    return sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()


def snapshot(b):
    return dict(now=b.now,cap=b.cap,week_end=b.week_end,
        tasks={k:{f:deepcopy(getattr(t,f,None)) for f in hive.TASK_FIELDS} for k,t in b.tasks.items()},
        handoffs={k:{f:deepcopy(getattr(h,f,None)) for f in hive.HAND_FIELDS} for k,h in b.hands.items()},
        people={k:dict(role=p.role,rec=p.rec,capacity=hive.capacity(b,k),
            unavailable=[dict(start=w['start'],end=w['end']) for w in hive.policy(b,k).get('unavailable',[])])
            for k,p in b.people.items()})


def view(b):
    return dict(tasks=[dict(id=t.id,who=t.who,title=t.title,start=t.s,days=t.d,kind=t.kind,
                           context=t.context or {}) for t in b.tasks.values() if not t.cut],
        handoffs=[dict(id=h.id,source=h.from_task,target=h.to_task,title=h.title,due=h.t,
                       expected=hive.pred(b,h),agreed=bool(h.agreed)) for h in b.hands.values() if not h.done],
        milestones=[dict(id=t.id,title=t.title,who=t.who,start=t.s,end=t.s+t.d)
                    for t in b.tasks.values() if t.kind=='milestone' and not t.cut],
        deferred=[dict(id=t.id,title=t.title,who=t.who,days=t.d,to=(t.context or {}).get('deferred_to')) for t in b.tasks.values() if t.cut and (t.context or {}).get('deferred_to')],
        omitted=[dict(id=t.id,title=t.title,covered_by=(t.context or {}).get('omitted_in_favor_of')) for t in b.tasks.values() if t.cut and (t.context or {}).get('omitted_in_favor_of')],
        fairness=hive.fairness(b),gate=hive.gate(b))


def canonical(allocations,changes,plan_actions=None):
    # Titles and arbitrary part keys do not make a distinct plan.
    by_key={a.get('key'):a['what'].strip() for a in allocations if a.get('key')}
    parts=[dict(who=a['who'],what=a['what'].strip(),effort=round(a['effort'],8),days=round(a['days'],8),
                dependencies=sorted(by_key.get(d,d) for d in a.get('depends_on',[]))) for a in allocations]
    payload=dict(parts=sorted(parts,key=lambda x:json.dumps(x,sort_keys=True)),changes=sorted(changes,key=lambda x:json.dumps(x,sort_keys=True)))
    if plan_actions:
        normalized=[]
        for action in plan_actions:
            item={k:action[k] for k in ('kind','task','milestone') if action.get(k) is not None}
            names={p['key']:p['what'].strip() for p in action.get('parts',[])}
            if action.get('parts'):
                item['parts']=sorted([dict(what=p['what'].strip(),effort=p['effort'],start=p.get('start'),depends_on=sorted(names.get(k,k) for k in p.get('depends_on',[]))) for p in action['parts']],key=lambda v:json.dumps(v,sort_keys=True))
            normalized.append(item)
        payload['plan_actions']=sorted(normalized,key=lambda x:json.dumps(x,sort_keys=True))
    return digest(payload)


def execution_key(st,allocations,plan_actions=None):
    """Identity is the validated execution, not decorative text or release hints."""
    labels={}
    for tid,t in st.tasks.items():
        context=t.context or {}
        if tid.startswith('__discussion_'):
            item=allocations[int(tid.rsplit('_',1)[1])];labels[tid]='part:'+item['what'].strip()
        elif tid.startswith('__'):
            labels[tid]='aux:'+digest(dict(who=t.who,scope=context.get('description',t.title),parent=context.get('partition_of') or context.get('collaboration_for')))
        else:labels[tid]=tid
    tasks=sorted([dict(id=labels[t.id],who=t.who,start=round(t.s,8),days=round(t.d,8),cut=t.cut,kind=t.kind) for t in st.tasks.values()],key=lambda x:json.dumps(x,sort_keys=True))
    links=sorted([dict(source=labels[h.from_task],target=labels[h.to_task],due=round(h.t,8),done=h.done) for h in st.hands.values()],key=lambda x:json.dumps(x,sort_keys=True))
    scope_actions=deepcopy(plan_actions or [])
    for action in scope_actions:
        for part in action.get('parts',[]):part.pop('start',None)
    return digest(dict(scope=canonical(allocations,[],scope_actions),tasks=tasks,links=links))


def authorized(b,source_id,action):
    """Only operators whose explicit Task contract exists can be proposed (see plans.apply_actions)."""
    t=b.tasks.get(action.task);ctx=(t.context or {}) if t else {}
    if not t:return False
    if action.kind=='defer':return bool(ctx.get('defer_option'))
    if action.kind=='omit':return bool(ctx.get('optional') and ctx.get('covered_by'))
    if action.kind=='restructure':return action.task!=source_id and bool(ctx.get('required_parts') and ctx.get('inbound_scope'))
    return False


def enumerate_plans(b,ctx,templates,settings):
    """No private cards or fairness ordering. Every yielded plan passed full Hive."""
    source=b.tasks[ctx['task']]
    whole=Transformation(title='원 업무 전체 유지·양도',basis='원 업무의 산출물과 완료 기준 전체를 보존한다.',
        parts=[Part(key='whole',title=source.title,what=(source.context or {}).get('deliverable') or source.title,
                    effort=source.d)])
    # 최상위 parts 가 빈 LLM 템플릿은 원 Task 전체를 그대로 보유하는 구조로 본다.
    templates=[t if t.parts else t.model_copy(update={'parts':list(whole.parts)}) for t in templates]
    # 권한 계약이 없는 plan_actions(예: 분해를 restructure로 표현)는 그 항목만 떼어 내고 나머지 구조를 살린다.
    # 권한 우회가 아니다: 남은 구조도 Hive 전체 검증을 그대로 받는다.
    removed=0;cleaned=[]
    for t in templates:
        keep=[a for a in t.plan_actions if authorized(b,source.id,a)]
        removed+=len(t.plan_actions)-len(keep)
        cleaned.append(t if len(keep)==len(t.plan_actions) else t.model_copy(update={'plan_actions':keep}))
    templates=[whole]+cleaned
    contract=(source.context or {}).get('required_parts',[])
    contract_template=None
    if contract and abs(sum(p['effort'] for p in contract)-source.d)<=hive.EPS:
        contract_template=Transformation(title='Task에 명시된 산출물 분담',basis='Task 원문에 명시된 분리 경계·분량·담당 권한을 그대로 보존한다.',
            parts=[Part(**{k:v for k,v in p.items() if k!='assignees'}) for p in contract])
        templates.append(contract_template)
    # Explicit author-provided transformation contracts are additional structures,
    # not a preselected winner. LLM proposals and these structures share validation.
    option=(source.context or {}).get('defer_option')
    if option:
        templates.append(Transformation(**{**whole.model_dump(),'title':'선택 범위의 후속 milestone 이관',
            'plan_actions':[dict(kind='defer',task=source.id,milestone=option['milestone'],basis='Task에 명시된 선택 범위와 동반 산출물을 후속 milestone으로 보존하여 이관한다.')] }))
    # Optional (P1) tasks this issue may touch can leave the milestone as a declared contract
    # option. Paired with each base structure so a deferral is a real alternative, not noise.
    deferrable=[b.tasks[x] for x in (source.context or {}).get('allowed_change_tasks',[])
                if x!=source.id and x in b.tasks and (b.tasks[x].context or {}).get('defer_option') and (b.tasks[x].context or {}).get('optional')]
    def defer_action(x):
        return dict(kind='defer',task=x.id,milestone=x.context['defer_option']['milestone'],basis='Task에 명시된 선택 업무를 후속 milestone으로 보존하여 이관한다.')
    for base_template in [whole]+([contract_template] if contract_template else []):
        for x in deferrable:
            templates.append(Transformation(**{**base_template.model_dump(),'title':base_template.title+' + '+x.title+' 이관','plan_actions':[defer_action(x)]}))
    reachable={source.id}
    for _ in b.tasks:
        reachable.update(h.to_task for h in b.hands.values() if h.from_task in reachable)
    for task in b.tasks.values():
        scope=task.context or {};required=scope.get('required_parts')
        if task.id==source.id or task.id not in reachable or not scope.get('inbound_scope') or not required:continue
        action=PlanAction(kind='restructure',task=task.id,basis='명시된 중간 산출물 범위를 보존하고 선행 산출물은 필요한 최종 조각에만 연결한다.',
            parts=[ScheduledPart(**{k:v for k,v in part.items() if k!='assignees'}) for part in required])
        variants_actions=[[action]]+[[action,PlanAction(**defer_action(x))] for x in deferrable]
        for check in b.tasks.values():
            if check.id in reachable and (check.context or {}).get('covered_by'):
                variants_actions.append([action,PlanAction(kind='omit',task=check.id,basis='동일 검증 항목이 최종 검증에 포함되는 선택 중간 검증만 본인 확인을 조건으로 생략한다.')])
        # The downstream restructure may pair with the source's own contract pieces
        # (e.g. A1 rough/final + G2 temporary/final). Both contracts are explicit.
        for base_template in [whole]+([contract_template] if contract_template else []):
            for acts in variants_actions:
                templates.append(Transformation(**{**base_template.model_dump(),
                    'title':'중간 산출물과 최종 반영의 단계별 재설계' if base_template is whole else '산출물 분담과 후속 단계별 재설계',
                    'plan_actions':[a.model_dump() for a in acts]}))
    randomizer=random.Random(settings.seed)
    # Round-robin across semantic templates and operation families avoids first-template bias.
    def variants(template):
        if abs(sum(p.effort for p in template.parts)-source.d)>hive.EPS:return
        if len(template.parts)>1 and (source.context or {}).get('splittable_hint') is False:return
        if len({p.what.strip() for p in template.parts})!=len(template.parts):return
        from ..task_partition import permitted
        choices=[[pid for pid in sorted(b.people) if permitted(source,dict(who=pid,**part.model_dump()),b.people,len(template.parts)>1)] for part in template.parts]
        assignments=list(product(*choices))
        randomizer.shuffle(assignments)
        def one_assignment(owners):
            allocations=[dict(who=who,title=part.title,what=part.what,key=part.key,depends_on=part.depends_on,
                effort=part.effort,days=part.effort if who==source.who else hive.scaled_days(b,part.effort,source.tag,who,source.who))
                for who,part in zip(owners,template.parts)]
            base_changes=[c.model_dump(exclude_none=True) for c in template.schedule_changes]
            if template.support:
                if (source.context or {}).get('allow_collaboration') is False:return
                if len(allocations)!=1:return
                sup=template.support
                helpers=[p.id for p in b.people.values() if p.role==sup.role and p.id!=owners[0]]
                for helper in helpers:
                    plan=deepcopy(allocations);plan[0]['days']*=sup.main_ratio
                    yield plan,[dict(task=source.id,basis=sup.basis,support=[dict(who=helper,days=sup.days,what=sup.what)])],'collaborate',template
                return
            yield allocations,base_changes,'split' if len(allocations)>1 else 'transfer',template
            # A request to move the source itself must be enumerable as well.
            context=source.context or {}
            for start in [context['requested_start']] if 'requested_start' in context else []:
                yield allocations,base_changes+[dict(task=source.id,start=start)],'move',template
            if (source.context or {}).get('single_actor'):return
            # Move another not-started task or shift its release time. Preserve effort/role.
            for t in sorted(b.tasks.values(),key=lambda t:t.id):
                if t.id not in (source.context or {}).get('allowed_change_tasks',b.tasks):continue
                if t.id==source.id or t.cut or t.kind in ('done','milestone','prop') or t.s<b.now-hive.EPS:continue
                # A task this template already restructures is not also moved as a side change.
                if t.id in {a.task for a in template.plan_actions}:continue
                for pid in sorted(b.people):
                    if pid!=t.who and b.people[pid].role==t.role:
                        yield allocations,base_changes+[dict(task=t.id,who=pid)],'compose',template
                # Search the entire remaining horizon, not just +/- half a day.
                # Try grid boundaries deterministically; Hive handles release, availability and deadlines.
                quantum=float((t.context or {}).get('time_quantum',.25))
                quantum=max(.25,quantum)
                starts=[b.now,t.s0-.25,t.s0+.25,t.s0+.5]
                starts.extend(round(b.now+i*.5,8) for i in range(int((b.week_end-b.now)/.5)+1))
                starts.extend(round(b.now+i*quantum,8) for i in range(int((b.week_end-b.now)/quantum)+1))
                for start in dict.fromkeys(starts):
                    if start>=b.now and start<b.week_end and abs(start-t.s0)>hive.EPS:
                        yield allocations,base_changes+[dict(task=t.id,start=start)],'move',template
        # Give every owner combination a turn before exploring many side moves
        # for a single combination. Otherwise three-way divisions are starved.
        active=[iter(one_assignment(owners)) for owners in assignments if len(set(owners)-{source.who})<=3]
        while active:
            remaining=[]
            for iterator in active:
                try:yield next(iterator)
                except StopIteration:continue
                remaining.append(iterator)
            active=remaining
    iterators=[iter(variants(t)) for t in templates]
    found=[];seen=set();executions=set();stats=dict(attempted=0,rejected=0,duplicates=0,reasons={},templates=len(templates),unauthorized_actions_removed=removed)
    while iterators and stats['attempted']<settings.raw_limit:
        next_iterators=[]
        for it in iterators:
            if stats['attempted']>=settings.raw_limit:break
            try:allocations,changes,operator,template=next(it)
            except StopIteration:continue
            next_iterators.append(it);stats['attempted']+=1
            plan_actions=[a.model_dump(exclude_none=True) for a in template.plan_actions]
            key=canonical(allocations,changes,plan_actions)
            if key in seen:stats['duplicates']+=1;continue
            seen.add(key)
            try:
                st,affected,confirm,pm_scope=plans.preview(b,ctx,allocations,changes,plan_actions)
            except (ValueError,KeyError,TypeError) as exc:
                stats['rejected']+=1;reason=str(exc)
                stats['reasons'][reason]=stats['reasons'].get(reason,0)+1
                continue
            key=execution_key(st,allocations,plan_actions)
            if key in executions:
                stats['duplicates']+=1;continue
            executions.add(key)
            found.append(dict(id='c_'+key[:16],revision=1,plan_hash=key,operator=operator,
                title=template.title,allocations=allocations,schedule_changes=changes,plan_actions=plan_actions,required_confirmations=confirm,requires_scope_approval=pm_scope,scope='whole_task',
                basis=template.basis,affected=affected,board=view(st)))
        iterators=next_iterators
    # Reservoir by operation family, never sort by fairness.
    buckets={}
    for item in found:buckets.setdefault((item['operator'],tuple(sorted({a['who'] for a in item['allocations']})),tuple(a['kind'] for a in item.get('plan_actions',[]))),[]).append(item)
    for bucket in buckets.values():randomizer.shuffle(bucket)
    selected=[]
    while buckets and len(selected)<settings.candidate_limit:
        for key in list(buckets):
            if len(selected)>=settings.candidate_limit:break
            selected.append(buckets[key].pop())
            if not buckets[key]:del buckets[key]
    stats.update(feasible=len(found),retained=len(selected),truncated=bool(iterators or buckets),
        search_complete=not bool(iterators),search_stop='raw_limit' if iterators else 'enumerated',
        raw_limit=settings.raw_limit,retention_limit=settings.candidate_limit)
    return selected,stats
