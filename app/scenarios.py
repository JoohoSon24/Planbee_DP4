"""Read-only seed visualization; never reset or switch the active demo."""
from types import SimpleNamespace as NS
import yaml
from . import store, hive


def initial(demo):
    if demo not in store.demos():raise ValueError('없는 데모')
    root=store.SEED/demo
    data=yaml.safe_load((root/'team.yaml').read_text())
    feeds=yaml.safe_load((root/'feed.yaml').read_text()) or {}
    rules={r['key']:r['value'] for r in data.get('rules',[])}
    people={p['id']:NS(**p) for p in data['people']}
    cards={c['who']:c for c in data.get('cards',[])}
    tasks={t['id']:NS(**{**dict(kind='',cut=False,context={},oi=i,s=t['s0']),**t}) for i,t in enumerate(data['tasks'])}
    hands={h['id']:NS(**{**dict(done=False,prop=False,agreed=False,basis='',oi=i),**h,
        'from_task':h['from'],'to_task':h['to']}) for i,h in enumerate(data['handoffs'])}
    b=hive.Board(people,tasks,hands,cap=rules.get('weekly_cap',{}).get('days',5),
        week_end=rules.get('deadline',{}).get('week_end',5),now=data.get('meta',{}).get('now',0),
        extra={'policies':{pid:cards.get(pid,{}).get('policy',{}) for pid in people}})
    hive.schedule(b)
    return dict(id=demo,meta=data.get('meta',{}),week_end=b.week_end,
        people=[dict(**p,card=cards.get(p['id'],{}),load=hive.load_of(b,p['id']),capacity=hive.capacity(b,p['id'])) for p in data['people']],
        tasks=[dict(**{**t,'context':t.get('context',{})},start=tasks[t['id']].s,end=tasks[t['id']].s+t['d'],start_label=hive.when(tasks[t['id']].s),end_label=hive.when(tasks[t['id']].s+t['d'])) for t in data['tasks']],
        handoffs=[dict(**h,from_task=h['from'],to_task=h['to'],expected=hive.pred(b,hands[h['id']]),deadline_label=hive.when(h['t']),state=hive.h_state(b,hands[h['id']])) for h in data['handoffs']],
        steps=[dict(id=k,**v) for k,v in feeds.items()],gate=hive.gate(b))
