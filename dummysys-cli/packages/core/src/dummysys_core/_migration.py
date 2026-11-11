"""迁移执行器：目录迁移的计划、分阶段日志、中断恢复。

阶段：prepared → docs_moved → resources_moved → records_updated → links_verified → completed
     或 needs_recovery。每个外部副作用前持久化意图，完成后持久化结果。
"""
from __future__ import annotations

from dummysys_core import locations as loc

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time

from .operations import GovernanceError, safe_target, save, digest, payload

STAGES = ('prepared', 'docs_moved', 'resources_moved', 'records_updated', 'links_verified', 'completed')
MIGRATION_PATTERN = re.compile(r'\[task ([1-9]\d*)\]\[(\d{8})\](.+)')
RESERVED_NAMES = frozenset({'CON', 'PRN', 'AUX', 'NUL', 'COM1', 'COM2', 'COM3', 'COM4',
                            'COM5', 'COM6', 'COM7', 'COM8', 'COM9', 'LPT1', 'LPT2', 'LPT3',
                            'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'})


def validate_dir_name(name):
    if not name or name in {'.', '..'} or name == 'archive':
        raise GovernanceError('INVALID_ARGUMENT', '目录名无效', name=name)
    if re.search(r'[<>:"/\\|?*\x00-\x1f]', name) or name.endswith((' ', '.')):
        raise GovernanceError('INVALID_ARGUMENT', '目录名含非法字符或尾部空格/点', name=name)
    stem = name.split('.')[0].upper()
    if stem in RESERVED_NAMES:
        raise GovernanceError('INVALID_ARGUMENT', 'Windows 保留名不可用作目录名', name=name)
    return name


def check_same_volume(source, target):
    if os.path.splitdrive(str(source))[0].casefold() != os.path.splitdrive(str(target))[0].casefold():
        raise GovernanceError('INVALID_ARGUMENT', '跨卷迁移不受支持，请使用同卷路径',
                              source=str(source), target=str(target))


def hash_tree(path):
    """返回目录树的文件哈希清单 {relative: sha256}。"""
    result = {}
    base = Path(path).resolve()
    if os.name == 'nt' and not str(base).startswith('\\\\?\\'):
        value = str(base)
        base = Path('\\\\?\\UNC\\' + value[2:] if value.startswith('\\\\') else '\\\\?\\' + value)
    if not base.exists():
        return result
    for p in sorted(base.rglob('*')):
        if p.is_file() and not p.is_symlink():
            result[p.relative_to(base).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return result


def check_idle(resource):
    from . import _records as records
    for run in Path(resource).rglob('run.json'):
        if records.read_json(run).get('status') in ('planned', 'running'):
            raise GovernanceError('STATE_CONFLICT', '仍有未结束 Run，禁止迁移', path=str(run))


def check_paths(root, source, target):
    root, source, target = map(Path, (root, source, target))
    for path in (source, target):
        try:
            safe_target(root, loc.relative(root, path))
        except ValueError as error:
            raise GovernanceError('PATH_OUTSIDE_ROOT', '迁移路径越界', path=str(path)) from error
        if any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction())
               for p in (path, *path.parents) if p != root.parent):
            raise GovernanceError('PATH_OUTSIDE_ROOT', '迁移路径包含目录链接', path=str(path))
    if any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()) for p in source.rglob('*')):
        raise GovernanceError('PATH_OUTSIDE_ROOT', '迁移子树包含链接')
    check_same_volume(source, target)
    if not source.is_dir() or target.exists():
        raise GovernanceError('STATE_CONFLICT', '源缺失或目标已占用', source=str(source), target=str(target))


class MigrationJournal:
    def __init__(self, root, operation_id):
        self.root = Path(root).resolve()
        self.folder = loc.runtime(self.root) / 'state/workspace/operations' / operation_id
        self.path = self.folder / 'migration.json'
        self.data = {'schema_version': 1, 'stage': 'prepared', 'steps': [], 'operation_id': operation_id}

    def load(self):
        data = payload(self.path)
        if data is not None:
            self.data = json.loads(data)
        return self.data

    def record(self, stage, detail=None):
        self.data['stage'] = stage
        self.data['steps'].append({'stage': stage, 'at': time.time(), 'detail': detail or {}})
        save(self.path, self.data)

    def set_stage(self, stage):
        self.data['stage'] = stage
        save(self.path, self.data)


