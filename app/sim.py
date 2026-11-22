"""서버 없이 데모를 끝까지 돌리고 지표를 뽑는다. run_demo.py 와 evaluate.py 가 같이 쓴다.

비교 대상 두 가지도 여기 있다 (둘 다 LLM 없이 코드로 흉내 낸 것):
  push     늦어지면 뒤로 민다. 도움을 청하지 않고, 늦어진 약속을 전부 예상 시각으로 고친다.
  central  한 곳에서 계획을 다시 짠다. 조각을 가장 빨리 끝낼 사람에게 주되 위임 카드 · 한도 · 조건은 보지 않는다.
"""
from __future__ import annotations

from sqlalchemy import select

from . import hive, store, workflow, bundles
from .llm import default_bid_days, get_llm
from .models import Ask, Card, Confirmation, Handoff, Message, Rule, Run, Task


def _open(db):
    return db.scalars(select(Ask).where(Ask.open.is_(True))).first()


def _act(db, ask, pm: str) -> bool:
    """PM 정책대로 한 번 답한다. 답했으면 True."""
    keys = [g["key"] for g in ask.grants]
    kind, _, arg = pm.partition(":")
    if kind == "reject" and not getattr(_act, "rejected", False):
        hit = [k for k in keys if k.startswith(arg)] if arg else keys
        if hit:
            _act.rejected = True
            workflow.reject(db, ask.id, "이번 제출에 꼭 필요함", hit)
            return True
    if kind == "reagree" or not keys:
        workflow.reagree(db, ask.hid, auto_confirm=True)
        return True
    pick = next((k for k in keys if kind == "grant" and k.startswith(arg)), keys[0])
    workflow.grant(db, ask.id, pick)
    return True


def simulate(demo: str, pm: str = "first", pref: str = "fast", cards: dict | None = None, rounds: int | None = None,
             mode: str = "planbee", handoff_updates: dict | None = None):
    """mode: planbee · push · central.  돌려주는 값: (화면용 상태, 지표)"""
    old = store.DEMO
    store.use_demo(demo)
    try:
        engine = store.make_engine("sqlite://")
        with store.make_session_factory(engine)() as db:
            store.reset(db)
            db.get(Rule, "pref").value = {"choice": pref}
            if rounds:
                db.get(Rule, "rounds").value = {"max": rounds}
            for pid, change in (cards or {}).items():
                for k, v in change.items():
                    setattr(store.card(db, pid), k, v)
            for hid, change in (handoff_updates or {}).items():
                hand = db.get(Handoff, hid)
                if hand:
                    for key, value in change.items():
                        if key in {"t", "agreed", "done"}:
                            setattr(hand, key, value)
            b = store.board(db)
            plan = {tid: (t.who, t.s, t.d, t.title) for tid, t in b.tasks.items()}
            promised = {hid: h.t for hid, h in b.hands.items()}
            feed, extra = store.load_yaml("feed.yaml"), {"overrides": 0, "pm_talks": set()}
            _act.rejected = False
            while feed.get(store.meta(db, "phase")):
                f = feed[store.meta(db, "phase")]
                store.set_meta(db, "now", f["now"])
                store.set_meta(db, "phase", "run")
                if f.get("action") == "bundle":
                    run = bundles.propose(db, f["transfers"])
                    workflow.patch(run, phase_after=f["next_phase"])
                    for cid in run.ctx.get("waiting_for", []):
                        workflow.apply_confirm(db, db.get(Confirmation, cid))
                    bundles.resume(db, run)
                elif mode == "planbee":
                    workflow.start_records(db, f["records"], auto_confirm=True, phase_after=f["next_phase"])
                    for _ in range(8):
                        ask = _open(db)
                        if not ask or not _act(db, ask, pm):
                            break
                else:
                    _baseline(db, f["records"], mode, extra)
                if store.meta(db, "phase") in ("run", "ask"):
                    store.set_meta(db, "phase", f["next_phase"])
            db.flush()
            s = store.state_json(db)
            return s, metrics(db, s, plan, promised, extra)
    finally:
        store.use_demo(old)


