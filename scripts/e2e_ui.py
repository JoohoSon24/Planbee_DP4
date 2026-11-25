"""End-to-end UI test of a running Plan Bee server (local or deployed), driven in a real browser.

    python3 scripts/e2e_ui.py --url http://127.0.0.1:8000
    PLANBEE_PASSWORD=... python3 scripts/e2e_ui.py --url https://planbee-o9nt.onrender.com --user planbee
    add --headed to watch, --skip-live to skip the two steps that call the LLM

Each step is a named check; the run stops a step on failure but continues with the next one.
Results go to eval/e2e/<timestamp>/report.md and summary.json, with a screenshot per step.
The test resets the board at the start and at the end.
"""
from pathlib import Path
from datetime import datetime
import argparse
import json
import os
import re
import sys
import time

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    sys.exit('Playwright is missing: pip install playwright && python3 -m playwright install chromium')

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument('--url', default='http://127.0.0.1:8000')
p.add_argument('--user', default=os.environ.get('PLANBEE_USER', 'planbee'))
p.add_argument('--password', default=os.environ.get('PLANBEE_PASSWORD', ''))
p.add_argument('--lang', choices=['ko', 'en'], default='en')
p.add_argument('--headed', action='store_true')
p.add_argument('--skip-live', action='store_true')
p.add_argument('--timeout', type=int, default=180, help='seconds to wait for one LLM run')
a = p.parse_args()

out = ROOT / 'eval' / 'e2e' / datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
out.mkdir(parents=True, exist_ok=True)
results, errors = [], []


def step(name):
    def wrap(fn):
        started = time.monotonic()
        try:
            detail = fn() or ''
            ok = True
        except Exception as exc:  # one failing step must not hide the others
            ok, detail = False, f'{type(exc).__name__}: {exc}'.splitlines()[0][:300]
        shot = out / f'{len(results) + 1:02d}_{re.sub(r"[^a-z0-9]+", "_", name.lower())[:40]}.png'
        try:
            page.screenshot(path=str(shot))
        except Exception:
            shot = None
        results.append(dict(step=name, ok=ok, detail=str(detail), seconds=round(time.monotonic() - started, 1),
                            screenshot=shot.name if shot else None))
        print(('PASS ' if ok else 'FAIL ') + name + (f' — {detail}' if detail else ''), flush=True)
        return ok
    return wrap


server_errors = []


def api(path, tries=3):
    """GET a JSON endpoint; a 5xx is recorded as a finding and retried, since one busy moment should not end the test."""
    for i in range(tries):
        r = page.request.get(a.url.rstrip('/') + path)
        if r.ok:
            return r.json()
        if r.status >= 500:
            server_errors.append(f'{path} -> {r.status}')
            page.wait_for_timeout(2000)
            continue
        break
    raise AssertionError(f'{path} -> {r.status}')


def text(sel):
    return page.locator(sel).first.inner_text(timeout=5000).strip()


def last_run_id():
    runs = api('/candidate-runs')
    return runs[0]['id'] if runs else 0


def wait_run_stops(after):
    """Wait for a run newer than `after` to start, then poll that run (as the UI does) until it stops."""
    deadline = time.monotonic() + a.timeout
    rid = None
    while time.monotonic() < deadline and rid is None:
        runs = api('/candidate-runs')
        if runs and runs[0]['id'] > after:
            rid = runs[0]['id']
        else:
            page.wait_for_timeout(1500)
    while rid and time.monotonic() < deadline:
        r = api(f'/runs/{rid}')
        if r['status'] != 'running':
            return r
        page.wait_for_timeout(3000)
    raise AssertionError(f'run still running after {a.timeout}s')


