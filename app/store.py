"""DB 연결, 시드 적재, 판(Board) 읽기, 기록 도우미, 되돌리기."""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from sqlalchemy import create_engine, delete, func, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from . import hive
from .models import (SNAPSHOT_TABLES, Ask, Base, Card, Confirmation, Grant, Handoff, HandoffEvent,
                     Message, Meta, Person, Record, Resolution, Rule, Run, Snapshot, Task)

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "seed"
DEFAULT_DEMO = yaml.safe_load((SEED/'catalog.yaml').read_text(encoding='utf-8'))['default']
DEMO = os.environ.get("PLANBEE_DEMO", DEFAULT_DEMO)


def demos() -> list[str]:
    return sorted(p.name for p in SEED.iterdir() if (p / "team.yaml").exists())


def service_demos() -> list[str]:
    """Published scenarios; archived seeds remain available to regression tools."""
    config = yaml.safe_load((SEED / 'catalog.yaml').read_text(encoding='utf-8'))
    return list(config['scenarios'])


def demo_catalog(include_archived=False):
    out = []
    for demo in (demos() if include_archived else service_demos()):
        data = yaml.safe_load((SEED / demo / 'team.yaml').read_text(encoding='utf-8'))
        info = data.get('meta', {})
        feed = yaml.safe_load((SEED / demo / 'feed.yaml').read_text(encoding='utf-8')) or {}
        out.append(dict(id=demo, title=info.get('title', demo), summary=info.get('summary', ''),
            people=len(data['people']), tasks=len(data['tasks']), steps=len(feed),
            scenario_doc='DEMOS.md', scenario_anchor=demo,
            scenario_url=f'/scenario.html?demo={demo}',scenario_source_url=f'/demos/{demo}/scenario'))
    return out


def use_demo(name: str) -> None:
    """다른 데모로 바꾼다. 바꾼 뒤 reset() 을 불러야 그 데모의 데이터로 채워진다."""
    global DEMO
    if name not in demos():
        raise ValueError(f"없는 데모: {name} (있는 것: {', '.join(demos())})")
    DEMO = name
    from . import llm
    llm.set_llm(None)      # Mock 대본도 데모마다 다르다


def make_engine(url: str | None = None):
    url = url or os.environ.get("PLANBEE_DB", f"sqlite:///{ROOT / f'planbee_{DEMO}.db'}")
    kw = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    if url in ("sqlite://", "sqlite:///:memory:"):
        kw["poolclass"] = StaticPool
    eng = create_engine(url, **kw)
    # Add the new JSON fields in place. Never drop a user's existing schedules.
    insp = inspect(eng)
    for name, table in Base.metadata.tables.items():
        if not insp.has_table(name):
            continue
        actual = {c["name"] for c in insp.get_columns(name)}
        expected = {c.name for c in table.columns}
        missing = expected - actual
        if actual - expected or missing - ({"context"} if name == "task" else {"policy"} if name == "card" else set()):
            raise RuntimeError(f"지원하지 않는 DB 스키마 차이: {name}; 데이터는 보존했습니다")
        if missing:
            with eng.begin() as conn:
                for col in missing:
                    conn.execute(text(f"""ALTER TABLE "{name}" ADD COLUMN "{col}" JSON NOT NULL DEFAULT '{{}}'"""))
    Base.metadata.create_all(eng)
    return eng


def make_session_factory(engine):
    return sessionmaker(engine, expire_on_commit=False, autoflush=True)


def load_yaml(name: str) -> dict:
    return yaml.safe_load((SEED / DEMO / name).read_text(encoding="utf-8"))


