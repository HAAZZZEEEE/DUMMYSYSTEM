"""治理 CLI（dmy）子进程桥。

工作台不直写 Project/Task/Run 记录：所有变更经 dummysys_cli 以子进程执行，
保留其 request_id 幂等、if_version 乐观锁与 Operation 提交流水。
只读仍走 catalog.py 的目录扫描（含孤立 Run、nav_hidden 等导航语义）。

可执行解析顺序（不可调换）：
  1. 环境变量 DMY_EXE —— 显式覆盖，指向运维固定入口 dmy.cmd 等。
  2. <workspace>/runtime/state/workspace/cli-install.json 的登记发行 ——
     Operations.source_commit() 只认登记的 core_path，用别的安装会在每次
     写入时失败 INSTALLATION_CHANGED。
  3. 当前解释器 -m dummysys_cli —— 工作台 venv 内的安装，适用于未登记
     的工作区（source_commit 返回 development-unverified）。
"""
from __future__ import annotations

import json
import os
import subprocess
from .processes import run_background
import sys
import time
from threading import RLock
from .tracing import current_trace
from pathlib import Path

READ_TIMEOUT = 30.0
MUTATE_TIMEOUT = 90.0

# 与 dummysys_core._records 同值；表单下拉与校验用，避免前端硬编码。
TASK_STATUSES = ('active', 'blocked', 'awaiting_acceptance', 'completed', 'cancelled')
RUN_STATUSES = ('planned', 'running', 'completed', 'failed', 'cancelled')
RUN_FINISH_STATUSES = ('completed', 'failed', 'cancelled')
PTR_ORIGINS = ('user', 'agent')

# 工作台已接线的治理动作：action 名 → 后端路由。只列本工作台真正实现的
# 写入路由。能力以 CLI 自述（capabilities）为准，本表是「我已接」。
WORKBENCH_ACTIONS = {
    'project.create': 'ptr/project/create',
    'project.update': 'ptr/project/update',
    'project.rename': 'ptr/project/rename',
    'project.pause': 'ptr/project/pause',
    'project.resume': 'ptr/project/resume',
    'project.archive': 'ptr/project/archive',
    'project.unarchive': 'ptr/project/unarchive',
    'project.delete': 'ptr/project/delete',
    'project.undelete': 'ptr/project/undelete',
    'task.create': 'ptr/task/create',
    'task.update': 'ptr/task/update',
    'task.handoff': 'ptr/task/handoff',
    'task.rename': 'ptr/task/rename',
    'task.move': 'ptr/task/move',
    'task.archive': 'ptr/task/archive',
    'task.unarchive': 'ptr/task/unarchive',
    'task.delete': 'ptr/task/delete',
    'task.undelete': 'ptr/task/undelete',
    'run.create': 'ptr/run/create',
    'run.start': 'ptr/run/start',
    'run.finish': 'ptr/run/finish',
    'run.update': 'ptr/run/update',
    'run.rename': 'ptr/run/rename',
    'run.archive': 'ptr/run/archive',
    'run.unarchive': 'ptr/run/unarchive',
    'run.delete': 'ptr/run/delete',
    'run.undelete': 'ptr/run/undelete',
}

# status 缺失的 reason 类别（前端 tooltip 与禁用项标题用）。
MISSING_REASON = 'dmy 未提供该命令'
REASON_UNWIRED = '工作台未接线该动作'
REASON_TOO_OLD = '当前 dmy 不支持该动作'
REASON_NO_CLI = '无法读取治理 CLI 能力'

# capabilities 拉取缓存：键 = (命令前缀, tool_version, contract_version)，
# 任一变则失效重取。避免每次 /ptr/surface 都起子进程。
_cap_cache: dict[tuple, tuple[float, dict]] = {}
_cap_lock = RLock()


def _identity(path):
    try:
        info=path.stat()
        return str(path), info.st_mtime_ns, info.st_size, info.st_ino
    except OSError:
        return str(path), None


