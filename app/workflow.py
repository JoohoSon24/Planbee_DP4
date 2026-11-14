"""협상 워크플로. LLM(프록시)이 쓰고, Hive 코드가 판단하고, LangGraph 가 단계를 돈다.

한 건의 진행 상태는 run 표에 있다. 사람 확인이나 PM 허락을 기다릴 때는 그래프가 끝나고
(status = waiting_*), 답이 오면 resume() 이 같은 run 을 멈춘 단계부터 다시 돌린다.
상태가 DB에 있어서 서버를 껐다 켜도 이어지고, 되돌리기도 DB 스냅샷 하나로 끝난다.

기록 한 묶음이 지나가는 길:
  ingest → help → bids ⇄ tally → (person) → propose → confirm → commit → (reconfirm) → finish
                    ↑      └→ ask(PM 대기) → granted ─┬→ bids (라운드 새로)
                    └──────────────────────────────────┘└→ cutconfirm → finish

  bids  한 번이 한 라운드. 1라운드는 조각을 맡아 달라고 묻고, 다음 라운드는 조건부 답의 조건을 상대에게 확인한다.
  tally 확인할 조건이 남고 라운드가 남았으면 bids 로, 받을 사람이 있으면 고르고, 없으면 ask 로.
  person 고른 사람의 일수가 위임 카드 한도를 넘으면 본인 답을 기다린다.
"""
from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import hive
from .hive import num, when
from .llm import Piece, Reply, Split, default_bid_days, get_llm
from .models import Ask, Confirmation, Grant, Handoff, HandoffEvent, Message, Resolution, Run, Task
from .store import (F, N, TK, add_record, board, bump_decisions, card, hist, hive_say, meta, narr, next_id,
                    next_oi, pm_say, rule, say, set_meta, snap, stamp)

PREF_LABEL = {"fast": "빨리 끝나는 쪽", "learn": "배우고 싶은 사람"}


josa, _has_final = hive.josa, hive.has_final


def count_kr(n: int) -> str:
    return {2: "둘", 3: "셋", 4: "넷"}.get(n, f"{n}명")


def patch(run: Run, **kw) -> None:
    run.ctx = {**run.ctx, **kw}


# ── 공통 동작 ─────────────────────────────────────────────────────────
def announce(db: Session, b: hive.Board, before: dict, run_id=None) -> None:
    """상태가 바뀐 Handoff 를 주는 쪽 프록시가 받는 쪽에 알린다."""
    after = hive.states(b)
    for hid, st in after.items():
        h = b.hands[hid]
        a, c = b.tasks[h.from_task], b.tasks[h.to_task]
        was = before.get(hid)
        if st == "risk" and was != "risk":
            h.basis = h.basis or "앞 일정이 밀림"
            hist(db, hid, "proxy", f"예상 {when(h.t)} → {when(hive.pred(b, h))} · At risk", who=a.who)
            say(db, a.who, "알림", [TK(h.title), N(f"{when(h.t)} → {when(hive.pred(b, h))}")], to=c.who, hid=hid, run_id=run_id)
        elif was == "risk" and st not in ("risk", "cut"):
            hist(db, hid, "proxy", f"다시 제때 → {hive.STATE_NAME[st]}", who=a.who)
            say(db, a.who, "약속", [TK(h.title), N(when(h.t))], to=c.who, hid=hid, run_id=run_id)
        elif st == "cut" and was != "cut":
            hist(db, hid, "hive", "주는 일이나 받는 일이 빠져서 없어짐")


def ask_person(db, run, who, prompt, text, hid, role) -> Confirmation:
    c = Confirmation(who=who, prompt=prompt, text=text, hid=hid, role=role, run_id=run.id)
    db.add(c)
    db.flush()
    return c


def apply_confirm(db: Session, c: Confirmation, ok: bool = True) -> None:
    c.status = "confirmed" if ok else "rejected"
    c.t = stamp(db)
    db.add(Message(k="person", who=c.who, text=c.text if ok else f"{c.prompt} · 거절", hid=c.hid, run_id=c.run_id, t=c.t))
    db.flush()


def wait_confirms(db: Session, run: Run):
    """이 run 이 기다리는 사람 확인을 살핀다. auto_confirm 이면 사람 대신 눌러 준다(시연용)."""
    cs = list(db.scalars(select(Confirmation).where(Confirmation.run_id == run.id).order_by(Confirmation.id)))
    open_ids = set(run.ctx.get("waiting_for", []))
    cs = [c for c in cs if c.id in open_ids]
    if run.auto_confirm:
        for c in cs:
            if c.status == "pending":
                apply_confirm(db, c)
    rejected = [c for c in cs if c.status == "rejected"]
    if rejected:
        return "rejected", rejected[0]
    if any(c.status == "pending" for c in cs):
        run.status = "waiting_confirm"
        return "pending", None
    run.status = "running"
    return "ok", None


def done(db, run, text=None) -> None:
    run.step, run.status = "done", "done"
    if text:
        narr(db, text)
    if run.ctx.get("phase_after"):
        set_meta(db, "phase", run.ctx["phase_after"])


