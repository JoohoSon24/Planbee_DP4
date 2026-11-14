"""서버 없이 시연 흐름을 끝까지 돌려 오간 말을 찍어 본다.   python run_demo.py [defer|cut] [fast|learn]"""
import sys

from sqlalchemy import select

from app import store, workflow
from app.models import Ask, Rule

grant_kind = sys.argv[1] if len(sys.argv) > 1 else "defer"
pref = sys.argv[2] if len(sys.argv) > 2 else "fast"
engine = store.make_engine("sqlite://")
with store.make_session_factory(engine)() as db:
    store.reset(db)
    db.get(Rule, "pref").value = {"choice": pref}
    feed = store.load_yaml("feed.yaml")
    for phase in ("mon", "wed"):
        f = feed[phase]
        store.set_meta(db, "now", f["now"])
        workflow.start_records(db, f["records"], auto_confirm=True, phase_after=f["next_phase"])
    ask = db.scalars(select(Ask).where(Ask.open.is_(True))).first()
    if ask:
        key = next(g["key"] for g in ask.grants if g["key"].startswith(grant_kind))
        workflow.grant(db, ask.id, key)
    s = store.state_json(db)
    names = {p["id"]: p["name"] for p in s["people"]}
    for m in s["log"]:
        if m["k"] == "proxy":
            to = f" → {names[m['to']]}" if m["to"] else ""
            extra = " ".join(x for x in [f"[{m['basis']}]" if m["basis"] else "", f"({m['pref']})" if m["pref"] else "",
                                         f'"{m["say"]}"' if m["say"] else ""] if x)
            print(f"{m['t']}  ⬢ {names[m['from']]}{to}  {m['a']}: {' · '.join(f['t'] for f in m['f'])}  {extra}")
        elif m["k"] == "hive":
            print(f"{m['t']}  ⚙ Hive  {m['text']}")
        else:
            print(f"{m['t']}  ○ {names.get(m['who'], 'PM')}  {m['text']}")
    print()
    for hid, h in s["hand"].items():
        print(f"{hid}  {h['state_label']:<10} {h['title']:<8} {names[h['from_who']]}→{names[h['to_who']]}  약속 {h['t_label']} · 예상 {h['pred_label']}")
    print("해결:", *[f"\n  - {r['body']}  ({r['why']})" for r in s["resolved"]])
    print("집계:", s["stats"], "| 경고:", [w["text"] for w in s["gate"]["warnings"]])
