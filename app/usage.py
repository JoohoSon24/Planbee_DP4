"""Live LLM 토큰 사용량과 OpenRouter 키의 남은 크레딧. 서버 프로세스 동안만 메모리에 쌓는다.

record()      LiveLLM 이 응답을 받을 때마다 부른다 (OpenRouter usage: 토큰 · 비용).
snapshot()    GET /llm/usage 가 돌려주는 값. 남은 크레딧은 OpenRouter /key 를 15초 캐시로 조회한다.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone

KEY_URL = "https://openrouter.ai/api/v1/key"
CREDIT_TTL = 15.0
RECENT = 20

_lock = threading.Lock()
_credit = {"at": 0.0, "value": None}


def _empty() -> dict:
    return {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost": 0.0}


def _fresh() -> dict:
    return {"since": datetime.now(timezone.utc).isoformat(), "total": _empty(), "by_model": {}, "by_kind": {},
            "recent": [], "missing_usage": 0}


_state = _fresh()


def _add(bucket: dict, tokens: dict) -> None:
    bucket["calls"] += 1
    for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
        bucket[k] += tokens[k]
    bucket["cost"] += tokens["cost"]


def record(model: str, usage: dict | None, kind: str = "") -> None:
    """응답 하나의 usage 를 더한다. usage 가 없는 응답도 호출 수에는 넣고 따로 센다."""
    usage = usage or {}
    prompt, completion = int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
    tokens = {"prompt_tokens": prompt, "completion_tokens": completion,
              "total_tokens": int(usage.get("total_tokens") or prompt + completion), "cost": float(usage.get("cost") or 0.0)}
    with _lock:
        _add(_state["total"], tokens)
        _add(_state["by_model"].setdefault(model, _empty()), tokens)
        _add(_state["by_kind"].setdefault(kind or "기타", _empty()), tokens)
        if not usage:
            _state["missing_usage"] += 1
        _state["recent"] = ([{"t": datetime.now(timezone.utc).isoformat(), "model": model, "kind": kind, **tokens}]
                            + _state["recent"])[:RECENT]


def reset() -> None:
    global _state
    with _lock:
        _state = _fresh()


def credit(force: bool = False) -> dict | None:
    """OpenRouter 키의 한도 · 사용액 · 남은 액수 (USD). 키가 없으면 None."""
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        return None
    now = time.monotonic()
    if not force and _credit["value"] is not None and now - _credit["at"] < CREDIT_TTL:
        return _credit["value"]
    import httpx
    try:
        r = httpx.get(KEY_URL, headers={"Authorization": f"Bearer {key}"}, timeout=5)
        r.raise_for_status()
        d = r.json().get("data") or {}
        value = {"available": True, "limit": d.get("limit"), "remaining": d.get("limit_remaining"),
                 "usage": d.get("usage"), "usage_daily": d.get("usage_daily"), "limit_reset": d.get("limit_reset"),
                 "checked_at": datetime.now(timezone.utc).isoformat()}
    except Exception as e:  # 조회 실패는 화면에 이유만 보인다
        value = {"available": False, "error": f"{type(e).__name__}", "checked_at": datetime.now(timezone.utc).isoformat()}
    _credit.update(at=now, value=value)
    return value


def snapshot(mode: str, model: str | None) -> dict:
    with _lock:
        s = {k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v) for k, v in _state.items()}
        s["by_model"] = {k: dict(v) for k, v in _state["by_model"].items()}
        s["by_kind"] = {k: dict(v) for k, v in _state["by_kind"].items()}
    s.update(mode=mode, model=model, credit=credit() if mode == "live" else None)
    return s