# ── 단계: 기록 → 견적 ─────────────────────────────────────────────────
def n_ingest(db: Session, run: Run) -> None:
    b = board(db)
    ctx = run.ctx
    person = b.people[ctx["who"]]
    mine = [t for t in b.tasks.values() if t.who == person.id and not t.cut and t.kind != "done"]
    ans = get_llm().reestimate(person, ctx["records"], mine)
    if not ans or ans.task not in b.tasks or abs(ans.days - b.tasks[ans.task].d) < hive.EPS:
        return done(db, run, "새 기록을 읽음 · 견적은 그대로")
    t = b.tasks[ans.task]
    outs = [h for h in b.hands.values() if h.from_task == t.id and hive.h_state(b, h) != "cut"]
    before = hive.states(b)
    say(db, person.id, "견적", [TK(t.title), N(f"{num(t.d)}일 → {num(ans.days)}일")], basis=ans.basis,
        hid=outs[0].id if outs else None, run_id=run.id)
    t.d = ans.days
    for h in outs:
        h.basis = ans.basis
    hive.schedule(b)
    narr(db, "Handoff를 따라 영향이 번지는 중")
    announce(db, b, before, run.id)
    late = [h for h in outs if hive.h_state(b, h) == "risk"]
    if not late:
        return done(db, run, "견적이 바뀌었지만 약속은 그대로 지킴")
    patch(run, task=t.id, hid=late[0].id, round=0, excluded=[], replies=None, refused=[])
    run.step = "help"


# ── 단계: 도움 요청을 열고, 담당 프록시가 떼어 낼 조각을 정함 ─────────
def n_help(db: Session, run: Run) -> None:
    b = board(db)
    h, t = b.hands[run.ctx["hid"]], b.tasks[run.ctx["task"]]
    owner = b.people[t.who]
    narr(db, f"Hive가 도움 요청을 엶 · 떼어 낼 조각은 {owner.name}의 프록시가 정함")
    hive_say(db, f"도움 요청 · {h.title} · {when(h.t)}까지 · {t.role}", hid=h.id, run_id=run.id)
    hist(db, h.id, "hive", "도움 요청 열림")
    split = get_llm().split(owner, t, hive.pred(b, h) - h.t)
    if not split:
        patch(run, no_split=True)
        run.step = "ask"
        return
    p = split.piece
    say(db, owner.id, "조건", [TK(p.title), N(f"{num(p.days)}일"), F(p.reason)], basis=p.basis, hid=h.id, run_id=run.id)
    patch(run, split=split.model_dump())
    run.step = "bids"


# ── 단계: 프록시들에게 묻고, 프록시가 답 유형을 고름 ─────────────────
def _mentor(b, t, piece, pid, owner_id):
    """그 조각을 가장 많이 해 본 같은 역할 사람 (자기와 담당 제외). 도움을 청할 상대."""
    return max((x for x in b.people.values() if x.role == t.role and x.id not in (pid, owner_id)),
               key=lambda x: (x.rec or {}).get(piece.tag, 0), default=None)


def _ask_proxy(db, run, b, p, piece, owner_id, t, hid, helper_minutes=None) -> Reply:
    """프록시 하나에게 묻는다. 답이 규칙에 어긋나면 이유를 붙여 한 번 돌려보내고(라운드는 쓰지 않음), 또 어긋나면 거절로 적는다."""
    llm, cd = get_llm(), card(db, p.id)
    c = {"load": hive.load_of(b, p.id), "cap": b.cap, "deferrable": hive.deferrable(b, p.id), "violation": None,
         "default_days": default_bid_days(b, piece, p.id, owner_id), "mentor": _mentor(b, t, piece, p.id, owner_id)}
    v = None
    for _ in range(2):
        ans = llm.help_reply(p, cd, helper_minutes, c) if helper_minutes else llm.reply(p, cd, piece, c)
        fixed, v = hive.check_reply(b, p.id, ans.model_dump(), piece.days, c["default_days"], owner_id, bool(helper_minutes))
        if not v:
            return Reply(**fixed)
        hive_say(db, f"반려 · {p.name}의 프록시 답 {ans.type} · {v['code']}: {v['text']} · 라운드는 쓰지 않음", hid=hid, run_id=run.id)
        c["violation"] = v
    return Reply(type="REJECT", reason=f"규칙 확인을 통과하지 못함 ({v['code']})")


