"""DUMMYSYS Windows 治理命令；上下文查询不替代 AGENTS.md。"""
from __future__ import annotations

import argparse
from time import perf_counter
from uuid import uuid4
import json
import os
from pathlib import Path
import sys
import sqlite3

from . import usage, diagnostics
from .parser import Parser, argument, build_parser, capabilities, command_path
from dummysys_core import contracts
from dummysys_core.telemetry import capture, measured

from dummysys_core import __version__, _repositories as repos, _records as records
from dummysys_core.operations import GovernanceError, workspace_lock
from dummysys_core.workspace import Workspace



def configured_workspace(explicit=None, config=None):
    if explicit:
        return Path(explicit)
    selected = config or os.environ.get('DMY_CONFIG')
    if not selected:
        raise GovernanceError('CONFIG_REQUIRED', '指定 --workspace、--config 或 DMY_CONFIG；不读取全局安装配置')
    config = Path(selected)
    if not config.is_file():
        raise GovernanceError('CONFIG_REQUIRED', '指定 --workspace 或安装本机 CLI 配置', config=str(config))
    value = json.loads(config.read_text(encoding='utf-8-sig'))
    if value.get('schema_version') != 1 or not Path(value.get('workspace', '')).is_absolute():
        raise GovernanceError('INVALID_CONFIG', 'CLI 配置格式错误', config=str(config))
    return Path(value['workspace'])


@measured('dispatch')
def dispatch(ws, args, global_args):
    p = vars(args).copy()
    group, command = p.pop('group'), p.pop('command', None)
    if group == 'context':
        value=ws.context(p['task'])
        section=p['section']
        if section == 'all': return value
        if section == 'summary': return {k:v for k,v in value.items() if k not in ('reading','repositories','task')} | {'task':{k:value['task'].get(k) for k in ('task_id','status','owner','version','document')}}
        return {section:value[section], 'queried_at':value['queried_at'], 'coverage':value['coverage'], 'missing':value['missing']}
    if group == 'doctor':
        from .health import doctor
        return doctor(ws, full=p['full'])
    if group == 'check':
        from .doccheck import check_docs
        return check_docs(ws.root) if p['docs'] else ws.check()
    if group == 'diagnose':
        return diagnostics.show(ws.root, p['id'])
    if group == 'project':
        if command == 'list': return ws.projects()
        if command == 'show': return ws.project(p['id'])
        if command == 'sync':
            if not p.pop('apply', False): return ws.sync_preview(p.get('project'))
        elif command != 'sync':
            pass  # 新命令落入 mutate
    if group == 'task':
        if command == 'list': return ws.tasks(p.get('project'))
        if command == 'show': return ws.task(p['id'])
    if group == 'run':
        if command == 'list': return ws.runs(p['task'])
        if command == 'show': return ws.run(p['task'], p['id'])
        if 'execution_command' in p:
            val = p.pop('execution_command')
            if val is not None: p['command'] = val
    if group == 'repo':
        if command == 'list': return repos.catalog(ws.root)
        if command == 'show':
            value = repos.catalog(ws.root).get(p['id'])
            if value is None: raise GovernanceError('NOT_FOUND', 'Repo 未登记')
            return dict(value, checkout=repos.mappings(ws.root)['checkouts'].get(p['id']), version=ws.version('repo', p['id']))
        if command == 'resolve':
            return repos.resolve(ws.root, ws.project_name(p['project']) if p.get('project') else None, p.get('task'))
        if 'subpath' in p: p['subpaths'] = p.pop('subpath') or ['.']
        if 'checkout' in p:
            overrides = {}
            for entry in p.pop('checkout') or []:
                key, sep, path = entry.partition('=')
                if not sep or key in overrides: raise GovernanceError('INVALID_ARGUMENT', 'checkout 格式为唯一 repo_id=绝对路径')
                overrides[key] = path
            p['checkouts'] = overrides
    if group == 'scope':
        _, resource, _ = records.locate_task(ws.root, p['task'])
        return records.scope_report(records.read_json(resource / 'task.json')['scope'], p['read_path'], p['write_path'])
    if group == 'operation':
        if command == 'list': return ws.operations.list()
        if command == 'show': return ws.operations.show(p['id'])
        return ws.operations.recover(p['id'])
    for old, new in [('read_path', 'read_paths'), ('write_path', 'write_paths')]:
        if old in p:
            value = p.pop(old)
            if value is not None: p[new] = value
            if p.pop('clear_' + new, False): p[new] = []
    if p.get('remote_resources') is not None:
        p['remote_resources'] = json.loads(p['remote_resources'])
    if p.get('aliases') is not None:
        p['aliases'] = json.loads(p['aliases']) if isinstance(p['aliases'], str) else p['aliases']
    dry_run = p.pop('dry_run', False)
    if_plan = p.pop('if_plan', None)
    p = {k: v for k, v in p.items() if v is not None}
    actor = global_args.actor or os.environ.get('CODEX_THREAD_ID')
    if not actor: raise GovernanceError('ACTOR_REQUIRED', '写操作需要 --actor 或实际 CODEX_THREAD_ID')
    action_name = group + '.' + command
    if dry_run:
        return ws.plan(action_name, p, actor=actor)
    return ws.mutate(action_name, p, actor=actor,
                     request_id=global_args.request_id, if_version=global_args.if_version,
                     if_plan=if_plan)


