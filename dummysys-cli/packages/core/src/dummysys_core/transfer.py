"""项目离线资料包：显式清单、稳定身份、内容校验与受管导入。"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat
import tempfile
import unicodedata
import zipfile

from . import locations as loc, _records as records, _repositories as repos
from ._frontmatter import parse
from ._paths import task_dirs, project_readmes
from .layout import governance_paths
from .operations import GovernanceError, digest, workspace_lock, safe_target, native_path

FORMAT = 'dummysys-project'
MAX_FILES = 20000
MAX_FILE = 64 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
EXCLUDED = {'.git', '.obsidian', '.venv', 'venv', 'envs', '__pycache__', 'node_modules',
            'cache', 'caches', '.cache', '.pytest_cache', '.mypy_cache', '.ruff_cache',
            '.env', 'credentials.json', 'profiles.json', 'id_rsa', 'id_ed25519'}
RESERVED = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}


def invalid(message, **details):
    raise GovernanceError('INVALID_ARGUMENT', message, **details)


def portable_path(value):
    if not isinstance(value, str) or not value or value != unicodedata.normalize('NFC', value):
        invalid('包内路径须为非空 NFC 名称')
    parts = value.split('/')
    if any(not part or part in ('.', '..') or len(part) > 240 or part.endswith((' ', '.'))
           or re.search(r'[<>:"\\|?*\x00-\x1f]', part) or part.split('.')[0].upper() in RESERVED for part in parts):
        invalid('包内路径包含不可移植名称或越级路径', path=value)
    return PurePosixPath(value)


def metadata(data):
    return parse(data.decode('utf-8-sig').replace('\r\n', '\n'))[0]


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def _file_data(path):
    path = native_path(path)
    if not stat.S_ISREG(path.stat().st_mode) or path.stat().st_size > MAX_FILE:
        invalid('单文件超过资料包大小限制', path=str(path), maximum=MAX_FILE)
    with path.open('rb') as stream:
        data = stream.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        invalid('读取期间文件超过大小限制')
    return data


def _collision_names(names):
    seen = {}
    for name in names:
        parts = portable_path(name).parts
        for i in range(1, len(parts) + 1):
            prefix = '/'.join(parts[:i])
            key = prefix.casefold()
            if key in seen and seen[key] != prefix:
                invalid('包内存在大小写或 Unicode 路径碰撞', path=name)
            seen[key] = prefix
    files = set(names)
    if any('/'.join(PurePosixPath(name).parts[:i]) in files
           for name in files for i in range(1, len(PurePosixPath(name).parts))):
        invalid('包内文件与目录名称冲突')


def read_bundle(path):
    """先验证中央目录、大小与文件清单，再读取有界内容；不使用 extractall。"""
    path = Path(path)
    if not path.is_absolute() or not path.is_file() or loc._linked(path):
        invalid('资料包须为明确的本机绝对文件路径')
    if path.stat().st_size > MAX_TOTAL + MAX_FILES * 1024:
        invalid('资料包文件本身超过大小限制')
    try:
        with path.open('rb') as source:
            identity = hashlib.file_digest(source, 'sha256').hexdigest()
            source.seek(0)
            with zipfile.ZipFile(source) as archive:
                infos = archive.infolist()
                names = [item.filename for item in infos]
                if len(names) != len(set(names)) or len(names) > MAX_FILES + 1 or 'manifest.json' not in names:
                    invalid('资料包文件重复、数量超限或缺少清单')
                _collision_names(names)
                total = 0
                for item in infos:
                    mode = item.external_attr >> 16
                    if (item.is_dir() or stat.S_IFMT(mode) not in (0, stat.S_IFREG)
                            or item.flag_bits & 1 or item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                        invalid('资料包不允许链接、特殊文件、目录条目或加密文件')
                    if item.file_size > (1024 * 1024 if item.filename == 'manifest.json' else MAX_FILE):
                        invalid('资料包单文件超过限制')
                    total += item.file_size
                if total > MAX_TOTAL:
                    invalid('资料包解压总量超过限制', maximum=MAX_TOTAL)
                manifest = json.loads(archive.read('manifest.json'))
                if not isinstance(manifest, dict) or manifest.get('format') != FORMAT or manifest.get('format_version') != 1:
                    invalid('不支持的资料包格式或版本；保留原包，不自动升级')
                declared = manifest.get('files')
                if not isinstance(declared, dict) or set(declared) != set(names) - {'manifest.json'}:
                    invalid('资料包清单与实际文件不一致')
                files = {}
                for name, entry in declared.items():
                    if not isinstance(entry, dict) or type(entry.get('size')) is not int or not re.fullmatch('[0-9a-f]{64}', str(entry.get('sha256', ''))):
                        invalid('资料包文件校验字段无效')
                    with archive.open(name) as stream:
                        data = stream.read(MAX_FILE + 1)
                    if len(data) != entry['size'] or digest(data) != entry['sha256']:
                        invalid('资料包文件大小或哈希不匹配', path=name)
                    files[name] = data
            source.seek(0)
            if hashlib.file_digest(source, 'sha256').hexdigest() != identity:
                invalid('读取期间资料包发生变化')
        return manifest, files, identity
    except (zipfile.BadZipFile, UnicodeError, json.JSONDecodeError, RuntimeError, RecursionError) as error:
        raise GovernanceError('INVALID_ARGUMENT', '资料包损坏或无法解析；未导入任何内容') from error


def export_project(ws, project, output=None, *, include_resource=(), dry_run=False):
    with workspace_lock(ws.root):
        if ws.operations.pending():
            raise GovernanceError('RECOVERY_REQUIRED', '导出前先处理待恢复操作')
        current = ws.project(project)
        docs, resource = records.paired(ws.root, current['name'])
        tasks = ws.tasks(current['project_id'])
        runs = [run for task in tasks for run in ws.runs(task['task_id'])]
        if any(run.get('status') in ('planned', 'running') for run in runs):
            raise GovernanceError('STATE_CONFLICT', '项目存在未结束 Run，停止写入并结束 Run 后再导出')
        files, originals, omitted, dependencies, evidence_files = {}, {}, [], [], []

        def add(path, base, prefix, *, required=False):
            physical = native_path(path)
            if not physical.exists():
                dependencies.append(dict(kind='missing_file', reference=str(path)))
                return
            if loc._linked(physical) or any(loc._linked(native_path(parent)) for parent in path.parents if parent.is_relative_to(base)):
                invalid('导出子树含链接，不能打包', path=str(path))
            relative = path.relative_to(base)
            local_tree = any(native_path(parent / '.git').exists() or native_path(parent / 'pyvenv.cfg').exists()
                             for parent in (path, *path.parents) if parent.is_relative_to(base) and native_path(parent).is_dir())
            if (local_tree or any(part.casefold() in EXCLUDED or part.casefold().startswith('.env.') for part in relative.parts)
                    or path.suffix.lower() in ('.pem', '.key', '.pyc', '.pyo')):
                if required:
                    invalid('受管记录名称落入排除范围')
                omitted.append(dict(path=str(path), reason='本机 checkout、环境、缓存、应用状态或凭据文件'))
                return
            if physical.is_dir():
                for child in sorted(physical.iterdir()):
                    add(path / child.name, base, prefix)
                return
            name = prefix + '/' + relative.as_posix()
            portable_path(name)
            data = _file_data(path)
            files[name] = data
            originals[path] = digest(data)
            if len(files) > MAX_FILES or sum(map(len, files.values())) > MAX_TOTAL:
                invalid('选定资料超过导出限制，请缩小资源选择范围')

        add(docs, docs, 'documents')
        add(resource / 'project.json', resource, 'resources', required=True)
        if native_path(resource / 'transfer-history').exists():
            add(resource / 'transfer-history', resource, 'resources')
        for task in tasks:
            _, task_resource, _ = records.locate_task(ws.root, task['task_id'])
            add(task_resource / 'task.json', resource, 'resources', required=True)
        for run in runs:
            record = Path(run['record'])
            add(record, resource, 'resources', required=True)
            if native_path(record.with_name('run-management.json')).exists():
                add(record.with_name('run-management.json'), resource, 'resources')
            for snapshot in run.get('repositories', []):
                reference = snapshot.get('evidence')
                if not reference:
                    continue
                relative = portable_path(reference)
                add(record.parent.joinpath(*relative.parts), resource, 'resources')
            for evidence in run.get('evidence', []):
                p = Path(evidence)
                candidates = [p] if p.is_absolute() else [record.parent / p, resource / p]
                existing = {p for p in candidates if native_path(p).exists() and p.is_relative_to(resource)
                            and p.resolve().is_relative_to(resource.resolve())}
                if len(existing) == 1:
                    selected = next(iter(existing))
                    add(selected, resource, 'resources')
                    evidence_files.append(dict(run_id=run['run_id'], reference=evidence,
                                               path='resources/' + selected.relative_to(resource).as_posix()))
                else:
                    dependencies.append(dict(kind='evidence', run_id=run['run_id'], reference=evidence))
        for relative in include_resource:
            path = portable_path(relative)
            target = resource.joinpath(*path.parts)
            if not native_path(target).exists():
                invalid('显式选择的资源不存在', path=relative)
            add(target, resource, 'resources')
        references = list(current['binding'].get('repositories', []))
        for task in tasks:
            references.extend(ws.task(task['task_id'])['binding'].get('repositories', []))
        known = repos.catalog(ws.root)
        for key in sorted({ref['repo_id'] for ref in references if ref.get('repo_id')}):
            if key not in known:
                invalid('项目引用的 Repo 未登记', repo_id=key)
            add(loc.resolve(ws.root, known[key]['document']), governance_paths(ws.root)['repositories'], 'repositories')
            dependencies.append(dict(kind='repo_checkout', repo_id=key))
        for name, data in list(files.items()):
            if not name.startswith(('documents/', 'repositories/')) or not name.endswith('.md'):
                continue
            body = data.decode('utf-8-sig')
            for raw in re.findall(r'\[\[(.*?)\]\]', body):
                link = raw.split('|', 1)[0].split('#', 1)[0].strip()
                if link.startswith('80-附件/'):
                    p = loc.vault(ws.root).joinpath(*portable_path(link).parts)
                    add(p, loc.vault(ws.root) / '80-附件', 'attachments')
                elif link.startswith(('20-知识/', '30-项目/')) and not link.startswith(docs.relative_to(loc.vault(ws.root)).as_posix() + '/'):
                    dependencies.append(dict(kind='wiki_link', reference=link))
            for link in re.findall(r'(?<!!)\]\(([^)]+)\)|!\[[^\]]*\]\(([^)]+)\)', body):
                reference = next(value for value in link if value).strip('<>')
                if re.match(r'^(?:[a-zA-Z][\w+.-]*:|/|\\\\|\.\./)', reference):
                    dependencies.append(dict(kind='document_link', document=name, reference=reference))
        # 未选择的资源只登记入口，不遍历环境、缓存或大目录。
        def omitted_tree(path):
            if path in originals:
                return
            included = any(p.is_relative_to(path) for p in originals)
            if not included:
                omitted.append(dict(path=str(path), reason='未选择的项目资源；可用 --include-resource 显式收入'))
            elif native_path(path).is_dir() and not loc._linked(native_path(path)):
                for child in sorted(native_path(path).iterdir()):
                    omitted_tree(path / child.name)
        for child in sorted(native_path(resource).iterdir()):
            omitted_tree(resource / child.name)
        _collision_names(files)
        for path, expected in originals.items():
            if digest(_file_data(path)) != expected:
                raise GovernanceError('VERSION_CONFLICT', '导出期间来源变化；停止写入后重试')
        manifest = dict(format=FORMAT, format_version=1, created_at=records.now(),
                        project_id=current['project_id'], project_name=current['name'],
                        archived=docs.parent.name == 'archive',
                        source=dict(workspace=str(ws.root), **loc.load(ws.root).as_dict()),
                        dependencies=dependencies, omitted=omitted, evidence_files=evidence_files,
                        files={name: dict(size=len(data), sha256=digest(data)) for name, data in files.items()})
        if len(json_bytes(manifest)) > 1024 * 1024 or sum(map(len, files.values())) + len(json_bytes(manifest)) > MAX_TOTAL:
            invalid('清单或资料总量超过读取限制，请缩小导出范围')
        result = dict(project_id=current['project_id'], files=len(files), bytes=sum(map(len, files.values())),
                      dependencies=dependencies, omitted=omitted, dry_run=dry_run)
        if dry_run:
            return result
        if output is None or not Path(output).is_absolute():
            invalid('导出必须提供 --output 绝对路径')
        output = Path(output)
        if output.exists() or loc._linked(output) or output.resolve().is_relative_to(loc.vault(ws.root)) or output.resolve().is_relative_to(resource):
            invalid('导出目标已存在或位于当前项目/正文内；不会覆盖', path=str(output))
        output.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.dmy-export-', dir=output.parent)
        os.close(fd)
        try:
            with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('manifest.json', json_bytes(manifest))
                for name, data in files.items():
                    archive.writestr(name, data)
            # 同目录发布，硬链接具有目标已存在则拒绝的语义；不覆盖竞争者文件。
            os.link(temporary, output)
        finally:
            Path(temporary).unlink(missing_ok=True)
        with output.open('rb') as stream:
            identity = hashlib.file_digest(stream, 'sha256').hexdigest()
        return dict(result, output=str(output), sha256=identity)


def _foreign_path(value):
    """解析来源机器路径；Windows 路径在 macOS 上也保留其语义。"""
    if not isinstance(value, str):
        invalid('来源路径必须是字符串')
    return PureWindowsPath(value) if re.match(r'^(?:[a-zA-Z]:|\\\\)', value) else PurePosixPath(value)


def _managed_kind(path):
    from ._paths import TASK_PATTERN
    parts = PurePosixPath(path).parts
    if path == 'resources/project.json':
        return 'project'
    if len(parts) < 3 or parts[0] != 'resources' or not re.fullmatch(TASK_PATTERN, parts[1]):
        return None
    if len(parts) == 3 and parts[2] == 'task.json':
        return 'task'
    if len(parts) == 5 and parts[2] == 'runs':
        return {'run.json': 'run', 'run-management.json': 'management'}.get(parts[4])
    return None


def _package(manifest, files):
    name = manifest.get('project_name')
    if len(portable_path(name).parts) != 1 or name in ('archive', '00-Playground'):
        invalid('不允许导入保留项目或多级项目名称')
    if type(manifest.get('archived')) is not bool:
        invalid('资料包缺少归档位置声明')
    try:
        project = json.loads(files['resources/project.json'])
        props = metadata(files['documents/README.md'])
        pid = manifest['project_id']
        if not records.valid_id(pid) or props.get('project_id') != pid or project.get('project_id') != pid:
            invalid('项目身份与清单不一致')
        if project.get('schema_version') != 1:
            invalid('不支持的项目记录格式版本')
        watermark = project.get('task_number_high_watermark', 0)
        if type(watermark) is not int or watermark < 0:
            invalid('项目 Task 编号高水位必须为非负整数')
        identities = {pid}
        for path, data in files.items():
            parts = PurePosixPath(path).parts
            if len(parts) < 2 or parts[0] not in ('documents', 'resources', 'repositories', 'attachments'):
                invalid('未知资料分区', path=path)
            if parts[0] == 'repositories':
                if len(parts) != 2 or parts[1] != repos.repo_key(metadata(data).get('repo_id')) + '.md':
                    invalid('Repo 文档身份与名称不一致')
            kind = _managed_kind(path)
            if kind == 'management':
                sidecar = json.loads(data)
                run = json.loads(files[str(PurePosixPath(path).with_name('run.json'))])
                if (len(parts) != 5 or parts[2] != 'runs' or not isinstance(sidecar, dict)
                        or sidecar.get('schema_version') != 1 or sidecar.get('run_id') != run.get('run_id')):
                    invalid('Run 管理记录格式、版本或身份不匹配')
                for key in ('display_title', 'deleted_at', 'deleted_by', 'delete_reason', 'delete_operation_id',
                            'archived_at', 'archived_by', 'archive_reason', 'archive_operation_id'):
                    if sidecar.get(key) is not None and not isinstance(sidecar[key], str):
                        invalid('Run 管理字段须为文本或空值', field=key)
            if kind in ('task', 'run'):
                record = json.loads(data)
                expected = 3 if kind == 'task' else 5
                if len(parts) != expected or (kind == 'run' and parts[2] != 'runs'):
                    invalid('受管记录位置无效', path=path)
                identity = record.get(kind + '_id')
                if not records.valid_id(identity) or identity in identities:
                    invalid('资料包身份重复或无效', path=path)
                identities.add(identity)
                if record.get('schema_version') != 1:
                    invalid('不支持的受管记录格式版本', path=path)
                if kind == 'task':
                    from ._paths import TASK_PATTERN
                    number = re.fullmatch(TASK_PATTERN, parts[1])
                    if not number or ('task_number_high_watermark' in project and int(number[1]) > watermark):
                        invalid('Task 名称或项目编号高水位不一致')
                    scope = record['scope']
                    for key in ('read_paths', 'write_paths', 'remote_resources'):
                        if not isinstance(scope.get(key), list):
                            invalid('Task 范围字段须为列表', field=key)
                    if any(not isinstance(p, str) for key in ('read_paths', 'write_paths') for p in scope[key]):
                        invalid('Task 本机范围须为路径字符串')
                else:
                    if not isinstance(record.get('evidence'), list) or any(not isinstance(p, str) for p in record['evidence']):
                        invalid('Run 证据须为字符串列表')
                if kind == 'run' and record.get('status') not in ('completed', 'failed', 'cancelled'):
                    invalid('资料包包含未结束 Run')
            if Path(path).suffix in ('.md', '.json'):
                data.decode('utf-8')  # 普通执行器按文本处理这些扩展名。
        source = manifest['source']
        for key in ('workspace', 'vault_root', 'runtime_root'):
            if not _foreign_path(source[key]).is_absolute():
                invalid('来源根目录不是绝对路径')
        for entry in manifest.get('evidence_files', []):
            if entry['run_id'] not in identities or not isinstance(entry['reference'], str):
                invalid('证据映射身份或引用无效')
            if portable_path(entry['path']).parts[0] != 'resources':
                invalid('证据映射不能越出项目资源')
        return name, pid, identities
    except (KeyError, ValueError, TypeError, AttributeError) as error:
        if isinstance(error, GovernanceError):
            raise
        raise GovernanceError('INVALID_ARGUMENT', '资料包记录缺失、身份无效或内容无法解析') from error


def _import_plan(ws, manifest, files, identity, actor, repo_paths):
    name, pid, identities = _package(manifest, files)
    docs_base = 'dmy_vault/30-项目/' + ('archive/' if manifest['archived'] else '') + name
    resource_base = 'runtime/project_src/' + name
    for project in ws.projects():
        if project.get('project_id') in identities or Path(project['document']).parent.name == name:
            raise GovernanceError('STATE_CONFLICT', '目标已有相同项目身份或名称；不会合并覆盖')
    for task in ws.tasks():
        if task.get('task_id') in identities or any(run.get('run_id') in identities for run in ws.runs(task['task_id'])):
            raise GovernanceError('STATE_CONFLICT', '目标已有相同 Task 或 Run 身份')
    for base in (docs_base, 'dmy_vault/30-项目/' + name, 'dmy_vault/30-项目/archive/' + name, resource_base):
        if safe_target(ws.root, base).exists():
            raise GovernanceError('STATE_CONFLICT', '目标项目目录已存在；不会覆盖', path=base)
    prefixes = dict(documents=docs_base, resources=resource_base,
                    attachments='dmy_vault/80-附件',
                    repositories=loc.relative(ws.root, governance_paths(ws.root)['repositories']).as_posix())
    targets, reused = {}, []
    for path, data in files.items():
        section, relative = path.split('/', 1)
        target = prefixes[section] + '/' + relative
        existing = safe_target(ws.root, target)
        if native_path(existing).exists():
            if section not in ('attachments', 'repositories') or not native_path(existing).is_file() or native_path(existing).read_bytes() != data:
                raise GovernanceError('STATE_CONFLICT', '目标文件冲突；不会覆盖', path=target)
            reused.append(path)
        targets[path] = target
    bindings = {}
    packaged = {metadata(data)['repo_id'] for path, data in files.items() if path.startswith('repositories/')}
    local = repos.mappings(ws.root)['checkouts']
    for entry in repo_paths:
        key, sep, value = entry.partition('=')
        if not sep or key in bindings or key not in packaged:
            invalid('--repo-path 须为资料包引用的唯一 repo_id=绝对路径')
        path = str(repos.checkout_root(value))
        if key in local and Path(local[key]['path']).resolve() != Path(path):
            raise GovernanceError('STATE_CONFLICT', '已有 Repo 本机绑定不同；导入不修改其他项目的绑定', repo_id=key)
        bindings[key] = path
    # 对共享 Repo 身份不偷偷改名；未绑定允许资料落盘，后续上下文会明确报告缺项。
    missing_repos = sorted(packaged - set(local) - set(bindings))
    from .operations import inventory
    dependency = digest(json_bytes({k: digest(v) for k, v in inventory(ws.root).items()}))
    plan = dict(archive_sha256=identity, project_id=pid, project_name=name,
                locations=loc.load(ws.root).as_dict(), targets=targets, reused=reused,
                repo_bindings=bindings, missing_repos=missing_repos,
                dependencies=manifest.get('dependencies', []), omitted=manifest.get('omitted', []),
                actor=actor, dependency=dependency)
    return dict(plan=plan, plan_token=digest(json_bytes(plan)), dry_run=True)


def plan_import(ws, bundle, *, actor, repo_paths=()):
    manifest, files, identity = read_bundle(bundle)
    with workspace_lock(ws.root):
        if ws.operations.pending():
            raise GovernanceError('RECOVERY_REQUIRED', '导入预演不自动恢复或提交其他操作；先显式处理未决操作')
        return _import_plan(ws, manifest, files, identity, actor, repo_paths)


def _materialize(stage, manifest, files, plan):
    """只改当前绑定字段；原始资料及差异放入独立导入收据。"""
    name = plan['project_name']
    docs = loc.resolve(stage, next(v.rsplit('/', 1)[0] for k, v in plan['targets'].items() if k == 'documents/README.md'))
    resource = loc.runtime(stage) / 'project_src' / name
    source = manifest['source']
    old_docs = _foreign_path(source['vault_root']) / '30-项目'
    if manifest['archived']:
        old_docs /= 'archive'
    old_docs /= name
    old_resource = _foreign_path(source['runtime_root']) / 'project_src' / name
    changes, unresolved = [], []
    def mapped(value):
        old = _foreign_path(value)
        for previous, target in ((old_docs, docs), (old_resource, resource)):
            if old.is_relative_to(previous):
                relative = old.relative_to(previous)
                # 不让来源字符串把当前权限扩大到项目之外。
                portable_path(relative.as_posix()) if relative.parts else None
                return str(target.joinpath(*relative.parts))
        return None
    for path, data in files.items():
        if path in plan['reused']:
            continue
        target = loc.resolve(stage, plan['targets'][path])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    for path, data in files.items():
        kind = _managed_kind(path)
        if kind not in ('project', 'task', 'run'):
            continue
        target = loc.resolve(stage, plan['targets'][path])
        value = json.loads(data)
        if target.name == 'task.json':
            scope = value.get('scope', {})
            for key in ('read_paths', 'write_paths'):
                replacement = []
                for old in scope.get(key, []):
                    new = mapped(old)
                    if new:
                        replacement.append(new)
                    else:
                        unresolved.append(dict(kind='scope', record=path, field=key, reference=old))
                scope[key] = replacement
            for old in scope.get('remote_resources', []):
                unresolved.append(dict(kind='remote_scope', record=path, reference=old))
            scope['remote_resources'] = []
            value['scope'] = scope
        if target.name in ('project.json', 'task.json'):
            kept = []
            for ref in value.get('repositories', []):
                if ref.get('repo_id'):
                    kept.append(ref)
                else:
                    unresolved.append(dict(kind='legacy_repo', record=path, reference=ref))
            if 'repositories' in value:
                value['repositories'] = kept
        if target.name == 'run.json':
            evidence = []
            for old in value.get('evidence', []):
                match = next((entry for entry in manifest.get('evidence_files', [])
                              if entry['run_id'] == value['run_id'] and entry['reference'] == old), None)
                new = str(resource.joinpath(*PurePosixPath(match['path']).parts[1:])) if match else mapped(old)
                if not new and not _foreign_path(old).is_absolute():
                    relative = PurePosixPath(path).parent / old.replace('\\', '/')
                    if relative.as_posix() in files:
                        new = str(loc.resolve(stage, plan['targets'][relative.as_posix()]))
                if new and Path(new).exists():
                    evidence.append(new)
                else:
                    # 外部原路径保留在原件和收据；当前引用明确标为未搬入。
                    evidence.append('external:' + old if _foreign_path(old).is_absolute() else old)
                    unresolved.append(dict(kind='evidence', record=path, reference=old))
            value['evidence'] = evidence
        target.write_bytes(json_bytes(value))
    records.initialize_project(stage, name)
    for task in task_dirs(docs):
        (resource / task.name / 'runs').mkdir(exist_ok=True, parents=True)
    for key, path in plan['repo_bindings'].items():
        repos.bind(stage, key, path)
    records.refresh(stage, name)
    receipt = resource / 'transfer-history' / plan['archive_sha256']
    if receipt.exists():
        invalid('资料包占用了本次导入收据位置')
    for path, original in files.items():
        if path in plan['reused']:
            continue
        current = loc.resolve(stage, plan['targets'][path]).read_bytes()
        if original != current:
            backup = receipt / 'originals' / (path + '.bin')
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_bytes(original)
            changes.append(dict(path=path, original_sha256=digest(original)))
    report = dict(project_id=plan['project_id'], archive_sha256=plan['archive_sha256'],
                  changes=changes, unresolved=unresolved, missing_repos=plan['missing_repos'],
                  dependencies=plan['dependencies'], omitted=plan['omitted'],
                  imported_at=records.now(), actor=plan['actor'])
    receipt.mkdir(parents=True, exist_ok=True)
    (receipt / 'manifest.json').write_bytes(json_bytes(manifest))
    (receipt / 'report.json').write_bytes(json_bytes(report))
    return dict(report, document=str(docs / 'README.md'), report=str(receipt / 'report.json'))


def import_project(ws, bundle, *, actor, request_id, if_plan, repo_paths=(), checkpoint=None):
    manifest, files, identity = read_bundle(bundle)
    def prepare(stage):
        preview = _import_plan(ws, manifest, files, identity, actor, repo_paths)
        if preview['plan_token'] != if_plan:
            raise GovernanceError('PLAN_CONFLICT', '包、目标工作区或路径绑定已变化；重新预演')
        baseline = set(records.check(stage))
        try:
            result = _materialize(stage, manifest, files, preview['plan'])
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            if isinstance(error, GovernanceError):
                raise
            raise GovernanceError('INVALID_ARGUMENT', '导入记录结构无效；正式资料未写入') from error
        failures = set(records.check(stage)) - baseline
        allowed = {f'Repo 关联错误 {preview["plan"]["project_name"]}：Repo 缺少本机映射：{key}'
                   for key in preview['plan']['missing_repos']}
        if failures - allowed:
            invalid('导入记录未通过治理校验；正式资料未写入', failures=sorted(failures - allowed))
        return result
    with workspace_lock(ws.root):
        operation_id = digest((request_id or '').encode())
        if any(item['operation_id'] != operation_id for item in ws.operations.pending()):
            raise GovernanceError('RECOVERY_REQUIRED', '先显式处理其他未决操作，再导入资料')
        return ws.operations.execute('project.import', dict(bundle_sha256=identity, if_plan=if_plan, repo_paths=list(repo_paths)),
                                     actor, prepare, request_id=request_id, checkpoint=checkpoint)
