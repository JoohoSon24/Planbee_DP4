"""Run the three game-team scenarios end to end and score them against expected.yaml.

No human raters: every check is a rule written in seed/<scenario>/expected.yaml before the run.
Behaviour data (who said what, with which basis, answering whom) is collected for each run.

Usage (from the project folder):
  python3 scripts/run_game_scenarios.py                 # Live LLM, 3 scenarios, 1 repeat each
  python3 scripts/run_game_scenarios.py --llm mock      # offline smoke test
  python3 scripts/run_game_scenarios.py --repeat 3 --scenario m4_g1_qa_absence
Results: eval/game_scenarios/<time>_<llm>/summary.json and report.md
"""
from pathlib import Path
from datetime import datetime
from collections import Counter
import argparse
import json
import os
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
p = argparse.ArgumentParser()
p.add_argument('--llm', choices=['live', 'mock'], default='live')
p.add_argument('--scenario', action='append')
p.add_argument('--repeat', type=int, default=1)
p.add_argument('--max-calls', type=int, default=120)
p.add_argument('--rounds', type=int, default=4)
p.add_argument('--shortlist', type=int, default=6)
p.add_argument('--language', choices=['ko', 'en'], default='ko')
p.add_argument('--no-discussion', action='store_true', help='ablation: Hive rule order only, no proxy discussion')
a = p.parse_args()
os.environ['PLANBEE_LLM'] = a.llm
os.environ.setdefault('PLANBEE_RUNS_DIR', str(ROOT / 'runs' / 'v2'))
os.environ['PLANBEE_RUN_ORIGIN'] = 'game_scenarios'
os.environ['PLANBEE_AUTO_CONFIRM'] = '0'

import yaml  # noqa: E402
from app import store, llm  # noqa: E402
from app.candidates import engine  # noqa: E402

DISCUSSION_ACTS = ('QUESTION', 'ANSWER', 'PREFER', 'REJECT', 'CONDITION', 'PASS')


def settings():
    return engine.Settings(max_calls=a.max_calls, max_rounds=a.rounds, shortlist_limit=a.shortlist,
                           candidate_limit=40, raw_limit=1500, max_seconds=1800, skip_discussion=a.no_discussion)


def planned_starts(sid):
    team = yaml.safe_load((ROOT / 'seed' / sid / 'team.yaml').read_text(encoding='utf-8'))
    return {t['id']: t['s0'] for t in team['tasks']}


def options(run):
    return [c for c in run.ctx.get('candidates', []) if c['id'] in (run.ctx.get('final_candidates') or [])]


