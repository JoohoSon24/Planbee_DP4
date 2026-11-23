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
from .models import Assessment, Consent, ConstraintReview, Designs, Opinion, Part, Speech, Transformation, TaskSelection
from . import plans
from .generator import enumerate_plans, snapshot, view, canonical, execution_key
from .. import hive, store, runlogs, prompts
from ..llm import LiveLLM, get_llm
from ..models import Run, Task, Confirmation
from ..negotiation_budget import bound, consume, CallBudgetExceeded

class Settings(BaseModel):
    raw_limit: int = Field(default=500,ge=1,le=2000)
    candidate_limit: int = Field(default=50,ge=1,le=100)
    shortlist_limit: int = Field(default=10,ge=1,le=12)
    max_rounds: int = Field(default=2,ge=1,le=15)
    max_calls: int = Field(default=120,ge=1,le=400)
    max_seconds: int = Field(default=600,ge=1,le=1800)
    seed: int = 17

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

def checkpoint(db,run):
    # A frozen copy makes nested JSON changes visible to SQLAlchemy.
    run.ctx=deepcopy(run.ctx)
    db.flush()


def event(db,run,actor,action,text,candidate_id=None,recipient=None):
    entry=dict(round=run.ctx.get('round',0),phase=run.ctx.get('candidate_phase','generate'),
        requester=actor,recipient=recipient,response=action,reason=text,candidate_id=candidate_id,
        llm_budget=deepcopy(run.ctx.get('llm_budget')))
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
    adapter=get_llm();budget=run.ctx['llm_budget']
    try:
        with prompts.frozen(run.ctx['prompt_snapshot']),bound(budget):
            if isinstance(adapter,LiveLLM):
                instruction=prompts.load_prompt(group,name)
                if group=='candidate_generation':instruction=prompts.load_prompt(group,'system')+'\n'+instruction
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
    items=[]
    for c in candidates:
        st,_,_,_=plans.preview(b,run.ctx,c['allocations'],c['schedule_changes'],c.get('plan_actions'))
        own=[dict(id=t.id,title=t.title,who=t.who,start=t.s,days=t.d) for t in st.tasks.values() if t.who==pid and not t.cut]
        items.append(dict(id=c['id'],plan_hash=c['plan_hash'],title=c['title'],operator=c['operator'],
            allocations=c['allocations'],schedule_changes=c['schedule_changes'],plan_actions=c.get('plan_actions',[]),affected=c['affected'],required_confirmations=c.get('required_confirmations',[]),deferred=c['board'].get('deferred',[]),omitted=c['board'].get('omitted',[]),allocations_are_deferred=any(t['id']==run.ctx['task'] for t in c['board'].get('deferred',[])),hive_verification=c['board']['gate'],
            milestones=[t for t in c['board']['tasks'] if st.tasks[t['id']].kind=='milestone'],
            my_new_work=incoming(b,st,run.ctx,c['allocations'],pid),my_schedule=own,
            fairness=c['board']['fairness'],basis=c['basis']))
    p=b.people[pid]
    cd=run.ctx['private_cards'][pid]
    return dict(self=dict(id=pid,name=p.name),my_delegation=deepcopy(cd),agent_instructions=agent_instructions(run,b,pid),issue=run.ctx['issue'],
        candidates=items,public_conditions=run.ctx.get('supplement_conditions',[]),public_history=run.ctx.get('public_history',[]),
        participants=[dict(id=p.id,name=p.name,role=p.role) for p in b.people.values()],
        source=b.tasks[run.ctx['task']].who,original_task=dict(id=run.ctx['task'],
            title=b.tasks[run.ctx['task']].title,days=b.tasks[run.ctx['task']].d,
            context=b.tasks[run.ctx['task']].context or {}),public_board=snapshot(b))


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
        facts=dict(self=dict(id=pid,name=b.people[pid].name),my_delegation=run.ctx['private_cards'][pid],
            agent_instructions=agent_instructions(run,b,pid),issue=run.ctx['issue'],
            public_board=snapshot(b),public_history=run.ctx['public_history'],validation_feedback=run.ctx['generation'],
            participants=[dict(id=p.id,name=p.name,role=p.role) for p in b.people.values()])
        answer=invoke(db,run,ConstraintReview,'discussion','no_options',facts,pid)
        if answer.recipient not in set(b.people)|{'pm',None}:raise ModelFailure('invalid_review_recipient')
        event(db,run,pid,'CONSTRAINT_REVIEW',answer.message+' '+answer.required_decision,recipient=answer.recipient)


