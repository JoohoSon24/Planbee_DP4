"""Hive 계산과 규칙 확인(code gate) 단위 테스트. LLM 과 무관."""
from types import SimpleNamespace as NS

from app import hive


def P(id, role, rec=None, wants=None, oi=0):
    return NS(id=id, name=id.title(), role=role, rec=rec or {}, wants=wants or [], oi=oi)


def T(id, who, s0, d, tag="x", role="dev", oi=0, **kw):
    base = dict(id=id, who=who, who0=None, title=id, s0=s0, s=s0, d=d, plan=d, base=d, tag=tag, role=role, kind="",
                oi=oi, cut=False, got=False, cut_options=[])
    base.update(kw)
    return NS(**base)


def H(id, a, b, t, **kw):
    base = dict(id=id, from_task=a, to_task=b, title=id, what="", t=t, done=False, prop=False, agreed=False, basis="", oi=0)
    base.update(kw)
    return NS(**base)


def make():
    people = {"a": P("a", "dev", {"x": 6}), "b": P("b", "dev", {"x": 0}, ["x"], 1), "q": P("q", "qa", oi=2)}
    tasks = {"t1": T("t1", "a", 0, 3), "t2": T("t2", "a", 3, 2, oi=1), "t3": T("t3", "q", 3, 1, role="qa", oi=2)}
    hands = {"h1": H("h1", "t1", "t3", 3)}
    return hive.Board(people, tasks, hands, now=2)


def test_when_and_num():
    assert [hive.when(x) for x in (1.5, 3, 4.5, 5, 5.5)] == ["화 오전", "수 저녁", "금 오전", "금 저녁", "2주차 월 오전"]
    assert [hive.num(x) for x in (0.5, 1, 2.5)] == ["½", "1", "2½"]


def test_delay_propagates_along_handoff_and_lane():
    b = make()
    b.tasks["t1"].d = 4
    hive.schedule(b)
    assert b.tasks["t2"].s == 4 and b.tasks["t3"].s == 4       # 같은 사람의 다음 일, 받는 일 모두 밀림
    assert hive.h_state(b, b.hands["h1"]) == "risk" and hive.pred(b, b.hands["h1"]) == 4


def test_gate_reports_what_broke():
    b = make()
    b.tasks["t1"].d = 4
    hive.schedule(b)
    g = hive.gate(b)
    assert not g["ok"]
    assert {v["code"] for v in g["violations"]} == {"OVERLOAD", "HANDOFF_LATE"}
    over = next(v for v in g["violations"] if v["code"] == "OVERLOAD")
    assert over["who"] == "a" and over["limit"] == 5 and over["load"] == 6
    assert [w["code"] for w in g["warnings"]] == ["DEADLINE_SPILL"]


def test_estimate_scales_with_record_and_blocks_other_roles():
    b = make()
    assert hive.est(b, "t1", "b") == {"days": 4.5, "basis": "x 0건", "wish": True}   # 처음 하는 사람은 1.5배
    assert hive.est(b, "t1", "q") is None


def test_preview_does_not_touch_board():
    b = make()
    pv = hive.preview(b, "t2", "next")
    assert pv["task"].s0 == 5 and b.tasks["t2"].s0 == 3
    pv = hive.preview(b, "t1", "cut")
    assert hive.h_state(pv["board"], pv["board"].hands["h1"]) == "cut" and not b.tasks["t1"].cut


def test_check_reply_only_checks_rules():
    b = make()           # a: 5/5일(t1 3일 + t2 2일), b: 0/5일
    ok = lambda who, r, **kw: hive.check_reply(b, who, r, 1, 1.5, "q", **kw)
    r, v = ok("b", {"type": "ACCEPT", "days": 0.25})
    assert v is None and r["days"] == 1                                   # 숙련자 기준보다 짧을 수 없음
    r, v = ok("b", {"type": "ACCEPT", "days": 9})
    assert v is None and r["days"] == 2.5                                 # 기본값의 1.5배까지
    assert ok("a", {"type": "ACCEPT", "days": 1})[1]["code"] == "OVERLOAD"
    assert ok("a", {"type": "REJECT"})[1] is None                         # 거절은 언제나 받아들임
    assert ok("a", {"type": "COUNTER", "days": 1})[1]["code"] == "BAD_CONDITION"
    assert ok("a", {"type": "COUNTER", "days": 1, "cond": {"kind": "defer", "task": "t2"}})[1] is None
    bad = ok("a", {"type": "COUNTER", "days": 1, "cond": {"kind": "defer", "task": "t1"}})[1]
    assert bad["code"] == "BAD_CONDITION" and bad["allowed"] == ["t2"]    # 이미 시작했고 넘겨줄 것이 있는 일은 못 미룸
    assert ok("b", {"type": "COUNTER", "days": 1, "cond": {"kind": "help", "who": "q"}})[1]["code"] == "BAD_CONDITION"  # 역할이 다름
    assert ok("a", {"type": "ACCEPT"}, help_request=True)[1]["code"] == "OVERLOAD"
    assert ok("b", {"type": "ACCEPT"}, help_request=True)[1] is None