def _baseline(db, records, mode, extra) -> None:
    b = store.board(db)
    llm = get_llm()
    by_who: dict[str, list[str]] = {}
    for r in records:
        store.add_record(db, r["src"], r["text"], who=r.get("who"), t=r.get("t"))
        by_who.setdefault(r["who"], []).append(r["text"])
    for who, texts in by_who.items():
        mine = [t for t in b.tasks.values() if t.who == who and not t.cut and t.kind not in ("done", "milestone")]
        ans = llm.reestimate(b.people[who], texts, mine)
        if not ans or ans.task not in {t.id for t in mine}:
            continue
        t = b.tasks[ans.task]
        t.d = ans.days
        hive.schedule(b)
        late = [h for h in b.hands.values() if h.from_task == t.id and hive.h_state(b, h) == "risk"]
        if mode == "central" and late:
            split = llm.split(b.people[who], t, hive.pred(b, late[0]) - late[0].t)
            if split:
                # 가장 빨리 끝낼 사람에게 준다. 카드 · 한도 · 조건은 보지 않는다
                cands = [p for p in b.people.values() if p.role == (split.piece.role or t.role) and p.id != who]
                pick = min(cands, key=lambda p: (default_bid_days(b, split.piece, p.id, who), p.oi))
                days = default_bid_days(b, split.piece, pick.id, who)
                cd = store.card(db, pick.id)
                if days > cd.auto_days + hive.EPS or split.piece.tag in (cd.refuse_tags or []):
                    extra["overrides"] += 1          # 본인이 맡기지 않은 범위를 대신 정함
                target = b.tasks[late[0].to_task] if split.to == "downstream" else t
                tid, hid = store.next_id(db, Task, "piece"), store.next_id(db, Handoff, "h")
                db.add(Task(id=tid, who=pick.id, title=split.piece.title, s0=b.now, s=b.now, d=days, plan=days, base=split.piece.days,
                            tag=split.piece.tag, role=split.piece.role or t.role, kind="new", oi=store.next_oi(db, Task)))
                db.flush()
                db.add(Handoff(id=hid, from_task=tid, to_task=target.id, title=split.piece.title, what=split.piece.what, t=b.now + days,
                               agreed=True, oi=store.next_oi(db, Handoff)))
                t.d = t.plan = (split.keep.days if split.keep and split.keep.days else None) or max(0.5, t.d - split.piece.days)
                db.flush()
                extra["pm_talks"] |= {pick.id, who, target.who}   # 계획을 받은 뒤 각자 승인해야 하는 사람
                b = store.board(db)
                hive.schedule(b)
        for h in b.hands.values():      # 그래도 늦는 약속은 예상 시각으로 고쳐 통보
            if hive.h_state(b, h) == "risk":
                extra["pm_talks"] |= {b.tasks[h.from_task].who, b.tasks[h.to_task].who}
                h.t, h.agreed = hive.pred(b, h), True
        hive.schedule(b)
    db.flush()


def metrics(db, s, plan, promised, extra) -> dict:
    """한 번 돌린 결과를 숫자로. cost 는 사람별로 떠안은 것: 이번 주에 늘어난 일수(+)와 2주차로 밀린 일수(밀림)."""
    b = store.board(db)
    hive.schedule(b)
    msgs = list(db.scalars(select(Message)))
    runs = list(db.scalars(select(Run).where(Run.kind == "record")))
    cost = {}
    for p in b.people.values():
        added = sum(t.d for t in b.tasks.values() if t.who == p.id and not t.cut and t.id not in plan and t.s < b.week_end)
        grown = sum(max(0.0, t.d - plan[tid][2]) for tid, t in b.tasks.items() if tid in plan and t.who == p.id and not t.cut and t.s < b.week_end)
        pushed = sum(t.d for tid, t in b.tasks.items() if tid in plan and t.who == p.id and not t.cut
                     and t.s >= b.week_end - hive.EPS and plan[tid][1] < b.week_end - hive.EPS)
        if added or grown or pushed:
            cost[p.name] = {"늘어남": round(added + grown, 1), "밀림": round(pushed, 1)}
    total = sum(v["늘어남"] + v["밀림"] for v in cost.values())
    top = max(cost.items(), key=lambda kv: kv[1]["늘어남"] + kv[1]["밀림"], default=None)
    gate = hive.gate(b)
    return {
        "pm_decisions": s["stats"]["decisions"],
        "pm_talks": len(extra["pm_talks"]),                      # PM 이 직접 알리거나 승인받아야 하는 사람 수
        "confirms": s["stats"]["confirms"],
        "proxy_msgs": s["stats"]["msgs"],
        "rounds": sum(sum(1 for m in msgs if m.k == "hive" and m.run_id == r.id and "라운드 · " in m.text) for r in runs),
        "hive_rejects": sum(1 for m in msgs if m.k == "hive" and m.text.startswith("반려")),
        "late_end": len(hive.risks(b)),                          # 끝났을 때 아직 늦을 약속
        "promises_moved": sum(1 for hid, h in b.hands.items() if hid in promised and abs(h.t - promised[hid]) > hive.EPS),
        "past_deadline": sum(1 for w in gate["warnings"]),       # 제출일을 넘기거나 뒤로 밀린 일
        "scope_cut": sum(1 for g in s["granted"] if "2주차" not in g),
        "overload": sum(1 for v in gate["violations"] if v["code"] == "OVERLOAD"),
        "overrides": extra["overrides"],                         # 본인의 위임 카드를 넘겨 대신 정한 횟수
        "cost": cost,
        "cost_people": len(cost),
        "top_share": round((top[1]["늘어남"] + top[1]["밀림"]) / total, 2) if top and total else 0.0,
        "top_who": top[0] if top else "",
        "fairness": hive.fairness(b),
    }
