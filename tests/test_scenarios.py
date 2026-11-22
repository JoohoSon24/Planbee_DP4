"""프로토타입 시연 대본을 기대 결과로 삼은 시나리오 테스트. Mock LLM 으로 돈다."""
import os

os.environ["PLANBEE_DB"] = "sqlite://"
os.environ["PLANBEE_LLM"] = "mock"

import pytest
from fastapi.testclient import TestClient

from app.api import app


@pytest.fixture()
def c():
    from app import store
    store.use_demo("demo1")
    with TestClient(app) as client:
        client.post("/reset")
        yield client


def advance(c, auto=True):
    r = c.post("/demo/advance", json={"auto_confirm": auto})
    assert r.status_code == 200, r.text
    return r.json()


def to_thursday_ask(c):
    advance(c)
    s = advance(c)
    assert s["phase"] == "ask"
    return s, [a for a in s["asks"] if a["open"]][0]


def test_seed_matches_prototype(c):
    s = c.get("/state").json()
    assert len(s["people"]) == 6 and len(s["tasks"]) == 14 and len(s["hand"]) == 4
    assert {h["state"] for h in s["hand"].values()} == {"ok", "done"}
    load = {p["id"]: p["load"] for p in s["people"]}
    assert load == {"mia": 5, "ivy": 2, "leo": 4.5, "sam": 5, "ben": 2, "zoe": 4}
    assert s["gate"]["ok"] and s["phase"] == "mon"


def test_S1_wednesday_solved_inside_rules(c):
    """수요일: Mia가 하루 늦어짐 → Ivy가 무기 그림을 맡음. PM 결정 0."""
    s = advance(c)
    assert s["phase"] == "wed"
    assert s["tasks"]["draw"]["title"] == "캐릭터 몸" and s["tasks"]["draw"]["d"] == 3
    assert s["tasks"]["weapon"]["who"] == "ivy" and s["tasks"]["weapon"]["kind"] == "new"
    assert s["hand"]["h1"]["state"] == "ok" and s["hand"]["h1"]["title"] == "캐릭터 몸"
    assert s["hand"]["h5"]["state"] == "agreed" and s["hand"]["h5"]["to"] == "code"
    assert s["hand"]["h2"]["state"] == "ok"
    assert s["stats"]["msgs"] >= 10  # Deadline repair is followed by public fairness discussion.
    assert {k: v for k, v in s["stats"].items() if k != "msgs"} == {"pm_direct_asks": 0, "confirms": 2, "decisions": 0}
    assert s["resolved"][0]["hid"] == "h1" and "PM 결정 없음" in s["resolved"][0]["why"]
    assert not s["asks"] and s["gate"]["ok"]


def test_S2_people_confirm_one_by_one(c):
    """auto_confirm 을 끄면: Ivy 는 카드 한도(½일)를 넘어 먼저 본인 확인, 그다음 담당 Mia 확인."""
    s = advance(c, auto=False)
    assert "h5" not in s["hand"] and s["hand"]["h1"]["state"] == "risk"      # Ivy 가 답하기 전에는 가약속도 없다
    assert [p["who"] for p in s["pending_confirms"]] == ["ivy"] and "한도" in s["pending_confirms"][0]["prompt"]
    assert c.post("/demo/advance").status_code == 409                         # 기다리는 동안 잠김
    s = c.post(f"/confirmations/{s['pending_confirms'][0]['id']}").json()
    assert s["hand"]["h5"]["state"] == "prop" and s["tasks"]["draw"]["d"] == 4   # 가약속. Mia 의 일은 아직 그대로
    assert [p["who"] for p in s["pending_confirms"]] == ["mia"]
    cid = s["pending_confirms"][0]["id"]
    s = c.post(f"/confirmations/{cid}").json()
    assert s["hand"]["h5"]["state"] == "agreed" and s["hand"]["h1"]["state"] == "ok" and s["phase"] == "wed"
    assert c.post(f"/confirmations/{cid}").status_code == 409                 # 두 번 누를 수 없음


