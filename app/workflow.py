"""협상 워크플로. LLM(프록시)이 쓰고, Hive 코드가 판단하고, LangGraph 가 단계를 돈다.

한 건의 진행 상태는 run 표에 있다. 사람 확인이나 PM 허락을 기다릴 때는 그래프가 끝나고
(status = waiting_*), 답이 오면 resume() 이 같은 run 을 멈춘 단계부터 다시 돌린다.
상태가 DB에 있어서 서버를 껐다 켜도 이어지고, 되돌리기도 DB 스냅샷 하나로 끝난다.

기록 → 의존 일정 → 마감 검사 → 분리안 → 다자간 discussion → 버전별 동의 → 적용.
거절/수정안은 공개 기록에 남기고 모든 참여자가 재제안할 수 있다.
일정은 코드가 검증하고 위임 판단은 각자의 카드만 받은 LLM이 수행한다.
기한 조정 완료 뒤에도 fairness_gate로 연결해 안전한 배분을 바탕으로 협상한다.
"""
from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import hive
from .policies import needs_review
from .hive import num, when
from .llm import Piece, Reply, Split, default_bid_days, get_llm
from .models import Ask, Confirmation, Grant, Handoff, HandoffEvent, Message, Resolution, Rule, Run, Task
from . import store
from .store import (F, N, TK, add_record, board, bump_decisions, card, hist, hive_say, meta, narr, next_id,
                    next_oi, pm_say, rule, say, set_meta, snap, stamp)

PREF_LABEL = {"fast": "빨리 끝나는 쪽", "learn": "배우고 싶은 사람", "fair": "누적 부담 균형"}


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
    run = db.get(Run, c.run_id) if c.run_id else None
    db.add(Message(k="person", who=c.who, text=c.text if ok else f"{c.prompt} · 거절", hid=c.hid, run_id=c.run_id, t=c.t,
                   round=run.ctx.get("round", 0) if run else None, attempt=run.ctx.get("attempt", 0) if run else 0))
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


# ── PDF chain 1: Issue → Task 견적 ───────────────────────────────────
def n_ingest(db: Session, run: Run) -> None:
    """PDF step 1: 담당 Proxy가 issue를 읽고 달라진 Task 견적을 적는다."""
    b = board(db)
    ctx = run.ctx
    person = b.people[ctx["who"]]
    mine = [t for t in b.tasks.values() if t.who == person.id and not t.cut and t.kind not in ("done", "milestone")]
    ans = get_llm().reestimate(person, ctx["records"], mine, model=card(db, person.id).model)
    if not ans or ans.task not in {t.id for t in mine} or abs(ans.days - b.tasks[ans.task].d) < hive.EPS:
        # No schedule change still enters dependency/deadline review, then the
        # fairness gate can look for an optional, safe redistribution.
        patch(run, issue_task=None, issue_hands=[], issue_before=hive.states(b), estimate_changed=False)
        narr(db, "새 기록을 읽음 · 견적 변경은 없음 · 마감과 부담 균형을 계속 확인")
        run.step = "dependency_check"
        return
    t = b.tasks[ans.task]
    outs = [h for h in b.hands.values() if h.from_task == t.id and hive.h_state(b, h) != "cut"]
    before = hive.states(b)
    say(db, person.id, "견적", [TK(t.title), N(f"{num(t.d)}일 → {num(ans.days)}일")], basis=ans.basis,
        hid=outs[0].id if outs else None, run_id=run.id)
    t.d = ans.days
    for h in outs:
        h.basis = ans.basis
    patch(run, issue_task=t.id, issue_hands=[h.id for h in outs], issue_before=before)
    patch(run, estimate_changed=True)
    narr(db, "이슈 접수 · 담당 Proxy가 수정한 Task를 의존 일정 검사로 전달")
    run.step = "dependency_check"


def n_dependency_check(db: Session, run: Run) -> None:
    """PDF step 2: Hive가 의존 작업 전체를 다시 배치하고 영향 전파를 표시한다."""
    b = board(db)
    hive.schedule(b)
    narr(db, "의존성 검사 · Hive가 선후 작업과 담당자 일정을 다시 계산")
    announce(db, b, run.ctx.get("issue_before", {}), run.id)
    late = [b.hands[hid] for hid in hive.risks(b)]
    patch(run, issue_late=[h.id for h in late])
    run.step = "deadline_gate"


def record_feasible_baseline(db, run):
    """Freeze a verified agreed deadline solution before discussing fairness."""
    b=board(db);hive.schedule(b)
    gate=hive.gate(b)
    if hive.risks(b) or gate['violations'] or gate['warnings']:
        return False
    patch(run, feasible_baseline=dict(
        tasks={key:{f:getattr(t,f,None) for f in hive.TASK_FIELDS} for key,t in b.tasks.items()},
        handoffs={key:{f:getattr(h,f,None) for f in hive.HAND_FIELDS} for key,h in b.hands.items()},
        fairness=hive.fairness(b)), negotiation_stage='fairness')
    return True


def audit_constraints(db, run, b):
    """Persist the code gate, including zero-effort approval availability decisions."""
    result = hive.gate(b)
    patch(run, constraint_evaluation=result)
    for a in result.get('adjustments', []):
        t = b.tasks[a['task']]
        reasons = ', '.join(w.get('reason') or '가용 불가' for w in a['unavailable']
                            if w['start'] <= a['requested'] < w['end'])
        hive_say(db, f"제약 평가 · {b.people[t.who].name} · {t.title} · "
                 f"승인 시각 {a['requested']:g}은 불가 ({reasons}) · "
                 f"가용 시각 {a['scheduled']:g}으로 이동 · 후속 마감 재검사", run_id=run.id)
    for v in result['violations'] + result['warnings']:
        hive_say(db, f"제약 위반 · {v['code']} · {v['text']}", run_id=run.id)
    return result


