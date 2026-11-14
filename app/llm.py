"""프록시. 사람마다 하나씩, 그 사람의 기록 · 일정 · 위임 카드만 보고 답한다.

프록시가 하는 일: 견적 고치기, 떼어 낼 조각 정하기, 요청에 ACCEPT / REJECT / COUNTER / NEEDS_INPUT 로 답하기.
Hive(hive.py)는 그 답이 규칙 안인지만 검사한다.

PLANBEE_LLM=mock (기본)  seed/mock_llm.yaml 대본대로 답한다. 시연과 테스트가 매번 같다.
PLANBEE_LLM=live         OpenRouter 를 부른다. OPENROUTER_API_KEY 필요.
                         모델은 PLANBEE_MODEL 로 바꾼다 (도구 호출을 지원하는 모델이어야 함).
모든 답은 pydantic 으로 모양을 강제하고, 숫자는 코드가 한 번 더 범위를 자른다.
"""
from __future__ import annotations

import json
import math
import os

from typing import Literal

from pydantic import BaseModel, Field

from . import hive
from .store import load_yaml


class Reestimate(BaseModel):
    task: str
    days: float = Field(gt=0, le=10)
    basis: str = ""


class Piece(BaseModel):
    id: str | None = None
    title: str
    days: float = Field(gt=0, le=5)
    tag: str
    what: str = ""
    reason: str = "따로 할 수 있음"
    basis: str = ""
    handover: str = ""


class Part(BaseModel):
    id: str | None = None
    title: str
    days: float | None = None


class Split(BaseModel):
    piece: Piece
    to: str = "self"                 # self | downstream
    keep: Part | None = None
    extra: list[Part] = []
    rename_handoff: str | None = None


class Cond(BaseModel):
    kind: Literal["help", "defer"]       # help: 누가 30분 봐 주면 가능 · defer: 내 일 하나를 2주차로 미루면 가능
    who: str | None = None               # help 일 때 도움을 청할 사람 id
    task: str | None = None              # defer 일 때 미룰 내 일 id
    minutes: int = 30


class Reply(BaseModel):
    """프록시가 고르는 답. Hive 는 이 답이 규칙 안인지만 검사한다."""
    type: Literal["ACCEPT", "REJECT", "COUNTER", "NEEDS_INPUT"]
    days: float | None = Field(default=None, gt=0, le=10)
    cond: Cond | None = None
    reason: str = ""                     # 왜 이 답인지 한 줄 (PM 에게 그대로 보임)
    say: str = ""                        # 상대 프록시에게 덧붙이는 말


def _round_half(x: float) -> float:
    return max(0.5, round(x * 2) / 2)


