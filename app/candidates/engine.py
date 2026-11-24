"""Persistent candidate workflow: no plan is applied before an explicit PM choice."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from types import SimpleNamespace as NS
import itertools
import json
import os
import time

from pydantic import BaseModel, Field
from sqlalchemy import select
from .models import Assessment, Consent, ConstraintReview, Designs, Opinion, Part, Speech, Transformation, TaskSelection, ReportedChange
from . import plans
from . import relax
from .generator import enumerate_plans, snapshot, view, canonical, execution_key
from .. import hive, store, runlogs, prompts
from ..llm import LiveLLM, MockLLM, get_llm
from ..models import Run, Task, Confirmation
from ..negotiation_budget import bound, consume, CallBudgetExceeded

class Settings(BaseModel):
    raw_limit: int = Field(default=2000,ge=1,le=10000)
    candidate_limit: int = Field(default=60,ge=1,le=100)
    shortlist_limit: int = Field(default=12,ge=1,le=12)
    max_rounds: int = Field(default=6,ge=1,le=15)
    max_calls: int = Field(default=240,ge=1,le=600)
    max_seconds: int = Field(default=1200,ge=1,le=3600)
    seed: int = 17
    demo_auto_consent: bool = False
    skip_discussion: bool = False   # ablation: Hive's rule order only, no proxy discussion

class ModelFailure(RuntimeError):pass
class TimeLimit(RuntimeError):pass


def model_failure(db,run,exc):
    detail=str(exc)
    try:kind=json.loads(detail).get('type')
    except (ValueError,AttributeError):kind=None
    reason='model_unavailable' if kind and kind not in ('ValidationError','JSONDecodeError') else 'model_output_invalid'
    patch(run,model_error=detail)
    fail(db,run,reason)


def patch(run,**kw):run.ctx={**run.ctx,**kw}

_MOCK={}
def adapter_for(run):
    """A scenario may pin its proxies to the offline card rules (meta llm_mode: mock); otherwise the server mode."""
    if (run.ctx.get('proxy_mode') if run is not None else None)=='mock':
        key=store.DEMO
        if key not in _MOCK:_MOCK.clear();_MOCK[key]=MockLLM()
        return _MOCK[key]
    return get_llm()


def live(run):return isinstance(adapter_for(run),LiveLLM)

def checkpoint(db,run):
    # A frozen copy makes nested JSON changes visible to SQLAlchemy.
    run.ctx=deepcopy(run.ctx)
    db.flush()


def event(db,run,actor,action,text,candidate_id=None,recipient=None,**extra):
    if extra.get('reason_en') is None:extra.pop('reason_en',None)
    entry=dict(round=run.ctx.get('round',0),phase=run.ctx.get('candidate_phase','generate'),
        requester=actor,recipient=recipient,response=action,reason=text,candidate_id=candidate_id,
        llm_budget=deepcopy(run.ctx.get('llm_budget')),**extra)
    patch(run,public_history=run.ctx.get('public_history',[])+[entry])
    store.mark(run.ctx.get('round',0),0)
    if actor=='hive':store.hive_say(db,text,run_id=run.id)
    elif actor=='pm':store.pm_say(db,text,run_id=run.id)
    else:store.say(db,actor,action,[store.F(text)],to=recipient,run_id=run.id)
    checkpoint(db,run)


def check_time(run):
    if time.time()>run.ctx['expires_at']:raise TimeLimit('max_wall_time')


def invoke(db,run,schema,group,name,facts,pid=None):
    check_time(run)
    adapter=adapter_for(run);budget=run.ctx['llm_budget']
    try:
        with prompts.frozen(run.ctx['prompt_snapshot']),bound(budget):
            if isinstance(adapter,LiveLLM):
                instruction=prompts.load_prompt(group,name)
                if group=='candidate_generation':instruction=prompts.load_prompt(group,'system')+'\n'+instruction
                if run.ctx.get('language')=='en':
                    instruction+='\n\nThe session language is English. Write every free-text field (message, reason, condition, required_decision, title, basis text) in English. Keep IDs exactly as given.'
                result=adapter._ask(schema,instruction,facts,run.ctx['private_cards'][pid].get('model') if pid else os.environ.get('PLANBEE_GENERATOR_MODEL'))
                if result is None and schema is Designs and (adapter.last_error or {}).get('type') in ('ValidationError','JSONDecodeError'):
                    error=deepcopy(adapter.last_error)
                    event(db,run,'hive','SCHEMA_REPAIR','생성 응답 형식이 잘못되어 필드별 오류를 한 번만 전달합니다. 같은 요청의 무제한 재시도는 하지 않습니다.')
                    repair=prompts.load_prompt('candidate_generation','format_repair')
                    result=adapter._ask(schema,repair,{**facts,'format_errors':error},os.environ.get('PLANBEE_GENERATOR_MODEL'))
                if result is None:raise ModelFailure(json.dumps(adapter.last_error,ensure_ascii=False))
                check_time(run)
            else:
                consume()
                if hasattr(adapter,'candidate_reply'):
                    result=schema.model_validate(adapter.candidate_reply(schema,deepcopy(facts)))
                else:result=mock_reply(db,run,schema,facts,pid)
    finally:
        # event/checkpoint may deep-copy ctx mid-call. Always restore the actual
        # bound counter, including repair attempts, on success and on failure.
        patch(run,llm_budget=deepcopy(budget))
    checkpoint(db,run)
    return result


def cards(db):
    return {p.id:store.card_json(store.card(db,p.id)) for p in store.board(db).people.values()}


def public_candidate(c):
    return {k:deepcopy(v) for k,v in c.items() if k not in ('private_assessments',)}


def participant_facts(db,run,pid,candidates):
    from ..plan_adjustments import incoming
    from ..discussion import preview
    b=store.board(db);hive.schedule(b)
    from .card_proxy import plan_cost
    me_profile=deepcopy(((getattr(b.people[pid],'notes',None) or {}).get('profile',{})))
    planned={k:v['s0'] for k,v in snapshot(b).get('tasks',{}).items()}
    items=[]
    for c in candidates:
        st,_,_,_=plans.preview(b,run.ctx,c['allocations'],c['schedule_changes'],c.get('plan_actions'))
        own=[dict(id=t.id,title=t.title,who=t.who,start=t.s,days=t.d) for t in st.tasks.values() if t.who==pid and not t.cut]
        items.append(dict(id=c['id'],name=('안 '+c['letter']) if c.get('letter') else None,plan_hash=c['plan_hash'],title=c['title'],operator=c['operator'],
            allocations=c['allocations'],schedule_changes=c['schedule_changes'],plan_actions=c.get('plan_actions',[]),affected=c['affected'],required_confirmations=c.get('required_confirmations',[]),deferred=c['board'].get('deferred',[]),omitted=c['board'].get('omitted',[]),allocations_are_deferred=any(t['id']==run.ctx['task'] for t in c['board'].get('deferred',[])),hive_verification=c['board']['gate'],
            milestones=[t for t in c['board']['tasks'] if st.tasks[t['id']].kind=='milestone'],
            my_new_work=incoming(b,st,run.ctx,c['allocations'],pid),my_schedule=own,
            fairness=c['board']['fairness'],basis=c['basis']))
        items[-1]['my_cost']=plan_cost(items[-1],pid,me_profile,planned,run.ctx.get('language')=='en')
    p=b.people[pid]
    cd=run.ctx['private_cards'][pid]
    notes=lambda x:(getattr(x,'notes',None) or {})
    return dict(self=dict(id=pid,name=p.name),my_delegation=deepcopy(cd),my_profile=deepcopy(notes(p).get('profile',{})),
        issue_reported_by=reporter_name(b,run),you_reported_the_issue=reporter_id(run)==pid,
        agent_instructions=agent_instructions(run,b,pid),issue=run.ctx['issue'],consent_mode=run.ctx.get('consent_mode','card'),language=run.ctx.get('language','ko'),
        candidates=items,public_conditions=run.ctx.get('supplement_conditions',[]),
        public_history=[dict({k:v for k,v in e.items() if k!='llm_budget'},index=i) for i,e in enumerate(run.ctx.get('public_history',[]))],
        participants=[dict(id=x.id,name=x.name,role=x.role,skills=notes(x).get('source_skills',{}),takes=notes(x).get('profile',{}).get('takes',[])) for x in b.people.values()],
        source=b.tasks[run.ctx['task']].who,original_task=dict(id=run.ctx['task'],
            title=b.tasks[run.ctx['task']].title,days=b.tasks[run.ctx['task']].d,
            context=b.tasks[run.ctx['task']].context or {}),public_board=snapshot(b))


def reporter_id(run):
    r=run.ctx.get('reporter') or ''
    return r[7:] if r.startswith('person:') else 'pm' if r in ('pm','') else r


def reporter_name(b,run):
    rid=reporter_id(run)
    return b.people[rid].name if rid in b.people else 'PM'


def near_copy(text,others,run=None):
    """True when a message repeats another participant's wording (model echo)."""
    from difflib import SequenceMatcher
    a=' '.join(str(text).split())
    # Mock replies are canned templates; short replies ("선호해요") are legitimately alike.
    if not live(run) or len(a)<25:return False
    if any(SequenceMatcher(None,a,' '.join(str(o).split())).ratio()>=.85 for o in others if o):return True
    # A reply that re-asks someone's question and adds a line is still an echo:
    # the first sentence carries the point, so compare it with every earlier sentence.
    import re
    split=lambda x:[y for y in (z.strip() for z in re.split(r'(?<=[.?!요다])\s+',' '.join(str(x).split()))) if len(y)>=20]
    mine=split(a)
    if not mine:return False
    lead=mine[0]
    return any(SequenceMatcher(None,lead,o).ratio()>=.8 for x in others if x for o in split(x))


def agent_instructions(run,b,pid):
    key=(getattr(b.people[pid],'notes',{}) or {}).get('prompt_role')
    if not key:return ''
    return run.ctx['prompt_snapshot'].get('agents/'+key+'.md','')