def checks(sid, run, first_stop, expected):
    out = []
    def add(name, ok, detail=''):
        out.append(dict(check=name, ok=bool(ok), detail=detail))
    imp = run.ctx.get('impact') or {}
    e = expected.get('impact', {})
    if e:
        add('impact.broken', set(e.get('broken_any', [])) <= set(imp.get('broken', [])), imp.get('broken'))
        add('impact.owner', imp.get('owner') == e.get('owner'), imp.get('owner'))
        add('impact.involved', set(e.get('involved_any', [])) <= set(imp.get('involved', [])) | set(imp.get('may_help', [])),
            dict(involved=imp.get('involved'), may_help=imp.get('may_help')))
        add('impact.not_involved', set(e.get('not_involved', [])) <= set(imp.get('not_involved', [])), imp.get('not_involved'))
    fp = expected.get('first_pass')
    if fp:
        add('first_pass.termination', first_stop.get('termination') == fp['termination'], first_stop.get('termination'))
        found = {o['id']: o['feasible'] for o in first_stop.get('relaxation_options') or []}
        for rid, rule in fp.get('feasible', {}).items():
            n = found.get(rid)
            add(f'first_pass.feasible.{rid}', n is not None and ((n > 0) if rule == '>0' else (n == int(rule))), n)
    opts = options(run)
    pm = expected.get('pm', {})
    add('pm.options', pm.get('options_min', 1) <= len(opts) <= pm.get('options_max', 3), len(opts))
    cand = expected.get('candidates', {})
    starts = planned_starts(sid)
    if 'families_any' in cand:
        owner = imp.get('owner')
        fams = {tuple(sorted({x['who'] for x in c['allocations']} - {owner})) for c in opts}
        add('candidates.families', all(tuple(f) in fams for f in cand['families_any']), sorted(fams))
    for tid, parts in (cand.get('keep_parts') or {}).items():
        ok = all(all(x['who'] == who for x in c['allocations'] if x.get('key') == key) for c in opts for key, who in parts.items())
        add(f'candidates.keep_parts.{tid}', ok and opts, parts)
    if 'all_restructure' in cand:
        add('candidates.restructure', opts and all(any(x['kind'] == 'restructure' and x['task'] == cand['all_restructure'] for x in c.get('plan_actions', [])) for c in opts))
    if 'restructure_any' in cand:
        for tid in cand['restructure_any']:
            add(f'candidates.restructure_any.{tid}', any(any(x['kind'] == 'restructure' and x['task'] == tid for x in c.get('plan_actions', [])) for c in opts))
    if 'all_split' in cand:
        add('candidates.split', opts and all(len(c['allocations']) >= 2 for c in opts))
    for tid in cand.get('unchanged', []):
        ok = all(abs(next(t['start'] for t in c['board']['tasks'] if t['id'] == tid) - starts[tid]) < 1e-9 for c in opts)
        add(f'candidates.unchanged.{tid}', ok and opts)
    part = expected.get('participants', {})
    who = set(run.ctx.get('participants') or [])
    if part:
        add('participants.include', set(part.get('include', [])) <= who, sorted(who))
        add('participants.exclude', not (set(part.get('exclude', [])) & who), sorted(who))
    beh = expected.get('behaviour', {})
    acts = behaviour(run)['acts']
    if 'non_prefer_acts_min' in beh:
        n = sum(acts.get(k, 0) for k in ('QUESTION', 'ANSWER', 'REJECT', 'CONDITION'))
        add('behaviour.disagreement_or_questions', n >= beh['non_prefer_acts_min'], n)
    if 'constraint_reviews_min' in beh:
        n = sum(1 for e in run.ctx.get('public_history', []) if e['response'] == 'CONSTRAINT_REVIEW')
        add('behaviour.constraint_reviews', n >= beh['constraint_reviews_min'], n)
    return out


def behaviour(run):
    said = [e for e in run.ctx.get('public_history', []) if e.get('phase') in ('fairness_discussion', 'rule_discussion') and e['requester'] not in ('hive', 'pm')]
    acts = Counter(e['response'] for e in said)
    by = {}
    for e in said:
        by.setdefault(e['requester'], Counter())[e['response']] += 1
    spoken = [e for e in said if e['response'] != 'PASS']
    return dict(acts=dict(acts), by_person={k: dict(v) for k, v in by.items()},
                messages=len(said), with_basis=sum(1 for e in spoken if e.get('basis')),
                with_reply_to=sum(1 for e in spoken if e.get('reply_to') is not None),
                spoken=len(spoken),
                invites=sum(1 for e in run.ctx.get('public_history', []) if e['response'] == 'INVITE'),
                supplements=sum(1 for e in run.ctx.get('public_history', []) if e['response'] == 'SUPPLEMENT'),
                rounds=run.ctx.get('round', 0))


SPEAK = ('fairness_discussion',)
VOICE = ('REJECT', 'CONDITION')


def fidelity(db, run):
    """Do the proxies speak for their person?  Ground truth is computed by code from each profile:
    what a plan costs that person (new work, a cared-about task late or deferred, an avoided reshape
    or slot).  The same rule drives the Mock proxy, so for Mock this is an upper bound; for Live it
    measures whether the model stays faithful to the profile."""
    from app.candidates import card_proxy
    short = [c for c in run.ctx.get('candidates', []) if c['id'] in (run.ctx.get('shortlist') or [])]
    if len(short) < 1:
        return None
    people = run.ctx.get('participants') or []
    cost, harm = {}, {}
    for pid in people:
        facts = engine.participant_facts(db, run, pid, short)
        planned = {k: v['s0'] for k, v in (facts.get('public_board') or {}).get('tasks', {}).items()}
        for item in facts['candidates']:
            c, why = card_proxy._cost(item, pid, facts.get('my_profile') or {}, planned)
            cost[(pid, item['id'])] = c; harm[(pid, item['id'])] = why
    said = [e for e in run.ctx.get('public_history', []) if e.get('phase') in SPEAK and e['requester'] in people and e.get('candidate_id')]
    voiced = [e for e in said if e['response'] in VOICE]
    prefer = [e for e in said if e['response'] == 'PREFER']
    precision = [cost.get((e['requester'], e['candidate_id']), 0) > 0 for e in voiced]
    pref_ok = []
    for e in prefer:
        mine = [cost[(e['requester'], c['id'])] for c in short if (e['requester'], c['id']) in cost]
        pref_ok.append(bool(mine) and cost.get((e['requester'], e['candidate_id'])) == min(mine))
    # a plan clearly hurts someone when it costs them more than their best option
    hurt = [(pid, c['id']) for pid in people for c in short if (pid, c['id']) in cost and cost[(pid, c['id'])] > 0
            and cost[(pid, c['id'])] > min(cost.get((pid, x['id']), 0) for x in short)]
    heard = []
    for pid, cid in hurt:
        mine = {x['id']: cost[(pid, x['id'])] for x in short if (pid, x['id']) in cost}
        heard.append(any(e['requester'] == pid and ((e['candidate_id'] == cid and e['response'] in VOICE) or
                         (e['response'] == 'PREFER' and mine.get(e['candidate_id'], 1e9) < mine[cid])) for e in said))
    ratio = lambda xs: None if not xs else round(sum(xs) / len(xs), 2)
    return dict(objection_precision=ratio(precision), objections=len(precision),
                harm_recall=ratio(heard), harmed_pairs=len(heard),
                preference_consistency=ratio(pref_ok), preferences=len(pref_ok),
                missed=[f'{p}:{c[:8]}' for (p, c), ok in zip(hurt, heard) if not ok])