# ── 시드 ──────────────────────────────────────────────────────────────
def reset(db: Session) -> None:
    from . import progress
    progress.clear()
    """모든 표를 비우고 seed/<데모>/team.yaml 로 다시 채운다."""
    for m in SNAPSHOT_TABLES + [Snapshot]:
        db.execute(delete(m))
    data = load_yaml("team.yaml")
    for i, p in enumerate(data["people"]):
        db.add(Person(id=p["id"], name=p["name"], role=p["role"], rec=p.get("rec", {}),
                      wants=p.get("wants", []), notes=p.get("notes", {}), oi=i))
    db.flush()
    cards = {c["who"]: c for c in data.get("cards", [])}
    for p in data["people"]:
        c = cards.get(p["id"], {})
        db.add(Card(person_id=p["id"], auto_days=c.get("auto_days", 1), refuse_tags=c.get("refuse_tags", []),
                    gives_help=c.get("gives_help", True), note=c.get("note", ""), wait_days=c.get("wait_days", 0),
                    model=c.get("model"), policy=c.get("policy", {})))
    roles = {p["id"]: p["role"] for p in data["people"]}
    for i, t in enumerate(data["tasks"]):
        db.add(Task(id=t["id"], who=t["who"], title=t["title"], s0=t["s0"], s=t["s0"], d=t["d"],
                    plan=t["d"], base=t["d"], tag=t["tag"], role=roles[t["who"]], kind=t.get("kind", ""),
                    oi=i, cut_options=t.get("cut_options", []), context=t.get("context", {})))
    db.flush()
    for i, h in enumerate(data["handoffs"]):
        db.add(Handoff(id=h["id"], from_task=h["from"], to_task=h["to"], title=h["title"], what=h["what"],
                       t=h["t"], done=h.get("done", False), oi=i))
        for e in h.get("hist", []):
            db.add(HandoffEvent(handoff_id=h["id"], t=e["t"], kind=e["kind"], who=e.get("who"), text=e["text"]))
    for r in data["records"]:
        db.add(Record(t=r["t"], src=r["src"], who=r.get("who"), text=r["text"], old=r.get("old", False)))
    for i, r in enumerate(data["rules"]):
        db.add(Rule(key=r["key"], label=r["label"], value=r["value"], locked=r.get("locked", True), oi=i))
    for k, v in data["meta"].items():
        db.add(Meta(key=k, value={"v": v}))
    db.add(Meta(key="decisions", value={"v": 0}))
    db.add(Meta(key="demo", value={"v": DEMO}))
    db.flush()
    b = board(db)
    hive.schedule(b)
    db.flush()


def is_empty(db: Session) -> bool:
    """비었거나, 위임 카드가 생기기 전의 옛 DB 이면 다시 채워야 한다."""
    return (db.scalar(select(func.count()).select_from(Person)) == 0
            or db.scalar(select(func.count()).select_from(Card)) == 0 or db.get(Rule, "rounds") is None)


def card(db: Session, pid: str) -> Card:
    c = db.get(Card, pid)
    if not c:
        c = Card(person_id=pid)
        db.add(c)
        db.flush()
    return c


def card_json(c: Card) -> dict:
    return {"who": c.person_id, "auto_days": c.auto_days, "refuse_tags": c.refuse_tags,
            "gives_help": c.gives_help, "note": c.note, "wait_days": c.wait_days, "model": c.model, "policy": c.policy}


# ── 읽기 ──────────────────────────────────────────────────────────────
def meta(db: Session, key: str, default=None):
    m = db.get(Meta, key)
    return m.value["v"] if m else default


def set_meta(db: Session, key: str, v) -> None:
    m = db.get(Meta, key)
    if m:
        m.value = {"v": v}
    else:
        db.add(Meta(key=key, value={"v": v}))


def rule(db: Session, key: str) -> dict:
    return db.get(Rule, key).value


def board(db: Session) -> hive.Board:
    """DB의 일 · Handoff 를 Hive가 계산할 수 있는 판으로 묶는다. 객체는 DB 행 그대로라 고치면 저장된다."""
    people = {p.id: p for p in db.scalars(select(Person).order_by(Person.oi))}
    tasks = {t.id: t for t in db.scalars(select(Task).order_by(Task.oi))}
    hands = {h.id: h for h in db.scalars(select(Handoff).order_by(Handoff.oi))}
    return hive.Board(people, tasks, hands, cap=rule(db, "weekly_cap")["days"],
                      week_end=rule(db, "deadline")["week_end"], now=meta(db, "now", 2),
                      extra={"policies": {pid: card(db, pid).policy or {} for pid in people}})


