"""The three published game-team data scenarios (plus the free-input check), run offline (Mock) through the candidate engine."""
from pathlib import Path
import yaml
import pytest
from app import store, llm
from app.candidates import engine

ROOT = Path(__file__).resolve().parents[1]
IDS = ['m4_g1_qa_absence', 'm4_g2_art_slip', 'm4_g3_deploy_slot']


def drive(db, run):
    for _ in range(120):
        if run.status != 'running':
            break
        engine.advance(db, run)


def start(sid):
    store.use_demo(sid); llm.set_llm(None)
    db = store.make_session_factory(store.make_engine('sqlite://'))()
    store.reset(db)
    feed = yaml.safe_load((ROOT / 'seed' / sid / 'feed.yaml').read_text(encoding='utf-8'))['issue']
    rec = feed['records'][0]
    run = engine.start(db, feed['task'], rec['text'], engine.Settings(shortlist_limit=6, max_rounds=4, max_calls=120),
                       reporter='pm')
    drive(db, run)
    return db, run


def test_demo_lists_only_free_input_and_keeps_test_set():
    assert store.service_demos() == ['m4_g4_free']
    cfg = yaml.safe_load((ROOT / 'seed' / 'catalog.yaml').read_text(encoding='utf-8'))
    assert cfg['test_set'] == IDS and cfg['default'] == 'm4_g4_free'


def test_data_scenarios_pin_card_rules_and_free_input_needs_live():
    for sid in IDS:
        assert yaml.safe_load((ROOT / 'seed' / sid / 'team.yaml').read_text(encoding='utf-8'))['meta']['llm_mode'] == 'mock'
    store.use_demo('m4_g4_free'); llm.set_llm(None)
    db = store.make_session_factory(store.make_engine('sqlite://'))()
    store.reset(db)
    run = engine.start(db, None, 'Ben이 B2 메뉴 화면을 수요일 오후에는 시작할 수 없대요.', engine.Settings(), reporter='pm')
    assert run.ctx['termination'] == 'issue_needs_clarification' and 'Live' in run.ctx['clarification']


@pytest.mark.parametrize('sid', IDS)
def test_discussion_mode_reaches_pm_options(sid):
    db, run = start(sid)
    expected = yaml.safe_load((ROOT / 'seed' / sid / 'expected.yaml').read_text(encoding='utf-8'))
    imp = run.ctx['impact']
    assert run.ctx['consent_mode'] == 'discussion'
    assert set(expected['impact']['broken_any']) <= set(imp['broken'])
    assert set(expected['impact']['not_involved']) <= set(imp['not_involved'])
    if expected.get('first_pass'):
        assert run.ctx['termination'] == 'needs_rule_relaxation'
        found = {o['id']: o['feasible'] for o in run.ctx['relaxation_options']}
        assert found['R1'] > 0 and found['R2'] == 0 and found['R3'] > 0
        engine.grant_rule(db, run, expected['grant'], 'test')
        drive(db, run)
    assert run.status == 'awaiting_pm_selection'
    final = [c for c in run.ctx['candidates'] if c['id'] in run.ctx['final_candidates']]
    assert 1 <= len(final) <= 3
    assert all(c.get('discussion_tally') for c in final)
    assert not set(expected['participants']['exclude']) & set(run.ctx['participants'])
    spoken = [e for e in run.ctx['public_history'] if e.get('phase') == 'fairness_discussion' and e['requester'] not in ('hive', 'pm')]
    assert spoken and all('basis' in e and 'reply_to' in e for e in spoken)


def test_qa_absence_offers_ben_and_sam():
    db, run = start('m4_g1_qa_absence')
    final = [c for c in run.ctx['candidates'] if c['id'] in run.ctx['final_candidates']]
    takers = {tuple(sorted({a['who'] for a in c['allocations']} - {'zoe'})) for c in final}
    assert ('ben',) in takers and ('sam',) in takers
    assert all(a['who'] == 'zoe' for c in final for a in c['allocations'] if a.get('key') == 'regression')


def test_pm_selection_applies_without_personal_confirmation():
    db, run = start('m4_g2_art_slip')
    c = next(c for c in run.ctx['candidates'] if c['id'] == run.ctx['final_candidates'][0])
    engine.select_pm(db, run, 'select', c['id'], c['plan_hash'], 'test')
    assert run.status == 'done' and run.ctx['termination'] == 'applied'
