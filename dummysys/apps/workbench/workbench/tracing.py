"""请求诊断关联；不与业务幂等 request_id 混用。"""
from contextvars import ContextVar
from uuid import uuid4

trace = ContextVar('workbench_trace', default=None)


def current_trace():
    return trace.get() or str(uuid4())
