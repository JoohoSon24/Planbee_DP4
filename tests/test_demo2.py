"""데모 2 (Plan Bee 팀의 M4 주간) · PM 거절 · 조건별 비교."""
import os

os.environ["PLANBEE_DB"] = "sqlite://"
os.environ["PLANBEE_LLM"] = "mock"

import pytest
from fastapi.testclient import TestClient

from app import sim, store
from app.api import app


@pytest.fixture()
def c():
    with TestClient(app) as client:
        s = client.post("/demo/select", json={"demo": "demo2"}).json()
        assert s["demo"]["id"] == "demo2"
        yield client
        client.post("/demo/select", json={"demo": "demo1"})


def advance(c, auto=True):
    r = c.post("/demo/advance", json={"auto_confirm": auto})
    assert r.status_code == 200, r.text
    return r.json()


def thursday(c):
    advance(c)
    s = advance(c)
    return s, [a for a in s["asks"] if a["open"]][0]


def test_demo2_starts_clean(c):
    s = c.get("/state").json()
    assert [(p["name"], p["role"]) for p in s["people"]] == [("여경", "에이전트"), ("정민", "에이전트"), ("주호", "화면"), ("나정", "화면")]
    assert len(s["tasks"]) == 13 and s["gate"]["ok"] and not s["gate"]["warnings"]
    assert s["now_label"] == "1주차 · 화요일 오전" and s["feed_label"] == "시연 · 화요일 기록 받기"
    catalog = c.get("/demos").json()
    assert catalog["current"] == "demo2"
    assert catalog["all"] == store.service_demos()
    assert [entry["id"] for entry in catalog["catalog"]] == catalog["all"]
    assert c.post("/demo/select", json={"demo": "nope"}).status_code == 404


def test_tuesday_piece_goes_to_the_other_role_without_pm(c):
    """화요일: 에이전트 쪽 여경의 일에서 DB 조각을 떼어 화면 쪽에 묻는다. 주호의 프록시가 한도 안에서 맡고 PM 은 아무것도 안 한다."""
    s = advance(c)
    n = c.get(f"/negotiations/{s['negotiations'][0]['id']}").json()
    assert n["proposal"]["piece"]["role"] == "화면"
    by = {r["who"]: r for r in n["replies"]}
    assert set(by) == {"jh", "nj"}                                             # 같은 역할인 정민에게는 묻지 않음
    assert by["jh"]["type"] == "ACCEPT" and by["jh"]["late_to"] is None
    # 나정은 하던 일 뒤에야 시작할 수 있어 약속이 늦어진다 → 받는 쪽(주호)의 프록시에게 먼저 물음
    assert by["nj"]["type"] == "NEEDS_INPUT" and by["nj"]["late_to"] == 3.5 and by["nj"]["wish"]
    assert not any(m["k"] == "proxy" and m["f"][-1]["t"] == "늦게 받아도 돼요?" for m in s["log"])
    assert s["tasks"]["resume"]["who"] == "jh" and s["tasks"]["resume"]["role"] == "화면"
    assert s["hand"]["h1"]["state"] == "ok" and s["hand"]["h2"]["state"] == "ok"
    assert s["stats"]["decisions"] == 0 and [x["who"] for x in s["confirms"]] == ["yk"]   # 주호는 한도 안이라 프록시가 수락
    assert s["phase"] == "thu" and s["feed_label"] == "시연 · 목요일 기록 받기" and s["gate"]["ok"] and not s["asks"]


def test_tuesday_learning_preference_cannot_override_deadline(c):
    """학습 선호라도 마감 밖의 후보 대신 기한 안의 후보를 선택한다."""
    c.put("/rules/pref", json={"choice": "learn"})
    s=advance(c)
    assert s['tasks']['resume']['who']=='jh'
    assert [x['who'] for x in s['confirms']]==['yk']
    assert all(h['state']!='risk' for h in s['hand'].values())
    assert s['gate']['ok'] and not s['gate']['warnings']


def test_thursday_options_come_with_previews(c):
    s, ask = thursday(c)
    assert "여경: 엣지 케이스 · 교착 처리를 2주차로 미루면 가능" in ask["why"]      # 에이전트 쪽에는 여경뿐
    assert [g["key"] for g in ask["grants"]] == ["defer:edge", "cut:base:one_scn"]
    g = {x["key"]: x for x in ask["grants"]}
    assert "약속 모두 제때" in g["defer:edge"]["effect"] and g["defer:edge"]["preview"]["who"] == "yk"
    s = c.post(f"/asks/{ask['id']}/grant", json={"key": "defer:edge"}).json()
    assert s["tasks"]["adapter"]["who"] == "yk" and s["hand"]["h3"]["state"] == "ok" and s["gate"]["ok"] and not s["gate"]["warnings"]
    assert s["tasks"]["edge"]["moved"] and s["phase"] == "end"