def n_deadline_gate(db: Session, run: Run) -> None:
    """PDF step 3: deadline risk takes priority; a safe schedule proceeds to fairness review."""
    b = board(db)
    hive.schedule(b)
    gate = audit_constraints(db, run, b)
    late = [b.hands[hid] for hid in hive.risks(b)]
    if not late and not gate['ok']:
        # Some capacity/submission violations have no outgoing Handoff to negotiate.
        # Keep this explicitly blocked instead of reporting successful completion.
        run.step, run.status = 'done', 'blocked'
        narr(db, 'Hive 제약 검증 실패 · 미해결 마감·용량 제약 · 일정/담당/가용 설정 수정 후 다시 실행 필요')
        return
    if not late:
        record_feasible_baseline(db,run)
        hive_say(db, "마감 판정 · 현재 영향받은 약속은 모두 기한 안 · 공정한 부담 분담도 확인", run_id=run.id)
        run.step = "fairness_gate"
        return
    h = late[0]
    t = b.tasks[h.from_task]
    next_action = "승인 담당·일정 재조정이 필요" if t.kind == 'milestone' else "담당 Proxy에게 실행 가능한 분담안을 요청"
    hive_say(db, f"마감 판정 · {h.title} {when(h.t)} 위험 · {next_action}",
             hid=h.id, run_id=run.id)
    patch(run, task=t.id, hid=h.id, round=0, attempt=0, excluded=[], replies=None,
          refused=[], notes=[], recv={}, banned=[], pm_reasons=[], rebalance_reason="deadline",
          negotiation_stage="deadline")
    if t.kind == 'milestone':
        patch(run, notes=[f"{b.people[t.who].name} · {t.title} 승인 가능 시각 {t.s:g} · "
                         f"{h.title} 마감 {h.t:g} 위반 · 승인 담당·일정 재조정 필요"])
        run.step = "ask"
    else:
        run.step = "help"


def n_fairness_gate(db: Session, run: Run) -> None:
    """No deadline risk is not an automatic stop: find safe work to rebalance."""
    b = board(db)
    hive.schedule(b)
    if hive.risks(b):
        run.step = "deadline_gate"
        return
    if not record_feasible_baseline(db,run):
        run.step = "deadline_gate"
        return
    if run.ctx.get('discussion'):
        patch(run, discussion_archive=run.ctx.get('discussion_archive', []) + [run.ctx['discussion']], discussion=None)
    fairness = hive.fairness(b)
    # Conservative defaults: review only a visible spread, and only move work
    # when source and same-role recipient differ by at least two effort-days.
    cfg = {"min_range": 3.0, "min_gap": 2.0}
    rule_row = db.get(Rule, "fairness")
    if rule_row:
        cfg.update(rule_row.value or {})
    if fairness["range"] < cfg["min_range"]:
        return done(db, run, f"공정성 검토 · 부담 범위 {hive.num(fairness['range'])}일 · 재분담 기준 미달")

    owners = sorted(b.people, key=lambda pid: fairness["totals"][pid], reverse=True)
    choice = None
    for owner_id in owners:
        owner = b.people[owner_id]
        owner_total = fairness["totals"][owner_id]
        peers = [p for p in b.people.values() if p.id != owner_id and p.role == owner.role
                 and owner_total - fairness["totals"][p.id] >= cfg["min_gap"]]
        if not peers:
            continue
        recipient = min(peers, key=lambda p: fairness["totals"][p.id])
        tasks = sorted((t for t in b.tasks.values() if t.who == owner_id and not t.cut
                        and t.kind not in ("done", "milestone", "prop") and t.d >= 1
                        and t.s < b.week_end), key=lambda t: (-t.d, t.s, t.oi))
        for task in tasks:
            outs = sorted((h for h in b.hands.values() if h.from_task == task.id
                           and hive.h_state(b, h) not in ("cut", "done")), key=lambda h: h.t)
            if not outs:
                continue
            # Moving half the source/recipient gap would equalize their totals.
            hint = min(task.d - 0.5, max(0.5, (owner_total - fairness["totals"][recipient.id]) / 2))
            choice = (owner, task, outs[0], recipient, hint)
            break
        if choice:
            break
    if not choice:
        return done(db, run, "공정성 검토 · 부담 차이는 있으나 안전하게 나눌 연결 업무를 찾지 못함")

    owner, task, h, recipient, hint = choice
    hive_say(db, f"공정성 검토 · {owner.name} {hive.num(fairness['totals'][owner.id])}일 / "
             f"{recipient.name} {hive.num(fairness['totals'][recipient.id])}일 · "
             f"기한 위험 없는 {task.title} 분담안을 확인", hid=h.id, run_id=run.id)
    patch(run, task=task.id, hid=h.id, round=0, attempt=0, excluded=[], replies=None,
          refused=[], notes=[], recv={}, banned=[], pm_reasons=[], rebalance_reason="fairness",
          fairness_before=fairness, fairness_owner=owner.id, fairness_recipient=recipient.id,
          piece_hint=hint, issue_hands=[h.id])
    run.step = "help"


# ── PDF chain 4: 담당 Proxy가 독립 분담안과 인수인계를 제안 ────────────
def n_help(db: Session, run: Run) -> None:
    """PDF step 4a: 담당 Proxy가 위임 가능한 독립 조각과 인수인계를 제안한다."""
    b = board(db)
    h, t = b.hands[run.ctx["hid"]], b.tasks[run.ctx["task"]]
    owner = b.people[t.who]
    narr(db, f"Hive가 도움 요청을 엶 · 떼어 낼 조각은 {owner.name}의 프록시가 정함")
    label = "공정성 분담 검토" if run.ctx.get("rebalance_reason") == "fairness" else "도움 요청"
    hive_say(db, f"{label} · {h.title} · {when(h.t)}까지 · {t.role}", hid=h.id, run_id=run.id)
    hist(db, h.id, "hive", "도움 요청 열림")
    hint = run.ctx.get("piece_hint")
    if hint is None:
        hint = max(0.5, hive.pred(b, h) - h.t)
    split = get_llm().split(owner, t, hint, model=card(db, owner.id).model)
    if not split:
        decision = getattr(get_llm(), "last_split_decision", {})
        hive_say(db, "분리 보류 · " + decision.get("rationale", "독립 분리 근거가 부족함"), hid=h.id, run_id=run.id)
        patch(run, no_split=True)
        patch(run,recovery_strategies=['whole_transfer','move_other_work','reschedule','collaborate'],
              split_assessment=decision)
        hive_say(db,'분리 불가 ≠ 일정 해결 불가 · 전체 양도·다른 업무 이동·순서 변경·협업 대안 토의',hid=h.id,run_id=run.id)
        from .discussion import begin_whole
        if begin_whole(db,run):
            run.step = "bids"
        else:
            run.step = "ask"
        return
    p = split.piece
    say(db, owner.id, "조건", [TK(p.title), N(f"{num(p.days)}일"), F(p.reason)], basis=p.basis, hid=h.id, run_id=run.id)
    patch(run, split=split.model_dump())
    run.step = "card_check"


