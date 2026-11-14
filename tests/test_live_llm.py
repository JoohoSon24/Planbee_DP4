"""Live 모드의 요청 · 응답 형식 테스트. OpenRouter 대신 가짜 서버를 붙인다 (실제 호출 없음)."""
import json
from types import SimpleNamespace as NS

import httpx

from app.llm import LiveLLM, Piece


def make(handler):
    return LiveLLM(client=httpx.Client(transport=httpx.MockTransport(handler)))


def reply(args):
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": "1", "type": "function", "function": {"name": "answer", "arguments": json.dumps(args)}}]}}]})


BEN = NS(id="ben", name="Ben", rec={"빌드": 5}, wants=["캐릭터 코드"])
CARD = NS(auto_days=1, refuse_tags=[], gives_help=True, note="")
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


def test_failure_falls_back_to_the_rule_based_proxy():
    llm = make(lambda r: httpx.Response(401, json={"error": {"message": "bad key"}}))
    r = llm.reply(BEN, CARD, PIECE, ctx())          # 기록 0건 → 기본 프록시는 도움을 조건으로 건다
    assert r.type == "COUNTER" and r.cond.who == "sam" and llm.failures == 1
    llm = make(lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "모르겠어요"}}]}))
    assert llm.help_reply(BEN, CARD, 30, ctx()).type == "ACCEPT"
    task = NS(id="code", title="캐릭터 넣기", d=2.5, tag="캐릭터 코드")
    assert llm.reestimate(BEN, ["기록"], [task]) is None
