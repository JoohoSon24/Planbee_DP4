"""서버 없이 시연 흐름을 끝까지 돌려 오간 말을 찍어 본다.

  python run_demo.py                                  데모 1, PM 은 첫 선택지를 허락
  python run_demo.py --demo demo2 --pm grant:cut      PM 이 '범위 줄이기'를 허락
  python run_demo.py --demo demo2 --pm reject:defer:deploy --pref learn
  --pm 값: first · grant:<선택지 key 앞부분> · reagree · reject:<key 앞부분> (거절 뒤 남은 첫 선택지를 허락)
"""
import argparse

from app import sim

ap = argparse.ArgumentParser()
ap.add_argument("--demo", default="demo1")
ap.add_argument("--pm", default="first")
ap.add_argument("--pref", default="fast", choices=["fast", "learn", "fair"])
a = ap.parse_args()

s, m = sim.simulate(a.demo, pm=a.pm, pref=a.pref)
names = {p["id"]: p["name"] for p in s["people"]}
for x in s["log"]:
    if x["k"] == "proxy":
        to = f" → {names[x['to']]}" if x["to"] else ""
        extra = " ".join(v for v in [f"[{x['basis']}]" if x["basis"] else "", f"({x['pref']})" if x["pref"] else "",
                                     f'"{x["say"]}"' if x["say"] else ""] if v)
        print(f"{x['t']}  ⬢ {names[x['from']]}{to}  {x['a']}: {' · '.join(f['t'] for f in x['f'])}  {extra}")
    elif x["k"] == "hive":
        print(f"{x['t']}  ⚙ Hive  {x['text']}")
    else:
        print(f"{x['t']}  ○ {names.get(x['who'], 'PM')}  {x['text']}")
print()
for a_ in s["asks"]:
    print(f"PM 확인 ({a_['chosen'] or '열림'}):", *[f"\n   · {w}" for w in a_["why"]], *[f"\n   → {g['label']}  [{g['effect']}]" for g in a_["grants"]])
print()
for hid, h in s["hand"].items():
    print(f"{hid}  {h['state_label']:<10} {h['title']}  {names[h['from_who']]}→{names[h['to_who']]}  약속 {h['t_label']} · 예상 {h['pred_label']}")
print("해결:", *[f"\n  - {r['body']}  ({r['why']})" for r in s["resolved"]])
print("지표:", {k: v for k, v in m.items() if k != "cost"})
print("떠안은 것:", m["cost"], "| 경고:", [w["text"] for w in s["gate"]["warnings"]])
