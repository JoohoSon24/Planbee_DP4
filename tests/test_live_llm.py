"""Live 모드의 요청 · 응답 형식 테스트. OpenRouter 대신 가짜 서버를 붙인다 (실제 호출 없음)."""
import json
from types import SimpleNamespace as NS

import httpx
import pytest

from app.llm import LiveLLM, Piece


def make(handler):
    return LiveLLM(client=httpx.Client(transport=httpx.MockTransport(handler)))


def reply(args):
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": "1", "type": "function", "function": {"name": "answer", "arguments": json.dumps(args)}}]}}]})


BEN = NS(id="ben", name="Ben", rec={"빌드": 5}, wants=["캐릭터 코드"])
CARD = NS(auto_days=1, refuse_tags=[], gives_help=True, note="", wait_days=0, model=None)
PIECE = Piece(title="움직임 코드", days=1, tag="캐릭터 코드")
SAM = NS(id="sam", name="Sam")


def ctx(**kw):
    return {"load": 2, "cap": 5, "default_days": 1.5, "deferrable": [], "mentor": SAM, "violation": None, **kw}


def test_request_shape_and_parse():
    seen = {}

    def handler(req):
        seen["url"], seen["auth"], seen["body"] = str(req.url), req.headers["authorization"], json.loads(req.content)
        return reply({"type": "COUNTER", "days": 1.5, "cond": {"kind": "help", "who": "sam"}, "reason": "Sam의 도움이 필요"})

    llm = make(handler)
    llm.key = "test-key"
    r = llm.reply(BEN, CARD, PIECE, ctx())
    assert r.type == "COUNTER" and r.cond.kind == "help" and r.cond.who == "sam" and r.days == 1.5
    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions" and seen["auth"] == "Bearer test-key"
    b = seen["body"]
    assert b["tool_choice"] == {"type": "function", "function": {"name": "answer"}}
    assert set(b["tools"][0]["function"]["parameters"]["properties"]) >= {"type", "days", "cond", "reason"}
    user = b["messages"][1]["content"]
    assert "Ben" in user and "위임 카드" in user and "ACCEPT" in user


def test_violation_is_passed_back_to_the_model():
    seen = []
    llm = make(lambda req: (seen.append(json.loads(req.content)["messages"][1]["content"]), reply({"type": "REJECT", "reason": "꽉 참"}))[1])
    llm.reply(BEN, CARD, PIECE, ctx(violation={"code": "OVERLOAD", "text": "Ben 5 + 1½ = 6½/5일로 넘침"}))
    assert "직전 답이 반려된 이유" in seen[0] and "넘침" in seen[0]


def test_failure_never_falls_back_to_a_mock_acceptance():
    llm = make(lambda r: httpx.Response(401, json={"error": {"message": "bad key"}}))
    r = llm.reply(BEN, CARD, PIECE, ctx())          # 기록 0건 → 기본 프록시는 도움을 조건으로 건다
    assert r.type == "REJECT" and 'LLM 응답 실패' in r.reason and llm.failures == 1
    llm = make(lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "모르겠어요"}}]}))
    assert llm.help_reply(BEN, CARD, 30, ctx()).type == "REJECT"
    task = NS(id="code", title="캐릭터 넣기", d=2.5, tag="캐릭터 코드")
    assert llm.reestimate(BEN, ["기록"], [task]) is None


def test_each_proxy_can_use_its_own_model_and_sees_its_thread():
    seen = []
    llm = make(lambda req: (seen.append(json.loads(req.content)), reply({"type": "ACCEPT", "days": 1}))[1])
    other = NS(auto_days=1, refuse_tags=[], gives_help=True, note="", wait_days=0, model="anthropic/claude-haiku-5-5")
    llm.reply(BEN, CARD, PIECE, ctx())
    llm.reply(BEN, other, PIECE, ctx(thread=["Leo → 나 · 질문: 움직임 코드 · 1일 · 금 오전까지 돼요?"]))
    assert [b["model"] for b in seen] == [llm.model, "anthropic/claude-haiku-5-5"]
    assert "지금까지 내가 주고받은 말" in seen[1]["messages"][1]["content"] and "금 오전까지 돼요?" in seen[1]["messages"][1]["content"]


