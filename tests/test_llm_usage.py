"""토큰 사용량 집계와 /llm/usage. OpenRouter 대신 가짜 서버를 붙인다 (실제 호출 없음)."""
import json

import httpx
from fastapi.testclient import TestClient

from app import usage
from app.llm import LiveLLM
from tests.test_live_llm import BEN, CARD, PIECE, ctx


def reply(args, used=None):
    body = {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": "1", "type": "function", "function": {"name": "answer", "arguments": json.dumps(args)}}]}}]}
    if used is not None:
        body["usage"] = used
    return httpx.Response(200, json=body)


def test_live_call_records_tokens_and_requests_cost():
    usage.reset()
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        return reply({"type": "ACCEPT", "days": 1, "reason": "가능"},
                     {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150, "cost": 0.0012})

    llm = LiveLLM(client=httpx.Client(transport=httpx.MockTransport(handler)))
    llm.key, llm.model = "k", "test/model"
    llm.reply(BEN, CARD, PIECE, ctx())
    llm.reply(BEN, CARD, PIECE, ctx())
    assert seen["body"]["usage"] == {"include": True}
    s = usage.snapshot("mock", None)
    assert s["total"] == {"calls": 2, "prompt_tokens": 240, "completion_tokens": 60, "total_tokens": 300, "cost": 0.0024}
    assert s["by_model"]["test/model"]["calls"] == 2 and len(s["recent"]) == 2 and s["missing_usage"] == 0


def test_response_without_usage_still_counts_call():
    usage.reset()
    llm = LiveLLM(client=httpx.Client(transport=httpx.MockTransport(lambda req: reply({"type": "ACCEPT", "days": 1, "reason": "가능"}))))
    llm.key = "k"
    llm.reply(BEN, CARD, PIECE, ctx())
    s = usage.snapshot("mock", None)
    assert s["total"]["calls"] == 1 and s["total"]["total_tokens"] == 0 and s["missing_usage"] == 1


def test_credit_reads_openrouter_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(httpx, "get", lambda url, **kw: httpx.Response(
        200, json={"data": {"limit": 5.0, "limit_remaining": 4.25, "usage": 0.75, "usage_daily": 0.1}},
        request=httpx.Request("GET", url)))
    c = usage.credit(force=True)
    assert c["available"] and c["remaining"] == 4.25 and c["limit"] == 5.0


def test_usage_endpoint_and_reset():
    from app.api import app
    usage.reset()
    usage.record("m", {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "cost": 0.001}, "Reply")
    client = TestClient(app)
    s = client.get("/llm/usage").json()
    assert s["mode"] == "mock" and s["credit"] is None and s["total"]["total_tokens"] == 15
    assert client.post("/llm/usage/reset").json() == {"ok": True}
    assert client.get("/llm/usage").json()["total"]["calls"] == 0