def n_card_check(db: Session, run: Run) -> None:
    """PDF step 4b: 같은 역할 Proxy를 찾고 각자에게 자기 위임카드로 답하게 한다."""
    b = board(db)
    h, t = b.hands[run.ctx["hid"]], b.tasks[run.ctx["task"]]
    piece = Piece(**run.ctx["split"]["piece"])
    role = piece.role or t.role
    cands = sorted((p for p in b.people.values()
                    if p.role == role and p.id != t.who and p.id not in run.ctx.get("excluded", [])),
                   key=lambda p: (-(p.rec or {}).get(piece.tag, 0), p.oi))
    patch(run, candidate_ids=[p.id for p in cands])
    if not cands:
        suffix = "기존 배정 유지" if run.ctx.get("rebalance_reason") == "fairness" else "PM 검토"
        hive_say(db, f"위임카드·역할 확인 · '{role}'에서 담당 외 후보가 없음 → {suffix}",
                 hid=h.id, run_id=run.id)
        if run.ctx.get("rebalance_reason") == "fairness":
            return done(db, run, "공정성 분담 검토 · 같은 역할에서 동의 가능한 후보가 없어 기존 배정을 유지")
        patch(run, replies=[])
        run.step = "ask"
        return
    hive_say(db, f"위임카드 확인 단계 · {len(cands)}명의 '{role}' Proxy에게 각자 자기 카드와 일정으로 요청",
             hid=h.id, run_id=run.id)
    run.step = "bids"


# ── PDF chain 5: 공유 토론 중 각 후보 Proxy가 자기 카드로 답함 ─────────
def _mentor(b, t, piece, pid, owner_id):
    """그 조각을 가장 많이 해 본 같은 역할 사람 (자기와 담당 제외). 도움을 청할 상대."""
    return max((x for x in b.people.values() if x.role == (piece.role or t.role) and x.id not in (pid, owner_id)),
               key=lambda x: (x.rec or {}).get(piece.tag, 0), default=None)


def _thread(db, run, b, pid) -> list[str]:
    """이 협상에서 그 프록시가 주고받은 말. 프록시는 자기 것만 본다 (Live 모드에서 LLM 에게 준다)."""
    out = []
    for m in db.scalars(select(Message).where(Message.run_id == run.id, Message.k == "proxy").order_by(Message.id)):
        if pid not in (m.frm, m.to):
            continue
        other = m.to if m.frm == pid else m.frm
        head = f"나 → {b.people[other].name}" if m.frm == pid and other else "나" if m.frm == pid else f"{b.people[other].name} → 나"
        out.append(f"{head} · {m.act}: " + " · ".join(f["t"] for f in m.fields) + (f' "{m.say}"' if m.say else ""))
    return out[-12:]


def _shared_thread(db, run, b) -> list[str]:
    """공유 토론 기록. 공개된 제안과 이유만 전달하고 위임카드 원문은 노출하지 않는다."""
    out = []
    for m in db.scalars(select(Message).where(Message.run_id == run.id, Message.k == "proxy").order_by(Message.id)):
        sender = b.people[m.frm].name if m.frm in b.people else "Proxy"
        recipient = f" → {b.people[m.to].name}" if m.to in b.people else ""
        fields = " · ".join(f["t"] for f in (m.fields or []))
        out.append(f"{sender}{recipient} · {m.act}: {fields}" + (f" · {m.say}" if m.say else ""))
    return out[-24:]


def _ask_proxy(db, run, b, p, piece, owner_id, t, hid, helper_minutes=None, wait=None) -> Reply:
    """프록시 하나에게 묻는다. 답이 규칙에 어긋나면 이유를 붙여 한 번 돌려보내고(라운드는 쓰지 않음), 또 어긋나면 거절로 적는다.

    helper_minutes 를 주면 도움 요청, wait(preview_offer 결과에 title · old · new 를 더한 것)를 주면 늦춰 받기 요청.
    """
    llm, cd = get_llm(), card(db, p.id)
    banned = [k.split(":", 1)[1] for k in run.ctx.get("banned", []) if k.startswith("defer:")]
    c = {"now": b.now, "load": hive.load_of(b, p.id), "cap": hive.capacity(b,p.id), "deferrable": hive.deferrable(b, p.id, banned), "violation": None,
         "pm_reasons": [f"{', '.join(x['labels'])} → 거절: {x['reason']}" for x in run.ctx.get("pm_reasons", [])],
         "default_days": default_bid_days(b, piece, p.id, owner_id), "mentor": _mentor(b, t, piece, p.id, owner_id),
         "thread": _thread(db, run, b, p.id), "shared_thread": _shared_thread(db, run, b)}
    if wait:
        c.update(wait)
    v = None
    for _ in range(2):
        if wait:
            ans = llm.wait_reply(p, cd, c)
            fixed, v = hive.check_wait_reply(ans.model_dump(), wait)
        else:
            ans = llm.help_reply(p, cd, helper_minutes, c) if helper_minutes else llm.reply(p, cd, piece, c)
            fixed, v = hive.check_reply(b, p.id, ans.model_dump(), piece.days, c["default_days"], owner_id, bool(helper_minutes), banned)
        if not v:
            return Reply(**fixed)
        hive_say(db, f"반려 · {p.name}의 프록시 답 {ans.type} · {v['code']}: {v['text']} · 라운드는 쓰지 않음", hid=hid, run_id=run.id)
        c["violation"] = v
    return Reply(type="REJECT", reason=f"규칙 확인을 통과하지 못함 ({v['code']})")


def _viable(e) -> bool:
    return e["type"] in ("ACCEPT", "NEEDS_INPUT") or (e["type"] == "COUNTER" and e["cond"]["kind"] == "help" and e["help"] == "ok")