def test_receiver_request_shape():
    seen = []
    llm = make(lambda req: (seen.append(json.loads(req.content)["messages"][1]["content"]), reply({"type": "NEEDS_INPUT", "reason": "본인에게 물어야 함"}))[1])
    zoe = NS(id="zoe", name="Zoe", rec={}, wants=[])
    r = llm.wait_reply(zoe, CARD, {"title": "캐릭터 코드", "old": "금 오전", "new": "금 저녁", "late_by": 0.5, "pushed": ["캐릭터 테스트"], "breaks": []})
    assert r.type == "NEEDS_INPUT" and "금 오전 → 금 저녁" in seen[0] and "캐릭터 테스트" in seen[0]


def test_discussion_record_does_not_invent_an_estimate_change():
    task=NS(id='work',title='상태 전이·계약 검증',d=3,tag='계약',context={})
    adapter=make(lambda req:reply(dict(duration_changed=True,task='work',days=4,basis='분담 논의로 범위 증가',evidence='')))
    assert adapter.reestimate(BEN,['계약 검증 분담을 논의합니다.'],[task]) is None
    adapter=make(lambda req:reply(dict(duration_changed=True,task='work',days=4,basis='독립 검증 추가',evidence='검증 추가로 하루 증가')))
    assert adapter.reestimate(BEN,['검증 추가로 하루 증가'],[task]).days==4


def test_live_wait_prompt_distinguishes_receiving_from_taking_new_work():
    seen=[]
    adapter=make(lambda req:(seen.append(json.loads(req.content)['messages'][1]['content']),reply(dict(type='REJECT',reason='수신 기한을 넘음')))[1])
    adapter.wait_reply(BEN,CARD,dict(title='계약 동결본',old='수 저녁',new='목 저녁',late_by=1,pushed=[],breaks=[]))
    assert '새 업무를 맡는 것이 아니라' in seen[0]
    assert '거절 근거로 혼동하지 말고' in seen[0]


def test_discussion_keeps_own_allocation_and_repair_feedback_explicit():
    seen=[]
    adapter=make(lambda req:(seen.append(json.loads(req.content)['messages'][1]['content']),
        reply(dict(action='PASS',reason='대안 없음')))[1])
    adapter.discuss(BEN,CARD,dict(mode='revise',source='sam',proposal=[dict(who='ben',days=.5),dict(who='sam',days=2)],
        validation_feedback=[dict(code='OWNER_IN_PIECE')]))
    facts=json.loads(seen[0].split('\n\n',1)[1])
    assert facts['current_request']['prior_proposal_to_revise'][0]==dict(who='ben',days=.5)
    assert facts['self']['is_original_owner'] is False
    assert facts['design_request']['latest_validation'][0]['code']=='OWNER_IN_PIECE'


def test_consent_call_does_not_request_allocations_or_copy_historical_proposals():
    seen=[]
    adapter=make(lambda req:(seen.append(json.loads(req.content)),reply(dict(settings_check='compatible',settings_reason='메모 범위 안',max_incoming_days=None,action='ACCEPT',reason='현재 배분 동의')))[1])
    result=adapter.discuss(BEN,CARD,dict(mode='respond',version=3,source='sam',
        proposal=[dict(who='ben',days=.5)],history=[dict(requester='sam',recipient='ben',response='COUNTER',
            reason='이전 조건',proposal=[dict(what='old draft must not be copied')])]))
    assert result.action=='ACCEPT' and len(seen)==1
    assert set(seen[0]['tools'][0]['function']['parameters']['properties'])=={'action','reason','settings_check','settings_reason','max_incoming_days'}
    facts=json.loads(seen[0]['messages'][1]['content'].split('\n\n',1)[1])
    assert facts['public_history'][0]['reason']=='이전 조건'
    assert 'old draft must not be copied' not in str(facts)
    assert facts['current_request']['version']==3


def test_counter_decision_gets_separate_proposal_call_without_fabricating_consent():
    seen=[]
    def handler(req):
        seen.append(json.loads(req.content))
        return reply(dict(settings_check='forbidden',settings_reason='분량 초과',max_incoming_days=.5,action='COUNTER',reason='분량 조정') if len(seen)==1 else
            dict(action='COUNTER',reason='새 분담',proposal_scope='piece',allocations=[dict(who='ben',title='정상 경로',what='정상 경로',days=.5,effort=.5)]))
    result=make(handler).discuss(BEN,CARD,dict(mode='respond',proposal=[],source='sam'))
    assert len(seen)==2 and result.action=='COUNTER'
    assert seen[1]['tools'][0]['function']['parameters']['properties']['action']['enum']==['COUNTER','PASS']


