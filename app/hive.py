"""Hive: 규칙대로 계산만 하는 코드. LLM을 부르지 않는다.

프로토타입의 schedule / hState / pred / loadOf / est / preview 를 그대로 옮겼다.
시간 단위는 '일'. 0 = 1주차 월 아침, 5 = 2주차 월 아침(= 금 저녁).
"""
from __future__ import annotations

import math
import copy
from dataclasses import dataclass, field
from types import SimpleNamespace

EPS = 1e-9
DAY = ["월", "화", "수", "목", "금"]
STATE_NAME = {"ok": "On track", "risk": "At risk", "prop": "Proposed",
              "agreed": "Agreed", "done": "Delivered", "cut": "Cut"}

TASK_FIELDS = ["id", "who", "who0", "title", "s0", "s", "d", "plan", "base", "tag", "role",
               "kind", "oi", "cut", "got", "cut_options", "context"]
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
        tasks = {k: SimpleNamespace(**{f: getattr(t, f, {}) for f in TASK_FIELDS}) for k, t in self.tasks.items()}
        hands = {k: SimpleNamespace(**{f: getattr(h, f) for f in HAND_FIELDS}) for k, h in self.hands.items()}
        return Board(self.people, tasks, hands, self.cap, self.week_end, self.now, copy.deepcopy(self.extra))


# ── 표기 ──────────────────────────────────────────────────────────────
def when(t: float) -> str:
    k = math.floor(t + EPS)
    if abs(t - round(t)) > EPS:
        return (f"{k//5+1}주차 " if k >= 5 else "") + DAY[k % 5] + " 오전"
    return (f"{(k-1)//5+1}주차 " if k - 1 >= 5 else "") + DAY[(k - 1) % 5] + " 저녁"


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


def policy(b, pid):
    p = b.extra.get("policies", {}).get(pid, {})
    return p if p.get("approved") else {}


def capacity(b, pid):
    p = policy(b, pid)
    intervals=sorted((max(0,w["start"]), min(b.week_end,w["end"])) for w in p.get("unavailable",[]) if w["start"]<b.week_end)
    unavailable=0.; end=0.
    for a,z in intervals:
        unavailable+=max(0,z-max(a,end));end=max(end,z)
    limit=p.get("weekly_limit")
    return max(0,min(b.cap, b.week_end-unavailable, limit if limit is not None else b.cap))


def available_start(b, pid, start, days):
    for w in sorted(policy(b,pid).get("unavailable",[]),key=lambda w:w["start"]):
        if (start < w["end"]-EPS and
                (start+days > w["start"]+EPS or
                 (days <= EPS and start >= w["start"]-EPS))):
            start=w["end"]
    return start


def fairness(b):
    totals={pid:float((getattr(p,"notes",None) or {}).get("past_effort",0))+load_of(b,pid) for pid,p in b.people.items()}
    mean=sum(totals.values())/max(1,len(totals))
    return {"totals":totals,"variance":sum((v-mean)**2 for v in totals.values())/max(1,len(totals)),
            "range":max(totals.values(),default=0)-min(totals.values(),default=0),"definition":"past_effort + current-week allocated days (done included once)"}


