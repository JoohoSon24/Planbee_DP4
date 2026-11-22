"""Request-local budget; every Live HTTP attempt consumes the persistent run cap."""
from contextvars import ContextVar
from contextlib import contextmanager

_current = ContextVar('negotiation_budget', default=None)


class CallBudgetExceeded(RuntimeError):
    pass


def consume():
    budget = _current.get()
    if budget is None:
        return
    if budget['used'] >= budget['max']:
        raise CallBudgetExceeded('max_llm_calls')
    budget['used'] += 1


@contextmanager
def bound(budget):
    token = _current.set(budget)
    try:
        yield
    finally:
        _current.reset(token)
