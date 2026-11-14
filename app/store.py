"""DB 연결, 시드 적재, 판(Board) 읽기, 기록 도우미, 되돌리기."""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from . import hive
from .models import (SNAPSHOT_TABLES, Ask, Base, Card, Confirmation, Grant, Handoff, HandoffEvent,
                     Message, Meta, Person, Record, Resolution, Rule, Run, Snapshot, Task)

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "seed"


def make_engine(url: str | None = None):
    url = url or os.environ.get("PLANBEE_DB", f"sqlite:///{ROOT / 'planbee.db'}")
    kw = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    if url in ("sqlite://", "sqlite:///:memory:"):
        kw["poolclass"] = StaticPool
    eng = create_engine(url, **kw)
    Base.metadata.create_all(eng)
    return eng


def make_session_factory(engine):
    return sessionmaker(engine, expire_on_commit=False, autoflush=True)


def load_yaml(name: str) -> dict:
    return yaml.safe_load((SEED / name).read_text(encoding="utf-8"))


# ── 시드 ──────────────────────────────────────────────────────────────
def reset(db: Session) -> None:
    """모든 표를 비우고 seed/team.yaml 로 다시 채운다."""
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
                    gives_help=c.get("gives_help", True), note=c.get("note", "")))
    roles = {p["id"]: p["role"] for p in data["people"]}
    for i, t in enumerate(data["tasks"]):
        db.add(Task(id=t["id"], who=t["who"], title=t["title"], s0=t["s0"], s=t["s0"], d=t["d"],
                    plan=t["d"], base=t["d"], tag=t["tag"], role=roles[t["who"]], kind=t.get("kind", ""),
                    oi=i, cut_options=t.get("cut_options", [])))
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
            "gives_help": c.gives_help, "note": c.note}


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
                      week_end=rule(db, "deadline")["week_end"], now=meta(db, "now", 2))


# ── 쓰기 도우미 ───────────────────────────────────────────────────────
def stamp(db: Session) -> str:
    """시연용 시계. 그날 아침 9시 10분부터 메시지 하나에 1분씩 간다."""
    now = meta(db, "now", 2)
    day = hive.DAY[min(4, int(now))]
    n = db.scalar(select(func.count()).select_from(Message).where(Message.t.like(f"{day} %"))) or 0
    minutes = 9 * 60 + 10 + n
    return f"{day} {minutes // 60:02d}:{minutes % 60:02d}"


def F(t):   # 일반 값
    return {"t": str(t)}


def N(t):   # 숫자 · 시각
    return {"t": str(t), "n": True}


def TK(t):  # 일 이름
    return {"t": str(t), "tk": True}


def say(db, frm, act, fields, to=None, basis="", pref="", say="", hid=None, run_id=None) -> Message:
    m = Message(k="proxy", frm=frm, to=to, act=act, fields=fields, basis=basis, pref=pref, say=say,
                hid=hid, run_id=run_id, t=stamp(db))
    db.add(m)
    db.flush()
    return m


def hive_say(db, text, hid=None, run_id=None) -> Message:
    m = Message(k="hive", text=text, hid=hid, run_id=run_id, t=stamp(db))
    db.add(m)
    db.flush()
    return m


def pm_say(db, text, hid=None) -> Message:
    m = Message(k="pm", text=text, hid=hid, t=stamp(db))
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
                "basis": m.basis, "pref": m.pref, "say": m.say, "hid": m.hid, "t": m.t}
    return {"id": m.id, "k": m.k, "text": m.text, "who": m.who, "hid": m.hid, "t": m.t}


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
        out["ask"] = ask_json(ask) if ask else None
        res = db.scalars(select(Resolution).where(Resolution.hid == h.id).order_by(Resolution.id.desc())).first()
        out["resolved"] = {"body": res.body, "why": res.why} if res else None
        out["can_reagree"] = st == "risk" and not ask
    return out


def ask_json(a: Ask) -> dict:
    return {"id": a.id, "hid": a.hid, "open": a.open, "why": a.why, "chosen": a.chosen,
            "grants": [{"key": g["key"], "label": g["label"], "effect": g["effect"]} for g in a.grants]}


def confirm_json(c: Confirmation) -> dict:
    return {"id": c.id, "who": c.who, "prompt": c.prompt, "text": c.text, "hid": c.hid,
            "status": c.status, "t": c.t}


def state_json(db: Session) -> dict:
    """프로토타입의 S 와 같은 모양. 세 화면이 이것 하나로 다시 그려진다."""
    b = board(db)
    hive.schedule(b)
    tasks = {}
    for tid, t in b.tasks.items():
        tasks[tid] = {
            "id": tid, "who": t.who, "who0": t.who0, "title": t.title, "s0": t.s0, "s": t.s, "d": t.d,
            "plan": t.plan, "base": t.base, "tag": t.tag, "role": t.role, "kind": t.kind, "cut": t.cut,
            "got": t.got, "oi": t.oi,
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
    return {
        "phase": meta(db, "phase"), "now": b.now, "narr": meta(db, "narr"),
        "now_label": "1주차 · " + ("수요일 오전" if b.now < 3 else "목요일 오전"),
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
        "asks": [ask_json(a) for a in db.scalars(select(Ask).order_by(Ask.id))],
        "resolved": [{"hid": r.hid, "body": r.body, "why": r.why} for r in db.scalars(select(Resolution).order_by(Resolution.id))],
        "stats": {"msgs": sum(1 for m in msgs if m.k == "proxy"), "pm_direct_asks": 0,
                  "confirms": sum(1 for c in confirms if c.status == "confirmed"),
                  "decisions": meta(db, "decisions", 0)},
        "gate": hive.gate(b),
        "waiting": [{"run": r.id, "kind": r.kind, "status": r.status} for r in runs],
        "can_undo": can_undo(db),
    }
