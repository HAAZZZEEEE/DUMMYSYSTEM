"""治理资料收拢：一次迁移一个分区，沿用 Obsidian、Operation 与恢复协议。"""

from dummysys_core import locations as loc
import json
import os
from pathlib import Path

from . import _migration as migration
from .layout import governance_paths, manifest, LEGACY, DESTINATIONS
from .operations import GovernanceError, atomic_write, digest, payload, safe_target, save


def files(root):
    paths = set(migration.tracked_files(root))
    # 本机设置仅纳入本动作会修改的键所在文件，不采集其他应用配置。
    paths.update(loc.resolve(root, p) for p in ('.dummysys-docs.json', 'dmy_vault/.obsidian/templates.json',
                                    'runtime/state/workspace/retired-paths.json', 'AGENTS.md'))
    return sorted(paths)


def inventory(root):
    return {loc.relative(root, p).as_posix(): digest(payload(p)) for p in files(root)}


def _original(ws, operation):
    record = ws.operations.show(operation)
    if record.get('action') != 'governance.relocate' or record['status'] != 'completed':
        raise GovernanceError('INVALID_ARGUMENT', '只能回滚已完成的治理分区迁移')
    folder = ws.operations.base / operation
    journal = migration.MigrationJournal(ws.root, operation).load()
    if not journal.get('governance_after') or not journal.get('governance_before'):
        raise GovernanceError('RECOVERY_REQUIRED', '迁移缺少完整前后快照，保留现场')
    for relative, item in journal['governance_before'].items():
        safe_target(ws.root, relative)
        backup = folder / item['blob']
        if backup.parent != folder or item['sha256'] is not None and digest(payload(backup)) != item['sha256']:
            raise GovernanceError('RECOVERY_CORRUPT', '回滚快照损坏', path=relative)
    return record, folder, journal


def plan(ws, action, params, actor):
    root = ws.root
    project = ws.project(params['project'])
    if project.get('deleted_at') or project.get('status') != 'active':
        raise GovernanceError('STATE_CONFLICT', '治理归属项目必须处于 active')
    if action == 'governance.relocate':
        section = params['section']
        if section not in LEGACY:
            raise GovernanceError('INVALID_ARGUMENT', '未知治理分区')
        declared = manifest(root).get('governance', {})
        if declared.get('project_id', project['project_id']) != project['project_id']:
            raise GovernanceError('STATE_CONFLICT', '治理分区不能拆分到不同项目')
        source = governance_paths(root)[section]
        target = Path(project['document']).parent / DESTINATIONS[section]
    else:
        original, _, journal = _original(ws, params['operation'])
        def content(state):
            # 逆序回滚自身会追加历史路径记录；它不是用户正文修改。
            return {k: v for k, v in state.items() if k != 'runtime/state/workspace/retired-paths.json'}
        if content(inventory(root)) != content(journal['governance_after']):
            raise GovernanceError('RECOVERY_CONFLICT', '迁移后文档或配置已有修改；不覆盖后续工作')
        previous = original['plan']
        if previous['project_id'] != project['project_id']:
            raise GovernanceError('INVALID_ARGUMENT', '回滚项目与原迁移不符')
        section = previous['section']
        source, target = Path(previous['docs_target']), Path(previous['docs_source'])
    migration.check_paths(root, source, target)
    value = dict(action=action, project_id=project['project_id'], section=section,
                 docs_source=str(source), docs_target=str(target), actor=actor,
                 operation=params.get('operation'), reason=params['reason'])
    dependency = inventory(root)
    return dict(plan=value, dependency=dependency,
                plan_token=migration.compute_plan_token(value, dependency), dry_run=True)


