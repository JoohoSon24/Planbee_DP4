"""Additive API; candidate PM authority is separate from legacy exception grants."""
import os
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from . import engine, evaluation
from ..models import Run, CandidateEvaluation, Confirmation
from .. import store, workflow, viewer

class StartIn(BaseModel):
    task_id: str | None = None
    timeline_event_id: str | None = None
    issue: str = Field(min_length=1,max_length=8000)
    settings: engine.Settings | None = None
    language: str = Field(default='ko',pattern='^(ko|en)$')

class TranslationIn(BaseModel):
    keys: list[str] = Field(min_length=1,max_length=12)


class DisplayTranslationIn(BaseModel):
    texts: list[str] = Field(min_length=1,max_length=24)


class PMIn(BaseModel):
    action: Literal['select','reject','revise']
    candidate_id: str | None = None
    plan_hash: str | None = None
    reason: str = Field(default='',max_length=4000)

class RuleIn(BaseModel):
    rule_id: str = Field(min_length=1,max_length=40)
    reason: str = Field(default='',max_length=2000)

class EvalIn(BaseModel):
    rubric: Literal['fairness','card_fit']
    person_id: str | None = None
    seed: int = 17

class LabelIn(BaseModel):
    evaluation_hash: str
    ranking_groups: list[list[str]]
    eligibility: dict[str, Literal['ACCEPT','REJECT','NEEDS_INPUT']] = Field(default_factory=dict)