def n_bids(db: Session, run: Run) -> None:
    if run.ctx.get('rebalance_reason') == 'fairness' or run.ctx.get('discussion'):
        from .discussion import turn
        return turn(db, run)
    b, ctx = board(db), run.ctx
    h, t = b.hands[ctx['hid']], b.tasks[ctx['task']]
    piece = Piece(**ctx['split']['piece'])
    owner, rnd = b.people[t.who], ctx.get('round', 0)+1
    store.mark(rnd, ctx.get('attempt', 0))
    from . import progress,stages
    progress.publish(run,stages.for_node(run,'bids'),store.DEMO,round=rnd)
    today = hive.DAY[min(4, int(b.now))]
    replies, recv = ctx.get('replies'), dict(ctx.get('recv') or {})
    if replies is None:
        ids = ctx.get('candidate_ids')
        cands = [b.people[p] for p in ids] if ids is not None else sorted(
            (p for p in b.people.values() if p.role == (piece.role or t.role) and p.id != owner.id),
            key=lambda p: (-(p.rec or {}).get(piece.tag, 0), p.oi))
        cands = [p for p in cands if p.id not in ctx.get('excluded', [])]
        replies = []
        for p in cands:
            if not ctx.get('quiet'):
                say(db, owner.id, '질문', [TK(piece.title), N(f'{num(piece.days)}일'), F(f'{when(h.t)}까지 돼요?')], to=p.id, hid=h.id, run_id=run.id)
            r = _ask_proxy(db, run, b, p, piece, owner.id, t, h.id)
            e = dict(who=p.id, type=r.type, days=r.days, cond=r.cond.model_dump() if r.cond else None,
                     reason=r.reason, say=r.say, wish=piece.tag in (p.wants or []), help=None,
                     help_reason='', help_task=None, approved=False, late_to=None, late=None)
            if r.days and r.type != 'REJECT':
                pv = hive.preview_offer(b, ctx['split'], t.id, h.id, p.id, r.days)
                e.update(fairness=pv['fairness'], deadline_risk=bool(pv['late_to'] is not None or pv['pushed_all'] or pv['breaks']))
                if pv['late_to'] is not None:
                    e.update(late_to=pv['late_to'], late=pv)
            fields = [TK(piece.title)] + ([N(f'{num(r.days)}일')] if r.days else [])
            label = {'ACCEPT':'수락', 'REJECT':'거절', 'NEEDS_INPUT':'본인 확인 필요', 'COUNTER':'조건부'}[r.type]
            say(db, p.id, '견적' if r.type != 'COUNTER' or r.cond.kind == 'help' else '조건', fields+[F(label if r.type != 'COUNTER' or r.cond.kind == 'help' else r.reason)],
                to=owner.id, basis=r.reason if r.type == 'REJECT' else hive.tag_line(p, piece.tag), say=r.say, hid=h.id, run_id=run.id)
            replies.append(e)
    else:
        todo = [e for e in replies if e['type']=='COUNTER' and e['cond']['kind']=='help' and e['help'] is None and e['who'] not in ctx['excluded']]
        late = [e for e in replies if e['late_to'] is not None and e['who'] not in ctx['excluded'] and str(e['late_to']) not in recv and (_viable(e) or e in todo)]
        if ctx.get('rebalance_reason') == 'deadline':
            late = []
        receiver = b.people[b.tasks[h.to_task].who]
        for e in todo:
            cand, helper, mins = b.people[e['who']], b.people[e['cond']['who']], e['cond']['minutes']
            say(db, cand.id, '질문', [F(f'도움 {mins}분'), F(f'{today} 오후 돼요?')], to=helper.id, hid=h.id, run_id=run.id)
            r = _ask_proxy(db, run, b, helper, piece, owner.id, t, h.id, helper_minutes=mins)
            if r.type in ('ACCEPT', 'NEEDS_INPUT'):
                e['help'] = 'ok'
                say(db, helper.id, '약속', [F(f'도움 {mins}분'), N(f'{today} 오후')], to=cand.id, pref=r.say, hid=h.id, run_id=run.id)
            elif r.type == 'COUNTER':
                e.update(help='defer', help_reason=r.reason, help_task=r.cond.task)
                say(db, helper.id, '조건', [F(f'도움 {mins}분'), F(r.reason)], to=cand.id, hid=h.id, run_id=run.id)
            else:
                e.update(help='no', help_reason=r.reason)
                say(db, helper.id, '견적', [F(f'도움 {mins}분'), F('거절')], to=cand.id, basis=r.reason, hid=h.id, run_id=run.id)
        for e in late:
            key = str(e['late_to'])
            if key in recv or not _viable(e):
                continue
            if receiver.id == owner.id:
                recv[key] = dict(state='ok', reason='')
                continue
            pv = e['late']
            say(db, owner.id, '질문', [TK(h.title), N(f"{when(h.t)} → {when(e['late_to'])}"), F('늦게 받아도 돼요?')], to=receiver.id, hid=h.id, run_id=run.id)
            r = _ask_proxy(db, run, b, receiver, piece, owner.id, t, h.id, wait={**pv, 'title':h.title, 'old':when(h.t), 'new':when(e['late_to'])})
            if r.type == 'ACCEPT' and pv['late_by'] > card(db, receiver.id).wait_days+hive.EPS:
                r = Reply(type='NEEDS_INPUT', reason='늦춰 받는 한도를 넘음')
            state = {'ACCEPT':'ok','NEEDS_INPUT':'ask'}.get(r.type, 'no')
            recv[key] = dict(state=state, reason=r.reason)
            say(db, receiver.id, '약속' if state=='ok' else '견적', [TK(h.title), F({'ok':'받을게요','ask':'본인 확인 필요','no':'거절'}[state])], to=owner.id, basis=r.reason, hid=h.id, run_id=run.id)
    patch(run, replies=replies, round=rnd, recv=recv)
    run.step = 'tally'