# ── 쓰기 도우미 ───────────────────────────────────────────────────────
def stamp(db: Session) -> str:
    """시연용 시계. 그날 아침 9시 10분부터 메시지 하나에 1분씩 간다."""
    now = meta(db, "now", 2)
    day = (f'{int(now)//5+1}주차 ' if now>=5 else '')+hive.DAY[int(now)%5]
    n = db.scalar(select(func.count()).select_from(Message).where(Message.t.like(f"{day} %"))) or 0
    minutes = 9 * 60 + 10 + n
    return f"{day} {minutes // 60:02d}:{minutes % 60:02d}"


def F(t):   # 일반 값
    return {"t": str(t)}


def N(t):   # 숫자 · 시각
    return {"t": str(t), "n": True}


def TK(t):  # 일 이름
    return {"t": str(t), "tk": True}


MARK = {"round": None, "attempt": 0}


def mark(rnd, attempt=0) -> None:
    """지금부터 남기는 말이 몇 라운드 것인지 표시한다 (협상 보기용)."""
    MARK["round"], MARK["attempt"] = rnd, attempt


def say(db, frm, act, fields, to=None, basis="", pref="", say="", hid=None, run_id=None) -> Message:
    m = Message(k="proxy", frm=frm, to=to, act=act, fields=fields, basis=basis, pref=pref, say=say,
                hid=hid, run_id=run_id, t=stamp(db), round=MARK["round"], attempt=MARK["attempt"])
    db.add(m)
    db.flush()
    return m


def hive_say(db, text, hid=None, run_id=None) -> Message:
    m = Message(k="hive", text=text, hid=hid, run_id=run_id, t=stamp(db), round=MARK["round"], attempt=MARK["attempt"])
    db.add(m)
    db.flush()
    return m


def pm_say(db, text, hid=None, run_id=None) -> Message:
    m = Message(k="pm", text=text, hid=hid, run_id=run_id, t=stamp(db), round=MARK["round"], attempt=MARK["attempt"])
    db.add(m)
    db.flush()
    return m


def add_record(db, src, text, who=None, t=None) -> Record:
    for r in db.scalars(select(Record).where(Record.fresh.is_(True))):
        r.fresh = False
    r = Record(t=t or stamp(db), src=src, who=who, text=text, fresh=True)
    db.add(r)
    db.flush()
    return r


def hist(db, hid, kind, text, who=None, t=None) -> None:
    db.add(HandoffEvent(handoff_id=hid, t=t or stamp(db), kind=kind, who=who, text=text))
    db.flush()


def bump_decisions(db) -> None:
    set_meta(db, "decisions", meta(db, "decisions", 0) + 1)


def narr(db, text) -> None:
    set_meta(db, "narr", text)


def next_id(db, model, prefix: str) -> str:
    n = db.scalar(select(func.count()).select_from(model)) + 1
    while db.get(model, f"{prefix}{n}"):
        n += 1
    return f"{prefix}{n}"


def next_oi(db, model) -> int:
    return (db.scalar(select(func.max(model.oi))) or 0) + 1


# ── 되돌리기 ──────────────────────────────────────────────────────────
def snap(db: Session) -> None:
    db.flush()
    data = {}
    for m in SNAPSHOT_TABLES:
        cols = [c.name for c in m.__table__.columns]
        data[m.__tablename__] = [{c: getattr(row, c) for c in cols} for row in db.scalars(select(m))]
    db.add(Snapshot(data=data))
    db.flush()


def undo(db: Session) -> bool:
    last = db.scalars(select(Snapshot).order_by(Snapshot.id.desc()).limit(1)).first()
    if not last:
        return False
    data = last.data
    db.delete(last)
    for m in reversed(SNAPSHOT_TABLES):
        db.execute(delete(m))
    db.flush()
    db.expunge_all()
    for m in SNAPSHOT_TABLES:
        for row in data.get(m.__tablename__, []):
            db.add(m(**row))
        db.flush()
    narr(db, "되돌렸습니다")
    return True


