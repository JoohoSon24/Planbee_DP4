"""Rule-based card proxy: the offline (Mock) stand-in for an LLM proxy in discussion mode.

It reads only what an LLM proxy reads (its own card and profile, the public board, the
shortlisted plans and the public discussion) and applies fixed rules, so it is also the
'card rules, no LLM' condition of the ablation. Every rule is listed here; nothing is random.

1. A question addressed to me that I have not answered -> ANSWER it.
2. I already spoke this discussion -> PASS.
3. My profile states a condition naming a task I own, and a plan restructures it -> CONDITION.
4. Work I own is handed to someone else and I have a wish about it -> QUESTION to the receiver.
5. Plans differ in what they cost me (new work, a cared-about task pushed later or deferred,
   new work in a slot I want to keep) -> REJECT the costliest, giving the cause.
6. Otherwise PREFER the cheapest for me (ties keep Hive's rule order).
"""
import re
from .models import Speech

IDS = re.compile(r'(?<![A-Za-z0-9])([A-Z][0-9])(?![0-9])')
SLOTS = {'목요일 오후': (3.5, 4.0), '금요일 오후': (4.5, 5.0), '수요일 오후': (2.5, 3.0)}


def _cost(c, me, profile, planned):
    text = ' '.join(str(profile.get(k, '')) for k in ('wish', 'avoid', 'condition'))
    cared = set(IDS.findall(text))
    new_days = sum(x['days'] for x in c['my_new_work'])
    reasons, cost = [], 2 * new_days
    if new_days:
        reasons.append(('new', new_days))
    deferred = {d['id'] for d in c.get('deferred', [])}
    for t in c['my_schedule']:
        tid = t['id']
        if tid in cared and tid in planned and t['start'] > planned[tid] + 1e-9:
            late = t['start'] - planned[tid]
            cost += 3 * late; reasons.append(('late', tid, late))
    for tid in cared & deferred:
        cost += 5; reasons.append(('deferred', tid))
    avoided = set(IDS.findall(str(profile.get('avoid', ''))))
    for a in c.get('plan_actions', []):
        if a.get('kind') == 'restructure' and a['task'] in avoided:
            cost += 3; reasons.append(('restructure', a['task']))
    avoid = str(profile.get('avoid', ''))
    for label, (a, z) in SLOTS.items():
        if label in avoid and any(t['id'] not in planned and a - 1e-9 <= t['start'] < z for t in c['my_schedule']):
            cost += 2; reasons.append(('slot', label))
    return cost, reasons


def _why(reasons, en):
    out = []
    for r in reasons:
        if r[0] == 'new':
            out.append(f'new work of {r[1]:g} days for me' if en else f'제게 새 업무 {r[1]:g}일이 생김')
        elif r[0] == 'late':
            out.append(f'{r[1]} moves {r[2]:g} days later' if en else f'{r[1]}이(가) {r[2]:g}일 늦어짐')
        elif r[0] == 'deferred':
            out.append(f'{r[1]} leaves this demo' if en else f'{r[1]}이(가) 이번 데모에서 빠짐')
        elif r[0] == 'restructure':
            out.append(f'{r[1]} is reshaped in a way I wanted to avoid' if en else f'피하고 싶던 방식으로 {r[1]}이(가) 바뀜')
        elif r[0] == 'slot':
            out.append(f'I lose {r[1]} I wanted to keep' if en else f'지키고 싶은 {r[1]} 시간이 없어짐')
    return ', '.join(out)


def speech(facts):
    me = facts['self']['id']; en = facts.get('language') == 'en'
    L = lambda ko, e: e if en else ko
    items = facts['candidates']; history = facts.get('public_history') or []
    said = [e for e in history if e.get('phase') == 'fairness_discussion']
    profile = facts.get('my_profile') or {}
    planned = {k: v['s0'] for k, v in (facts.get('public_board') or {}).get('tasks', {}).items()}
    last = next((e['index'] for e in reversed(said) if e.get('requester') not in ('hive', 'pm', me)), None)
    # 1. answer a question put to me
    asked = [e for e in said if e.get('recipient') == me and e.get('response') == 'QUESTION']
    answered = {e.get('reply_to') for e in said if e.get('requester') == me}
    for q in asked:
        if q['index'] not in answered:
            return Speech(candidate_id=q['candidate_id'], action='ANSWER', recipient=q['requester'], reply_to=q['index'],
                          basis=['card', 'plan:' + q['candidate_id']],
                          message=L('네, 맡게 되면 결과를 정리해서 바로 공유할게요.', 'Yes. If I take it, I will share the results right away.'))
    # 2. one position per discussion
    if any(e.get('requester') == me for e in said):
        return Speech(candidate_id=items[0]['id'], action='PASS', message=L('새로 더할 쟁점은 없어요.', 'Nothing new to add.'), basis=['card'], reply_to=last)
    # 3. a stated condition on a task of mine that a plan restructures
    mine = {t['id'] for t in (facts.get('public_board') or {}).get('tasks', {}).values() if t.get('who') == me}
    if profile.get('condition'):
        named = set(IDS.findall(str(profile['condition'])))
        for c in items:
            hit = [a['task'] for a in c.get('plan_actions', []) if a.get('kind') == 'restructure' and a['task'] in mine and a['task'] in named]
            if hit:
                return Speech(candidate_id=c['id'], action='CONDITION', condition=profile['condition'], requires_new_candidate=False,
                              basis=['card', 'task:' + hit[0], 'plan:' + c['id']], reply_to=last,
                              message=L(f"{hit[0]}을(를) 나눠서 하는 건 가능해요. 다만 {profile['condition']}.",
                                        f"I can split {hit[0]}, on one condition: {profile['condition']}."))
    # 4. my work goes to someone else and I care how it is done
    source = facts.get('source')
    if source == me and profile.get('wish'):
        first = items[0]
        takers = sorted({a['who'] for a in first['allocations'] if a['who'] != me})
        if takers:
            return Speech(candidate_id=first['id'], action='QUESTION', recipient=takers[0], basis=['card', 'plan:' + first['id']], reply_to=last,
                          message=L('이 안이면 넘겨받은 작업 결과를 제 남은 작업 전에 공유해 줄 수 있나요? 직접 검토하고 싶어요.',
                                    'With this plan, can you share the results of the work you take before my remaining part? I want to review them myself.'))
    # 5./6. compare what each plan costs me
    costs = [(_cost(c, me, profile, planned), i) for i, c in enumerate(items)]
    best_i = min(costs, key=lambda x: (x[0][0], x[1]))[1]
    worst_i = max(costs, key=lambda x: (x[0][0], -x[1]))[1]
    (wc, wr), (bc, _) = costs[worst_i][0], costs[best_i][0]
    if wc > bc and wc > 0:
        c = items[worst_i]
        return Speech(candidate_id=c['id'], action='REJECT', basis=['card', 'plan:' + c['id']], reply_to=last,
                      message=L(f'이 안에는 반대해요. {_why(wr, en)}.', f'I object to this plan: {_why(wr, en)}.'))
    c = items[best_i]
    return Speech(candidate_id=c['id'], action='PREFER', basis=['card', 'plan:' + c['id']], reply_to=last,
                  message=L('이 안을 선호해요. 제 일정과 바람이 가장 덜 바뀌어요.', 'I prefer this plan: it changes my schedule and wishes the least.'))


