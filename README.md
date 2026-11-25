# Plan Bee — DPM4 high-fi prototype

Plan Bee helps a small game team re-plan a sprint when one person's schedule changes.
The PM reports the change in one sentence. **Hive** (code, not an LLM) finds who is affected and
searches for plans that keep the rules and the deadline. Each affected teammate has a **proxy agent**
(an LLM) that knows only that teammate's profile; the proxies discuss the plans in public and state
preferences, objections, conditions and questions. The PM picks one of at most three plans, A/B/C,
or—if no plan fits the rules—picks one rule to relax.

CS473 (KAIST) · Team Plan Bee · Yeokyung Chang, Jeongmin Lee, Jooho Son, Najeong Ryu

## Try the deployed prototype

- URL: see the DPM4 report (the Render service is password-protected).
- Desktop Chrome. The free server sleeps when idle; the first load can take about a minute.
- One change takes 20–60 seconds because every proxy reply is a real LLM call.
- The server keeps one shared sprint board. If several people use it at the same time, they see the same board.

## Run locally

Python 3.10 or newer.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env        # then set OPENROUTER_API_KEY in .env
.venv/bin/python start.py --llm live
```

Open http://127.0.0.1:8000. Free-text input needs `--llm live`.

## The three tasks

| Task | What the PM does | What the agents do |
|---|---|---|
| T1 · Report a change | Picks a sentence template (or types freely), fills the blanks, sends | An LLM reads the sentence into day + morning/afternoon slots; Hive converts them to times, finds the late handoffs and invites only the affected teammates' proxies |
| T2 · Let the proxies discuss | Watches the rounds and opens the evidence behind any message | Round 1: every invited proxy states a position on plans A/B/C. Later rounds: only proxies that were asked a question answer. Stops when no questions remain, or after 3 rounds |
| T3 · Decide before anything changes | Compares A/B/C with their tallies, previews one on the board, presses "이 안으로 결정" | Hive re-checks the chosen plan on the latest board and applies it all-or-nothing. If no plan fits the rules, each proxy says which rule would cost it least and the PM grants one |

"↺ 보고 전으로" restores the board to just before the last report; "초기화" resets everything.

## Where things are

| Path | What it holds |
|---|---|
| `start.py` | Starts the server |
| `app/candidates/engine.py` | The pipeline: read → impact → plans → discussion → PM choice → apply |
| `app/candidates/generator.py`, `plans.py`, `relax.py` | Plan generation, rule checks, rule relaxation |
| `app/candidates/card_proxy.py` | What each proxy is told about its own costs per plan |
| `app/hive.py` | Scheduling, deadline and capacity checks |
| `prompts/` | Prompts for reading the PM's sentence, proxy speech and plan shapes |
| `seed/m4_g4_free/` | The demo team and board; `seed/m4_g1_qa_absence/`, `m4_g2_art_slip/`, `m4_g3_deploy_slot/` are the three test scenarios |
| `front/Plan Bee Front.html`, `front/planbee-app.js` | The UI (channel, board, templates) |
| `scripts/` | Evaluation scripts (below) |

## Evaluation

```bash
# three scenarios with written answer keys, 3 runs each (live LLM)
.venv/bin/python scripts/run_game_scenarios.py --llm live --repeat 3

# same scenarios without proxy discussion (Hive rule order only)
.venv/bin/python scripts/run_game_scenarios.py --llm live --no-discussion

# 18 labelled free-text sentences: changes, questions, unrelated text
.venv/bin/python scripts/probe_free_input.py

# end-to-end UI test in a real browser (needs: pip install playwright && python -m playwright install chromium)
.venv/bin/python scripts/e2e_ui.py --url http://127.0.0.1:8000
```

Results are written to `eval/game_scenarios/`, `eval/free_input/` and `eval/e2e/` as `report.md` and `summary.json`.

| Scenario | Change | Checked |
|---|---|---|
| ① QA absence | Zoe can't run Thursday afternoon's Q2 smoke test | Leo invited, Mia not; plans handing the test to Ben and to Sam both appear; Zoe keeps the final regression |
| ② Handoff delay | Mia can't finish A1 boss art on Wednesday morning | A plan splitting G2 and a plan moving the boss check to Q2 both appear; the G3 demo build does not move |
| ③ Outside the rules | Sam can't deploy S2 on Wednesday afternoon | No plan within the rules; relaxing R1 or R3 yields plans, R2 does not |

Older developer notes (legacy negotiation path, earlier demos) are in [`docs/README_dev.md`](docs/README_dev.md).
