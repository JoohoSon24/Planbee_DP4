"""Human-reviewed interpretation of natural-language delegation notes."""
from datetime import date
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

class TimeOff(BaseModel):
    model_config=ConfigDict(extra='forbid')
    start: FiniteFloat=Field(ge=0,le=20,multiple_of=.5)
    end: FiniteFloat=Field(gt=0,le=20,multiple_of=.5)
    reason: str=''
    start_date: str | None = None
    end_date_exclusive: str | None = None
    @model_validator(mode='after')
    def ordered(self):
        if self.end<=self.start:raise ValueError('휴가 종료는 시작보다 뒤여야 함')
        return self

class CardPolicy(BaseModel):
    model_config=ConfigDict(extra='forbid')
    week_start: str = "2026-11-16"
    source_note: str
    busy: bool=False
    unavailable: list[TimeOff]=Field(default_factory=list,max_length=16)
    weekly_limit: FiniteFloat | None=Field(default=None,ge=0,le=5,multiple_of=.5)
    questions: list[str]=Field(default_factory=list)
    approved: bool=False

    @model_validator(mode='after')
    def calendar_dates(self):
        origin=date.fromisoformat(self.week_start)
        if origin.weekday()!=0:raise ValueError("week_start는 월요일이어야 함")
        for w in self.unavailable:
            if w.start_date is not None or w.end_date_exclusive is not None:
                if not w.start_date or not w.end_date_exclusive:
                    raise ValueError('휴가 날짜의 시작과 종료가 모두 필요함')
                a=(date.fromisoformat(w.start_date)-origin).days
                z=(date.fromisoformat(w.end_date_exclusive)-origin).days
                if not 0<=a<z<=20:
                    raise ValueError('휴가 날짜가 달력 범위를 벗어남')
                w.start,w.end=float(a),float(z)
        return self


def active(card):
    raw=getattr(card,'policy',None) or {}
    return raw if raw.get('approved') else {}


def needs_review(card):
    raw=getattr(card,'policy',None) or {}
    return bool(raw.get('needs_review') or active(card).get('busy'))