def test_model_classified_card_prohibition_cannot_be_bypassed_by_confirmation():
    adapter=make(lambda req:reply(dict(settings_check='forbidden',settings_reason='메모에서 허용한 실제 분량 초과',max_incoming_days=.5,action='NEEDS_INPUT',reason='권한 초과')))
    result=adapter.discuss(BEN,CARD,dict(mode='respond',proposal=[],source='sam'))
    assert result.action=='REJECT' and '실제 분량 초과' in result.reason


def test_capacity_retry_recovers_without_changing_model_or_inventing_consent(monkeypatch):
    seen=[];sleeps=[]
    monkeypatch.setattr('app.llm.time.sleep',sleeps.append)
    def handler(req):
        seen.append(json.loads(req.content)['model'])
        return httpx.Response(503,headers={'retry-after':'1'}) if len(seen)<3 else reply(dict(type='ACCEPT',days=1,reason='동의'))
    adapter=make(handler)
    assert adapter.reply(BEN,CARD,PIECE,ctx()).type=='ACCEPT'
    assert len(set(seen))==1 and len(seen)==3 and len(sleeps)==2
    assert adapter.failures==0 and adapter.retries==2


def test_long_retry_after_and_auth_failure_do_not_trigger_rapid_retries(monkeypatch):
    monkeypatch.setattr('app.llm.time.sleep',lambda _:pytest.fail('must not sleep'))
    for status,headers in [(503,{'retry-after':'60'}),(401,{})]:
        adapter=make(lambda req:httpx.Response(status,headers=headers))
        assert adapter.reply(BEN,CARD,PIECE,ctx()).type=='REJECT'
        assert adapter.request_attempts==1


def test_model_selects_pattern_and_defines_scopes_without_code_selecting_winner():
    seen=[]
    adapter=make(lambda req:(seen.append(json.loads(req.content)),reply(dict(action='COUNTER',reason='두 범위를 나눔',pattern_index=1,
        scopes=[dict(title='상태 전이 코어',what='상태 전이 구현',key='core'),dict(title='실패 검증',what='실패 사례 검증',key='failure')])))[1])
    patterns=[
        [dict(who='sam',days=2,effort=2),dict(who='ben',days=1,effort=1)],
        [dict(who='sam',days=2.5,effort=2.5),dict(who='ben',days=.5,effort=.5)]]
    result=adapter.discuss(BEN,CARD,dict(mode='revise',source='sam',proposal=[],recovery_strategy='independent_split',schedule_workload_patterns={'patterns':patterns}))
    assert result.proposal_scope=='whole_task'
    assert [(a.who,a.days,a.effort) for a in result.allocations]==[('sam',2.5,2.5),('ben',.5,.5)]
    assert len(seen)==1 and result.allocations[1].what=='실패 사례 검증'


def test_invalid_pattern_selection_is_not_replaced_with_an_automatic_allocation():
    adapter=make(lambda req:reply(dict(action='COUNTER',reason='없는 숫자 조합',pattern_index=99,scopes=[])))
    result=adapter.discuss(BEN,CARD,dict(mode='revise',proposal=[],recovery_strategy='independent_split',schedule_workload_patterns={'patterns':[[dict(who='ben',days=1,effort=1)]]}))
    assert result.action=='COUNTER' and not result.allocations


def test_live_system_pins_current_actor_and_only_their_card():
    seen=[]
    adapter=make(lambda req:(seen.append(json.loads(req.content)),reply(dict(action='PASS',reason='대안 없음')))[1])
    adapter.discuss(BEN,CARD,dict(mode='revise',proposal=[],history=[dict(requester='sam',reason='Sam의 공개 거절')]))
    system=seen[0]['messages'][0]['content']
    assert 'Ben (ben)' in system and '본인의 위임 설정' in system
    assert 'Sam의 공개 거절' not in system


def test_negotiation_budget_counts_transport_retries_and_propagates(monkeypatch):
    from app.negotiation_budget import bound, CallBudgetExceeded
    monkeypatch.setattr('app.llm.time.sleep',lambda _:None)
    seen=[]
    adapter=make(lambda req:(seen.append(req),httpx.Response(503))[1])
    budget=dict(used=0,max=2)
    with bound(budget),pytest.raises(CallBudgetExceeded):
        adapter._ask(Piece,'test',{})
    assert len(seen)==2 and budget['used']==2
    # A later request in the same run cannot bypass the exhausted shared budget.
    with bound(budget),pytest.raises(CallBudgetExceeded):
        adapter._ask(Piece,'test',{})
    assert len(seen)==2