def n_bids(db: Session, run: Run) -> None:
    b = board(db)
    ctx = run.ctx
    h, t = b.hands[ctx["hid"]], b.tasks[ctx["task"]]
    piece = Piece(**ctx["split"]["piece"])
    owner = b.people[t.who]
    rnd = ctx.get("round", 0) + 1
    today = hive.DAY[min(4, int(b.now))]
    replies = ctx.get("replies")
    if replies is None:
        # 첫 물음: 같은 역할의 모든 프록시에게
        cands = sorted((p for p in b.people.values() if p.role == t.role and p.id != owner.id and p.id not in ctx["excluded"]),
                       key=lambda p: (-(p.rec or {}).get(piece.tag, 0), p.oi))
        if not cands:
            patch(run, replies=[])
            run.step = "ask"
            return
        hive_say(db, f"{rnd}라운드 · 물어볼 대상 · " + ", ".join(f"{p.name}의 프록시" for p in cands) + f" ({t.role})", hid=h.id, run_id=run.id)
        replies = []
        for p in cands:
            if not ctx.get("quiet"):
                say(db, owner.id, "질문", [TK(piece.title), N(f"{num(piece.days)}일"), F(f"{when(h.t)}까지 돼요?")], to=p.id, hid=h.id, run_id=run.id)
            r = _ask_proxy(db, run, b, p, piece, owner.id, t, h.id)
            wish = piece.tag in (p.wants or [])
            e = {"who": p.id, "type": r.type, "days": r.days, "cond": r.cond.model_dump() if r.cond else None,
                 "reason": r.reason, "say": r.say, "wish": wish, "help": None, "help_reason": "", "help_task": None, "approved": False}
            fields = [TK(piece.title)] + ([N(f"{num(r.days)}일")] if r.days else [])
            basis, pref = hive.tag_line(p, piece.tag), (f"바라던 일 · {piece.tag}" if wish else "")
            if r.type == "ACCEPT":
                say(db, p.id, "견적", fields + [F("수락")], to=owner.id, basis=basis, pref=pref, say=r.say, hid=h.id, run_id=run.id)
            elif r.type == "NEEDS_INPUT":
                say(db, p.id, "견적", fields + [F("본인 확인 필요")], to=owner.id, basis=f"{basis} · {r.reason}", pref=pref, say=r.say, hid=h.id, run_id=run.id)
            elif r.type == "REJECT":
                say(db, p.id, "견적", [TK(piece.title), F("거절")], to=owner.id, basis=r.reason, hid=h.id, run_id=run.id)
            elif r.cond.kind == "help":
                say(db, p.id, "견적", fields + [F("조건부")], to=owner.id, basis=basis, pref=pref, say=r.say or r.reason, hid=h.id, run_id=run.id)
            else:
                say(db, p.id, "조건", fields + [F(r.reason)], to=owner.id,
                    basis=f"{basis} · 금까지 {num(hive.load_of(b, p.id))}/{num(b.cap)}", hid=h.id, run_id=run.id)
            replies.append(e)
    else:
        # 다음 라운드: 조건부 답의 조건을 상대 프록시에게 확인
        todo = [e for e in replies if e["type"] == "COUNTER" and e["cond"]["kind"] == "help" and e["help"] is None
                and e["who"] not in ctx["excluded"]]
        hive_say(db, f"{rnd}라운드 · 조건 확인 · " + ", ".join(
            f"{b.people[e['who']].name} → {b.people[e['cond']['who']].name} (도움 {e['cond']['minutes']}분)" for e in todo), hid=h.id, run_id=run.id)
        for e in todo:
            cand, helper = b.people[e["who"]], b.people[e["cond"]["who"]]
            mins = e["cond"]["minutes"]
            say(db, cand.id, "질문", [F(f"도움 {mins}분"), F(f"{today} 오후 돼요?")], to=helper.id, hid=h.id, run_id=run.id)
            r = _ask_proxy(db, run, b, helper, piece, owner.id, t, h.id, helper_minutes=mins)
            if r.type in ("ACCEPT", "NEEDS_INPUT"):
                e["help"] = "ok"
                say(db, helper.id, "약속", [F(f"도움 {mins}분"), N(f"{today} 오후")], to=cand.id, pref=r.say, hid=h.id, run_id=run.id)
            elif r.type == "COUNTER":
                e["help"], e["help_reason"], e["help_task"] = "defer", r.reason, r.cond.task
                say(db, helper.id, "조건", [F(f"도움 {mins}분"), F(r.reason)], to=cand.id,
                    basis=f"금까지 {num(hive.load_of(b, helper.id))}/{num(b.cap)}", hid=h.id, run_id=run.id)
            else:
                e["help"], e["help_reason"] = "no", r.reason
                say(db, helper.id, "견적", [F(f"도움 {mins}분"), F("거절")], to=cand.id, basis=r.reason, hid=h.id, run_id=run.id)
    patch(run, replies=replies, round=rnd)
    run.step = "tally"


# ── 단계: Hive 가 답을 모아 다음을 정함 ───────────────────────────────
def n_tally(db: Session, run: Run) -> None:
    b = board(db)
    ctx = run.ctx
    max_rounds = rule(db, "rounds")["max"]
    replies = [e for e in ctx["replies"] if e["who"] not in ctx["excluded"]]
    open_help = [e for e in replies if e["type"] == "COUNTER" and e["cond"]["kind"] == "help" and e["help"] is None]
    if open_help and ctx["round"] < max_rounds:
        run.step = "bids"          # 확인할 조건이 남았고 라운드가 남았으면 한 번 더
        return
    if open_help:
        hive_say(db, f"{max_rounds}라운드 안에 조건을 다 확인하지 못함", hid=ctx["hid"], run_id=run.id)
    ok = [e for e in replies if e["type"] in ("ACCEPT", "NEEDS_INPUT") or (e["type"] == "COUNTER" and e["help"] == "ok")]
    if not ok:
        run.step = "ask"
        return
    pref = rule(db, "pref")["choice"]
    ok.sort(key=(lambda e: (not e["wish"], e["days"])) if pref == "learn" else (lambda e: e["days"]))
    chosen = ok[0]
    taker = b.people[chosen["who"]]
    if len(ok) > 1:
        hive_say(db, f"받을 사람이 {count_kr(len(ok))} · 내 규칙 '{PREF_LABEL[pref]}' → {taker.name}의 프록시", hid=ctx["hid"], run_id=run.id)
    patch(run, chosen=chosen, by_pref=pref if len(ok) > 1 else ctx.get("by_pref"))
    limit = card(db, taker.id).auto_days
    if chosen["days"] > limit + hive.EPS and not chosen["approved"]:
        # 권한은 코드가 지킨다: 카드 한도를 넘으면 프록시가 뭐라고 답했든 본인에게 묻는다
        piece = Piece(**ctx["split"]["piece"])
        hive_say(db, f"권한 확인 · {taker.name}의 카드 한도 {num(limit)}일 < {num(chosen['days'])}일 → 본인 확인", hid=ctx["hid"], run_id=run.id)
        c = ask_person(db, run, taker.id, f"{piece.title} {num(chosen['days'])}일 · 내 한도({num(limit)}일)를 넘어요. 맡아도 될까요?",
                       f"{piece.title} {num(chosen['days'])}일 맡을게요 · 확인", ctx["hid"], "taker")
        narr(db, f"{taker.name}에게 확인 알림 · 사람 차례")
        patch(run, waiting_for=[c.id])
        run.step = "person"
        return
    run.step = "propose"