def review_no_options(db,run,b):
    """Ask relevant people about a failed search, never simulate an agreement."""
    source=b.tasks[run.ctx['task']];pids={source.who}
    for h in b.hands.values():
        if h.from_task==source.id:pids.add(b.tasks[h.to_task].who)
    for pid in sorted(pids,key=lambda x:x!=source.who):
        facts=dict(self=dict(id=pid,name=b.people[pid].name),my_delegation=run.ctx['private_cards'][pid],language=run.ctx.get('language','ko'),
            issue_reported_by=reporter_name(b,run),you_reported_the_issue=reporter_id(run)==pid,
            my_profile=deepcopy((getattr(b.people[pid],'notes',None) or {}).get('profile',{})),
            agent_instructions=agent_instructions(run,b,pid),issue=run.ctx['issue'],
            public_board=snapshot(b),public_history=run.ctx['public_history'],validation_feedback=run.ctx['generation'],
            participants=[dict(id=p.id,name=p.name,role=p.role) for p in b.people.values()])
        answer=invoke(db,run,ConstraintReview,'discussion','no_options',facts,pid)
        earlier=[e['reason'] for e in run.ctx['public_history'] if e['response']=='CONSTRAINT_REVIEW' and e['requester']!=pid]
        if near_copy(answer.message,earlier,run):
            answer=invoke(db,run,ConstraintReview,'discussion','no_options',dict(facts,copy_feedback='직전 답이 다른 사람의 검토와 거의 같았다. 당신의 업무와 일정 기준으로 다시 써라.'),pid)
            if near_copy(answer.message,earlier,run):
                name=b.people[pid].name
                event(db,run,'hive','COPY_SKIPPED',f'{name}의 발언은 앞 발언과 같아 뺐어요.',reason_en=f"Skipping {name}'s message: it repeats another participant.")
                continue
        if answer.recipient not in set(b.people)|{'pm',None}:raise ModelFailure('invalid_review_recipient')
        event(db,run,pid,'CONSTRAINT_REVIEW',answer.message+' '+answer.required_decision,recipient=answer.recipient)


def mock_reply(db,run,schema,facts,pid):
    """Explicit offline fixtures only. Live errors never take this branch."""
    if schema is TaskSelection:
        text=facts['issue'].split('\n\n참조:')[0].split('\n\nReferences:')[0].casefold()
        matches=[t for t in facts['tasks'] if t['title'].casefold() in text or t['id'].casefold() in text or t['id'].replace('_',' ').casefold() in text]
        if len(matches)==1:return TaskSelection(task_id=matches[0]['id'],reason='Mock: 이슈에 명시된 업무 이름을 찾았습니다.')
        if matches:
            matches.sort(key=lambda t:min([text.find(v) for v in (t['title'].casefold(),t['id'].casefold(),t['id'].replace('_',' ').casefold()) if v in text]))
            return TaskSelection(task_id=matches[0]['id'],reason='Mock: 이슈에 먼저 언급된 업무를 선택했습니다.')
        return TaskSelection(reason='Mock에서 명시된 업무 이름을 찾지 못했습니다.',clarification='어떤 업무에서 무엇이 바뀌었는지 한 문장으로 알려 주세요.')
    if schema is Designs:
        t=store.board(db).tasks[run.ctx['task']]
        script=(getattr(adapter_for(run),'script',{}) or {}).get('split',{}).get(t.id)
        templates=[]
        if script and (t.context or {}).get('splittable_hint') is not False:
            piece=script.get('piece') or {};n=piece.get('days',0)
            if 0<n<t.d:
                templates=[Transformation(title='Mock 대본의 독립 검증 분리',basis='Mock 데모에 명시된 조각 범위와 원 담당자의 보유분을 분리한다.',parts=[
                    Part(key='core',title=t.title+' 보유분',what=t.title+'의 '+str(piece.get('title','조각'))+' 이외 원 업무',effort=t.d-n),
                    Part(key='piece',title=piece['title'],what=piece.get('what') or piece['title'],effort=n)])]
        return Designs(templates=templates,reason='Mock 대본 기반 의미 설계. 없으면 전체 양도와 다른 업무 이동만 탐색.')
    if schema is ConstraintReview and facts.get('language')=='en':
        return ConstraintReview(recipient='pm',message='I checked the order of the remaining work and the public schedule. No plan in the current search meets the deadline.',required_decision='Without cutting required work or checks, ask the PM which rule may change.')
    if schema is ConstraintReview:
        return ConstraintReview(recipient='pm',message='추가 수정 후의 검증 순서와 공개 일정 제약을 확인했어요. 현재 후보 탐색에서는 기한을 지킬 수 있는 안이 없어요.',required_decision='필수 작업·검증을 줄이지 않고 PM에게 보류 검토를 요청합니다.')
    items=facts['candidates'];cd=facts['my_delegation']
    if schema is Speech and facts.get('consent_mode')=='discussion':
        from .card_proxy import speech as card_speech
        return card_speech(facts)
    if schema is Speech:
        me=facts['self']['id'];history=facts.get('public_history') or [];en=facts.get('language')=='en'
        L=lambda ko,e:e if en else ko
        last=next((e['index'] for e in reversed(history) if e.get('requester') not in ('hive','pm',me) and e.get('phase')=='fairness_discussion'),None)
        if any(e.get('requester')==me and e.get('phase')=='fairness_discussion' for e in history):
            return Speech(candidate_id=items[0]['id'],action='PASS',message=L('새로 더할 쟁점은 없어요.','Nothing new to add.'),basis=['card'],reply_to=last)
        loads=sorted((sum(x['days'] for x in c['my_new_work']),i) for i,c in enumerate(items))
        best=items[loads[0][1]];worst=items[loads[-1][1]];extra=loads[-1][0]
        if extra>0 and worst['id']!=best['id']:
            return Speech(candidate_id=worst['id'],action='REJECT',message=L(f'이 안은 제게 새 업무 {extra:g}일이 생겨요. 제 일정이 그대로인 다른 안이 낫다고 봐요.',f'This plan adds {extra:g} days of new work for me. A plan that keeps my schedule is better.'),
                basis=['card','plan:'+worst['id']],reply_to=last)
        return Speech(candidate_id=best['id'],action='PREFER',message=L('제 일정과 받는 일 범위가 그대로인 이 안을 선호해요.','I prefer this plan: my schedule and scope stay the same.') if last is None else L('앞 의견을 보고도 제 일정이 그대로인 이 안을 선호해요.','Having read the others, I still prefer this plan: my schedule stays the same.'),
            basis=['card','plan:'+best['id']],reply_to=last)
    opinions=[]
    for c in items:
        incoming=sum(x['days'] for x in c['my_new_work'])
        refused=any(x.get('tag') in cd.get('refuse_tags',[]) for x in c['my_new_work'])
        needs=incoming>cd.get('auto_days',0)+hive.EPS or bool(cd.get('note') and pid in c['affected'] and not (store.board(db).tasks[run.ctx['task']].context or {}).get('active_participants_only'))
        action='REJECT' if refused else 'NEEDS_INPUT' if needs else 'ACCEPT'
        load=sum(x['days'] for x in c['my_schedule'])
        score=max(0,100-load*8-incoming*5-(50 if refused else 0))
        opinions.append(Opinion(candidate_id=c['id'],action=action,score=score,fairness_score=max(0,100-load*8),
            card_fit_score=0 if refused else 65 if needs else 100,
            reason='제 카드에서 받지 않는 업무예요.' if refused else '이 변경은 제 확인이 필요해요.' if needs else '이 배분은 제 위임 범위 안에서 동의할 수 있어요.'))
    if schema is Consent:return Consent(action=opinions[0].action,reason=opinions[0].reason)
    return Assessment(opinions=opinions,message='후보별 제 업무와 공개된 조건을 비교했어요.')


def fail(db,run,reason):
    patch(run,termination=reason,pm_handoff=dict(message='협상 실패 → PM에게 전달됨',review_required=run.ctx['phase']=='deadline',
        summary=dict(title=run.ctx['issue'],termination=reason,llm_budget=run.ctx['llm_budget'],
            engine_support=store.meta(db,'engine_support',''),
            generation=run.ctx.get('generation'),candidate_count=len(run.ctx.get('candidates',[])),
            last_messages=run.ctx.get('public_history',[])[-12:],disposition='미합의 변경 미적용 · 마지막 검증·합의 배분 유지')))
    run.status='waiting_pm';run.step='candidate_failed'
    event(db,run,'hive','END',f'협상을 마쳤어요. {reason} · 미합의 변경은 적용하지 않고 PM에게 상황을 전달합니다.',reason_en=f'Negotiation ended ({reason}). Nothing unagreed is applied; the situation goes to the PM.')


