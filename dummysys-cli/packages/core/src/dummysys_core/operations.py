"""受管文件变更：工作区互斥、准备区、幂等回执和可恢复提交。

仅复制治理正文与记录；业务运行产物不进入准备区。发布计划只包含差异文件，
恢复同时核对全部目标再写入，避免覆盖另一个执行者的后续修改。
"""
from __future__ import annotations

from dummysys_core import locations as loc

from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
import ctypes
from ctypes import wintypes
import functools
import hashlib
import inspect
import json
import os
from pathlib import Path
import tempfile
import time
from uuid import uuid4

from . import __version__
from .telemetry import span, measured


class GovernanceError(ValueError):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code, self.details = code, details


def digest(data):
    return hashlib.sha256(data).hexdigest() if data is not None else None


def payload(path):
    return path.read_bytes() if path.is_file() else None


def atomic_write(path, data):
    if os.name == 'nt' and not str(path).startswith('\\\\?\\'):
        absolute = str(path.resolve())
        path = Path('\\\\?\\UNC\\' + absolute[2:] if absolute.startswith('\\\\') else '\\\\?\\' + absolute)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.dmy-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        # MoveFileEx(REPLACE_EXISTING) 在目标被无 FILE_SHARE_DELETE 打开时返回
        # ERROR_ACCESS_DENIED（Obsidian 索引器/杀软/并发读者）。退避重试；仍失败
        # 则把持有方线索写进错误，不再让 WinError 5 变成来路不明的偶发。
        last = None
        for attempt in range(5):
            try:
                os.replace(temporary, path)
                last = None
                break
            except PermissionError as error:
                last = error
                time.sleep(0.05 * (attempt + 1))
        if last is not None:
            raise GovernanceError('STATE_CONFLICT',
                                  f'目标文件被占用，无法原子替换：{path}',
                                  path=str(path), winerror=getattr(last, 'winerror', None),
                                  next_action='关闭占用该文件的进程（Obsidian 索引、杀软、并发读取）后重试')
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save(path, value):
    atomic_write(path, (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode())


_held = ContextVar('dmy_locks', default=frozenset())
_external = ContextVar('dmy_external_writer', default=False)


@contextmanager
def workspace_lock(root, timeout=15, *, snapshot_locations=True):
    key = os.path.normcase(str(Path(root).resolve()))
    if key in _held.get():
        yield
        return
    if os.name != 'nt':
        raise GovernanceError('UNSUPPORTED_PLATFORM', '受管写入仅支持 Windows')
    dll = ctypes.WinDLL('kernel32', use_last_error=True)
    dll.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    dll.CreateMutexW.restype = wintypes.HANDLE
    dll.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    dll.WaitForSingleObject.restype = wintypes.DWORD
    dll.ReleaseMutex.argtypes = [wintypes.HANDLE]
    dll.ReleaseMutex.restype = wintypes.BOOL
    dll.CloseHandle.argtypes = [wintypes.HANDLE]
    dll.CloseHandle.restype = wintypes.BOOL
    handle = dll.CreateMutexW(None, False, 'Global\\DUMMYSYS-' + digest(key.encode()))
    if not handle:
        raise GovernanceError('LOCK_FAILED', f'创建工作区互斥量失败：{ctypes.get_last_error()}')
    acquired = False
    try:
        with span('lock_wait'):
            result = dll.WaitForSingleObject(handle, int(timeout * 1000))
        if result not in (0, 0x80):  # abandoned mutex still grants ownership
            code = 'LOCK_BUSY' if result == 0x102 else 'LOCK_FAILED'
            raise GovernanceError(code, '工作区正在写入或互斥量不可用，请稍后重试')
        acquired = True
        token = _held.set(_held.get() | {key})
        try:
            with loc.snapshot(Path(root).resolve()) if snapshot_locations else nullcontext():
                yield
        finally:
            _held.reset(token)
    finally:
        if acquired:
            dll.ReleaseMutex(handle)
        dll.CloseHandle(handle)


def safe_target(root, relative):
    root = Path(root).resolve()
    p = Path(relative)
    if p.is_absolute() or '..' in p.parts or ':' in str(relative):
        raise GovernanceError('PATH_OUTSIDE_ROOT', '操作路径必须在工作区内', path=str(relative))
    target = loc.resolve(root, p)
    boundary = loc.boundary(root, p)
    if not target.resolve().is_relative_to(boundary):
        raise GovernanceError('PATH_OUTSIDE_ROOT', '目录链接越出资料根', path=str(target))
    if any(loc._linked(part) for part in (target, *target.parents) if part.is_relative_to(boundary)):
        raise GovernanceError('PATH_OUTSIDE_ROOT', '受管文件不能为链接', path=str(target))
    return target


def inventory(root):
    """不扫描 Run 产物和凭据；保留项目文档拓扑供导航生成。"""
    root = Path(root)
    paths = set()
    from .layout import governance_paths
    config = root / '.dummysys-docs.json'
    if config.is_file():
        paths.add(config)
    # 准备区包含定位声明及规则；否则新版路径在 stage 中无法解析。
    for base in governance_paths(root).values():
        if base.is_dir():
            paths.update(base.rglob('*.md'))
        elif base.is_file():
            paths.add(base)
    for relative in ('dmy_vault/30-项目', 'dmy_vault/10-系统/仓库'):
        base = loc.resolve(root, relative)
        if base.exists():
            paths.update(base.rglob('*.md'))
    base = loc.runtime(root) / 'project_src'
    if base.exists():
        for project in base.iterdir():
            if not project.is_dir():
                continue
            for name in ('project.json', 'README.md', 'AGENTS.md'):
                if (project / name).is_file():
                    paths.add(project / name)
            for task in project.iterdir():
                if task.is_dir() and task.name.startswith('[task '):
                    for name in ('task.json', 'README.md', 'AGENTS.md'):
                        if (task / name).is_file():
                            paths.add(task / name)
                    paths.update(task.glob('runs/*/run.json'))
                    paths.update(task.glob('runs/*/run-management.json'))
    for name in ('repositories.json', 'retired-paths.json'):
        path = loc.runtime(root) / 'state/workspace' / name
        if path.exists():
            paths.add(path)
    return {loc.relative(root, p).as_posix(): safe_target(root, loc.relative(root, p)).read_bytes()
            for p in sorted(paths) if p.is_file()}


def rebase_text(text, source, target):
    source, target = Path(source), Path(target)
    for old, new in ((loc.vault(source), loc.vault(target)), (loc.runtime(source), loc.runtime(target)), (source, target)):
        text = _replace_root(text, old, new)
    return text


def _replace_root(text, source, target):
    for a, b in ((str(source), str(target)), (source.as_posix(), target.as_posix()),
                 (json.dumps(str(source), ensure_ascii=False)[1:-1], json.dumps(str(target), ensure_ascii=False)[1:-1]),
                 (json.dumps(str(source))[1:-1], json.dumps(str(target))[1:-1])):
        text = text.replace(a, b)
    return text


class Operations:
    def __init__(self, root):
        self.root = Path(root).resolve()

    @property
    def base(self):
        return loc.runtime(self.root) / 'state/workspace/operations'

    def source_commit(self):
        manifest = loc.runtime(self.root) / 'state/workspace/cli-install.json'
        if not manifest.exists():
            return 'development-unverified'
        installed = json.loads(manifest.read_text(encoding='utf-8-sig'))
        expected = Path(installed['core_path']) / 'dummysys_core'
        if expected.resolve() != Path(__file__).resolve().parent:
            raise GovernanceError('INSTALLATION_CHANGED', '当前进程未使用登记发行，请用固定入口重启工具')
        return installed['source_commit']

    def list(self):
        return [self._load(p) for p in sorted(self.base.glob('*/operation.json'))]

    def _load(self, path):
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
        except (ValueError,OSError) as error:
            raise GovernanceError('INCOMPATIBLE_OPERATION','Operation 无法读取，请保留现场并核对原发行',path=str(path)) from error
        if not isinstance(value,dict) or value.get('schema_version') != 1 or value.get('workspace') != str(self.root):
            raise GovernanceError('INCOMPATIBLE_OPERATION', 'Operation 格式或工作区不匹配', path=str(path))
        if value['status'] not in ('completed', 'aborted'):
            expected = value.get('locations', loc.configured(self.root).as_dict())
            if expected != loc.load(self.root).as_dict():
                raise GovernanceError('INCOMPATIBLE_OPERATION', '资料位置已变化，恢复原配置后再恢复操作', path=str(path))
        return value

    def show(self, operation_id):
        if not operation_id or any(c not in '0123456789abcdef' for c in operation_id) or len(operation_id) != 64:
            raise GovernanceError('INVALID_ARGUMENT', 'Operation ID 格式错误')
        p = self.base / operation_id / 'operation.json'
        if not p.exists():
            raise GovernanceError('NOT_FOUND', 'Operation 不存在')
        return self._load(p)

    def pending(self):
        return [r for r in self.list() if r['status'] not in ('completed', 'aborted')]

    @measured('recovery')
    def recover(self, operation_id):
        with workspace_lock(self.root):
            record = self.show(operation_id)
            folder = self.base / operation_id
            if record['status'] in ('completed', 'aborted'):
                return record
            if record['tool_version'] != __version__ or record.get('source_commit') != self.source_commit():
                raise GovernanceError('INCOMPATIBLE_OPERATION', '请使用原版本恢复操作',
                                      required=record['tool_version'], source_commit=record.get('source_commit'))
            if record.get('kind') == 'migration':
                return self._recover_migration(folder, record)
            if record['status'] == 'preparing':
                record['status'] = 'aborted'  # 真实目标尚未修改，可安全重新提交同一请求。
                save(folder / 'operation.json', record)
                return record
            return self._commit(folder, record)

    def _recover_migration(self, folder, record):
        """迁移恢复：只做能确定的判定，不盲目重跑 renameFile。

        迁移的真实副作用进度在 migration.json 的 STAGES 里，operation.json 的
        status 说明不了「真实目标改没改」——所以这里**绝不**像 staged 操作那样
        把 preparing 折叠成 aborted（那会谎称「真实目标尚未修改」，而目录可能
        已半挪、重试会撞 target exists）。续做需原动作的 mover/finish 闭包，
        故由同一 request_id 重提交驱动 execute_migration 落到 _advance。
        """
        from ._migration import MigrationJournal
        journal = MigrationJournal(self.root, record['operation_id']).load()
        stage = journal.get('stage')
        if stage == 'completed':
            record['status'] = 'completed'
            record['finished_at'] = time.time()
            save(folder / 'operation.json', record)
            return record
        if stage == 'needs_recovery':
            raise GovernanceError('RECOVERY_REQUIRED',
                                  '迁移结果不可判定，须人工核对源/目标后恢复；不能盲目重跑 renameFile',
                                  operation_id=record['operation_id'], journal=str(folder))
        # 其余阶段可续做：保持 pending，等同一 request_id 重提交 roll-forward。
        return record

    def settle(self, include_archive=True, exclude_operation=None):
        if include_archive:
            for path in (loc.runtime(self.root) / 'state/workspace/archive-migrations').glob('*/manifest.json'):
                record = json.loads(path.read_text(encoding='utf-8'))
                if record.get('status') in ('prepared', 'failed'):
                    raise GovernanceError('RECOVERY_REQUIRED', '归档迁移尚未恢复，请使用原归档工具的 rollback', journal=str(path.parent))
        from ._migration import MigrationJournal
        for record in self.pending():
            if record['operation_id'] == exclude_operation:
                continue
            if record.get('kind') == 'migration':
                stage = MigrationJournal(self.root, record['operation_id']).load().get('stage')
                if stage == 'needs_recovery':
                    raise GovernanceError('RECOVERY_REQUIRED', '迁移需人工判定后恢复',
                                          operation_id=record['operation_id'])
                raise GovernanceError('RECOVERY_REQUIRED', '存在未结束迁移，先用原请求续做',
                                      operation_id=record['operation_id'])
            self.recover(record['operation_id'])

    @measured('commit')
    def _commit(self, folder, record, checkpoint=None):
        if record.get('locations', loc.configured(self.root).as_dict()) != loc.load(self.root, fresh=True).as_dict():
            raise GovernanceError('INCOMPATIBLE_OPERATION', '准备期间资料配置变化，保留现场并恢复原配置')
        # 先核对整个变更集，再逐文件提交。中断后允许目标等于 before 或 after。
        for entry in record['files']:
            target = safe_target(self.root, entry['path'])
            current = digest(payload(target))
            if current not in (entry['before'], entry['after']):
                raise GovernanceError('RECOVERY_CONFLICT', '文件已有后续修改，保留现场',
                                      operation_id=record['operation_id'], path=str(target))
            blob = folder / entry['blob']
            if blob.parent != folder or digest(blob.read_bytes()) != entry['after']:
                raise GovernanceError('RECOVERY_CORRUPT', '操作快照损坏')
        record['status'] = 'applying'
        save(folder / 'operation.json', record)
        for index, entry in enumerate(record['files']):
            target = safe_target(self.root, entry['path'])
            if digest(payload(target)) == entry['after']:
                continue
            if digest(payload(target)) != entry['before']:
                raise GovernanceError('RECOVERY_CONFLICT', '提交期间文件发生变化', path=str(target))
            atomic_write(target, (folder / entry['blob']).read_bytes())
            if checkpoint:
                checkpoint('file', index)
        for relative in record.get('directories', []):
            safe_target(self.root, relative).mkdir(parents=True, exist_ok=True)
        if any(digest(payload(safe_target(self.root, e['path']))) != e['after'] for e in record['files']):
            raise GovernanceError('RECOVERY_CONFLICT', '提交后校验不一致')
        record['status'] = 'completed'
        record['finished_at'] = time.time()
        save(folder / 'operation.json', record)
        return record

    def execute_migration(self, action, parameters, actor, run, *, request_id=None,
                          version=None, expected_version=None, if_plan=None, plan=None,
                          validate=None, checkpoint=None):
        """目录迁移专用执行器。

        与 execute() 共享 request_id 幂等与持久回执，但**不做 staged 文件记账**：
        目录移动没有文件 blob 表示，硬塞进 _commit/recover 会让语义失真。真实
        副作用进度由同目录 migration.json 的 STAGES 描述。同一 request_id 重提交
        = roll-forward（_advance 跳过已完成相位），因为首个真实移动之后 Obsidian
        已改写链接，回退会让链接失衡。
        """
        from ._migration import MigrationJournal
        request_id = request_id or str(uuid4())
        operation_id = digest(request_id.encode())
        # if_plan 必须进指纹：换一个 plan_token 重放同一 request_id 是两次不同意图。
        fingerprint = digest(json.dumps([action, parameters, actor, expected_version, if_plan],
                                       sort_keys=True, ensure_ascii=False, default=str).encode())
        with workspace_lock(self.root):
            folder = self.base / operation_id
            resuming = False
            if (folder / 'operation.json').exists():
                old = self.show(operation_id)
                if old['fingerprint'] != fingerprint:
                    raise GovernanceError('REQUEST_CONFLICT', '同一请求 ID 的参数或计划发生变化')
                journal = MigrationJournal(self.root, operation_id).load()
                stage = journal.get('stage')
                if stage == 'completed':
                    old['status'] = 'completed'
                    save(folder / 'operation.json', old)
                    return old
                if stage == 'needs_recovery':
                    raise GovernanceError('RECOVERY_REQUIRED', '迁移需人工判定后恢复',
                                          operation_id=operation_id, journal=str(folder))
                # 其余阶段：可续做，落到下面的 run(journal) 推进。
                resuming = True
            self.settle(exclude_operation=operation_id)
            if not resuming and expected_version is not None and (version is None or version() != expected_version):
                raise GovernanceError('VERSION_CONFLICT', '记录已变化，请重新查询后提交')
            if validate and not resuming:
                # 锁内、回执落盘前校验（计划过期抛 PLAN_CONFLICT），不留失败回执。
                validate()
            folder.mkdir(parents=True, exist_ok=True)
            record = old if resuming else dict(schema_version=1, tool_version=__version__, workspace=str(self.root),
                          source_commit=self.source_commit(), kind='migration',
                          operation_id=operation_id, request_id=request_id, fingerprint=fingerprint,
                          action=action, actor=actor, status='migrating', created_at=time.time(),
                          files=[], locations=loc.load(self.root).as_dict(), plan=plan() if callable(plan) else plan, if_plan=if_plan)
            save(folder / 'operation.json', record)
            if checkpoint:
                checkpoint('preparing', 0)
            journal = MigrationJournal(self.root, operation_id)
            journal.load()
            journal.data['plan'] = record['plan']
            try:
                result = run(journal)
            except Exception:
                record['status'] = 'failed'
                record['finished_at'] = time.time()
                save(folder / 'operation.json', record)
                raise
            record['status'] = 'completed'
            record['result'] = result
            record['finished_at'] = time.time()
            save(folder / 'operation.json', record)
            return record

    def execute(self, action, parameters, actor, prepare, *, request_id=None,
                version=None, expected_version=None, checkpoint=None):
        request_id = request_id or str(uuid4())
        operation_id = digest(request_id.encode())
        fingerprint = digest(json.dumps([action, parameters, actor, expected_version],
                                       sort_keys=True, ensure_ascii=False, default=str).encode())
        with workspace_lock(self.root):
            folder = self.base / operation_id
            if (folder / 'operation.json').exists():
                old = self.show(operation_id)
                if old['fingerprint'] != fingerprint:
                    raise GovernanceError('REQUEST_CONFLICT', '同一请求 ID 的参数发生变化')
                old = self.recover(operation_id)
                if old['status'] == 'completed':
                    return old
            self.settle()
            if expected_version is not None and (version is None or version() != expected_version):
                raise GovernanceError('VERSION_CONFLICT', '记录已变化，请重新查询后提交')
            folder.mkdir(parents=True, exist_ok=True)
            record = dict(schema_version=1, tool_version=__version__, workspace=str(self.root),
                          source_commit=self.source_commit(),
                          operation_id=operation_id, request_id=request_id, fingerprint=fingerprint,
                          action=action, actor=actor, status='preparing', created_at=time.time(), files=[],
                          locations=loc.load(self.root).as_dict())
            save(folder / 'operation.json', record)
            if checkpoint:
                checkpoint('preparing', 0)
            try:
                before = inventory(self.root)
                temp_root = loc.runtime(self.root) / 'tmp/dmy'
                temp_root.mkdir(parents=True, exist_ok=True)
                # 准备区再次嵌套完整工作区，会超过传统 MAX_PATH；仅文件 I/O
                # 使用扩展路径。下方 rebase_text 在发布前还原正式工作区路径。
                if os.name == 'nt' and not str(temp_root).startswith('\\\\?\\'):
                    value = str(temp_root.resolve())
                    temp_root = Path('\\\\?\\UNC\\' + value[2:] if value.startswith('\\\\') else '\\\\?\\' + value)
                with tempfile.TemporaryDirectory(prefix='prepare-', dir=temp_root) as temporary, loc.snapshot(Path(temporary)):
                    stage = Path(temporary)
                    (stage / 'dmy_vault').mkdir()
                    for relative, data in before.items():
                        path = stage / relative
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(data)
                    # 已有源码证据仅保留目录存在性，防止重建覆盖；不复制大型证据。
                    for path in loc.runtime(self.root).glob('project_src/*/[[]task *]*/runs/*/source-snapshot'):
                        if path.is_dir():
                            (stage / loc.relative(self.root, path)).mkdir(parents=True, exist_ok=True)
                    # 空 runs 目录也属于结构契约。
                    for meta in stage.glob('runtime/project_src/*/[[]task *]*/task.json'):
                        (meta.parent / 'runs').mkdir(exist_ok=True)
                    with span('prepare'):
                        result = prepare(stage)
                    files = []
                    directories = []
                    # 普通记录执行器：拒绝隐式删除——before 中存在但 stage 中消失的文件
                    stage_files = set()
                    for path in sorted(stage.rglob('*')):
                        relative = path.relative_to(stage).as_posix()
                        if path.is_dir():
                            if not loc.resolve(self.root, relative).exists():
                                directories.append(relative)
                            continue
                        stage_files.add(relative)
                        data = path.read_bytes()
                        if path.suffix in ('.md', '.json'):
                            data = rebase_text(data.decode('utf-8'), stage, self.root).encode('utf-8')
                        if data == before.get(relative):
                            continue
                        target = safe_target(self.root, relative)
                        if digest(payload(target)) != digest(before.get(relative)):
                            raise GovernanceError('VERSION_CONFLICT', '准备期间文件变化', path=str(target))
                        number = len(files)
                        if relative in before:
                            atomic_write(folder / f'{number}.before', before[relative])
                        atomic_write(folder / f'{number}.after', data)
                        files.append(dict(path=relative, before=digest(before.get(relative)),
                                          after=digest(data), blob=f'{number}.after'))
                    # 检查隐式删除：before 中有但 stage 中没有的文件
                    implicit_deletes = set(before) - stage_files
                    if implicit_deletes:
                        raise GovernanceError('INVALID_ARGUMENT',
                            '普通操作不支持隐式删除文件；迁移请使用专用执行器',
                            deleted=sorted(implicit_deletes)[:5])
                    result = json.loads(rebase_text(json.dumps(result, ensure_ascii=False, default=str), stage, self.root))
                    record.update(status='prepared', files=files, directories=directories, result=result)
                    save(folder / 'operation.json', record)
            except Exception:
                record['status'] = 'aborted'
                save(folder / 'operation.json', record)
                raise
            if checkpoint:
                checkpoint('prepared', 0)
            return self._commit(folder, record, checkpoint)


def external_writer(function):
    """归档工具保留自己的迁移日志，同时与 CLI 共用互斥协议。"""
    @functools.wraps(function)
    def wrapped(root, *args, **kwargs):
        signature = inspect.signature(function)
        if 'apply' in signature.parameters:
            bound = signature.bind(root, *args, **kwargs)
            bound.apply_defaults()
            if not bound.arguments['apply']:
                return function(root, *args, **kwargs)
        with workspace_lock(root):
            Operations(root).settle(include_archive=function.__name__ == 'migrate')
            token = _external.set(True)
            try:
                return function(root, *args, **kwargs)
            finally:
                _external.reset(token)
    return wrapped