# ── 일정 계산 ─────────────────────────────────────────────────────────
def schedule(b: Board) -> None:
    """각 일의 실제 시작 s 를 다시 계산한다. Handoff 순서와 한 사람 한 번에 한 일을 지킨다."""
    ids = [i for i, t in b.tasks.items() if not t.cut]
    adjustments = {}
    for i in ids:
        b.tasks[i].s = b.tasks[i].s0
    for _ in range(max(40, len(ids) * 2 + 1)):
        changed = False
        for h in b.hands.values():
            a, c = b.tasks.get(h.from_task), b.tasks.get(h.to_task)
            if not a or not c or a.cut or c.cut:
                continue
            need = a.s + a.d
            if c.s < need - EPS:
                c.s, changed = need, True
        for pid in b.people:
            lane = sorted((b.tasks[i] for i in ids if b.tasks[i].who == pid and b.tasks[i].kind != "milestone"), key=lambda t: (t.s0, t.oi))
            end = 0.0
            for t in lane:
                at = available_start(b, pid, max(t.s,end), t.d) if t.kind != "done" else max(t.s,end)
                if at > t.s + EPS:
                    t.s, changed = at, True
                if t.s < end - EPS:
                    t.s, changed = end, True
                end = max(end, t.s + t.d)
        # A human-owned approval is an instantaneous event, not effort-free availability.
        # Only synthetic completion barriers can finish while their nominal owner is away.
        for i in ids:
            t = b.tasks[i]
            if t.kind != "milestone" or (getattr(t, "context", {}) or {}).get("completion_barrier"):
                continue
            at = available_start(b, t.who, t.s, t.d)
            if at > t.s + EPS:
                adjustments.setdefault(i, dict(code="MILESTONE_AVAILABILITY", task=i, who=t.who,
                    requested=t.s, unavailable=policy(b,t.who).get("unavailable", [])))
                adjustments[i]["scheduled"] = at
                t.s, changed = at, True
        if not changed:
            break
    b.extra["schedule_adjustments"] = list(adjustments.values())


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
        limit = capacity(b,pid)
        if load > limit + EPS:
            violations.append({"code": "OVERLOAD", "who": pid, "limit": limit, "load": load,
                               "text": f"{p.name} {num(load)}/{num(limit)}일 넘침"})
    for hid in risks(b):
        h = b.hands[hid]
        violations.append({"code": "HANDOFF_LATE", "hid": hid, "promised": h.t, "predicted": pred(b, h),
                           "text": f"{h.title} {when(h.t)} → {when(pred(b, h))}"})
    for tid, t in b.tasks.items():
        context=getattr(t,'context',{}) or {}
        if not t.cut and t.kind not in ('done','milestone'):
            checks=[('allowed_assignees' in context and t.who not in context['allowed_assignees'],'TASK_OWNER','전담 담당자 변경 금지'),
                ('earliest_start' in context and t.s<context['earliest_start']-EPS,'TASK_EARLIEST','가용 시작 이전 수행 금지'),
                ('latest_finish' in context and t.s+t.d>context['latest_finish']+EPS,'TASK_DEADLINE','Task 완료 기한 초과'),
                ('fixed_start' in context and abs(t.s-context['fixed_start'])>EPS,'TASK_FIXED_START','고정 시작 시각 변경 금지'),
                ('max_shift_days' in context and abs(t.s-context.get('original_start',t.s0))>context['max_shift_days']+EPS,'TASK_SHIFT','일정 이동 권한 초과')]
            for invalid,code,reason in checks:
                if invalid:violations.append(dict(code=code,task=tid,text=t.title+' · '+reason))
        if (not t.cut and t.kind == "milestone" and
                not (getattr(t,"context",{}) or {}).get("completion_barrier") and
                available_start(b,t.who,t.s,t.d) > t.s + EPS):
            violations.append({"code":"MILESTONE_UNAVAILABLE", "task":tid, "who":t.who,
                "at":t.s, "text":f"{b.people[t.who].name} · {t.title} 승인 시각에 가용하지 않음"})
        if not t.cut and t.s < b.week_end - EPS and t.s + t.d > b.week_end + EPS:
            warnings.append({"code": "DEADLINE_SPILL", "task": tid, "ends": t.s + t.d,
                             "text": f"{t.title} 제출일을 넘겨 {when(t.s + t.d)}에 끝남"})
        elif not t.cut and t.s >= b.week_end - EPS and t.s0 < b.week_end - EPS:
            warnings.append({"code": "PUSHED_PAST_DEADLINE", "task": tid, "starts": t.s,
                             "text": f"{t.title} 제출일 뒤로 밀림"})
    return {"ok": not violations and not warnings, "violations": violations, "warnings": warnings,
            "adjustments": b.extra.get("schedule_adjustments", [])}


# ── 프록시 답 검사 ────────────────────────────────────────────────────
def deferrable(b: Board, pid: str, banned=()) -> list:
    """미뤄도 다른 사람이 기다리지 않는, 아직 시작 안 한 그 사람의 일. 곧 시작할 것부터(미루면 지금 손이 빈다).

    banned: PM 이 미루기를 거절한 일 id.
    """
    out = [t for t in b.tasks.values()
           if t.who == pid and not t.cut and t.kind not in ("done", "prop", "milestone") and b.now - EPS <= t.s < b.week_end
           and t.id not in banned
           and not any(h.from_task == t.id and h_state(b, h) != "cut" for h in b.hands.values())]
    return sorted(out, key=lambda t: (t.s, t.oi))


