"""Ephemeral public progress for the local single-process demo server.

Authoritative history remains the persisted Run; no cards, prompts or proposals here.
"""
from copy import deepcopy
from threading import Lock

_lock=Lock()
_state=None


def publish(run, stage, demo, round=None, status=None):
    global _state
    with _lock:
        _state=dict(demo=demo,run_id=run.id,current=dict(stage),status=status or run.status,demo_step=run.ctx.get('demo_step'),
                    round=run.ctx.get('round',0) if round is None else round)


def read(demo):
    with _lock:
        return deepcopy(_state) if _state and _state['demo']==demo else None


def clear():
    global _state
    with _lock:
        _state=None
