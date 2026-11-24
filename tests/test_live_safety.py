"""Live demo safety: a report can be undone without losing the thread, and a run can be stopped."""
import pytest
from fastapi.testclient import TestClient
from app import api, store
from app.models import Card


@pytest.fixture
def env(monkeypatch):
    old = store.DEMO; store.use_demo('m4_g1_qa_absence')
    eng = store.make_engine('sqlite://'); factory = store.make_session_factory(eng)
    monkeypatch.setattr(api, 'SessionLocal', factory)
    with TestClient(api.app) as client:
        client.post('/reset', json={})
        yield client, factory
    store.use_demo(old); eng.dispose()


def drive(client, r):
    for _ in range(80):
        if r['status'] != 'running':
            return r
        r = client.post(f"/runs/{r['id']}/advance", json={}).json()
    return r


def test_revert_restores_board_and_keeps_thread(env):
    client, factory = env
    before = client.get('/state').json()
    r = client.post('/candidate-runs', json=dict(task_id='Q2', issue='Zoe가 목요일 오후 스모크를 못 한대요.')).json()
    r = drive(client, r)
    assert r['status'] == 'awaiting_pm_selection'
    # simulate what a free-input report does: change a card and a task after the run started
    with factory() as db:
        card = db.get(Card, 'mia'); card.policy = {**(card.policy or {}), 'unavailable': [dict(start=3, end=4, reason='x')]}
        db.commit()
    out = client.post(f"/runs/{r['id']}/revert-report", json={})
    assert out.status_code == 200, out.text
    body = out.json()
    assert body['termination'] == 'reverted' and body['status'] == 'done'
    after = client.get('/state').json()
    assert after['tasks'] == before['tasks']
    with factory() as db:
        assert not (db.get(Card, 'mia').policy or {}).get('unavailable')
    runs = client.get('/candidate-runs').json()
    assert runs and runs[0]['id'] == r['id'] and any(e['response'] == 'REVERT' for e in runs[0]['public_history'])
    # a new report can start right away
    assert client.post('/candidate-runs', json=dict(task_id='Q2', issue='다시 보고')).status_code == 200


def test_only_latest_report_reverts_and_stop_applies_nothing(env):
    client, _ = env
    first = drive(client, client.post('/candidate-runs', json=dict(task_id='Q2', issue='첫 보고')).json())
    stopped = client.post(f"/runs/{first['id']}/stop", json={}).json()
    assert stopped['status'] == 'done' and stopped['termination'] == 'pm_stopped'
    second = drive(client, client.post('/candidate-runs', json=dict(task_id='Q2', issue='둘째 보고')).json())
    assert client.post(f"/runs/{first['id']}/revert-report", json={}).status_code == 409
    assert client.post(f"/runs/{second['id']}/revert-report", json={}).status_code == 200
