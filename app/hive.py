"""Hive: 규칙대로 계산만 하는 코드. LLM을 부르지 않는다.

프로토타입의 schedule / hState / pred / loadOf / est / preview 를 그대로 옮겼다.
시간 단위는 '일'. 0 = 1주차 월 아침, 5 = 2주차 월 아침(= 금 저녁).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from types import SimpleNamespace

EPS = 1e-9
DAY = ["월", "화", "수", "목", "금"]
STATE_NAME = {"ok": "On track", "risk": "At risk", "prop": "Proposed",
              "agreed": "Agreed", "done": "Delivered", "cut": "Cut"}

TASK_FIELDS = ["id", "who", "who0", "title", "s0", "s", "d", "plan", "base", "tag", "role",
               "kind", "oi", "cut", "got", "cut_options"]
HAND_FIELDS = ["id", "from_task", "to_task", "title", "what", "t", "done", "prop", "agreed",
               "basis", "oi"]


@dataclass
class Board:
    people: dict            # id -> Person 같은 객체 (name, role, rec, wants, oi)
    tasks: dict             # id -> Task 같은 객체
    hands: dict             # id -> Handoff 같은 객체
    cap: float = 5.0        # 한 사람 한 주 최대 일수
    week_end: float = 5.0   # 제출일 (금 저녁)
    now: float = 2.0
    extra: dict = field(default_factory=dict)

    def clone(self) -> "Board":
        """미리 보기용 복사본. DB 객체를 건드리지 않는다."""
        tasks = {k: SimpleNamespace(**{f: getattr(t, f) for f in TASK_FIELDS}) for k, t in self.tasks.items()}
        hands = {k: SimpleNamespace(**{f: getattr(h, f) for f in HAND_FIELDS}) for k, h in self.hands.items()}
        return Board(self.people, tasks, hands, self.cap, self.week_end, self.now)


# ── 표기 ──────────────────────────────────────────────────────────────
def when(t: float) -> str:
    k = math.floor(t + EPS)
    if abs(t - round(t)) > EPS:
        return ("2주차 " if k >= 5 else "") + DAY[k % 5] + " 오전"
    return ("2주차 " if k - 1 >= 5 else "") + DAY[(k - 1) % 5] + " 저녁"


def num(d: float) -> str:
    if abs(d - round(d)) > EPS:
        w = math.floor(d)
        return f"{w}½" if w else "½"
    return str(int(round(d)))


def has_final(word: str) -> bool:
    ch = word.strip()[-1]
    if "가" <= ch <= "힣":
        return (ord(ch) - 0xAC00) % 28 != 0
    return ch.lower() not in "aeiouy"


def josa(word: str, with_final: str, without: str) -> str:
    """한국어 조사 붙이기. josa("Sam", "이", "가") -> "Sam이" """
    return word + (with_final if has_final(word) else without)


# ── 일정 계산 ─────────────────────────────────────────────────────────
def schedule(b: Board) -> None:
    """각 일의 실제 시작 s 를 다시 계산한다. Handoff 순서와 한 사람 한 번에 한 일을 지킨다."""
    ids = [i for i, t in b.tasks.items() if not t.cut]
    for i in ids:
        b.tasks[i].s = b.tasks[i].s0
    for _ in range(40):
        changed = False
        for h in b.hands.values():
            a, c = b.tasks.get(h.from_task), b.tasks.get(h.to_task)
            if not a or not c or a.cut or c.cut:
                continue
            need = a.s + a.d
            if c.s < need - EPS:
                c.s, changed = need, True
        for pid in b.people:
            lane = sorted((b.tasks[i] for i in ids if b.tasks[i].who == pid), key=lambda t: (t.s0, t.oi))
            end = 0.0
            for t in lane:
                if t.s < end - EPS:
                    t.s, changed = end, True
                end = max(end, t.s + t.d)
        if not changed:
            break


def pred(b: Board, h) -> float:
    """주는 일이 실제로 끝나는 시각 = 이 Handoff의 예상 시각."""
    a = b.tasks[h.from_task]
    return a.s + a.d


def h_state(b: Board, h) -> str:
    a, c = b.tasks.get(h.from_task), b.tasks.get(h.to_task)
    if not a or not c or a.cut or c.cut:
        return "cut"
    if h.done:
        return "done"
    if h.prop:
        return "prop"
    if a.s + a.d > h.t + EPS:
        return "risk"
    return "agreed" if h.agreed else "ok"


def states(b: Board) -> dict:
    return {k: h_state(b, h) for k, h in b.hands.items()}


def risks(b: Board) -> list[str]:
    return [k for k, h in b.hands.items() if h_state(b, h) == "risk"]


def load_of(b: Board, pid: str) -> float:
    """이번 주에 그 사람에게 잡힌 일수. 2주차로 미뤄진 일은 세지 않는다."""
    return sum(t.d for t in b.tasks.values() if t.who == pid and not t.cut and t.s < b.week_end)


# ── 프록시 견적의 기본값 (기록 건수로만 계산) ─────────────────────────
def factor(person, tag: str) -> float:
    n = (person.rec or {}).get(tag, 0)
    return 1.0 if n >= 5 else 1.25 if n >= 2 else 1.5


def tag_line(person, tag: str) -> str:
    return f"{tag} {(person.rec or {}).get(tag, 0)}건"


def scaled_days(b: Board, base: float, tag: str, pid: str, owner: str) -> float:
    d = math.ceil(base * factor(b.people[pid], tag) / factor(b.people[owner], tag) * 2) / 2
    return max(0.5, d)


def est(b: Board, task_id: str, pid: str):
    """pid 가 이 일을 맡으면 며칠인가. 역할이 다르면 None."""
    t = b.tasks[task_id]
    p = b.people[pid]
    if pid == t.who:
        return {"days": t.d, "basis": tag_line(p, t.tag), "wish": False}
    if p.role != t.role:
        return None
    return {"days": scaled_days(b, t.base, t.tag, pid, t.who0 or t.who),
            "basis": tag_line(p, t.tag), "wish": t.tag in (p.wants or [])}


def preview(b: Board, task_id: str, dest: str) -> dict:
    """일을 dest(사람 id · 'next' · 'cut')로 옮기면 어떻게 되는지. 원본은 그대로."""
    st = b.clone()
    t = st.tasks[task_id]
    if dest == "next":
        t.s0 = max(st.week_end, t.s0)
    elif dest == "cut":
        t.cut = True
    else:
        e = est(b, task_id, dest)
        if e is None:
            raise ValueError("역할이 달라 맡을 수 없음")
        t.who, t.d, t.s0 = dest, e["days"], max(t.s0, b.now)
    schedule(st)
    before, after = risks(b), risks(st)
    return {
        "board": st,
        "task": t,
        "load": None if dest in ("next", "cut") else load_of(st, dest),
        "new_risk": [k for k in after if k not in before],
        "fixed": [k for k in before if k not in after],
    }


# ── 규칙 확인 (code gate) ─────────────────────────────────────────────
def gate(b: Board) -> dict:
    """확정 전에 통과해야 하는 검사. 무엇이 어긋났는지 코드와 수치로 돌려준다."""
    violations, warnings = [], []
    for pid, p in b.people.items():
        load = load_of(b, pid)
        if load > b.cap + EPS:
            violations.append({"code": "OVERLOAD", "who": pid, "limit": b.cap, "load": load,
                               "text": f"{p.name} {num(load)}/{num(b.cap)}일 넘침"})
    for hid in risks(b):
        h = b.hands[hid]
        violations.append({"code": "HANDOFF_LATE", "hid": hid, "promised": h.t, "predicted": pred(b, h),
                           "text": f"{h.title} {when(h.t)} → {when(pred(b, h))}"})
    for tid, t in b.tasks.items():
        if not t.cut and t.s < b.week_end - EPS and t.s + t.d > b.week_end + EPS:
            warnings.append({"code": "DEADLINE_SPILL", "task": tid, "ends": t.s + t.d,
                             "text": f"{t.title} 제출일을 넘겨 {when(t.s + t.d)}에 끝남"})
        elif not t.cut and t.s >= b.week_end - EPS and t.s0 < b.week_end - EPS:
            warnings.append({"code": "PUSHED_PAST_DEADLINE", "task": tid, "starts": t.s,
                             "text": f"{t.title} 제출일 뒤로 밀림"})
    return {"ok": not violations, "violations": violations, "warnings": warnings}


# ── 프록시 답 검사 ────────────────────────────────────────────────────
def deferrable(b: Board, pid: str) -> list:
    """미뤄도 다른 사람이 기다리지 않는, 아직 시작 안 한 그 사람의 일. 늦게 시작하는 것부터."""
    out = [t for t in b.tasks.values()
           if t.who == pid and not t.cut and t.kind not in ("done", "prop") and b.now - EPS <= t.s < b.week_end
           and not any(h.from_task == t.id and h_state(b, h) != "cut" for h in b.hands.values())]
    return sorted(out, key=lambda t: -t.s)


def check_reply(b: Board, pid: str, reply: dict, base_days: float, default_days: float, owner: str, help_request: bool = False):
    """프록시의 답이 규칙 안에 있는지 본다. 고르는 것은 프록시, 여기서는 어긋난 것만 찾아 돌려준다.

    돌려주는 값: (정리된 답, 위반 또는 None). 위반은 {"code", "text", ...} 로 무엇이 어긋났는지 담는다.
    """
    r = dict(reply)
    p = b.people[pid]
    load = load_of(b, pid)
    typ, cond = r.get("type"), r.get("cond") or None
    if typ not in ("ACCEPT", "REJECT", "COUNTER", "NEEDS_INPUT"):
        return r, {"code": "BAD_TYPE", "text": f"알 수 없는 답 유형: {typ}"}
    if typ == "REJECT":
        r["cond"] = None
        return r, None
    if not help_request:   # 일수는 숙련자 기준보다 짧을 수 없고, 기록 기준 기본값의 1.5배를 넘을 수 없다
        d = r.get("days") or default_days
        r["days"] = min(max(math.floor(d * 2 + 0.5) / 2, base_days), math.ceil(default_days * 1.5 * 2) / 2)
    need = 0 if help_request else r["days"]
    if typ == "COUNTER":
        if not cond or cond.get("kind") not in ("help", "defer"):
            return r, {"code": "BAD_CONDITION", "text": "조건부 답에는 help 또는 defer 조건이 있어야 함"}
        if cond["kind"] == "help":
            who = cond.get("who")
            if help_request or who not in b.people or who in (pid, owner) or b.people[who].role != p.role:
                return r, {"code": "BAD_CONDITION", "text": "도움은 같은 역할의 다른 사람(담당 제외)에게만 청할 수 있음"}
        else:
            ok = {t.id: t for t in deferrable(b, pid)}
            t = ok.get(cond.get("task"))
            if not t:
                return r, {"code": "BAD_CONDITION", "text": "미룰 수 있는 것은 아직 시작하지 않았고 넘겨줄 것이 없는 자기 일뿐",
                           "allowed": list(ok)}
            if load - t.d + need > b.cap + EPS:
                return r, {"code": "OVERLOAD", "who": pid, "limit": b.cap, "load": load - t.d + need,
                           "text": f"{t.title}{'을' if has_final(t.title) else '를'} 미뤄도 {num(load - t.d + need)}/{num(b.cap)}일로 넘침"}
            return r, None
    if help_request:
        if typ == "ACCEPT" and load > b.cap - EPS:
            return r, {"code": "OVERLOAD", "who": pid, "limit": b.cap, "load": load,
                       "text": f"{p.name} 금까지 {num(load)}/{num(b.cap)}일이라 도울 틈이 없음"}
        return r, None
    if load + need > b.cap + EPS:
        return r, {"code": "OVERLOAD", "who": pid, "limit": b.cap, "load": load + need,
                   "text": f"{p.name} {num(load)} + {num(need)} = {num(load + need)}/{num(b.cap)}일로 넘침"}
    return r, None
