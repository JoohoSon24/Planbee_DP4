"""DB 스키마. 프로토타입의 상태 S를 테이블로 옮긴 것."""
from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Person(Base):
    """팀원. 프록시는 사람과 1:1이라 별도 테이블 없이 이 행을 근거 자료로 쓴다."""
    __tablename__ = "person"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String)            # 그림 · 개발 · 테스트
    rec: Mapped[dict] = mapped_column(JSON, default=dict)   # 태그별 과거 작업 건수 (프록시의 견적 근거)
    wants: Mapped[list] = mapped_column(JSON, default=list)  # 해 보고 싶은 일 태그
    notes: Mapped[dict] = mapped_column(JSON, default=dict)  # 개인 선호 (예: 리뷰 시간대)
    oi: Mapped[int] = mapped_column(Integer, default=0)


class Card(Base):
    """위임 카드. 사람이 자기 프록시에게 맡긴 권한과 한도."""
    __tablename__ = "card"
    person_id: Mapped[str] = mapped_column(ForeignKey("person.id"), primary_key=True)
    auto_days: Mapped[float] = mapped_column(Float, default=1.0)      # 이 일수까지는 프록시가 알아서 수락
    refuse_tags: Mapped[list] = mapped_column(JSON, default=list)     # 받지 않는 일 종류
    gives_help: Mapped[bool] = mapped_column(Boolean, default=True)   # 30분 도움 요청을 프록시가 받아도 되는가
    note: Mapped[str] = mapped_column(String, default="")             # 약속할 때 덧붙이는 조건


class Task(Base):
    __tablename__ = "task"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    who: Mapped[str] = mapped_column(ForeignKey("person.id"))
    who0: Mapped[str | None] = mapped_column(String, nullable=True)  # 옮겨 오기 전 담당
    title: Mapped[str] = mapped_column(String)
    s0: Mapped[float] = mapped_column(Float)   # 계획 시작 (0 = 월 아침, 5 = 2주차 월 아침)
    s: Mapped[float] = mapped_column(Float)    # Hive가 계산한 실제 시작
    d: Mapped[float] = mapped_column(Float)    # 현재 견적 (일)
    plan: Mapped[float] = mapped_column(Float)  # 처음 계획한 길이
    base: Mapped[float] = mapped_column(Float)  # 숙련자 기준 길이
    tag: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String, default="")   # "" · done · prop · new
    oi: Mapped[int] = mapped_column(Integer, default=0)
    cut: Mapped[bool] = mapped_column(Boolean, default=False)
    got: Mapped[bool] = mapped_column(Boolean, default=False)
    cut_options: Mapped[list] = mapped_column(JSON, default=list)  # PM이 허락하면 줄일 수 있는 범위


class Handoff(Base):
    __tablename__ = "handoff"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    from_task: Mapped[str] = mapped_column(ForeignKey("task.id"))
    to_task: Mapped[str] = mapped_column(ForeignKey("task.id"))
    title: Mapped[str] = mapped_column(String)
    what: Mapped[str] = mapped_column(String)
    t: Mapped[float] = mapped_column(Float)     # 약속 시각
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    prop: Mapped[bool] = mapped_column(Boolean, default=False)    # 가약속
    agreed: Mapped[bool] = mapped_column(Boolean, default=False)  # 다시 정함
    basis: Mapped[str] = mapped_column(String, default="")
    oi: Mapped[int] = mapped_column(Integer, default=0)


class HandoffEvent(Base):
    __tablename__ = "handoff_event"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    handoff_id: Mapped[str] = mapped_column(ForeignKey("handoff.id"))
    t: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)   # hive · proxy · pm · person
    who: Mapped[str | None] = mapped_column(String, nullable=True)
    text: Mapped[str] = mapped_column(Text)


class Record(Base):
    """입력 화면의 '들어온 기록'. 팀 도구에서 자동으로 들어오거나 PM 결정이 남는다."""
    __tablename__ = "record"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    t: Mapped[str] = mapped_column(String)
    src: Mapped[str] = mapped_column(String)    # 작업 · 저장소 · 메신저 · PM
    who: Mapped[str | None] = mapped_column(String, nullable=True)
    text: Mapped[str] = mapped_column(Text)
    old: Mapped[bool] = mapped_column(Boolean, default=False)
    fresh: Mapped[bool] = mapped_column(Boolean, default=False)