def evidence(db, run):
    """Is each cited basis real and relevant to the speaker or the plan they talk about?"""
    b = store.board(db)
    short = {c['id']: c for c in run.ctx.get('candidates', []) if c['id'] in (run.ctx.get('shortlist') or [])}
    hist = run.ctx.get('public_history', [])
    ok = bad = 0; bad_refs = []
    for i, e in enumerate(hist):
        if e.get('phase') not in SPEAK + ('rule_discussion',) or not e.get('basis'):
            continue
        c = short.get(e.get('candidate_id')) or {}
        touched = {x.get('task') for x in c.get('schedule_changes', []) + c.get('plan_actions', [])} | {run.ctx.get('task')}
        touched |= {t['id'] for t in (c.get('board') or {}).get('tasks', []) if t.get('who') == e['requester']}
        for ref in e['basis']:
            k, _, v = ref.partition(':')
            good = (k == 'card' or
                    (k == 'task' and v in b.tasks and (b.tasks[v].who == e['requester'] or v in touched or (b.tasks[v].context or {}).get('partition_of') in touched)) or
                    (k == 'handoff' and v in b.hands and ({b.hands[v].from_task, b.hands[v].to_task} & touched)) or
                    (k == 'plan' and v in short) or
                    (k == 'history' and v.isdigit() and int(v) < i and hist[int(v)].get('requester') not in ('hive',)))
            ok += good; bad += not good
            if not good:
                bad_refs.append(f"{e['requester']}:{ref}")
    return dict(valid=ok, invalid=bad, rate=None if ok + bad == 0 else round(ok / (ok + bad), 2), invalid_refs=bad_refs[:10])


def live_stats(run):
    h = run.ctx.get('public_history', [])
    turns = sum(1 for e in h if e.get('phase') in SPEAK and e['requester'] not in ('hive', 'pm'))
    skipped = sum(1 for e in h if e['response'] in ('COPY_SKIPPED', 'REPEAT_SKIPPED'))
    asked = sum(1 for e in h if e.get('phase') in SPEAK and e['response'] == 'QUESTION' and e.get('recipient'))
    return dict(rounds=run.ctx.get('round', 0), echo_rate=None if turns + skipped == 0 else round(skipped / (turns + skipped), 2),
                questions=asked, open_questions=len(engine.open_questions(run)),
                failed=run.status != 'awaiting_pm_selection' and run.ctx.get('termination') not in ('needs_rule_relaxation',))


def drive(db, run):
    for _ in range(200):
        if run.status != 'running':
            break
        engine.advance(db, run)


