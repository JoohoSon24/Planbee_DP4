"""K3: when no plan satisfies the rules, show the PM which rule to relax.

A Task contract may list `relaxations`: named rule changes with an explicit patch and who may
authorise them. Hive applies each patch to a copy of the board and runs the same deterministic
plan search, so the PM sees how many valid plans each relaxation would unlock. Nothing is
applied until the PM grants one; then the patch is written to the board and planning restarts.
"""
from copy import deepcopy
from types import SimpleNamespace as NS
from .. import hive

PATCH_TASK_FIELDS = ('s0', 'd', 'cut', 'who')


def apply_to_board(b, patch):
    """Apply a relaxation patch to an in-memory board (a clone). Returns the board."""
    for tid, change in (patch.get('tasks') or {}).items():
        t = b.tasks[tid]
        for field in PATCH_TASK_FIELDS:
            if field in change:
                setattr(t, field, change[field])
        if change.get('context'):
            t.context = {**deepcopy(t.context or {}), **deepcopy(change['context'])}
    for hid, change in (patch.get('handoffs') or {}).items():
        if 't' in change:
            b.hands[hid].t = float(change['t'])
    for pid, change in (patch.get('people') or {}).items():
        if 'unavailable' in change:
            policy = b.extra.setdefault('policies', {}).setdefault(pid, {})
            policy.update(approved=True, unavailable=deepcopy(change['unavailable']))
    hive.schedule(b)
    return b


def options(b, ctx, settings):
    """Evaluate every declared relaxation of the issue task on a clone of the board."""
    from .generator import enumerate_plans
    source = b.tasks[ctx['task']]
    out = []
    for r in (source.context or {}).get('relaxations', []):
        clone = apply_to_board(b.clone(), r.get('patch') or {})
        clone.people = b.people
        try:
            found, stats = enumerate_plans(clone, ctx, [], settings)
        except (ValueError, KeyError, TypeError) as exc:
            found, stats = [], dict(feasible=0, error=str(exc))
        gate = hive.gate(clone)
        out.append(dict(id=r['id'], label=r['label'], rule=r.get('rule', ''), authorizer=r.get('authorizer', 'pm'),
                        feasible=stats.get('feasible', 0),
                        baseline_ok=gate['ok'],
                        example=(dict(id=found[0]['id'], title=found[0]['title'], affected=found[0]['affected'])
                                 if found else None),
                        remaining=[v['text'] for v in (gate['violations'] + gate['warnings'])][:4] if not found else []))
    # Fewest rules first is implicit (one rule each); order by unlocked plans, PM-authorised first.
    out.sort(key=lambda o: (o['feasible'] == 0, o['authorizer'] != 'pm', -o['feasible'], o['id']))
    return out


def persist(db, b, patch):
    """Write a granted patch to the stored board (DB rows). Caller commits."""
    from .. import store
    for tid, change in (patch.get('tasks') or {}).items():
        row = b.tasks[tid]
        for field in PATCH_TASK_FIELDS:
            if field in change:
                setattr(row, field, change[field])
        if change.get('context'):
            row.context = {**deepcopy(row.context or {}), **deepcopy(change['context'])}
    for hid, change in (patch.get('handoffs') or {}).items():
        if 't' in change:
            b.hands[hid].t = float(change['t'])
    for pid, change in (patch.get('people') or {}).items():
        if 'unavailable' in change:
            card = store.card(db, pid)
            card.policy = {**deepcopy(card.policy or {}), 'approved': True, 'unavailable': deepcopy(change['unavailable'])}
    db.flush()