def install(app,get_db,busy):
    router=APIRouter()
    @router.post('/display-translations')
    def display_translations(body:DisplayTranslationIn):
        from ..translations import translate_display
        return attempt(lambda:translate_display(body.texts))

    @router.get('/runtime')
    def runtime():
        from ..llm import runtime_mode,get_llm
        adapter=get_llm()
        return dict(t6_force_agree_enabled=os.environ.get('PLANBEE_T6_FORCE_AGREE','1')=='1',demo_force_agree=store.DEMO=='m4_t6_game_demo' and os.environ.get('PLANBEE_T6_FORCE_AGREE','1')=='1',auto_confirm=os.environ.get('PLANBEE_AUTO_CONFIRM')=='1',llm_mode=runtime_mode(),model=getattr(adapter,'model',None),negotiation_mode='candidate_discussion')
    def find(db,rid):
        run=db.get(Run,rid)
        if not run or run.kind!='candidate':raise HTTPException(404,'후보 run을 찾을 수 없음')
        return run
    def attempt(fn):
        try:return fn()
        except ValueError as exc:raise HTTPException(409,str(exc))
    def evalrow(db,eid):
        row=db.get(CandidateEvaluation,eid)
        if not row:raise HTTPException(404,'평가를 찾을 수 없음')
        return row

    @router.post('/candidate-runs')
    def start(body:StartIn,request:Request,db=Depends(get_db)):
        board=store.board(db);reporter=viewer.role(request)
        if reporter and reporter!='pm' and reporter[7:] not in board.people:raise HTTPException(403,'없는 사용자 역할')
        if body.task_id:
            task=board.tasks.get(body.task_id)
            if not task:raise HTTPException(404,'없는 Task')
            viewer.owner(request,task.who)
        # Reporting a public team issue is distinct from consenting to a change.
        # The inferred owner and all affected people still decide by their own cards.
        busy(db);store.snap(db);before=store.latest_snapshot_id(db)
        if body.timeline_event_id:
            from ..timeline import apply_report
            event=attempt(lambda:apply_report(db,body.timeline_event_id,body.issue))
            task_id=event['task']
        else:task_id=body.task_id
        run=attempt(lambda:engine.start(db,task_id,body.issue,body.settings,reporter=reporter,language=body.language))
        if body.timeline_event_id:engine.patch(run,timeline_event=body.timeline_event_id)
        engine.patch(run,pre_report_snapshot=before)
        return engine.response(run)

    @router.post('/runs/{rid}/revert-report')
    def revert_report(rid:int,request:Request,db=Depends(get_db)):
        """Live demo safety: put the board back to just before this report, whatever happened after it.
        Only the latest report can be reverted, and not while the model is still working on it."""
        viewer.pm(request)
        run=find(db,rid)
        latest=db.scalars(select(Run).where(Run.kind=='candidate').order_by(Run.id.desc())).first()
        if latest is None or latest.id!=run.id:raise HTTPException(409,'가장 최근 보고만 되돌릴 수 있어요.')
        if run.status=='running':raise HTTPException(409,'아직 처리 중이에요. 멈춘 뒤 되돌려 주세요.')
        if run.ctx.get('termination')=='reverted':return engine.response(run)
        sid=run.ctx.get('pre_report_snapshot')
        if not sid or not store.restore_board(db,sid):raise HTTPException(409,'되돌릴 저장 지점이 없어요.')
        run=find(db,rid);run.status='done';run.step='done'
        engine.patch(run,termination='reverted',pm_acknowledged=True)
        engine.event(db,run,'pm','REVERT','이 보고 전의 보드로 되돌렸어요. 이 스레드의 계획은 적용되지 않아요.',
                     reason_en='Reverted the board to before this report. No plan from this thread is applied.')
        return engine.response(run)

    @router.post('/runs/{rid}/stop')
    def stop(rid:int,request:Request,db=Depends(get_db)):
        """Stop a run between model calls (the call in flight finishes first). Nothing is applied."""
        viewer.pm(request)
        run=find(db,rid)
        if run.status in ('running','awaiting_pm_selection','waiting_pm','waiting_confirm'):
            run.status='done';run.step='done'
            engine.patch(run,termination='pm_stopped',pm_acknowledged=True)
            engine.event(db,run,'pm','STOP','PM이 진행을 멈췄어요. 적용된 계획은 없어요.',reason_en='The PM stopped this run. No plan was applied.')
        return engine.response(run)

    @router.get('/candidate-runs')
    def runs(db=Depends(get_db)):
        return [engine.response(r) for r in db.scalars(select(Run).where(Run.kind=='candidate').order_by(Run.id.desc()))]

    @router.get('/runs/{rid}')
    def get_run(rid:int,db=Depends(get_db)):return engine.response(find(db,rid))

    @router.post('/runs/{rid}/advance')
    def advance(rid:int,db=Depends(get_db)):
        run=find(db,rid)
        return engine.response(attempt(lambda:engine.advance(db,run)))

    @router.post('/runs/{rid}/translations')
    def translate_run(rid:int,body:TranslationIn,db=Depends(get_db)):
        from .. import translations
        return attempt(lambda:translations.translate(find(db,rid),body.keys))

    @router.get('/runs/{rid}/candidate-pools')
    def pools(rid:int,db=Depends(get_db)):
        r=find(db,rid);return dict(revision=r.ctx.get('pool_revision'),hash=r.ctx.get('pool_hash'),generation=r.ctx.get('generation'))

    @router.get('/runs/{rid}/candidates')
    def candidates(rid:int,pool_revision:int|None=None,db=Depends(get_db)):
        run=find(db,rid)
        if pool_revision is not None and pool_revision!=run.ctx['pool_revision']:raise HTTPException(409,'현재 pool revision이 아님')
        return [engine.public_candidate(c) for c in run.ctx.get('candidates',[])]

    @router.get('/runs/{rid}/candidates/{cid}')
    def candidate(rid:int,cid:str,db=Depends(get_db)):
        run=find(db,rid);found=next((c for c in run.ctx.get('candidates',[]) if c['id']==cid),None)
        if not found:raise HTTPException(404,'없는 후보')
        return engine.public_candidate(found)

    @router.get('/runs/{rid}/discussion')
    def discussion(rid:int,db=Depends(get_db)):return find(db,rid).ctx.get('public_history',[])

    @router.get('/runs/{rid}/pm-options')
    def options(rid:int,db=Depends(get_db)):
        run=find(db,rid)
        return dict(status=run.status,summary=run.ctx.get('pm_handoff'),
            options=[engine.public_candidate(c) for c in run.ctx.get('candidates',[]) if c['id'] in run.ctx.get('final_candidates',[])])

    @router.post('/runs/{rid}/pm-selection')
    def choose(rid:int,body:PMIn,request:Request,db=Depends(get_db)):
        viewer.pm(request)
        run=find(db,rid);store.snap(db)
        attempt(lambda:engine.select_pm(db,run,body.action,body.candidate_id,body.plan_hash,body.reason))
        if run.status=='awaiting_pm_selection' and body.action=='select':
            candidate=next(c for c in run.ctx['candidates'] if c['id']==body.candidate_id)
            prior=run.ctx.get('pm_selection')
            if prior and prior['candidate_id']!=body.candidate_id:raise HTTPException(409,'다른 후보의 본인 확인이 진행 중')
        return engine.response(run)

    @router.post('/runs/{rid}/rules')
    def grant_rule(rid:int,body:RuleIn,request:Request,db=Depends(get_db)):
        # PM grants one relaxation Hive listed; planning restarts with that rule changed.
        viewer.pm(request)
        run=find(db,rid);store.snap(db)
        attempt(lambda:engine.grant_rule(db,run,body.rule_id,body.reason))
        return engine.response(attempt(lambda:engine.advance(db,run)))

    @router.post('/runs/{rid}/evaluations')
    def new_eval(rid:int,body:EvalIn,db=Depends(get_db)):
        row=attempt(lambda:evaluation.create(db,find(db,rid),body.rubric,body.person_id,body.seed))
        return evaluation.blind_view(row)

    @router.get('/evaluations/{eid}')
    def get_eval(eid:int,db=Depends(get_db)):
        row=evalrow(db,eid)
        return dict(**evaluation.blind_view(row),result=row.data.get('result'))

    @router.post('/evaluations/{eid}/human-ranking')
    @router.post('/evaluations/{eid}/human-rankings')
    def label(eid:int,body:LabelIn,db=Depends(get_db)):
        return attempt(lambda:evaluation.submit(evalrow(db,eid),body.ranking_groups,body.evaluation_hash,body.eligibility))

    @router.post('/evaluations/{eid}/compare')
    @router.get('/evaluations/{eid}/compare')
    def compared(eid:int,db=Depends(get_db)):
        row=evalrow(db,eid)
        if not row.data.get('result'):raise HTTPException(409,'사람 순위를 먼저 제출하세요')
        return row.data['result']

    @router.post('/runs/{rid}/close')
    def close(rid:int,request:Request,db=Depends(get_db)):
        viewer.pm(request)
        run=find(db,rid)
        if run.status=='done' and run.ctx.get('pm_acknowledged'):return engine.response(run)
        if run.status!='waiting_pm':raise HTTPException(409,'실패 요약을 확인하는 상태가 아님')
        run.status='done';engine.patch(run,termination=run.ctx.get('termination') or 'pm_closed',pm_acknowledged=True)
        engine.event(db,run,'pm','CLOSE','현재 상황을 확인했습니다. 미합의 변경은 적용하지 않습니다.')
        if run.ctx.get('phase_after'):store.set_meta(db,'phase',run.ctx['phase_after'])
        return engine.response(run)
    app.include_router(router)