def run_one(sid, i):
    store.use_demo(sid); llm.set_llm(None)
    expected = yaml.safe_load((ROOT / 'seed' / sid / 'expected.yaml').read_text(encoding='utf-8'))
    feed = yaml.safe_load((ROOT / 'seed' / sid / 'feed.yaml').read_text(encoding='utf-8'))['issue']
    dbengine = store.make_engine('sqlite://'); started = time.monotonic()
    with store.make_session_factory(dbengine)() as db:
        store.reset(db)
        if a.llm == 'live':
            store.set_meta(db, 'llm_mode', 'live')   # the data scenarios pin Mock for the UI; a live test overrides
        rec = feed['records'][0]
        text = rec['text']
        if a.language == 'en':
            text = store.display_glossary().get(text, text)
        run = engine.start(db, feed['task'], text, settings(), reporter='pm', language=a.language)
        drive(db, run)
        first_stop = dict(status=run.status, termination=run.ctx.get('termination'),
                          relaxation_options=run.ctx.get('relaxation_options'))
        if run.ctx.get('termination') == 'needs_rule_relaxation' and expected.get('grant'):
            engine.grant_rule(db, run, expected['grant'], '자동 시험: 정답지에 적힌 규칙을 허락')
            drive(db, run)
        db.commit()
        cands = run.ctx.get('candidates', [])
        result = dict(scenario=sid, repeat=i, llm=a.llm, language=a.language, condition='rule_only' if a.no_discussion else ('card_rules' if a.llm == 'mock' else 'llm'),
                      pool=len(cands), dominated=sum(1 for c in cands if (c.get('metrics') or {}).get('dominated_by')),
                      final_ids=list(run.ctx.get('final_candidates') or []), status=run.status, termination=run.ctx.get('termination'),
                      model_error=run.ctx.get('model_error'), llm_calls=run.ctx['llm_budget']['used'],
                      seconds=round(time.monotonic() - started, 1), generation=run.ctx.get('generation'),
                      impact=run.ctx.get('impact'), first_stop=first_stop, granted_rules=run.ctx.get('granted_rules'),
                      participants=run.ctx.get('participants'), shortlist=len(run.ctx.get('shortlist') or []),
                      behaviour=behaviour(run), fidelity=fidelity(db, run), evidence=evidence(db, run), live=live_stats(run),
                      pattern=sorted({(e['requester'], next((c.get('letter') or '?' for c in cands if c['id'] == e.get('candidate_id')), '?'), e['response'])
                                      for e in run.ctx.get('public_history', []) if e.get('phase') in SPEAK and e['requester'] not in ('hive', 'pm')}),
                      families=sorted({tuple(sorted({x['who'] for x in c['allocations']})) for c in options(run)}),
                      options=[dict(id=c['id'], title=c['title'],
                                    work=[(x['who'], x['what']) for x in c['allocations']],
                                    changes=c.get('schedule_changes'), actions=[x['kind'] + ':' + x['task'] for x in c.get('plan_actions', [])],
                                    metrics=c.get('metrics'), tally=c.get('discussion_tally')) for c in options(run)],
                      checks=checks(sid, run, first_stop, expected),
                      history=[{k: v for k, v in e.items() if k != 'llm_budget'} for e in run.ctx.get('public_history', [])],
                      transcript_file=run.ctx.get('transcript_file'))
    dbengine.dispose()
    return result