def start(db,task_id,issue,settings=None,phase_after=None,reporter=None,language='ko'):
    b=store.board(db);hive.schedule(b)
    t=b.tasks.get(task_id)
    if task_id and (not t or t.cut or t.kind in ('done','milestone','prop') or t.d<=0):raise ValueError('실행 가능한 Task를 선택하세요')
    cfg=settings or Settings(max_calls=int(os.environ.get('PLANBEE_MAX_CANDIDATE_CALLS','240')),demo_auto_consent=store.DEMO=='m4_t4_composite' and os.environ.get('PLANBEE_DEMO_AUTO_CONSENT')=='1')
    if cfg.demo_auto_consent and store.DEMO!='m4_t4_composite':raise ValueError('개인 동의 자동 수락은 T4 데모에서만 사용할 수 있습니다.')
    snap=snapshot(b);files=prompts.snapshot()
    gate=hive.gate(b)
    run=Run(kind='candidate',step='candidate_input',status='running',auto_confirm=False,ctx=dict(
        task=t.id if t else None,who=t.who if t else None,reporter=reporter,issue=issue,records=[issue],phase='fairness' if gate['ok'] else 'deadline',
        rebalance_reason='fairness' if gate['ok'] else 'deadline',round=0,settings=cfg.model_dump(),
        phase_after=phase_after,board_snapshot=snap,snapshot_hash=sha256(json.dumps(snap,sort_keys=True,default=str).encode()).hexdigest(),
        initial_board=view(b),private_cards=cards(db),prompt_snapshot=files,
        prompt_hashes={k:sha256(v.encode()).hexdigest() for k,v in files.items()},
        expires_at=time.time()+cfg.max_seconds,llm_budget=dict(used=0,max=cfg.max_calls),
        public_history=[],candidates=[],pool_revision=1,consent_mode=store.meta(db,'consent_mode','card'),proxy_mode='mock' if store.meta(db,'llm_mode',None)=='mock' or not isinstance(get_llm(),LiveLLM) else 'live',language='en' if language=='en' else 'ko'))
    db.add(run);db.flush();runlogs.ensure_metadata(run)
    patch(run,initial_milestones=runlogs.milestones(db))
    input_turn=runlogs.start_turn(db,run,'candidate_input')
    event(db,run,'hive','ISSUE','보고를 받았어요.',reason_en='Report received.')
    # The issue owner's estimate changes the problem, never an allocation consent.
    try:
        if t is None and store.meta(db,'free_input'):
            t=apply_reported_change(db,run,b,issue,reporter)
            if t is None:
                runlogs.finish_turn(db,run,input_turn);return run
            task_id=t.id;b=store.board(db);hive.schedule(b)
        if t is None:
            eligible=[x for x in b.tasks.values() if not x.cut and x.kind not in ('done','milestone','prop') and x.d>0]
            facts=dict(issue=issue,reporter=reporter,tasks=[dict(id=x.id,title=x.title,owner=x.who,role=b.people[x.who].role,days=x.d,context=x.context or {}) for x in eligible])
            selection=invoke(db,run,TaskSelection,'input','resolve_task',facts)
            if selection.task_id is None:
                run.status='done';run.step='done'
                patch(run,termination='issue_needs_clarification',clarification=selection.clarification or '어떤 업무에 어떤 변경이 있는지 더 구체적으로 알려 주세요.')
                event(db,run,'hive','CLARIFY',run.ctx['clarification'])
                runlogs.finish_turn(db,run,input_turn);return run
            if selection.task_id not in {x.id for x in eligible}:raise ModelFailure('invalid_issue_task_reference')
            task_id=selection.task_id;t=b.tasks[task_id]
            patch(run,task=task_id,who=t.who,task_resolution=dict(task_id=task_id,reason=selection.reason))
            event(db,run,'hive','TASK_IDENTIFIED',f'이슈를 읽고 {b.people[t.who].name}의 {t.title} 업무로 연결했어요. {selection.reason}')
        adapter=adapter_for(run)
        with prompts.frozen(files),bound(run.ctx['llm_budget']):
            if not isinstance(adapter,LiveLLM):consume()
            estimate=adapter.reestimate(b.people[t.who],[issue],[t],model=run.ctx['private_cards'][t.who].get('model')) if hasattr(adapter,'reestimate') else None
            if isinstance(adapter,LiveLLM) and getattr(adapter,'last_error',None):
                raise ModelFailure(json.dumps(adapter.last_error,ensure_ascii=False))
        if run.ctx.get('reported_change'):estimate=None
        if estimate and estimate.task==task_id and abs(estimate.days-t.d)>hive.EPS:
            t.d=estimate.days;hive.schedule(b)
            updated=snapshot(b)
            patch(run,board_snapshot=updated,snapshot_hash=sha256(json.dumps(updated,sort_keys=True,default=str).encode()).hexdigest(),
                phase='fairness' if hive.gate(b)['ok'] else 'deadline',
                rebalance_reason='fairness' if hive.gate(b)['ok'] else 'deadline')
            event(db,run,t.who,'ESTIMATE',f'이슈를 읽고 이 업무를 {t.d:g}일로 다시 견적했어요.',reason_en=f'Read the issue and re-estimated this task to {t.d:g} days.')
    except TimeLimit:
        fail(db,run,'max_wall_time');runlogs.finish_turn(db,run,input_turn);return run
    except CallBudgetExceeded:
        fail(db,run,'max_llm_calls');runlogs.finish_turn(db,run,input_turn);return run
    except ModelFailure as exc:
        model_failure(db,run,exc);runlogs.finish_turn(db,run,input_turn);return run
    b=store.board(db);hive.schedule(b)
    found=impact(b,run.ctx['task'])
    patch(run,impact=found)
    event(db,run,'hive','IMPACT',impact_text(b,found),reason_en=impact_text_en(b,found))
    run.step='candidate_generate'
    runlogs.finish_turn(db,run,input_turn)
    return advance(db,run)


def impact(b,task_id):
    """T1: which handoffs the change breaks, who is involved, who could help, who is not.
    Deterministic: the scheduled board versus each handoff promise."""
    source=b.tasks[task_id];ctx=source.context or {}
    reach=[task_id];seen={task_id}
    for x in reach:
        for h in sorted(b.hands.values(),key=lambda h:h.oi):
            if h.from_task==x and h.to_task not in seen:seen.add(h.to_task);reach.append(h.to_task)
    chain=[dict(id=h.id,source=h.from_task,target=h.to_task,due=h.t,expected=hive.pred(b,h),state=hive.h_state(b,h))
           for h in sorted(b.hands.values(),key=lambda h:h.oi) if h.from_task in seen and not h.done]
    broken=[c for c in chain if c['state']=='risk']
    owner=source.who
    real=lambda tid:b.tasks[tid].kind!='milestone'
    involved=sorted({b.tasks[c['target']].who for c in broken if real(c['target'])}-{owner})
    helpers=set()
    for part in ctx.get('required_parts',[]):helpers.update(part.get('assignees',[]))
    for tid in ctx.get('allowed_change_tasks',[]):
        if tid in b.tasks:helpers.add(b.tasks[tid].who)
    helpers=sorted(helpers-{owner}-set(involved))
    task_issues=[dict(task=v['task'],code=v['code'],text=v['text']) for v in hive.gate(b)['violations'] if v.get('task')]
    return dict(task=task_id,owner=owner,chain=chain,broken=[c['id'] for c in broken],involved=involved,
                may_help=helpers,not_involved=sorted(set(b.people)-{owner}-set(involved)-set(helpers)),task_issues=task_issues)


DAY_EN=['Mon','Tue','Wed','Thu','Fri']
def when_en(t):
    import math
    k=math.floor(t+hive.EPS)
    if abs(t-round(t))>hive.EPS:return ('wk2 ' if k>=5 else '')+DAY_EN[k%5]+' AM'
    return ('wk2 ' if k-1>=5 else '')+DAY_EN[(k-1)%5]+' eve'


def en_title(x):
    return store.display_glossary().get(x,x)


def impact_text_en(b,found):
    name=lambda pid:b.people[pid].name
    title=en_title(b.tasks[found['task']].title)
    if not found['broken']:return f"No handoff breaks because of {title}. Nobody else needs to be contacted."
    links=', '.join(f"{b.hands[h].title} ({when_en(b.hands[h].t)} → {when_en(hive.pred(b,b.hands[h]))})" for h in found['broken'])
    parts=[f"{title} breaks these handoffs: {links}"]
    if found['involved']:parts.append('Affected: '+', '.join(map(name,found['involved'])))
    if found['may_help']:parts.append('Could take work or move tasks: '+', '.join(map(name,found['may_help'])))
    if found['not_involved']:parts.append('Not called: '+', '.join(map(name,found['not_involved'])))
    return ' · '.join(parts)


def impact_text(b,found):
    name=lambda pid:b.people[pid].name
    if not found['broken']:
        return f"{b.tasks[found['task']].title} 변경으로 깨지는 인계는 없어요. 다른 사람에게 연락하지 않아도 돼요."
    links=', '.join(f"{b.hands[h].title} ({hive.when(b.hands[h].t)} → {hive.when(hive.pred(b,b.hands[h]))})" for h in found['broken'])
    parts=[f"{b.tasks[found['task']].title} 변경으로 깨지는 인계: {links}"]
    if found['involved']:parts.append('영향: '+', '.join(map(name,found['involved'])))
    if found['may_help']:parts.append('대신 맡거나 일정을 바꿀 수 있는 사람: '+', '.join(map(name,found['may_help'])))
    if found['not_involved']:parts.append('부르지 않음: '+', '.join(map(name,found['not_involved'])))
    return ' · '.join(parts)


def discussion_mode(run):
    """No card-based scoring or personal confirmation: the PM decides from the public discussion."""
    return run.ctx.get('consent_mode')=='discussion'


def family(c,owner):
    return (tuple(sorted({a['who'] for a in c['allocations']}-{owner})),
            tuple(sorted({ch.get('task') for ch in c.get('schedule_changes',[]) if ch.get('task')})),
            tuple(sorted(a['kind']+':'+a['task'] for a in c.get('plan_actions',[]))))


def plan_metrics(c,source_id,owner):
    """Rule-based disruption measures, fixed before any run (no human raters, no LLM)."""
    reassigned=sum(1 for a in c['allocations'] if a['who']!=owner)+sum(1 for ch in c.get('schedule_changes',[]) if ch.get('who'))
    moved=len({ch['task'] for ch in c.get('schedule_changes',[]) if ch.get('task') and ch['task']!=source_id})
    totals=(c['board'].get('fairness') or {}).get('totals',{})
    return dict(reassigned=reassigned,other_tasks_moved=moved,deferred=len(c['board'].get('deferred',[])),
                people_changed=len(c.get('affected',[])),max_load=round(max(totals.values(),default=0),4))


def objective_key(c):
    m=c['metrics'];return (m['reassigned'],m['other_tasks_moved'],m['deferred'],m['people_changed'],m['max_load'],c['id'])


def shortlist_objective(db,run):
    """Discussion mode: Hive orders plans by the fixed rule, one per family first."""
    allc=deepcopy(run.ctx['candidates']);source=store.board(db).tasks[run.ctx['task']]
    for c in allc:c['metrics']=plan_metrics(c,source.id,source.who)
    # A plan with the same work split and plan operators as another valid plan, plus extra
    # moves, changes more for nothing: it stays in the pool but not in the discussion.
    def split(c):return json.dumps(sorted((a['who'],a['what']) for a in c['allocations']))
    def extras(c):return {json.dumps(ch,sort_keys=True) for ch in c.get('schedule_changes',[])}|{json.dumps(x,sort_keys=True) for x in c.get('plan_actions',[])}
    for c in allc:
        lighter=[o for o in allc if o is not c and split(o)==split(c) and extras(o)<extras(c)]
        c['metrics']['dominated_by']=min(lighter,key=objective_key)['id'] if lighter else None
    ranked=sorted([c for c in allc if not c['metrics']['dominated_by']],key=objective_key)+sorted([c for c in allc if c['metrics']['dominated_by']],key=objective_key)
    limit=min(run.ctx['settings']['shortlist_limit'],len(ranked))
    if discussion_mode(run):limit=min(limit,3)   # every plan discussed reaches the PM, so letters stay A, B, C
    picked=[];seen=set()
    for c in ranked:
        f=family(c,source.who)
        if f not in seen and len(picked)<limit and not c['metrics']['dominated_by']:picked.append(c);seen.add(f)
    for c in ranked:
        if len(picked)>=limit:break
        if c not in picked and not c['metrics']['dominated_by']:picked.append(c)
    picked.sort(key=objective_key)
    for i,c in enumerate(ranked):c['metrics']['objective_rank']=i+1
    for c in allc:c.pop('letter',None)
    for i,c in enumerate(picked):c['letter']=chr(65+i)
    patch(run,candidates=allc,shortlist=[c['id'] for c in picked])
    dropped=sum(1 for c in allc if c['metrics']['dominated_by'])
    event(db,run,'hive','SHORTLIST',f'바뀌는 일이 적은 순으로 {len(picked)}개를 토론에 올려요.'+(f' 같은 배분에 불필요한 이동만 더한 {dropped}개는 뺐어요.' if dropped else ''),
        reason_en=f'{len(picked)} plans that change the least go to discussion.'+(f' {dropped} plans that only add needless moves to the same split were left out.' if dropped else ''))
    pids=run.ctx.get('participants') or sorted(store.board(db).people)
    run.step='candidate_rank' if len(pids)==1 or run.ctx.get('round',0)>=run.ctx['settings']['max_rounds'] or run.ctx['settings'].get('skip_discussion') else 'candidate_discuss'


