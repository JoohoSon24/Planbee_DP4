"""Free-input scenario (④): how well does the first LLM step read a PM message?

Runs only the input step (one LLM call per message) on a fresh ④ board and scores it
against a labelled set written before the run. No planning or discussion calls.

Usage (from the project folder):
  python3 scripts/probe_free_input.py              # live model, every case once
  python3 scripts/probe_free_input.py --repeat 3   # stability: same case 3 times
Results: eval/free_input/<time>/report.md, summary.json
"""
from pathlib import Path
from datetime import datetime
from collections import Counter
import argparse
import re
import json
import os
import sys
import time

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
p = argparse.ArgumentParser()
p.add_argument('--repeat', type=int, default=1)
p.add_argument('--case', action='append')
a = p.parse_args()
os.environ['PLANBEE_LLM'] = 'live'
os.environ.setdefault('PLANBEE_RUNS_DIR', str(ROOT / 'runs' / 'v2'))
os.environ['PLANBEE_RUN_ORIGIN'] = 'probe_free_input'

from app import store, llm  # noqa: E402
from app.candidates import engine  # noqa: E402

SID = 'm4_g4_free'
# Board time: 0 = Mon 09:00, 0.5 = Mon 13:00 … 4.5 = Fri 13:00. "Now" is Tue 13:00 (1.5).
# win = the absence window the message implies (start, end); new_days = the new workload.
CASES = [
    # --- schedule changes (plain text) ---
    dict(id='c1_absence', text='Ben이 B2 메뉴 화면을 수요일 오후에는 시작할 수 없대요. 목요일 오후부터 할 수 있대요.',
         kind='change', task='B2', person='ben', win=(2.5, 3.5)),
    dict(id='c2_workload', text='S3 랭킹 화면이 생각보다 커서 반나절이 더 걸린대요.',
         kind='change', task='S3', new_days=1.5),
    dict(id='c3_sick_day', text='Mia가 목요일 하루 병가예요.',
         kind='change', task='A2', person='mia', win=(3.0, 4.0)),
    dict(id='c4_first_person', text='제가 금요일 오전에 회의가 생겨서 Q2 통합 QA를 못 봐요.',
         kind='change', task='Q2', person='zoe', win=(4.0, 4.5), note='화자=PM이 아니라 Zoe의 말을 그대로 옮긴 경우: person은 Q2 담당 Zoe'),
    dict(id='c5_handoff', text='G2 보스전 연결이 하루 더 걸려서 QA로 넘어가는 게 늦어질 것 같아요.',
         kind='change', task='G2', new_days=2.0),
    # --- schedule changes with quoted board items (the composer appends "참조: … [id]") ---
    dict(id='r1_task_ref', text='이 업무 수요일 오후에 못 해요. 목요일 오전부터 가능해요.\n\n참조: 업무 S2 · 서버 배포 [S2]',
         kind='change', task='S2', person='sam', win=(2.5, 3.0)),
    dict(id='r2_person_ref', text='이 사람 수요일 오후에 외부 일정이 있어요.\n\n참조: 사람 Leo [leo]',
         kind='change', task='G2', person='leo', win=(2.5, 3.0), note='수 오후 Leo가 하는 일은 G2(수 오후~목 오전)'),
    dict(id='r3_handoff_ref', text='이 인계가 하루 늦어져요.\n\n참조: Handoff A1 · 보스 그림 → G2 · 보스전 연결 [h_A1_G2]',
         kind='change', task='A1', new_days=2.0),
    # --- sentences built from the composer templates (blanks filled by chips; quoted items appended) ---
    dict(id='t1_tpl_absence', text='Sam 님이 수요일 오후에 S2 · 서버 배포 작업을 못 한대요. 목요일 오전부터 할 수 있대요.\n\n참조: 사람 Sam [sam], 업무 S2 · 서버 배포 [S2]',
         kind='change', task='S2', person='sam', win=(2.5, 3.0)),
    dict(id='t2_tpl_workload', text='G2 · 보스전 연결 작업이 반나절 더 걸린대요.\n\n참조: 업무 G2 · 보스전 연결 [G2]',
         kind='change', task='G2', new_days=1.5),
    dict(id='t3_tpl_dayoff', text='Zoe 님이 금요일 하루 쉬어요.\n\n참조: 사람 Zoe [zoe]',
         kind='change', task='Q2', person='zoe', win=(4.0, 5.0)),
    dict(id='t4_tpl_question', text='A2 · 이펙트 다듬기 작업은 언제 끝나요?\n\n참조: 업무 A2 · 이펙트 다듬기 [A2]',
         kind='question', expect_in_answer=['목'], expect_not_in_answer=['금'], note='A2는 목 오전~목 오후, 목요일 저녁에 끝남'),
    # --- questions ---
    dict(id='q1_who', text='Q2는 누가 해?', kind='question', expect_in_answer=['Zoe']),
    dict(id='q2_free_slot', text='목요일 오후에 비어 있는 사람 있어?', kind='question', expect_in_answer=['Leo', 'Ben'],
         expect_not_in_answer=['Mia', 'Sam', 'Zoe'], free_names=True,
         note='목 오후: Leo(G2는 목 오전까지)·Ben(B2는 목 오전까지)이 비어 있음'),
    dict(id='q3_ref_question', text='이 업무 언제 끝나?\n\n참조: 업무 B2 · 메뉴 화면 [B2]', kind='question', expect_in_answer=['목'], expect_not_in_answer=['금'],
         note='B2는 수 오후~목 오전, 목요일 13시에 끝남'),
    # --- other / unclear ---
    dict(id='o1_greeting', text='안녕하세요! 오늘도 화이팅', kind='other'),
    dict(id='o2_unrelated', text='점심 메뉴 추천해줘', kind='other'),
    dict(id='u1_vague', text='일정이 좀 꼬였어요', kind='change', unclear=True, note='무엇이 바뀌었는지 없음 → 되묻기(clarification)가 정답'),
]