class Rule(Base):
    """PM이 정한 규칙. Hive는 이 안에서만 움직인다."""
    __tablename__ = "rule"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    label: Mapped[str] = mapped_column(String)
    value: Mapped[dict] = mapped_column(JSON)
    locked: Mapped[bool] = mapped_column(Boolean, default=True)
    oi: Mapped[int] = mapped_column(Integer, default=0)


class Grant(Base):
    """PM이 한 번 허락한 예외."""
    __tablename__ = "grant"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    label: Mapped[str] = mapped_column(String)
    key: Mapped[str] = mapped_column(String)
    ask_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    t: Mapped[str] = mapped_column(String)


class Message(Base):
    """오간 말. k = proxy(프록시끼리) · hive(규칙 계산) · person(사람 확인) · pm(PM 조작)."""
    __tablename__ = "message"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    k: Mapped[str] = mapped_column(String)
    frm: Mapped[str | None] = mapped_column(String, nullable=True)
    to: Mapped[str | None] = mapped_column(String, nullable=True)
    act: Mapped[str | None] = mapped_column(String, nullable=True)  # 견적 · 조건 · 질문 · 약속 · 알림 · 넘김
    fields: Mapped[list] = mapped_column(JSON, default=list)
    basis: Mapped[str] = mapped_column(String, default="")
    pref: Mapped[str] = mapped_column(String, default="")
    say: Mapped[str] = mapped_column(String, default="")
    text: Mapped[str] = mapped_column(Text, default="")
    who: Mapped[str | None] = mapped_column(String, nullable=True)
    hid: Mapped[str | None] = mapped_column(String, nullable=True)
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    t: Mapped[str] = mapped_column(String, default="")


class Confirmation(Base):
    """프록시가 사람의 시간을 약속하기 전에 받는 원터치 확인."""
    __tablename__ = "confirmation"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    who: Mapped[str] = mapped_column(ForeignKey("person.id"))
    prompt: Mapped[str] = mapped_column(Text)        # 사람에게 보이는 질문
    text: Mapped[str] = mapped_column(Text)          # 확인하면 기록에 남는 말
    hid: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending · confirmed · rejected
    role: Mapped[str] = mapped_column(String, default="")           # taker · owner · receiver
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    t: Mapped[str] = mapped_column(String, default="")


class Ask(Base):
    """규칙 안에서 못 풀 때 PM에게 가는 확인. grants = PM이 고를 수 있는 허락."""
    __tablename__ = "ask"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hid: Mapped[str] = mapped_column(String)
    open: Mapped[bool] = mapped_column(Boolean, default=True)
    why: Mapped[list] = mapped_column(JSON, default=list)
    grants: Mapped[list] = mapped_column(JSON, default=list)
    chosen: Mapped[str | None] = mapped_column(String, nullable=True)
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Resolution(Base):
    __tablename__ = "resolution"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hid: Mapped[str] = mapped_column(String)
    body: Mapped[str] = mapped_column(Text)
    why: Mapped[str] = mapped_column(Text)


class Run(Base):
    """협상 한 건의 진행 상태. 사람이나 PM을 기다리는 동안 여기 멈춰 있다가 이어서 돈다."""
    __tablename__ = "run"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String)       # record · reagree · move
    step: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="running")  # running · waiting_confirm · waiting_pm · done
    auto_confirm: Mapped[bool] = mapped_column(Boolean, default=False)
    ctx: Mapped[dict] = mapped_column(JSON, default=dict)


class Meta(Base):
    __tablename__ = "meta"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)


class Snapshot(Base):
    """되돌리기용. PM이 무언가를 정하기 직전의 전체 상태."""
    __tablename__ = "snapshot"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    data: Mapped[dict] = mapped_column(JSON)


SNAPSHOT_TABLES = [Person, Card, Task, Handoff, HandoffEvent, Record, Rule, Grant, Message,
                   Confirmation, Ask, Resolution, Run, Meta]
