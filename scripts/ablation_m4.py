"""Ablation on the five M4 scenarios: simple algorithm / no discussion / full Plan Bee.

Conditions (same seed, same oracle scripts/check_m4_results.py):
  algorithm      No LLM. The new duration is given as a structured fact (Mock re-estimate) because a
                 pure algorithm cannot read the issue text - an advantage to this baseline. Only the
                 code-built structures are searched (no generation AI), and the Hive-valid plan with
                 the lowest load variance is applied automatically.
  no_discussion  Live re-estimate + Live generation AI + Hive. No assessment, discussion, ranking or
                 consent: the three lowest-variance valid plans go to the PM.
  full           The whole Live pipeline (generation, card-based discussion, consent, PM options).

For every plan an approach applies or recommends, a code audit reports affected people whose card
authority is exceeded (needs a personal confirmation) and new work with a tag the card refuses.
Usage: .venv/bin/python scripts/ablation_m4.py [--condition algorithm ...] [--scenario m4_t1_...]
"""
from pathlib import Path
from datetime import datetime
from types import SimpleNamespace as NS
import argparse
import json
import os
import sys
import time

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
p = argparse.ArgumentParser()
p.add_argument('--condition', action='append', choices=['algorithm', 'no_discussion', 'full'])
p.add_argument('--scenario', action='append')
p.add_argument('--seed', type=int, default=17)
p.add_argument('--strip-issue-hints', action='store_true',
               help='Remove Task fields that restate the issue solution (T1 requested move, T2 split contract).')
a = p.parse_args()
os.environ.setdefault('PLANBEE_RUNS_DIR', str(ROOT / 'runs' / 'v2'))
os.environ['PLANBEE_RUN_ORIGIN'] = 'ablation'

from app import store, llm, hive  # noqa: E402
from app.candidates import engine  # noqa: E402
from app.candidates.models import Designs  # noqa: E402
from app.policies import needs_review  # noqa: E402
from scripts.check_m4_results import checks  # noqa: E402

ORIGINAL_INVOKE = engine.invoke
# Fields that restate what the issue text asks for. Authorization contracts that exist regardless
# of the issue (defer_option, covered_by, stage-split permission, allowed_assignees, deadlines) stay:
# without them the engine forbids scope changes for every approach by design.
ISSUE_HINTS = {
    'm4_t1_rescheduling': {'polish': ['requested_start', 'single_actor']},
    'm4_t2_reallocation': {'ui_integration': ['required_parts', 'split_boundary']},
}
ORIGINAL_REVIEW = engine.review_no_options


def settings():
    return engine.Settings(seed=a.seed, max_calls=60, max_seconds=600, max_rounds=2, raw_limit=200,
                           candidate_limit=4, shortlist_limit=4)


def audit(db, run, c):
    """Code-checkable card facts for one plan: who must confirm, who receives refused work."""
    confirm, refused = [], []
    for pid in c['affected']:
        facts = engine.participant_facts(db, run, pid, [c])['candidates'][0]
        card = run.ctx['private_cards'][pid]
        amount = sum(x['days'] for x in facts['my_new_work'])
        if any(x.get('tag') in card.get('refuse_tags', []) for x in facts['my_new_work']):
            refused.append(pid)
        if amount > card['auto_days'] + hive.EPS or needs_review(NS(**card)) or pid in c.get('required_confirmations', []):
            confirm.append(pid)
    return dict(id=c['id'], title=c['title'], needs_confirmation=sorted(set(confirm)), refused_tag=sorted(set(refused)),
                variance=c['board']['fairness']['variance'])


def run_one(condition, sid):
    os.environ['PLANBEE_LLM'] = 'mock' if condition == 'algorithm' else 'live'
    llm.set_llm(None)
    if condition == 'algorithm':
        engine.invoke = lambda db, run, schema, *rest, **kw: (Designs(templates=[], reason='algorithm-only')
                                                             if schema is Designs else ORIGINAL_INVOKE(db, run, schema, *rest, **kw))
    else:
        engine.invoke = ORIGINAL_INVOKE
    # Asking people to review a failed search is a personal-proxy (discussion) call.
    engine.review_no_options = ORIGINAL_REVIEW if condition == 'full' else (lambda *x, **k: None)
    store.use_demo(sid)
    dbengine = store.make_engine('sqlite://'); started = time.monotonic()
    with store.make_session_factory(dbengine)() as db:
        store.reset(db); f = store.load_yaml('feed.yaml')['issue']
        if a.strip_issue_hints:
            from app.models import Task
            for tid, drop in ISSUE_HINTS.get(sid, {}).items():
                task = db.get(Task, tid)
                task.context = {k: v for k, v in (task.context or {}).items() if k not in drop}
            db.flush()
        run = engine.start(db, f['task'], f['records'][0]['text'], settings())
        if condition == 'full':
            for _ in range(80):
                if run.status != 'running':
                    break
                engine.advance(db, run)
        db.commit()
        result = engine.response(run)
        pool = [c for c in run.ctx.get('candidates', [])]
        by_variance = sorted(pool, key=lambda c: (c['board']['fairness']['variance'], c['id']))
        if condition == 'full':
            chosen = [c for c in pool if c['id'] in (result.get('final_candidates') or [])]
            consented = True
        else:
            chosen = by_variance[:1] if condition == 'algorithm' else by_variance[:3]
            consented = False
            if chosen:
                result['final_candidates'] = [c['id'] for c in chosen]
                result['status'] = 'awaiting_pm_selection'
        audits = [audit(db, run, c) for c in chosen]
        report = dict(condition=condition, scenario=sid, issue_hints_removed=a.strip_issue_hints, status=result['status'], termination=result.get('termination'),
                      llm_calls=0 if condition == 'algorithm' else run.ctx['llm_budget']['used'],
                      duration_seconds=round(time.monotonic() - started, 2), pool=len(pool),
                      chosen=audits, consent_collected=consented, model_error=run.ctx.get('model_error'),
                      checks=checks(sid, result), transcript_file=run.ctx.get('transcript_file'))
    dbengine.dispose()
    return report


stamp = datetime.now().astimezone().strftime('%Y-%m-%d_%H-%M-%S')
out = ROOT / 'eval' / 'ablation' / (stamp + ('_no_issue_hints' if a.strip_issue_hints else '_structured')); out.mkdir(parents=True, exist_ok=True)
results = []
for condition in a.condition or ['algorithm', 'no_discussion', 'full']:
    for sid in a.scenario or store.service_demos():
        print('START', condition, sid, flush=True)
        r = run_one(condition, sid)
        results.append(r)
        (out / 'summary.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
        print('RESULT', json.dumps({k: r[k] for k in ('condition', 'scenario', 'status', 'termination', 'llm_calls', 'pool')}, ensure_ascii=False),
              'ready', r['checks']['expected_outcome_ready'], 'match', len(r['checks']['matching_pm_options']),
              'confirm', [x['needs_confirmation'] for x in r['chosen']], 'refused', [x['refused_tag'] for x in r['chosen']], flush=True)
print('ABLATION', out, flush=True)