def plan_rename(root, kind, identity, new_title, reason, actor):
    """计算 rename 计划；返回 plan 描述字典。"""
    from . import _records as records
    if kind == 'project':
        name = identity if identity == '00-Playground' else None
        if identity == '00-Playground':
            raise GovernanceError('STATE_CONFLICT', 'Playground 不允许 rename')
        matches = [p.parent.name for p in records.project_readmes(root)
                    if records.properties(p).get('project_id') == identity or p.parent.name == identity]
        if len(matches) != 1:
            raise GovernanceError('NOT_FOUND', '项目应唯一匹配', project=identity)
        old_name = matches[0]
        if old_name == '00-Playground':
            raise GovernanceError('STATE_CONFLICT', 'Playground 不允许 rename')
        date_match = re.match(r'\[(\d{8})\]', old_name)
        date_part = f'[{date_match.group(1)}]' if date_match else ''
        new_name = f'{date_part}{new_title}'
        validate_dir_name(new_name)
        docs_old = records.project_docs(root, old_name)
        res_old = loc.runtime(Path(root)) / 'project_src' / old_name
        docs_new = docs_old.parent / new_name
        res_new = res_old.parent / new_name
        check_idle(res_old)
        check_paths(root, docs_old, docs_new)
        check_paths(root, res_old, res_new)
        check_same_volume(docs_old, docs_new)
        if docs_new.exists() or res_new.exists():
            if docs_new != docs_old or res_new != res_old:
                raise GovernanceError('STATE_CONFLICT', '目标目录名已占用', name=new_name)
        return {
            'action': 'project.rename', 'kind': 'project', 'old_name': old_name, 'new_name': new_name,
            'docs_source': str(docs_old), 'docs_target': str(docs_new),
            'resource_source': str(res_old), 'resource_target': str(res_new),
            'reason': reason, 'actor': actor, 'project': old_name,
            'project_id': records.properties(docs_old / 'README.md')['project_id'],
        }
    elif kind == 'task':
        doc, resource, props = records.locate_task(root, identity)
        if props.get('deleted_at'):
            raise GovernanceError('STATE_CONFLICT', '已删除对象仅允许查询和 undelete')
        old_name = doc.parent.name
        match = re.fullmatch(MIGRATION_PATTERN, old_name)
        if not match:
            raise GovernanceError('INVALID_ARGUMENT', 'Task 目录名不合规', name=old_name)
        new_name = f'[task {match.group(1)}][{match.group(2)}]{new_title}'
        validate_dir_name(new_name)
        docs_old = doc.parent
        res_old = resource
        docs_new = docs_old.parent / new_name
        res_new = res_old.parent / new_name
        check_idle(res_old)
        check_paths(root, docs_old, docs_new)
        check_paths(root, res_old, res_new)
        check_same_volume(docs_old, docs_new)
        if (docs_new.exists() and docs_new != docs_old) or (res_new.exists() and res_new != res_old):
            raise GovernanceError('STATE_CONFLICT', '目标目录名已占用', name=new_name)
        return {
            'action': 'task.rename', 'kind': 'task', 'old_name': old_name, 'new_name': new_name,
            'task_id': identity,
            'docs_source': str(docs_old), 'docs_target': str(docs_new),
            'resource_source': str(res_old), 'resource_target': str(res_new),
            'reason': reason, 'actor': actor,
        }
    raise GovernanceError('INVALID_ARGUMENT', '未知迁移类型', kind=kind)


def plan_move(root, task_id, to_project, reason, actor):
    """计算 Task 跨项目移动计划。"""
    from . import _records as records
    doc, resource, props = records.locate_task(root, task_id)
    if props.get('deleted_at'):
        raise GovernanceError('STATE_CONFLICT', '已删除对象仅允许查询和 undelete')
    if doc.parent.parent.name == 'archive':
        raise GovernanceError('STATE_CONFLICT', '归档 Task 先 unarchive 再移动')
    source_project_name = resource.parent.name
    source_docs, source_res = records.paired(root, source_project_name)
    matches = [p.parent.name for p in records.project_readmes(root)
                if records.properties(p).get('project_id') == to_project or p.parent.name == to_project]
    if len(matches) != 1:
        raise GovernanceError('NOT_FOUND', '目标项目应唯一匹配', project=to_project)
    target_project_name = matches[0]
    if target_project_name == '00-Playground':
        pass  # 允许移入
    target_docs, target_res = records.paired(root, target_project_name)
    target_props = records.properties(target_docs / 'README.md')
    source_props = records.properties(source_docs / 'README.md')
    if source_props.get('status') != 'active' or target_props.get('status') != 'active':
        raise GovernanceError('STATE_CONFLICT', '源和目标项目必须都是 active')
    if source_props.get('deleted_at') or target_props.get('deleted_at'):
        raise GovernanceError('STATE_CONFLICT', '源和目标项目不能已删除')
    if props.get('status') in ('planned', 'running'):
        pass  # Task 状态不会是 planned/running
    runs = list(resource.glob('runs/*/run.json'))
    unfinished = [r for r in runs if records.read_json(r).get('status') in ('planned', 'running')]
    if unfinished:
        raise GovernanceError('STATE_CONFLICT', '活动 Task 有未结束 Run 时不可移动')
    from . import _repositories as repos
    effective = repos.references(root, task=task_id)
    target_refs = repos.references(root, project=target_project_name)
    try:
        repos.validate_refs(root, effective, target_refs)
        for ref in effective:
            if 'repo_id' not in ref and ref not in target_refs:
                raise ValueError('目标项目没有对应的旧 Repo 绑定')
    except ValueError as error:
        raise GovernanceError('REPOSITORY_SCOPE_CONFLICT', str(error)) from error
    meta = records.read_json(resource / 'task.json')
    # 远端边界不含本机路径时保持原样；含旧本机路径时要求先显式修订。
    remote = json.dumps(meta.get('scope', {}).get('remote_resources', []), ensure_ascii=False)
    if str(resource) in remote or resource.as_posix() in remote:
        raise GovernanceError('STATE_CONFLICT', 'remote_resources 含旧本机路径，须先修订')
    # 编号分配：只读预演。真正推进高水位在提交期的 records_updated 相位做，
    # 否则 --dry-run 会污染 project.json，提交时又会二次推进。
    from ._management import peek_high_watermark
    new_number = peek_high_watermark(root, target_project_name)
    match = re.fullmatch(MIGRATION_PATTERN, doc.parent.name)
    if not match:
        raise GovernanceError('INVALID_ARGUMENT', 'Task 目录名不合规')
    new_name = f'[task {new_number}][{match.group(2)}]{match.group(3)}'
    check_paths(root, doc.parent, target_docs / new_name)
    check_paths(root, resource, target_res / new_name)
    check_same_volume(source_docs, target_docs)
    return {
        'action': 'task.move', 'kind': 'task_move', 'task_id': task_id,
        'old_name': doc.parent.name, 'new_name': new_name,
        'old_number': match.group(1), 'new_number': str(new_number),
        'source_project': source_project_name, 'target_project': target_project_name,
        'docs_source': str(doc.parent), 'docs_target': str(target_docs / new_name),
        'resource_source': str(resource), 'resource_target': str(target_res / new_name),
        'reason': reason, 'actor': actor, 'repositories': effective,
        'source_high_watermark': peek_high_watermark(root, source_project_name) - 1,
        'target_project_id': target_props['project_id'],
    }