def run_case(case):
    store.use_demo(SID); llm.set_llm(None)
    dbengine = store.make_engine('sqlite://')
    with store.make_session_factory(dbengine)() as db:
        store.reset(db)
        t0 = time.monotonic()
        try:
            run = engine.start(db, None, case['text'], engine.Settings(max_calls=10), reporter='pm')
            err = None
        except Exception as e:  # model failure counts as a miss, not a crash
            run, err = None, f'{type(e).__name__}: {e}'
        sec = round(time.monotonic() - t0, 1)
        ctx = run.ctx if run else {}
        ch = ctx.get('reported_change') or {}
        term = ctx.get('termination')
        got_kind = 'change' if ch else (ctx.get('input_kind') or 'other') if term == 'not_a_change' else \
                   'clarify' if term == 'issue_needs_clarification' else 'error'
        answer = ctx.get('clarification') or ''
        if got_kind == 'error' and not err:
            err = f"{term}: {ctx.get('model_error') or ''}"[:200]
        return dict(id=case['id'], seconds=sec, error=err, kind=got_kind, task=ctx.get('task'), change=ch, answer=answer,
                    calls=(ctx.get('llm_budget') or {}).get('used'))


def score(case, got):
    s = {}
    if case.get('unclear'):
        # Right if nothing is changed and the PM is asked for more (a clarification, or a question-style reply).
        s['kind'] = got['kind'] in ('clarify', 'question', 'other') and not got['change']
        return s
    s['kind'] = got['kind'] == case['kind']
    if case['kind'] == 'change' and got['kind'] == 'change':
        ch = got['change']; ap = ch.get('applied') or {}
        s['task'] = got['task'] == case['task']
        if 'person' in case:
            s['person'] = ch.get('person') == case['person']
        if 'win' in case:
            ws = ap.get('windows') or []
            lo, hi = case['win']
            # the window must cover the stated slot and not spill more than half a day outside it
            s['window'] = bool(ws) and abs(min(w['start'] for w in ws) - lo) < 1e-6 and abs(max(w['end'] for w in ws) - hi) < 1e-6
        if 'new_days' in case:
            s['workload'] = ap.get('new_days') is not None and abs(ap['new_days'] - case['new_days']) < 0.26
    if case['kind'] == 'question' and got['kind'] == 'question' and case.get('expect_in_answer'):
        ans = got['answer']
        if case.get('free_names'):   # judge only the sentence that says who is free
            head = next((x for x in re.split(r'(?<=[.!?다요])\s+', ans) if '비어' in x), '')
            ans = head
        s['answer'] = all(x in ans for x in case['expect_in_answer']) and not any(x in ans for x in case.get('expect_not_in_answer', []))
    return s