def n_person(db: Session, run: Run) -> None:
    """한도를 넘는 일을 맡기 전에 본인 답을 기다린다."""
    res, c = wait_confirms(db, run)
    if res == "pending":
        return
    ctx = run.ctx
    who = ctx["chosen"]["who"]
    run.status = "running"
    if res == "rejected":
        hive_say(db, f"{board(db).people[who].name} 본인이 거절 · 다른 답을 다시 봄", hid=ctx["hid"], run_id=run.id)
        patch(run, excluded=ctx["excluded"] + [who], refused=ctx.get("refused", []) + [who], waiting_for=[])
        run.step = "tally"
        return
    replies = [dict(e, approved=True) if e["who"] == who else e for e in ctx["replies"]]
    patch(run, replies=replies, chosen=dict(ctx["chosen"], approved=True), waiting_for=[])
    run.step = "propose"


# ── 단계: 가약속을 판에 올리고 규칙 확인 ──────────────────────────────
def n_propose(db: Session, run: Run) -> None:
    b = board(db)
    ctx = run.ctx
    h, t = b.hands[ctx["hid"]], b.tasks[ctx["task"]]
    split, chosen = Split(**ctx["split"]), ctx["chosen"]
    p, taker, owner = split.piece, b.people[chosen["who"]], b.people[t.who]
    target = b.tasks[h.to_task] if split.to == "downstream" else t
    promise = b.now + chosen["days"]
    tid = p.id if p.id and not db.get(Task, p.id) else next_id(db, Task, "piece")
    hid = next_id(db, Handoff, "h")
    db.add(Task(id=tid, who=taker.id, title=p.title, s0=b.now, s=b.now, d=chosen["days"], plan=chosen["days"],
                base=p.days, tag=p.tag, role=t.role, kind="prop", oi=next_oi(db, Task)))
    db.flush()
    db.add(Handoff(id=hid, from_task=tid, to_task=target.id, title=p.title, what=p.what or p.title, t=promise,
                   prop=True, oi=next_oi(db, Handoff)))
    db.flush()
    say(db, taker.id, "약속", [TK(p.title), N(when(promise)), F("가약속")], to=target.who, hid=hid, run_id=run.id)
    hist(db, hid, "proxy", f"가약속 · {when(promise)}", who=taker.id)

    b = board(db)
    hive.schedule(b)
    over = [v for v in hive.gate(b)["violations"] if v["code"] == "OVERLOAD" and v["who"] == taker.id]
    if over:   # 입찰 때 걸렀으니 여기 오면 안 되지만, 확정 전에 한 번 더 막는다
        hive_say(db, "규칙 확인 · " + " · ".join(v["text"] for v in over) + " → 이 사람은 제외", hid=h.id, run_id=run.id)
        _drop_provisional(db, tid, hid)
        patch(run, excluded=ctx["excluded"] + [taker.id])
        run.step = "tally"
        return
    how = "본인이 확인함" if chosen["approved"] else f"카드 한도 {num(card(db, taker.id).auto_days)}일 안이라 프록시가 수락"
    hive_say(db, f"규칙 확인 · 넘침 없음 · 제출일 · 범위 그대로 · {taker.name}: {how} → 담당 확인만", hid=h.id, run_id=run.id)
    c2 = ask_person(db, run, owner.id, f"{josa(p.title, '은', '는')} {taker.name}에게 넘겨도 될까요?",
                    f"{josa(p.title, '은', '는')} {taker.name}에게 · 확인", h.id, "owner")
    narr(db, f"{owner.name}에게 확인 알림 · 사람 차례")
    patch(run, piece_task=tid, piece_hand=hid, waiting_for=[c2.id])
    run.step = "confirm"


def _drop_provisional(db: Session, tid: str, hid: str) -> None:
    for e in db.scalars(select(HandoffEvent).where(HandoffEvent.handoff_id == hid)):
        db.delete(e)
    h = db.get(Handoff, hid)
    if h:
        db.delete(h)
        db.flush()
    t = db.get(Task, tid)
    if t:
        db.delete(t)
        db.flush()


def n_confirm(db: Session, run: Run) -> None:
    res, c = wait_confirms(db, run)
    if res == "pending":
        return
    if res == "ok":
        run.step = "commit"
        return
    b = board(db)
    ctx = run.ctx
    for other in db.scalars(select(Confirmation).where(Confirmation.run_id == run.id, Confirmation.status == "pending")):
        other.status = "withdrawn"
    _drop_provisional(db, ctx["piece_task"], ctx["piece_hand"])
    run.status = "running"
    hive_say(db, f"{b.people[c.who].name} 거절 · 조각을 넘기지 않음", hid=ctx["hid"], run_id=run.id)
    patch(run, owner_refused=True, waiting_for=[], replies=[])
    run.step = "ask"


