"""应用层：目录与打开规则的编排。

组合 Catalog（定位）与 Opener（打开），提供动作解析、打开发起、偏好读写。
打开接口注入 opener 适配器：生产实现真正打开应用；测试实现只记录动作和目标。
"""
from __future__ import annotations

import os
import time
import threading
from concurrent.futures import Future
from pathlib import Path
from .governance import GovernanceGateway

from .catalog import (
    BlockedLink,
    Catalog,
    CatalogError,
    InvalidTarget,
    PathOutsideRoot,
    ProjectNotFound,
    RootNotFound,
    StaleCursor,
    TargetNotFound,
    TargetForbidden,
)
from .ports import AppUnavailable, OpenFailed
from .action_policy import SCRIPT_EXTENSIONS
from .preferences import Preferences
from . import dmy

# 固定动作标识
ACTION_OBSIDIAN = "obsidian_open"
ACTION_VSCODE = "vscode_open"
ACTION_EXPLORER = "explorer_open"
ACTION_REVEAL = "explorer_reveal"
ACTION_SYSTEM = "system_open"

MARKDOWN_EXTENSIONS = {".md", ".markdown", ".mdown"}
MAX_READ_BYTES = 2 * 1024 * 1024


def _text(value, label: str, required: bool = True) -> str:
    if value is None and not required:
        return ''
    if not isinstance(value, str) or (required and not value.strip()):
        raise InvalidTarget(f'{label} 必须是非空文本')
    if any(ord(c) < 32 for c in value):
        raise InvalidTarget(f'{label} 不能包含控制字符')
    return value.strip() if required else value


def _choice(value, label: str, allowed) -> str:
    text = _text(value, label)
    if text not in set(allowed):
        raise InvalidTarget(f'{label} 必须是 {"、".join(allowed)} 之一')
    return text


def _text_list(value, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise InvalidTarget(f'{label} 必须是列表')
    return [_text(item, label) for item in value]


def _integer(value, label: str) -> int:
    if type(value) is not int:
        raise InvalidTarget(f'{label} 必须是整数')
    return value


def _json_array(value, label: str) -> str:
    import json
    if not isinstance(value, list):
        raise InvalidTarget(f'{label} 必须是列表')
    return json.dumps(value, ensure_ascii=False)

# 打开规则：默认动作与可用动作
CODE_EXTENSIONS = {
    ".py", ".pyw", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".conf", ".txt", ".log", ".sh", ".bat", ".cmd",
    ".ps1", ".sql", ".c", ".h", ".cpp", ".hpp", ".java", ".go", ".rs",
    ".css", ".xml", ".csv", ".tsv", ".mdx",
}
DOCUMENT_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp"}
MEDIA_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp", ".ico",
                    ".mp3", ".wav", ".mp4", ".mkv", ".webm", ".mov", ".avi", ".flac"}


class OpenRequest:
    """一次打开请求；记录 request_id 用于防重。"""

    def __init__(self, fingerprint: tuple, created: float):
        self.fingerprint = fingerprint
        self.future = Future()
        self.created = created