def capabilities(workspace: Path | str, *, runner=None) -> dict | None:
    """同工作区与执行来源复用能力；安装标记变化立即失效，最长缓存 30 秒。"""
    workspace=Path(workspace).resolve()
    command, source=resolve_command(workspace)
    paths=[workspace/'runtime/state/workspace/cli-install.json', Path(command[0])]
    if source == 'registered':
        try:
            manifest=json.loads(paths[0].read_text(encoding='utf-8-sig'))
            paths += [Path(manifest['core_path'])/'dummysys_cli/parser.py']
        except (OSError,ValueError,KeyError):
            pass
    runner_key=(id(getattr(runner,'__self__',None)), id(getattr(runner,'__func__',runner)))
    key=(os.path.normcase(str(workspace)),tuple(command),tuple(_identity(p) for p in paths),runner_key)
    with _cap_lock:
        cached=_cap_cache.get(key)
        if cached and time.monotonic()-cached[0] < 30:
            return cached[1]
        try:
            data=run_dmy(['capabilities'],workspace=workspace,runner=runner)
        except DmyError:
            _cap_cache.pop(key,None)
            return None
        if not isinstance(data,dict) or data.get('contract_version') != 2:
            raise DmyError('INCOMPATIBLE_CLI','治理 CLI 契约版本不支持；请核对配套发行')
        while len(_cap_cache) >= 16:
            _cap_cache.pop(next(iter(_cap_cache)))
        _cap_cache[key]=(time.monotonic(),data)
        return data


def negotiate_surface(cap: dict | None, wired: dict[str, str], *, origins, task_statuses,
                      run_statuses, run_finish_statuses, cli_info, hostname) -> dict:
    """由 CLI 自述 ∩ 已接线路由，推导每个 p/t/r 动作的 status/reason。

    动作集合取两者并集：CLI 有而工作台未接 → missing/未接线；
    工作台声明而 CLI 无（或 CLI 不可读）→ missing/工具版本不支持 或 依赖未就绪。
    """
    cli_actions = (cap or {}).get('actions', {}) or {}
    names = set(cli_actions.keys()) | set(wired.keys())
    names = {n for n in names if n.split('.', 1)[0] in ('project', 'task', 'run')}
    surface = {kind: {} for kind in ('project', 'task', 'run')}
    for action in sorted(names):
        kind, op = action.split('.', 1)
        entry = {'status': 'ready', 'route': wired.get(action), 'dmy': f'{kind} {op}'}
        if cap is None:
            entry.update(status='missing', reason=REASON_NO_CLI)
        elif action not in cli_actions:
            entry.update(status='missing', reason=REASON_TOO_OLD)
        elif action not in wired:
            entry.update(status='missing', reason=REASON_UNWIRED)
        surface[kind][op] = entry
    declared=(cap or {}).get('statuses', {})
    surface.update({
        'cli': cli_info,
        'origins': list(declared.get('origins', origins)),
        'task_statuses': list(declared.get('task', task_statuses)),
        'run_statuses': list(declared.get('run', run_statuses)),
        'run_finish_statuses': list(declared.get('run_finish', run_finish_statuses)),
        'hostname': hostname,
        'transitions': (cap or {}).get('transitions', {}),
        'error_codes': (cap or {}).get('error_codes', []),
        'contract_version': (cap or {}).get('contract_version'),
        'tool_version': (cap or {}).get('version'),
    })
    return surface

# dmy error.code → HTTP 状态；未列出的按 500 处理。
ERROR_STATUS = {
    'INCOMPATIBLE_CLI': 409,
    'NOT_FOUND': 404,
    'FORBIDDEN': 403,
    'OWNER_CONFLICT': 403,
    'SCOPE_VIOLATION': 403,
    'PATH_OUTSIDE_ROOT': 403,
    'INVALID_ARGUMENT': 400,
    'ACTOR_REQUIRED': 400,
    'REQUEST_REQUIRED': 400,
    'VERSION_REQUIRED': 400,
    'INVALID_STATE': 409,
    'VERSION_CONFLICT': 409,
    'REQUEST_CONFLICT': 409,
    'STATE_CONFLICT': 409,
    'PLAN_CONFLICT': 409,
    'REPOSITORY_SCOPE_CONFLICT': 409,
    'LOCK_FAILED': 409,
    'RECOVERY_REQUIRED': 409,
    'RECOVERY_CONFLICT': 409,
    'INCOMPATIBLE_OPERATION': 409,
    'INSTALLATION_CHANGED': 409,
    'RESULT_UNKNOWN': 202,
    'CAPABILITY_UNAVAILABLE': 501,
    'CONFIG_REQUIRED': 500,
    'INVALID_CONFIG': 500,
    'INVALID_WORKSPACE': 500,
    'CLI_UNAVAILABLE': 502,
    'DMY_BAD_OUTPUT': 502,
}


class DmyError(Exception):
    """dmy 子进程失败。code 与 dmy 的 error.code 同名，直接透传给前端。"""

    def __init__(self, code: str, message: str, details: dict | None = None,
                 next_action: str | None = None):
        super().__init__(message)
        self.code = code
        self.status = ERROR_STATUS.get(code, 500)
        self.details = details or {}
        self.next_action = next_action