def can_undo(db: Session) -> bool:
    return (db.scalar(select(func.count()).select_from(Snapshot)) or 0) > 0


# ── 화면에 내보내는 모양 ──────────────────────────────────────────────
def msg_json(m: Message) -> dict:
    if m.k == "proxy":
        return {"id": m.id, "k": "proxy", "from": m.frm, "to": m.to, "a": m.act, "f": m.fields,
                "basis": m.basis, "pref": m.pref, "say": m.say, "hid": m.hid, "t": m.t, "run": m.run_id, "round": m.round}
    return {"id": m.id, "k": m.k, "text": m.text, "who": m.who, "hid": m.hid, "t": m.t, "run": m.run_id, "round": m.round}


def negotiation_json(db: Session, run: Run, detail: bool = True) -> dict:
    """협상 한 건을 라운드별로 묶어 보여 준다: 제안, 프록시들의 답, 오간 말, 기다리는 것."""
    ctx = run.ctx
    out = {"id": run.id, "kind": run.kind, "status": run.status, "step": run.step, "hid": ctx.get("hid"),
           "task": ctx.get("task"), "owner": ctx.get("who"), "round": ctx.get("round", 0), "attempt": ctx.get("attempt", 0),
           "max_rounds": rule(db, "rounds")["max"]}
    out["pm_handoff"] = ctx.get("pm_handoff")
    out["llm_budget"] = ctx.get("llm_budget")
    out["workflow_stage"] = ctx.get("workflow_stage")
    out["stage_history"] = ctx.get("stage_history", [])
    out["demo_step"] = ctx.get("demo_step")
    out["llm_mode"] = ctx.get("llm_mode")
    out["llm_modes"] = ctx.get("llm_modes",[])
    out["transcript_origin"] = ctx.get("transcript_origin")
    out["transcript_file"] = ctx.get("transcript_file")
    out["negotiation_stage"] = ctx.get("negotiation_stage")
    out["feasible_baseline"] = ctx.get("feasible_baseline")
    out["discussion"] = ctx.get("discussion")
    out["discussion_archive"] = ctx.get("discussion_archive", [])
    if not detail:
        return out
    msgs = list(db.scalars(select(Message).where(Message.run_id == run.id).order_by(Message.id)))
    groups: list[dict] = []
    for m in msgs:
        key = (m.attempt, m.round or 0)
        if not groups or groups[-1]["key"] != key:
            groups.append({"key": key, "attempt": m.attempt, "round": m.round or 0, "messages": [],
                           "label": ("준비" if not m.round else f"{m.round}라운드") + (f" · PM 답 {m.attempt}회 뒤" if m.attempt else "")})
        groups[-1]["messages"].append(msg_json(m))
    for g in groups:
        del g["key"]
    ask = db.scalars(select(Ask).where(Ask.run_id == run.id).order_by(Ask.id.desc())).first()
    out.update({
        "initial_milestones": ctx.get("initial_milestones"),
        "constraint_evaluation": ctx.get("constraint_evaluation"),
        "execution_turns": ctx.get("execution_turns", []),
        "discussion": ctx.get("discussion"),
        "fairness_before": ctx.get("fairness_before"),
        "fairness_after": ctx.get("fairness_after"),
        "proposal": ctx.get("split"),
        "replies": ctx.get("replies") or [],
        "chosen": ctx.get("chosen"),
        "rounds": groups,
        "pending_confirms": [confirm_json(c) for c in db.scalars(
            select(Confirmation).where(Confirmation.run_id == run.id, Confirmation.status == "pending").order_by(Confirmation.id))],
        "ask": ask_json(ask,db) if ask else None,
    })
    return out


