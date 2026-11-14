"""HTTP API. 프로토타입의 세 화면(입력 · 판 · Handoffs)이 쓰는 것만 있다.

실행:  uvicorn app.api:app --reload      문서:  http://localhost:8000/docs
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import select

from . import hive, store, workflow
from .models import Ask, Confirmation, Message, Record, Rule, Run

engine = store.make_engine()
SessionLocal = store.make_session_factory(engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    with SessionLocal() as db:
        if store.is_empty(db):
            store.reset(db)
            db.commit()
    yield


app = FastAPI(title="Plan Bee · Handoffs API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def get_db():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def bad(e: Exception):
    raise HTTPException(status_code=409, detail=str(e))


def busy(db):
    """협상이 사람이나 PM을 기다리는 동안에는 새 기록 · PM 조작을 받지 않는다 (프로토타입의 RUN 잠금)."""
    r = db.scalars(select(Run).where(Run.status.in_(["waiting_confirm", "waiting_pm"]))).first()
    if r:
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


class AutoIn(BaseModel):
    auto_confirm: bool = True


class ConfirmIn(BaseModel):
    ok: bool = True


class GrantIn(BaseModel):
    key: str | None = None
    index: int | None = None


class PrefIn(BaseModel):
    choice: Literal["fast", "learn"]


class CardIn(BaseModel):
    auto_days: float | None = None       # 이 일수까지는 프록시가 알아서 수락 (0 ~ 5, 0.5 단위)
    refuse_tags: list[str] | None = None
    gives_help: bool | None = None
    note: str | None = None


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
    workflow.start_records(db, [r.model_dump() for r in body.records], body.auto_confirm)
    return store.state_json(db)


@app.get("/rules", summary="내 규칙 (PM이 정함) 과 허락한 예외")
def get_rules(db=Depends(get_db)):
    s = store.state_json(db)
    return {"rules": s["rules"], "pref": s["pref"], "granted": s["granted"]}


@app.put("/rules/pref", summary="받을 사람이 여럿이면: 빨리 끝나는 쪽 | 배우고 싶은 사람")
def put_pref(body: PrefIn, db=Depends(get_db)):
    db.get(Rule, "pref").value = {"choice": body.choice}
    return {"pref": body.choice}


@app.put("/rules/rounds", summary="프록시끼리 몇 라운드까지 주고받게 할지 (1 ~ 5)")
def put_rounds(body: RoundsIn, db=Depends(get_db)):
    if not 1 <= body.max <= 5:
        raise HTTPException(422, "라운드는 1 ~ 5")
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
        c.note = body.note
    return store.state_json(db)


@app.get("/confirmations", summary="팀원 확인. status=pending 이면 아직 사람이 누르지 않은 것")
def get_confirmations(who: str | None = None, status: str | None = None, db=Depends(get_db)):
    q = select(Confirmation).order_by(Confirmation.id)
    if who:
        q = q.where(Confirmation.who == who)
    if status:
        q = q.where(Confirmation.status == status)
    return [store.confirm_json(c) for c in db.scalars(q)]


@app.post("/confirmations/{cid}", summary="팀원이 프록시의 가약속을 확인 (ok=false 면 거절)")
def post_confirm(cid: int, body: ConfirmIn = ConfirmIn(), db=Depends(get_db)):
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
    busy(db)
    try:
        workflow.reagree(db, hid, body.auto_confirm)
    except ValueError as e:
        bad(e)
    return store.state_json(db)


@app.get("/asks", summary="PM 확인 (규칙 안에서 못 푼 것)")
def get_asks(open: bool | None = None, db=Depends(get_db)):
    q = select(Ask).order_by(Ask.id)
    if open is not None:
        q = q.where(Ask.open.is_(open))
    return [store.ask_json(a) for a in db.scalars(q)]


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


# ── 시연 · 되돌리기 ───────────────────────────────────────────────────
@app.post("/demo/advance", summary="시연 버튼: 다음 날 기록 받기 (월→수, 수→목)")
def demo_advance(body: AutoIn = AutoIn(), db=Depends(get_db)):
    busy(db)
    phase = store.meta(db, "phase")
    feed = store.load_yaml("feed.yaml").get(phase)
    if not feed:
        raise HTTPException(409, "더 받을 시연 기록이 없음 (시연 끝)")
    store.snap(db)
    store.set_meta(db, "now", feed["now"])
    store.set_meta(db, "phase", "run")
    store.narr(db, feed["narr"])
    workflow.start_records(db, feed["records"], body.auto_confirm, phase_after=feed["next_phase"])
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
# web/index.html 을 같은 주소에서 내보낸다. API 경로를 모두 등록한 뒤에 붙여야 가리지 않는다.
if (store.ROOT / "web").exists():
    app.mount("/", StaticFiles(directory=store.ROOT / "web", html=True), name="web")
