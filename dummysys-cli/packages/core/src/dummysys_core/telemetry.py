"""调用内阶段计时；仅在入口启用时收集，不参与事务或写入决策。"""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from time import perf_counter

_current = ContextVar('dmy_trace', default=None)


@contextmanager
def capture():
    stages = {}
    token = _current.set(stages)
    try:
        yield stages
    finally:
        _current.reset(token)


@contextmanager
def span(name):
    stages = _current.get()
    if stages is None:
        yield
        return
    start = perf_counter()
    try:
        yield
    finally:
        value = stages.setdefault(name, {'calls': 0, 'total_ms': 0.0})
        value['calls'] += 1
        value['total_ms'] += (perf_counter() - start) * 1000


def measured(name):
    def decorate(fn):
        @wraps(fn)
        def call(*args, **kwargs):
            with span(name):
                return fn(*args, **kwargs)
        return call
    return decorate