def plan_archive(root, kind, identity, reason, actor, allow_unfinished=False):
    if not isinstance(allow_unfinished, bool):
        raise GovernanceError('INVALID_ARGUMENT', 'allow_unfinished 必须为布尔值')
    """计算归档计划。"""
    from . import _records as records
    if kind == 'project':
        matches = [p.parent.name for p in records.project_readmes(root)
                    if records.properties(p).get('project_id') == identity or p.parent.name == identity]
        if len(matches) != 1:
            raise GovernanceError('NOT_FOUND', '项目应唯一匹配', project=identity)
        name = matches[0]
        if name == '00-Playground':
            raise GovernanceError('STATE_CONFLICT', 'Playground 不允许归档')
        docs, resources = records.paired(root, name)
        props = records.properties(docs / 'README.md')
        if props.get('deleted_at'):
            raise GovernanceError('STATE_CONFLICT', '已删除对象仅允许查询和 undelete')
        if props.get('status') == 'archived':
            raise GovernanceError('STATE_CONFLICT', '项目已归档')
        # 未完成 Task 需要显式确认；Run 执行保护始终保留。
        unfinished_tasks = []
        for task_dir in records.task_dirs(docs):
            task_props = records.properties(task_dir / 'README.md')
            if task_props.get('status') not in ('completed', 'cancelled'):
                unfinished_tasks.append({'task_id': task_props.get('task_id'),
                    'title': task_props.get('title') or task_dir.name, 'status': task_props.get('status')})
            task_res = resources / task_dir.name
            for run_path in task_res.glob('runs/*/run.json'):
                run = records.read_json(run_path)
                if run.get('status') in ('planned', 'running'):
                    raise GovernanceError('STATE_CONFLICT', f'存在未结束 Run：{task_dir.name}')
        if unfinished_tasks and not allow_unfinished:
            raise GovernanceError('STATE_CONFLICT', '项目有未完成 Task；确认保留Task状态归档时使用 --allow-unfinished',
                unfinished_tasks=unfinished_tasks)
        archive_docs = docs.parent / 'archive' / name
        check_same_volume(docs, archive_docs)
        return {
            'action': 'project.archive', 'kind': 'project_archive', 'name': name,
            'docs_source': str(docs), 'docs_target': str(archive_docs),
            'resource_source': None, 'resource_target': None,
            'reason': reason, 'actor': actor,
            'project_status': props.get('status'),
            'unfinished_tasks': unfinished_tasks,
            'allow_unfinished': bool(allow_unfinished),
        }
    elif kind == 'task':
        doc, resource, props = records.locate_task(root, identity)
        if props.get('deleted_at'):
            raise GovernanceError('STATE_CONFLICT', '已删除对象仅允许查询和 undelete')
        if doc.parent.parent.name == 'archive':
            raise GovernanceError('STATE_CONFLICT', 'Task 已归档')
        unfinished = props.get('status') not in ('completed', 'cancelled')
        if unfinished and not allow_unfinished:
            raise GovernanceError('STATE_CONFLICT', 'Task 尚未完成；确认保留原状态归档时使用 --allow-unfinished')
        for run_path in resource.glob('runs/*/run.json'):
            run = records.read_json(run_path)
            if run.get('status') in ('planned', 'running'):
                raise GovernanceError('STATE_CONFLICT', '存在未结束 Run，不能归档')
        archive_target = doc.parent.parent / 'archive' / doc.parent.name
        check_same_volume(doc.parent, archive_target)
        return {
            'action': 'task.archive', 'kind': 'task_archive', 'task_id': identity,
            'docs_source': str(doc.parent), 'docs_target': str(archive_target),
            'resource_source': None, 'resource_target': None,
            'reason': reason, 'actor': actor,
            'task_status': props.get('status'),
            'allow_unfinished': bool(allow_unfinished),
        }
    raise GovernanceError('INVALID_ARGUMENT', '未知归档类型', kind=kind)


