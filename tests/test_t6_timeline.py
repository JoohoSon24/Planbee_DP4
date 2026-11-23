"""A scenario can receive new, date-specific issues without resetting its board."""
from tests.test_m4_catalog import app_env


def test_t6_multi_day_issues_preserve_previous_agreement(app_env,monkeypatch):
    c,_=app_env;monkeypatch.setenv('PLANBEE_T6_FORCE_AGREE','1')
    c.post('/demo/select',json={'demo':'m4_t6_game_demo'})
    def submit(event_id):
        state=c.get('/state').json()
        event=next(e for e in state['demo']['timeline']['events'] if e['id']==event_id)
        assert event['available'],event
        response=c.post('/candidate-runs',json={'timeline_event_id':event_id,'issue':event['text']})
        assert response.status_code==200,response.text
        r=response.json()
        for _ in range(80):
            if r['status']!='running':break
            r=c.post(f"/runs/{r['id']}/advance",json={}).json()
        assert r['status']=='awaiting_pm_selection',(r.get('termination'),r.get('generation'),r.get('model_error'))
        selected=next(x for x in r['candidates'] if x['id']==r['final_candidates'][0])
        response=c.post(f"/runs/{r['id']}/pm-selection",json={'action':'select','candidate_id':selected['id'],'plan_hash':selected['plan_hash']})
        assert response.status_code==200,response.text
        assert response.json()['termination']=='applied'
        assert c.get('/state').json()['now']==state['now']
    submit('t6_tue_qa')
    after_qa=c.get('/state').json()
    qa_parts={k:v['who'] for k,v in after_qa['tasks'].items() if v['context'].get('partition_of')=='Q2'}
    assert qa_parts
    c.post('/day/next',json={})
    submit('t6_wed_effects')
    state=c.get('/state').json()
    assert state['tasks']['A2']['s']==4
    assert {k:state['tasks'][k]['who'] for k in qa_parts}==qa_parts
    c.post('/day/next',json={})
    submit('t6_thu_build')
    c.post('/day/next',json={})
    submit('t6_fri_build')
    state=c.get('/state').json()
    assert state['now']==4.5 and state['gate']['ok']
    assert len(state['demo']['timeline']['runs'])==4


def test_t6_future_or_edited_dated_issue_is_rejected(app_env):
    c,_=app_env;c.post('/demo/select',json={'demo':'m4_t6_game_demo'})
    state=c.get('/state').json()
    event=next(e for e in state['demo']['timeline']['events'] if e['id']=='t6_wed_menu')
    before=c.get('/board').json()
    assert c.post('/candidate-runs',json={'timeline_event_id':event['id'],'issue':event['text']}).status_code==409
    first=next(e for e in state['demo']['timeline']['events'] if e['available'])
    assert c.post('/candidate-runs',json={'timeline_event_id':first['id'],'issue':'다른 내용'}).status_code==409
    assert c.get('/board').json()==before