def resolve_command(workspace: Path | str) -> tuple[list[str], str]:
    """返回 (命令前缀, 来源)。来源 ∈ {env, registered, venv}。"""
    override = os.environ.get('DMY_EXE', '').strip()
    if override:
        return override.split(), 'env'
    manifest = Path(workspace) / 'runtime' / 'state' / 'workspace' / 'cli-install.json'
    if manifest.is_file():
        try:
            installed = json.loads(manifest.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            installed = {}
        python = installed.get('python')
        if python and Path(python).is_file():
            return [python, '-X', 'utf8', '-m', 'dummysys_cli'], 'registered'
    return [sys.executable, '-X', 'utf8', '-m', 'dummysys_cli'], 'venv'


def describe_cli(workspace: Path | str) -> dict:
    """供设置/诊断展示：实际会用哪份 CLI。"""
    command, source = resolve_command(workspace)
    registered = None
    manifest = Path(workspace) / 'runtime' / 'state' / 'workspace' / 'cli-install.json'
    if manifest.is_file():
        try:
            installed = json.loads(manifest.read_text(encoding='utf-8-sig'))
            registered = {'version': installed.get('version'),
                          'source_commit': installed.get('source_commit'),
                          'python': installed.get('python')}
        except (OSError, ValueError):
            registered = None
    return {'command': command, 'source': source, 'registered': registered,
            'note': '登记工作区只认 cli-install.json 的发行；DMY_EXE 覆盖后若写入报 '
                    'INSTALLATION_CHANGED，请改回登记入口或重新登记。'}


def run_dmy(argv: list[str], *, workspace: Path | str,
            actor: str | None = None, request_id: str | None = None,
            if_version: str | None = None, mutating: bool = False,
            timeout: float | None = None, runner=None) -> dict:
    """执行一条 dmy 命令并返回其 data。失败抛 DmyError。"""
    command, _source = resolve_command(workspace)
    full = [*command, '--json', '--workspace', str(workspace)]
    if actor:
        full += ['--actor', actor]
    if request_id:
        full += ['--request-id', request_id]
    if if_version is not None:
        full += ['--if-version', str(if_version)]
    full += list(argv)

    if runner is None:
        runner = run_background
    limit = timeout if timeout is not None else (MUTATE_TIMEOUT if mutating else READ_TIMEOUT)
    try:
        env=dict(os.environ, DMY_CALL_SOURCE='workbench', DMY_TRACE_ID=current_trace())
        completed = runner(full, capture_output=True, encoding='utf-8', errors='replace', env=env,
                           timeout=limit, cwd=str(workspace))
    except FileNotFoundError as error:
        raise DmyError('CLI_UNAVAILABLE', f'找不到治理 CLI：{error}',
                       next_action='安装 dummysys-cli 到工作台 venv，或设 DMY_EXE 指向登记入口') from error
    except subprocess.TimeoutExpired as error:
        raise DmyError('RESULT_UNKNOWN', f'治理 CLI 超时（{limit:.0f}s），结果未知',
                       next_action='稍候用「确认结果」查 operation，或直接重试（request_id 幂等）') from error
    except OSError as error:
        raise DmyError('CLI_UNAVAILABLE', f'无法启动治理 CLI：{error}') from error

    stdout = completed.stdout or ''
    try:
        payload = json.loads(stdout)
    except ValueError as error:
        raise DmyError('DMY_BAD_OUTPUT',
                       f'治理 CLI 输出不是 JSON（退出码 {completed.returncode}）',
                       details={'stdout_length':len(stdout), 'stderr_length':len(completed.stderr or '')}) from error
    if not isinstance(payload, dict):
        raise DmyError('DMY_BAD_OUTPUT', '治理 CLI 输出格式错误')
    if payload.get('schema_version') != 1:
        raise DmyError('INCOMPATIBLE_CLI','治理 CLI JSON schema_version 不支持')
    if 'error' in payload and isinstance(payload['error'], dict):
        failure = payload['error']
        code = failure.get('code') or 'INVALID_STATE'
        raise DmyError(code, failure.get('message') or '治理操作失败',
                       details={**(failure.get('details') or {}),
                                'diagnostic_id':payload.get('diagnostic_id'), 'trace_id':payload.get('trace_id'),
                                'retry':failure.get('retry')}, next_action=failure.get('next_action'))
    if completed.returncode not in (0, 1):
        # dmy 用退出码 1 表示业务 ok:false，其余非零视为工具失败。
        raise DmyError('DMY_BAD_OUTPUT', f'治理 CLI 异常退出（{completed.returncode}）',
                       details={'stderr_length':len(completed.stderr or '')})
    return payload.get('data')