def n_tally(db: Session, run: Run) -> None:
    if run.ctx.get('rebalance_reason') == 'fairness':
        run.step = 'bids'
        return
    b, ctx = board(db), run.ctx
    h, t = b.hands[ctx['hid']], b.tasks[ctx['task']]
    replies = [e for e in ctx['replies'] if e['who'] not in ctx['excluded']]
    recv = ctx.get('recv') or {}
    open_help = [e for e in replies if e['type']=='COUNTER' and e['cond']['kind']=='help' and e['help'] is None]
    open_recv = [] if ctx.get('rebalance_reason') == 'deadline' else [e for e in replies if _viable(e) and e['late_to'] is not None and str(e['late_to']) not in recv]
    if (open_help or open_recv) and ctx['round'] < rule(db, 'rounds')['max']:
        run.step = 'bids'
        return
    if open_help or open_recv:
        hive_say(db, f"{rule(db, 'rounds')['max']}라운드 안에 조건을 다 확인하지 못함", hid=h.id, run_id=run.id)
    def recv_state(e):
        return None if e['late_to'] is None else recv.get(str(e['late_to']), {'state':'ask'})['state']
    ok = [e for e in replies if _viable(e) and recv_state(e) != 'no']
    if ctx.get('rebalance_reason') == 'deadline':
        ok = [e for e in ok if not e.get('deadline_risk')]
    if not ok:
        if replies:
            from .discussion import from_rejections
            if from_rejections(db, run):
                run.step = 'bids'
                return
        run.step = 'ask'
        return
    pref = rule(db, 'pref')['choice']
    if pref == 'fair':
        ok.sort(key=lambda e:(e.get('deadline_risk',False),bool(e.get('late_to')),e.get('fairness',{}).get('variance',float('inf')),e['days']))
    else:
        ok.sort(key=(lambda e:(not e['wish'],e['days'])) if pref=='learn' else (lambda e:e['days']))
    chosen = ok[0]
    taker = b.people[chosen['who']]
    patch(run, chosen=chosen, by_pref=pref if len(ok)>1 else ctx.get('by_pref'))
    piece, waiting = Piece(**ctx['split']['piece']), []
    limit = card(db,taker.id).auto_days
    if (chosen['days'] > limit+hive.EPS or needs_review(card(db,taker.id))) and not chosen['approved']:
        waiting.append(ask_person(db,run,taker.id,f"{piece.title} {num(chosen['days'])}일 · 내 한도({num(limit)}일)를 넘어요. 맡아도 될까요?", f"{piece.title} {num(chosen['days'])}일 맡을게요 · 확인", h.id,'taker'))
    if recv_state(chosen)=='ask' and not chosen.get('recv_approved'):
        receiver = b.people[b.tasks[h.to_task].who]
        note = f" ({', '.join(chosen['late']['pushed'])} 제출일 뒤로 밀림)" if chosen['late']['pushed'] else ''
        waiting.append(ask_person(db,run,receiver.id,f"{h.title} {when(chosen['late_to'])}에 받아도 될까요?{note}",f"{h.title} {when(chosen['late_to'])} 받기 · 확인",h.id,'receiver'))
    if waiting:
        patch(run,waiting_for=[c.id for c in waiting])
        run.step='person'
    else:
        run.step='propose'


def n_person(db: Session, run: Run) -> None:
    """한도를 넘는 일을 맡는 사람, 늦춰 받게 되는 사람의 답을 기다린다."""
    res, c = wait_confirms(db, run)
    if res == "pending":
        return
    ctx = run.ctx
    who = ctx["chosen"]["who"]
    run.status = "running"
    if res == "rejected":
        b = board(db)
        for other in db.scalars(select(Confirmation).where(Confirmation.run_id == run.id, Confirmation.status == "pending")):
            other.status = "withdrawn"
        name = b.people[c.who].name
        if c.role == "taker":
            hive_say(db, f"{name} 본인이 거절 · 다른 답을 다시 봄", hid=ctx["hid"], run_id=run.id)
            note = f"{name}: 본인이 거절"
        else:
            hive_say(db, f"{name} 본인이 늦춰 받기를 거절 · 다른 답을 다시 봄", hid=ctx["hid"], run_id=run.id)
            note = f"{b.people[who].name}: 받는 {josa(name, '이', '가')} 늦춘 약속을 거절"
        patch(run, excluded=ctx["excluded"] + [who], refused=ctx.get("refused", []) + [who],
              notes=ctx.get("notes", []) + [note], waiting_for=[])
        run.step = "tally"
        return
    done_roles = {x.role for x in db.scalars(select(Confirmation).where(Confirmation.id.in_(ctx["waiting_for"])))}
    upd = {"approved": True} if "taker" in done_roles else {}
    if "receiver" in done_roles:
        upd["recv_approved"] = True
    replies = [dict(e, **upd) if e["who"] == who else e for e in ctx["replies"]]
    patch(run, replies=replies, chosen=dict(ctx["chosen"], **upd), waiting_for=[])
    run.step = "propose"


# ── 단계: 가약속을 판에 올리고 규칙 확인 ──────────────────────────────
def n_propose(db: Session, run: Run) -> None:
    b = board(db)
    ctx = run.ctx
    h, t = b.hands[ctx["hid"]], b.tasks[ctx["task"]]
    split, chosen = Split(**ctx["split"]), ctx["chosen"]
    p, taker, owner = split.piece, b.people[chosen["who"]], b.people[t.who]
    target = b.tasks[h.to_task] if split.to == "downstream" else t
    # 약속 시각은 맡는 사람의 줄에서 실제로 끝나는 때 (하던 일이 있으면 그 뒤)
    promise = hive.preview_offer(b, ctx["split"], t.id, h.id, taker.id, chosen["days"])["piece_end"]
    tid = p.id if p.id and not db.get(Task, p.id) else next_id(db, Task, "piece")
    hid = next_id(db, Handoff, "h")
    db.add(Task(id=tid, who=taker.id, title=p.title, s0=b.now, s=b.now, d=chosen["days"], plan=chosen["days"],
                base=p.days, tag=p.tag, role=p.role or t.role, context=p.context or t.context, kind="prop", oi=next_oi(db, Task)))
    db.flush()
    db.add(Handoff(id=hid, from_task=tid, to_task=target.id, title=p.title, what=p.what or p.title, t=promise,
                   prop=True, oi=next_oi(db, Handoff)))
    db.flush()
    say(db, taker.id, "약속", [TK(p.title), N(when(promise)), F("가약속")], to=target.who if target.who != taker.id else None,
        hid=hid, run_id=run.id)
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
def _commit_initial_offer(db: Session, run: Run) -> None:
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
    if ctx.get('rebalance_reason') == 'deadline':
        gate=hive.gate(b)
        if not gate['ok']:
            raise ValueError('; '.join(x['text'] for x in gate['violations']+gate['warnings']))
        hive_say(db,'최종 제약 검증 통과 · 당사자 확인 후 마감·용량·가용 시간 재검증 · 약속 시각 유지',hid=h.id,run_id=run.id)
    if hive.h_state(b, h) == "risk":      # 명시적 PM 경로의 기존 약속 재확인
        new_t = hive.pred(b, h)
        receiver = b.people[b.tasks[h.to_task].who]
        h.t, h.agreed = new_t, True
        patch(run, before={**before, h.id: "agreed"})      # 새 약속은 바로 아래에서 알리므로 finish 에서 또 알리지 않는다
        hist(db, h.id, "proxy", f"약속 다시 정함 · {when(new_t)}", who=owner.id)
        say(db, owner.id, "약속", [TK(h.title), N(when(new_t))], to=receiver.id, say=get_llm().reagree_note(taker),
            hid=h.id, run_id=run.id)
        agreed_to = chosen.get("late_to")
        state = (ctx.get("recv") or {}).get(str(agreed_to), {}).get("state")
        if agreed_to is not None and abs(agreed_to - new_t) < hive.EPS and (chosen.get("recv_approved") or state == "ok"):
            # 토론 중에 받는 쪽이 이미 동의한 시각이라 다시 묻지 않는다
            who_ok = f"{receiver.name} 확인" if chosen.get("recv_approved") else f"{receiver.name}의 프록시가 카드 한도 안에서 수락"
            hist(db, h.id, "person" if chosen.get("recv_approved") else "proxy", f"{who_ok} → Agreed", who=receiver.id)
            patch(run, reagreed=True)
            run.step = "finish"
            return
        c = ask_person(db, run, receiver.id, f"{h.title} {when(new_t)}에 받아도 될까요?",
                       f"{h.title} {when(new_t)} 받기 · 확인", h.id, "receiver")
        narr(db, f"{receiver.name}에게 확인 알림 · 사람 차례")
        patch(run, waiting_for=[c.id], reagreed=True)
        run.step = "reconfirm"
        return
    run.step = "finish"


