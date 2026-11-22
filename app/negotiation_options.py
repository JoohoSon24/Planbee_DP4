"""Public schedule-only workload patterns, never a choice or an agreement.

The model must define real disjoint deliverables and dependencies, then Hive
validates that actual proposal again. These optimistic independent patterns do
not imply that a task can in fact be decomposed this way.
"""
from itertools import combinations, product
from . import hive


def patterns(b,ctx,limits=None):
    from .discussion import preview
    source=b.tasks[ctx['task']]
    if (source.context or {}).get('splittable_hint') is False:return []
    peers=[p.id for p in b.people.values() if p.role==source.role and p.id!=source.who]
    keep=(ctx.get('split',{}).get('keep') or {}).get('days') or .5
    found=[]
    # Spread the budget across recipient combinations rather than returning only
    # many near-identical solutions for the first recipient. No private cards.
    for count in (1,2):
        for recipients in combinations(peers,count):
            local=[]
            for amounts in product((.25,.5,.75,1),repeat=count):
                retained=round(source.d-sum(amounts),8)
                if retained<keep-hive.EPS:continue
                allocation=[dict(who=source.who,effort=retained,days=retained)]
                allocation += [dict(who=pid,effort=n,days=n*hive.factor(b.people[pid],source.tag)/hive.factor(b.people[source.who],source.tag)) for pid,n in zip(recipients,amounts)]
                if any(a['who'] in (limits or {}) and a['who']!=source.who and a['days']>limits[a['who']]+hive.EPS for a in allocation):continue
                probe=[dict(**a,title=f'범위 {i}',what=f'미확정 독립 산출물 {i}',key=f'unit_{i}') for i,a in enumerate(allocation)]
                try:preview(b,ctx,probe,'whole_task')
                except (ValueError,KeyError,TypeError):continue
                local.append(allocation)
            # Small, medium and large numeric examples per combination.
            if local:
                for i in sorted({0,len(local)//2,len(local)-1}):found.append(local[i])
    return found[:24]