# ── 단계: 확정 ────────────────────────────────────────────────────────
def n_commit(db: Session, run: Run) -> None:
    b = board(db)
    ctx = run.ctx
    h, t = b.hands[ctx["hid"]], b.tasks[ctx["task"]]
    split, chosen = Split(**ctx["split"]), ctx["chosen"]
    p, taker, owner = split.piece, b.people[chosen["who"]], b.people[t.who]
    piece_task, piece_hand = b.tasks[ctx["piece_task"]], b.hands[ctx["piece_hand"]]
    before = hive.states(b)

    if p.handover:
        say(db, owner.id, "넘김", [TK(p.title), F(p.handover)], to=taker.id, hid=piece_hand.id, run_id=run.id)
    piece_task.kind = "new"
    piece_hand.prop, piece_hand.agreed = False, True
    if chosen["approved"]:
        hist(db, piece_hand.id, "person", f"{taker.name} 확인 → Agreed", who=taker.id)
    else:
        hist(db, piece_hand.id, "proxy", f"{taker.name}의 프록시가 카드 한도 안에서 수락 → Agreed", who=taker.id)

    # 담당에게 남는 일을 다시 나눔
    at = b.now
    for part in split.extra:
        d = part.days or 0.5
        db.add(Task(id=part.id if part.id and not db.get(Task, part.id) else next_id(db, Task, "part"), who=owner.id,
                    title=part.title, s0=at, s=at, d=d, plan=d, base=d, tag=t.tag, role=t.role, oi=next_oi(db, Task)))
        db.flush()
        at += 0.5
    keep_days = (split.keep.days if split.keep and split.keep.days else None) or max(0.5, t.d - p.days)
    t.d = t.plan = t.base = keep_days
    if split.keep:
        t.title = split.keep.title
    if split.extra:
        t.s0 = max(t.s0, at)
    if split.rename_handoff:
        h.title = split.rename_handoff
    h.basis = ""
    hist(db, h.id, "person", f"{owner.name} 확인 · {josa(p.title, '은', '는')} {josa(taker.name, '이', '가')}", who=owner.id)

    b = board(db)
    hive.schedule(b)
    h = b.hands[ctx["hid"]]
    patch(run, before=before, waiting_for=[])
    if hive.h_state(b, h) == "risk":      # 도움을 받아도 늦으면, 받는 사람에게 새 약속을 확인받음
        new_t = hive.pred(b, h)
        receiver = b.people[b.tasks[h.to_task].who]
        h.t, h.agreed = new_t, True
        hist(db, h.id, "proxy", f"약속 다시 정함 · {when(new_t)}", who=owner.id)
        say(db, owner.id, "약속", [TK(h.title), N(when(new_t))], to=receiver.id, say=get_llm().reagree_note(taker),
            hid=h.id, run_id=run.id)
        c = ask_person(db, run, receiver.id, f"{h.title} {when(new_t)}에 받아도 될까요?",
                       f"{h.title} {when(new_t)} 받기 · 확인", h.id, "receiver")
        narr(db, f"{receiver.name}에게 확인 알림 · 사람 차례")
        patch(run, waiting_for=[c.id], reagreed=True)
        run.step = "reconfirm"
        return
    run.step = "finish"


def n_reconfirm(db: Session, run: Run) -> None:
    res, c = wait_confirms(db, run)
    if res == "pending":
        return
    if res == "rejected":
        run.status = "running"
        hive_say(db, "받는 사람이 새 약속을 거절 → PM 확인", hid=run.ctx["hid"], run_id=run.id)
        patch(run, receiver_refused=True, replies=[], waiting_for=[])
        run.step = "ask"
        return
    run.step = "finish"


def n_finish(db: Session, run: Run) -> None:
    b = board(db)
    hive.schedule(b)
    ctx = run.ctx
    h, t = b.hands[ctx["hid"]], b.tasks[ctx["task"]]
    owner = b.people[t.who]
    announce(db, b, ctx.get("before", {}), run.id)
    granted = ctx.get("grant_label")
    if ctx.get("cut_done"):
        body = f"{josa(ctx['cut_note'], '을', '를')} 빼서 {josa(owner.name, '이', '가')} {when(h.t)} 약속을 지킴"
        why = f"PM이 범위를 줄임 · {owner.name} 확인"
    else:
        p, taker = Split(**ctx["split"]).piece, b.people[ctx["chosen"]["who"]]
        body = f"{josa(taker.name, '이', '가')} {p.title} {num(ctx['chosen']['days'])}일을 맡음 · {h.title} {when(hive.pred(b, h))}"
        parts = [f"PM이 허락 · {granted}" if granted else "규칙 안"]
        if ctx.get("by_pref"):
            parts.append(f"받을 사람은 내 규칙 '{PREF_LABEL[ctx['by_pref']]}'")
        parts.append(f"{taker.name} 본인 확인" if ctx["chosen"]["approved"] else f"{taker.name}의 프록시가 카드 한도 안에서 수락")
        parts.append(f"{owner.name} 확인")
        parts.append(f"{ctx['round']}라운드")
        if not granted:
            parts.append("PM 결정 없음")
        why = " · ".join(parts)
    db.add(Resolution(hid=h.id, body=body, why=why))
    done(db, run, "해결됨 · PM은 규칙 하나만 정함" if granted else "해결됨 · PM 결정 없이 당사자 확인으로 끝남")