def rule_speech(facts):
    """Card rules for the rule-relaxation discussion (scenario ③ type). Same rule list as above,
    applied to what each relaxation would change for me."""
    me = facts['self']['id']; en = facts.get('language') == 'en'
    L = lambda ko, e: e if en else ko
    profile = facts.get('my_profile') or {}
    rules = [r for r in facts['rules'] if r['feasible'] > 0] or facts['rules']
    history = facts.get('public_history') or []
    said = [e for e in history if e.get('phase') == 'rule_discussion']
    last = next((e['index'] for e in reversed(said) if e.get('requester') not in ('hive', 'pm', me)), None)
    if any(e.get('requester') == me for e in said):
        return Speech(candidate_id=rules[0]['id'], action='PASS', message=L('새로 더할 쟁점은 없어요.', 'Nothing new to add.'), basis=['card'], reply_to=last)
    def cost(r):
        return rule_cost(facts, r)
    scored = [(cost(r), i) for i, r in enumerate(rules)]
    best = min(scored, key=lambda x: (x[0][0], x[1])); worst = max(scored, key=lambda x: (x[0][0], -x[1]))
    if worst[0][0] > best[0][0] and worst[0][0] >= 2:
        r = rules[worst[1]]
        return Speech(candidate_id=r['id'], action='REJECT', basis=['card'], reply_to=last,
                      message=L(f"{r['id']}에는 반대해요. " + ', '.join(worst[0][1]) + '.', f"I object to {r['id']}: " + ', '.join(worst[0][1]) + '.'))
    r = rules[best[1]]
    return Speech(candidate_id=r['id'], action='PREFER', basis=['card'], reply_to=last,
                  message=L(f"{r['id']}을(를) 선호해요. 제 일정과 바람이 가장 덜 바뀌어요.", f"I prefer {r['id']}: it changes my schedule and wishes the least."))


def rule_cost(facts, r):
    """What relaxing rule r costs this person, from their own profile (score, reasons)."""
    me = facts['self']['id']; en = facts.get('language') == 'en'
    L = lambda ko, e: e if en else ko
    profile = facts.get('my_profile') or {}
    text = ' '.join(str(profile.get(k, '')) for k in ('wish', 'avoid', 'condition'))
    cared = set(IDS.findall(text))
    if True:
        c, why = 0, []
        p = r.get('patch') or {}
        if me in (p.get('people') or {}):
            c += 3; why.append(L('제 가용 시간을 바꿔야 함', 'I would have to change my own availability'))
        for tid, ch in (p.get('tasks') or {}).items():
            if tid in facts.get('my_tasks', []):
                if ch.get('cut') and tid in cared:
                    c += 5; why.append(L(f'{tid}이(가) 이번 데모에서 빠짐', f'{tid} leaves this demo'))
                elif ch.get('context', {}).get('splittable_hint'):
                    c += 1; why.append(L(f'{tid}을(를) 나눠서 다시 이어 해야 함', f'I would split and resume {tid}'))
        for hid, ch in (p.get('handoffs') or {}).items():
            if facts.get('handoff_targets', {}).get(hid) in cared:
                c += 1; why.append(L(f'{facts["handoff_targets"][hid]}의 시작이 늦어짐', f'{facts["handoff_targets"][hid]} starts later'))
        return c, why


def plan_cost(item, me, profile, planned, en=False):
    """What a plan costs this person, as data a Live proxy can speak from (score, reasons in words)."""
    c, reasons = _cost(item, me, profile, planned)
    return dict(score=c, reasons=_why(reasons, en) or ('no change for me' if en else '나에게 바뀌는 것 없음'))