def recommend_discussion(db,run):
    """Discussion mode: rank by the public discussion on top of the rule order. No consent gate."""
    allc=deepcopy(run.ctx['candidates']);source=store.board(db).tasks[run.ctx['task']]
    order={cid:i for i,cid in enumerate(run.ctx.get('shortlist',[]))}
    short=[c for c in allc if c['id'] in order] or allc
    said=[e for e in run.ctx.get('public_history',[]) if e.get('phase')=='fairness_discussion' and e.get('candidate_id') and e.get('requester') not in ('hive','pm')]
    names=store.board(db).people
    for c in short:
        mine=[e for e in said if e['candidate_id']==c['id']]
        tally={k:sum(1 for e in mine if e['response']==k) for k in ('PREFER','REJECT','CONDITION','QUESTION','ANSWER')}
        objections=sorted({e['requester'] for e in mine if e['response']=='REJECT' and e['requester'] in c['affected']})
        score=-order.get(c['id'],len(order))+2*tally['PREFER']-3*tally['REJECT']-tally['CONDITION']
        c['discussion_tally']=dict({k.lower():v for k,v in tally.items()},objections=objections,score=score,
            rule_rank=order.get(c['id'],len(order))+1,by=[dict(who=e['requester'],action=e['response']) for e in mine])
    short.sort(key=lambda c:(bool(c['discussion_tally']['objections']),-c['discussion_tally']['score'],c['id']))
    # One plan per set of people who receive moved work first, so the PM sees real alternatives
    # (an objected alternative stays visible with its objection), then fill by the tally.
    picked=[];seen=set()
    for c in short:
        f=family(c,source.who)[0]
        if f not in seen and len(picked)<3:picked.append(c);seen.add(f)
    for c in short:
        if len(picked)>=3:break
        if c not in picked:picked.append(c)
    picked.sort(key=lambda c:(c.get('letter') or 'Z',c['id']))
    for c in picked:
        c['consents']={pid:dict(action='ACCEPT',reason='토론 모드: 카드 기반 동의·본인 확인 단계를 쓰지 않음. PM이 공개 토론을 보고 결정.',source='discussion_mode') for pid in c['affected']}
    byid={c['id']:c for c in picked}
    allc=[byid.get(c['id'],c) for c in allc]
    patch(run,final_candidates=[c['id'] for c in picked],candidates=allc,termination=None)
    run.status='awaiting_pm_selection';run.step='candidate_pm'
    def line(i,c):
        t=c['discussion_tally']
        bits=[f"선호 {t['prefer']}",f"반대 {t['reject']}"+(f"({', '.join(names[p].name for p in t['objections'])})" if t['objections'] else ''),f"조건 {t['condition']}",f"질문 {t['question']}"]
        return f"안 {c.get('letter') or i+1}: "+' · '.join(bits)
    def line_en(i,c):
        t=c['discussion_tally']
        return f"Plan {c.get('letter') or i+1}: prefer {t['prefer']} · object {t['reject']}"+(f" ({', '.join(names[p].name for p in t['objections'])})" if t['objections'] else '')+f" · conditions {t['condition']} · questions {t['question']}"
    event(db,run,'hive','DISCUSSION_TALLY','토론 집계 — '+' / '.join(line(i,c) for i,c in enumerate(picked)),
        reason_en='Discussion tally — '+' / '.join(line_en(i,c) for i,c in enumerate(picked)))
    event(db,run,'hive','PM_OPTIONS',f'계획 {len(picked)}개 중에서 골라 주세요.',reason_en=f'Choose one of {len(picked)} plans.')


def rule_options(db,run,b):
    cfg=Settings(**run.ctx['settings'])
    granted={g['id'] for g in run.ctx.get('granted_rules',[])}
    small=Settings(raw_limit=min(cfg.raw_limit,600),candidate_limit=60,seed=cfg.seed)
    opts=[o for o in relax.options(b,run.ctx,small) if o['id'] not in granted]
    name=lambda pid:'PM' if pid=='pm' else b.people[pid].name if pid in b.people else pid
    text='규칙 안에서는 마감을 지키는 계획이 없어요. 풀 수 있는 규칙마다 다시 계산했어요 — '+' / '.join(
        f"{o['id']} {o['label']}: 계획 {o['feasible']}개 ({name(o['authorizer'])} 결정)" for o in opts)
    patch(run,relaxation_options=opts,termination='needs_rule_relaxation',
        pm_handoff=dict(message='규칙 안 계획 없음 → PM이 풀 규칙을 고르면 다시 계획합니다',review_required=True,relaxation_options=opts,
            summary=dict(title=run.ctx['issue'],termination='needs_rule_relaxation',generation=run.ctx.get('generation'),
                disposition='보드 변경 없음 · PM이 규칙을 허락하면 그 규칙으로 다시 계획')))
    run.status='waiting_pm';run.step='candidate_failed'
    g=store.display_glossary()
    text_en='No plan meets the deadline inside the rules. Hive recomputed each rule that could be relaxed — '+' / '.join(
        f"{o['id']} {g.get(o['label'],o['label'])}: {o['feasible']} plans ({'PM' if o['authorizer']=='pm' else name(o['authorizer'])} decides)" for o in opts)
    event(db,run,'hive','RULE_OPTIONS',text,reason_en=text_en)
    rule_discussion(db,run,b,opts)
    patch(run,pm_handoff={**run.ctx['pm_handoff'],'relaxation_options':run.ctx['relaxation_options']})


def rule_discussion(db,run,b,opts):
    """Before the PM picks a rule, the people the change touches say which relaxation costs them what."""
    feasible=[o for o in opts if o['feasible']>0]
    if len(feasible)<2 or run.ctx.get('granted_rules') or run.ctx['settings'].get('skip_discussion'):return
    imp=run.ctx.get('impact') or {}
    pids=[p for p in [imp.get('owner')]+list(imp.get('involved',[])) if p in b.people]
    specs={r['id']:r for r in (b.tasks[run.ctx['task']].context or {}).get('relaxations',[])}
    patch(run,candidate_phase='rule_discussion')
    for rnd in (1,2):
        patch(run,round=rnd);spoke=0
        for pid in pids:
            p=b.people[pid]
            facts=dict(self=dict(id=pid,name=p.name),my_delegation=deepcopy(run.ctx['private_cards'][pid]),
                my_profile=deepcopy((getattr(p,'notes',None) or {}).get('profile',{})),agent_instructions=agent_instructions(run,b,pid),
                issue=run.ctx['issue'],issue_reported_by=reporter_name(b,run),you_reported_the_issue=reporter_id(run)==pid,
                language=run.ctx.get('language','ko'),consent_mode=run.ctx.get('consent_mode','card'),
                rules=[dict(o,patch=specs.get(o['id'],{}).get('patch',{})) for o in opts],
                my_tasks=[t.id for t in b.tasks.values() if t.who==pid],
                handoff_targets={h.id:h.to_task for h in b.hands.values()},
                public_history=[dict({k:v for k,v in e.items() if k!='llm_budget'},index=i) for i,e in enumerate(run.ctx.get('public_history',[]))],
                participants=[dict(id=x.id,name=x.name,role=x.role) for x in b.people.values()],public_board=snapshot(b))
            from .card_proxy import rule_cost
            for r in facts['rules']:
                sc,why=rule_cost(facts,r);r['my_cost']=dict(score=sc,reasons=', '.join(why) or ('no change for me' if facts['language']=='en' else '나에게 바뀌는 것 없음'))
            if any(e.get('phase')=='rule_discussion' and e.get('requester')==pid for e in run.ctx['public_history']) and not any(
                    e.get('phase')=='rule_discussion' and e.get('recipient')==pid and e['response']=='QUESTION' for e in run.ctx['public_history']):
                continue   # one position per person; later rounds only answer questions put to them
            if live(run):answer=invoke(db,run,Speech,'discussion','rule_speak',facts,pid)
            else:
                consume_mock(run)
                from .card_proxy import rule_speech
                answer=rule_speech(facts)
            normalize_recipient(db,answer)
            if answer.candidate_id not in {o['id'] for o in opts}:answer.candidate_id=feasible[0]['id']
            if answer.action=='PASS':continue
            others=[e['reason'] for e in run.ctx['public_history'] if e.get('phase')=='rule_discussion' and e['requester'] not in ('hive','pm',pid)]
            if near_copy(answer.message,others,run):
                event(db,run,'hive','COPY_SKIPPED',f'{p.name}의 발언은 앞 발언과 같아 뺐어요.',reason_en=f"Skipping {p.name}'s message: it repeats another participant.")
                continue
            spoke+=1
            event(db,run,pid,answer.action,answer.message,answer.candidate_id,answer.recipient,basis=[x for x in answer.basis if x=='card' or x.split(':')[0] in ('task','handoff')][:4],
                  reply_to=answer.reply_to if isinstance(answer.reply_to,int) and 0<=answer.reply_to<len(run.ctx['public_history']) else None)
        if not spoke:break
    for o in opts:
        mine=[e for e in run.ctx['public_history'] if e.get('phase')=='rule_discussion' and e.get('candidate_id')==o['id']]
        o['tally']=dict(prefer=sum(e['response']=='PREFER' for e in mine),reject=sum(e['response']=='REJECT' for e in mine),
            by=[dict(who=e['requester'],action=e['response']) for e in mine])
    patch(run,relaxation_options=opts,candidate_phase='generate',round=0)


def consume_mock(run):
    from ..negotiation_budget import bound
    with bound(run.ctx['llm_budget']):consume()
    patch(run,llm_budget=deepcopy(run.ctx['llm_budget']))