def plan_unarchive(root, kind, identity, reason, actor):
    from . import _records as records
    if kind == 'project':
        matches = [p.parent.name for p in records.project_readmes(root)
                    if records.properties(p).get('project_id') == identity or p.parent.name == identity]
        if len(matches) != 1:
            raise GovernanceError('NOT_FOUND', '项目应唯一匹配', project=identity)
        name = matches[0]
        docs = loc.vault(Path(root)) / '30-项目/archive' / name
        if not docs.exists():
            raise GovernanceError('NOT_FOUND', '归档项目不存在', name=name)
        target = loc.vault(Path(root)) / '30-项目' / name
        check_same_volume(docs, target)
        return {
            'action': 'project.unarchive', 'kind': 'project_unarchive', 'name': name,
            'docs_source': str(docs), 'docs_target': str(target),
            'resource_source': None, 'resource_target': None,
            'reason': reason, 'actor': actor,
        }
    elif kind == 'task':
        # locate in archive
        for project_readme in records.project_readmes(root):
            project_docs = project_readme.parent
            for task_dir in (project_docs / 'archive').iterdir() if (project_docs / 'archive').exists() else []:
                if not task_dir.is_dir():
                    continue
                readme = task_dir / 'README.md'
                if not readme.exists():
                    continue
                try:
                    task_props = records.properties(readme)
                except (ValueError, OSError):
                    continue
                if task_props.get('task_id') == identity:
                    target = project_docs / task_dir.name
                    check_same_volume(task_dir, target)
                    return {
                        'action': 'task.unarchive', 'kind': 'task_unarchive', 'task_id': identity,
                        'docs_source': str(task_dir), 'docs_target': str(target),
                        'resource_source': None, 'resource_target': None,
                        'reason': reason, 'actor': actor,
                    }
        raise GovernanceError('NOT_FOUND', '归档 Task 不存在', task=identity)
    raise GovernanceError('INVALID_ARGUMENT', '未知恢复类型', kind=kind)


def dependency_snapshot(root, plan):
    """计划依赖快照：token 必须覆盖「会让计划过期」的一切，不能只看父 README 的 version。

    覆盖源/目标 Project（props + project.json 摘要，含高水位）、Task（props +
    task.json 摘要，含 scope）、相关 Run 与管理 sidecar、目录占用、Repo 关联、
    repositories.json，以及将被改写的链接文件集合摘要。
    """
    from . import _records as records
    from ._paths import project_readmes
    from ._management import peek_high_watermark
    root = Path(root)
    snapshot = {'plan_identity': plan.get('task_id') or plan.get('project') or plan.get('name')}

    def props_of(readme):
        return dict(records.properties(readme)) if readme.exists() else {}

    def file_digest(path):
        return digest(payload(path)) if path.exists() else None

    names = set()
    for key in ('source_project', 'target_project', 'name', 'project'):
        if plan.get(key):
            names.add(plan[key])
    snapshot['projects'] = {}
    for name in sorted(names):
        try:
            docs, resources = records.paired(root, name)
        except (ValueError, OSError):
            continue
        snapshot['projects'][name] = {
            'props': props_of(docs / 'README.md'),
            'binding': file_digest(resources / 'project.json'),
            'next_task_number': peek_high_watermark(root, name),
        }
    task_ids = {plan[k] for k in ('task_id',) if plan.get(k)}
    snapshot['tasks'] = {}
    for task_id in sorted(task_ids):
        try:
            doc, resource, props = records.locate_task(root, task_id)
        except (ValueError, OSError):
            continue
        runs = {}
        for run_json in sorted(resource.glob('runs/*/run.json')):
            record = records.read_json(run_json)
            sidecar = run_json.parent / 'run-management.json'
            runs[record.get('run_id')] = {'status': record.get('status'),
                                          'sidecar': file_digest(sidecar)}
        snapshot['tasks'][task_id] = {
            'props': props, 'task_json': file_digest(resource / 'task.json'), 'runs': runs,
        }
    snapshot['occupancy'] = {k: Path(plan[k]).exists()
                             for k in ('docs_target', 'resource_target') if plan.get(k)}
    resource_source = plan.get('resource_source')
    if resource_source:
        snapshot['execution_records'] = {
            p.relative_to(Path(resource_source)).as_posix(): file_digest(p)
            for p in sorted(Path(resource_source).rglob('*.json'))
            if p.name in ('run.json', 'run-management.json', 'task.json', 'project.json')}
    snapshot['link_surface'] = digest(json.dumps(
        [[loc.relative(root, p).as_posix(), digest(payload(p))] for p in tracked_files(root)],
        ensure_ascii=False, default=str).encode())
    try:
        from . import _repositories as repos
        snapshot['repositories'] = repos.catalog(root)
        snapshot['repositories_digest'] = file_digest(
            loc.runtime(root) / 'state/workspace/repositories.json')
    except (ValueError, OSError):
        snapshot['repositories'] = {}
    return snapshot


def compute_plan_token(plan, snapshot=None):
    """plan_token = 规范化动作 + 输入 + 依赖快照的摘要。snapshot 为 None 时退化为只看 plan。"""
    normalized = json.dumps({'plan': plan, 'dependency': snapshot}, sort_keys=True,
                            ensure_ascii=False, default=str)
    return digest(normalized.encode())


