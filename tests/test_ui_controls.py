"""Demo controls preserve assignments and PM acknowledgement is retry-safe."""
from copy import deepcopy
from tests.test_m4_catalog import app_env
from app.models import Task


def test_day_previous_restores_completed_tasks_without_losing_logs(app_env):
    c,_=app_env
    before=c.get('/state').json()
    assert not before['can_previous_day']
    assert c.post('/day/next',json={}).status_code==200
    assert c.get('/state').json()['can_previous_day']
    response=c.post('/day/previous',json={})
    assert response.status_code==200,response.text
    after=c.get('/state').json()
    assert after['now']==before['now']
    assert after['tasks']==before['tasks']
    assert not after['can_previous_day']
    assert c.post('/day/previous',json={}).status_code==409


def test_day_previous_blocks_overwriting_new_work(app_env):
    c,f=app_env
    c.post('/day/next',json={})
    with f() as db:
        db.get(Task,'polish').d+=.5;db.commit()
    before=deepcopy(c.get('/board').json())
    assert c.post('/day/previous',json={}).status_code==409
    assert c.get('/board').json()==before
    c.post('/demo/select',json={'demo':'m4_t6_game_demo'})
    assert not c.get('/state').json()['can_previous_day']


def test_t5_pm_acknowledgement_is_idempotent(app_env):
    from app import store
    c,_=app_env
    c.post('/demo/select',json={'demo':'m4_t5_infeasible'})
    issue=store.load_yaml('feed.yaml')['issue']
    r=c.post('/candidate-runs',json={'issue':issue['records'][0]['text']}).json()
    for _ in range(80):
        if r['status']!='running':break
        r=c.post(f"/runs/{r['id']}/advance",json={}).json()
    assert r['status']=='waiting_pm'
    before=c.get('/board').json()
    for _ in range(2):
        response=c.post(f"/runs/{r['id']}/close",json={},headers={'X-Planbee-Role':'pm'})
        assert response.status_code==200,response.text
        assert response.json()['status']=='done'
    assert c.get('/board').json()==before


def test_full_display_translation_is_cached_and_requires_english(app_env,monkeypatch):
    from app import translations,llm
    from collections import OrderedDict
    c,_=app_env
    class Translator(llm.LiveLLM):
        def __init__(self):self.calls=0
        def _ask(self,schema,instruction,facts,model=None):
            self.calls+=1
            assert set(facts)=={'target_language','messages'}
            return translations.TranslationBatch(translations=[translations.Translation(id=x['id'],text='English interface text') for x in facts['messages']])
    adapter=Translator()
    monkeypatch.setattr(translations,'get_llm',lambda:adapter)
    monkeypatch.setattr(translations,'_cache',OrderedDict())
    monkeypatch.setattr(translations,'_attempts',OrderedDict())
    before=c.get('/board').json()
    body={'texts':['업무 상세','본인 확인 필요']}
    first=c.post('/display-translations',json=body)
    assert first.status_code==200,first.text
    assert all(x['text']=='English interface text' for x in first.json()['items'])
    assert c.post('/display-translations',json=body).json()==first.json()
    assert adapter.calls==1 and c.get('/board').json()==before
    assert c.post('/display-translations',json={'texts':['x']*25}).status_code==422
    assert c.post('/display-translations',json={'texts':['x','x']}).status_code==409


def test_full_display_translation_rejects_korean_output(app_env,monkeypatch):
    from app import translations,llm
    from collections import OrderedDict
    c,_=app_env
    class Translator(llm.LiveLLM):
        def __init__(self):pass
        def _ask(self,schema,instruction,facts,model=None):
            return translations.TranslationBatch(translations=[translations.Translation(id=x['id'],text='아직 한국어') for x in facts['messages']])
    monkeypatch.setattr(translations,'get_llm',lambda:Translator())
    monkeypatch.setattr(translations,'_cache',OrderedDict())
    monkeypatch.setattr(translations,'_attempts',OrderedDict())
    assert c.post('/display-translations',json={'texts':['새 한국어 문구']}).status_code==409