with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=not a.headed)
    ctx = browser.new_context(viewport=dict(width=1440, height=900),
                              http_credentials=dict(username=a.user, password=a.password) if a.password else None)
    ctx.add_init_script(f"try{{localStorage.setItem('pb-lang','{a.lang}');sessionStorage.setItem('pb-lang-chosen','{a.lang}');localStorage.removeItem('pb-example-m4_g4_free')}}catch(e){{}}")
    page = ctx.new_page()
    page.on('pageerror', lambda e: errors.append('pageerror: ' + str(e)[:200]))
    page.on('console', lambda m: errors.append('console: ' + m.text[:200]) if m.type == 'error' and '/llm/usage' not in m.text else None)
    page.on('dialog', lambda d: d.accept())   # revert and reset ask for confirmation

    @step('Load page and state')
    def _():
        r = page.goto(a.url, wait_until='domcontentloaded', timeout=120000)
        assert r and r.status == 200, f'HTTP {r.status if r else "none"}'
        page.wait_for_selector('#goalbar b', timeout=60000)
        rt = api('/runtime'); st = api('/state')
        assert rt['llm_mode'] == 'live' or a.skip_live, f"llm_mode={rt['llm_mode']}"
        assert [d['id'] for d in st['demo']['catalog']] == ['m4_g4_free'], st['demo']['catalog']
        assert len(st['demo'].get('examples') or []) == 5, 'examples'
        return f"llm_mode={rt['llm_mode']} · scenario={st['demo']['id']}"

    @step('Reset board')
    def _():
        page.click('#reset'); page.wait_for_timeout(2500)
        st = api('/state')
        assert not [r for r in api('/candidate-runs') if r['status'] in ('running', 'awaiting_pm_selection')], 'open run left'
        return f"now={st['now']}"

    @step('Sprint goal is the goal, not the scenario title')
    def _():
        g = text('#goalbar b')
        assert ('demo build' in g.lower() or '데모 빌드' in g) and 'live' not in g.lower(), g
        return g

    @step('Board shows five people and the deadline')
    def _():
        names = page.locator('#lanes .lane .who b, #grid .row-h b').all_inner_texts() or []
        body = page.locator('#grid').inner_text()
        for n in ('Mia', 'Leo', 'Sam', 'Ben', 'Zoe'):
            assert n in body, f'{n} missing'
        assert '17:00' in page.locator('#demo').inner_text(), 'deadline marker'

    @step('Tab cycles the five examples')
    def _():
        box = page.locator('#change-input'); seen = []
        for _ in range(3):
            box.click(); page.keyboard.press('Tab'); page.wait_for_timeout(600)
            seen.append(box.input_value())
        assert all(seen) and len(set(seen)) == 3, seen
        assert re.search(r'\((?:\d)/5\)', text('#composer-help')), text('#composer-help')
        box.fill('')
        return ' | '.join(s[:30] for s in seen)

    @step('Template fills blanks from chips')
    def _():
        page.click('#sugg [data-template] >> nth=0'); page.wait_for_timeout(300)
        before = page.locator('#change-input').input_value()
        page.click('#blank-pick button >> nth=0'); page.wait_for_timeout(300)
        after = page.locator('#change-input').input_value()
        assert after != before, after
        assert a.lang != 'en' or not re.search('[가-힣]', after), f'Korean left in English sentence: {after}'
        page.locator('#change-input').fill(''); page.wait_for_timeout(200)
        return after[:70]

    @step('Task tile opens the detail drawer')
    def _():
        page.click('#grid .tile >> nth=2'); page.wait_for_timeout(500)
        assert page.locator('#drawer.open').count() == 1, 'drawer did not open'
        page.keyboard.press('Escape'); page.wait_for_timeout(300)

    @step('Chat hides and opens again')
    def _():
        w0 = page.locator('.chan').bounding_box()['width']
        page.click('.chat-toggle'); page.wait_for_timeout(700)
        w1 = page.locator('.chan').bounding_box()['width']
        page.click('.chat-reopen, [aria-label="Open chat"], [aria-label="채팅 열기"]'); page.wait_for_timeout(700)
        w2 = page.locator('.chan').bounding_box()['width']
        assert w1 < 5 and abs(w2 - w0) < 5, (w0, w1, w2)
        return f'{w0:.0f} → {w1:.0f} → {w2:.0f}px'

    if not a.skip_live:
        @step('Question is answered without changing the board')
        def _():
            before = api('/state')['tasks']
            box = page.locator('#change-input')
            box.fill('Who is free on Thursday afternoon?' if a.lang == 'en' else '목요일 오후에 비어 있는 사람이 누구예요?')
            last = last_run_id()
            page.click('#form button[type=submit]')
            r = wait_run_stops(last)
            assert r.get('termination') == 'not_a_change', (r['status'], r.get('termination'))
            assert api('/state')['tasks'] == before, 'board changed'
            return 'answered · board unchanged'

        @step('Change report reaches plans A/B/C with a discussion')
        def _():
            # Example 1 (Ben, B2) is the one that changes the board; type it so the Tab position does not matter.
            sent = ("Ben can't start the B2 menu screen on Wednesday afternoon. He can work on it from Thursday afternoon."
                    if a.lang == 'en' else 'Ben이 B2 메뉴 화면을 수요일 오후에는 시작할 수 없대요. 목요일 오후부터 할 수 있대요.')
            page.locator('#change-input').fill(sent)
            last = last_run_id()
            page.click('#form button[type=submit]')
            r = wait_run_stops(last)
            assert r['status'] == 'awaiting_pm_selection', (r['status'], r.get('termination'), r.get('model_error'))
            page.wait_for_selector('.pb-impact', timeout=20000)
            page.wait_for_selector('.opt', timeout=20000)
            rounds = page.locator('details.round').count()
            opts = page.locator('.opt').count()
            assert 1 <= opts <= 3 and rounds >= 1, (opts, rounds)
            return f'"{sent[:50]}" → {opts} plans, {rounds} round(s), {r["llm_budget"]["used"]} LLM calls'

        @step('Evidence opens from a discussion message')
        def _():
            page.click('details.round >> nth=0 >> summary'); page.wait_for_timeout(300)
            page.click('details.bas >> nth=0 >> summary'); page.wait_for_timeout(300)
            page.click('details.bas[open] li >> nth=0'); page.wait_for_timeout(600)
            assert page.locator('#drawer.open').count() == 1 or page.locator('.tile.chg, .tile.new').count() > 0, 'no drawer or preview'
            page.keyboard.press('Escape')

        @step('Selecting a plan previews it, then applies it')
        def _():
            changed = 0
            for i in range(page.locator('.opt').count()):     # a plan may legitimately keep the board as it is
                page.click(f'.opt >> nth={i}'); page.wait_for_timeout(800)
                changed = page.locator('#grid .tile.chg, #grid .tile.new').count()
                if changed:
                    break
            assert changed > 0, 'no plan preview shows changed tasks'
            page.click('[data-select]:not([disabled]) >> nth=0')
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                r = api('/candidate-runs')[0]
                if r['status'] in ('done', 'applied') or r.get('termination') == 'applied':
                    break
                page.wait_for_timeout(1500)
            r = api(f"/runs/{api('/candidate-runs')[0]['id']}")
            assert r.get('termination') == 'applied', (r['status'], r.get('termination'))
            return f'{changed} tasks changed in preview · applied'

        @step('"Before this report" restores the board')
        def _():
            before = api('/state')['tasks']
            page.click('[data-revert-report]'); page.wait_for_timeout(2500)
            after = api('/state')['tasks']
            assert after != before, 'board did not change back'
            r = api(f"/runs/{api('/candidate-runs')[0]['id']}")
            assert r.get('termination') == 'reverted', r.get('termination')

    @step('Final reset')
    def _():
        if page.locator('[data-stop-run]').count():          # leave no run behind on a shared server
            page.click('[data-stop-run]'); page.wait_for_timeout(4000)
        page.click('#reset', timeout=60000); page.wait_for_timeout(2500)
        assert not [r for r in api('/candidate-runs') if r['status'] == 'running'], 'a run is still running'

    @step('No server errors (5xx)')
    def _():
        assert not server_errors, server_errors[:5]

    @step('No page or console errors')
    def _():
        assert not errors, errors[:5]

    browser.close()

passed = sum(r['ok'] for r in results)
(out / 'summary.json').write_text(json.dumps(dict(url=a.url, lang=a.lang, passed=passed, total=len(results), results=results, errors=errors), ensure_ascii=False, indent=1))
lines = [f'# E2E UI test · {out.name}', '', f'{a.url} · {a.lang} · **{passed}/{len(results)} passed**', '', '| # | Step | Result | Time | Detail |', '|---|---|---|---|---|']
lines += [f"| {i} | {r['step']} | {'PASS' if r['ok'] else 'FAIL'} | {r['seconds']}s | {r['detail'].replace('|', '/')} |" for i, r in enumerate(results, 1)]
if errors:
    lines += ['', '## Browser errors', ''] + [f'- {e}' for e in errors[:20]]
(out / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
print(f'\n{passed}/{len(results)} passed · {out.relative_to(ROOT)}/report.md')
sys.exit(0 if passed == len(results) else 1)