def test_S3_taker_rejects_goes_to_pm(c):
    """Ivy가 거절하면 그림 역할에 다른 사람이 없어 PM에게 간다."""
    s = advance(c, auto=False)
    s = c.post(f"/confirmations/{s['pending_confirms'][0]['id']}", json={"ok": False}).json()
    assert "weapon" not in s["tasks"] and "h5" not in s["hand"]
    assert s["phase"] == "ask" and s["hand"]["h1"]["state"] == "risk"
    ask = [a for a in s["asks"] if a["open"]][0]
    assert ask["hid"] == "h1" and ask["grants"] == [] and ask["why"] == ["Ivy: 본인이 거절"]
    assert c.post("/handoffs/h3/reagree", json={"auto_confirm": True}).status_code == 409    # 다른 조작은 잠김
    # 고를 허락이 없으니 PM 은 그 Handoff 의 약속을 늦추는 것으로 답한다
    s = c.post("/handoffs/h1/reagree", json={"auto_confirm": True}).json()
    assert s["hand"]["h1"]["state"] == "agreed" and s["hand"]["h1"]["t"] == 4 and s["phase"] == "wed"
    assert not [a for a in s["asks"] if a["open"]] and not s["waiting"]


def test_S4_thursday_needs_pm(c):
    """목요일: Sam은 꽉 찼고 Ben은 Sam의 도움이 필요 → 규칙 안에서 못 풂."""
    s, ask = to_thursday_ask(c)
    assert ask["hid"] == "h2"
    # 이유는 프록시가 쓴 말 그대로이고, 미루기 선택지는 Sam 의 프록시가 낸 조건에서 나온다
    assert {"Sam: 버그 고치기를 2주차로 미루면 가능",
            "Ben: Sam의 30분 도움이 필요 → Sam: 버그 고치기를 2주차로 미루면 가능"} <= set(ask['why'])
    assert any('협상 한도 내 합의 실패' in reason for reason in ask['why'])
    assert "Sam의 프록시가 낸 조건" in ask["grants"][0]["effect"]
    assert any("라운드 끝" in m.get("text", "") for m in s["log"])
    detail=c.get(f"/negotiations/{ask['run']}").json()
    strategies=' '.join(e['reason'] for e in detail['discussion']['history'] if e['response']=='STRATEGY_CHANGE')
    assert all(strategy in strategies for strategy in ('whole_transfer','move_other_work','collaborate'))
    assert [g["key"] for g in ask["grants"]] == ["defer:bugs", "cut:code:weapon_fx"]
    assert s["hand"]["h2"]["state"] == "risk" and s["tasks"]["code"]["d"] == 2.5
    assert s["stats"]["decisions"] == 0
    d = c.get("/handoffs/h2").json()
    assert d["ask"]["id"] == ask["id"] and d["up"] == ["h1", "h5"] and not d["can_reagree"]


def test_S5_grant_defer_fast_picks_sam(c):
    s, ask = to_thursday_ask(c)
    s = c.post(f"/asks/{ask['id']}/grant", json={"key": "defer:bugs"}).json()
    assert s["phase"] == "end" and s["tasks"]["bugs"]["moved"]
    assert s["tasks"]["move"]["who"] == "sam" and s["tasks"]["move"]["d"] == 1
    assert s["tasks"]["sm"]["who"] == "leo" and s["tasks"]["code"]["title"] == "캐릭터 붙이기"
    assert s["hand"]["h6"]["state"] == "agreed" and s["hand"]["h2"]["state"] == "ok" and s["hand"]["h2"]["t"] == 4.5
    assert s["stats"]["decisions"] == 1 and s["granted"] == ["버그 고치기(Sam)를 2주차로 미뤄도 됨"]
    # Sam 은 카드 한도(1일) 안이라 프록시가 알아서 수락: 목요일에 확인한 사람은 담당 Leo 뿐
    assert [x["who"] for x in s["confirms"]][:3] == ["ivy", "mia", "leo"]
    assert any("Sam의 프록시가 카드 한도 안에서 수락" in r["why"] for r in s["resolved"])
    assert s["gate"]["ok"] and not s["gate"]["warnings"]


