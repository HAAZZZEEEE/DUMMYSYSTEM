"""真实缓存格式与跨项目身份契约，使用临时工作区。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dummysys_core.workspace import Workspace
from dummysys_core import _migration as migration, _records as records
from dummysys_core.operations import GovernanceError


class MigrationContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'dmy_vault/30-项目').mkdir(parents=True)
        self.ws = Workspace(self.root)
        self.ws._mover = lambda root, src, dst, executable: (dst.parent.mkdir(parents=True, exist_ok=True), src.rename(dst))
        self.ws._link_state = lambda: {'unresolved': set(), 'resolved': set(), 'identity': {}}
        self.seq = 0

    def tearDown(self):
        self.tmp.cleanup()

    def change(self, action, body, kind=None, identity=None):
        self.seq += 1
        version = self.ws.version(kind, identity) if kind else None
        token = self.ws.plan(action, body, actor='alice')['plan_token'] if action in ('task.move', 'project.rename') else None
        return self.ws.mutate(action, body, actor='alice', request_id=str(self.seq), if_version=version, if_plan=token)

    def project(self, title):
        self.change('project.create', {'title': title, 'created': '2026-09-24'})
        return '[20260924]' + title

    def test_move_preserves_run_and_number_reservation(self):
        a, b = self.project('来源'), self.project('目标')
        task = self.change('task.create', {'project': a, 'title': '任务', 'origin': 'user', 'goal': '验证'})['result']['task_id']
        run = self.change('run.create', {'task': task, 'title': '旧执行', 'host': 'local', 'source': 'test', 'inputs': 'test', 'command': 'test'})['result']['run_id']
        self.ws.mutate('run.finish', {'task': task, 'run': run, 'status': 'cancelled', 'result': '取消计划'}, actor='alice', request_id='cancel', if_version=self.ws.version('run', run, task))
        old = self.ws.run_path(task, run)
        before = old.read_bytes()
        self.change('task.move', {'task': task, 'to_project': b, 'reason': '整理', 'authorization': '用户要求'}, 'task', task)
        doc, resource, props = records.locate_task(self.root, task)
        self.assertEqual(resource.parent.name, b)
        self.assertEqual(props['project_id'], records.properties(self.root / 'dmy_vault/30-项目' / b / 'README.md')['project_id'])
        self.assertEqual(self.ws.run_path(task, run).read_bytes(), before)
        source_readme = (self.root / 'dmy_vault/30-项目' / a / 'README.md').read_text(encoding='utf-8')
        self.assertIn('已迁出 Task 1', source_readme)
        self.assertIn(f'30-项目/{b}/', source_readme)
        self.assertEqual(records.read_json(resource / 'task.json')['repositories'], [])
        next_task = self.change('task.create', {'project': a, 'title': '新任务', 'origin': 'user', 'goal': '验证'})['result']['task_id']
        self.assertEqual(self.ws.task(next_task)['task_number'], '2')

    def test_project_rename_replay_by_uuid(self):
        name = self.project('来源')
        identity = self.ws.project(name)['project_id']
        body = {'project': identity, 'title': '新名称', 'reason': '整理'}
        version = self.ws.version('project', identity)
        token = self.ws.plan('project.rename', body, actor='alice')['plan_token']
        first = self.ws.mutate('project.rename', body, actor='alice', request_id='rename', if_version=version, if_plan=token)
        replay = self.ws.mutate('project.rename', body, actor='alice', request_id='rename', if_version=version, if_plan=token)
        self.assertEqual(first['operation_id'], replay['operation_id'])
        self.assertEqual(self.ws.project(identity)['title'], '新名称')

    def test_open_run_blocks_project_rename(self):
        name = self.project('来源')
        task = self.change('task.create', {'project': name, 'title': '任务', 'origin': 'user', 'goal': '验证'})['result']['task_id']
        self.change('run.create', {'task': task, 'title': '执行', 'host': 'local', 'source': 'test', 'inputs': 'test', 'command': 'test'})
        with self.assertRaises(GovernanceError):
            self.ws.plan('project.rename', {'project': name, 'title': '新名称', 'reason': '整理'}, actor='alice')

    def test_resume_after_document_move(self):
        name = self.project('来源')
        identity = self.ws.project(name)['project_id']
        body = {'project': identity, 'title': '恢复后', 'reason': '恢复测试'}
        version = self.ws.version('project', identity)
        token = self.ws.plan('project.rename', body, actor='alice')['plan_token']
        def interrupted(root, src, dst, executable):
            src.rename(dst)
            raise RuntimeError('模拟文档移动后进程中断')
        self.ws._mover = interrupted
        with self.assertRaises(RuntimeError):
            self.ws.mutate('project.rename', body, actor='alice', request_id='resume', if_version=version, if_plan=token)
        with self.assertRaises(GovernanceError):
            self.change('project.create', {'title': '禁止穿插写入'})
        self.ws._mover = lambda *args: self.fail('已经移动的目录不能再次调用 mover')
        receipt = self.ws.mutate('project.rename', body, actor='alice', request_id='resume', if_version=version, if_plan=token)
        self.assertEqual(receipt['status'], 'completed')
        self.assertEqual(self.ws.project(identity)['title'], '恢复后')

    def test_real_obsidian_count_map_and_moved_source(self):
        vault = self.root / 'dmy_vault'
        old, new = vault / 'old', vault / 'new'
        old.mkdir()
        (old / 'README.md').write_text('---\nproject_id: abc\n---\n', encoding='utf-8')
        cache = {'unresolved': {}, 'resolved': {'old/README.md': {'old/README.md': 2}}}
        with patch.object(migration, 'obsidian_eval', return_value='=> ' + json.dumps(cache)):
            before = migration.link_snapshot(self.root)
        old.rename(new)
        cache['resolved'] = {'new/README.md': {'new/README.md': 2}}
        with patch.object(migration, 'obsidian_eval', return_value='=> ' + json.dumps(cache)):
            after = migration.link_snapshot(self.root)
        self.assertEqual(migration.verify_links(before, after, old, new)['checked_identity'], 1)

    def test_markdown_rewrite_allowed_but_attachment_preserved(self):
        name = self.project('来源')
        base = self.root / 'dmy_vault/30-项目' / name
        (base / 'image.bin').write_bytes(b'original')
        def mover(root, src, dst, executable):
            src.rename(dst)
            with (dst / 'README.md').open('a', encoding='utf-8') as stream:
                stream.write('\n链接已更新\n')
        self.ws._mover = mover
        self.change('project.rename', {'project': name, 'title': '新名称', 'reason': '整理'}, 'project', name)
        self.assertEqual((base.parent / '[20260924]新名称/image.bin').read_bytes(), b'original')


if __name__ == '__main__':
    unittest.main()
