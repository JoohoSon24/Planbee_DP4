"""Typed boundaries for feasibility design and private participant judgements."""
from typing import Literal
from pydantic import BaseModel, Field, FiniteFloat, model_validator
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
    reason: str

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
