"""供 CLI、兼容入口和工作台复用的工作区接口。"""
from __future__ import annotations

from dummysys_core import locations as loc

import json
from pathlib import Path
import shutil
import tempfile
from functools import wraps

from . import __version__, _records as records, _repositories as repos, _entries as entries
from ._paths import project_readmes, task_dirs
from .operations import Operations, GovernanceError, digest, payload, workspace_lock, glob_paths, native_path
from .telemetry import measured
from .layout import governance_paths

# 目录迁移类动作：有目录副作用、需要两步计划，且必须走真实 Vault 根，
# 不能经 staged 记录执行器（它只按文件内容记账，表达不了目录移动）。
MIGRATION_ACTIONS = frozenset({
    'project.rename', 'task.rename', 'task.move',
    'project.archive', 'project.unarchive', 'task.archive', 'task.unarchive',
})


def read_view(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with workspace_lock(self.root):
            return method(self, *args, **kwargs)
    return wrapped


class Workspace:
    def __init__(self, root):
        self.root = Path(root).resolve()
        if not (loc.vault(self.root)).is_dir():
            raise GovernanceError('INVALID_WORKSPACE', '工作区缺少 dmy_vault', path=str(self.root))
        self.operations = Operations(self.root)

    def project_name(self, identity):
        if identity == '00-Playground':
            return identity
        matches = [p.parent.name for p in project_readmes(self.root)
                   if records.properties(p).get('project_id') == identity or p.parent.name == identity]
        if len(matches) != 1:
            raise GovernanceError('NOT_FOUND', '项目应唯一匹配', project=identity, matches=len(matches))
        return matches[0]

    def version(self, kind, identity=None, task=None):
        if kind == 'task':
            doc, resource, _ = records.locate_task(self.root, identity)
            paths = [doc, resource / 'task.json']
        elif kind == 'run':
            paths = [self.run_path(task, identity)]
        elif kind == 'project':
            doc, resource = records.paired(self.root, self.project_name(identity))
            paths = [doc / 'README.md', resource / 'project.json']
        elif kind == 'repo':
            paths = [governance_paths(self.root)['repositories'] / (repos.repo_key(identity) + '.md'), repos.mapping_path(self.root)]
        else:
            raise GovernanceError('INVALID_ARGUMENT', '未知对象种类')
        return self._paths_version(paths)

    def _paths_version(self, paths):
        return digest(json.dumps([(loc.relative(self.root, p).as_posix(), digest(payload(p)))
                                  for p in paths], ensure_ascii=False).encode())

    @read_view
    def projects(self):
        result = []
        for p in project_readmes(self.root):
            meta = records.properties(p)
            result.append(dict(meta, document=str(p), version=self.version('project', p.parent.name)))
        return result

    @read_view
    def project(self, identity):
        name = self.project_name(identity)
        doc, resource = records.paired(self.root, name)
        binding = resource / 'project.json'
        props = records.properties(doc / 'README.md')
        return dict(props, name=name, document=str(doc / 'README.md'),
                    binding=records.read_json(binding) if binding.exists() else None,
                    version=self.version('project', name),
                    **self._governance_view('project', props, props))

    @read_view
    def tasks(self, project=None):
        docs = [records.paired(self.root, self.project_name(project))[0]] if project else [p.parent for p in project_readmes(self.root)]
        return [dict(records.properties(t / 'README.md'), document=str(t / 'README.md'))
                for doc in docs for t in task_dirs(doc)]

    @read_view
    def task(self, identity):
        doc, resource, props = records.locate_task(self.root, identity)
        binding = records.read_json(resource / 'task.json')
        runs = self.runs(identity)
        open_runs = sum(1 for r in runs if r.get('status') in ('planned', 'running'))
        return dict(props, document=str(doc), binding=binding, version=self.version('task', identity),
                    runs=runs, pending_operations=self.operations.pending(),
                    **self._governance_view('task', props, props, open_runs=open_runs))

    def _governance_view(self, kind, status_source, marks, open_runs=0):
        """汇总 effective_status/blocked_reasons/allowed_actions，供 show 输出提示。

        界面据此点亮或置灰动作；写入仍由执行器重验全部前置条件。
        """
        from ._actions import allowed_actions
        from ._management import effective_status, is_deleted, is_archived
        effective, blocked = effective_status(status_source, marks)
        blocked = list(blocked)
        deleted = is_deleted(marks)
        archived = is_archived(marks)
        if open_runs and not deleted:
            blocked.append(f'存在 {open_runs} 个未结束 Run，归档或删除前需先结束')
        return {
            'effective_status': effective,
            'blocked_reasons': blocked,
            'allowed_actions': allowed_actions(kind, status_source.get('status', 'unknown'),
                                              deleted=deleted, archived=archived),
        }

    @read_view
    @measured('run_scan')
    def runs(self, task):
        _, resource, _ = records.locate_task(self.root, task)
        result = []
        seen = {}
        for path in sorted(glob_paths(resource, 'runs/*/run.json')):
            raw = payload(path)
            value = json.loads(raw)
            if not isinstance(value,dict) or not isinstance(value.get('run_id'),str) or not value['run_id']:
                raise GovernanceError('INVALID_STATE','Run 记录缺少有效身份',path=str(path))
            if value['run_id'] in seen:
                raise GovernanceError('STATE_CONFLICT','Run ID 重复，无法唯一查询或更新',run=value['run_id'],paths=[seen[value['run_id']],str(path)])
            seen[value['run_id']]=str(path)
            version = digest(json.dumps([(loc.relative(self.root, path).as_posix(), digest(raw))],
                                        ensure_ascii=False).encode())
            result.append(dict(value, record=str(path), version=version))
        return result

    def run_path(self, task, identity):
        _, resource, _ = records.locate_task(self.root, task)
        found = [p for p in glob_paths(resource, 'runs/*/run.json') if records.read_json(p).get('run_id') == identity]
        if len(found) != 1:
            raise GovernanceError('NOT_FOUND', 'Run 应唯一匹配', run=identity)
        return found[0]

    @read_view
    def run(self, task, identity):
        from ._management import read_sidecar
        path = self.run_path(task, identity)
        record = records.read_json(path)
        marks = read_sidecar(path)
        return dict(record, record=str(path), management=marks,
                    version=self.version('run', identity, task),
                    **self._governance_view('run', record, marks))

    @read_view
    def context(self, task):
        value = self.task(task)
        runs = value.pop('runs')
        pending = value.pop('pending_operations')
        doc = Path(value['document'])
        _, resource, _ = records.locate_task(self.root, task)
        missing = []
        try:
            repositories = repos.resolve(self.root, task=task)
        except (ValueError, OSError) as error:
            repositories = []
            missing.append(str(error))
        rules = governance_paths(self.root)
        project = records.paired(self.root, resource.parent.name)[0]
        entrypoints = [
            (self.root / 'AGENTS.md', '全局约束与条件路由', '开始工作'),
            (project / 'AGENTS.md', '项目定制约束与审核要求', '在所属项目工作'),
            (project / 'README.md', '背景、目标与精选正文', '需要项目背景'),
            (doc, '当前目标、范围、结论与相关报告入口', '接续此 Task'),
            (rules['protocol'], 'Task/Run、重试、恢复与文档收尾', '创建、接续或执行 Task/Run'),
            (rules['policy'], 'Vault、runtime 与 Repo 的存储边界', '选择存储位置或迁移资源'),
            (project / '目录索引.md', '完整文档清单；不代表审核通过', '需要查找非精选正文或历史'),
        ]
        body = native_path(doc).read_text(encoding='utf-8')
        goal = body.split('## 目标与完成条件', 1)[-1].split('\n## ', 1)[0].strip() if '## 目标与完成条件' in body else None
        if goal is None:
            missing.append('Task 缺少目标与完成条件段落')
        return dict(task=value, goal=goal, repositories=repositories,
                    active_runs=[{k: r.get(k) for k in ('run_id', 'title', 'status', 'actor', 'record', 'version')}
                                 for r in runs if r['status'] in ('planned', 'running')],
                    pending_operations=[{k: r.get(k) for k in ('operation_id', 'action', 'status', 'source_commit')}
                                        for r in pending],
                    reading=[{'path': str(p), 'exists': p.is_file(), 'purpose': purpose,
                              'when': when, 'source': 'governance-routing'} for p, purpose, when in entrypoints],
                    allowed_task_statuses=sorted(records.TASK_STATUSES),
                    missing=missing, queried_at=records.now(),
                    coverage='仅查询当前记录与阅读入口；不替代规则阅读、授权或写入时校验')

    @read_view
    def check(self):
        failures = records.check(self.root)
        for p in project_readmes(self.root):
            try:
                for path, text in entries.expected(self.root, p.parent.name).items():
                    if not native_path(path).exists() or native_path(path).read_text(encoding='utf-8') != text:
                        failures.append(f'项目入口待同步：{path}')
            except (ValueError, OSError) as error:
                failures.append(str(error))
        pending = self.operations.pending()
        return dict(ok=not failures and not pending, failures=failures, pending_operations=pending,
                    coverage='Project/Task/Run、Repo与派生入口；不替代全Vault链接与目录检查')

    @read_view
    def sync_preview(self, project=None):
        names = [self.project_name(project)] if project else [p.parent.name for p in project_readmes(self.root)]
        changed = []
        for name in names:
            for path, text in entries.expected(self.root, name).items():
                if not path.exists() or path.read_text(encoding='utf-8') != text:
                    changed.append(str(path))
            docs, resource = records.paired(self.root, name)
            if not records.properties(docs / 'README.md').get('project_id') or not (resource / 'project.json').exists():
                changed.append(str(resource / 'project.json'))
        return dict(projects=names, changed=sorted(set(changed)), mode='preview')

    def plan(self, action, parameters, *, actor):
        """dry-run：返回 plan_token 和依赖信息，无持久业务写入。"""
        from . import _migration as migrate
        params = dict(parameters)
        if action == 'project.import':
            from .transfer import plan_import
            return plan_import(self, actor=actor, **params)
        if action in ('governance.relocate', 'governance.rollback'):
            from . import _governance
            with workspace_lock(self.root):
                self.operations.settle()
                return _governance.plan(self, action, params, actor)
        if params.get('project') and action not in MIGRATION_ACTIONS:
            params['project'] = self.project_name(params['project'])
        with workspace_lock(self.root):
            self.operations.settle()
            if action in ('project.rename', 'task.rename', 'task.move', 'project.archive', 'project.unarchive', 'task.archive', 'task.unarchive'):
                if action == 'project.rename':
                    plan = migrate.plan_rename(self.root, 'project', params['project'], params['title'], params.get('reason', ''), actor)
                elif action == 'task.rename':
                    plan = migrate.plan_rename(self.root, 'task', params['task'], params['title'], params.get('reason', ''), actor)
                elif action == 'task.move':
                    plan = migrate.plan_move(self.root, params['task'], params['to_project'], params.get('reason', ''), actor)
                elif action == 'project.archive':
                    plan = migrate.plan_archive(self.root, 'project', params['project'], params.get('reason', ''), actor, params.get('allow_unfinished', False))
                elif action == 'project.unarchive':
                    plan = migrate.plan_unarchive(self.root, 'project', params['project'], params.get('reason', ''), actor)
                elif action == 'task.archive':
                    plan = migrate.plan_archive(self.root, 'task', params['task'], params.get('reason', ''), actor, params.get('allow_unfinished', False))
                elif action == 'task.unarchive':
                    plan = migrate.plan_unarchive(self.root, 'task', params['task'], params.get('reason', ''), actor)
                dependency = migrate.dependency_snapshot(self.root, plan)
                token = migrate.compute_plan_token(plan, dependency)
                return {'plan_token': token, 'plan': plan, 'dependency': dependency, 'dry_run': True}
            return {'plan_token': None, 'dry_run': True, 'note': '此操作不需要两步计划'}

    def mutate(self, action, parameters, *, actor, request_id=None, if_version=None,
               if_plan=None, compatibility=False, checkpoint=None):
        params = dict(parameters)
        if action == 'project.sync' and not compatibility and not params.get('project'):
            raise GovernanceError('INVALID_ARGUMENT', '新 CLI 同步写入须指定一个 --project 并提供该项目版本')
        if params.get('project') and action not in MIGRATION_ACTIONS:
            params['project'] = self.project_name(params['project'])
        version = None
        if action in ('task.update', 'task.handoff', 'task.rename', 'task.move', 'task.archive', 'task.unarchive', 'task.delete', 'task.undelete'):
            version = lambda: self.version('task', params['task'])
        elif action in ('run.start', 'run.finish', 'run.update', 'run.rename', 'run.archive', 'run.unarchive', 'run.delete', 'run.undelete', 'repo.snapshot'):
            version = lambda: self.version('run', params['run'], params['task'])
        elif action in ('project.update', 'project.pause', 'project.resume', 'project.rename', 'project.archive', 'project.unarchive', 'project.delete', 'project.undelete'):
            version = lambda: self.version('project', params['project'])
        elif action == 'repo.link':
            version = (lambda: self.version('task', params['task'])) if params.get('task') else (lambda: self.version('project', params['project']))
        elif action == 'repo.bind':
            version = lambda: self.version('repo', params['repo'])
        elif action in ('governance.relocate', 'governance.rollback') or action == 'project.sync' and params.get('project'):
            version = lambda: self.version('project', params['project'])
        if not compatibility and not request_id:
            raise GovernanceError('REQUEST_REQUIRED', '写操作必须提供稳定 --request-id')
        if version and not compatibility and if_version is None:
            raise GovernanceError('VERSION_REQUIRED', '更新已有对象必须提供 --if-version')
        from . import _actions as actions_contract
        if actions_contract.requires_plan(action):
            if not compatibility and not if_plan:
                raise GovernanceError('PLAN_CONFLICT',
                                      '迁移需两步：先 --dry-run 取 plan_token，再 --if-plan 提交')
        elif if_plan:
            raise GovernanceError('INVALID_ARGUMENT', '此操作不需要 --if-plan', action=action)
        if action == 'project.import':
            from .transfer import import_project
            return import_project(self, actor=actor, request_id=request_id, if_plan=if_plan,
                                  checkpoint=checkpoint, **params)
        if action in ('governance.relocate', 'governance.rollback'):
            from . import _governance
            return _governance.execute(self, action, params, actor, request_id, if_version, if_plan, checkpoint)
        if action in MIGRATION_ACTIONS:
            return self._mutate_migration(action, params, actor, request_id, if_version,
                                          if_plan, checkpoint, version=version)
        def prepare(stage):
            return self._apply(stage, action, params, actor)
        if action == 'repo.snapshot':
            return self._snapshot(params, actor, request_id, if_version, compatibility, checkpoint)
        return self.operations.execute(action, params, actor, prepare, request_id=request_id,
                                       version=version, expected_version=if_version, checkpoint=checkpoint)

    def _mutate_migration(self, action, p, actor, request_id, if_version, if_plan, checkpoint, version=None):
        """目录迁移：不经 staged 记录执行器，走 execute_migration。

        计划对**真实根**计算（不是 stage）——此前对 stage 算 plan_* 却把 moves 交给
        真实根的 migrate()，vault_pairs 恒为空，rename/move/archive 一个都跑不完。
        """
        from . import _migration as migrate

        def build_plan():
            if action == 'project.rename':
                return migrate.plan_rename(self.root, 'project', p['project'], p['title'], p.get('reason', ''), actor)
            if action == 'task.rename':
                return migrate.plan_rename(self.root, 'task', p['task'], p['title'], p.get('reason', ''), actor)
            if action == 'task.move':
                return migrate.plan_move(self.root, p['task'], p['to_project'], p.get('reason', ''), actor)
            if action in ('project.archive', 'task.archive'):
                kind = 'project' if action.startswith('project.') else 'task'
                return migrate.plan_archive(self.root, kind, p.get('project') or p['task'], p.get('reason', ''), actor, p.get('allow_unfinished', False))
            if action in ('project.unarchive', 'task.unarchive'):
                kind = 'project' if action.startswith('project.') else 'task'
                return migrate.plan_unarchive(self.root, kind, p.get('project') or p['task'], p.get('reason', ''), actor)
            raise GovernanceError('INVALID_ARGUMENT', '未知迁移操作', action=action)

        def validate():
            # 锁内、回执落盘前重算计划与依赖快照；不一致即计划过期，不做自动合并。
            current = build_plan()
            dep = migrate.dependency_snapshot(self.root, current)
            if migrate.compute_plan_token(current, dep) != if_plan:
                raise GovernanceError('PLAN_CONFLICT',
                                      '计划已过期（对象、依赖或占用已变化），请重新 --dry-run 后提交',
                                      expected_token=if_plan,
                                      computed_token=migrate.compute_plan_token(current, dep))

        def run(journal):
            plan = journal.data.get('plan') or build_plan()
            journal.data['plan'] = plan
            moves = [(plan[f'{k}_source'], plan[f'{k}_target']) for k in ('docs', 'resource')
                     if plan.get(f'{k}_source') and plan.get(f'{k}_target')]
            return migrate._advance(
                self.root, moves, journal,
                identity=p.get('task') or plan.get('project_id') or p.get('project'),
                finish=lambda: self._update_records_after_migration(action, plan, p),
                executable=getattr(self, '_obsidian_executable', None),
                mover=getattr(self, '_mover', None),
                link_state=getattr(self, '_link_state', None),
                new_number=plan.get('new_number'), target_project=plan.get('target_project'))

        return self.operations.execute_migration(
            action, p, actor, run, request_id=request_id, version=version,
            expected_version=if_version, if_plan=if_plan,
            plan=build_plan,
            validate=validate, checkpoint=checkpoint)

    def _apply(self, root, action, p, actor):
        if action == 'task.create':
            return records.create_task(root, p.get('project', '00-Playground'), p['title'], p['origin'],
                                       p.get('owner', actor), p['goal'], p.get('read_paths', []),
                                       p.get('write_paths', []), p.get('requires_acceptance', False))
        if action in ('task.update', 'task.handoff'):
            doc, resource, props = records.locate_task(root, p['task'])
            if action == 'task.handoff' and actor != props['owner']:
                if not p.get('authorization', '').strip() or not p.get('note', '').strip():
                    raise GovernanceError('OWNER_CONFLICT', '新负责者接手须记录用户授权来源与原因')
                records.set_properties(doc, {'owner': actor})
                with doc.open('a', encoding='utf-8') as stream:
                    stream.write(f'\n- {records.now()} `{actor}` 根据用户授权接手；原 owner `{props["owner"]}`；授权来源：{p["authorization"]}。\n')
            updates = {}
            if p.get('title') is not None:
                updates['title'] = p['title']
            if p.get('goal') is not None:
                updates['goal'] = p['goal']
            if updates:
                records.set_properties(doc, updates)
            result = records.update_task(root, p['task'], actor, p.get('status'), p.get('owner'), p.get('note', ''), p.get('accepted', False))
            if any(k in p for k in ('read_paths', 'write_paths', 'remote_resources')):
                meta = records.read_json(resource / 'task.json')
                for key in ('read_paths', 'write_paths', 'remote_resources'):
                    if key in p:
                        if not isinstance(p[key], list):
                            raise GovernanceError('INVALID_ARGUMENT', 'scope 字段必须为列表')
                        if key != 'remote_resources' and any(not Path(x).is_absolute() for x in p[key]):
                            raise GovernanceError('INVALID_ARGUMENT', 'scope 路径必须是绝对路径')
                        meta['scope'][key] = p[key]
                records.write_json(resource / 'task.json', meta)
            return {'document': result}
        if action == 'run.create':
            return records.create_run(root, p['task'], p['title'], actor, p['command'], p['host'], p['source'], p['inputs'], p.get('retry_of'))
        if action == 'run.start':
            path = records.mutate_run(root, p['task'], p['run'], actor, status='running')
            return {'record': path}
        if action == 'run.finish':
            path = records.mutate_run(root, p['task'], p['run'], actor, status=p['status'],
                                      result=p.get('result'), exit_code=p.get('exit_code'),
                                      evidence=p.get('evidence'), finish_authorization=p.get('authorization'))
            return {'record': path}
        if action == 'run.update':
            path = records.mutate_run(root, p['task'], p['run'], actor,
                                      status=p.get('status'),
                                      result=p.get('result'), exit_code=p.get('exit_code'),
                                      add_evidence=p.get('add_evidence'),
                                      host=p.get('host'), source=p.get('source'),
                                      inputs=p.get('inputs'), command=p.get('command'))
            return {'record': path}
        if action == 'run.rename':
            path = records.rename_run(root, p['task'], p['run'], actor, p['title'])
            return {'record': path}
        if action in ('run.archive', 'run.unarchive', 'run.delete', 'run.undelete'):
            op = action.split('.')[1]
            path = records.manage_run(root, p['task'], p['run'], actor, op, p.get('reason', ''))
            return {'record': path}
        if action == 'project.create':
            return records.create_project(root, p['title'], p.get('created'))
        if action == 'project.update':
            name = self.project_name(p['project'])
            return {'document': records.update_project(root, name, p.get('title'), p.get('aliases'), p.get('description'))}
        if action in ('project.pause', 'project.resume'):
            name = self.project_name(p['project'])
            status = 'paused' if action == 'project.pause' else 'active'
            return {'document': records.set_project_status(root, name, status, actor, p.get('reason', ''))}
        if action in ('task.delete', 'project.delete'):
            kind = 'task' if action == 'task.delete' else 'project'
            identity = p['task'] if kind == 'task' else self.project_name(p['project'])
            return {'document': records.delete_object(root, kind, identity, actor, p.get('reason', ''))}
        if action in ('task.undelete', 'project.undelete'):
            kind = 'task' if action == 'task.undelete' else 'project'
            identity = p['task'] if kind == 'task' else self.project_name(p['project'])
            return {'document': records.undelete_object(root, kind, identity, actor, p.get('reason', ''))}
        if action in ('run.delete', 'run.undelete'):
            pass  # 已由 run.archive 分支处理
        if action in ('project.rename', 'task.rename', 'task.move', 'project.archive', 'project.unarchive', 'task.archive', 'task.unarchive'):
            # 迁移动作不走 staged 记录执行器，见 _mutate_migration。
            raise GovernanceError('INVALID_ARGUMENT', '迁移操作不得经 staged 执行器', action=action)
        if action == 'repo.register':
            return repos.register(root, p['repo'], p['title'], p['purpose'])
        if action == 'repo.bind':
            return repos.bind(root, p['repo'], Path(p['path']))
        if action == 'repo.link':
            return repos.associate(root, p['repo'], p.get('subpaths', ['.']), p.get('project'), p.get('task'))
        if action == 'project.sync':
            names = [p['project']] if p.get('project') else [x.parent.name for x in project_readmes(root)]
            for name in names:
                entries.expected(root, name)
                records.initialize_project(root, name)
                records.refresh(root, name)
            return {'projects': names, 'mode': 'applied'}
        raise GovernanceError('INVALID_ARGUMENT', '未知治理操作', action=action)

    def _apply_migration(self, root, action, p, actor):
        """迁移执行器：直接在 stage 上执行目录移动和记录更新。"""
        from . import _migration as migrate
        if action == 'project.rename':
            plan = migrate.plan_rename(root, 'project', p['project'], p['title'], p.get('reason', ''), actor)
        elif action == 'task.rename':
            plan = migrate.plan_rename(root, 'task', p['task'], p['title'], p.get('reason', ''), actor)
        elif action == 'task.move':
            plan = migrate.plan_move(root, p['task'], p['to_project'], p.get('reason', ''), actor)
        elif action == 'project.archive':
            plan = migrate.plan_archive(root, 'project', p['project'], p.get('reason', ''), actor, p.get('allow_unfinished', False))
        elif action == 'project.unarchive':
            plan = migrate.plan_unarchive(root, 'project', p['project'], p.get('reason', ''), actor)
        elif action == 'task.archive':
            plan = migrate.plan_archive(root, 'task', p['task'], p.get('reason', ''), actor, p.get('allow_unfinished', False))
        elif action == 'task.unarchive':
            plan = migrate.plan_unarchive(root, 'task', p['task'], p.get('reason', ''), actor)
        else:
            raise GovernanceError('INVALID_ARGUMENT', '未知迁移操作', action=action)
        # 目录迁移必须落在真实 Vault 根上：Obsidian 只索引真实库，链接更新不在
        # stage 副本里发生。此前这里用 shutil.move 普通移动假装完成迁移，会留下
        # 未更新的内部链接——已改为走 migrate()（renameFile 语义 + 链接核验）。
        moves = []
        for key in ('docs', 'resource'):
            src, dst = plan.get(f'{key}_source'), plan.get(f'{key}_target')
            if src and dst:
                moves.append((src, dst))
        migrate.migrate(self.root, moves,
                        identity=p.get('task') or p.get('project'),
                        finish=lambda: self._update_records_after_migration(action, plan, p))
        return plan

    def _update_records_after_migration(self, action, plan, p):
        """迁移完成后刷新记录：标题/状态/路径绑定与派生入口。"""
        from ._paths import project_readmes
        base = loc.vault(self.root) / '30-项目'
        if action == 'project.rename':
            readme = Path(plan['docs_target']) / 'README.md'
            if readme.exists():
                props = records.properties(readme)
                aliases = props.get('aliases', [])
                aliases = aliases if isinstance(aliases, list) else [aliases]
                old_title = props.get('title')
                if old_title and old_title != p['title'] and old_title not in aliases:
                    aliases.append(old_title)
                records.set_properties(readme, {'title': p['title'], 'aliases': aliases,
                                               'updated': records.now()[:10]})
                import re
                readme.write_text(re.sub(r'(?m)^# .+$', lambda _: '# ' + p['title'],
                                         readme.read_text(encoding='utf-8'), count=1), encoding='utf-8')
        elif action == 'project.archive':
            readme = base / 'archive' / plan['name'] / 'README.md'
            if readme.exists():
                records.set_properties(readme, {'status': 'archived', 'updated': records.now()[:10],
                    'archived_from_status': plan['project_status'],
                    'archive_unfinished_confirmed': plan['allow_unfinished']})
        elif action == 'project.unarchive':
            readme = base / plan['name'] / 'README.md'
            if readme.exists():
                previous = records.properties(readme).get('archived_from_status')
                records.set_properties(readme, {'status': previous if previous in ('active', 'paused') else 'active',
                    'archive_unfinished_confirmed': False, 'updated': records.now()[:10]})
        elif action in ('task.rename', 'task.move', 'task.archive', 'task.unarchive'):
            doc = Path(plan['docs_target']) / 'README.md'
            updates = {'updated': records.now()[:10]}
            if action == 'task.rename':
                updates['title'] = p['title']
            if action == 'task.archive':
                updates['archived_at'] = records.now()[:10]
                updates['archived_from_status'] = plan['task_status']
                updates['archive_unfinished_confirmed'] = plan['allow_unfinished']
            if action == 'task.unarchive':
                updates.update(archived_at='', archive_unfinished_confirmed=False)
            if action == 'task.move':
                updates.update(project_id=plan['target_project_id'], task_number=plan['new_number'],
                               project=f"[[30-项目/{plan['target_project']}/README]]")
                meta_path = Path(plan['resource_target']) / 'task.json'
                meta = records.read_json(meta_path)
                meta.update(project_id=plan['target_project_id'], repositories=plan['repositories'],
                            docs_root=loc.relative(self.root, Path(plan['docs_target'])).as_posix(),
                            resource_root=loc.relative(self.root, Path(plan['resource_target'])).as_posix())
                records.write_json(meta_path, meta)
                for child in doc.parent.rglob('*.md'):
                    if child != doc and records.properties(child).get('project'):
                        records.set_properties(child, {'project': updates['project']})
                for name, number in ((plan['source_project'], plan['source_high_watermark']),
                                     (plan['target_project'], int(plan['new_number']))):
                    binding_path = loc.runtime(self.root) / 'project_src' / name / 'project.json'
                    binding = records.read_json(binding_path)
                    binding['task_number_high_watermark'] = max(int(binding.get('task_number_high_watermark', 0)), number)
                    records.write_json(binding_path, binding)
                note = (f"\n- 受管移动：{plan['source_project']} Task {plan['old_number']} → "
                        f"{plan['target_project']} Task {plan['new_number']}；原因：{plan['reason']}；"
                        f"授权：{p.get('authorization', '')}；Task/Run ID 与历史执行事实保持。\n")
                text = doc.read_text(encoding='utf-8')
                if note not in text:
                    doc.write_text(text + note, encoding='utf-8')
                source_readme = loc.vault(self.root) / '30-项目' / plan['source_project'] / 'README.md'
                destination = doc.with_suffix('').relative_to(loc.vault(self.root)).as_posix()
                breadcrumb = f"\n- 已迁出 Task {plan['old_number']}：[[{destination}|{records.properties(doc).get('title', plan['new_name'])}]]；{plan['reason']}。\n"
                source_text = source_readme.read_text(encoding='utf-8')
                if breadcrumb not in source_text:
                    source_readme.write_text(source_text + breadcrumb, encoding='utf-8')
            records.set_properties(doc, updates)
        # 路径绑定与派生入口按新位置重算。
        if action == 'project.rename':
            names = {plan['new_name']}
        elif action == 'task.move':
            names = {plan['source_project'], plan['target_project']}
        else:
            names = {r.parent.name for r in project_readmes(self.root)
                     if Path(plan['docs_target']).is_relative_to(r.parent)}
        for name in names:
            records.initialize_project(self.root, name)
            records.refresh(self.root, name)

    @measured('source_snapshot')
    def _snapshot(self, p, actor, request_id, if_version, compatibility, checkpoint):
        # 准备源码证据不持有治理写锁；提交时重新检查 Run 和 Repo 依赖。
        with workspace_lock(self.root):
            self.operations.settle()
            if request_id:
                identifier = digest(request_id.encode())
                if (self.operations.base / identifier / 'operation.json').exists():
                    return self.operations.execute('repo.snapshot', p, actor, lambda _: None,
                        request_id=request_id, expected_version=if_version,
                        version=lambda: self.version('run', p['run'], p['task']))
            run_version = self.version('run', p['run'], p['task'])
            if if_version is not None and if_version != run_version:
                raise GovernanceError('VERSION_CONFLICT', 'Run 已变化')
            run_path = self.run_path(p['task'], p['run'])
            record = records.read_json(run_path)
            if record['actor'] != actor or record['status'] != 'running':
                raise GovernanceError('STATE_CONFLICT', '仅执行者可给 running Run 取证')
            if (run_path.parent / 'source-snapshot').exists():
                raise GovernanceError('STATE_CONFLICT', '源码证据已存在，重新执行请创建新 Run')
            refs = repos.resolve(self.root, task=p['task'])
            if not refs:
                raise GovernanceError('STATE_CONFLICT', 'Task 没有关联源码仓库')
            task_version = self.version('task', p['task'])
            original_refs = json.dumps(refs, sort_keys=True)
            _, resource, _ = records.locate_task(self.root, p['task'])
            scope = records.read_json(resource / 'task.json')['scope']
            overrides = p.get('checkouts', {})
            if set(overrides) - {ref.get('repo_id') for ref in refs}:
                raise GovernanceError('SCOPE_VIOLATION', 'checkout 覆盖引用了未关联 Repo')
            for ref in refs:
                key = ref.get('repo_id')
                if key in overrides:
                    selected = repos.checkout_root(overrides[key])
                    common = lambda path: Path(repos.git(path, 'rev-parse', '--path-format=absolute', '--git-common-dir').stdout.decode().strip()).resolve()
                    if common(selected) != common(ref['path']):
                        raise GovernanceError('SCOPE_VIOLATION', 'checkout 必须属于同一 Git 仓库')
                    ref['path'] = str(selected)
                if not compatibility or overrides:
                    allowed = scope.get('read_paths', []) + scope.get('write_paths', [])
                    if not any(Path(ref['path']).resolve().is_relative_to(Path(x).resolve()) for x in allowed):
                        raise GovernanceError('SCOPE_VIOLATION', '源码 checkout 不在 Task 声明范围内')
                for sub in ref.get('paths', ['.']):
                    if not (Path(ref['path']) / sub).resolve(strict=True).is_relative_to(Path(ref['path']).resolve()):
                        raise GovernanceError('SCOPE_VIOLATION', '源码子路径经链接越界')
        temp_root = loc.runtime(self.root) / 'tmp/dmy'
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='source-', dir=temp_root) as temporary:
            evidence = Path(temporary)
            captured = repos.capture(refs, evidence)
            def prepare(stage):
                if self.version('task', p['task']) != task_version or json.dumps(repos.resolve(self.root, task=p['task']), sort_keys=True) != original_refs:
                    raise GovernanceError('VERSION_CONFLICT', '取证期间 Task 或 Repo 关联发生变化')
                repos.verify_capture(captured, evidence)
                target_run = stage / loc.relative(self.root, run_path)
                destination = target_run.parent / 'source-snapshot'
                shutil.copytree(evidence, destination)
                current = records.read_json(target_run)
                current['repositories'] = captured
                current['evidence'] = [*current.get('evidence', []), str(destination)]
                records.write_json(target_run, current)
                return captured
            return self.operations.execute('repo.snapshot', p, actor, prepare, request_id=request_id,
                version=lambda: self.version('run', p['run'], p['task']), expected_version=if_version or run_version,
                checkpoint=checkpoint)
