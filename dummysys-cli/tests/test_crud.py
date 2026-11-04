"""新增治理能力契约测试：frontmatter、管理 sidecar、删除恢复、Run 更新、计划契约。"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from dummysys_core import _records as records
from dummysys_core import _frontmatter
from dummysys_core import _management
from dummysys_core.operations import GovernanceError
from dummysys_core.workspace import Workspace


class CrudTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        doc = self.root / 'dmy_vault/30-项目/00-Playground/README.md'
        doc.parent.mkdir(parents=True)
        doc.write_text('---\ntype: project\ncreated: 2026-09-22\nstatus: active\n---\n# 测试\n', encoding='utf-8')
        self.ws = Workspace(self.root)

    def create_task(self, title='测试任务'):
        return self.ws.mutate('task.create', dict(title=title, origin='agent', goal='验证'),
                              actor='tester', request_id=str(uuid4()))['result']['task_id']

    def create_run(self, task):
        return self.ws.mutate('run.create', dict(task=task, title='执行', command='test',
            host='local', source='fixture', inputs='fixture'), actor='tester',
            request_id=str(uuid4()))['result']['run_id']

    # ---- Frontmatter 类型化 ----
    def test_frontmatter_preserves_comments_and_lists(self):
        path = self.root / 'test.md'
        path.write_text('---\ntype: task\ntitle: "示例"\n# 这是注释\naliases:\n  - 第一项\n  - 第二项\ntags: [a, b]\nstatus: active\n---\n正文内容\n', encoding='utf-8')
        props = _frontmatter.read(path)
        self.assertEqual(props['aliases'], ['第一项', '第二项'])
        self.assertEqual(props['tags'], ['a', 'b'])
        self.assertEqual(props['title'], '示例')
        _frontmatter.update(path, {'title': '新标题'})
        text = path.read_text(encoding='utf-8')
        self.assertIn('# 这是注释', text)
        self.assertIn('正文内容', text)
        self.assertIn('aliases:', text)

    def test_frontmatter_rejects_duplicate_keys(self):
        path = self.root / 'test.md'
        path.write_text('---\ntype: task\ntitle: a\ntitle: b\n---\n', encoding='utf-8')
        with self.assertRaises(_frontmatter.FrontmatterError):
            _frontmatter.read(path)

    # ---- Project CRUD ----
    def test_project_create_and_update(self):
        result = self.ws.mutate('project.create', dict(title='新项目'),
                                actor='tester', request_id='pc1')
        name = result['result']['name']
        self.assertIn('新项目', name)
        project_id = result['result']['project_id']
        self.ws.mutate('project.update', dict(project=project_id, title='改名了', aliases=['别名']),
                       actor='tester', request_id='pu1', if_version=self.ws.version('project', project_id))
        info = self.ws.project(project_id)
        self.assertEqual(info['title'], '改名了')

    def test_project_pause_resume(self):
        result = self.ws.mutate('project.create', dict(title='暂停测试'),
                                actor='tester', request_id='pp1')
        pid = result['result']['project_id']
        self.ws.mutate('project.pause', dict(project=pid, reason='暂停一下'),
                       actor='tester', request_id='pause1', if_version=self.ws.version('project', pid))
        info = self.ws.project(pid)
        self.assertEqual(info['status'], 'paused')
        self.ws.mutate('project.resume', dict(project=pid, reason='恢复'),
                       actor='tester', request_id='resume1', if_version=self.ws.version('project', pid))
        self.assertEqual(self.ws.project(pid)['status'], 'active')

    # ---- Run 更新与重命名 ----
    def test_run_update_fields(self):
        task = self.create_task()
        run = self.create_run(task)
        self.ws.mutate('run.start', dict(task=task, run=run),
                       actor='tester', request_id='rs1', if_version=self.ws.version('run', run, task))
        self.ws.mutate('run.update', dict(task=task, run=run, result='中间结果', add_evidence=['证据1']),
                       actor='tester', request_id='ru1', if_version=self.ws.version('run', run, task))
        info = self.ws.run(task, run)
        self.assertEqual(info['result'], '中间结果')
        self.assertIn('证据1', info['evidence'])

    def test_run_rename_display_title(self):
        task = self.create_task()
        run = self.create_run(task)
        self.ws.mutate('run.rename', dict(task=task, run=run, title='新展示名'),
                       actor='tester', request_id='rr1', if_version=self.ws.version('run', run, task))
        record_path = self.ws.run(task, run)['record']
        sidecar = _management.read_sidecar(Path(record_path))
        self.assertEqual(sidecar['display_title'], '新展示名')
        # 原 title 保留
        self.assertEqual(self.ws.run(task, run)['title'], '执行')

    # ---- 删除与恢复 ----
    def test_task_delete_undelete(self):
        task = self.create_task()
        self.ws.mutate('task.delete', dict(task=task, reason='不需要了'),
                       actor='tester', request_id='td1', if_version=self.ws.version('task', task))
        info = self.ws.task(task)
        self.assertTrue(info.get('deleted_at'))
        self.ws.mutate('task.undelete', dict(task=task, reason='搞错了'),
                       actor='tester', request_id='tu1', if_version=self.ws.version('task', task))
        self.assertFalse(self.ws.task(task).get('deleted_at'))

    def test_run_delete_requires_terminal(self):
        task = self.create_task()
        run = self.create_run(task)
        with self.assertRaises((GovernanceError, ValueError)):
            self.ws.mutate('run.delete', dict(task=task, run=run, reason='删除'),
                           actor='tester', request_id='rd1', if_version=self.ws.version('run', run, task))

    def test_run_delete_undelete(self):
        task = self.create_task()
        run = self.create_run(task)
        self.ws.mutate('run.start', dict(task=task, run=run),
                       actor='tester', request_id='rs2', if_version=self.ws.version('run', run, task))
        self.ws.mutate('run.finish', dict(task=task, run=run, status='failed', result='失败了'),
                       actor='tester', request_id='rf1', if_version=self.ws.version('run', run, task))
        self.ws.mutate('run.delete', dict(task=task, run=run, reason='清理'),
                       actor='tester', request_id='rd2', if_version=self.ws.version('run', run, task))
        record_path = self.ws.run(task, run)['record']
        sidecar = _management.read_sidecar(Path(record_path))
        self.assertTrue(sidecar.get('deleted_at'))
        self.ws.mutate('run.undelete', dict(task=task, run=run, reason='恢复'),
                       actor='tester', request_id='ru2', if_version=self.ws.version('run', run, task))
        sidecar = _management.read_sidecar(Path(record_path))
        self.assertFalse(sidecar.get('deleted_at'))

    # ---- Run 归档 ----
    def test_run_archive_unarchive(self):
        task = self.create_task()
        run = self.create_run(task)
        self.ws.mutate('run.start', dict(task=task, run=run),
                       actor='tester', request_id='rs3', if_version=self.ws.version('run', run, task))
        self.ws.mutate('run.finish', dict(task=task, run=run, status='completed', result='完成',
                       exit_code=0, evidence=['证据']),
                       actor='tester', request_id='rf2', if_version=self.ws.version('run', run, task))
        self.ws.mutate('run.archive', dict(task=task, run=run, reason='归档'),
                       actor='tester', request_id='ra1', if_version=self.ws.version('run', run, task))
        record_path = self.ws.run(task, run)['record']
        sidecar = _management.read_sidecar(Path(record_path))
        self.assertTrue(sidecar.get('archived_at'))
        self.ws.mutate('run.unarchive', dict(task=task, run=run, reason='恢复'),
                       actor='tester', request_id='ra2', if_version=self.ws.version('run', run, task))
        sidecar = _management.read_sidecar(Path(record_path))
        self.assertFalse(sidecar.get('archived_at'))

    # ---- 编号高水位 ----
    def test_high_watermark_bump(self):
        task = self.create_task()
        self.assertEqual(self.ws.task(task)['task_number'], '1')
        from dummysys_core._management import bump_high_watermark
        n = bump_high_watermark(self.root, '00-Playground')
        self.assertEqual(n, 2)

    # ---- 隐式删除拒绝 ----
    def test_implicit_delete_rejected(self):
        task = self.create_task()
        doc = self.root / 'dmy_vault/30-项目/00-Playground' / f'[task {self.ws.task(task)["task_number"]}][20260923]测试任务' / 'README.md'
        # 创建一个额外文件然后试图通过 mutate 删除它
        # 这里用 monkeypatch 模拟 prepare 删除文件
        original_apply = self.ws._apply
        def bad_apply(root, action, p, actor):
            result = original_apply(root, action, p, actor)
            # 删除一个已有文件模拟隐式删除
            for f in root.rglob('README.md'):
                if 'task' in f.parent.name and f.parent.name != '00-Playground':
                    f.unlink()
                    break
            return result
        self.ws._apply = bad_apply
        with self.assertRaises((GovernanceError, ValueError)) as ctx:
            self.ws.mutate('task.create', dict(title='删除测试', origin='agent', goal='测试'),
                          actor='tester', request_id='del1')

    # ---- 计划契约 ----
    def test_plan_dry_run_returns_token(self):
        result = self.ws.mutate('project.create', dict(title='计划测试'),
                                actor='tester', request_id='pl1')
        pid = result['result']['project_id']
        plan = self.ws.plan('project.rename', dict(project=pid, title='新名字', reason='测试'),
                           actor='tester')
        self.assertIsNotNone(plan.get('plan_token'))
        self.assertTrue(plan.get('dry_run'))

    # ---- Run update 不允许 terminal 修改 ----
    def test_run_update_terminal_denied(self):
        task = self.create_task()
        run = self.create_run(task)
        self.ws.mutate('run.start', dict(task=task, run=run),
                       actor='tester', request_id='rs4', if_version=self.ws.version('run', run, task))
        self.ws.mutate('run.finish', dict(task=task, run=run, status='failed', result='失败'),
                       actor='tester', request_id='rf3', if_version=self.ws.version('run', run, task))
        with self.assertRaises((GovernanceError, ValueError)):
            self.ws.mutate('run.update', dict(task=task, run=run, host='新主机'),
                           actor='tester', request_id='ru3', if_version=self.ws.version('run', run, task))

    # ---- 父删除不覆盖子标记 ----
    def test_project_delete_checks_runs(self):
        result = self.ws.mutate('project.create', dict(title='删除检查'),
                                actor='tester', request_id='pdel1')
        pid = result['result']['project_id']
        name = result['result']['name']
        task = self.ws.mutate('task.create', dict(project=name, title='子任务', origin='agent', goal='测试'),
                              actor='tester', request_id='tc2')['result']['task_id']
        run = self.create_run(task)
        # 有 planned Run 时不可删除
        with self.assertRaises((GovernanceError, ValueError)):
            self.ws.mutate('project.delete', dict(project=pid, reason='测试'),
                           actor='tester', request_id='pd2', if_version=self.ws.version('project', pid))


if __name__ == '__main__':
    unittest.main()