class MockLLM:
    """대본이 있으면 대본, 없으면 기록 건수로 계산한 기본값."""

    def __init__(self):
        self.script = load_yaml("mock_llm.yaml")

    def reestimate(self, person, records: list[str], tasks: list) -> Reestimate | None:
        for rule in self.script.get("reestimate", []):
            m = rule["match"]
            if m["who"] == person.id and any(m["contains"] in r for r in records):
                return Reestimate(**rule["answer"])
        return None

    def split(self, person, task, piece_hint: float) -> Split | None:
        s = self.script.get("split", {}).get(task.id)
        if s:
            return Split(**s)
        if task.d < 1:
            return None
        days = _round_half(min(piece_hint, task.d - 0.5))
        return Split(piece=Piece(title=f"{task.title} 일부", days=days, tag=task.tag,
                                 what=f"{task.title} 일부", basis="늦어진 만큼 떼어 냄"), to="self")

    # 아래 둘이 Mock 프록시의 '머리'다. 자기 사람의 카드 · 일정 · 기록만 보고 답 유형을 고른다.
    # c = {load, cap, default_days, deferrable: [일], mentor: 사람|None, violation: Hive 가 반려한 이유|None}
    def reply(self, person, card, piece: Piece, c: dict) -> Reply:
        s = self.script.get("bid", {}).get(piece.title, {}).get(person.id, {})
        days, say = s.get("days", c["default_days"]), s.get("say", "")
        if piece.tag in (card.refuse_tags or []):
            return Reply(type="REJECT", reason=f"카드에 '{piece.tag}'{'은' if hive.has_final(piece.tag) else '는'} 받지 않는다고 되어 있음")
        if c["load"] + days > c["cap"] + hive.EPS:
            if c["deferrable"]:
                t = c["deferrable"][0]
                return Reply(type="COUNTER", days=days, cond=Cond(kind="defer", task=t.id),
                             reason=f"{t.title}{'을' if hive.has_final(t.title) else '를'} 2주차로 미루면 가능")
            return Reply(type="REJECT", reason=f"금까지 {hive.num(c['load'])}/{hive.num(c['cap'])}일로 꽉 참")
        if (person.rec or {}).get(piece.tag, 0) == 0 and c["mentor"] is not None:
            m = c["mentor"]
            return Reply(type="COUNTER", days=days, cond=Cond(kind="help", who=m.id),
                         reason=f"{m.name}의 30분 도움이 필요", say=say or f"{hive.josa(m.name, '이', '가')} 30분만 봐 주면 돼요.")
        if days > card.auto_days + hive.EPS:
            return Reply(type="NEEDS_INPUT", days=days, reason=f"내 한도 {hive.num(card.auto_days)}일을 넘음", say=say)
        return Reply(type="ACCEPT", days=days, say=say)

    def help_reply(self, person, card, minutes: int, c: dict) -> Reply:
        if not card.gives_help:
            return Reply(type="REJECT", reason="카드에 도움 요청은 받지 않는다고 되어 있음")
        if c["load"] > c["cap"] - hive.EPS:
            if c["deferrable"]:
                t = c["deferrable"][0]
                return Reply(type="COUNTER", cond=Cond(kind="defer", task=t.id),
                             reason=f"{t.title}{'을' if hive.has_final(t.title) else '를'} 2주차로 미루면 가능")
            return Reply(type="REJECT", reason="금까지 꽉 참")
        return Reply(type="ACCEPT", say=card.note or "")

    def reagree_note(self, person) -> str:
        return self.script.get("reagree_note", {}).get(person.id, "")


