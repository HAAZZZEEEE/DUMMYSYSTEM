"""复杂项目治理：内容与执行分离、按需路由及可恢复分区迁移。"""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from dummysys_core import _entries
from dummysys_core.layout import governance_paths
from dummysys_core.operations import GovernanceError
from dummysys_core.workspace import Workspace
from dummysys_cli.doccheck import check_docs


class GovernanceLayoutTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        (self.root / 'dmy_vault').mkdir()
        self.ws = Workspace(self.root)
        self.pid = self.mutate('project.create', dict(title='治理夹具', created='2026-10-24'))['project_id']
        self.docs = Path(self.ws.project(self.pid)['document']).parent
        for section, directory in [('entry', '00-入口'), ('system', '10-系统'), ('templates', '90-模板')]:
            path = self.root / 'dmy_vault' / directory
            path.mkdir()
            (path / '说明.md').write_text('# 只读内容\n', encoding='utf-8')
        canonical = self.root / 'dmy_vault/10-系统/Codex工作区指令.md'
        canonical.write_text('# 工作规则\n', encoding='utf-8')
        os.link(canonical, self.root / 'AGENTS.md')
        for filename in ('项目与任务执行规范.md', 'DUMMYSYS目录与资源治理.md', 'Obsidian知识库规范.md'):
            (canonical.parent / filename).write_text('# 规则\n', encoding='utf-8')
        self.ws._mover = self.move
        self.ws._link_state = lambda: {'unresolved': set(), 'resolved': set(), 'identity': {}}
        self.mutate('project.sync', dict(project=self.pid), self.ws.project(self.pid)['version'])

    @staticmethod
    def move(root, source, target, executable=None):
        target.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target)

    def mutate(self, action, params, version=None, **options):
        return self.ws.mutate(action, params, actor='tester', request_id=str(uuid4()),
                              if_version=version, **options)['result']

    def relocate(self, section):
        params = dict(project=self.pid, section=section, reason='验证治理收拢')
        plan = self.ws.plan('governance.relocate', params, actor='tester')
        version = self.ws.project(self.pid)['version']
        request = str(uuid4())
        result = self.ws.mutate('governance.relocate', params, actor='tester', request_id=request,
            if_plan=plan['plan_token'], if_version=version)
        return params, plan, version, request, result

    def test_content_is_not_execution_and_sync_preserves_custom_rules(self):
        topic = self.docs / '专题/README.md'
        topic.parent.mkdir()
        topic.write_text('# 长期说明\n正式汇总须人工审核。\n', encoding='utf-8')
        loose = self.root / 'dmy_vault/30-项目/收藏/README.md'
        loose.parent.mkdir()
        loose.write_text('# 收藏，不是正式项目\n', encoding='utf-8')
        agents = self.docs / 'AGENTS.md'
        agents.write_text(agents.read_text(encoding='utf-8') + '\n正式数据须经用户批准。\n', encoding='utf-8')
        readme = self.docs / 'README.md'
        readme.write_text(readme.read_text(encoding='utf-8') + '\n## 精选\n人工策展入口。\n', encoding='utf-8')
        original = topic.read_bytes()
        task = self.mutate('task.create', dict(project=self.pid, title='多次尝试', origin='agent', goal='分析'))['task_id']
        taskdoc = Path(self.ws.task(task)['document'])
        for index in range(4):
            (taskdoc.parent / f'报告{index}.md').write_text('# 当前报告\n', encoding='utf-8')
        for index in range(3):
            run = self.mutate('run.create', dict(task=task, title=f'尝试{index}', host='fixture',
                source='fixture', inputs='fixture', command='fixture'))['run_id']
            self.mutate('run.start', dict(task=task, run=run), self.ws.run(task, run)['version'])
            self.mutate('run.finish', dict(task=task, run=run, status='failed' if index < 2 else 'completed',
                result='夹具，未进入正式汇总', exit_code=1 if index < 2 else 0, evidence=['fixture']),
                self.ws.run(task, run)['version'])
        self.mutate('project.sync', dict(project=self.pid), self.ws.project(self.pid)['version'])
        self.assertEqual(topic.read_bytes(), original)
        self.assertIn('正式数据须经用户批准', agents.read_text(encoding='utf-8'))
        self.assertIn('人工策展入口', readme.read_text(encoding='utf-8'))
        self.assertNotIn('报告3', readme.read_text(encoding='utf-8'))
        self.assertIn('报告3', (self.docs / '目录索引.md').read_text(encoding='utf-8'))
        self.assertEqual(len(self.ws.projects()), 1)
        self.assertEqual(len(self.ws.tasks(self.pid)), 1)
        self.assertEqual([r['status'] for r in self.ws.runs(task)], ['failed', 'failed', 'completed'])
        self.assertFalse((self.root / 'runtime/project_src' / self.docs.name / '专题').exists())
        self.assertEqual(self.ws.sync_preview(self.pid)['changed'], [])
        reading = self.ws.context(task)['reading']
        self.assertTrue(all(r['purpose'] and r['when'] for r in reading))
        self.assertFalse(any('报告' in r['path'] for r in reading))

    def test_create_task_only_creates_readme_and_binding_without_run(self):
        task = self.mutate('task.create', dict(project=self.pid, title='最小任务', origin='agent', goal='验证'))['task_id']
        value = self.ws.task(task)
        doc = Path(value['document'])
        self.assertEqual([p.name for p in doc.parent.iterdir()], ['README.md'])
        self.assertEqual(value['runs'], [])
        self.assertTrue(value['owner'])
        self.assertIn('scope', value['binding'])

    def test_all_sections_relocate_and_managed_operations_use_new_layout(self):
        self.ws.mutate('repo.register', dict(repo='fixture', title='夹具', purpose='测试'),
                       actor='tester', request_id='repo')
        for section in ('entry', 'system', 'templates'):
            params, plan, version, request, first = self.relocate(section)
            retry = self.ws.mutate('governance.relocate', params, actor='tester', request_id=request,
                if_plan=plan['plan_token'], if_version=version)
            self.assertEqual(first, retry)
        paths = governance_paths(self.root)
        self.assertTrue((self.root / 'AGENTS.md').samefile(paths['instructions']))
        self.assertTrue((paths['repositories'] / 'fixture.md').exists())
        self.assertFalse((self.root / 'dmy_vault/10-系统').exists())
        task = self.mutate('task.create', dict(project=self.pid, title='新布局任务', origin='agent', goal='验证'))['task_id']
        self.assertIn('/治理/', self.ws.context(task)['reading'][4]['path'].replace('\\', '/'))
        self.assertEqual(len(self.ws.tasks()), 1)

    def test_interruption_resumes_and_later_change_blocks_rollback(self):
        params = dict(project=self.pid, section='system', reason='中断恢复')
        plan = self.ws.plan('governance.relocate', params, actor='tester')
        version = self.ws.project(self.pid)['version']
        def interrupt(root, source, target, executable=None):
            self.move(root, source, target)
            raise RuntimeError('移动完成后中断')
        self.ws._mover = interrupt
        with self.assertRaisesRegex(RuntimeError, '中断'):
            self.ws.mutate('governance.relocate', params, actor='tester', request_id='interrupt',
                if_plan=plan['plan_token'], if_version=version)
        self.ws._mover = lambda *args: self.fail('已完成移动不应重放')
        result = self.ws.mutate('governance.relocate', params, actor='tester', request_id='interrupt',
            if_plan=plan['plan_token'], if_version=version)
        undo = dict(project=self.pid, operation=result['operation_id'], reason='回滚演练')
        edited = self.docs / '治理/说明.md'
        old = edited.read_bytes()
        edited.write_bytes(b'new work')
        with self.assertRaises(GovernanceError) as error:
            self.ws.plan('governance.rollback', undo, actor='tester')
        self.assertEqual(error.exception.code, 'RECOVERY_CONFLICT')
        edited.write_bytes(old)
        self.ws._mover = self.move
        token = self.ws.plan('governance.rollback', undo, actor='tester')['plan_token']
        self.mutate('governance.rollback', undo, self.ws.project(self.pid)['version'], if_plan=token)
        paths = governance_paths(self.root)
        self.assertTrue((self.root / 'AGENTS.md').samefile(paths['instructions']))
        self.assertTrue((self.root / 'dmy_vault/10-系统/说明.md').exists())

    def test_explicit_layout_is_not_silently_ignored(self):
        (self.root / '.dummysys-docs.json').write_text(json.dumps(dict(schema_version=1,
            documents=[], governance=dict(project_id='missing', sections=['system']))), encoding='utf-8')
        with self.assertRaises(GovernanceError):
            governance_paths(self.root)

    def test_three_sections_can_rollback_in_reverse_order(self):
        receipts = [self.relocate(key)[-1] for key in ('entry', 'system', 'templates')]
        for receipt in reversed(receipts):
            params = dict(project=self.pid, operation=receipt['operation_id'], reason='配套回滚')
            token = self.ws.plan('governance.rollback', params, actor='tester')['plan_token']
            self.mutate('governance.rollback', params, self.ws.project(self.pid)['version'], if_plan=token)
        self.assertTrue((self.root / 'AGENTS.md').samefile(governance_paths(self.root)['instructions']))
        for directory in ('00-入口', '10-系统', '90-模板'):
            self.assertTrue((self.root / 'dmy_vault' / directory).is_dir())

    def test_derived_source_change_requires_review_not_automatic_admission(self):
        source, output = self.root / 'source.md', self.root / 'page.html'
        source.write_text('# 来源\n', encoding='utf-8')
        output.write_text('readable', encoding='utf-8')
        spec = dict(schema_version=1, documents=[], derived_documents=[dict(output='page.html',
            sources=[dict(path='source.md', sha256=hashlib.sha256(source.read_bytes()).hexdigest())],
            rebuild='核对来源后运行项目生成器', coverage=[dict(pattern='*.md', included=['AGENTS.md','source.md'])])])
        (self.root / '.dummysys-docs.json').write_text(json.dumps(spec), encoding='utf-8')
        self.assertEqual(check_docs(self.root, [self.root])['review_required'], [])
        source.write_text('# 新来源\n', encoding='utf-8')
        checked = check_docs(self.root, [self.root])
        self.assertTrue(checked['ok'])
        self.assertEqual(checked['review_required'][0]['code'], 'SOURCE_CHANGED')
        source.unlink()
        self.assertFalse(check_docs(self.root, [self.root])['ok'])