# ── 단계: 규칙 안에서 못 풀면 PM에게 ──────────────────────────────────
def n_ask(db: Session, run: Run) -> None:
    b = board(db)
    ctx = run.ctx
    h, t = b.hands[ctx["hid"]], b.tasks[ctx["task"]]
    replies = ctx.get("replies") or []
    why, grants, defers = [], [], []
    if ctx.get("no_split"):
        why.append("떼어 낼 수 있는 조각이 없음")
    if ctx.get("owner_refused"):
        why.append("담당이 조각 넘기기를 거절")
    if ctx.get("receiver_refused"):
        why.append("받는 사람이 늦춘 약속을 거절")
    for pid in ctx.get("refused", []):
        why.append(f"{b.people[pid].name}: 본인이 거절")
    for e in replies:      # 이유는 프록시가 쓴 말 그대로
        if e["who"] in ctx.get("refused", []):
            continue
        name = b.people[e["who"]].name
        if e["type"] == "REJECT":
            why.append(f"{name}: {e['reason']}")
        elif e["type"] == "COUNTER" and e["cond"]["kind"] == "defer":
            why.append(f"{name}: {e['reason']}")
            defers.append((e["cond"]["task"], name))
        elif e["type"] == "COUNTER":
            helper = b.people[e["cond"]["who"]].name
            tail = {"defer": f" → {helper}: {e['help_reason']}", "no": f" → {helper}: 거절 ({e['help_reason']})",
                    None: " → 라운드 안에 확인 못 함"}.get(e["help"], "")
            why.append(f"{name}: {e['reason']}{tail}")
            if e["help"] == "defer":
                defers.append((e["help_task"], helper))
    if not why:
        why.append("같은 역할에 물어볼 사람이 없음")
    seen = set()
    for tid, proposer in defers:      # 미루기는 PM 만 정할 수 있어서 프록시의 조건이 PM 의 선택지가 된다
        x = b.tasks.get(tid)
        if not x or tid in seen:
            continue
        seen.add(tid)
        p = b.people[x.who]
        grants.append({"key": f"defer:{x.id}", "label": f"{x.title}({p.name}){'을' if _has_final(x.title) else '를'} 2주차로 미뤄도 됨",
                       "effect": f"{p.name} {num(x.d)}일 비워짐 · {proposer}의 프록시가 낸 조건", "short": f"{x.title} 미루기"})
    over = hive.pred(b, h) - h.t
    for opt in t.cut_options or []:
        if opt["saves"] >= over - hive.EPS:
            grants.append({"key": f"cut:{t.id}:{opt['key']}", "label": opt["label"],
                           "effect": f"{t.title} {num(t.d)} → {num(t.d - opt['saves'])}일", "short": "범위 줄이기"})
    hive_say(db, f"{ctx.get('round', 0)}라운드 끝 · 받을 수 있는 조합 없음 → PM에게 규칙 허락을 물음", hid=h.id, run_id=run.id)
    hist(db, h.id, "hive", "규칙 안에서 못 풂 → PM 확인 요청")
    db.add(Ask(hid=h.id, why=why, grants=grants, run_id=run.id))
    patch(run, phase_after=ctx.get("phase_after") or meta(db, "phase"))
    set_meta(db, "phase", "ask")
    narr(db, f"PM 차례 · '{h.title}'에서 규칙 하나를 허락하세요" if grants else f"PM 차례 · '{h.title}' 약속을 다시 정해야 합니다")
    run.step, run.status = "granted", "waiting_pm"


def n_granted(db: Session, run: Run) -> None:
    """PM 이 허락한 뒤. grant() 가 ctx['grant'] 를 채우고 다시 돌린다."""
    b = board(db)
    ctx = run.ctx
    h, t = b.hands[ctx["hid"]], b.tasks[ctx["task"]]
    kind, _, rest = ctx["grant"].partition(":")
    if kind == "defer":
        x = b.tasks[rest]
        narr(db, "규칙이 바뀜 · 프록시들이 다시 답하는 중")
        hive_say(db, f"규칙 바뀜 · {x.title} → 2주차 허락", hid=h.id, run_id=run.id)
        x.s0 = max(b.week_end, x.s0)
        hive.schedule(b)
        patch(run, replies=None, round=0, quiet=True)      # 규칙이 바뀌었으니 라운드를 새로 센다
        run.step = "bids"
        return
    tid, _, okey = rest.partition(":")
    opt = next(o for o in t.cut_options if o["key"] == okey)
    owner = b.people[t.who]
    before = hive.states(b)
    narr(db, f"범위가 바뀜 · {owner.name}의 프록시가 다시 계산하는 중")
    hive_say(db, f"규칙 바뀜 · {josa(opt['note'], '은', '는')} 이번 제출에서 뺌", hid=h.id, run_id=run.id)
    say(db, owner.id, "견적", [TK(t.title), N(f"{num(t.d)}일 → {num(t.d - opt['saves'])}일")], hid=h.id, run_id=run.id)
    t.d = t.plan = t.d - opt["saves"]
    t.cut_options = [o for o in t.cut_options if o["key"] != okey]
    h.basis = ""
    hive.schedule(b)
    c = ask_person(db, run, owner.id, f"{h.title} {when(h.t)} 약속을 지킬 수 있나요?", f"{when(h.t)} 약속 확인", h.id, "owner")
    patch(run, before=before, cut_done=True, cut_note=opt["note"], waiting_for=[c.id])
    run.step = "cutconfirm"


def n_cutconfirm(db: Session, run: Run) -> None:
    res, _ = wait_confirms(db, run)
    if res == "pending":
        return
    if res == "rejected":
        run.status = "running"
        patch(run, owner_refused=True, replies=[], waiting_for=[], cut_done=False)
        run.step = "ask"
        return
    run.step = "finish"