def mock_reply(db,run,schema,facts,pid):
    """Explicit offline fixtures only. Live errors never take this branch."""
    if schema is TaskSelection:
        text=facts['issue'].split('\n\n참조:')[0].split('\n\nReferences:')[0].casefold()
        matches=[t for t in facts['tasks'] if t['title'].casefold() in text or t['id'].casefold() in text]
        if len(matches)==1:return TaskSelection(task_id=matches[0]['id'],reason='Mock: 이슈에 명시된 업무 이름을 찾았습니다.')
        if matches:
            matches.sort(key=lambda t:min([text.find(v) for v in (t['title'].casefold(),t['id'].casefold()) if v in text]))
            return TaskSelection(task_id=matches[0]['id'],reason='Mock: 이슈에 먼저 언급된 업무를 선택했습니다.')
        return TaskSelection(reason='Mock에서 명시된 업무 이름을 찾지 못했습니다.',clarification='어떤 업무에서 무엇이 바뀌었는지 한 문장으로 알려 주세요.')
    if schema is Designs:
        t=store.board(db).tasks[run.ctx['task']]
        script=(getattr(get_llm(),'script',{}) or {}).get('split',{}).get(t.id)
        templates=[]
        if script and (t.context or {}).get('splittable_hint') is not False:
            piece=script.get('piece') or {};n=piece.get('days',0)
            if 0<n<t.d:
                templates=[Transformation(title='Mock 대본의 독립 검증 분리',basis='Mock 데모에 명시된 조각 범위와 원 담당자의 보유분을 분리한다.',parts=[
                    Part(key='core',title=t.title+' 보유분',what=t.title+'의 '+str(piece.get('title','조각'))+' 이외 원 업무',effort=t.d-n),
                    Part(key='piece',title=piece['title'],what=piece.get('what') or piece['title'],effort=n)])]
        return Designs(templates=templates,reason='Mock 대본 기반 의미 설계. 없으면 전체 양도와 다른 업무 이동만 탐색.')
    if schema is ConstraintReview:
        return ConstraintReview(recipient='pm',message='추가 수정 후의 검증 순서와 공개 일정 제약을 확인했어요. 현재 후보 탐색에서는 기한을 지킬 수 있는 안이 없어요.',required_decision='필수 작업·검증을 줄이지 않고 PM에게 보류 검토를 요청합니다.')
    items=facts['candidates'];cd=facts['my_delegation']
    if schema is Speech:
        cid=items[0]['id']
        return Speech(candidate_id=cid,action='PREFER',message='공개된 조건을 확인했어요. 제 카드로 가능한 후보부터 비교하고 싶어요.' if not facts.get('public_history') else '앞서 나온 조건을 반영해서 제 부담과 다른 팀원의 변경 일정을 다시 비교할게요.')
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
    event(db,run,'hive','END',f'협상을 마쳤어요. {reason} · 미합의 변경은 적용하지 않고 PM에게 상황을 전달합니다.')


