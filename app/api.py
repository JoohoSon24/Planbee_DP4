"""HTTP API. 프로토타입의 세 화면(입력 · 판 · Handoffs)이 쓰는 것만 있다.

실행:  uvicorn app.api:app --reload      문서:  http://localhost:8000/docs
"""
from __future__ import annotations

import base64
import os
import secrets
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import PlainTextResponse, FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator
from sqlalchemy import select

from . import hive, store, workflow, bundles, viewer
from .models import Ask, Confirmation, Message, Record, Rule, Run, Task
from .policies import CardPolicy

engine = store.make_engine()
SessionLocal = store.make_session_factory(engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    with SessionLocal() as db:
        if store.is_empty(db) or store.meta(db, "demo") != store.DEMO:
            store.reset(db)
            db.commit()
    yield


app = FastAPI(title="Plan Bee · Handoffs API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# 배포용 접근 제한. PLANBEE_BASIC_AUTH_PASSWORD 가 설정된 경우에만 전체 경로에 Basic Auth 를 건다.
# 로컬 실행(변수 없음)은 기존과 동일하다. /healthz 는 호스팅의 상태 검사용으로 열어 둔다.
_AUTH_PASSWORD = os.environ.get("PLANBEE_BASIC_AUTH_PASSWORD", "")
_AUTH_USER = os.environ.get("PLANBEE_BASIC_AUTH_USER", "planbee")


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    if not _AUTH_PASSWORD or request.url.path == "/healthz":
        return await call_next(request)
    header = request.headers.get("authorization", "")
    if header.lower().startswith("basic "):
        try:
            user, _, pw = base64.b64decode(header[6:]).partition(b":")
        except ValueError:
            user, pw = b"", b""
        # 바이트로 비교한다. str 비교는 한글 등 비 ASCII 입력에서 TypeError(500)를 낸다.
        ok_user = secrets.compare_digest(user, _AUTH_USER.encode("utf-8"))
        ok_pw = secrets.compare_digest(pw, _AUTH_PASSWORD.encode("utf-8"))
        if ok_user and ok_pw:
            return await call_next(request)
    return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="Plan Bee"'})


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}


def get_db(request: Request):
    db = SessionLocal()
    readonly = request.method in ("GET", "HEAD", "OPTIONS")
    try:
        if readonly:
            db.autoflush = False
        else:
            bundles.lock(db)
        yield db
        if readonly:
            db.rollback()
        else:
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def bad(e: Exception):
    raise HTTPException(status_code=409, detail=str(e))


def busy(db, pm_may_reagree: str | None = None):
    """협상이 사람이나 PM을 기다리는 동안에는 새 기록 · PM 조작을 받지 않는다 (프로토타입의 RUN 잠금).

    하나만 예외: PM 확인이 열린 바로 그 Handoff 의 약속을 다시 정하는 것은 PM 의 답으로 받는다.
    """
    r = db.scalars(select(Run).where(Run.status.in_(["running", "waiting_confirm", "waiting_pm", "awaiting_pm_selection"]))).first()
    if not r or (r.status == "waiting_pm" and pm_may_reagree and r.ctx.get("hid") == pm_may_reagree):
        return
    what = "PM 확인" if r.status == "waiting_pm" else "팀원 확인"
    raise HTTPException(status_code=409, detail=f"진행 중인 협상이 {what}을 기다리고 있음")


# ── 요청 모양 ─────────────────────────────────────────────────────────
class RecordIn(BaseModel):
    src: Literal["작업", "저장소", "메신저"]
    who: str
    text: str
    t: str | None = None


class RecordsIn(BaseModel):
    records: list[RecordIn]
    auto_confirm: bool = False
    negotiation_mode: Literal['legacy','candidate_discussion'] | None = None


class AutoIn(BaseModel):
    auto_confirm: bool = True
    negotiation_mode: Literal['legacy','candidate_discussion'] | None = None


class ConfirmIn(BaseModel):
    ok: bool = True


class GrantIn(BaseModel):
    key: str | None = None
    index: int | None = None


class RejectIn(BaseModel):
    reason: str                          # 왜 안 되는지. 프록시들이 이 이유를 받아 다시 협상한다
    keys: list[str] | None = None        # 거절할 선택지. 비우면 전부


class DemoIn(BaseModel):
    demo: str


class PrefIn(BaseModel):
    choice: Literal["fast", "learn", "fair"]


class CardIn(BaseModel):
    policy: CardPolicy | None = None
    auto_days: float | None = None       # 이 일수까지는 프록시가 알아서 수락 (0 ~ 5, 0.5 단위)
    refuse_tags: list[str] | None = None
    gives_help: bool | None = None
    note: str | None = None
    wait_days: float | None = None       # 받기로 한 것이 이만큼 늦어져도 프록시가 알아서 수락 (0 ~ 5)
    model: str | None = None             # 이 프록시만 쓸 LLM (OpenRouter 모델 이름). 빈 문자열이면 기본 모델로


class RoundsIn(BaseModel):
    max: int


class MoveIn(BaseModel):
    dest: str            # 사람 id · "next"(2주차로) · "cut"(이번 제출에서 빼기)
    auto_confirm: bool = False


# ── 전체 상태 ─────────────────────────────────────────────────────────
@app.get("/state", summary="세 화면을 그리는 데 필요한 전부 (프로토타입의 S)")
def get_state(db=Depends(get_db)):
    return store.state_json(db)


# ── 입력 화면: 기록과 규칙 ────────────────────────────────────────────
@app.get("/records", summary="들어온 기록")
def get_records(db=Depends(get_db)):
    return store.state_json(db)["recs"]


@app.post("/records", summary="새 기록을 넣고 그 사람의 프록시를 깨움")
def post_records(body: RecordsIn, db=Depends(get_db)):
    busy(db)
    b = store.board(db)
    for r in body.records:
        if r.who not in b.people:
            raise HTTPException(404, f"없는 사람: {r.who}")
    store.snap(db)
    workflow.start_records(db, [r.model_dump() for r in body.records], body.auto_confirm,negotiation_mode=body.negotiation_mode)
    return store.state_json(db)


@app.get("/rules", summary="내 규칙 (PM이 정함) 과 허락한 예외")
def get_rules(db=Depends(get_db)):
    s = store.state_json(db)
    return {"rules": s["rules"], "pref": s["pref"], "granted": s["granted"]}


@app.put("/rules/pref", summary="받을 사람이 여럿이면: 빨리 끝나는 쪽 | 배우고 싶은 사람")
def put_pref(body: PrefIn, db=Depends(get_db)):
    db.get(Rule, "pref").value = {"choice": body.choice}
    return {"pref": body.choice}


@app.put("/rules/rounds", summary="프록시끼리 몇 라운드까지 주고받게 할지 (1 ~ 50)")
def put_rounds(body: RoundsIn, db=Depends(get_db)):
    if not 1 <= body.max <= 50:
        raise HTTPException(422, "라운드는 1 ~ 50")
    r = db.get(Rule, "rounds")
    r.value, r.label = {"max": body.max}, f"프록시끼리 {body.max}라운드까지"
    return {"max": body.max}


@app.get("/cards", summary="위임 카드: 사람마다 프록시에게 맡긴 한도")
def get_cards(db=Depends(get_db)):
    return store.state_json(db)["cards"]


@app.put("/people/{pid}/card", summary="위임 카드 고치기. 보낸 칸만 바뀜")
def put_card(pid: str, body: CardIn, db=Depends(get_db)):
    if pid not in store.board(db).people:
        raise HTTPException(404, "없는 사람")
    c = store.card(db, pid)
    if body.auto_days is not None:
        if not 0 <= body.auto_days <= 5:
            raise HTTPException(422, "auto_days 는 0 ~ 5")
        c.auto_days = round(body.auto_days * 2) / 2
    if body.refuse_tags is not None:
        c.refuse_tags = body.refuse_tags
    if body.gives_help is not None:
        c.gives_help = body.gives_help
    if body.note is not None:
        if body.note != c.note:
            c.policy = {**(c.policy or {}), "needs_review": True}
        c.note = body.note
    if body.policy is not None:
        if not body.policy.approved or body.policy.source_note != c.note:
            raise HTTPException(422, "메모 원문과 일치하는 해석을 사람이 승인해야 합니다")
        if body.policy.questions:
            raise HTTPException(422, "불명확한 질문을 해결한 뒤 승인하세요")
        c.policy = body.policy.model_dump()
    if body.wait_days is not None:
        if not 0 <= body.wait_days <= 5:
            raise HTTPException(422, "wait_days 는 0 ~ 5")
        c.wait_days = round(body.wait_days * 2) / 2
    if body.model is not None:
        c.model = body.model.strip() or None
    return store.state_json(db)


class InterpretIn(BaseModel):
    note: str
    week_start: date = date(2026,11,16)

    @field_validator("week_start")
    @classmethod
    def monday(cls,value):
        if value.weekday()!=0:
            raise ValueError("week_start는 월요일이어야 함")
        return value

@app.post("/people/{pid}/card/interpret", summary="자연어 위임 카드의 해석 초안 (권한·일정에는 아직 미적용)")
def interpret_card(pid: str, body: InterpretIn, db=Depends(get_db)):
    b=store.board(db)
    if pid not in b.people:
        raise HTTPException(404,"없는 사람")
    from .llm import get_llm
    result=get_llm().interpret_card(b.people[pid],body.note,body.week_start.isoformat(),store.card(db,pid).model)
    return {"draft":result.model_dump(),"applied":False,"review_required":True}

class ContextIn(BaseModel):
    context: dict

@app.patch("/tasks/{tid}/context", summary="업무 목적·산출물·분리 경계·의존성 입력")
def update_context(tid: str, body: ContextIn, db=Depends(get_db)):
    task=db.get(Task,tid)
    if task is None:
        raise HTTPException(404,"없는 일")
    task.context=body.context
    return {"id":tid,"context":task.context}

class SplitHintIn(BaseModel):
    days: FiniteFloat=Field(default=.5,gt=0,multiple_of=.5)

@app.post("/tasks/{tid}/analyze-split", summary="맥락을 읽고 업무 분리 가능성·방법을 판단 (배정 미변경)")
def analyze_split(tid: str, body: SplitHintIn=SplitHintIn(), db=Depends(get_db)):
    b=store.board(db)
    if tid not in b.tasks:
        raise HTTPException(404,"없는 일")
    t=b.tasks[tid]
    if t.cut or t.kind in ("done","milestone","prop"):
        raise HTTPException(409,"판단할 수 없는 작업 상태")
    from .llm import get_llm, LiveLLM
    llm=get_llm();llm.last_split_decision={}
    before=getattr(llm,"failures",0)
    split=llm.split(b.people[t.who],t,body.days,store.card(db,t.who).model)
    return {"mode":"live" if isinstance(llm,LiveLLM) else "mock", "split":split.model_dump() if split else None,
            "decision":getattr(llm,"last_split_decision",{}),"failures":getattr(llm,"failures",0)-before,"applied":False}

@app.get("/confirmations", summary="팀원 확인. status=pending 이면 아직 사람이 누르지 않은 것")
def get_confirmations(who: str | None = None, status: str | None = None, db=Depends(get_db)):
    q = select(Confirmation).order_by(Confirmation.id)
    if who:
        q = q.where(Confirmation.who == who)
    if status:
        q = q.where(Confirmation.status == status)
    return [store.confirm_json(c) for c in db.scalars(q)]


@app.post("/confirmations/{cid}", summary="팀원이 프록시의 가약속을 확인 (ok=false 면 거절)")
def post_confirm(cid: int, request: Request, body: ConfirmIn = ConfirmIn(), db=Depends(get_db)):
    confirmation=db.get(Confirmation,cid)
    if not confirmation:raise HTTPException(404,'없는 본인 확인')
    viewer.owner(request,confirmation.who,allow_pm=False)
    try:
        workflow.confirm(db, cid, body.ok)
    except ValueError as e:
        bad(e)
    return store.state_json(db)


# ── 시스템 화면: 판 ───────────────────────────────────────────────────
@app.get("/board", summary="이번 주 판: 사람 · 일 · Handoff 화살표")
def get_board(db=Depends(get_db)):
    s = store.state_json(db)
    return {k: s[k] for k in ("now", "now_label", "deadline_label", "people", "tasks", "hand", "gate")}


@app.get("/log", summary="오간 말. hid 를 주면 그 Handoff 것만")
def get_log(hid: str | None = None, db=Depends(get_db)):
    q = select(Message).order_by(Message.id)
    if hid:
        q = q.where(Message.hid == hid)
    return [store.msg_json(m) for m in db.scalars(q)]


@app.get("/tasks/{tid}", summary="일 자세히: 기간 · 견적 근거 · 받는 것 · 넘기는 것")
def get_task(tid: str, db=Depends(get_db)):
    s = store.state_json(db)
    if tid not in s["tasks"] or s["tasks"][tid]["cut"]:
        raise HTTPException(404, "없거나 빠진 일")
    live = {k: h for k, h in s["hand"].items() if h["state"] != "cut"}
    return {**s["tasks"][tid], "ins": [h for h in live.values() if h["to"] == tid],
            "outs": [h for h in live.values() if h["from"] == tid]}


@app.get("/tasks/{tid}/bids", summary="배정판: 이 일을 옮기면 누가 며칠에 받을 수 있나 (판은 그대로)")
def get_task_bids(tid: str, db=Depends(get_db)):
    if tid not in store.board(db).tasks:
        raise HTTPException(404, "없는 일")
    if store.board(db).tasks[tid].kind == "milestone":
        raise HTTPException(409, "완료 대기점은 옮길 수 없음")
    out = workflow.move_bids(db, tid)
    db.rollback()
    return out


@app.post("/tasks/{tid}/move", summary="PM이 일을 옮김: 사람 id · next · cut")
def post_move(tid: str, body: MoveIn, db=Depends(get_db)):
    busy(db)
    try:
        workflow.move(db, tid, body.dest, body.auto_confirm)
    except ValueError as e:
        bad(e)
    return store.state_json(db)


# Explicit proposals: the engine validates the whole bundle; no auto-generated swaps.
class TransferIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task: str
    to: str
    amount: FiniteFloat | None = Field(default=None, gt=0, multiple_of=0.5)

class BundleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transfers: list[TransferIn] = Field(min_length=1, max_length=32)

@app.post("/bundles/preview", summary="여러 이동의 전체 일정·권한 미리 보기 (변경 없음)")
def bundle_preview(body: BundleIn, db=Depends(get_db)):
    try:
        _, pv = bundles.plan(db, [x.model_dump() for x in body.transfers])
        return pv
    except ValueError as e:
        bad(e)

@app.post("/bundles", summary="여러 이동을 묶어 제안하고 당사자 동의 대기")
def bundle_propose(body: BundleIn, db=Depends(get_db)):
    try:
        return bundles.view(bundles.propose(db, [x.model_dump() for x in body.transfers]))
    except ValueError as e:
        bad(e)

@app.get("/bundles/{bid}", summary="묶음의 동의 대기·전체 확정·취소 상태")
def bundle_get(bid: int, db=Depends(get_db)):
    run = db.get(Run, bid)
    if not run or run.kind != "bundle":
        raise HTTPException(404, "없는 묶음")
    return bundles.view(run)

@app.post("/bundles/{bid}/cancel", summary="대기 중인 묶음 전체 취소 (배정 변경 없음)")
def bundle_cancel(bid: int, db=Depends(get_db)):
    run = db.get(Run, bid)
    if not run or run.kind != "bundle":
        raise HTTPException(404, "없는 묶음")
    if run.status != "waiting_confirm":
        raise HTTPException(409, "이미 끝난 묶음")
    return bundles.view(bundles.cancel(db, run, "제안자가 전체 취소함"))


# ── 출력 화면: Handoffs ───────────────────────────────────────────────
FILTERS = {"all": None, "watch": ["risk", "prop"], "live": ["ok", "agreed"], "done": ["done"]}


@app.get("/handoffs", summary="Handoff 목록. filter = all | watch(주의) | live(진행) | done(끝)")
def get_handoffs(filter: Literal["all", "watch", "live", "done"] = "all", db=Depends(get_db)):
    b = store.board(db)
    hive.schedule(b)
    rows = [store.hand_json(db, b, h) for h in b.hands.values()]
    rows = [r for r in rows if r["state"] != "cut"]
    counts = {k: sum(1 for r in rows if not v or r["state"] in v) for k, v in FILTERS.items()}
    keep = FILTERS[filter]
    s = store.state_json(db)
    return {"items": [r for r in rows if not keep or r["state"] in keep], "counts": counts, "stats": s["stats"]}


@app.get("/handoffs/{hid}", summary="Handoff 자세히: 약속 · 예상 · 앞뒤 단계 · 바뀐 기록 · 오간 말 · PM 확인")
def get_handoff(hid: str, db=Depends(get_db)):
    b = store.board(db)
    hive.schedule(b)
    if hid not in b.hands:
        raise HTTPException(404, "없는 Handoff")
    return store.hand_json(db, b, b.hands[hid], detail=True)


@app.post("/handoffs/{hid}/reagree", summary="PM이 늦어질 Handoff의 약속을 예상 시각으로 다시 정함")
def post_reagree(hid: str, body: AutoIn = AutoIn(auto_confirm=False), db=Depends(get_db)):
    busy(db, pm_may_reagree=hid)
    try:
        workflow.reagree(db, hid, body.auto_confirm)
    except ValueError as e:
        bad(e)
    return store.state_json(db)


@app.get("/negotiations", summary="협상 목록 (기록 한 묶음이 한 건)")
def get_negotiations(db=Depends(get_db)):
    return [store.negotiation_json(db, r, detail=False) for r in db.scalars(select(Run).where(Run.kind == "record").order_by(Run.id))]


@app.get("/negotiations/{rid}", summary="협상 한 건: 제안 · 프록시들의 답 · 라운드별 오간 말 · 기다리는 것")
def get_negotiation(rid: int, db=Depends(get_db)):
    r = db.get(Run, rid)
    if not r or r.kind != "record":
        raise HTTPException(404, "없는 협상")
    return store.negotiation_json(db, r)


@app.post("/negotiations/{rid}/retry", summary="라운드를 늘린 뒤 공개 기록을 유지하며 협상 재개")
def retry_negotiation(rid: int, body: AutoIn = AutoIn(), db=Depends(get_db)):
    try:
        workflow.retry_negotiation(db,rid,body.auto_confirm)
    except ValueError as exc:
        bad(exc)
    return store.state_json(db)


@app.get("/asks", summary="PM 확인 (규칙 안에서 못 푼 것)")
def get_asks(open: bool | None = None, db=Depends(get_db)):
    q = select(Ask).order_by(Ask.id)
    if open is not None:
        q = q.where(Ask.open.is_(open))
    return [store.ask_json(a,db) for a in db.scalars(q)]


@app.post("/asks/{aid}/grant", summary="PM이 규칙 하나를 허락. key 또는 index 로 고름")
def post_grant(aid: int, body: GrantIn, db=Depends(get_db)):
    a = db.get(Ask, aid)
    if not a:
        raise HTTPException(404, "없는 PM 확인")
    key = body.key
    if key is None and body.index is not None and 0 <= body.index < len(a.grants):
        key = a.grants[body.index]["key"]
    try:
        workflow.grant(db, aid, key or "")
    except ValueError as e:
        bad(e)
    return store.state_json(db)


@app.post("/asks/{aid}/reject", summary="PM이 선택지를 이유와 함께 거절. 프록시들이 다시 협상함")
def post_reject(aid: int, body: RejectIn, db=Depends(get_db)):
    if not db.get(Ask, aid):
        raise HTTPException(404, "없는 PM 확인")
    try:
        workflow.reject(db, aid, body.reason, body.keys)
    except ValueError as e:
        bad(e)
    return store.state_json(db)


@app.get("/workflow/progress", summary="실행 중인 공개 처리 단계 (로컬 서버)")
def get_workflow_progress():
    from . import progress
    return progress.read(store.DEMO)


@app.get("/llm/usage", summary="Live LLM 토큰 사용량(이 서버 실행 동안)과 OpenRouter 키의 남은 크레딧")
def get_llm_usage():
    from . import usage
    from .llm import runtime_mode, get_llm
    mode = runtime_mode()
    try:
        model = getattr(get_llm(), "model", None) if mode == "live" else None
    except RuntimeError:      # live 인데 키가 없음: 크레딧 조회도 None 으로 보인다
        model = None
    return usage.snapshot(mode, model)


@app.post("/llm/usage/reset", summary="토큰 사용량 집계를 0부터 다시 셈 (크레딧은 그대로)")
def reset_llm_usage():
    from . import usage
    usage.reset()
    return {"ok": True}


@app.get("/demos", summary="고를 수 있는 데모와 지금 데모")
def get_demos():
    return {"current": store.DEMO, "all": store.service_demos(), "catalog": store.demo_catalog()}


@app.get("/demos/{demo}/scenario", response_class=PlainTextResponse, summary="데모의 초기 보드·위임카드·Task 상세 설명")
def demo_scenario(demo: str):
    entry = next((d for d in store.demo_catalog(include_archived=True) if d['id'] == demo), None)
    if not entry:
        raise HTTPException(404, "없는 데모")
    path = store.ROOT / 'docs' / 'DEMOS.md'
    if not path.is_file():
        raise HTTPException(404, "시나리오 문서가 없음")
    text = path.read_text(encoding='utf-8')
    start, end = f'<!-- DEMO_START:{demo} -->', f'<!-- DEMO_END:{demo} -->'
    if start not in text or end not in text:
        raise HTTPException(404, "시나리오 문서가 없음")
    return text.split(start, 1)[1].split(end, 1)[0].strip()


@app.get('/demos/{demo}/scenario-data', summary='시나리오 시각화용 초기 보드 (현재 실행 변경 없음)')
def demo_scenario_data(demo: str):
    from .scenarios import initial
    try:return initial(demo)
    except ValueError as exc:raise HTTPException(404,str(exc))


@app.get('/demos/{demo}/board', summary='M4 원본 일정 이미지')
def demo_source_board(demo: str):
    if demo not in store.service_demos():raise HTTPException(404,'없는 시나리오')
    return FileResponse(store.SEED/demo/'board.png',media_type='image/png')


@app.post("/demo/select", summary="다른 데모로 바꾸고 그 데모의 데이터로 다시 채움")
def post_demo_select(body: DemoIn, db=Depends(get_db)):
    try:
        store.use_demo(body.demo)
    except ValueError as e:
        raise HTTPException(404, str(e))
    store.reset(db)
    return store.state_json(db)


# ── 시연 · 되돌리기 ───────────────────────────────────────────────────
@app.post("/demo/advance", summary="시연 버튼: 다음 날 기록 받기 (월→수, 수→목)")
def demo_advance(body: AutoIn = AutoIn(), db=Depends(get_db)):
    busy(db)
    phase = store.meta(db, "phase")
    feed = store.load_yaml("feed.yaml").get(phase)
    if not feed:
        raise HTTPException(409, "더 받을 시연 기록이 없음 (시연 끝)")
    store.snap(db)
    keys=list(store.load_yaml("feed.yaml"))
    store.set_meta(db,"demo_step",dict(index=keys.index(phase)+1,total=len(keys),key=phase,label=feed.get('label',phase)))
    store.set_meta(db, "now", feed["now"])
    store.set_meta(db, "phase", "run")
    store.narr(db, feed["narr"])
    if feed.get("action") == "bundle":
        import os
        if (body.negotiation_mode or os.environ.get('PLANBEE_NEGOTIATION_MODE'))=='candidate_discussion':
            from .candidates import engine as candidates
            board=store.board(db)
            editable=[x['task'] for x in feed['transfers'] if x['task'] in board.tasks and not board.tasks[x['task']].cut
                      and board.tasks[x['task']].kind not in ('done','milestone','prop') and board.tasks[x['task']].d>0]
            if not editable:
                store.hive_say(db,'이 기록의 대상들은 이미 완료·분해되어 새 분담 요청을 시작할 수 없습니다. 미완료 변경이 있으면 PM이 별도 확인해 주세요.')
                store.set_meta(db,'phase',feed['next_phase'])
                return store.state_json(db)
            first=editable[0]
            issue=feed['narr']+' · '+', '.join(f"{x['task']} → {x['to']}" for x in feed['transfers'])
            candidates.start(db,first,issue,phase_after=feed['next_phase'])
            return store.state_json(db)
        try:
            run = bundles.propose(db, feed["transfers"])
        except ValueError as exc:
            bad(exc)
        workflow.patch(run, phase_after=feed["next_phase"])
        if body.auto_confirm:
            for cid in run.ctx.get("waiting_for", []):
                workflow.apply_confirm(db, db.get(Confirmation, cid))
        bundles.resume(db, run)
    else:
        records = feed.get("records") or []
        if not records:
            raise HTTPException(422, "데모 단계에 실행할 기록이 없음")
        workflow.start_records(db, records, body.auto_confirm, phase_after=feed["next_phase"],negotiation_mode=body.negotiation_mode,task_id=feed.get('task'))
    return store.state_json(db)


@app.post("/undo", summary="되돌리기: PM이 마지막으로 정하기 전 상태로")
def post_undo(db=Depends(get_db)):
    if not store.undo(db):
        raise HTTPException(409, "되돌릴 것이 없음")
    return store.state_json(db)


@app.post("/reset", summary="처음부터: 시드 데이터로 다시 채움")
def post_reset(db=Depends(get_db)):
    store.reset(db)
    return store.state_json(db)


# ── 화면 ──────────────────────────────────────────────────────────────
from .candidates.api import install as install_candidates
install_candidates(app, get_db, busy)


@app.get('/', include_in_schema=False)
def frontend():
    return FileResponse(store.ROOT / 'front' / 'Plan Bee Front.html')


app.mount('/front', StaticFiles(directory=store.ROOT / 'front'), name='front')

# web/index.html 을 같은 주소에서 내보낸다. API 경로를 모두 등록한 뒤에 붙여야 가리지 않는다.
if (store.ROOT / "web").exists():
    app.mount("/", StaticFiles(directory=store.ROOT / "web", html=True), name="web")