def grant_rule(db,run,rule_id,reason=''):
    """PM grants one listed relaxation: write its patch to the board and plan again."""
    if run.status!='waiting_pm' or run.ctx.get('termination')!='needs_rule_relaxation':raise ValueError('규칙 허락을 기다리는 상태가 아님')
    option=next((o for o in run.ctx.get('relaxation_options',[]) if o['id']==rule_id),None)
    if not option:raise ValueError('없는 규칙 선택지')
    b=store.board(db);hive.schedule(b)
    spec=next((r for r in (b.tasks[run.ctx['task']].context or {}).get('relaxations',[]) if r['id']==rule_id),None)
    if not spec:raise ValueError('Task 계약에 없는 규칙')
    relax.persist(db,b,spec.get('patch') or {})
    b=store.board(db);hive.schedule(b);db.flush()
    snap=snapshot(b)
    granted=run.ctx.get('granted_rules',[])+[dict(id=rule_id,label=option['label'],rule=option.get('rule',''),authorizer=option['authorizer'],reason=reason)]
    patch(run,granted_rules=granted,board_snapshot=snap,snapshot_hash=sha256(json.dumps(snap,sort_keys=True,default=str).encode()).hexdigest(),
        private_cards=cards(db),candidates=[],shortlist=[],final_candidates=[],supplement_conditions=[],supplemented=False,
        pool_revision=run.ctx['pool_revision']+1,termination=None,pm_handoff=None,round=0,stable_discussion_rounds=0,
        initial_cursor=0,final_cursor=0,initial_assessments={},final_assessments={},active_seconds=0,
        phase='fairness' if hive.gate(b)['ok'] else 'deadline')
    run.status='running';run.step='candidate_generate'
    who='' if option['authorizer']=='pm' else f" ({b.people[option['authorizer']].name}의 결정으로 기록)" if option['authorizer'] in b.people else ''
    who_en='' if option['authorizer']=='pm' else f" (recorded as {b.people[option['authorizer']].name}'s decision)" if option['authorizer'] in b.people else ''
    event(db,run,'pm','RULE_GRANTED',(f"{option['label']} — 이 규칙을 허락합니다{who}. "+(reason or '')).strip(),
        reason_en=(f"{store.display_glossary().get(option['label'],option['label'])} — I allow this rule{who_en}. "+(reason or '')).strip())
    checkpoint(db,run)
    return run


def span_label(a,z):
    """'수 오후 ~ 목 오전': the half-days a span covers, start and last, in words."""
    return slot_label(a)+' ~ '+slot_label(max(a,z-0.5))


def week_grid(b,eligible):
    """Who is on what in each half-day from now to the deadline, so the model reads instead of computing."""
    out={}
    x=b.now
    while x<b.week_end-hive.EPS:
        out[slot_label(x)]={b.people[p].name:next((t.id for t in eligible if t.who==p and t.s<=x+hive.EPS and t.s+t.d>x+hive.EPS),'비어 있음') for p in b.people}
        x+=0.5
    return out


def slot_label(x):
    import math
    d=math.floor(x+hive.EPS);part=x-d
    return ('다음 주 ' if d>=5 else '')+hive.DAY[d%5]+(' 오전' if part<0.25 else ' 정오' if part<0.5 else ' 오후' if part<0.75 else ' 저녁')


def quoted(b,issue):
    """Board items the PM quoted into the message (the composer appends '[id]' for each)."""
    import re
    out=[]
    for x in re.findall(r'\[([A-Za-z0-9_\-]+)\]',str(issue)):
        if x in b.tasks:out.append(dict(type='task',id=x,title=b.tasks[x].title,owner=b.tasks[x].who))
        elif x in b.people:out.append(dict(type='person',id=x,name=b.people[x].name))
        elif x in b.hands:out.append(dict(type='handoff',id=x,from_task=b.hands[x].from_task,to_task=b.hands[x].to_task))
    return out


def apply_reported_change(db,run,b,issue,reporter):
    """Free-input scenario: the model turns the report into one board change, which code checks and applies."""
    if not live(run):
        run.status='done';run.step='done'
        patch(run,termination='issue_needs_clarification',clarification='자유 입력 시나리오는 Live LLM으로 서버를 켰을 때만 동작해요. (python3.13 start.py --llm live)')
        event(db,run,'hive','CLARIFY',run.ctx['clarification'],reason_en='The free-input scenario needs the live model (start the server with --llm live).')
        return None
    eligible=[x for x in b.tasks.values() if not x.cut and x.kind not in ('done','milestone','prop') and x.d>0]
    facts=dict(issue=issue,reporter=reporter,now=b.now,week_end=b.week_end,
        time_axis='0=월 09:00, 0.5=월 13:00, 1=화 09:00 … 4.5=금 13:00, 5=금 18:00. 오전 [d,d+0.5), 오후 [d+0.5,d+1)',
        people=[dict(id=p.id,name=p.name,role=p.role) for p in b.people.values()],
        tasks=[dict(id=x.id,title=x.title,owner=x.who,start=x.s,end=x.s+x.d,when=span_label(x.s,x.s+x.d),days=x.d,priority=(x.context or {}).get('priority')) for x in eligible],
        handoffs=[dict(id=h.id,from_task=h.from_task,to_task=h.to_task,title=h.title,promised=h.t) for h in b.hands.values() if not h.done],
        unavailable={pid:(store.card(db,pid).policy or {}).get('unavailable',[]) for pid in b.people},
        references=quoted(b,issue),week=week_grid(b,eligible))
    facts['free']={k:[n for n,v in row.items() if v=='비어 있음'] for k,row in facts['week'].items()}
    change=invoke(db,run,ReportedChange,'input','apply_change',facts)
    if change.kind!='change':
        run.status='done';run.step='done'
        text=(change.answer or '').strip() if change.kind=='question' else ''
        text=text or '이 창에는 이번 주 일정에 생긴 변경을 적어 주세요. 보드에 대한 질문에도 답할 수 있어요.'
        patch(run,termination='not_a_change',clarification=text,input_kind=change.kind)
        event(db,run,'hive','ANSWER' if change.kind=='question' else 'CLARIFY',text)
        event(db,run,'hive','HINT','일정이 바뀌었다면 누가, 언제, 무엇을 못 하게 됐는지 적어 주세요. 그때 계획을 다시 짭니다.',
              reason_en='If the schedule changed, say who can’t do what, and when. Hive will replan from that.')
        return None
    ids={x.id for x in eligible}
    if (not change.task_id or change.task_id not in ids) and change.person in b.people and change.unavailable_slots:
        # "Zoe is off on Friday": the cause is whatever Zoe has in that time; code finds it.
        days='월화수목금'
        span=[(days.index(x.day)+(0.5 if x.part=='오후' else 0),days.index(x.day)+(0.5 if x.part=='오전' else 1)) for x in change.unavailable_slots]
        mine=sorted((x for x in eligible if x.who==change.person and any(x.s<z-hive.EPS and x.s+x.d>max(a,b.now)+hive.EPS for a,z in span)),key=lambda x:x.s)
        if mine:change.task_id=mine[0].id
    if not change.task_id or change.task_id not in ids:
        run.status='done';run.step='done'
        patch(run,termination='issue_needs_clarification',clarification=change.clarification or '어떤 업무가 언제 어떻게 바뀌었는지 한 문장으로 알려 주세요.')
        event(db,run,'hive','CLARIFY',run.ctx['clarification'])
        return None
    t=b.tasks[change.task_id];applied=[];windows=[]
    # A quoted handoff is late because of the work before it, not the work that waits for it.
    for ref in facts['references']:
        if ref['type']=='handoff' and t.id==ref['to_task'] and ref['from_task'] in ids:t=b.tasks[ref['from_task']]
    if change.extra_days:change.unavailable_slots=[];change.available_again=None   # longer work is not an absence
    if change.person in b.people and change.unavailable_slots:
        days='월화수목금'
        spans=sorted({(days.index(x.day)+(0.5 if x.part=='오후' else 0),days.index(x.day)+(0.5 if x.part=='오전' else 1)) for x in change.unavailable_slots})
        if change.available_again:   # "free again from Thu PM": absent until then
            back=days.index(change.available_again.day)+(0.5 if change.available_again.part=='오후' else 0)
            if back>spans[0][0]+hive.EPS:spans=sorted(set(spans)|{(spans[0][0],back)})
        for a,z in spans:   # merge touching half-days, drop the past
            a,z=max(b.now,a),min(b.week_end,z)
            if z<=a:continue
            if windows and a<=windows[-1]['end']+hive.EPS:windows[-1]['end']=max(windows[-1]['end'],z)
            else:windows.append(dict(start=a,end=z,reason='보고된 부재'))
        # The cause is the person's own work in that time, whatever task the model named.
        hit=[x for x in eligible if x.who==change.person and any(x.s<w['end']-hive.EPS and x.s+x.d>w['start']+hive.EPS for w in windows)]
        if hit and t not in hit and t.who==change.person:t=hit[0]
        if windows:
            card=store.card(db,change.person)
            card.policy={**(card.policy or {}),'approved':True,'unavailable':list((card.policy or {}).get('unavailable',[]))+windows}
            applied.append(b.people[change.person].name+' '+', '.join(slot_label(w['start'])+'–'+slot_label(w['end']) for w in windows)+' 부재')
    new_days=None
    if change.extra_days:
        # An amount stated in words wins over the model's number (templates write exactly one of these).
        said=[v for k,v in (('반나절',0.5),('하루',1.0),('이틀',2.0),('half a day',0.5),('a day',1.0),('two days',2.0)) if k in str(issue)]
        if len(said)==1:change.extra_days=said[0]*(1 if change.extra_days>0 else -1)
        new_days=max(0.5,round((t.d+float(change.extra_days))*2)/2)
        if abs(new_days-t.d)>hive.EPS:t.d=new_days;applied.append(f'{t.title} {t.d:g}일')
    if not applied:
        run.status='done';run.step='done'
        patch(run,termination='issue_needs_clarification',clarification=change.clarification or '보드에서 무엇이 바뀌는지(누가 언제 일할 수 없는지, 또는 작업량) 알려 주세요.')
        event(db,run,'hive','CLARIFY',run.ctx['clarification'])
        return None
    db.flush();b=store.board(db);hive.schedule(b);snap=snapshot(b)
    patch(run,task=t.id,who=t.who,reported_change=dict(change.model_dump(),applied=dict(task=t.id,windows=windows,new_days=new_days)),private_cards=cards(db),board_snapshot=snap,
        snapshot_hash=sha256(json.dumps(snap,sort_keys=True,default=str).encode()).hexdigest(),
        phase='fairness' if hive.gate(b)['ok'] else 'deadline',initial_board=view(b))
    event(db,run,'hive','CHANGE_APPLIED',f'보고를 보드에 반영했어요: {change.summary or "; ".join(applied)}',
          reason_en=f'Applied the report to the board: {change.summary or "; ".join(applied)}')
    return b.tasks[t.id]