def main(argv=None):
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'): stream.reconfigure(encoding='utf-8')
    with capture() as stages:
        return _main(argv, stages)


def _main(argv, stages):
    started=perf_counter()
    diagnostic_id=str(uuid4())
    trace_id=diagnostic_id
    argv = list(sys.argv[1:] if argv is None else argv)
    globals_parser = Parser(add_help=False)
    for name in ('workspace', 'config', 'actor', 'request_id', 'if_version', 'trace_id'):
        argument(globals_parser, name)
    argument(globals_parser, 'json', action='store_true')
    json_output = '--json' in argv
    args = argparse.Namespace()
    usage_root = None
    code = 2
    recognized_command = None
    try:
        global_args, remaining = globals_parser.parse_known_args(argv)
        try:
            candidate = configured_workspace(global_args.workspace, global_args.config).resolve() if remaining[:1] != ['init'] else None
            if candidate is not None and (candidate / 'dmy_vault').is_dir():
                usage_root = candidate
        except (ValueError, KeyError, OSError):
            pass
        trace_id=diagnostics.validate_id(global_args.trace_id or os.environ.get('DMY_TRACE_ID') or diagnostic_id)
        parser = build_parser()
        recognized_command = command_path(parser, remaining)
        args = parser.parse_args(remaining, namespace=args)
        if args.group == 'capabilities':
            data = capabilities(parser, args.query_command, args.query_action)
        elif args.group == 'init':
            if not global_args.workspace:
                raise GovernanceError('INVALID_ARGUMENT', 'init 必须显式提供 --workspace 绝对路径')
            from dummysys_core.initialize import initialize
            data = initialize(global_args.workspace)
        elif args.group == 'stats':
            if args.days is not None and args.days < 1:
                raise ValueError('--days 必须大于 0')
            data = usage.summary(configured_workspace(global_args.workspace, global_args.config), args.days)
        else:
            ws = Workspace(configured_workspace(global_args.workspace, global_args.config))
            # 写操作自行加锁；读取也在同一互斥范围内获得一致快照。
            mutating = args.group in ('task', 'run', 'repo') and args.command not in ('list', 'show', 'resolve')
            mutating = mutating or args.group == 'project' and args.command == 'sync' and args.apply
            mutating = mutating or args.group == 'operation' and args.command == 'recover'
            if mutating:
                data = dispatch(ws, args, global_args)
            else:
                with workspace_lock(ws.root):
                    data = dispatch(ws, args, global_args)
        result = dict(schema_version=1, tool_version=__version__, data=data, diagnostic_id=diagnostic_id, trace_id=trace_id)
        code = 1 if isinstance(data, dict) and data.get('ok') is False else 0
    except (GovernanceError, ValueError, KeyError, OSError, sqlite3.Error) as error:
        code = 2
        error_code=getattr(error, 'code', 'INVALID_STATE')
        details=getattr(error, 'details', {})
        policy=contracts.error_policy(error_code)
        result = dict(schema_version=1, tool_version=__version__, diagnostic_id=diagnostic_id, trace_id=trace_id,
                      error=dict(code=error_code, message=str(error), details=details,
                                 retry=policy['retry'], next_action=details.get('next_action') or policy['next_action']))
    except Exception as error:
        code=2
        result=dict(schema_version=1, tool_version=__version__, diagnostic_id=diagnostic_id, trace_id=trace_id,
                    error=dict(code='INTERNAL_ERROR', message='内部错误：'+type(error).__name__, retry='stop',
                               next_action='使用 dmy diagnose show 查询本次诊断编号'))
    finally:
        group = getattr(args, 'group', None)
        command = getattr(args, 'command', None)
        # help 不计数；未知命令、无法定位工作区的调用不归属任何工作区。
        if usage_root is not None and recognized_command and not recognized_command.startswith(('dmy stats','dmy diagnose')) and not any(a in ('-h', '--help') for a in argv):
            name = recognized_command
            error_code=result.get('error', {}).get('code')
            source=os.environ.get('DMY_CALL_SOURCE','cli')
            source=source if source in ('cli','workbench','legacy') else 'cli'
            duration=(perf_counter()-started)*1000
            try:
                usage.record(usage_root,name,code,duration_ms=duration,error_code=error_code,source=source)
            except (OSError,sqlite3.Error):
                print('提示：本次调用统计未写入，命令结果不受影响。',file=sys.stderr)
            try:
                data=result.get('data') or {}
                operation_id=data.get('operation_id') if isinstance(data,dict) else None
                if not operation_id and global_args.request_id:
                    from dummysys_core.operations import digest
                    operation_id=digest(global_args.request_id.encode())
                diagnostics.save(usage_root,diagnostic_id=diagnostic_id,trace_id=trace_id,
                    command=name,code=code,outcome=usage.classify(code,error_code),error_code=error_code,
                    duration_ms=duration,source=source,stages=stages,operation_id=operation_id)
                result['diagnostic_persisted']=True
            except OSError:
                print('提示：本次详细诊断未写入，命令结果不受影响。',file=sys.stderr)
    result.setdefault('diagnostic_persisted',False)
    if json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif 'error' in result:
        print(f"错误 [{result['error']['code']}]：{result['error']['message']}", file=sys.stderr)
    else:
        print(json.dumps(result['data'], ensure_ascii=False, indent=2))
    return code


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