def start(db,task_id,issue,settings=None,phase_after=None,reporter=None):
    b=store.board(db);hive.schedule(b)
    t=b.tasks.get(task_id)
    if task_id and (not t or t.cut or t.kind in ('done','milestone','prop') or t.d<=0):raise ValueError('실행 가능한 Task를 선택하세요')
    cfg=settings or Settings(max_calls=int(os.environ.get('PLANBEE_MAX_CANDIDATE_CALLS','120')))
    snap=snapshot(b);files=prompts.snapshot()
    gate=hive.gate(b)
    run=Run(kind='candidate',step='candidate_input',status='running',auto_confirm=False,ctx=dict(
        task=t.id if t else None,who=t.who if t else None,reporter=reporter,issue=issue,records=[issue],phase='fairness' if gate['ok'] else 'deadline',
        rebalance_reason='fairness' if gate['ok'] else 'deadline',round=0,settings=cfg.model_dump(),
        phase_after=phase_after,board_snapshot=snap,snapshot_hash=sha256(json.dumps(snap,sort_keys=True,default=str).encode()).hexdigest(),
        initial_board=view(b),private_cards=cards(db),prompt_snapshot=files,
        prompt_hashes={k:sha256(v.encode()).hexdigest() for k,v in files.items()},
        expires_at=time.time()+cfg.max_seconds,llm_budget=dict(used=0,max=cfg.max_calls),
        public_history=[],candidates=[],pool_revision=1))
    db.add(run);db.flush();runlogs.ensure_metadata(run)
    patch(run,initial_milestones=runlogs.milestones(db))
    input_turn=runlogs.start_turn(db,run,'candidate_input')
    event(db,run,'hive','ISSUE','이슈를 받았어요. 시간 안에 가능한 새 milestone 계획부터 만들겠습니다.')
    # The issue owner's estimate changes the problem, never an allocation consent.
    try:
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
        adapter=get_llm()
        with prompts.frozen(files),bound(run.ctx['llm_budget']):
            if not isinstance(adapter,LiveLLM):consume()
            estimate=adapter.reestimate(b.people[t.who],[issue],[t],model=run.ctx['private_cards'][t.who].get('model')) if hasattr(adapter,'reestimate') else None
            if isinstance(adapter,LiveLLM) and getattr(adapter,'last_error',None):
                raise ModelFailure(json.dumps(adapter.last_error,ensure_ascii=False))
        if estimate and estimate.task==task_id and abs(estimate.days-t.d)>hive.EPS:
            t.d=estimate.days;hive.schedule(b)
            updated=snapshot(b)
            patch(run,board_snapshot=updated,snapshot_hash=sha256(json.dumps(updated,sort_keys=True,default=str).encode()).hexdigest(),
                phase='fairness' if hive.gate(b)['ok'] else 'deadline',
                rebalance_reason='fairness' if hive.gate(b)['ok'] else 'deadline')
            event(db,run,t.who,'ESTIMATE',f'이슈를 읽고 이 업무를 {t.d:g}일로 다시 견적했어요.')
    except TimeLimit:
        fail(db,run,'max_wall_time');runlogs.finish_turn(db,run,input_turn);return run
    except CallBudgetExceeded:
        fail(db,run,'max_llm_calls');runlogs.finish_turn(db,run,input_turn);return run
    except ModelFailure as exc:
        model_failure(db,run,exc);runlogs.finish_turn(db,run,input_turn);return run
    run.step='candidate_generate'
    runlogs.finish_turn(db,run,input_turn)
    return advance(db,run)


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
    if not candidates and isinstance(get_llm(),LiveLLM):
        event(db,run,'hive','REPAIR_REQUEST','현재 구조로 통과한 계획이 없어요. 제약 위반을 근거로 한 번만 구조를 다시 요청합니다.')
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
        return fail(db,run,'search_exhausted')
    if (t.context or {}).get('active_participants_only'):
        patch(run,participants=sorted({pid for c in candidates for pid in c['affected']}))
    event(db,run,'hive','CANDIDATES',f"일정 검증을 통과한 새 milestone 계획 {len(candidates)}개를 준비했어요. 이제 각자 카드로 비교합니다.")
    run.step='candidate_assess'


def assess(db,run,final=False):
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
            result=invoke(db,run,Assessment,'discussion','rank' if final else 'assess',facts,pid)
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
        event(db,run,pid,'RANK' if final else 'ASSESS','토론 조건을 반영해서 제 최종 선호를 정리했어요.' if final else '제 위임 범위와 일정으로 후보들을 비교했어요.')
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
        recommended=[]
        for c in eligible:
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