# ============ 迁移执行：Vault 内移动必须由 Obsidian 完成 ============
# 语义对齐 Obsidian 的 FileManager.renameFile——只有它会顺带更新内部链接。
# 本模块不降级为普通文件移动：Obsidian 条件不满足就报 CAPABILITY_UNAVAILABLE，
# 绝不「假装链接已更新」。参考实现 DUMMYSYSTEM/tools/vault/archive_migration.py。
LINKED_SUFFIXES = frozenset({'.md', '.canvas', '.base'})
REGISTRY_NAME = 'retired-paths.json'


def find_obsidian(explicit=None):
    if explicit is not None:
        # 显式指定就只认它：坏路径直接报错，不静默回落到别处的 Obsidian。
        if Path(explicit).is_file():
            return str(explicit)
        raise GovernanceError('CAPABILITY_UNAVAILABLE', f'指定的 Obsidian 不可用：{explicit}')
    candidates = [shutil.which('obsidian.com'), shutil.which('obsidian')]
    if os.name == 'nt':
        candidates += [str(Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Obsidian/Obsidian.com'),
                       str(Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs/Obsidian/Obsidian.com')]
    for value in candidates:
        if value and Path(value).is_file():
            return str(value)
    raise GovernanceError('CAPABILITY_UNAVAILABLE', '未找到 Obsidian CLI；迁移需它更新内部链接',
                          next_action='安装 Obsidian 并启用命令行接口，或用 --obsidian 指定')


def obsidian_eval(vault, code, executable=None):
    """在目标 Vault 里执行一段 Obsidian JS；cwd 决定库，JS 内再核对真实路径。"""
    import subprocess
    try:
        result = subprocess.run([find_obsidian(executable), 'eval', 'code=' + code], cwd=str(vault),
                                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise GovernanceError('CAPABILITY_UNAVAILABLE', f'Obsidian 调用失败：{error}')
    if result.returncode or 'DUMMYSYS_OK' not in (result.stdout or ''):
        raise GovernanceError('CAPABILITY_UNAVAILABLE',
                              'Obsidian 操作失败：' + (result.stdout or '') + (result.stderr or ''))
    return result.stdout


def obsidian_move(root, source, target, executable=None):
    """Vault 内目录移动：由 app.fileManager.renameFile 完成，顺带更新内部链接。

    依次核对当前 Vault 路径、自动更新链接（alwaysUpdateLinks）、新链接格式
    （newLinkFormat=absolute）、源已被索引、目标空缺；任一不满足即报错停止，
    不做普通文件移动兜底。
    """
    vault = loc.vault(Path(root))
    for path in (Path(source), Path(target)):
        if not path.resolve().is_relative_to(vault.resolve()):
            raise GovernanceError('PATH_OUTSIDE_ROOT', '迁移路径必须在 Vault 内', path=str(path))
    executable = find_obsidian(executable)   # 先确认条件，再动目录；不满足绝不普通移动兜底
    old, new = [p.resolve().relative_to(vault.resolve()).as_posix() for p in (Path(source), Path(target))]
    code = r'''(async()=>{
const expected=EXPECTED, old=OLD, target=NEW;
const norm=p=>p.replace(/\\/g,'/').replace(/\/$/,'').toLowerCase();
if(norm(app.vault.adapter.getBasePath())!==norm(expected))throw Error('Vault 路径不匹配');
if(!app.vault.getConfig('alwaysUpdateLinks'))throw Error('请开启自动更新内部链接');
if(app.vault.getConfig('newLinkFormat')!=='absolute')throw Error('请将新链接格式设置为绝对路径');
const node=app.vault.getAbstractFileByPath(old);
if(!node)throw Error('Obsidian 尚未索引源目录');
if(app.vault.getAbstractFileByPath(target))throw Error('目标已存在');
const parent=target.substring(0,target.lastIndexOf('/'));
if(!app.vault.getAbstractFileByPath(parent))await app.vault.createFolder(parent);
await app.fileManager.renameFile(node,target);
return 'DUMMYSYS_OK';
})()'''.replace('EXPECTED', json.dumps(str(vault))).replace('OLD', json.dumps(old)).replace('NEW', json.dumps(new))
    obsidian_eval(vault, code, executable)
    if Path(source).exists() or not Path(target).is_dir():
        raise GovernanceError('STATE_CONFLICT', 'Obsidian 返回后目录迁移未完成')


def tracked_files(root):
    """链接更新可能改动的文件：md/canvas/base + JSON 路径绑定 + 路径登记。

    刻意不含原始产物、Run 记录与证据——历史事实不批量改写（见 resolve_legacy_path）。
    """
    root = Path(root)
    vault = loc.vault(root)
    files = [p for p in vault.rglob('*')
             if p.is_file() and '.obsidian' not in p.parts and p.suffix in LINKED_SUFFIXES]
    from ._paths import project_readmes
    for readme in project_readmes(root):
        resource = loc.runtime(root) / 'project_src' / readme.parent.name
        files += [p for p in (resource / 'README.md', resource / 'AGENTS.md', resource / 'project.json') if p.is_file()]
        files += list(resource.glob('*/task.json'))
        for task in resource.glob('[[]task *]*/'):
            files += [p for p in (task / 'README.md', task / 'AGENTS.md') if p.is_file()]
            # 项目内服务的当前配置会随资源根移动；历史 runs 与安装回执保持字节不变。
            files += list(task.glob('configs/**/*.json'))
            files += list(task.glob('state/*.json'))
    registry = loc.runtime(root) / 'state' / 'workspace' / REGISTRY_NAME
    if registry.exists():
        files.append(registry)
    return sorted(set(files))


def rewrite_external_links(root, moves):
    """补 Obsidian 不保证更新的引用。

    覆盖：Vault 外资源入口的绝对路径、Base 查询里的路径字符串、Canvas 路径、
    JSON 路径绑定（project.json / task.json 的 docs_root、resource_root）。只替换
    完整路径前缀，不做无限字符串替换。retired-paths 登记本身不改写。
    moves 是 [(source, target), ...]，docs 与 resource 两侧一起处理。
    """
    root = Path(root)
    vault = loc.vault(root)
    pairs = []
    in_vault = []
    for source, target in moves:
        source, target = Path(source), Path(target)
        pairs += [(source.as_posix(), target.as_posix()), (str(source), str(target))]
        if source.resolve().is_relative_to(vault.resolve()):
            in_vault.append((source.relative_to(vault).as_posix(), target.relative_to(vault).as_posix()))
    for path in tracked_files(root):
        if path.name == REGISTRY_NAME:
            continue
        text = path.read_text(encoding='utf-8')
        rewritten = text
        for old, new in pairs:
            variants = [(old, new), (json.dumps(old)[1:-1], json.dumps(new)[1:-1]),
                        (json.dumps(old, ensure_ascii=False)[1:-1], json.dumps(new, ensure_ascii=False)[1:-1])]
            for a, b in variants:
                rewritten = re.sub(re.escape(a) + r'(?=[/\\"<>\s`)]|$)', lambda _m, b=b: b, rewritten)
        if path.suffix in {'.base', '.canvas'}:
            for old, new in in_vault:
                for a, b in [(old, new), (json.dumps(old)[1:-1], json.dumps(new)[1:-1])]:
                    rewritten = re.sub(re.escape(a) + r'(?=[/"\']|$)', lambda _m, b=b: b, rewritten)
        if rewritten != text:
            path.write_text(rewritten, encoding='utf-8')


def link_snapshot(root, executable=None):
    """取链接状态：unresolved / resolved / identity（路径→对象 UUID）。

    identity 取 README frontmatter 的 project_id 或 task_id——这是「链接指向哪个
    对象」的权威依据，不能只看路径字符串。
    """
    vault = loc.vault(Path(root))
    # renameFile 后每文件缓存可以已更新，而 resolvedLinks/unresolvedLinks 仍旧；
    # isCacheClean 也不能证明引用解析已刷新。只重算派生缓存，不改正文。
    code = ("(()=>{const cache=app.metadataCache;"
            "if(typeof cache.resolveLinks!=='function')throw Error('Obsidian 缺少链接重算能力');"
            "for(const file of app.vault.getMarkdownFiles())cache.resolveLinks(file.path);"
            "return JSON.stringify({marker:'DUMMYSYS_OK',"
            "unresolved:cache.unresolvedLinks,resolved:cache.resolvedLinks});})()")
    raw = obsidian_eval(vault, code, executable).split('=>', 1)[-1].strip()
    data = json.loads(raw)
    unresolved = {(str((vault / src).resolve()), link) for src, links in (data.get('unresolved') or {}).items()
                  for link, count in links.items() if count}
    # resolvedLinks 是 {源相对路径: {目标相对路径: 引用次数}}，值不是目标路径。
    resolved = {(str((vault / src).resolve()), str((vault / dst).resolve()), str((vault / dst).resolve()))
                for src, links in (data.get('resolved') or {}).items()
                for dst, count in links.items() if count}
    identity = {}
    from ._records import properties
    for readme in vault.rglob('README.md'):
        if '.obsidian' in readme.parts:
            continue
        props = properties(readme)
        key = props.get('task_id') or props.get('project_id')
        if key:
            identity[readme.parent.resolve().as_posix()] = key
            identity[readme.resolve().as_posix()] = key
    return {'unresolved': unresolved, 'resolved': resolved, 'identity': identity}


def verify_links(before, after, source, target):
    """迁移后核验链接。两条都过才允许报成功。

    1) 新增断链：迁移前能解析的，迁移后仍须能解析（迁移前就断的不算）。
    2) 仍指向原对象：迁移前解析进 source 子树的链接，迁移后必须解析进 target
       子树的**同一相对位置**，且该处对象的 project_id/task_id 与迁移前一致。
       同名文件、短链接、别名、路径重用都靠这道身份比对兜底——「链接能解析」
       不等于「链接仍指向原对象」。
    """
    source, target = Path(source).resolve(), Path(target).resolve()

    def inside(path, base):
        try:
            return Path(path).resolve().relative_to(base)
        except ValueError:
            return None

    # 1) 新增断链：把基线里的源路径按同一相对位移映射到目标，再比差集。
    remapped = {(str(target / inside(s, source)) if inside(s, source) else s, link)
                for s, link in before['unresolved']}
    added_unresolved = {pair for pair in after['unresolved']
                        if pair not in remapped and pair not in before['unresolved']}
    problems = [f'新增断链：{src} -> {link}' for src, link in sorted(added_unresolved)]

    # 2) 身份保持
    before_resolved = {(s, l): t for s, l, t in before['resolved']}
    after_resolved = {(s, l): t for s, l, t in after['resolved']}
    checked = 0
    for (src_file, link), old in sorted(before_resolved.items()):
        rel = inside(old, source)
        if rel is None:
            continue
        checked += 1
        src_rel = inside(src_file, source)
        new_src = str(target / src_rel) if src_rel is not None else src_file
        new_link = str(target / rel) if link == old else link
        new = after_resolved.get((new_src, new_link))
        if new is None:
            problems.append(f'{src_file} -> {link}: 迁移后不再解析')
            continue
        expected = (target / rel).resolve()
        if Path(new).resolve() != expected:
            problems.append(f'{src_file} -> {link}: 解析到 {new}，应为 {expected}（疑指向同名另一对象）')
            continue
        old_id = before['identity'].get(Path(old).resolve().as_posix())
        new_id = after['identity'].get(Path(new).resolve().as_posix())
        if old_id and new_id and old_id != new_id:
            problems.append(f'{src_file} -> {link}: 对象身份 {old_id} -> {new_id}（指向了另一个对象）')
    if problems:
        raise GovernanceError('STATE_CONFLICT', '迁移后链接核验未通过，不报告迁移成功',
                              problems=problems[:20], total=len(problems))
    return {'checked_identity': checked, 'unresolved_after': len(after['unresolved'])}


def resolve_legacy_path(root, path, identity=None):
    """历史路径 → 当前位置。不改写历史，只在查询时按映射解析。

    按对象身份与迁移代次链式解析，检测往返环与路径重用；无法唯一解析时报歧义，
    不做「字符串替换到哪算哪」。
    """
    root = Path(root)
    registry = loc.runtime(root) / 'state' / 'workspace' / REGISTRY_NAME
    mappings = json.loads(registry.read_text(encoding='utf-8')) if registry.exists() else []
    current = str(path)
    seen = {current}
    via = False
    for entry in mappings:   # 旧→新按写入顺序，代次即顺序
        if identity and entry.get('identity') not in (None, identity):
            continue
        if current == str(entry['source']):
            current = str(entry['target'])
            via = True
            if current in seen:
                return {'path': str(path), 'resolved': None, 'ambiguous': '路径映射成环', 'via_mapping': True}
            seen.add(current)
    exists = Path(current).exists()
    # 路径重用：目标位置当前由另一个身份占用时，历史引用不再唯一。这道检查
    # 与是否走过映射、registry 是否存在都无关——「路径还在、链接能解析」也可能
    # 指向另一个同名对象，只比路径字符串发现不了。
    if exists and identity:
        from ._records import properties
        props = properties(Path(current) / 'README.md')
        resident = props.get('task_id') or props.get('project_id')
        if resident and resident != identity:
            return {'path': str(path), 'resolved': None, 'via_mapping': via,
                    'ambiguous': f'歧义：位置已由 {resident} 占用，历史引用不再指向原对象'}
    return {'path': str(path), 'resolved': current if exists else None,
            'via_mapping': via, 'exists': exists}


def _phase_done(journal, stage):
    return any(s.get('stage') == stage and (s.get('detail') or {}).get('done')
               for s in journal.data.get('steps', []))


def _move_state(source, target):
    """一次目录移动的三态：todo / done / indeterminate。"""
    src_exists, dst_exists = Path(source).exists(), Path(target).exists()
    if src_exists and not dst_exists:
        return 'todo'
    if dst_exists and not src_exists:
        return 'done'
    return 'indeterminate'


def _advance(root, pairs, journal, *, identity, finish, executable, mover, link_state,
             new_number=None, target_project=None, finalize=None):
    """可续做的迁移推进：按 STAGES 走，已完成相位跳过。

    首个真实移动之后一律 roll-forward——Obsidian 已改写内部链接，回退会让链接
    失衡。每次外部副作用前持久化意图、之后持久化可核对的结果。
    """
    root = Path(root)
    vault = (loc.vault(root)).resolve()
    pairs = [(Path(s), Path(t)) for s, t in pairs]
    vault_pairs = [(s, t) for s, t in pairs if s.resolve().is_relative_to(vault)]
    side_pairs = [(s, t) for s, t in pairs if not s.resolve().is_relative_to(vault)]
    source, target = vault_pairs[0]

    if not _phase_done(journal, 'prepared'):
        before = link_state() if link_state is not None else link_snapshot(root, executable)
        journal.data['before_links'] = {
            'unresolved': sorted(map(list, before['unresolved'])),
            'resolved': sorted(map(list, before['resolved'])),
            'identity': before['identity'],
        }
        journal.record('prepared', {'moves': [(str(s), str(t)) for s, t in pairs],
                                    'identity': identity, 'done': True,
                                    'inventory': {str(s): hash_tree(s) for s, _t in pairs}})
    inventory = next(step['detail']['inventory'] for step in journal.data['steps']
                     if step['stage'] == 'prepared' and step.get('detail', {}).get('done'))

    if not _phase_done(journal, 'docs_moved'):
        journal.record('docs_moved', {'intent': True, 'source': str(source), 'target': str(target)})
        state = _move_state(source, target)
        if state == 'indeterminate':
            journal.set_stage('needs_recovery')
            raise GovernanceError('RECOVERY_REQUIRED',
                                  '源与目标同时存在或同时缺失，迁移结果不可判定',
                                  source=str(source), target=str(target))
        if state == 'todo':
            (mover or obsidian_move)(root, source, target, executable)
        actual = hash_tree(target)
        original = inventory[str(source)]
        # renameFile 合法更新 Markdown/Canvas/Base 链接；附件必须逐字节保持。
        if set(actual) != set(original) or any(actual[k] != v for k, v in original.items()
                                               if Path(k).suffix not in LINKED_SUFFIXES):
            journal.set_stage('needs_recovery')
            raise GovernanceError('STATE_CONFLICT', '迁移前后文件清单或内容不一致')
        journal.record('docs_moved', {'done': True})

    if not _phase_done(journal, 'resources_moved'):
        journal.record('resources_moved', {'intent': True,
                                           'moves': [(str(s), str(t)) for s, t in side_pairs]})
        for src, dst in side_pairs:
            state = _move_state(src, dst)
            if state == 'indeterminate':
                journal.set_stage('needs_recovery')
                raise GovernanceError('RECOVERY_REQUIRED', '资源侧迁移结果不可判定',
                                      source=str(src), target=str(dst))
            if state == 'todo':
                Path(dst).parent.mkdir(parents=True, exist_ok=True)
                src.rename(dst)
            if hash_tree(dst) != inventory[str(src)]:
                journal.set_stage('needs_recovery')
                raise GovernanceError('STATE_CONFLICT', '资源侧迁移前后内容不一致', path=str(dst))
        journal.record('resources_moved', {'done': True})

    if not _phase_done(journal, 'records_updated'):
        journal.record('records_updated', {'intent': True})
        rewrite_external_links(root, pairs)
        finish()
        registry = loc.runtime(root) / 'state' / 'workspace' / REGISTRY_NAME
        mappings = json.loads(registry.read_text(encoding='utf-8')) if registry.exists() else []
        for src, dst in pairs:
            entry = {'source': str(src), 'target': str(dst), 'identity': identity,
                     'generation': len(mappings), 'operation_id': journal.data['operation_id'],
                     'reason': '受管迁移；原始执行记录保持字节不变'}
            if not any(m.get('operation_id') == entry['operation_id'] and m.get('source') == str(src)
                       for m in mappings):
                mappings.append(entry)
        save(registry, mappings)
        journal.record('records_updated', {'done': True})

    if not _phase_done(journal, 'links_verified'):
        journal.record('links_verified', {'intent': True})
        before = journal.data.get('before_links')
        if not before:
            journal.set_stage('needs_recovery')
            raise GovernanceError('RECOVERY_REQUIRED', '缺少迁移前链接基线，无法核验')
        baseline = {'unresolved': {tuple(x) for x in before['unresolved']},
                    'resolved': {tuple(x) for x in before['resolved']},
                    'identity': before['identity']}
        for attempt in range(20):
            after = link_state() if link_state is not None else link_snapshot(root, executable)
            try:
                checked = verify_links(baseline, after, source, target)
                break
            except GovernanceError:
                if link_state is not None or attempt == 19:
                    raise
                time.sleep(.25)
        journal.record('links_verified', {'done': True, **checked})

    if finalize:
        finalize()
    journal.record('completed')
    return journal.data


def migrate(root, moves, finish, *, identity=None, operation_id=None, executable=None,
            mover=None, link_state=None, journal=None, new_number=None, target_project=None):
    """执行目录迁移并核验链接。finish() 在链接改写后、登记前调用。

    moves 是 [(source, target), ...]：Vault 内的一对走 Obsidian renameFile（更新
    内部链接），Vault 外的（资源侧）走普通移动并靠 rewrite_external_links 改写
    绝对路径引用。mover/link_state 是测试接缝；缺省路径下拿不到链接状态就报
    CAPABILITY_UNAVAILABLE，不静默跳过核验。
    """
    root = Path(root)
    vault = (loc.vault(root)).resolve()
    pairs = [(Path(s), Path(t)) for s, t in moves]
    if not pairs:
        raise GovernanceError('INVALID_ARGUMENT', '没有要迁移的路径')
    vault_pairs, side_pairs = [], []
    for source, target in pairs:
        check_same_volume(source, target)
        if any(p.is_symlink() or p.is_junction() for p in source.rglob('*')) and source.exists():
            raise GovernanceError('PATH_OUTSIDE_ROOT', '源目录包含链接，不能安全迁移')
        (vault_pairs if source.resolve().is_relative_to(vault) else side_pairs).append((source, target))
    if len(vault_pairs) != 1:
        raise GovernanceError('INVALID_ARGUMENT', '需且仅需一个 Vault 内的目录迁移',
                              vault_moves=len(vault_pairs))
    journal = journal or MigrationJournal(root, operation_id or digest(f'{pairs[0]}{time.time()}'.encode()))
    journal.data['identity'] = identity
    return _advance(root, pairs, journal, identity=identity, finish=finish,
                    executable=executable, mover=mover, link_state=link_state,
                    new_number=new_number, target_project=target_project)