def hand_json(db: Session, b: hive.Board, h: Handoff, detail: bool = False) -> dict:
    st = hive.h_state(b, h)
    a, c = b.tasks[h.from_task], b.tasks[h.to_task]
    out = {
        "id": h.id, "from": h.from_task, "to": h.to_task, "from_who": a.who, "to_who": c.who,
        "title": h.title, "what": h.what, "t": h.t, "t_label": hive.when(h.t),
        "pred": hive.pred(b, h), "pred_label": hive.when(hive.pred(b, h)),
        "state": st, "state_label": hive.STATE_NAME[st],
        "done": h.done, "prop": h.prop, "agreed": h.agreed, "basis": h.basis,
        "hist": [{"t": e.t, "kind": e.kind, "who": e.who, "text": e.text} for e in
                 db.scalars(select(HandoffEvent).where(HandoffEvent.handoff_id == h.id).order_by(HandoffEvent.id))],
    }
    if detail:
        live = {k: x for k, x in b.hands.items() if hive.h_state(b, x) != "cut"}
        out["up"] = [k for k, x in live.items() if x.to_task == h.from_task]       # 앞 단계
        out["down"] = [k for k, x in live.items() if x.from_task == h.to_task]     # 늦으면 영향 받는 곳
        out["msgs"] = [msg_json(m) for m in db.scalars(select(Message).where(Message.hid == h.id).order_by(Message.id))]
        ask = db.scalars(select(Ask).where(Ask.hid == h.id, Ask.open.is_(True))).first()
        out["ask"] = ask_json(ask,db) if ask else None
        res = db.scalars(select(Resolution).where(Resolution.hid == h.id).order_by(Resolution.id.desc())).first()
        out["resolved"] = {"body": res.body, "why": res.why} if res else None
        out["can_reagree"] = st == "risk" and not ask
    return out


def ask_json(a: Ask, db=None) -> dict:
    run=db.get(Run,a.run_id) if db and a.run_id else None
    summary=(run.ctx.get('pm_handoff') or {}).get('summary') if run else None
    if run and summary is None:
        # Older persisted PM requests remain inspectable after an app upgrade.
        from .pm_summary import build
        summary=build(db,run,a.why,a.grants)
    return {"id": a.id, "hid": a.hid, "run": a.run_id, "open": a.open, "why": a.why, "chosen": a.chosen,
            "summary": summary,
            "grants": [{"key": g["key"], "label": g["label"], "effect": g["effect"], "preview": g.get("preview")} for g in a.grants]}


def confirm_json(c: Confirmation) -> dict:
    return {"id": c.id, "who": c.who, "prompt": c.prompt, "text": c.text, "hid": c.hid,
            "status": c.status, "t": c.t}


def workflow_progress(db):
    from . import stages
    runs=list(db.scalars(select(Run).order_by(Run.id)))
    run=runs[-1] if runs else None
    timeline=[dict(stage=t.get('stage') or stages.for_node(r,t['node']),
                   message_after=t['message_after'],message_through=t['message_through'],round=t['round'])
              for r in runs for t in r.ctx.get('execution_turns',[])]
    return dict(stages=stages.STAGES,
        current=(run.ctx.get('workflow_stage') or stages.for_node(run,run.step)) if run else stages.STAGES[0],
        visited=run.ctx.get('stage_history',[]) if run else [],
        status=run.status if run else 'ready', round=run.ctx.get('round',0) if run else 0,
        run_id=run.id if run else None,timeline=timeline,
        pm_handoff=(run.ctx.get('pm_handoff') if run and (run.status=='waiting_pm' or
            (run.status=='done' and (run.ctx.get('discussion') or {}).get('termination') not in (None,'agreement'))) else None))