# ── PM 조작: 약속 다시 정하기 · 일 옮기기 ─────────────────────────────
def n_reagree_wait(db: Session, run: Run) -> None:
    res, _ = wait_confirms(db, run)
    if res == "pending":
        return
    b = board(db)
    h = b.hands[run.ctx["hid"]]
    receiver = b.people[b.tasks[h.to_task].who]
    h.prop = False
    if res == "rejected":
        run.status = "running"
        hist(db, h.id, "person", f"{receiver.name} 거절 · 약속 그대로", who=receiver.id)
        return done(db, run, f"{josa(receiver.name, '이', '가')} 새 약속을 거절했어요")
    before = hive.states(b)
    h.t, h.agreed, h.basis = run.ctx["new_t"], True, ""
    hist(db, h.id, "person", f"{receiver.name} 확인 → Agreed", who=receiver.id)
    hive.schedule(b)
    announce(db, b, before, run.id)
    done(db, run, "약속을 다시 정했어요")


def n_move_wait(db: Session, run: Run) -> None:
    res, _ = wait_confirms(db, run)
    if res == "pending":
        return
    b = board(db)
    ctx = run.ctx
    t = b.tasks[ctx["task"]]
    if res == "rejected":
        run.status = "running"
        t.who, t.d, t.plan, t.s0, t.kind, t.got = ctx["from"], ctx["old_d"], ctx["old_plan"], ctx["old_s0"], ctx["old_kind"], False
        hive.schedule(b)
        return done(db, run, "받을 사람이 거절해서 그대로 둠")
    t.kind = "new"
    hive.schedule(b)
    announce(db, b, ctx["before"], run.id)
    rk = len(hive.risks(b))
    done(db, run, f"늦어질 Handoff {rk}개 · Handoffs에서 약속을 다시 정할 수 있어요" if rk else "Handoff 모두 제때")


# ── LangGraph ─────────────────────────────────────────────────────────
NODES = {
    "ingest": n_ingest, "help": n_help, "bids": n_bids, "tally": n_tally, "person": n_person, "propose": n_propose,
    "confirm": n_confirm, "commit": n_commit, "reconfirm": n_reconfirm, "finish": n_finish,
    "ask": n_ask, "granted": n_granted, "cutconfirm": n_cutconfirm,
    "reagree_wait": n_reagree_wait, "move_wait": n_move_wait,
}


class GState(TypedDict):
    run_id: int


def _wrap(fn):
    def node(state: GState, config):
        db = config["configurable"]["db"]
        run = db.get(Run, state["run_id"])
        fn(db, run)
        db.flush()
        return state
    return node


def _route(state: GState, config):
    run = config["configurable"]["db"].get(Run, state["run_id"])
    return run.step if run.status == "running" and run.step in NODES else END


def build_graph():
    g = StateGraph(GState)
    g.add_node("router", lambda s: s)
    for name, fn in NODES.items():
        g.add_node(name, _wrap(fn))
        g.add_edge(name, "router")
    g.add_edge(START, "router")
    g.add_conditional_edges("router", _route, list(NODES) + [END])
    return g.compile()


GRAPH = build_graph()


def drive(db: Session, run: Run) -> Run:
    """run 을 멈출 때까지(사람 대기 · PM 대기 · 끝) 돌린다."""
    run.status = "running"
    db.flush()
    GRAPH.invoke({"run_id": run.id}, {"configurable": {"db": db}, "recursion_limit": 120})
    db.flush()
    return run


# ── 바깥에서 부르는 동작 ──────────────────────────────────────────────
def start_records(db: Session, records: list[dict], auto_confirm: bool, phase_after: str | None = None) -> Run | None:
    """새 기록 묶음을 받는다. 기록의 주인마다 그 사람의 프록시가 읽는다."""
    by_who: dict[str, list[str]] = {}
    for r in records:
        add_record(db, r["src"], r["text"], who=r.get("who"), t=r.get("t"))
        if r.get("who"):
            by_who.setdefault(r["who"], []).append(r["text"])
    last = None
    for who, texts in by_who.items():
        run = Run(kind="record", step="ingest", auto_confirm=auto_confirm,
                  ctx={"who": who, "records": texts, "phase_after": phase_after})
        db.add(run)
        db.flush()
        last = drive(db, run)
    return last


def confirm(db: Session, cid: int, ok: bool = True) -> Run | None:
    c = db.get(Confirmation, cid)
    if not c or c.status != "pending":
        raise ValueError("이미 처리됐거나 없는 확인")
    apply_confirm(db, c, ok)
    run = db.get(Run, c.run_id) if c.run_id else None
    if run and run.status == "waiting_confirm":
        drive(db, run)
    return run


def grant(db: Session, ask_id: int, key: str) -> Run:
    a = db.get(Ask, ask_id)
    if not a or not a.open:
        raise ValueError("이미 닫혔거나 없는 PM 확인")
    g = next((x for x in a.grants if x["key"] == key), None)
    if not g:
        raise ValueError("고를 수 없는 허락")
    snap(db)
    a.open, a.chosen = False, key
    t = stamp(db)
    db.add(Grant(label=g["label"], key=key, ask_id=a.id, t=t))
    bump_decisions(db)
    add_record(db, "PM", f"규칙 허락 · {g['label']}", t=t)
    hist(db, a.hid, "pm", f"허락 · {g['label']}", t=t)
    run = db.get(Run, a.run_id)
    patch(run, grant=key, grant_label=g["short"])
    return drive(db, run)


