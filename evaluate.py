"""같은 데모를 여러 조건으로 돌려 지표를 비교한다. 결과는 eval/<데모>_results.csv 와 eval/<데모>_report.md 로 남긴다.

  python evaluate.py                 데모 2
  python evaluate.py --demo demo1

Mock 프록시로 돌리므로 매번 같은 숫자가 나온다. 비교 대상 두 가지(뒤로 밀기 · 중앙 계획)는 LLM 없이 코드로 흉내 낸 것이다.
"""
import argparse
import csv
from pathlib import Path

from app import sim, store

COLS = [("pm_decisions", "PM 결정"), ("pm_talks", "PM이 직접 챙길 사람"), ("confirms", "팀원 확인"), ("proxy_msgs", "프록시 메시지"),
        ("rounds", "라운드"), ("late_end", "끝까지 늦는 약속"), ("promises_moved", "바뀐 약속"), ("past_deadline", "제출일 넘긴 일"),
        ("scope_cut", "줄인 범위"), ("overload", "5일 넘긴 사람"), ("overrides", "카드 무시"), ("cost_people", "떠안은 사람 수"),
        ("top_share", "최대 부담 비중")]

ap = argparse.ArgumentParser()
ap.add_argument("--demo", default="demo2")
a = ap.parse_args()

# PM 이 고를 수 있는 선택지를 먼저 알아낸다 (아무도 안 고른 상태로 한 번 돌려 봄)
s0, _ = sim.simulate(a.demo, pm="reagree")
keys = [g["key"] for ask in s0["asks"] for g in ask["grants"]]
people = [p["id"] for p in s0["people"]]

runs = [("비교: 늦으면 뒤로 민다", dict(mode="push")), ("비교: 중앙 계획 (카드 · 한도 무시)", dict(mode="central"))]
for k in dict.fromkeys(keys):
    runs.append((f"Plan Bee · PM 허락 {k}", dict(pm=f"grant:{k}")))
runs.append(("Plan Bee · PM이 허락 없이 약속을 늦춤", dict(pm="reagree")))
if keys:
    runs.append((f"Plan Bee · PM이 {keys[0]} 거절 후 다음 선택지", dict(pm=f"reject:{keys[0]}")))
runs.append(("Plan Bee · 받을 사람 기준 '배우고 싶은 사람'", dict(pref="learn")))
runs.append(("Plan Bee · 라운드 1회로 제한", dict(rounds=1)))
runs.append(("Plan Bee · 모두 한도 0 (항상 본인에게 물음)", dict(cards={p: {"auto_days": 0} for p in people})))
runs.append(("Plan Bee · 모두 한도 2일 (프록시에게 더 맡김)", dict(cards={p: {"auto_days": 2} for p in people})))

rows = []
for name, kw in runs:
    s, m = sim.simulate(a.demo, **kw)
    cost = " · ".join(f"{who} +{v['늘어남']:g}" + (f" (밀림 {v['밀림']:g})" if v["밀림"] else "") for who, v in m["cost"].items()) or "없음"
    rows.append({"조건": name, **{label: m[key] for key, label in COLS}, "누가 떠안았나": cost,
                 "남은 경고": " · ".join(w["text"] for w in s["gate"]["warnings"]) or "없음"})

out = Path(__file__).resolve().parent / "eval"
out.mkdir(exist_ok=True)
with open(out / f"{a.demo}_results.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)

head = ["조건"] + [label for _, label in COLS]
md = [f"# {s0['demo']['title']} · 조건별 비교", "",
      "Mock 프록시로 돌린 결과라 매번 같은 숫자가 나온다. '비교' 두 줄은 LLM 없이 코드로 흉내 낸 방식이다.", "",
      "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
md += ["| " + " | ".join(str(r[h]) for h in head) + " |" for r in rows]
md += ["", "## 누가 떠안았나", "", "| 조건 | 사람별 늘어난 일수 (밀림 = 2주차로 넘어간 일수) | 남은 경고 |", "|---|---|---|"]
md += [f"| {r['조건']} | {r['누가 떠안았나']} | {r['남은 경고']} |" for r in rows]
md += ["", "## 지표 읽는 법", "",
       "- **PM 결정**: PM이 허락 · 거절 · 약속 늦추기를 누른 횟수.",
       "- **PM이 직접 챙길 사람**: 비교 방식에서, 바뀐 계획을 PM이 알리고 동의를 받아야 하는 사람 수. Plan Bee 에서는 프록시가 대신하므로 0.",
       "- **팀원 확인**: 사람이 직접 누른 확인 수. 위임 카드 한도 안이면 프록시가 대신한다.",
       "- **끝까지 늦는 약속 · 제출일 넘긴 일 · 5일 넘긴 사람**: 계획이 실제 일정에 맞는지. 0 이 좋다.",
       "- **카드 무시**: 본인이 프록시에게 맡기지 않은 범위를 누가 대신 정한 횟수.",
       "- **최대 부담 비중**: 늘어나거나 밀린 일수 중 한 사람이 떠안은 가장 큰 몫. 1 에 가까우면 한 사람에게 몰린 것."]
(out / f"{a.demo}_report.md").write_text("\n".join(md) + "\n", encoding="utf-8")

w0 = max(len(r["조건"]) for r in rows)
print(f"{'조건':<{w0}}  " + "  ".join(label for _, label in COLS))
for r in rows:
    print(f"{r['조건']:<{w0}}  " + "  ".join(f"{str(r[label]):>{len(label)}}" for _, label in COLS))
print(f"\n→ {out / (a.demo + '_report.md')}\n→ {out / (a.demo + '_results.csv')}")