def state_json(db: Session) -> dict:
    """프로토타입의 S 와 같은 모양. 세 화면이 이것 하나로 다시 그려진다."""
    b = board(db)
    hive.schedule(b)
    tasks = {}
    for tid, t in b.tasks.items():
        tasks[tid] = {
            "id": tid, "who": t.who, "who0": t.who0, "title": t.title, "s0": t.s0, "s": t.s, "d": t.d,
            "plan": t.plan, "base": t.base, "tag": t.tag, "role": t.role, "kind": t.kind, "cut": t.cut,
            "got": t.got, "oi": t.oi, "context": t.context,
            "spill": t.s + t.d > b.week_end + hive.EPS and t.s < b.week_end,
            "moved": t.s >= b.week_end,
            "start_label": hive.when(t.s + 0.0001).replace(" 저녁", "").replace(" 오전", ""),
            "end_label": hive.when(t.s + t.d),
            "basis": hive.tag_line(b.people[t.who], t.tag),
        }
    people = [{"id": p.id, "name": p.name, "role": p.role, "rec": p.rec, "wants": p.wants,
               "load": hive.load_of(b, p.id), "free": b.cap - hive.load_of(b, p.id), "cap": b.cap}
              for p in b.people.values()]
    confirms = list(db.scalars(select(Confirmation).order_by(Confirmation.id)))
    msgs = list(db.scalars(select(Message).order_by(Message.id)))
    runs = list(db.scalars(select(Run).where(Run.status != "done")))
    from .timeline import describe
    timeline=describe(db,b)
    available=[e for e in (timeline or {}).get("events",[]) if e["available"]]
    return {
        "fairness": hive.fairness(b),
        "capacities": {pid: hive.capacity(b,pid) for pid in b.people},
        "phase": meta(db, "phase"), "now": b.now, "narr": meta(db, "narr"),
        "now_label": f"{int(b.now)//5+1}주차 · {hive.DAY[int(b.now)%5]}요일 {'오후' if b.now%1>=.5 else '오전'}",
        "week_end": b.week_end,
        "can_previous_day": bool(meta(db,"day_history",[])),
        "demo": {"id": meta(db,"demo",DEMO), "title": meta(db, "title", DEMO), "all": service_demos(), "catalog": demo_catalog(), "engine_support": meta(db,"engine_support",""), "source_task": meta(db,"source_task",None), "normalization_note": meta(db,"normalization_note",""),
                 "timeline": timeline, "issue_example": (available[0]["text"] if available else "") if timeline else '\n'.join(r['text'] for r in (load_yaml('feed.yaml').get('issue') or {}).get('records',[]))},
        "workflow_progress": workflow_progress(db),
        "demo_step": meta(db,"demo_step",None),
        "feed_label": ((load_yaml("feed.yaml").get(meta(db, "phase")) or {}).get("label")
                       or ("시연 · 다음 단계" if load_yaml("feed.yaml").get(meta(db, "phase")) else None)),
        "deadline_label": meta(db, "deadline_label"),
        "people": people,
        "tasks": tasks,
        "hand": {hid: hand_json(db, b, h) for hid, h in b.hands.items()},
        "recs": [{"id": r.id, "t": r.t, "src": r.src, "who": r.who, "text": r.text, "old": r.old, "fresh": r.fresh}
                 for r in db.scalars(select(Record).order_by(Record.id))],
        "rules": [{"key": r.key, "label": r.label, "value": r.value, "locked": r.locked}
                  for r in db.scalars(select(Rule).order_by(Rule.oi))],
        "pref": rule(db, "pref")["choice"],
        "cards": [card_json(card(db, p.id)) for p in b.people.values()],
        "max_rounds": rule(db, "rounds")["max"],
        "granted": [g.label for g in db.scalars(select(Grant).order_by(Grant.id))],
        "confirms": [confirm_json(c) for c in confirms if c.status == "confirmed"],
        "pending_confirms": [confirm_json(c) for c in confirms if c.status == "pending"],
        "log": [msg_json(m) for m in msgs],
        "asks": [ask_json(a,db) for a in db.scalars(select(Ask).order_by(Ask.id))],
        "resolved": [{"hid": r.hid, "body": r.body, "why": r.why} for r in db.scalars(select(Resolution).order_by(Resolution.id))],
        "stats": {"msgs": sum(1 for m in msgs if m.k == "proxy"), "pm_direct_asks": 0,
                  "confirms": sum(1 for c in confirms if c.status == "confirmed"),
                  "decisions": meta(db, "decisions", 0)},
        "gate": hive.gate(b),
        "waiting": [{"run": r.id, "kind": r.kind, "status": r.status} for r in runs],
        "negotiations": [negotiation_json(db, r, detail=False) for r in db.scalars(select(Run).where(Run.kind == "record").order_by(Run.id))],
        "can_undo": can_undo(db),
    }


# Register transcript persistence for workflow, human confirmations and bundle runs.
from . import runlogs as _runlogs
