"""旧 Python 函数与命令兼容；所有写入进入共享协调协议。"""
from __future__ import annotations

import argparse
import inspect
import os
from pathlib import Path
import types

from . import _records, _repositories, _entries, _paths
from .operations import Operations, _external, workspace_lock
from .workspace import Workspace


def _root_for(path):
    path = Path(path).resolve()
    return next(p for p in [path, *path.parents] if (p / 'dmy_vault').is_dir())


def _raw_call(function, root, *args, **kwargs):
    root = Path(root).resolve()
    if _external.get():
        return function(root, *args, **kwargs)
    params = inspect.signature(function).bind(root, *args, **kwargs)
    params.apply_defaults()
    values = dict(params.arguments)
    values.pop('root')
    receipt = Operations(root).execute('legacy.' + function.__name__, values,
        str(values.get('actor') or values.get('owner') or os.environ.get('CODEX_THREAD_ID') or 'legacy'),
        lambda stage: function(stage, *args, **kwargs))
    return receipt['result']


def _wrap(function):
    def wrapped(root, *args, **kwargs):
        return _raw_call(function, root, *args, **kwargs)
    wrapped.__name__ = function.__name__
    wrapped.__doc__ = function.__doc__
    return wrapped


def write_json(path, value):
    root = _root_for(path)
    with workspace_lock(root):
        if _external.get():
            return _records.write_json(path, value)
        relative = Path(path).resolve().relative_to(root)
        Operations(root).execute('legacy.write_json', {'path': str(relative), 'value': value},
            os.environ.get('CODEX_THREAD_ID', 'legacy'), lambda stage: _records.write_json(stage / relative, value))


def set_properties(path, values):
    root = _root_for(path)
    with workspace_lock(root):
        if _external.get():
            return _records.set_properties(path, values)
        relative = Path(path).resolve().relative_to(root)
        Operations(root).execute('legacy.set_properties', {'path': str(relative), 'values': values},
            os.environ.get('CODEX_THREAD_ID', 'legacy'), lambda stage: _records.set_properties(stage / relative, values))


def snapshot(root, task, run_id, actor):
    return Workspace(root).mutate('repo.snapshot', {'task': task, 'run': run_id}, actor=actor,
                                 compatibility=True)['result']


def _sync_main(root):
    parser = argparse.ArgumentParser(description=_entries.__doc__)
    parser.add_argument('--root', type=Path, default=root)
    parser.add_argument('--project')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--apply', action='store_true')
    modes.add_argument('--check', action='store_true')
    args = parser.parse_args()
    ws = Workspace(args.root)
    with workspace_lock(ws.root):
        preview = ws.sync_preview(args.project)
        if args.apply:
            ws.mutate('project.sync', {'project': args.project} if args.project else {},
                      actor=os.environ.get('CODEX_THREAD_ID', 'legacy'), compatibility=True)
        print(f"项目入口：{len(preview['projects'])} 个项目；" + ('已刷新' if args.apply else '待刷新') + f" {len(preview['changed'])} 个文件")
        if args.check and preview['changed']:
            for path in preview['changed']:
                print(f'- {path}')
            return 1
    return 0


def exports(name, root):
    modules = {'task_records': _records, 'repository_records': _repositories,
               'sync_project_entries': _entries, 'project_paths': _paths}
    module = modules[name]
    values = {k: v for k, v in vars(module).items() if not k.startswith('__')}
    values['ROOT'] = Path(root).resolve()
    if name == 'project_paths':
        from .layout import governance_paths
        values['governance_paths'] = governance_paths
    mutations = {'task_records': ['initialize_project', 'refresh', 'create_task', 'update_task', 'create_run', 'update_run'],
                 'repository_records': ['register', 'bind', 'associate']}
    for key in mutations.get(name, []):
        values[key] = _wrap(getattr(module, key))
    if name == 'task_records':
        values.update(write_json=write_json, set_properties=set_properties)
    if name == 'repository_records':
        values['snapshot'] = snapshot
    if name == 'sync_project_entries':
        values['main'] = lambda: _sync_main(values['ROOT'])
    elif hasattr(module, 'main'):
        # 仅旧命令的全局函数映射替换为适配器；原始领域函数保持包内调用。
        values['main'] = types.FunctionType(module.main.__code__, values, 'main', module.main.__defaults__)
    return values