class LiveLLM(MockLLM):
    """실제 LLM (OpenRouter). 답을 못 받거나 모양이 틀리면 Mock 의 기본값으로 떨어진다."""

    URL = "https://openrouter.ai/api/v1/chat/completions"
    SYSTEM = ("너는 게임 개발팀 한 사람의 일정 프록시다. 그 사람의 기록만 근거로 답한다. "
              "반드시 answer 함수를 한 번 호출해 답한다. 근거가 없으면 지어내지 않는다.")

    def __init__(self, client=None):
        super().__init__()
        self.script = {}           # 대본을 쓰지 않는다
        import httpx
        self.key = os.environ.get("OPENROUTER_API_KEY", "")
        if not self.key and client is None:
            raise RuntimeError("PLANBEE_LLM=live 인데 OPENROUTER_API_KEY 가 없음 (.env 파일 또는 환경 변수)")
        self.model = os.environ.get("PLANBEE_MODEL", "openai/gpt-4o-mini")
        self.client = client or httpx.Client(timeout=40)
        self.calls = self.failures = 0

    def _ask(self, model_cls, instruction: str, facts: dict):
        self.calls += 1
        try:
            r = self.client.post(self.URL, headers={"Authorization": f"Bearer {self.key}", "X-Title": "Plan Bee"}, json={
                "model": self.model, "max_tokens": 600, "temperature": 0,
                "messages": [{"role": "system", "content": self.SYSTEM},
                             {"role": "user", "content": instruction + "\n\n" + json.dumps(facts, ensure_ascii=False)}],
                "tools": [{"type": "function", "function": {"name": "answer", "description": instruction,
                                                            "parameters": model_cls.model_json_schema()}}],
                "tool_choice": {"type": "function", "function": {"name": "answer"}},
            })
            r.raise_for_status()
            msg = r.json()["choices"][0]["message"]
            calls = msg.get("tool_calls") or []
            raw = calls[0]["function"]["arguments"] if calls else msg.get("content") or ""
            return model_cls(**(json.loads(raw) if isinstance(raw, str) else raw))
        except Exception as e:  # 네트워크 · 모양 오류는 기본값으로
            self.failures += 1
            print(f"[llm] live 호출 실패, 기본값 사용 ({self.model}): {type(e).__name__}: {str(e)[:200]}")
        return None

    def reestimate(self, person, records, tasks):
        facts = {"사람": person.name, "새 기록": records,
                 "맡은 일": [{"id": t.id, "제목": t.title, "현재 견적(일)": t.d, "태그": t.tag} for t in tasks]}
        ans = self._ask(Reestimate, "새 기록 때문에 견적이 달라지는 일이 있으면 task(id), days(새 견적, 0.5 단위), "
                                    "basis(근거 한 줄)를 답하라. 달라질 일이 없으면 task 를 빈 문자열로.", facts)
        if not ans or ans.task not in {t.id for t in tasks}:
            return None
        ans.days = _round_half(ans.days)
        return ans

    def split(self, person, task, piece_hint):
        facts = {"사람": person.name, "일": task.title, "태그": task.tag, "현재 견적(일)": task.d,
                 "줄여야 하는 일수": piece_hint}
        ans = self._ask(Split, "이 일에서 다른 사람에게 따로 맡길 수 있는 조각 하나를 정하라. piece.days 는 0.5 단위, "
                               "piece.tag 는 일의 태그와 같게. keep.title 은 남은 일의 이름.", facts)
        if not ans:
            return super().split(person, task, piece_hint)
        ans.piece.days = _round_half(min(ans.piece.days, task.d - 0.5))
        ans.piece.tag, ans.piece.id, ans.extra = task.tag, None, []
        if ans.keep:
            ans.keep.id, ans.keep.days = None, None
        return ans

    RULES = ("답 유형은 넷 중 하나다. ACCEPT: 카드 한도 안이고 일정에 들어가서 내가 알아서 맡음. "
             "NEEDS_INPUT: 들어가지만 카드의 auto_days 를 넘어 본인에게 물어야 함. "
             "COUNTER: 조건이 맞으면 가능. cond.kind=help 는 같은 역할의 한 사람(cond.who=id)이 30분 봐 주면, "
             "cond.kind=defer 는 '미룰 수 있는 내 일' 중 하나(cond.task=id)를 2주차로 미루면. "
             "REJECT: 맡을 수 없음. reason 에 이유를 한 줄로 쓴다. 일수는 0.5 단위.")

    def _facts(self, person, card, c):
        f = {"사람": person.name, "과거 기록(태그별 건수)": person.rec, "바라는 일": person.wants,
             "위임 카드": {"auto_days": card.auto_days, "받지 않는 일": card.refuse_tags, "도움 요청 받음": card.gives_help, "메모": card.note},
             "이번 주 잡힌 일수": c["load"], "한 주 한도": c["cap"],
             "미룰 수 있는 내 일": [{"id": t.id, "제목": t.title, "일수": t.d} for t in c["deferrable"]]}
        if c.get("violation"):
            f["직전 답이 반려된 이유"] = c["violation"]["text"]
        return f

    def reply(self, person, card, piece, c):
        facts = self._facts(person, card, c)
        facts.update({"요청": {"조각": piece.title, "태그": piece.tag, "숙련자 기준(일)": piece.days, "내 기록 기준 기본값(일)": c["default_days"]},
                      "도움을 청할 수 있는 사람": [{"id": c["mentor"].id, "이름": c["mentor"].name}] if c["mentor"] is not None else []})
        ans = self._ask(Reply, "이 조각을 맡아 달라는 요청에 답하라. " + self.RULES, facts)
        return ans or super().reply(person, card, piece, c)

    def help_reply(self, person, card, minutes, c):
        facts = self._facts(person, card, c)
        facts["요청"] = f"다른 팀원이 {minutes}분 도움(리뷰)을 청함"
        ans = self._ask(Reply, "이 도움 요청에 답하라. days 는 비운다. help 조건은 쓸 수 없다. " + self.RULES, facts)
        return ans or super().help_reply(person, card, minutes, c)

    def reagree_note(self, person) -> str:
        return ""


_llm = None


def get_llm():
    global _llm
    if _llm is None:
        _llm = LiveLLM() if os.environ.get("PLANBEE_LLM", "mock") == "live" else MockLLM()
    return _llm


def set_llm(llm) -> None:
    global _llm
    _llm = llm


def default_bid_days(b: hive.Board, piece: Piece, pid: str, owner: str) -> float:
    return hive.scaled_days(b, piece.days, piece.tag, pid, owner)