def generate(db,run):
    b=store.board(db);hive.schedule(b);t=b.tasks[run.ctx['task']]
    facts=dict(issue=run.ctx['issue'],original_task=dict(id=t.id,title=t.title,days=t.d,context=t.context or {}),
        board=snapshot(b),public_conditions=run.ctx.get('supplement_conditions',[]))
    result=invoke(db,run,Designs,'candidate_generation','transform',facts)
    if result.dropped:
        patch(run,dropped_templates=result.dropped)
        event(db,run,'hive','TEMPLATE_DROPPED',f'형식이 맞지 않는 계획 구조 {len(result.dropped)}개는 제외하고, 나머지 {len(result.templates)}개와 Task에 명시된 기본 구조로 후보를 만듭니다.')
    cfg=Settings(**run.ctx['settings'])
    candidates,stats=enumerate_plans(b,run.ctx,result.templates,cfg)
    # One bounded structural repair, with concrete feasibility evidence.
    if not candidates and live(run):
        event(db,run,'hive','REPAIR_REQUEST','현재 구조로 통과한 계획이 없어요. 제약 위반을 근거로 한 번만 구조를 다시 요청합니다.',reason_en='No plan passed with the current structures. Hive asks once more, citing the violations.')
        result=invoke(db,run,Designs,'candidate_generation','repair',{**facts,'validation_feedback':stats})
        candidates,stats=enumerate_plans(b,run.ctx,result.templates,cfg)
    if hive.gate(b)['ok'] and not (t.context or {}).get('single_actor'):
        allocations=[dict(who=t.who,title=t.title,what=(t.context or {}).get('deliverable') or t.title,effort=t.d,days=t.d,key='whole',depends_on=[])]
        key=execution_key(b,allocations,[])
        baseline=dict(id='c_'+key[:16],revision=1,plan_hash=key,operator='baseline',title='현재 milestone 계획 유지',
            allocations=allocations,schedule_changes=[],scope='whole_task',basis='현재 보드는 모든 하드 제약을 충족한다.',affected=[t.who],board=view(b))
        candidates=[baseline]+[c for c in candidates if c['id']!=baseline['id']]
        candidates=candidates[:cfg.candidate_limit]
    prior=run.ctx.get('candidates',[]) if run.ctx.get('supplement_conditions') else []
    known={c['id'] for c in prior}
    candidates=prior+[c for c in candidates if c['id'] not in known]
    for c in candidates:c['snapshot_hash']=run.ctx['snapshot_hash']
    patch(run,candidates=candidates,generation=stats,generation_reason=result.reason,
        initial_cursor=0,final_cursor=0,initial_assessments={},final_assessments={},
        pool_hash=sha256(json.dumps([c['plan_hash'] for c in candidates]).encode()).hexdigest())
    if not candidates:
        if (t.context or {}).get('review_no_options'):review_no_options(db,run,b)
        if (t.context or {}).get('relaxations'):return rule_options(db,run,b)
        return fail(db,run,'search_budget_exhausted' if stats.get('search_stop')=='raw_limit' else 'search_exhausted')
    if (t.context or {}).get('active_participants_only'):
        invited=set((t.context or {}).get('discussion_participants',[])) & set(b.people)
        patch(run,participants=sorted({pid for c in candidates for pid in c['affected']}|invited))
    event(db,run,'hive','CANDIDATES',f"마감을 지키는 계획 {len(candidates)}개를 찾았어요."+('' if discussion_mode(run) else ' 이제 각자 카드로 비교합니다.'),
        reason_en=f"{len(candidates)} new plans passed the schedule check. "+('They are ordered by the fixed rule and discussed with the people involved.' if discussion_mode(run) else 'Each member now compares them by card.'))
    run.step='candidate_assess'


def demo_auto_consent(run):
    # This is explicitly a T4 demonstration, not a record of card-based agreement.
    enabled=run.ctx['settings'].get('demo_auto_consent',os.environ.get('PLANBEE_DEMO_AUTO_CONSENT')=='1')
    return bool(enabled) and store.DEMO=='m4_t4_composite'


def force_demo_agree(run):
    return store.DEMO=='m4_t6_game_demo' and os.environ.get('PLANBEE_T6_FORCE_AGREE','1')=='1'


def recommend_demo(db,run):
    import random
    allc=deepcopy(run.ctx['candidates'])
    chosen=[c for c in allc if c['id'] in run.ctx.get('shortlist',[])]
    random.Random(run.ctx['settings']['seed']).shuffle(chosen)
    if force_demo_agree(run):
        chosen=chosen or allc
        source=store.board(db).tasks[run.ctx['task']].who
        first=[];rest=[];seen=set()
        for candidate in chosen:
            family=tuple(sorted({a['who'] for a in candidate['allocations']}-{source}))
            (rest if family in seen else first).append(candidate);seen.add(family)
        chosen=first+rest
    demo='T6' if force_demo_agree(run) else 'T4'
    recommended=[]
    for c in chosen[:3]:
        c['consents']={pid:dict(action='ACCEPT',reason=demo+' 데모용 무조건 동의. 카드 기반 실제 개인 합의가 아닙니다.',auto_confirmed=True,source='demo_algorithm') for pid in c['affected']}
        for pid in c['affected']:event(db,run,pid,'AUTO_CONFIRM',c['consents'][pid]['reason'],c['id'])
        recommended.append(c['id'])
    if not recommended:return fail(db,run,'no_consented_candidate')
    patch(run,final_candidates=recommended,candidates=allc,termination=None,demo_auto_consent=True)
    run.status='awaiting_pm_selection';run.step='candidate_pm'
    event(db,run,'hive','DEMO_AUTO_CONSENT',demo+' 데모에서는 검증 후보 중 알고리즘이 최대 3개를 추리고 개인 동의를 무조건 수락합니다. 카드 기반 합의 결과가 아니며 PM 최종 선택과 Hive 검증은 유지합니다.')
    event(db,run,'hive','PM_OPTIONS',f'후보 {len(recommended)}개를 추렸어요. PM이 최종 결정해 주세요. 후보가 하나여도 자동 적용하지 않습니다.')


def assess(db,run,final=False):
    if discussion_mode(run):return recommend_discussion(db,run) if final else shortlist_objective(db,run)
    if final and (demo_auto_consent(run) or force_demo_agree(run)):return recommend_demo(db,run)
    b=store.board(db);pids=run.ctx.get('participants') or sorted(b.people)
    allc=run.ctx['candidates'];chosen=[c for c in allc if c['id'] in run.ctx.get('shortlist',[])] if final else allc
    cursor_key='final_cursor' if final else 'initial_cursor'
    result_key='final_assessments' if final else 'initial_assessments'
    cursor=run.ctx.get(cursor_key,0)
    opinions=deepcopy(run.ctx.get(result_key,{})) if cursor else {}
    if final and not cursor:patch(run,evaluation_history=deepcopy(run.ctx['public_history']))
    # Persist each participant's turn separately. A slow Live team must not keep
    # a single request open while every participant evaluates the entire pool.
    for pid in pids[cursor:cursor+1]:
        mine=[]
        for offset in range(0,len(chosen),8):
            batch=chosen[offset:offset+8];facts=participant_facts(db,run,pid,batch)
            if force_demo_agree(run):
                result=Assessment(opinions=[Opinion(candidate_id=c['id'],action='ACCEPT',score=50,fairness_score=50,card_fit_score=50,reason='T6 시연 모드: 일정 검증 후보에 무조건 동의합니다.') for c in batch],message='시연용 무조건 동의')
            else:result=invoke(db,run,Assessment,'discussion','rank' if final else 'assess',facts,pid)
            expected={c['id'] for c in batch};actual=[o.candidate_id for o in result.opinions]
            if len(actual)!=len(expected) or set(actual)!=expected:
                feedback=dict(expected_ids=sorted(expected),received_ids=actual,
                    missing_ids=sorted(expected-set(actual)),unexpected_ids=sorted(set(actual)-expected))
                event(db,run,'hive','ASSESSMENT_REPAIR','평가에 잘못된 후보 참조가 있어 정확한 후보 목록으로 한 번만 다시 요청합니다.')
                result=invoke(db,run,Assessment,'discussion','assessment_repair',dict(facts,assessment_feedback=feedback),pid)
                actual=[o.candidate_id for o in result.opinions]
                if len(actual)!=len(expected) or set(actual)!=expected:raise ModelFailure('candidate_assessment_ids_invalid')
            mine.extend(o.model_dump() for o in result.opinions)
        opinions[pid]=mine
        # A public summary contains no other agent's private material.
        event(db,run,pid,'RANK' if final else 'ASSESS','T6 시연 모드로 검증 후보에 무조건 동의했어요.' if force_demo_agree(run) else '토론 조건을 반영해서 제 최종 선호를 정리했어요.' if final else '제 위임 범위와 일정으로 후보들을 비교했어요.')
    patch(run,**{result_key:opinions,cursor_key:cursor+1},
        assessment_progress=dict(completed=cursor+1,total=len(pids),stage='final' if final else 'initial'))
    if cursor+1<len(pids):return
    scores={c['id']:[next(o['score'] for o in opinions[pid] if o['candidate_id']==c['id']) for pid in pids] for c in chosen}
    if not final:
        # Round-robin nominations guarantee every participant a recommendation slot.
        ranked={p:sorted(v,key=lambda o:(-o['score'],o['candidate_id'])) for p,v in opinions.items()}
        ids=[]
        for depth in range(len(chosen)):
            for pid in pids:
                cid=ranked[pid][depth]['candidate_id']
                if cid not in ids:ids.append(cid)
                if len(ids)>=min(run.ctx['settings']['shortlist_limit'],len(chosen)):break
            if len(ids)>=min(run.ctx['settings']['shortlist_limit'],len(chosen)):break
        patch(run,shortlist=ids)
        run.step='candidate_rank' if len(pids)==1 or run.ctx.get('round',0)>=run.ctx['settings']['max_rounds'] else 'candidate_discuss'
    else:
        # Unanimous non-rejection is required; scores order recommendations, not final application.
        eligible=[c for c in chosen if all(next(o for o in opinions[p] if o['candidate_id']==c['id'])['action']!='REJECT' for p in c['affected'])]
        eligible.sort(key=lambda c:(-sum(scores[c['id']])/len(scores[c['id']]),c['id']))
        # Reserve one eligible alternative per recipient family before near-identical
        # timing variants. This is a comparison shortlist, never an automatic winner.
        source_owner=store.board(db).tasks[run.ctx['task']].who
        families={}
        for c in eligible:
            family=tuple(sorted({a['who'] for a in c['allocations']}-{source_owner}))
            families.setdefault(family,[]).append(c)
        diverse=[]
        while families:
            for family in list(families):
                diverse.append(families[family].pop(0))
                if not families[family]:del families[family]
        recommended=[]
        for c in diverse:
            consents={}
            for pid in c['affected']:
                answer=invoke(db,run,Consent,'discussion','candidate_consent',participant_facts(db,run,pid,[c]),pid)
                # Code enforces delegation authority, while the LLM judges card meaning.
                facts=participant_facts(db,run,pid,[c])
                amount=sum(x['days'] for x in facts['candidates'][0]['my_new_work'])
                from ..policies import needs_review
                if answer.action=='ACCEPT' and (amount>run.ctx['private_cards'][pid]['auto_days']+hive.EPS
                        or needs_review(NS(**run.ctx['private_cards'][pid])) or pid in c.get('required_confirmations',[])):
                    answer=Consent(action='NEEDS_INPUT',reason='판단에는 동의하지만 자동 위임 권한을 넘어 본인 확인이 필요해요.')
                consents[pid]=answer.model_dump()
                event(db,run,pid,answer.action,answer.reason,c['id'])
            c['consents']=consents
            if all(a['action']!='REJECT' for a in consents.values()):recommended.append(c['id'])
            if len(recommended)==3:break
        if not recommended:return fail(db,run,'no_consented_candidate')
        patch(run,final_candidates=recommended,candidates=allc,termination=None)
        run.status='awaiting_pm_selection';run.step='candidate_pm'
        event(db,run,'hive','PM_OPTIONS',f'후보 {len(recommended)}개를 추렸어요. PM이 최종 결정해 주세요. 후보가 하나여도 자동 적용하지 않습니다.')