class Application:
    def __init__(self, catalog: Catalog, opener, dmy_runner=None):
        self.catalog = catalog
        self.opener = opener
        self._dmy_runner = dmy_runner
        self._preferences_path: Path | None = None
        self._open_log: dict[str, OpenRequest] = {}
        self._open_log_ttl = 30.0
        self._open_lock = threading.Lock()
        self._preferences = None
        from .storage import StorageMonitor
        self.storage = StorageMonitor(self.catalog.workspace_root,
                                      projects=lambda: self.catalog.list_projects(include_archived=True))
        self._governance = GovernanceGateway(
            lambda: self.load_preferences(),
            lambda argv, **kw: dmy.run_dmy(argv,workspace=self.catalog.workspace_root,runner=self._dmy_runner,**kw),
            lambda: self.catalog.refresh())

    # ---- 偏好 ----
    def set_preferences_path(self, path: str | Path) -> None:
        self._preferences_path = Path(path)
        self._preferences = Preferences(self._preferences_path)

    def load_preferences(self) -> dict:
        return self._preferences.read() if self._preferences else Preferences.defaults()

    def save_preferences(self, preferences: dict, expected_revision: str | None = None) -> dict:
        if self._preferences is None:
            raise CatalogError("偏好路径未配置")
        if isinstance(preferences, dict) and preferences.get('last_location') is not None:
            self._target(preferences['last_location'])
            location = preferences['last_location']
            if location.get('root_id') == 'homepage':
                from .homepage import Homepage
                if location.get('relative_path') or not Homepage(self.catalog).describe(location['project_id']):
                    raise InvalidTarget('首页位置无效')
            else:
                self.catalog.resolve_target(location)
        return self._preferences.patch(preferences, expected_revision)

    # ---- 项目与目录 ----
    def list_projects(self, query: str | None = None, include_archived: bool = False) -> dict:
        return self.catalog.list_projects(query, include_archived)

    def refresh(self) -> dict:
        self.catalog.refresh()
        return self.catalog.list_projects()

    def list_roots(self, project_id: str) -> dict:
        from .homepage import Homepage
        return {**self.catalog.list_roots(project_id),
                'homepage': Homepage(self.catalog).describe(project_id)}

    def project_nav(self, project_id: str) -> dict:
        return self.catalog.list_project_nav(project_id)

    def list_deleted(self) -> dict:
        return self.catalog.list_deleted()

    def search(self, query: str | None = None, types: list[str] | None = None,
               project_id: str | None = None) -> dict:
        return self.catalog.search(query, types, project_id)

    # ---- 治理读写（一律经 dmy 子进程，不直写记录） ----
    def overview(self) -> dict:
        from .overview import build_overview
        from .servers import server_inventory
        result = build_overview(self.catalog, lambda: self._ptr_read(['stats']))
        result['server_inventory'] = server_inventory(self.catalog.workspace_root)
        return result

    def ptr_surface(self) -> dict:
        cap = dmy.capabilities(self.catalog.workspace_root, runner=self._dmy_runner)
        return dmy.negotiate_surface(
            cap, dmy.WORKBENCH_ACTIONS,
            origins=dmy.PTR_ORIGINS,
            task_statuses=dmy.TASK_STATUSES,
            run_statuses=dmy.RUN_STATUSES,
            run_finish_statuses=dmy.RUN_FINISH_STATUSES,
            cli_info=dmy.describe_cli(self.catalog.workspace_root),
            hostname=os.environ.get('COMPUTERNAME') or '',
        )

    def _ptr_actor(self) -> str:
        return self._governance.actor()

    def _ptr_read(self, argv: list[str]) -> dict:
        return dmy.run_dmy(argv, workspace=self.catalog.workspace_root,runner=self._dmy_runner)

    def _ptr_write(self, argv: list[str], params: dict, *, require_version: bool) -> dict:
        return self._governance.write(argv,params,require_version=require_version)

    def _ptr_migrate_write(self, argv: list[str], params: dict) -> dict:
        return self._governance.write(argv,params,require_version=True,requires_plan=True)

    def ptr_show_task(self, task: str) -> dict:
        return self._ptr_read(['task', 'show', _text(task, 'task')])

    def ptr_create_task(self, params: dict) -> dict:
        argv = ['task', 'create',
                '--project', _text(params.get('project'), 'project'),
                '--title', _text(params.get('title'), 'title'),
                '--origin', _choice(params.get('origin'), 'origin', dmy.PTR_ORIGINS),
                '--goal', _text(params.get('goal'), 'goal')]
        if params.get('owner'):
            argv += ['--owner', _text(params['owner'], 'owner')]
        if params.get('requires_acceptance'):
            argv.append('--requires-acceptance')
        for path in _text_list(params.get('read_paths'), 'read_paths'):
            argv += ['--read-path', path]
        for path in _text_list(params.get('write_paths'), 'write_paths'):
            argv += ['--write-path', path]
        return self._ptr_write(argv, params, require_version=False)

    def ptr_update_task(self, params: dict) -> dict:
        argv = ['task', 'update',
                '--task', _text(params.get('task'), 'task'),
                '--note', _text(params.get('note'), 'note')]
        if params.get('status') is not None:
            argv += ['--status', _choice(params.get('status'), 'status', dmy.TASK_STATUSES)]
        if params.get('owner'):
            argv += ['--owner', _text(params['owner'], 'owner')]
        if params.get('accepted'):
            argv.append('--accepted')
        for path in _text_list(params.get('read_paths'), 'read_paths'):
            argv += ['--read-path', path]
        for path in _text_list(params.get('write_paths'), 'write_paths'):
            argv += ['--write-path', path]
        if params.get('remote_resources') is not None:
            argv += ['--remote-resources', _json_array(params['remote_resources'], 'remote_resources')]
        if params.get('clear_read_paths'):
            argv.append('--clear-read-paths')
        if params.get('clear_write_paths'):
            argv.append('--clear-write-paths')
        return self._ptr_write(argv, params, require_version=True)

    def ptr_handoff_task(self, params: dict) -> dict:
        argv = ['task', 'handoff',
                '--task', _text(params.get('task'), 'task'),
                '--note', _text(params.get('note'), 'note'),
                '--owner', _text(params.get('owner'), 'owner')]
        if params.get('authorization'):
            argv += ['--authorization', _text(params['authorization'], 'authorization')]
        return self._ptr_write(argv, params, require_version=True)

    def ptr_show_run(self, task: str, run: str) -> dict:
        return self._ptr_read(['run', 'show', '--task', _text(task, 'task'), _text(run, 'run')])

    def ptr_create_run(self, params: dict) -> dict:
        argv = ['run', 'create',
                '--task', _text(params.get('task'), 'task'),
                '--title', _text(params.get('title'), 'title'),
                '--host', _text(params.get('host'), 'host'),
                '--source', _text(params.get('source'), 'source'),
                '--inputs', _text(params.get('inputs'), 'inputs'),
                '--command', _text(params.get('command'), 'command')]
        if params.get('retry_of'):
            argv += ['--retry-of', _text(params['retry_of'], 'retry_of')]
        return self._ptr_write(argv, params, require_version=False)

    def ptr_start_run(self, params: dict) -> dict:
        return self._ptr_write(['run', 'start',
                                '--task', _text(params.get('task'), 'task'),
                                '--run', _text(params.get('run'), 'run')],
                               params, require_version=True)

    def ptr_finish_run(self, params: dict) -> dict:
        argv = ['run', 'finish',
                '--task', _text(params.get('task'), 'task'),
                '--run', _text(params.get('run'), 'run'),
                '--status', _choice(params.get('status'), 'status', dmy.RUN_FINISH_STATUSES),
                '--result', _text(params.get('result'), 'result')]
        if params.get('exit_code') is not None:
            argv += ['--exit-code', str(_integer(params['exit_code'], 'exit_code'))]
        for item in _text_list(params.get('evidence'), 'evidence'):
            argv += ['--evidence', item]
        return self._ptr_write(argv, params, require_version=True)

    def ptr_show_project(self, project: str) -> dict:
        return self._ptr_read(['project', 'show', _text(project, 'project')])

    def ptr_create_project(self, params: dict) -> dict:
        argv = ['project', 'create',
                '--title', _text(params.get('title'), 'title')]
        if params.get('created'):
            argv += ['--created', _text(params['created'], 'created')]
        return self._ptr_write(argv, params, require_version=False)

    def ptr_update_project(self, params: dict) -> dict:
        argv = ['project', 'update',
                '--project', _text(params.get('project'), 'project')]
        if params.get('title'):
            argv += ['--title', _text(params['title'], 'title')]
        if params.get('aliases') is not None:
            argv += ['--aliases', _json_array(params['aliases'], 'aliases')]
        if params.get('description') is not None:
            argv += ['--description', _text(params['description'], 'description')]
        return self._ptr_write(argv, params, require_version=True)

    def ptr_rename_project(self, params: dict) -> dict:
        return self._ptr_migrate_write(
            ['project', 'rename',
             '--project', _text(params.get('project'), 'project'),
             '--title', _text(params.get('title'), 'title'),
             '--reason', _text(params.get('reason'), 'reason')],
            params)

    def ptr_pause_project(self, params: dict) -> dict:
        return self._ptr_write(
            ['project', 'pause',
             '--project', _text(params.get('project'), 'project'),
             '--reason', _text(params.get('reason'), 'reason')],
            params, require_version=True)

    def ptr_resume_project(self, params: dict) -> dict:
        return self._ptr_write(
            ['project', 'resume',
             '--project', _text(params.get('project'), 'project'),
             '--reason', _text(params.get('reason'), 'reason')],
            params, require_version=True)

    def ptr_archive_project(self, params: dict) -> dict:
        confirmation = self._archive_confirmation(params)
        return self._ptr_migrate_write(
            ['project', 'archive',
             '--project', _text(params.get('project'), 'project'),
             '--reason', _text(params.get('reason'), 'reason')] + confirmation,
            params)

    def ptr_unarchive_project(self, params: dict) -> dict:
        return self._ptr_migrate_write(
            ['project', 'unarchive',
             '--project', _text(params.get('project'), 'project'),
             '--reason', _text(params.get('reason'), 'reason')],
            params)

    def ptr_delete_project(self, params: dict) -> dict:
        return self._ptr_write(
            ['project', 'delete',
             '--project', _text(params.get('project'), 'project'),
             '--reason', _text(params.get('reason'), 'reason')],
            params, require_version=True)

    def ptr_undelete_project(self, params: dict) -> dict:
        return self._ptr_write(
            ['project', 'undelete',
             '--project', _text(params.get('project'), 'project'),
             '--reason', _text(params.get('reason'), 'reason')],
            params, require_version=True)

    def ptr_rename_task(self, params: dict) -> dict:
        return self._ptr_migrate_write(
            ['task', 'rename',
             '--task', _text(params.get('task'), 'task'),
             '--title', _text(params.get('title'), 'title'),
             '--reason', _text(params.get('reason'), 'reason')],
            params)

    def ptr_move_task(self, params: dict) -> dict:
        argv = ['task', 'move',
                '--task', _text(params.get('task'), 'task'),
                '--to-project', _text(params.get('to_project'), 'to_project'),
                '--reason', _text(params.get('reason'), 'reason')]
        if params.get('authorization'):
            argv += ['--authorization', _text(params['authorization'], 'authorization')]
        return self._ptr_migrate_write(argv, params)

    def ptr_archive_task(self, params: dict) -> dict:
        confirmation = self._archive_confirmation(params)
        return self._ptr_migrate_write(
            ['task', 'archive',
             '--task', _text(params.get('task'), 'task'),
             '--reason', _text(params.get('reason'), 'reason')] + confirmation,
            params)

    def ptr_unarchive_task(self, params: dict) -> dict:
        return self._ptr_migrate_write(
            ['task', 'unarchive',
             '--task', _text(params.get('task'), 'task'),
             '--reason', _text(params.get('reason'), 'reason')],
            params)

    def ptr_delete_task(self, params: dict) -> dict:
        return self._ptr_write(
            ['task', 'delete',
             '--task', _text(params.get('task'), 'task'),
             '--reason', _text(params.get('reason'), 'reason')],
            params, require_version=True)

    def ptr_undelete_task(self, params: dict) -> dict:
        return self._ptr_write(
            ['task', 'undelete',
             '--task', _text(params.get('task'), 'task'),
             '--reason', _text(params.get('reason'), 'reason')],
            params, require_version=True)

    def ptr_rename_run(self, params: dict) -> dict:
        return self._ptr_write(
            ['run', 'rename',
             '--task', _text(params.get('task'), 'task'),
             '--run', _text(params.get('run'), 'run'),
             '--title', _text(params.get('title'), 'title')],
            params, require_version=True)

    def ptr_update_run(self, params: dict) -> dict:
        argv = ['run', 'update',
                '--task', _text(params.get('task'), 'task'),
                '--run', _text(params.get('run'), 'run')]
        if params.get('status') is not None:
            argv += ['--status', _choice(params['status'], 'status', dmy.RUN_STATUSES)]
        if params.get('host'):
            argv += ['--host', _text(params['host'], 'host')]
        if params.get('source'):
            argv += ['--source', _text(params['source'], 'source')]
        if params.get('inputs'):
            argv += ['--inputs', _text(params['inputs'], 'inputs')]
        if params.get('command'):
            argv += ['--command', _text(params['command'], 'command')]
        if params.get('result') is not None:
            argv += ['--result', _text(params['result'], 'result')]
        if params.get('exit_code') is not None:
            argv += ['--exit-code', str(_integer(params['exit_code'], 'exit_code'))]
        for item in _text_list(params.get('add_evidence'), 'add_evidence'):
            argv += ['--add-evidence', item]
        return self._ptr_write(argv, params, require_version=True)

    def ptr_archive_run(self, params: dict) -> dict:
        return self._ptr_write(
            ['run', 'archive',
             '--task', _text(params.get('task'), 'task'),
             '--run', _text(params.get('run'), 'run'),
             '--reason', _text(params.get('reason'), 'reason')],
            params, require_version=True)

    def ptr_unarchive_run(self, params: dict) -> dict:
        return self._ptr_write(
            ['run', 'unarchive',
             '--task', _text(params.get('task'), 'task'),
             '--run', _text(params.get('run'), 'run'),
             '--reason', _text(params.get('reason'), 'reason')],
            params, require_version=True)

    def ptr_delete_run(self, params: dict) -> dict:
        return self._ptr_write(
            ['run', 'delete',
             '--task', _text(params.get('task'), 'task'),
             '--run', _text(params.get('run'), 'run'),
             '--reason', _text(params.get('reason'), 'reason')],
            params, require_version=True)

    def ptr_undelete_run(self, params: dict) -> dict:
        return self._ptr_write(
            ['run', 'undelete',
             '--task', _text(params.get('task'), 'task'),
             '--run', _text(params.get('run'), 'run'),
             '--reason', _text(params.get('reason'), 'reason')],
            params, require_version=True)

    @staticmethod
    def _archive_confirmation(params: dict) -> list[str]:
        value = params.get('allow_unfinished', False)
        if not isinstance(value, bool):
            raise InvalidTarget('归档确认 allow_unfinished 必须为布尔值')
        return ['--allow-unfinished'] if value else []

    def ptr_plan(self, params: dict) -> dict:
        """两步计划第一步：dry-run，返回 plan_token 供后续 --if-plan 提交。"""
        action = _text(params.get('action'), 'action')
        argv = [action.split('.', 1)[0], action.split('.', 1)[1], '--dry-run']
        if action in ('task.archive', 'project.archive'):
            argv += self._archive_confirmation(params)
        for key in ('project', 'task', 'run', 'title', 'reason', 'to_project', 'authorization'):
            if params.get(key):
                flag = '--' + key.replace('_', '-')
                argv += [flag, _text(params[key], key)]
        data = dmy.run_dmy(argv, workspace=self.catalog.workspace_root,
                           actor=self._ptr_actor(), mutating=True, runner=self._dmy_runner)
        return data

    def ptr_check_operation(self, request_id: str) -> dict:
        """按 request_id 查 Operation，供超时后确认结果。"""
        operations = self._ptr_read(['operation', 'list'])
        for op in (operations or []):
            if isinstance(op, dict) and op.get('request_id') == request_id:
                return self._ptr_read(['operation', 'show', op.get('id') or op.get('operation_id', '')])
        return {'found': False, 'request_id': request_id,
                'note': '尚未产生 Operation 回执；可能仍在执行或未开始'}

    def list_directory(self, target: dict, name_filter: str | None = None,
                       cursor: dict | None = None, limit: int | None = None,
                       sort: str = 'name', kind: str = 'all', include_file_counts: bool = False) -> dict:
        self._target(target)
        if name_filter is not None and not isinstance(name_filter, str):
            raise InvalidTarget('目录过滤条件必须是字符串')
        if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool)):
            raise InvalidTarget('分页大小必须是整数')
        if cursor is not None:
            if not isinstance(cursor, dict):
                raise InvalidTarget('游标必须是对象')
            offset = cursor.get('offset', 0)
            if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
                raise InvalidTarget('游标偏移必须为非负整数')
        return self.catalog.list_directory(target, name_filter, cursor, limit, sort, kind, include_file_counts)

    @staticmethod
    def _target(target: dict) -> dict:
        if not isinstance(target, dict):
            raise InvalidTarget('target 必须是对象')
        if any(not isinstance(target.get(key), str) or not target[key]
               for key in ('project_id', 'root_id')):
            raise InvalidTarget('缺少项目或根标识')
        if not isinstance(target.get('relative_path', ''), str):
            raise InvalidTarget('相对路径必须是字符串')
        return {key: target.get(key, '') for key in ('project_id', 'root_id', 'relative_path')}

    # ---- 文本读取（右侧预览） ----
    def read_text(self, target: dict) -> dict:
        self._target(target)
        resolved = self.catalog.resolve_target(target)
        if resolved['kind'] == 'missing':
            raise FileNotFoundError('目标不存在')
        if resolved['kind'] != 'file':
            raise InvalidTarget('只能读取文件内容，不能读取目录')
        if resolved.get('available') is False or resolved.get('navigation_only'):
            raise TargetForbidden(resolved.get('reason') or '此目标不能读取')
        path = Path(resolved['path'])
        try:
            from dummysys_core.operations import native_path
            with native_path(path).open('rb') as stream:
                raw = stream.read(MAX_READ_BYTES + 1)
        except PermissionError as error:
            raise TargetForbidden('读取目标被拒绝') from error
        except OSError as error:
            raise CatalogError(f'读取文件失败：{error}') from error
        truncated = len(raw) > MAX_READ_BYTES
        if truncated:
            raw = raw[:MAX_READ_BYTES]
        if b'\x00' in raw[:8192]:
            raise InvalidTarget('该文件不是文本，不能用于预览')
        text = None
        for encoding in ('utf-8-sig', 'gbk', 'utf-8'):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            text = raw.decode('utf-8', errors='replace')
        return {'target': resolved, 'text': text, 'truncated': truncated,
                'size': native_path(path).stat().st_size if not truncated else len(raw)}

    # ---- 动作解析 ----
    def available_actions(self, target: dict) -> dict:
        self._target(target)
        resolved = self.catalog.resolve_target(target)
        return {**self._actions_for(resolved), 'target': resolved}

    def _actions_for(self, resolved: dict) -> dict:
        path = resolved["path"]
        kind = resolved["kind"]
        if resolved.get('navigation_only'):
            return {'default_action': 'browse', 'available_actions': []}
        if kind == "dir":
            return self._available('browse', [ACTION_VSCODE, ACTION_EXPLORER])
        if kind != "file":
            return {"default_action": None, "available_actions": []}
        ext = Path(path).suffix.casefold()
        vault = self.catalog.config.get("apps", {}).get("obsidian_vault_path")
        in_vault = self._in_vault(path, vault)
        actions = [ACTION_REVEAL]
        if ext in MARKDOWN_EXTENSIONS and in_vault:
            actions.insert(0, ACTION_OBSIDIAN)
            actions.insert(1, ACTION_VSCODE)
            default = ACTION_OBSIDIAN
        elif ext in CODE_EXTENSIONS or ext in MARKDOWN_EXTENSIONS:
            actions.insert(0, ACTION_VSCODE)
            default = ACTION_VSCODE
        elif ext in DOCUMENT_EXTENSIONS or ext in MEDIA_EXTENSIONS or ext == ".html":
            actions.insert(0, ACTION_SYSTEM)
            actions.insert(1, ACTION_VSCODE)
            default = ACTION_SYSTEM
        else:
            default = None
            if not self._executable(ext):
                actions.insert(0, ACTION_SYSTEM)
                default = ACTION_SYSTEM
        return self._available(default, actions)

    def _available(self, default: str | None, actions: list[str]) -> dict:
        probe = self.opener.probe()
        apps = {ACTION_VSCODE: 'vscode', ACTION_OBSIDIAN: 'obsidian'}
        available = [action for action in actions if action not in apps
                     or probe.get(apps[action], {}).get('available')]
        return {'default_action': default if default == 'browse' or default in available else None,
                'available_actions': available}

    @staticmethod
    def _executable(ext: str) -> bool:
        return ext in SCRIPT_EXTENSIONS

    @staticmethod
    def _in_vault(path: str, vault: str | None) -> bool:
        if not vault:
            return False
        try:
            return Path(os.path.normpath(path)).resolve() == Path(vault).resolve() \
                or Path(vault).resolve() in Path(os.path.normpath(path)).resolve().parents
        except OSError:
            return False

    # ---- 打开 ----
    def open(self, target: dict, action: str, request_id: str | None = None,
             *, session_id: str = 'local') -> dict:
        target = self._target(target)
        request_id = request_id or self._new_request_id()
        if not isinstance(action, str) or not isinstance(request_id, str) or len(request_id) > 200:
            raise InvalidTarget('动作和请求标识必须是有效字符串')
        now = time.monotonic()
        key = (session_id, request_id)
        fingerprint = (*target.values(), action)
        with self._open_lock:
            self._open_log = {k: v for k, v in self._open_log.items()
                              if not v.future.done() or now - v.created < self._open_log_ttl}
            entry = self._open_log.get(key)
            owner = entry is None
            if owner:
                entry = OpenRequest(fingerprint, now)
                self._open_log[key] = entry
            elif entry.fingerprint != fingerprint:
                raise InvalidTarget('同一 request_id 不能用于不同目标或动作')
        if owner:
            try:
                resolved = self.catalog.resolve_target(target)
                if resolved['kind'] == 'missing':
                    raise FileNotFoundError('目标不存在')
                if action == ACTION_SYSTEM and self._executable(Path(resolved['path']).suffix.casefold()):
                    raise InvalidTarget('可执行或脚本文件不提供系统默认打开')
                actions = self._actions_for(resolved)
                if action not in actions['available_actions']:
                    if action in (ACTION_VSCODE, ACTION_OBSIDIAN) and not resolved.get('navigation_only'):
                        probe = self.opener.probe().get('vscode' if action == ACTION_VSCODE else 'obsidian', {})
                        if not probe.get('available'):
                            raise AppUnavailable(probe.get('reason') or '应用不可用')
                    raise InvalidTarget(f'不支持的动作：{action}')
                self._dispatch(resolved['path'], action)
                entry.future.set_result({'status': 'dispatched', 'action': action, 'target': resolved['path']})
            except Exception as error:
                entry.future.set_exception(error)
            finally:
                entry.created = time.monotonic()
        return dict(entry.future.result())

    def _dispatch(self, path: str, action: str) -> None:
        try:
            if action == ACTION_OBSIDIAN:
                self.opener.obsidian_open(path)
            elif action == ACTION_VSCODE:
                self.opener.vscode_open(path)
            elif action == ACTION_EXPLORER:
                self.opener.explorer_open(path)
            elif action == ACTION_REVEAL:
                self.opener.explorer_reveal(path)
            elif action == ACTION_SYSTEM:
                self.opener.system_open(path)
            else:
                raise InvalidTarget(f"未知动作：{action}")
        except (AppUnavailable, OpenFailed):
            raise

    @staticmethod
    def _new_request_id() -> str:
        import uuid
        return str(uuid.uuid4())


# 供 web 层复用的错误映射
ERROR_STATUS = {
    TargetNotFound: 404,
    TargetForbidden: 403,
    InvalidTarget: 400,
    ProjectNotFound: 404,
    RootNotFound: 404,
    PathOutsideRoot: 403,
    BlockedLink: 403,
    StaleCursor: 409,
    AppUnavailable: 409,
    CatalogError: 500,
    OpenFailed: 502,
}

ERROR_CODE = {
    TargetNotFound: "NOT_FOUND",
    TargetForbidden: "FORBIDDEN",
    InvalidTarget: "INVALID_REQUEST",
    ProjectNotFound: "NOT_FOUND",
    RootNotFound: "NOT_FOUND",
    PathOutsideRoot: "PATH_OUTSIDE_ROOT",
    BlockedLink: "FORBIDDEN",
    StaleCursor: "STALE_CURSOR",
    AppUnavailable: "APP_UNAVAILABLE",
    CatalogError: "INTERNAL_ERROR",
    OpenFailed: "OPEN_FAILED",
}