def test_S6_learning_preference_preserves_original_deadline(c):
    c.put('/rules/pref',json={'choice':'learn'})
    s,ask=to_thursday_ask(c)
    s=c.post(f"/asks/{ask['id']}/grant",json={'index':0}).json()
    assert s['tasks']['move']['who']=='sam'
    assert s['hand']['h2']['t']==4.5 and s['hand']['h2']['state']=='ok'
    assert not s['gate']['warnings'] and s['gate']['ok']
    assert 'zoe' not in [x['who'] for x in s['confirms']]


def test_S7_grant_cut_scope(c):
    s, ask = to_thursday_ask(c)
    s = c.post(f"/asks/{ask['id']}/grant", json={"key": "cut:code:weapon_fx"}).json()
    assert s["tasks"]["code"]["d"] == 1.5 and "move" not in s["tasks"]
    assert s["hand"]["h2"]["state"] == "ok" and s["phase"] == "end"
    assert s["resolved"][-1]["why"] == "PM이 범위를 줄임 · Leo 확인"


def test_undo_restores_before_grant(c):
    s, ask = to_thursday_ask(c)
    c.post(f"/asks/{ask['id']}/grant", json={"key": "defer:bugs"})
    s = c.post("/undo").json()
    assert s["phase"] == "ask" and [a for a in s["asks"] if a["open"]] and "move" not in s["tasks"]
    s = c.post(f"/asks/{ask['id']}/grant", json={"key": "cut:code:weapon_fx"}).json()   # 다른 선택으로 다시
    assert s["hand"]["h2"]["state"] == "ok"
    for _ in range(3):
        s = c.post("/undo").json()
    assert s["phase"] == "mon" and c.post("/undo").status_code == 409


def test_unscripted_record_and_undo(c):
    """대본에 없는 기록은 견적을 바꾸지 않고, 거절 뒤에도 되돌리기로 기록 받기 전으로 간다."""
    r = c.post("/records", json={"records": [{"src": "작업", "who": "zoe", "text": "전투 테스트 예상 2일로"}], "auto_confirm": True})
    assert r.status_code == 200                                    # 대본에 없는 기록: 견적 그대로
    assert c.post("/handoffs/h1/reagree").status_code == 409       # 제때인 Handoff 는 못 고침
    s = advance(c, auto=False)                                     # h1 이 risk 인 채 멈춤
    s = c.post(f"/confirmations/{s['pending_confirms'][0]['id']}", json={"ok": False}).json()
    c.post("/undo")                                                # 거절 전으로 (기록 받기 전)
    s = c.get("/state").json()
    assert s["phase"] == "mon"


def test_move_task_board(c):
    bids = c.get("/tasks/bugs/bids").json()
    by = {b["who"]: b for b in bids["bids"]}
    assert set(by) == {"leo", "sam", "ben"} and by["sam"]["mine"]
    assert by["ben"]["days"] == 2.5 and not by["ben"]["over"] and by["leo"]["over"]
    s = c.post("/tasks/bugs/move", json={"dest": "ben", "auto_confirm": True}).json()
    assert s["tasks"]["bugs"]["who"] == "ben" and s["tasks"]["bugs"]["kind"] == "new" and s["stats"]["decisions"] == 1
    assert c.post("/tasks/bugs/move", json={"dest": "zoe"}).status_code == 409    # 역할이 다름
    s = c.post("/tasks/enemy/move", json={"dest": "cut"}).json()
    assert s["tasks"]["enemy"]["cut"]
    s = c.post("/tasks/code/move", json={"dest": "next"}).json()
    assert s["hand"]["h2"]["state"] == "risk"
    s = c.post("/handoffs/h2/reagree", json={"auto_confirm": True}).json()
    assert s["hand"]["h2"]["state"] == "agreed"


def test_handoff_filters(c):
    advance(c)
    advance(c)
    r = c.get("/handoffs", params={"filter": "watch"}).json()
    assert [h["id"] for h in r["items"]] == ["h2"] and r["counts"] == {"all": 5, "watch": 1, "live": 3, "done": 1}


