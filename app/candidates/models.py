"""Typed boundaries for feasibility design and private participant judgements."""
from typing import Literal
from pydantic import BaseModel, Field, FiniteFloat, ValidationError, model_validator
from pydantic.json_schema import SkipJsonSchema
from ..llm import ScheduleChange

class Part(BaseModel):
    key: str
    title: str
    what: str = Field(min_length=1)
    effort: FiniteFloat = Field(gt=0, le=20)
    depends_on: list[str] = Field(default_factory=list)

class SupportDesign(BaseModel):
    what: str = Field(min_length=4)
    days: FiniteFloat = Field(gt=0, le=5)
    role: str
    main_ratio: FiniteFloat = Field(gt=0, lt=1)
    basis: str = Field(min_length=8)

class ScheduledPart(Part):
    start: FiniteFloat | None = Field(default=None,ge=0,le=20)

class PlanAction(BaseModel):
    kind: Literal['defer','omit','restructure']
    task: str
    milestone: str | None = None
    parts: list[ScheduledPart] = Field(default_factory=list,max_length=4)
    basis: str = Field(min_length=8)

class Transformation(BaseModel):
    title: str
    # 빈 parts 는 '원 Task 전체 유지'로 정규화한다(generator.enumerate_plans). 이관·생략 템플릿에서
    # 모델이 plan_actions[].parts=[] 지시를 최상위 parts 로 오해해 전체 응답이 탈락하는 것을 막는다.
    parts: list[Part] = Field(default_factory=list,max_length=4)
    support: SupportDesign | None = None
    basis: str = Field(min_length=8)
    plan_actions: list[PlanAction] = Field(default_factory=list,max_length=6)
    schedule_changes: list[ScheduleChange] = Field(default_factory=list,max_length=6)

class Designs(BaseModel):
    templates: list[Transformation] = Field(default_factory=list,max_length=12)
    reason: str = ''
    # 형식이 틀린 template 하나가 응답 전체를 무효로 만들지 않도록, 개별 template만 버리고 기록한다.
    # (LLM 도구 schema에는 노출하지 않는다.)
    dropped: SkipJsonSchema[list[dict]] = Field(default_factory=list)

    @model_validator(mode='before')
    @classmethod
    def _drop_invalid_templates(cls,data):
        if not isinstance(data,dict) or not isinstance(data.get('templates'),list):return data
        kept,dropped=[],[]
        for i,raw in enumerate(data['templates']):
            try:kept.append(Transformation.model_validate(raw))
            except ValidationError as e:
                dropped.append(dict(index=i,title=(raw or {}).get('title') if isinstance(raw,dict) else None,
                    fields=[dict(path='.'.join(map(str,x['loc'])),type=x['type']) for x in e.errors(include_input=False,include_context=False,include_url=False)][:6]))
        return {**data,'templates':kept[:12],'dropped':dropped}

class Opinion(BaseModel):
    candidate_id: str
    action: Literal['ACCEPT','REJECT','NEEDS_INPUT']
    score: FiniteFloat = Field(ge=0,le=100)
    fairness_score: FiniteFloat = Field(ge=0,le=100)
    card_fit_score: FiniteFloat = Field(ge=0,le=100)
    reason: str

class Assessment(BaseModel):
    opinions: list[Opinion]
    message: str

class Speech(BaseModel):
    candidate_id: str
    recipient: str | None = None
    action: Literal['QUESTION','ANSWER','PREFER','REJECT','CONDITION','PASS']
    message: str
    # Public conditions can inform bounded supplemental generation.
    condition: str | None = None
    requires_new_candidate: bool = False
    # What the speaker relied on: 'card', 'task:<id>', 'handoff:<id>', 'plan:<candidate id>', 'history:<n>'.
    basis: list[str] = Field(default_factory=list)
    # Index in public_history of the message this one answers, if any.
    reply_to: int | None = None

    @model_validator(mode='before')
    @classmethod
    def _lenient_refs(cls,data):
        # A single reference string or an unparsable reply index must not fail the whole turn.
        if isinstance(data,dict):
            data=dict(data)
            if isinstance(data.get('basis'),str):data['basis']=[data['basis']]
            r=data.get('reply_to')
            if r is not None and not isinstance(r,int):
                try:data['reply_to']=int(str(r).strip().lstrip('#'))
                except ValueError:data['reply_to']=None
        return data

class Consent(BaseModel):
    action: Literal['ACCEPT','REJECT','NEEDS_INPUT']
    reason: str

class ConstraintReview(BaseModel):
    recipient: str | None = None
    message: str
    required_decision: str

class CandidateSettings(BaseModel):
    raw_limit: int = Field(default=500,ge=1,le=5000)
    feasible_limit: int = Field(default=50,ge=1,le=200)
    shortlist_limit: int = Field(default=10,ge=1,le=20)
    max_rounds: int = Field(default=3,ge=1,le=15)
    max_calls: int = Field(default=80,ge=1,le=500)
    max_seconds: int = Field(default=300,ge=1,le=1800)
    seed: int = 17


class TaskSelection(BaseModel):
    task_id: str | None = None
    reason: str
    clarification: str | None = None


class Slot(BaseModel):
    """A half-day the person cannot work. Code turns it into board time; the model never does arithmetic."""
    day: Literal['월', '화', '수', '목', '금']
    part: Literal['오전', '오후', '종일'] = '종일'


class ReportedChange(BaseModel):
    """Free-input scenario: what the PM's message means for the board, read by the model."""
    kind: Literal['change', 'question', 'other'] = 'change'
    answer: str | None = None
    task_id: str | None = None
    person: str | None = None
    unavailable_slots: list[Slot] = Field(default_factory=list)
    available_again: Slot | None = None
    extra_days: FiniteFloat | None = Field(default=None, ge=-5, le=5)
    summary: str = ''
    clarification: str | None = None

    @model_validator(mode='before')
    @classmethod
    def lenient(cls, v):
        # A question or chit-chat must not fail on leftover change fields.
        if isinstance(v, dict):
            v = dict(v)
            if v.get('kind') in ('question', 'other'):
                for k in ('task_id', 'person', 'unavailable_slots', 'available_again', 'extra_days'):
                    v.pop(k, None)
            if v.get('extra_days') in (0, 0.0):
                v['extra_days'] = None
            again = v.get('available_again')
            if again is not None and not isinstance(again, Slot) and not (isinstance(again, dict) and again.get('day') in ('월', '화', '수', '목', '금')):
                v['available_again'] = None
            slots = v.get('unavailable_slots')
            if 'unavailable_slots' in v and not isinstance(slots, list):
                v['unavailable_slots'] = []          # null or a stray string: no absence
            elif isinstance(slots, list):
                v['unavailable_slots'] = [x if not isinstance(x, dict) or x.get('part') in ('오전', '오후', '종일') else {**x, 'part': '종일'}
                                          for x in slots if not isinstance(x, dict) or x.get('day') in ('월', '화', '수', '목', '금')]
            if isinstance(v.get('available_again'), dict) and v['available_again'].get('part') not in ('오전', '오후', '종일'):
                v['available_again'] = {**v['available_again'], 'part': '오전'}
            for k in ('person', 'task_id'):
                x = v.get(k)
                if isinstance(x, list):             # e.g. both ends of a handoff: keep the first
                    x = next((y for y in x if isinstance(y, str)), None)
                if isinstance(x, dict):
                    x = x.get('id') or x.get('name')
                if x is not None and not isinstance(x, str):
                    x = None
                if k in v:
                    v[k] = x
        return v