def n_commit(db: Session, run: Run) -> None:
    """Initial offers also commit atomically after the latest full constraint check."""
    try:
        with db.begin_nested():
            _commit_initial_offer(db,run)
    except ValueError as exc:
        ctx=run.ctx
        _drop_provisional(db,ctx['piece_task'],ctx['piece_hand'])
        patch(run,waiting_for=[],notes=ctx.get('notes',[])+['최종 제약 검증 실패: '+str(exc)])
        hive_say(db,'최종 제약 검증 실패 · 미합의 변경 롤백 · '+str(exc),hid=ctx['hid'],run_id=run.id)
        from .discussion import from_rejections,_event
        if from_rejections(db,run):
            state=run.ctx['discussion']
            _event(db,run,state,'hive',None,'BLOCKED','최종 제약 검증 실패: '+str(exc))
            run.step='bids'
        else:
            run.step='ask'


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
    # PDF step 7: only record success after the affected deadlines pass the final
    # dependency schedule with agreed assignments and handoffs.
    gate = audit_constraints(db, run, b)
    if not gate["ok"]:
        detail = "; ".join(x["text"] for x in gate["violations"] + gate["warnings"])
        hive_say(db, f"최종 마감 검사 실패 · {detail} → 성공 처리 보류, PM 검토 필요", hid=h.id, run_id=run.id)
        patch(run, notes=ctx.get("notes", []) + [f"최종 마감 검사 실패: {detail}"], replies=[])
        run.step = "ask"
        return
    granted = ctx.get("grant_label")
    if ctx.get("cut_done"):
        body = f"{josa(ctx['cut_note'], '을', '를')} 빼서 {josa(owner.name, '이', '가')} {when(h.t)} 약속을 지킴"
        why = f"PM이 범위를 줄임 · {owner.name} 확인"
    else:
        p, taker = Split(**ctx["split"]).piece, b.people[ctx["chosen"]["who"]]
        body = f"{josa(taker.name, '이', '가')} {p.title} {num(ctx['chosen']['days'])}일을 맡음 · {h.title} {when(hive.pred(b, h))}"
        parts = [f"PM이 허락 · {granted}" if granted else "규칙 안"]
        if ctx.get("rebalance_reason") == "fairness":
            parts.append("기한 위험 없는 공정성 분담 검토")
        if ctx.get("by_pref"):
            parts.append(f"받을 사람은 내 규칙 '{PREF_LABEL[ctx['by_pref']]}'")
        if ctx.get("rebalance_reason") == "fairness":
            before_variance = ctx.get("fairness_before", {}).get("variance")
            if before_variance is not None:
                parts.append(f"부담 분산 {before_variance:.2f}→{hive.fairness(b)['variance']:.2f}")
        parts.append(f"{taker.name} 본인 확인" if ctx["chosen"]["approved"] else f"{taker.name}의 프록시가 카드 한도 안에서 수락")
        parts.append(f"{owner.name} 확인")
        parts.append(f"{ctx['round']}라운드")
        if not granted:
            parts.append("PM 결정 없음")
        why = " · ".join(parts)
    db.add(Resolution(hid=h.id, body=body, why=why))
    if ctx.get("rebalance_reason") != "fairness" and not hive.risks(b):
        record_feasible_baseline(db,run)
        patch(run, deadline_resolution=dict(task=ctx['task'], chosen=ctx.get('chosen'), split=ctx.get('split')))
        run.step = "fairness_gate"
        return
    done(db, run, "해결됨 · 당사자 확인으로 끝남")