# ── 위임 카드 · 답 유형 · 라운드 ──────────────────────────────────────
def test_card_within_limit_proxy_accepts_alone(c):
    """Ivy 의 한도를 1일로 올리면 프록시가 알아서 수락하고, 사람은 담당 Mia 만 확인한다."""
    assert c.put("/people/ivy/card", json={"auto_days": 1}).json()["cards"][1]["auto_days"] == 1
    s = advance(c)
    assert [x["who"] for x in s["confirms"]] == ["mia"] and s["hand"]["h5"]["state"] == "agreed"
    assert any(m["k"] == "proxy" and m["from"] == "ivy" and m["f"][-1]["t"] == "수락" for m in s["log"])
    assert "프록시가 카드 한도 안에서 수락" in c.get("/handoffs/h5").json()["hist"][-1]["text"]


def test_card_refuse_tag_makes_proxy_reject(c):
    c.put("/people/ivy/card", json={"refuse_tags": ["캐릭터 그림"]})
    s = advance(c)
    ask = [a for a in s["asks"] if a["open"]][0]
    assert s["phase"] == "ask" and "Ivy: 카드에 '캐릭터 그림'은 받지 않는다고 되어 있음" in ask["why"]


def test_card_no_help_blocks_the_learner(c):
    """Sam 이 도움 요청을 받지 않으면, '배우고 싶은 사람' 규칙이어도 Ben 은 조건을 못 채워 Sam 이 받는다."""
    c.put("/rules/pref", json={"choice": "learn"})
    c.put("/people/sam/card", json={"gives_help": False})
    s, ask = to_thursday_ask(c)
    assert ask["why"][1] == "Ben: Sam의 30분 도움이 필요 → Sam: 거절 (카드에 도움 요청은 받지 않는다고 되어 있음)"
    s = c.post(f"/asks/{ask['id']}/grant", json={"key": "defer:bugs"}).json()
    assert s["tasks"]["move"]["who"] == "sam"


def test_round_limit_escalates_with_open_items(c):
    """라운드를 1로 줄이면 Ben 의 조건을 Sam 에게 확인하지 못한 채 PM 에게 간다."""
    assert c.put("/rules/rounds", json={"max": 1}).status_code == 200
    s, ask = to_thursday_ask(c)
    assert ask["why"][1] == "Ben: Sam의 30분 도움이 필요 → 라운드 안에 확인 못 함"
    assert any("1라운드 안에 조건을 다 확인하지 못함" in m.get("text", "") for m in s["log"])
    assert not any("2라운드" in m.get("text", "") for m in s["log"])


def test_hive_sends_back_a_reply_that_breaks_the_rules(c):
    """프록시가 꽉 찬 사람을 대신해 무조건 수락해도 Hive 가 반려하고, 다시 어긋나면 거절로 적는다."""
    from app import llm

    class YesMan(llm.MockLLM):
        def reply(self, person, card, piece, ctx):
            self.seen = getattr(self, "seen", []) + [(person.id, ctx["violation"] and ctx["violation"]["code"])]
            return llm.Reply(type="ACCEPT", days=1)

    yes = YesMan()
    llm.set_llm(yes)
    try:
        s, ask = to_thursday_ask_or_done(c)
    finally:
        llm.set_llm(None)
    assert ("sam", None) in yes.seen and ("sam", "OVERLOAD") in yes.seen      # 반려 이유를 붙여 한 번 더 물음
    assert any("반려 · Sam의 프록시 답 ACCEPT · OVERLOAD" in m.get("text", "") for m in s["log"])
    assert s["tasks"]["move"]["who"] == "ben" and s["gate"]["ok"]            # 규칙 안에 있던 Ben 의 수락만 남음


def to_thursday_ask_or_done(c):
    advance(c)
    s = advance(c)
    open_asks = [a for a in s["asks"] if a["open"]]
    return s, (open_asks[0] if open_asks else None)


