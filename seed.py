"""DB를 비우고 seed/team.yaml 로 다시 채운다.   python seed.py"""
from app import store

engine = store.make_engine()
with store.make_session_factory(engine)() as db:
    store.reset(db)
    db.commit()
    s = store.state_json(db)
    print(f"사람 {len(s['people'])} · 일 {len(s['tasks'])} · Handoff {len(s['hand'])} · 기록 {len(s['recs'])} · 규칙 {len(s['rules'])}")