def main():
    cases = [c for c in CASES if not a.case or c['id'] in a.case]
    stamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    out = ROOT / 'eval' / 'free_input' / stamp; out.mkdir(parents=True, exist_ok=True)
    rows = []
    for case in cases:
        for i in range(a.repeat):
            got = run_case(case); sc = score(case, got)
            rows.append(dict(case=case['id'], repeat=i + 1, expected_kind='clarify' if case.get('unclear') else case['kind'],
                             score=sc, ok=all(sc.values()), **got))
            print(f"{case['id']:<16} {'OK ' if rows[-1]['ok'] else 'MISS'} kind={got['kind']:<8} task={got['task']} "
                  f"{json.dumps(sc, ensure_ascii=False)} {got['seconds']}s {got['error'] or ''}", flush=True)
    by_field = Counter(); hit = Counter()
    for r in rows:
        for k, v in r['score'].items():
            by_field[k] += 1; hit[k] += bool(v)
    kinds = Counter((r['expected_kind'], r['kind']) for r in rows)
    stable = {}
    for c in cases:
        rs = [r for r in rows if r['case'] == c['id']]
        stable[c['id']] = len({(r['kind'], r['task'], json.dumps((r['change'].get('applied') or {}), sort_keys=True)) for r in rs}) == 1
    summary = dict(cases=len(cases), repeat=a.repeat, all_ok=sum(r['ok'] for r in rows), runs=len(rows),
                   field_accuracy={k: f'{hit[k]}/{by_field[k]}' for k in by_field},
                   kind_confusion={f'{e}->{g}': n for (e, g), n in sorted(kinds.items())},
                   stable_across_repeats=stable if a.repeat > 1 else None,
                   seconds_median=sorted(r['seconds'] for r in rows)[len(rows) // 2], errors=sum(1 for r in rows if r['error']))
    (out / 'summary.json').write_text(json.dumps(dict(summary=summary, rows=rows), ensure_ascii=False, indent=1), encoding='utf-8')
    lines = [f'# Free-input probe · {stamp}', '', f"전체 정답 {summary['all_ok']}/{summary['runs']} · 오류 {summary['errors']} · 중앙값 {summary['seconds_median']}초", '',
             '| 항목 | 정확도 |', '|---|---|'] + [f'| {k} | {v} |' for k, v in summary['field_accuracy'].items()] + \
            ['', '| 기대 → 실제 | 횟수 |', '|---|---|'] + [f'| {k} | {v} |' for k, v in summary['kind_confusion'].items()] + \
            ['', '| case | 결과 | kind | task | 점수 | 답/요약 |', '|---|---|---|---|---|---|'] + \
            [f"| {r['case']} | {'OK' if r['ok'] else 'MISS'} | {r['kind']} | {r['task'] or ''} | {json.dumps(r['score'], ensure_ascii=False)} | "
             f"{(r['change'].get('summary') if r['change'] else r['answer'] or r['error'] or '')[:80]} |" for r in rows]
    (out / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'\n{summary}\n→ {out}/report.md')


if __name__ == '__main__':
    main()