# ── 단계: 규칙 안에서 못 풀면 PM에게 ──────────────────────────────────
def n_ask(db: Session, run: Run) -> None:
    b = board(db)
    ctx = run.ctx
    h, t = b.hands[ctx["hid"]], b.tasks[ctx["task"]]
    replies = ctx.get("replies") or []
    why, grants, defers = [], [], []
    diagnostics=[]
    discussion=ctx.get('discussion') or {}
    if discussion:
        diagnostics.append('협상 한도 내 합의 실패 · '+str(discussion.get('termination','')))
        diagnostics += [e['reason'] for e in discussion.get('history',[]) if e['response']=='BLOCKED'][-3:]
    if ctx.get("no_split"):
        why.append("떼어 낼 수 있는 조각이 없음")
    if ctx.get("owner_refused"):
        why.append("담당이 조각 넘기기를 거절")
    if ctx.get("receiver_refused"):
        why.append("받는 사람이 늦춘 약속을 거절")
    why.extend(ctx.get("notes", []))
    recv = ctx.get("recv") or {}
    banned = set(ctx.get("banned", []))
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
        if _viable(e) and e["late_to"] is not None and recv.get(str(e["late_to"]), {}).get("state") == "no":
            receiver = b.people[b.tasks[h.to_task].who].name
            why.append(f"{name}: 맡으면 {h.title}{'이' if _has_final(h.title) else '가'} {when(e['late_to'])}으로 늦어짐 → {receiver}: 거절 ({recv[str(e['late_to'])]['reason']})")
    if not why and not diagnostics:
        why.append("같은 역할에 물어볼 사람이 없음")
    why.extend(diagnostics)
    seen = set()
    for tid, proposer in defers:      # 미루기는 PM 만 정할 수 있어서 프록시의 조건이 PM 의 선택지가 된다
        x = b.tasks.get(tid)
        if not x or tid in seen or f"defer:{tid}" in banned:
            continue
        seen.add(tid)
        p = b.people[x.who]
        pv = _grant_preview(b, ctx, tid)
        grants.append({"key": f"defer:{x.id}", "label": f"{x.title}({p.name}){'을' if _has_final(x.title) else '를'} 2주차로 미뤄도 됨",
                       "effect": f"{pv['text']} · {proposer}의 프록시가 낸 조건", "short": f"{x.title} 미루기", "preview": pv})
    over = hive.pred(b, h) - h.t
    for opt in t.cut_options or []:
        if opt["saves"] >= over - hive.EPS and f"cut:{t.id}:{opt['key']}" not in banned:
            st = b.clone()
            st.tasks[t.id].d -= opt["saves"]
            hive.schedule(st)
            left = [st.hands[k].title for k in hive.risks(st)]
            grants.append({"key": f"cut:{t.id}:{opt['key']}", "label": opt["label"], "short": "범위 줄이기",
                           "effect": f"{t.title} {num(t.d)} → {num(t.d - opt['saves'])}일 · " + (f"그래도 늦음: {', '.join(left)}" if left else "약속 모두 제때"),
                           "preview": {"who": t.who, "warnings": left}})
    for x in ctx.get("pm_reasons", []):
        why.append(f"PM이 거절: {', '.join(x['labels'])} ({x['reason']})")
    if t.kind == 'milestone':
        hive_say(db, f"Hive 제약 검증 실패 · {b.people[t.who].name} · {t.title} · "
                 "승인 가능 시각과 후속 마감 충돌 → PM 검토", hid=h.id, run_id=run.id)
        hist(db, h.id, "hive", "승인 일정 제약 위반 → PM 검토 요청")
    else:
        hive_say(db, f"{ctx.get('round', 0)}라운드 끝 · 받을 수 있는 조합 없음 → PM에게 규칙 허락을 물음", hid=h.id, run_id=run.id)
        hist(db, h.id, "hive", "협상 한도 내 합의 실패 → PM 검토 요청")
    notice = '제약 검증 실패 → PM에게 전달됨' if t.kind == 'milestone' else '협상 실패 → PM에게 전달됨'
    from .pm_summary import build as pm_brief
    patch(run, pm_handoff=dict(message=notice, review_required=True, reasons=why,
                              summary=pm_brief(db,run,why,grants)))
    hive_say(db, notice+' · 사유와 검토 선택지 전달 · PM 결정 대기',hid=h.id,run_id=run.id)
    db.add(Ask(hid=h.id, why=why, grants=grants, run_id=run.id))
    patch(run, phase_after=ctx.get("phase_after") or meta(db, "phase"))
    set_meta(db, "phase", "ask")
    narr(db, notice+f" · PM 차례 · '{h.title}'"+(" 규칙 허락 검토" if grants else " 약속 재조정 검토"))
    run.step, run.status = "granted", "waiting_pm"


def _grant_preview(b, ctx, tid: str) -> dict:
    """이 일을 미루도록 허락하면 어떻게 되는지 미리 본다: 누가 조각을 언제까지 맡고, 무엇이 밀리는지."""
    x = b.tasks[tid]
    st = b.clone()
    st.tasks[tid].s0 = max(st.week_end, st.tasks[tid].s0)
    hive.schedule(st)
    e = next((r for r in ctx.get("replies") or [] if r["type"] == "COUNTER" and
              ((r["cond"]["kind"] == "defer" and r["cond"]["task"] == tid) or r.get("help_task") == tid)), None)
    out = {"who": None, "piece_end": None, "warnings": [f"{x.title} 2주차로"]}
    if not e or not ctx.get("split"):
        out["text"] = f"{b.people[x.who].name} {num(x.d)}일 비워짐"
        return out
    pv = hive.preview_offer(st, ctx["split"], ctx["task"], ctx["hid"], e["who"], e["days"])
    h, piece = b.hands[ctx["hid"]], ctx["split"]["piece"]["title"]
    if pv["late_to"] is not None:
        out["warnings"].append(f"{h.title} {when(pv['late_to'])}으로 늦어짐")
    out["warnings"] += [f"{title} 제출일 뒤로 밀림" for title in pv["pushed_all"]]
    out.update(who=e["who"], piece_end=pv["piece_end"])
    out["text"] = (f"{josa(b.people[e['who']].name, '이', '가')} {piece} {num(e['days'])}일 · {when(pv['piece_end'])}까지 · "
                   + (" · ".join(out["warnings"][1:]) if len(out["warnings"]) > 1 else "약속 모두 제때"))
    return out


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
        patch(run, discussion=None, replies=None, round=0, quiet=True, recv={}, attempt=ctx.get("attempt", 0) + 1)   # 규칙이 바뀌었으니 라운드를 새로 센다
        run.step = "card_check"
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
from .discussion import commit as n_discussion_commit

