"""一次读取请求内复用元数据；请求结束即丢弃，外部编辑下一请求可见。"""
from contextlib import contextmanager
from contextvars import ContextVar
import json
import yaml
from dummysys_core.operations import native_path

_active=ContextVar('metadata_reads', default=None)


@contextmanager
def reading():
    if _active.get() is not None:
        yield
        return
    token=_active.set({})
    try:
        yield
    finally:
        _active.reset(token)


def _memo(kind,path,load):
    cache=_active.get()
    if cache is None: return load()
    key=(kind,str(path))
    if key not in cache: cache[key]=load()
    return cache[key]


def read_json(path,error):
    def load():
        try: return json.loads(native_path(path).read_text(encoding='utf-8'))
        except (OSError,ValueError) as exc: raise error(f'无法读取 JSON {path}：{exc}') from exc
    return _memo('json',path,load)


def frontmatter(path,error):
    def load():
        with native_path(path).open(encoding='utf-8-sig') as stream:
            if stream.readline().strip() != '---': return {}
            lines=[]
            for line in stream:
                if line.rstrip() == '---': break
                lines.append(line)
            else: raise error(f'Properties 解析失败 {path}：缺少结束标记')
        try: value=yaml.safe_load(''.join(lines))
        except yaml.YAMLError as exc: raise error(f'Properties 解析失败 {path}：{exc}') from exc
        if not isinstance(value,dict): raise error(f'Properties 解析失败 {path}：必须是映射')
        return value
    return _memo('properties',path,load)