# ── 받는 쪽 프록시의 참여 · 협상 보기 ─────────────────────────────────
def test_unsafe_offer_never_requests_receiver_to_extend_deadline(c):
    c.put('/rules/pref',json={'choice':'learn'})
    advance(c);s=advance(c)
    ask=next(a for a in s['asks'] if a['open'])
    c.post('/undo')
    s=c.post('/demo/advance',json={'auto_confirm':False}).json()
    ask=next(a for a in s['asks'] if a['open'])
    s=c.post(f"/asks/{ask['id']}/grant",json={'key':'defer:bugs'}).json()
    assert [p['who'] for p in s['pending_confirms']]==['leo']
    assert s['tasks']['move']['who']=='sam' and s['tasks']['move']['kind']=='prop'
    s=c.post(f"/confirmations/{s['pending_confirms'][0]['id']}").json()
    assert s['hand']['h2']['t']==4.5 and s['hand']['h2']['state']=='ok'
    assert not s['gate']['warnings']


def test_wait_card_permission_is_not_permission_to_break_project_deadline(c):
    c.put('/rules/pref',json={'choice':'learn'})
    c.put('/people/zoe/card',json={'wait_days':.5})
    s,ask=to_thursday_ask(c)
    s=c.post(f"/asks/{ask['id']}/grant",json={'key':'defer:bugs'}).json()
    assert 'zoe' not in [x['who'] for x in s['confirms']]
    assert s['hand']['h2']['t']==4.5 and not s['gate']['warnings']


def test_negotiation_view_groups_by_round(c):
    s, ask = to_thursday_ask(c)
    runs = c.get("/negotiations").json()
    assert [r["status"] for r in runs] == ["done", "waiting_pm"]
    n = c.get(f"/negotiations/{runs[1]['id']}").json()
    assert [g['label'] for g in n['rounds']]==['준비']+[f'{i}라운드' for i in range(1,n['round']+1)]
    assert n['round']>=3 and n['max_rounds']==15
    assert n["discussion"]["termination"] == "no_valid_alternative"
    assert n["proposal"]["piece"]["title"] == "움직임 코드" and n["ask"]["id"] == ask["id"]
    by = {r["who"]: r for r in n["replies"]}
    assert by["sam"]["type"] == "COUNTER" and by["sam"]["cond"] == {"kind": "defer", "who": None, "task": "bugs", "minutes": 30}
    assert by["ben"]["cond"]["kind"] == "help" and by["ben"]["help"] == "defer" and by["ben"]["late_to"] == 5
    s = c.post(f"/asks/{ask['id']}/grant", json={"key": "defer:bugs"}).json()
    n = c.get(f"/negotiations/{runs[1]['id']}").json()
    assert {"1라운드 · PM 답 1회 뒤", "2라운드 · PM 답 1회 뒤"} <= {g["label"] for g in n["rounds"]}
    assert n["status"] == "done" and n["discussion"]["termination"]
    assert n["chosen"]["who"] == "sam" and c.get("/negotiations/999").status_code == 404


def test_final_hive_constraints_after_consents_rollback_initial_offer(c):
    """An initial recipient's earlier acceptance cannot bypass a changed time-off policy."""
    from app import api
    from app.models import Card
    state=advance(c,False)
    recipient=next(x for x in state['pending_confirms'] if x['who']=='ivy')
    state=c.post(f"/confirmations/{recipient['id']}",json={'ok':True}).json()
    source=next(x for x in state['pending_confirms'] if x['who']=='mia')
    with api.SessionLocal() as db:
        card=db.get(Card,'ivy')
        card.policy={'approved':True,'unavailable':[{'start':2,'end':5,'reason':'교육'}]}
        db.commit()
    response=c.post(f"/confirmations/{source['id']}",json={'ok':True})
    assert response.status_code==200,response.text
    state=response.json()
    assert state['tasks']['draw']['d']==4 and 'weapon' not in state['tasks']
    assert state['hand']['h1']['t']==3 and not state['resolved']
    assert any('최종 제약 검증 실패' in m.get('text','') for m in state['log'])
    assert state['negotiations'][0]['status']=='waiting_pm'