def _hardlink(root, canonical, allowed):
    entry = root / 'AGENTS.md'
    temporary = root / '.dmy-agents-link'
    if any(loc._linked(path) for path in (entry, canonical, temporary)):
        raise GovernanceError('PATH_OUTSIDE_ROOT', '根规则与临时入口不能是符号链接或目录链接')
    if not canonical.is_file():
        raise GovernanceError('RECOVERY_REQUIRED', '治理指令正文缺失', path=str(canonical))
    if entry.exists() and entry.samefile(canonical):
        return
    if digest(payload(entry)) not in {*allowed, digest(payload(canonical)), None}:
        raise GovernanceError('RECOVERY_CONFLICT', '根 AGENTS 已独立修改，拒绝覆盖')
    if temporary.exists():
        if not temporary.samefile(canonical) and temporary.read_text(encoding='utf-8') != loc.entry_pointer(root, canonical):
            raise GovernanceError('RECOVERY_CONFLICT', '根指令临时链接被占用')
    else:
        try:
            os.link(canonical, temporary)
        except OSError as error:
            import errno
            if error.errno != errno.EXDEV and getattr(error, 'winerror', None) != 17:
                raise
            temporary.write_text(loc.entry_pointer(root, canonical), encoding='utf-8')
    os.replace(temporary, entry)


def _finish(ws, value, journal):
    root = ws.root
    before = journal.data['governance_before']
    if value['action'] == 'governance.rollback':
        _, folder, previous = _original(ws, value['operation'])
        for relative, item in previous['governance_before'].items():
            if relative == 'AGENTS.md':
                continue
            path = safe_target(root, relative)
            if item['sha256'] is None:
                path.unlink(missing_ok=True)
            else:
                backup = folder / item['blob']
                data = payload(backup) if backup.parent == folder else None
                if data is None or digest(data) != item['sha256']:
                    raise GovernanceError('RECOVERY_CORRUPT', '回滚快照损坏', path=relative)
                atomic_write(path, data)
        _hardlink(root, governance_paths(root)['instructions'], [before.get('AGENTS.md', {}).get('sha256')])
        return
    config = manifest(root)
    section = value['section']
    declared = config.setdefault('governance', {'project_id': value['project_id'], 'sections': []})
    if section not in declared['sections']:
        declared['sections'].append(section)
    # 显式路径维护映射随分区迁移；不改写 runtime 原始执行证据。
    old = loc.relative(root, Path(value['docs_source'])).as_posix()
    new = loc.relative(root, Path(value['docs_target'])).as_posix()
    config = json.loads(json.dumps(config, ensure_ascii=False).replace(old + '/', new + '/'))
    save(root / '.dummysys-docs.json', config)
    if section == 'templates':
        path = loc.vault(root) / '.obsidian/templates.json'
        current = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
        current['folder'] = Path(value['docs_target']).relative_to(loc.vault(root)).as_posix()
        save(path, current)
    if section == 'system':
        _hardlink(root, governance_paths(root)['instructions'], [before.get('AGENTS.md', {}).get('sha256')])


def execute(ws, action, params, actor, request_id, if_version, if_plan, checkpoint=None):
    root = ws.root
    def build():
        return plan(ws, action, params, actor)
    def validate():
        if build()['plan_token'] != if_plan:
            raise GovernanceError('PLAN_CONFLICT', '治理迁移计划已过期，请重新预演')
    def run(journal):
        value = journal.data['plan']
        if 'governance_before' not in journal.data:
            snapshots = {}
            for index, path in enumerate(files(root)):
                data = payload(path)
                blob = f'governance-{index}.before'
                if data is not None:
                    atomic_write(journal.folder / blob, data)
                snapshots[loc.relative(root, path).as_posix()] = dict(sha256=digest(data), blob=blob)
            journal.data['governance_before'] = snapshots
            save(journal.path, journal.data)
        # 重试只检查已完成相位，不重放 Obsidian 的外部移动。
        migration._advance(root, [(value['docs_source'], value['docs_target'])], journal,
            identity=value['project_id'], finish=lambda: _finish(ws, value, journal),
            executable=getattr(ws, '_obsidian_executable', None),
            mover=getattr(ws, '_mover', None), link_state=getattr(ws, '_link_state', None),
            finalize=lambda: journal.data.update(governance_after=inventory(root)))
        return dict(section=value['section'], source=value['docs_source'], target=value['docs_target'],
                    snapshot=str(journal.path), rollback='governance rollback --operation ' + journal.data['operation_id'])
    return ws.operations.execute_migration(action, params, actor, run, request_id=request_id,
        version=lambda: ws.version('project', params['project']), expected_version=if_version,
        if_plan=if_plan, plan=lambda: build()['plan'], validate=validate, checkpoint=checkpoint)
