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


def test_preview_offer_and_receiver_check():
    b = make()
    b.tasks["t1"].d = 4                                   # a 가 하루 늦어짐 → h1(t1 → q 의 t3) 이 늦어질 판
    hive.schedule(b)
    piece = {"title": "조각", "days": 1, "tag": "x"}
    # 조각을 받는 일(t3)에 바로 넘기면 a 의 남은 3일은 제때 끝난다
    assert hive.preview_offer(b, {"piece": piece, "to": "downstream"}, "t1", "h1", "b", 1)["late_to"] is None
    # 조각을 a 가 받아 붙여야 하면(to: self) a 의 일이 조각 뒤로 밀려 그래도 늦는다. 원본 판은 그대로
    pv = hive.preview_offer(b, {"piece": piece, "to": "self"}, "t1", "h1", "b", 1)
    assert pv["late_to"] == 6 and pv["late_by"] == 3 and pv["receiver"] == "q" and b.tasks["t1"].d == 4
    assert pv["pushed"] == ["t3"]                         # 받는 사람 q 의 일이 제출일 뒤로 밀림
    assert hive.check_wait_reply({"type": "ACCEPT"}, pv)[1] is None
    assert hive.check_wait_reply({"type": "COUNTER"}, pv)[1]["code"] == "BAD_TYPE"
    assert hive.check_wait_reply({"type": "ACCEPT"}, {**pv, "breaks": ["빌드"]})[1]["code"] == "PROMISE_BROKEN"


def approval_board(at=4.5, *, barrier=False):
    b = hive.Board({'h': P('h', 'ops'), 'a': P('a', 'dev')}, {
        'approval': T('approval','h',at,0,role='ops',kind='milestone',context={'completion_barrier':barrier}),
        'final': T('final','a',4.5,.5),
    }, {'release': H('release','approval','final',4.5)}, now=0)
    b.extra['policies'] = {'h': {'approved':True,'unavailable':[{'start':4.5,'end':5,'reason':'교육'}]}}
    return b


def test_zero_effort_approval_checks_unavailability_start_boundary_and_propagates():
    b = approval_board()
    hive.schedule(b)
    assert b.tasks['approval'].s == 5
    assert b.tasks['final'].s == 5
    gate = hive.gate(b)
    assert not gate['ok']
    assert gate['adjustments'][0]['who'] == 'h'
    assert gate['adjustments'][0]['requested'] == 4.5
    assert gate['adjustments'][0]['scheduled'] == 5
    assert any(v['code']=='HANDOFF_LATE' for v in gate['violations'])
    assert any(w['task']=='final' for w in gate['warnings'])


def test_gate_detects_unscheduled_unavailable_approval_and_interval_end_is_available():
    b = approval_board()
    assert any(v['code']=='MILESTONE_UNAVAILABLE' for v in hive.gate(b)['violations'])
    assert hive.available_start(b,'h',4.5,0) == 5
    assert hive.available_start(b,'h',4.75,0) == 5
    assert hive.available_start(b,'h',5,0) == 5
    assert hive.available_start(b,'h',4,0) == 4


def test_completion_barrier_does_not_require_nominal_owner_attendance():
    b = approval_board(barrier=True)
    hive.schedule(b)
    assert b.tasks['approval'].s == 4.5
    assert hive.gate(b)['ok']
    assert not hive.gate(b)['adjustments']


def test_unapproved_time_off_does_not_become_a_hard_constraint():
    b=approval_board()
    b.extra['policies']['h']['approved']=False
    hive.schedule(b)
    assert b.tasks['approval'].s==4.5
    assert hive.gate(b)['ok']