def check_reply(b: Board, pid: str, reply: dict, base_days: float, default_days: float, owner: str, help_request: bool = False,
                banned=()):
    """프록시의 답이 규칙 안에 있는지 본다. 고르는 것은 프록시, 여기서는 어긋난 것만 찾아 돌려준다.

    돌려주는 값: (정리된 답, 위반 또는 None). 위반은 {"code", "text", ...} 로 무엇이 어긋났는지 담는다.
    """
    r = dict(reply)
    p = b.people[pid]
    load = load_of(b, pid)
    limit = capacity(b,pid)
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
            ok = {t.id: t for t in deferrable(b, pid, banned)}
            t = ok.get(cond.get("task"))
            if not t and cond.get("task") in banned:
                return r, {"code": "PM_REJECTED", "text": "PM 이 그 일을 미루는 것을 거절함", "allowed": list(ok)}
            if not t:
                return r, {"code": "BAD_CONDITION", "text": "미룰 수 있는 것은 아직 시작하지 않았고 넘겨줄 것이 없는 자기 일뿐",
                           "allowed": list(ok)}
            if load - t.d + need > limit + EPS:
                return r, {"code": "OVERLOAD", "who": pid, "limit": limit, "load": load - t.d + need,
                           "text": f"{t.title}{'을' if has_final(t.title) else '를'} 미뤄도 {num(load - t.d + need)}/{num(limit)}일로 넘침"}
            return r, None
    if help_request:
        if typ == "ACCEPT" and load > limit - EPS:
            return r, {"code": "OVERLOAD", "who": pid, "limit": limit, "load": load,
                       "text": f"{p.name} 금까지 {num(load)}/{num(limit)}일이라 도울 틈이 없음"}
        return r, None
    if load + need > limit + EPS:
        return r, {"code": "OVERLOAD", "who": pid, "limit": limit, "load": load + need,
                   "text": f"{p.name} {num(load)} + {num(need)} = {num(load + need)}/{num(limit)}일로 넘침"}
    return r, None


def preview_offer(b: Board, split: dict, task_id: str, hid: str, who: str, days: float) -> dict:
    """who 가 조각을 days 일에 맡는다면 판이 어떻게 되는지 미리 본다. 원본은 그대로.

    돌려주는 값: late_to(그래도 늦으면 새 예상 시각, 아니면 None), late_by, pushed(받는 사람의 일 중
    제출일 뒤로 밀리는 것), breaks(받는 사람이 넘겨줄 약속 중 새로 늦어지는 것).
    """
    st = b.clone()
    t, h, p = st.tasks[task_id], st.hands[hid], split["piece"]
    target = st.tasks[h.to_task] if split.get("to") == "downstream" else t

    def task(tid, owner, s0, d, oi):
        return SimpleNamespace(id=tid, who=owner, who0=None, title=tid, s0=s0, s=s0, d=d, plan=d, base=d, tag=t.tag,
                               role=t.role, kind="new", oi=oi, cut=False, got=False, cut_options=[])

    st.tasks["__piece"] = task("__piece", who, b.now, days, 10 ** 6)
    st.hands["__piece"] = SimpleNamespace(id="__piece", from_task="__piece", to_task=target.id, title="", what="", t=b.now + days,
                                          done=False, prop=False, agreed=True, basis="", oi=10 ** 6)
    at = b.now
    for i, part in enumerate(split.get("extra") or []):
        st.tasks[f"__x{i}"] = task(f"__x{i}", t.who, at, part.get("days") or 0.5, 10 ** 6 + i + 1)
        at += 0.5
    keep = split.get("keep") or {}
    t.d = keep.get("days") or max(0.5, t.d - p["days"])
    if split.get("extra"):
        t.s0 = max(t.s0, at)
    schedule(st)
    schedule(b)
    receiver = st.tasks[h.to_task].who
    piece_end = st.tasks["__piece"].s + st.tasks["__piece"].d
    # 받는 일이 다 받는 때: 남은 일과, (조각이 받는 일로 바로 가면) 조각 중 늦은 쪽
    arrive = max(pred(st, h), piece_end) if target.id == h.to_task else pred(st, h)
    late = arrive > h.t + EPS
    before = set(risks(b))
    return {
        "fairness": fairness(st),
        "piece_end": piece_end,
        "pushed_all": [x.title for k, x in st.tasks.items() if not k.startswith("__") and not x.cut
                       and x.s >= st.week_end - EPS and x.s0 < st.week_end - EPS],
        "late_to": arrive if late else None,
        "late_by": max(0.0, arrive - h.t),
        "receiver": receiver,
        "pushed": [x.title for k, x in st.tasks.items() if x.who == receiver and not k.startswith("__") and not x.cut
                   and x.s >= st.week_end - EPS and x.s0 < st.week_end - EPS],
        "breaks": [x.title for k, x in st.hands.items() if k not in before and k != hid and not k.startswith("__")
                   and h_state(st, x) == "risk" and st.tasks[x.from_task].who == receiver],
    }


def check_wait_reply(reply: dict, pv: dict):
    """받는 쪽 프록시의 답(늦춰 받기) 검사. 자기가 넘길 약속이 깨지는데 수락하면 돌려보낸다."""
    r = dict(reply)
    r["cond"] = None
    if r.get("type") not in ("ACCEPT", "REJECT", "NEEDS_INPUT"):
        return r, {"code": "BAD_TYPE", "text": "늦춰 받기 요청에는 수락 · 거절 · 본인 확인 필요로만 답할 수 있음"}
    if r["type"] == "ACCEPT" and pv["breaks"]:
        return r, {"code": "PROMISE_BROKEN", "text": "수락하면 내가 넘길 약속이 깨짐: " + ", ".join(pv["breaks"])}
    return r, None