def reagree(db: Session, hid: str, auto_confirm: bool) -> Run:
    """PM 이 늦어질 Handoff 의 약속을 예상 시각으로 다시 정한다. 받는 사람이 확인해야 굳는다."""
    b = board(db)
    h = b.hands.get(hid)
    if not h or hive.h_state(b, h) != "risk":
        raise ValueError("늦어질 Handoff 만 다시 정할 수 있음")
    a, c = b.tasks[h.from_task], b.tasks[h.to_task]
    new_t = hive.pred(b, h)
    snap(db)
    bump_decisions(db)
    add_record(db, "PM", f'"{h.title}" 약속을 {when(new_t)}로')
    pm_say(db, f'"{h.title}" 약속 {when(new_t)}로', hid=hid)
    h.prop = True
    hist(db, hid, "pm", f"새 약속 제안 · {when(new_t)}")
    run = Run(kind="reagree", step="reagree_wait", auto_confirm=auto_confirm, ctx={"hid": hid, "new_t": new_t})
    db.add(run)
    db.flush()
    say(db, a.who, "약속", [TK(h.title), N(when(new_t)), F("가약속")], to=c.who, hid=hid, run_id=run.id)
    cf = ask_person(db, run, c.who, f"{h.title} {when(new_t)}에 받아도 될까요?", f'"{h.title}" {when(new_t)} 받기 · 확인', hid, "receiver")
    patch(run, waiting_for=[cf.id])
    narr(db, f"{b.people[c.who].name}에게 확인 알림 · 사람 차례")
    return drive(db, run)


def move_bids(db: Session, task_id: str) -> dict:
    """배정판: 이 일을 누가 받을 수 있는지 프록시들의 답과, 미루기 · 빼기의 영향."""
    b = board(db)
    t = b.tasks[task_id]
    out = []
    for p in b.people.values():
        e = hive.est(b, task_id, p.id)
        if not e:
            continue
        mine = p.id == t.who
        pv = None if mine else hive.preview(b, task_id, p.id)
        load = hive.load_of(b, p.id) if mine else pv["load"]
        out.append({"who": p.id, "mine": mine, "days": e["days"], "basis": e["basis"], "wish": e.get("wish", False),
                    "load": load, "over": load > b.cap + hive.EPS,
                    "new_risk": [] if mine else pv["new_risk"], "fixed": [] if mine else pv["fixed"],
                    "start": t.s if mine else pv["task"].s})
    nxt, cut = hive.preview(b, task_id, "next"), hive.preview(b, task_id, "cut")
    return {"task": task_id, "bids": out,
            "next": {"new_risk": nxt["new_risk"], "fixed": nxt["fixed"]},
            "cut": {"fixed": cut["fixed"], "lost_handoffs": [k for k, h in b.hands.items()
                                                             if task_id in (h.from_task, h.to_task) and not h.done]}}


def move(db: Session, task_id: str, dest: str, auto_confirm: bool) -> Run | None:
    """PM 이 일을 다른 사람 · 2주차 · 범위 밖으로 옮긴다. 규칙을 넘겨도 PM 이 직접 정한 것이라 통과시키고 기록에 남긴다."""
    b = board(db)
    t = b.tasks.get(task_id)
    if not t or t.cut or t.kind == "done":
        raise ValueError("옮길 수 없는 일")
    frm = t.who
    if dest == frm:
        return None
    if dest not in ("next", "cut") and (dest not in b.people or b.people[dest].role != t.role):
        raise ValueError("역할이 달라 맡을 수 없음")
    snap(db)
    before = hive.states(b)
    bump_decisions(db)
    if dest == "next":
        t.s0 = max(b.week_end, t.s0)
        add_record(db, "PM", f'"{t.title}" 2주차로 미룸')
        pm_say(db, f'"{t.title}" 2주차로')
        say(db, frm, "약속", [TK(t.title), F("2주차")])
    elif dest == "cut":
        t.cut = True
        add_record(db, "PM", f'"{t.title}" 이번 제출에서 뺌')
        pm_say(db, f'"{t.title}" 이번 제출에서 빼기')
        hive_say(db, f"범위 바뀜 · {t.title} 빠짐")
    else:
        e, to = hive.est(b, task_id, dest), b.people[dest]
        over = hive.preview(b, task_id, dest)["load"] > b.cap + hive.EPS
        add_record(db, "PM", f'"{t.title}" → {to.name}')
        pm_say(db, f'"{t.title}" → {to.name}')
        hive_say(db, f"담당 변경 · {b.people[frm].name} → {to.name}" + (" · 규칙 넘김(5일 초과) · PM이 직접 정함" if over else ""))
        ctx = {"task": task_id, "from": frm, "old_d": t.d, "old_plan": t.plan, "old_s0": t.s0, "old_kind": t.kind, "before": before}
        t.who0 = t.who0 or frm
        t.who, t.d, t.plan, t.s0, t.kind, t.got = dest, e["days"], e["days"], max(t.s0, b.now), "prop", True
        hive.schedule(b)
        say(db, frm, "넘김", [TK(t.title), F("자료 위치 · 된 것")], to=dest)
        say(db, dest, "약속", [TK(t.title), N(f"{num(e['days'])}일"), F("가약속")], basis=e["basis"], pref="바라던 일" if e["wish"] else "")
        run = Run(kind="move", step="move_wait", auto_confirm=auto_confirm, ctx=ctx)
        db.add(run)
        db.flush()
        cf = ask_person(db, run, dest, f'"{t.title}" {num(e["days"])}일 맡아도 될까요?', f'"{t.title}" 맡을게요 · 확인', None, "taker")
        patch(run, waiting_for=[cf.id])
        narr(db, f"{to.name}에게 확인 알림 · 사람 차례")
        return drive(db, run)
    hive.schedule(b)
    announce(db, b, before)
    rk = len(hive.risks(b))
    narr(db, f"늦어질 Handoff {rk}개 · Handoffs에서 약속을 다시 정할 수 있어요" if rk else "Handoff 모두 제때")
    return None