def normalize_recipient(db,answer):
    """수신자를 실제 팀원 id로 맞춘다. 이름·대소문자 차이는 보정하고, PM·전체 등 팀원이 아닌 대상은 공개 발언(None)으로 둔다."""
    people=store.board(db).people
    if answer.recipient is None or answer.recipient in people:return
    key=str(answer.recipient).strip().lower()
    answer.recipient=next((pid for pid,p in people.items() if key in (pid.lower(),str(p.name).lower())),None)


def speech_refs(db,run,answer):
    """Keep only references that exist; the UI and the evaluation read these, not free text."""
    b=store.board(db);history=run.ctx.get('public_history',[]);kept=[]
    for ref in (answer.basis or [])[:6]:
        kind,_,key=str(ref).partition(':');kind=kind.strip().lower();key=key.strip()
        if kind in ('card','my_card','profile','my_profile') and not key:item='card'
        elif kind=='task' and key in b.tasks:item='task:'+key
        elif kind=='handoff' and key in b.hands:item='handoff:'+key
        elif kind=='plan' and key in run.ctx.get('shortlist',[]):item='plan:'+key
        elif kind=='history' and key.isdigit() and int(key)<len(history):item='history:'+key
        else:continue
        if item not in kept:kept.append(item)
    r=answer.reply_to
    return kept,(r if isinstance(r,int) and 0<=r<len(history) and history[r].get('requester') not in ('hive',) else None)


DISCUSSION_ROUNDS=3


def open_questions(run):
    """People asked a question in the plan discussion who have not replied since."""
    h=run.ctx.get('public_history',[]);waiting=[]
    for i,e in enumerate(h):
        if e.get('phase')!='fairness_discussion' or e.get('response')!='QUESTION' or not e.get('recipient'):continue
        who=e['recipient']
        if any(x.get('requester')==who and x.get('phase')=='fairness_discussion' for x in h[i+1:]):continue
        if who not in waiting:waiting.append(who)
    return waiting


def discuss(db,run):
    if demo_auto_consent(run) and run.ctx.get('round',0)>=1:
        run.step='candidate_rank'
        event(db,run,'hive','DEMO_AUTO_CONSENT','T4 데모의 공개 토론 1라운드를 마쳐 알고리즘 자동 동의·PM 후보 제출로 이동합니다.')
        return
    pids=run.ctx.get('participants') or sorted(store.board(db).people);r=run.ctx.get('round',0)+1
    everyone=list(pids)
    if discussion_mode(run) and r>1:
        # Round 1: everyone involved states a position. Later rounds: only people who were asked
        # something and have not answered yet. No open question -> the discussion is over.
        waiting=open_questions(run)
        if not waiting or r>DISCUSSION_ROUNDS:
            event(db,run,'hive','DISCUSSION_STABLE','남은 질문이 없어 토론을 마칩니다.' if not waiting else f'{DISCUSSION_ROUNDS}라운드까지 진행해 토론을 마칩니다. 답하지 못한 질문은 PM이 볼 수 있게 남겨 둡니다.',
                  reason_en='No open questions remain; the discussion ends.' if not waiting else f'Stopping after {DISCUSSION_ROUNDS} rounds; unanswered questions stay visible to the PM.')
            run.step='candidate_rank';return
        pids=[p for p in pids if p in waiting]+[p for p in waiting if p not in pids]
    patch(run,round=r,candidate_phase='fairness_discussion')
    selected=[c for c in run.ctx['candidates'] if c['id'] in run.ctx['shortlist']]
    meaningful=0
    new_conditions=[];messages=set((e['requester'],e['response'],e['reason']) for e in run.ctx['public_history'])
    if not discussion_mode(run):pids=pids[(r-1)%len(pids):]+pids[:(r-1)%len(pids)]
    for pid in pids:
        facts=participant_facts(db,run,pid,selected)
        answer=invoke(db,run,Speech,'discussion','speak',facts,pid)
        normalize_recipient(db,answer)
        if answer.candidate_id not in run.ctx['shortlist']:
            # A plan named by its letter ("안 A") or the only plan on the table is not ambiguous.
            said=str(answer.candidate_id).replace('안','').strip().upper()
            named=[c['id'] for c in selected if c.get('letter')==said]
            if named:answer.candidate_id=named[0]
            elif len(run.ctx['shortlist'])==1:answer.candidate_id=run.ctx['shortlist'][0]
        if answer.candidate_id not in run.ctx['shortlist']:
            # 평가 단계와 같이, 잘못된 후보 참조는 정확한 ID 목록과 함께 한 번만 다시 요청한다.
            event(db,run,'hive','SPEECH_REPAIR','발언이 토론 후보 목록에 없는 후보를 가리켜, 정확한 후보 ID로 한 번만 다시 요청합니다.')
            bad=answer.candidate_id
            answer=invoke(db,run,Speech,'discussion','speak',{**facts,'reference_feedback':dict(expected_candidate_ids=list(run.ctx['shortlist']),received_candidate_id=bad)},pid)
            normalize_recipient(db,answer)
            if answer.candidate_id not in run.ctx['shortlist']:
                # One speaker's bad reference should not end the whole discussion: drop that message and say so.
                patch(run,reference_errors=run.ctx.get('reference_errors',[])+[dict(speaker=pid,received_candidate_ids=[bad,answer.candidate_id],
                    expected_candidate_ids=list(run.ctx['shortlist']))])
                name=store.board(db).people[pid].name
                event(db,run,'hive','SPEECH_SKIPPED',f'{name}의 발언이 없는 계획을 가리켜 뺐어요.',reason_en=f"Skipping {name}'s message: it named a plan that is not on the table.")
                continue
        if answer.recipient and answer.recipient not in everyone:
            everyone.append(answer.recipient);pids.append(answer.recipient);patch(run,participants=list(everyone))
            event(db,run,'hive','INVITE',f'{store.board(db).people[answer.recipient].name}에게 실제 질문이 있어 토론에 초대합니다.',recipient=answer.recipient,
                reason_en=f'Inviting {store.board(db).people[answer.recipient].name}: there is a direct question for them.')
        others=[e['reason'] for e in run.ctx['public_history'] if e.get('phase')=='fairness_discussion' and e['requester'] not in ('hive','pm',pid)]
        if answer.action!='PASS' and near_copy(answer.message,others,run):
            answer=invoke(db,run,Speech,'discussion','speak',dict(facts,copy_feedback=dict(your_message=answer.message,
                note='다른 참여자 발언과 거의 같다. 당신 입장에서 다시 말하거나 새 쟁점이 없으면 PASS.')),pid)
            normalize_recipient(db,answer)
            if answer.candidate_id not in run.ctx['shortlist']:answer.candidate_id=run.ctx['shortlist'][0]
            if answer.action!='PASS' and near_copy(answer.message,others,run):
                event(db,run,'hive','COPY_SKIPPED',f'{store.board(db).people[pid].name}의 발언은 앞 발언과 같아 뺐어요.',
                    reason_en=f"Skipping {store.board(db).people[pid].name}'s message: it repeats another participant.")
                continue
        spoken=answer.message+((' 조건: '+answer.condition) if answer.condition and answer.condition not in answer.message else '')
        key=(pid,answer.action,spoken)
        if key in messages and answer.action=='PASS':continue
        if key in messages:
            event(db,run,'hive','REPEAT_SKIPPED',f'{store.board(db).people[pid].name}의 동일 발언 반복을 건너뜁니다.',reason_en=f'Skipping a repeated message from {store.board(db).people[pid].name}.')
            continue
        if answer.action!='PASS':meaningful+=1
        basis,reply_to=speech_refs(db,run,answer)
        event(db,run,pid,answer.action,spoken,answer.candidate_id,answer.recipient,basis=basis,reply_to=reply_to)
        if answer.action=='CONDITION' and answer.condition and answer.requires_new_candidate:new_conditions.append(dict(who=pid,condition=answer.condition))
    if new_conditions and not run.ctx.get('supplemented'):
        patch(run,supplemented=True,supplement_conditions=new_conditions,pool_revision=run.ctx['pool_revision']+1)
        run.step='candidate_generate'
        event(db,run,'hive','SUPPLEMENT','새 공개 조건이 나왔어요. 기존 후보를 보존하며 한 번만 대안을 보충합니다.',reason_en='A new public condition came up. Hive keeps the plans and adds alternatives once.')
    else:
        stable=run.ctx.get('stable_discussion_rounds',0)+1 if not meaningful else 0
        patch(run,stable_discussion_rounds=stable)
        if stable>=2:event(db,run,'hive','DISCUSSION_STABLE','새로 나온 쟁점이 없어 토론을 마칩니다.',reason_en='No new points came up; the discussion ends.')
        run.step='candidate_rank' if r>=run.ctx['settings']['max_rounds'] or stable>=2 else 'candidate_discuss'