def report(results, out):
    lines = ['# Game scenario runs', '', f"LLM: {a.llm} · {datetime.now().astimezone():%Y-%m-%d %H:%M}", '',
             '| 시나리오 | # | 상태 | 호출 | 초 | 계획 | 발언 | 질문 | 반대 | 조건 | 선호 | 근거 표시 | 답장 표시 | 초대 | 보충 | 체크 |',
             '|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    for r in results:
        if 'error' in r:
            lines.append(f"| {r['scenario']} | {r['repeat']} | 오류 | | | | | | | | | | | | | {r['error'][:60]} |"); continue
        b = r['behaviour']; ac = b['acts']; passed = sum(c['ok'] for c in r['checks'])
        lines.append(f"| {r['scenario']} | {r['repeat']} | {r['status']} {r['termination'] or ''} | {r['llm_calls']} | {r['seconds']} | "
                     f"{(r['generation'] or {}).get('feasible', '')} | {b['spoken']} | {ac.get('QUESTION', 0)} | {ac.get('REJECT', 0)} | "
                     f"{ac.get('CONDITION', 0)} | {ac.get('PREFER', 0)} | {b['with_basis']}/{b['spoken']} | {b['with_reply_to']}/{b['spoken']} | "
                     f"{b['invites']} | {b['supplements']} | {passed}/{len(r['checks'])} |")
    lines += ['', '## 프록시 충실도 · 근거 타당성 · 실행 지표', '',
              '| 시나리오 | # | 반대 정밀도 | 손해 재현율 | 선호 일관성 | 근거 타당 | 라운드 | 되풀이율 | 미답 질문 | 실패 | 놓친 손해 |', '|---|---|---|---|---|---|---|---|---|---|---|']
    for r in results:
        if 'error' in r:
            continue
        f = r.get('fidelity') or {}; ev = r.get('evidence') or {}; lv = r.get('live') or {}
        lines.append(f"| {r['scenario']} | {r['repeat']} | {f.get('objection_precision')} ({f.get('objections')}) | {f.get('harm_recall')} ({f.get('harmed_pairs')}) | "
                     f"{f.get('preference_consistency')} ({f.get('preferences')}) | {ev.get('rate')} ({ev.get('valid')}/{ev.get('valid', 0) + ev.get('invalid', 0)}) | "
                     f"{lv.get('rounds')} | {lv.get('echo_rate')} | {lv.get('open_questions')} | {lv.get('failed')} | {', '.join(f.get('missed') or [])} |")
    by = {}
    for r in results:
        if 'error' not in r:
            by.setdefault(r['scenario'], []).append(r)
    if any(len(v) > 1 for v in by.values()):
        lines += ['', '## 반복 안정성', '', '| 시나리오 | 반복 | 실패 | PM 후보 배분이 같은 비율 | 발언 패턴 유사도(자카드 평균) | 호출 중앙값 | 초 중앙값 |', '|---|---|---|---|---|---|---|']
        for sid, rs in by.items():
            fam = [tuple(map(tuple, x['families'])) for x in rs]
            same = max(fam.count(f) for f in fam) / len(fam)
            pats = [set(map(tuple, x['pattern'])) for x in rs]
            jac = [len(p & q) / len(p | q) for i, p in enumerate(pats) for q in pats[i + 1:] if p | q]
            med = lambda xs: sorted(xs)[len(xs) // 2]
            lines.append(f"| {sid} | {len(rs)} | {sum(1 for x in rs if x['live']['failed'])} | {same:.2f} | {(sum(jac) / len(jac)) if jac else 1:.2f} | "
                         f"{med([x['llm_calls'] for x in rs])} | {med([x['seconds'] for x in rs])} |")
    for r in results:
        if 'error' in r:
            continue
        lines += ['', f"## {r['scenario']} #{r['repeat']}", '', '실패한 체크: ' + (', '.join(c['check'] for c in r['checks'] if not c['ok']) or '없음'), '']
        for i, e in enumerate(r['history']):
            extra = (f" · 근거 {', '.join(e['basis'])}" if e.get('basis') else '') + (f" · ↩{e['reply_to']}" if e.get('reply_to') is not None else '')
            to = f" → {e['recipient']}" if e.get('recipient') else ''
            lines.append(f"{i}. **{e['requester']}**{to} `{e['response']}` {e['reason']}{extra}")
        lines.append('')
        for j, o in enumerate(r['options'], 1):
            t = o.get('tally') or {}
            lines.append(f"- 후보 {j}: {o['title']} · {o['work']} · {o['changes']} {o['actions']} · 선호 {t.get('prefer')} 반대 {t.get('reject')} {t.get('objections') or ''} 조건 {t.get('condition')}")
    (out / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


stamp = datetime.now().astimezone().strftime('%Y-%m-%d_%H-%M-%S')
out = ROOT / 'eval' / 'game_scenarios' / (f'{stamp}_{a.llm}_{a.language}' + ('_nodiscussion' if a.no_discussion else '')); out.mkdir(parents=True, exist_ok=True)
results = []
TEST_SET = ['m4_g1_qa_absence', 'm4_g2_art_slip', 'm4_g3_deploy_slot']   # not in the demo list; the evaluation set
for sid in a.scenario or TEST_SET:
    for i in range(1, a.repeat + 1):
        print('START', sid, i, flush=True)
        try:
            r = run_one(sid, i)
        except Exception as exc:  # keep the other runs; record the failure
            r = dict(scenario=sid, repeat=i, error=f'{type(exc).__name__}: {exc}', trace=traceback.format_exc())
        results.append(r)
        (out / 'summary.json').write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        report(results, out)
        if 'error' in r:
            print('ERROR', r['error'], flush=True)
        else:
            print('RESULT', r['status'], r['termination'], 'calls', r['llm_calls'], 'acts', r['behaviour']['acts'],
                  'checks', f"{sum(c['ok'] for c in r['checks'])}/{len(r['checks'])}", flush=True)
print('OUTPUT', out, flush=True)