def test_pm_rejects_with_a_reason_and_proxies_try_again(c):
    s, ask = thursday(c)
    assert c.post(f"/asks/{ask['id']}/reject", json={"reason": " ", "keys": ["defer:edge"]}).status_code == 409   # 이유는 꼭
    assert c.post(f"/asks/{ask['id']}/reject", json={"reason": "x", "keys": ["nope"]}).status_code == 409
    s = c.post(f"/asks/{ask['id']}/reject", json={"reason": "엣지 케이스는 리허설에 꼭 필요", "keys": ["defer:edge"]}).json()
    assert s["stats"]["decisions"] == 1 and s["phase"] == "ask"
    new = [a for a in s["asks"] if a["open"]][0]
    # 여경의 프록시는 거절된 조건 대신 다른 일을 조건으로 내고, 미리 보기가 그 길은 늦는다고 알려 준다
    assert new["id"] != ask["id"] and [g["key"] for g in new["grants"]] == ["defer:prompt", "cut:base:one_scn"]
    assert "베이스라인 결과 2주차 월 오전으로 늦어짐" in new["grants"][0]["effect"]
    assert new["why"][-1] == "PM이 거절: 엣지 케이스 · 교착 처리 미루기 (엣지 케이스는 리허설에 꼭 필요)"
    assert s["recs"][-1]["src"] == "PM" and "이유: 엣지 케이스는 리허설에 꼭 필요" in s["recs"][-1]["text"]
    # 남은 것을 전부 거절하면 고를 허락이 없고, 남는 것은 약속을 늦추는 것뿐
    s = c.post(f"/asks/{new['id']}/reject", json={"reason": "둘 다 M4 범위"}).json()
    last = [a for a in s["asks"] if a["open"]][0]
    assert last["grants"] == [] and s["stats"]["decisions"] == 2 and last["why"][0] == "여경: 금까지 4½/5일로 꽉 참"
    assert c.post(f"/asks/{last['id']}/reject", json={"reason": "x"}).status_code == 409    # 거절할 것이 없음
    s = c.post("/handoffs/h3/reagree", json={"auto_confirm": True}).json()
    assert s["hand"]["h3"]["state"] == "agreed" and s["phase"] == "end" and s["stats"]["decisions"] == 3
    labels = [g["label"] for g in c.get(f"/negotiations/{s['negotiations'][1]['id']}").json()["rounds"]]
    assert [x for x in labels if "PM 답" in x and x.startswith("1라운드")] == [f"1라운드 · PM 답 {i}회 뒤" for i in (1, 2)]   # 거절할 때마다 다시 협상
    for _ in range(3):
        c.post("/undo")
    assert [a["id"] for a in c.get("/asks", params={"open": True}).json()] == [ask["id"]]     # 되돌리면 처음 PM 확인으로


def test_sim_compares_conditions():
    """조건별 비교: Plan Bee 는 PM 이 직접 챙길 사람이 0 이고 제출일을 넘기는 일이 없다. 비교 방식은 그렇지 않다."""
    _, push = sim.simulate("demo2", mode="push")
    _, central = sim.simulate("demo2", mode="central")
    _, bee = sim.simulate("demo2", pm="grant:defer:edge")
    assert (push["pm_talks"], push["past_deadline"], push["promises_moved"]) == (4, 4, 3)
    assert (central["pm_talks"], central["past_deadline"]) == (4, 3)
    assert (bee["pm_decisions"], bee["pm_talks"], bee["late_end"], bee["past_deadline"], bee["overload"], bee["overrides"]) == (1, 0, 0, 0, 0, 0)
    assert bee["cost"] == {"여경": {"늘어남": 1.0, "밀림": 1.5}, "주호": {"늘어남": 1.0, "밀림": 0}}
    _, cut = sim.simulate("demo2", pm="grant:cut")
    assert cut["scope_cut"] == 1 and cut["top_who"] == "주호"
    _, d1 = sim.simulate("demo1")                              # 데모 1 도 같은 방법으로 돈다
    assert (d1["pm_decisions"], d1["late_end"], d1["overload"]) == (1, 0, 0)
