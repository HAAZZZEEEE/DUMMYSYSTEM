"""迁移执行路径：两步计划、回执幂等、恢复语义、三态判定。

覆盖 G1 的保证：迁移动作不经 staged 记录执行器；--dry-run 不留回执、不推进
高水位；plan_token 过期报 PLAN_CONFLICT；同 request_id 重放返回原回执、换意图
报 REQUEST_CONFLICT；移动结果不可判定时报 RECOVERY_REQUIRED；可续做阶段的回执
绝不折叠成 aborted（那会谎称「真实目标尚未修改」）。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dummysys_core import __version__
from dummysys_core.operations import GovernanceError, digest
from dummysys_core.workspace import Workspace, MIGRATION_ACTIONS


def fake_mover(root, source, target, executable=None):
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    Path(source).rename(target)


def empty_links():
    return {'unresolved': set(), 'resolved': set(), 'identity': {}}


class MigrationExecuteTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        (self.root / 'dmy_vault/30-项目/00-Playground').mkdir(parents=True)
        (self.root / 'dmy_vault/30-项目/00-Playground/README.md').write_text(
            '---\nproject_id: 11111111-1111-4111-8111-111111111111\n'
            'title: 沙盒\nstatus: active\ncreated: 2026-09-24\n---\n', encoding='utf-8')
        (self.root / 'runtime/project_src/00-Playground').mkdir(parents=True)
        self.ws = Workspace(self.root)
        self.ws._mover = fake_mover
        self.ws._link_state = empty_links
        self.ws._obsidian_executable = None

    def tearDown(self):
        self._tmp.cleanup()

    def _task(self, title='待迁移任务'):
        return self.ws.mutate('task.create',
                              {'project': '00-Playground', 'title': title, 'origin': 'user',
                               'goal': '验证迁移', 'owner': 'alice',
                               'read_paths': [], 'write_paths': []},
                              actor='alice', request_id=f'create-{title}')['result']['task_id']

    def _rename(self, task_id, title='改名之后', reason='迁移验证'):
        """返回 (body, plan)。计划与提交必须共用同一份输入，否则 token 必然对不上。"""
        body = {'task': task_id, 'title': title, 'reason': reason}
        return body, self.ws.plan('task.rename', dict(body), actor='alice')

    # ---- 端到端 ----
    def test_task_rename_end_to_end_through_mutate(self):
        task_id = self._task()
        body, plan = self._rename(task_id)
        receipt = self.ws.mutate('task.rename', body, actor='alice', request_id='rename-1',
                                 if_version=self.ws.version('task', task_id),
                                 if_plan=plan['plan_token'])
        self.assertEqual(receipt['status'], 'completed')
        self.assertEqual(receipt.get('kind'), 'migration', '迁移回执须标明 kind，便于恢复分流')
        self.assertTrue(Path(plan['plan']['docs_target']).is_dir())
        self.assertFalse(Path(plan['plan']['docs_source']).exists())
        registry = self.root / 'runtime/state/workspace/retired-paths.json'
        self.assertTrue(registry.exists(), '迁移须登记旧路径映射')
        self.assertEqual(json.loads(registry.read_text(encoding='utf-8'))[-1]['identity'], task_id)

    def test_migration_actions_are_declared(self):
        for action in ('task.rename', 'task.move', 'task.archive', 'project.rename'):
            self.assertIn(action, MIGRATION_ACTIONS)

    def test_unfinished_task_archive_requires_confirmation_and_preserves_status(self):
        for status in ('active', 'blocked', 'awaiting_acceptance'):
            with self.subTest(status=status):
                task = self._task('保留状态-' + status)
                if status != 'active':
                    self.ws.mutate('task.update', {'task': task, 'status': status, 'note': '测试状态'},
                        actor='alice', request_id='state-' + status, if_version=self.ws.version('task', task))
                body = {'task': task, 'reason': '确认收起任务'}
                with self.assertRaises(GovernanceError):
                    self.ws.plan('task.archive', body, actor='alice')
                body['allow_unfinished'] = True
                plan = self.ws.plan('task.archive', body, actor='alice')
                self.assertEqual(plan['plan']['task_status'], status)
                self.ws.mutate('task.archive', body, actor='alice', request_id='archive-' + status,
                    if_version=self.ws.version('task', task), if_plan=plan['plan_token'])
                current = self.ws.task(task)
                self.assertEqual(current['status'], status)
                self.assertEqual(current['owner'], 'alice')
                self.assertTrue(current['archive_unfinished_confirmed'])
                self.assertEqual(current['archived_from_status'], status)
                self.assertEqual(self.ws.check()['failures'], [])
                self.assertIn('/archive/', current['document'].replace('\\', '/'))
                undo = {'task': task, 'reason': '继续维护'}
                token = self.ws.plan('task.unarchive', undo, actor='alice')['plan_token']
                self.ws.mutate('task.unarchive', undo, actor='alice', request_id='undo-' + status,
                    if_version=self.ws.version('task', task), if_plan=token)
                self.assertEqual(self.ws.task(task)['status'], status)

    def test_archive_confirmation_does_not_override_open_run_protection(self):
        task = self._task('执行保护')
        run = self.ws.mutate('run.create', {'task': task, 'title': '计划', 'host': 'local',
            'source': 'test', 'inputs': 'test', 'command': 'test'}, actor='alice', request_id='run-create')['result']['run_id']
        for running in (False, True):
            if running:
                self.ws.mutate('run.start', {'task': task, 'run': run}, actor='alice', request_id='run-start',
                    if_version=self.ws.version('run', run, task))
            with self.assertRaisesRegex(GovernanceError, '未结束 Run'):
                self.ws.plan('task.archive', {'task': task, 'reason': '测试', 'allow_unfinished': True}, actor='alice')

    def test_project_archive_confirmation_preserves_all_task_states(self):
        project = self.ws.mutate('project.create', {'title': '确认归档项目', 'created': '2026-10-09'},
            actor='alice', request_id='project-create')['result']['project_id']
        tasks = []
        for status in ('active', 'blocked', 'awaiting_acceptance', 'completed', 'cancelled'):
            task = self.ws.mutate('task.create', {'project': project, 'title': status, 'origin': 'user', 'goal': '验证'},
                actor='alice', request_id='project-task-' + status)['result']['task_id']
            if status != 'active':
                self.ws.mutate('task.update', {'task': task, 'status': status, 'note': '设置状态'},
                    actor='alice', request_id='project-state-' + status, if_version=self.ws.version('task', task))
            tasks.append((task, status))
        body = {'project': project, 'reason': '收起项目'}
        with self.assertRaisesRegex(GovernanceError, '未完成 Task'):
            self.ws.plan('project.archive', body, actor='alice')
        body['allow_unfinished'] = True
        self.ws.mutate('project.pause', {'project': project, 'reason': '暂缓维护'}, actor='alice', request_id='project-pause',
            if_version=self.ws.version('project', project))
        plan = self.ws.plan('project.archive', body, actor='alice')
        self.assertEqual(len(plan['plan']['unfinished_tasks']), 3)
        self.ws.mutate('project.archive', body, actor='alice', request_id='project-archive',
            if_version=self.ws.version('project', project), if_plan=plan['plan_token'])
        for task, status in tasks:
            self.assertEqual(self.ws.task(task)['status'], status)
        failures = self.ws.check()['failures']
        self.assertFalse([f for f in failures if f.startswith('项目含未完成 Task，归档缺少显式确认：')])
        undo = {'project': project, 'reason': '恢复项目'}
        token = self.ws.plan('project.unarchive', undo, actor='alice')['plan_token']
        self.ws.mutate('project.unarchive', undo, actor='alice', request_id='project-undo',
            if_version=self.ws.version('project', project), if_plan=token)
        self.assertEqual(self.ws.project(project)['status'], 'paused')
        for task, status in tasks:
            self.assertEqual(self.ws.task(task)['status'], status)

    # ---- 两步计划 ----
    def test_dry_run_writes_no_receipt_or_watermark(self):
        task_id = self._task()
        ops = self.root / 'runtime/state/workspace/operations'
        binding = self.root / 'runtime/project_src/00-Playground/project.json'
        before_binding = binding.read_bytes()
        before = sorted(p.name for p in ops.glob('*/operation.json')) if ops.exists() else []
        _body, plan = self._rename(task_id)
        self.assertTrue(plan['plan_token'])
        self.assertIn('dependency', plan, 'token 必须覆盖依赖快照')
        after = sorted(p.name for p in ops.glob('*/operation.json')) if ops.exists() else []
        self.assertEqual(before, after, '--dry-run 不得产生回执')
        binding = self.root / 'runtime/project_src/00-Playground/project.json'
        data = json.loads(binding.read_text(encoding='utf-8')) if binding.exists() else {}
        self.assertEqual(binding.read_bytes(), before_binding, '--dry-run 不得推进高水位')

    def test_commit_without_if_plan_is_plan_conflict(self):
        task_id = self._task()
        body, _plan = self._rename(task_id)
        with self.assertRaises(GovernanceError) as caught:
            self.ws.mutate('task.rename', body, actor='alice', request_id='no-plan',
                           if_version=self.ws.version('task', task_id))
        self.assertEqual(caught.exception.code, 'PLAN_CONFLICT')

    def test_stale_plan_token_is_plan_conflict(self):
        task_id = self._task()
        body, plan = self._rename(task_id)
        self._task('另一个任务')   # 依赖变化：占用与高水位都动了
        with self.assertRaises(GovernanceError) as caught:
            self.ws.mutate('task.rename', body, actor='alice', request_id='stale-1',
                           if_version=self.ws.version('task', task_id),
                           if_plan=plan['plan_token'])
        self.assertEqual(caught.exception.code, 'PLAN_CONFLICT')

    def test_stray_if_plan_on_plain_action_is_invalid(self):
        task_id = self._task()
        with self.assertRaises(GovernanceError) as caught:
            self.ws.mutate('task.update', {'task': task_id, 'note': 'n', 'status': 'blocked'},
                           actor='alice', request_id='stray-1',
                           if_version=self.ws.version('task', task_id), if_plan='deadbeef')
        self.assertEqual(caught.exception.code, 'INVALID_ARGUMENT')

    # ---- 回执幂等 ----
    def test_same_request_id_replay_returns_original_receipt(self):
        task_id = self._task()
        body, plan = self._rename(task_id)
        version = self.ws.version('task', task_id)
        first = self.ws.mutate('task.rename', body, actor='alice', request_id='replay-1',
                               if_version=version, if_plan=plan['plan_token'])
        second = self.ws.mutate('task.rename', body, actor='alice', request_id='replay-1',
                                if_version=version, if_plan=plan['plan_token'])
        self.assertEqual(first['operation_id'], second['operation_id'])
        self.assertTrue(Path(plan['plan']['docs_target']).is_dir())

    def test_request_id_reuse_with_different_intent_is_request_conflict(self):
        """if_plan 进指纹：同一 request_id 换一个 plan_token 是两次不同意图。"""
        task_id = self._task()
        body, plan = self._rename(task_id)
        version = self.ws.version('task', task_id)
        self.ws.mutate('task.rename', body, actor='alice', request_id='fingerprint-1',
                       if_version=version, if_plan=plan['plan_token'])
        other_body, other_plan = self._rename(task_id, title='又改')
        with self.assertRaises(GovernanceError) as caught:
            self.ws.mutate('task.rename', other_body, actor='alice', request_id='fingerprint-1',
                           if_version=version, if_plan=other_plan['plan_token'])
        self.assertEqual(caught.exception.code, 'REQUEST_CONFLICT')

    # ---- 恢复与三态 ----
    def test_move_state_is_tri_valued(self):
        from dummysys_core import _migration as migrate
        base = self.root / 'dmy_vault/30-项目/00-Playground'
        source, target, missing = base / '两边都在', base / '改名', base / '不存在'
        source.mkdir(parents=True)
        target.mkdir(parents=True)
        self.assertEqual(migrate._move_state(source, target), 'indeterminate')
        self.assertEqual(migrate._move_state(source, missing), 'todo')
        self.assertEqual(migrate._move_state(missing, target), 'done')

    def test_resumable_migration_is_not_folded_to_aborted(self):
        """可续做阶段：recover 不抛，但绝不折叠成 aborted。

        folded→aborted 会谎称「真实目标尚未修改」，而目录可能已半挪、重试撞 target exists。
        """
        self._task()
        operation_id = digest(b'honest-recovery')
        from dummysys_core._migration import MigrationJournal
        folder = self.root / 'runtime/state/workspace/operations' / operation_id
        folder.mkdir(parents=True)
        (folder / 'operation.json').write_text(json.dumps({
            'schema_version': 1, 'tool_version': __version__, 'workspace': str(self.ws.root),
            'source_commit': self.ws.operations.source_commit(), 'kind': 'migration',
            'operation_id': operation_id, 'request_id': 'honest-recovery',
            'fingerprint': 'x', 'action': 'task.rename', 'actor': 'alice',
            'status': 'migrating', 'created_at': 0, 'files': []}), encoding='utf-8')
        MigrationJournal(self.root, operation_id).record('docs_moved', {'intent': True})
        record = self.ws.operations.recover(operation_id)
        self.assertEqual(record['status'], 'migrating')
        self.assertEqual(json.loads((folder / 'operation.json').read_text(encoding='utf-8'))['status'],
                         'migrating')

    def test_needs_recovery_blocks_settle(self):
        self._task()
        operation_id = digest(b'needs-recovery')
        from dummysys_core._migration import MigrationJournal
        folder = self.root / 'runtime/state/workspace/operations' / operation_id
        folder.mkdir(parents=True)
        (folder / 'operation.json').write_text(json.dumps({
            'schema_version': 1, 'tool_version': __version__, 'workspace': str(self.ws.root),
            'source_commit': self.ws.operations.source_commit(), 'kind': 'migration',
            'operation_id': operation_id, 'request_id': 'needs-recovery',
            'fingerprint': 'x', 'action': 'task.rename', 'actor': 'alice',
            'status': 'migrating', 'created_at': 0, 'files': []}), encoding='utf-8')
        MigrationJournal(self.root, operation_id).set_stage('needs_recovery')
        with self.assertRaises(GovernanceError) as caught:
            self.ws.operations.settle()
        self.assertEqual(caught.exception.code, 'RECOVERY_REQUIRED')

    def test_version_checked_before_plan(self):
        task_id = self._task()
        body, plan = self._rename(task_id)
        with self.assertRaises(GovernanceError) as caught:
            self.ws.mutate('task.rename', body, actor='alice', request_id='order-1',
                           if_version='stale-version', if_plan=plan['plan_token'])
        self.assertEqual(caught.exception.code, 'VERSION_CONFLICT')


if __name__ == '__main__':
    unittest.main()