def discuss(db,run):
    pids=run.ctx.get('participants') or sorted(store.board(db).people);r=run.ctx.get('round',0)+1
    patch(run,round=r,candidate_phase='fairness_discussion')
    selected=[c for c in run.ctx['candidates'] if c['id'] in run.ctx['shortlist']]
    new_conditions=[];messages=set((e['requester'],e['response'],e['reason']) for e in run.ctx['public_history'])
    pids=pids[(r-1)%len(pids):]+pids[:(r-1)%len(pids)]
    for pid in pids:
        facts=participant_facts(db,run,pid,selected)
        answer=invoke(db,run,Speech,'discussion','speak',facts,pid)
        normalize_recipient(db,answer)
        if answer.candidate_id not in run.ctx['shortlist']:
            # 평가 단계와 같이, 잘못된 후보 참조는 정확한 ID 목록과 함께 한 번만 다시 요청한다.
            event(db,run,'hive','SPEECH_REPAIR','발언이 토론 후보 목록에 없는 후보를 가리켜, 정확한 후보 ID로 한 번만 다시 요청합니다.')
            bad=answer.candidate_id
            answer=invoke(db,run,Speech,'discussion','speak',{**facts,'reference_feedback':dict(expected_candidate_ids=list(run.ctx['shortlist']),received_candidate_id=bad)},pid)
            normalize_recipient(db,answer)
            if answer.candidate_id not in run.ctx['shortlist']:
                patch(run,model_error=json.dumps(dict(type='invalid_discussion_reference',speaker=pid,received_candidate_ids=[bad,answer.candidate_id],
                    expected_candidate_ids=list(run.ctx['shortlist'])),ensure_ascii=False))
                raise ModelFailure('invalid_discussion_reference')
        if answer.recipient and answer.recipient not in pids:
            pids.append(answer.recipient);patch(run,participants=list(pids))
            event(db,run,'hive','INVITE',f'{store.board(db).people[answer.recipient].name}에게 실제 질문이 있어 토론에 초대합니다.',recipient=answer.recipient)
        spoken=answer.message+((' 조건: '+answer.condition) if answer.condition and answer.condition not in answer.message else '')
        key=(pid,answer.action,spoken)
        if key in messages:
            event(db,run,'hive','REPEAT_SKIPPED',f'{store.board(db).people[pid].name}의 동일 발언 반복을 건너뜁니다.')
            continue
        event(db,run,pid,answer.action,spoken,answer.candidate_id,answer.recipient)
        if answer.action=='CONDITION' and answer.condition and answer.requires_new_candidate:new_conditions.append(dict(who=pid,condition=answer.condition))
    if new_conditions and not run.ctx.get('supplemented'):
        patch(run,supplemented=True,supplement_conditions=new_conditions,pool_revision=run.ctx['pool_revision']+1)
        run.step='candidate_generate'
        event(db,run,'hive','SUPPLEMENT','새 공개 조건이 나왔어요. 기존 후보를 보존하며 한 번만 대안을 보충합니다.')
    else:run.step='candidate_rank' if r>=run.ctx['settings']['max_rounds'] else 'candidate_discuss'


def advance(db,run):
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
    event(db,run,'pm','SELECT',f"{c['title']} 계획을 선택합니다. {reason}",candidate_id)
    waiting=[]
    if os.environ.get('PLANBEE_AUTO_CONFIRM')=='1':
        # Service setting: each member's proxy settles its own NEEDS_INPUT by card; only the PM acts by hand.
        # A card-level REJECT already removed the plan before it reached the PM, so this never overrides a refusal.
        for pid,answer in c['consents'].items():
            if answer['action']=='NEEDS_INPUT':
                event(db,run,pid,'AUTO_CONFIRM','위임카드에 금지가 없어 본인 확인을 자동 승인했어요. (확인 요청 사유: '+(answer.get('reason') or '자동 위임 범위 밖')+')',candidate_id)
                answer['action']='ACCEPT';answer['auto_confirmed']=True
        patch(run,candidates=run.ctx['candidates'])
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
    event(db,run,'hive','APPLIED','PM 선택과 당사자 동의를 확인했고, 최종 마감 검증을 통과해 새 milestone 보드에 적용했어요.',c['id'])
    return run


def response(run):
    # Explicit allowlist: neither private cards nor prompt content nor private ballots leak.
    keys=('task','reporter','task_resolution','clarification','issue','phase','round','pool_revision','pool_hash','generation','generation_reason','shortlist',
        'final_candidates','public_history','llm_budget','termination','pm_selection','pm_handoff',
        'participants','supplement_error','prompt_hashes','snapshot_hash','initial_board','final_board','transcript_file','llm_mode','assessment_progress')
    return dict(id=run.id,kind=run.kind,status=run.status,step=run.step,
        **{k:deepcopy(run.ctx.get(k)) for k in keys},
        candidates=[public_candidate(c) for c in run.ctx.get('candidates',[])])