NODES = {
    "ingest": n_ingest, "dependency_check": n_dependency_check, "deadline_gate": n_deadline_gate,
    "fairness_gate": n_fairness_gate,
    "discussion_commit": n_discussion_commit,
    "help": n_help, "card_check": n_card_check, "bids": n_bids, "tally": n_tally, "person": n_person, "propose": n_propose,
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
        store.mark(run.ctx.get("round", 0), run.ctx.get("attempt", 0))
        from . import runlogs
        turn = runlogs.start_turn(db, run, run.step)
        fn(db, run)
        db.flush()
        runlogs.finish_turn(db, run, turn)
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
    if run.kind == 'candidate':
        from .candidates import engine
        return engine.commit(db, run) if run.step == 'candidate_confirm' else engine.advance(db, run)
    if run.kind == "bundle":
        from . import bundles
        return bundles.resume(db, run)
    run.status = "running"
    db.flush()
    GRAPH.invoke({"run_id": run.id}, {"configurable": {"db": db}, "recursion_limit": 1200})
    store.mark(None, 0)
    db.flush()
    return run


# ── 바깥에서 부르는 동작 ──────────────────────────────────────────────
def start_records(db: Session, records: list[dict], auto_confirm: bool, phase_after: str | None = None, negotiation_mode: str | None = None, task_id: str | None = None) -> Run | None:
    """새 기록 묶음을 받는다. 기록의 주인마다 그 사람의 프록시가 읽는다."""
    by_who: dict[str, list[str]] = {}
    for r in records:
        add_record(db, r["src"], r["text"], who=r.get("who"), t=r.get("t"))
        if r.get("who"):
            by_who.setdefault(r["who"], []).append(r["text"])
    import os
    if (negotiation_mode or os.environ.get('PLANBEE_NEGOTIATION_MODE')) == 'candidate_discussion' and by_who:
        from .candidates import engine
        b=board(db);hive.schedule(b)
        issue='\n'.join(text for texts in by_who.values() for text in texts)
        possible=[t for t in b.tasks.values() if t.who in by_who and not t.cut and t.kind not in ('done','milestone','prop')]
        if task_id:
            possible=[t for t in possible if t.id==task_id]
            if not possible:raise ValueError('시나리오의 대상 Task와 요청자가 일치하지 않음')
        def relevance(t):
            words=[w for w in t.title.replace('·',' ').split() if len(w)>1]
            score=100*(t.title in issue)+20*(t.tag in issue)+sum(w in issue for w in words)
            return (-score, not (t.s<=b.now<t.s+t.d),t.s,t.id)
        possible.sort(key=relevance)
        if not possible:
            hive_say(db,'새 기록을 받았지만 이 담당자의 재설계할 미완료 업무가 없습니다. 다른 Task를 직접 선택해 주세요.')
            if phase_after:set_meta(db,'phase',phase_after)
            return None
        return engine.start(db,possible[0].id,issue,phase_after=phase_after)
    last = None
    for who, texts in by_who.items():
        run = Run(kind="record", step="ingest", auto_confirm=auto_confirm,
                  ctx={"who": who, "records": texts, "phase_after": phase_after, "demo_step":meta(db,"demo_step",None)})
        db.add(run)
        db.flush()
        last = drive(db, run)
    return last


def retry_negotiation(db, run_id, auto_confirm=False):
    """Resume the same deadline discussion with its public history and extra budget."""
    from copy import deepcopy
    run=db.get(Run,run_id)
    if not run or run.kind!='record' or run.status!='waiting_pm':
        raise ValueError('PM 검토에서 멈춘 협상만 재개할 수 있음')
    other=db.scalars(select(Run).where(Run.id!=run_id,Run.status.in_(['waiting_pm','waiting_confirm']))).first()
    if other:raise ValueError('다른 진행 중 협상을 먼저 마쳐야 함')
    if run.ctx.get('round',0)>=rule(db,'rounds')['max']:
        raise ValueError('기록과 규칙에서 최대 라운드를 현재 라운드보다 크게 늘려 주세요')
    snap(db)
    state=deepcopy(run.ctx.get('discussion'))
    if state:
        state.update(termination=None,rejected=True,consents={},revision_consulted=[])
        patch(run,discussion=state)
    else:
        from .discussion import begin_whole
        if not begin_whole(db,run):raise ValueError('재개할 참여자를 찾지 못함')
    for ask in db.scalars(select(Ask).where(Ask.run_id==run.id,Ask.open.is_(True))):
        ask.open=False;ask.chosen='retry'
    run.auto_confirm=auto_confirm
    run.step='bids';run.status='running'
    set_meta(db,'phase','run')
    return drive(db,run)


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


def reject(db: Session, ask_id: int, reason: str, keys: list[str] | None = None) -> Run:
    """PM 이 선택지를 이유와 함께 거절한다. 거절한 것은 다시 나오지 않고, 프록시들이 그 이유를 받아 한 번 더 협상한다."""
    a = db.get(Ask, ask_id)
    if not a or not a.open:
        raise ValueError("이미 닫혔거나 없는 PM 확인")
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("거절 이유를 적어야 함")
    chosen = [g for g in a.grants if not keys or g["key"] in keys]
    if not chosen or (keys and len(chosen) != len(set(keys))):
        raise ValueError("거절할 선택지가 없음")
    snap(db)
    a.open, a.chosen = False, "reject"
    bump_decisions(db)
    labels = [g["short"] for g in chosen]
    t = stamp(db)
    add_record(db, "PM", f"거절 · {', '.join(labels)} · 이유: {reason}", t=t)
    hist(db, a.hid, "pm", f"거절 · {', '.join(labels)} · {reason}", t=t)
    run = db.get(Run, a.run_id)
    ctx = run.ctx
    store.mark(ctx.get("round", 0), ctx.get("attempt", 0))
    pm_say(db, f"거절 · {', '.join(labels)} · 이유: {reason}", hid=a.hid)
    patch(run, banned=ctx.get("banned", []) + [g["key"] for g in chosen],
          pm_reasons=ctx.get("pm_reasons", []) + [{"keys": [g["key"] for g in chosen], "labels": labels, "reason": reason}],
          discussion=None, replies=None, round=0, quiet=True, recv={}, attempt=ctx.get("attempt", 0) + 1)
    store.mark(0, run.ctx["attempt"])
    hive_say(db, "PM 이 거절함 · 프록시들이 이유를 받아 다시 답하는 중", hid=a.hid, run_id=run.id)
    narr(db, "PM 이 거절함 · 프록시들이 다시 답하는 중")
    set_meta(db, "phase", "run")
    run.step = "bids"
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
    # 이 Handoff 에 PM 확인이 열려 있으면, 허락 대신 약속을 늦추는 쪽을 고른 것이다: 그 협상은 여기서 끝난다
    open_ask = db.scalars(select(Ask).where(Ask.hid == hid, Ask.open.is_(True))).first()
    if open_ask:
        open_ask.open, open_ask.chosen = False, "reagree"
        old = db.get(Run, open_ask.run_id)
        if old:
            old.step, old.status = "done", "done"
            set_meta(db, "phase", old.ctx.get("phase_after") or "end")
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
    if not t or t.cut or t.kind in ("done", "milestone"):
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