def advance(db,run):
    if run.status=='waiting_pm' and run.ctx.get('termination')=='no_consented_candidate' and force_demo_agree(run) and run.ctx.get('candidates'):
        run.status='running';run.step='candidate_rank'
        patch(run,termination=None,pm_handoff=None)
        event(db,run,'hive','DEMO_AGREE_RECOVERY','T6 무조건 동의 시연 모드로 기존 검증 후보를 다시 제출합니다. PM 선택 전에는 적용하지 않습니다.')
    if run.status!='running':return run
    # The wall-time budget counts processing time only: a paused or closed page must not expire the run.
    step_started=time.time()
    patch(run,expires_at=step_started+run.ctx['settings']['max_seconds']-run.ctx.get('active_seconds',0))
    try:
        check_time(run)
        b=store.board(db);hive.schedule(b)
        if sha256(json.dumps(snapshot(b),sort_keys=True,default=str).encode()).hexdigest()!=run.ctx['snapshot_hash']:
            return fail(db,run,'stale_board') or run
        node=run.step
        turn=runlogs.start_turn(db,run,node)
        if node=='candidate_generate':generate(db,run)
        elif node=='candidate_assess':assess(db,run)
        elif node=='candidate_discuss':discuss(db,run)
        elif node=='candidate_rank':assess(db,run,final=True)
        else:raise ValueError('진행할 수 없는 후보 단계')
        checkpoint(db,run);runlogs.finish_turn(db,run,turn);checkpoint(db,run)
    except CallBudgetExceeded:fail(db,run,'max_llm_calls')
    except TimeLimit:fail(db,run,'max_wall_time')
    except ModelFailure as exc:
        if run.step=='candidate_generate' and run.ctx.get('candidates') and run.ctx.get('supplement_conditions'):
            patch(run,supplement_error=str(exc),final_cursor=0,final_assessments={})
            run.step='candidate_rank'
            event(db,run,'hive','SUPPLEMENT_FAILED','추가 후보 생성은 모델 응답 오류로 실패했어요. 기존 검증 후보를 보존하고 새 공개 조건으로 다시 평가합니다. 수락을 자동 재사용하지 않습니다.')
        else:model_failure(db,run,exc)
        if 'turn' in locals():runlogs.finish_turn(db,run,turn)
    patch(run,active_seconds=run.ctx.get('active_seconds',0)+time.time()-step_started)
    return run


def select_pm(db,run,action,candidate_id=None,plan_hash=None,reason=''):
    if run.kind!='candidate':raise ValueError('후보 협상 run이 아님')
    previous=run.ctx.get('pm_selection')
    if previous and run.status in ('done','waiting_confirm') and action=='select' and previous['candidate_id']==candidate_id and previous['plan_hash']==plan_hash:return run
    if run.status!='awaiting_pm_selection':raise ValueError('PM 최종 선택 대기 상태가 아님')
    if action in ('reject','revise'):
        if not reason.strip():raise ValueError('반려/수정 요청 이유가 필요함')
        event(db,run,'pm',action.upper(),reason)
        if action=='reject':
            run.status='done';run.step='done';patch(run,termination='pm_rejected')
            if run.ctx.get('phase_after'):store.set_meta(db,'phase',run.ctx['phase_after'])
        else:
            revised_candidates=[{k:v for k,v in c.items() if k!='consents'} for c in run.ctx['candidates']]
            patch(run,supplement_conditions=[dict(who='pm',condition=reason)],pool_revision=run.ctx['pool_revision']+1,
                final_candidates=[],candidates=revised_candidates,active_seconds=0,expires_at=time.time()+run.ctx['settings']['max_seconds'])
            # Shared call budget is retained; PM does not implicitly buy extra calls.
            run.status='running';run.step='candidate_generate'
        checkpoint(db,run);return run
    if candidate_id not in run.ctx.get('final_candidates',[]):raise ValueError('PM 최종 후보에 없는 계획')
    c=next(c for c in run.ctx['candidates'] if c['id']==candidate_id)
    if c['plan_hash']!=plan_hash:raise ValueError('선택 후보 버전이 다름')
    b=store.board(db);hive.schedule(b)
    if sha256(json.dumps(snapshot(b),sort_keys=True,default=str).encode()).hexdigest()!=run.ctx['snapshot_hash']:raise ValueError('보드가 변경됨 · 새 후보 검증과 토론이 필요함')
    if cards(db)!=run.ctx['private_cards']:raise ValueError('위임카드가 변경됨 · 새 평가와 동의가 필요함')
    if any(a['action']=='REJECT' for a in c['consents'].values()):raise ValueError('PM은 당사자 거절을 override할 수 없음')
    patch(run,pm_selection=dict(action='select',candidate_id=candidate_id,plan_hash=plan_hash,
        snapshot_hash=run.ctx['snapshot_hash'],reason=reason,selected_at=datetime.now(timezone.utc).isoformat()))
    event(db,run,'pm','SELECT',f"{c['title']} 계획을 선택합니다. {reason}",candidate_id,reason_en=f"I choose this plan. {reason}".strip())
    waiting=[]
    if os.environ.get('PLANBEE_AUTO_CONFIRM')=='1':
        # Service setting: each member's proxy settles its own NEEDS_INPUT by card; only the PM acts by hand.
        # A card-level REJECT already removed the plan before it reached the PM, so this never overrides a refusal.
        c=deepcopy(c)
        for pid,answer in c['consents'].items():
            if answer['action']=='NEEDS_INPUT':
                event(db,run,pid,'AUTO_CONFIRM','자동 확인 설정에 따라 소유권 변경을 포함한 본인 확인을 자동 승인했어요. (확인 요청 사유: '+(answer.get('reason') or '자동 위임 범위 밖')+')',candidate_id)
                answer['action']='ACCEPT';answer['auto_confirmed']=True
        patch(run,candidates=[c if item['id']==c['id'] else item for item in run.ctx['candidates']])
    for pid,answer in c['consents'].items():
        if answer['action']=='NEEDS_INPUT':
            confirmation=Confirmation(who=pid,prompt='PM이 선택한 새 milestone 계획에 동의하나요?',
                text=f"{c['id']} · {c['title']} · {c['plan_hash']}",role='candidate',run_id=run.id)
            db.add(confirmation);db.flush();waiting.append(confirmation.id)
    patch(run,waiting_for=waiting)
    if waiting:
        run.status='waiting_confirm';run.step='candidate_confirm'
        event(db,run,'hive','CONFIRM','PM 선택을 받았어요. 위임 권한 밖인 당사자의 본인 확인 후 적용합니다.')
    else:commit(db,run)
    return run


def commit(db,run):
    from .. import discussion,task_partition,plan_adjustments
    selection=run.ctx['pm_selection'];c=next(c for c in run.ctx['candidates'] if c['id']==selection['candidate_id'])
    if run.status=='done':return run
    confirmations=list(db.scalars(select(Confirmation).where(Confirmation.id.in_(run.ctx.get('waiting_for',[])))))
    if any(x.status=='rejected' for x in confirmations):
        for x in confirmations:
            if x.status=='pending':x.status='withdrawn'
        event(db,run,'hive','REJECT','당사자가 선택안을 거절했어요. 적용하지 않고 PM 후보 목록으로 돌아갑니다.')
        c['consents']={**c['consents'],**{x.who:dict(action='REJECT',reason='본인 거절') for x in confirmations if x.status=='rejected'}}
        patch(run,candidates=run.ctx['candidates'],final_candidates=[i for i in run.ctx['final_candidates'] if i!=c['id']],pm_selection=None,waiting_for=[])
        if not run.ctx['final_candidates']:fail(db,run,'no_consented_candidate')
        else:run.status='awaiting_pm_selection';run.step='candidate_pm'
        return run
    if any(x.status=='pending' for x in confirmations):return run
    b=store.board(db);hive.schedule(b)
    if sha256(json.dumps(snapshot(b),sort_keys=True,default=str).encode()).hexdigest()!=run.ctx['snapshot_hash']:
        return fail(db,run,'stale_board') or run
    if cards(db)!=run.ctx['private_cards']:return fail(db,run,'stale_cards') or run
    try:
        with db.begin_nested():
            st,affected,_,_=plans.preview(b,run.ctx,c['allocations'],c['schedule_changes'],c.get('plan_actions'))
            if set(affected)-set(c['consents']):raise ValueError('변경된 영향 당사자 동의 누락')
            plans.apply(db,b,st,run.ctx,c['allocations'])
            db.flush();current=store.board(db);hive.schedule(current)
            if not hive.gate(current)['ok']:raise ValueError('실제 저장 후 제약 실패')
    except (ValueError,KeyError,TypeError) as exc:
        return fail(db,run,'commit_validation_failed: '+str(exc)) or run
    run.status='done';run.step='done'
    patch(run,termination='applied',final_board=view(current))
    if run.ctx.get('phase_after'):store.set_meta(db,'phase',run.ctx['phase_after'])
    event(db,run,'hive','APPLIED','PM 선택과 당사자 동의를 확인했고, 최종 마감 검증을 통과해 새 milestone 보드에 적용했어요.',c['id'],reason_en="The PM's choice passed the final deadline check and is applied to the board.")
    return run


def response(run):
    # Explicit allowlist: neither private cards nor prompt content nor private ballots leak.
    keys=('demo_auto_consent','task','reporter','task_resolution','clarification','issue','phase','round','pool_revision','pool_hash','generation','generation_reason','shortlist',
        'final_candidates','public_history','llm_budget','termination','pm_selection','pm_handoff',
        'participants','supplement_error','prompt_hashes','snapshot_hash','initial_board','final_board','transcript_file','llm_mode','proxy_mode','assessment_progress',
        'consent_mode','impact','relaxation_options','granted_rules')
    return dict(id=run.id,kind=run.kind,status=run.status,step=run.step,
        **{k:deepcopy(run.ctx.get(k)) for k in keys},
        candidates=[public_candidate(c) for c in run.ctx.get('candidates',[])])
