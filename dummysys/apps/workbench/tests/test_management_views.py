"""治理管理标记在导航与搜索中生效，不改写原始运行证据。"""
import tempfile
import unittest
from pathlib import Path

from tests.helpers import build_application, build_workspace, write_json

PID = 'management-project'
TASK = '[task 1][20261009]任务'
RUN = '[20261009-090000]运行'


class ManagementViewsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.ws = build_workspace(base, {'项目': {'project_id': PID,
            'docs_root': 'dmy_vault/项目', 'resource_root': 'runtime/project_src/项目'}})
        self.task_docs = self.ws / 'dmy_vault/项目' / TASK
        self.task_docs.mkdir()
        (self.task_docs / 'README.md').write_text('---\ntitle: 任务\nstatus: completed\ntask_id: task-id\n---\n', encoding='utf-8')
        self.run_dir = self.ws / 'runtime/project_src/项目' / TASK / 'runs' / RUN
        write_json(self.run_dir / 'run.json', {'run_id': 'run-id', 'title': '原始运行', 'status': 'completed'})
        self.original = (self.run_dir / 'run.json').read_bytes()
        self.app, _ = build_application(self.ws, base / 'client')

    def mark(self, **values):
        write_json(self.run_dir / 'run-management.json', {'run_id': 'run-id', **values})

    def nav(self):
        return self.app.project_nav(PID)

    def test_display_title_does_not_modify_execution_record(self):
        self.mark(display_title='显示名称')
        self.assertEqual(self.nav()['tasks'][0]['runs'][0]['title'], '显示名称')
        self.assertEqual((self.run_dir / 'run.json').read_bytes(), self.original)
        self.assertEqual(self.app.search('显示名称', ['run'])['results'][0]['title'], '显示名称')

    def test_archived_run_keeps_execution_status(self):
        self.mark(archived_at='2026-10-09')
        run = self.nav()['tasks'][0]['runs'][0]
        self.assertEqual(run['status'], 'archived')
        self.assertEqual(run['execution_status'], 'completed')

    def test_deleted_run_moves_to_recovery_collection(self):
        self.mark(deleted_at='2026-10-09')
        task = self.nav()['tasks'][0]
        self.assertEqual(task['runs'], [])
        self.assertEqual(task['deleted_runs'][0]['run_id'], 'run-id')
        self.assertEqual(self.app.search('原始运行', ['run'])['results'], [])

    def test_deleted_task_moves_to_recovery_collection(self):
        readme = self.task_docs / 'README.md'
        readme.write_text(readme.read_text(encoding='utf-8').replace('status: completed', 'status: completed\ndeleted_at: 2026-10-09'), encoding='utf-8')
        nav = self.nav()
        self.assertEqual(nav['tasks'], [])
        self.assertEqual(nav['deleted_tasks'][0]['task_id'], 'task-id')
        self.assertEqual(self.app.search('任务', ['task'])['results'], [])
        self.assertEqual(self.app.search('原始运行', ['run'])['results'], [])

    def test_deleted_project_moves_to_recovery_collection(self):
        readme = self.ws / 'dmy_vault/项目/README.md'
        readme.write_text(readme.read_text(encoding='utf-8').replace('status: "active"', 'status: "active"\ndeleted_at: 2026-10-09'), encoding='utf-8')
        catalog = self.app.list_projects()
        self.assertEqual(catalog['projects'], [])
        self.assertEqual(catalog['deleted_projects'][0]['project_id'], PID)
        self.assertEqual(self.app.search('项目', ['project'])['results'], [])
        self.assertTrue(self.app.list_roots(PID)['roots'], '恢复前仍应能查询对象入口')

    def test_sidecar_for_other_run_is_ignored(self):
        write_json(self.run_dir / 'run-management.json', {'run_id': 'other-run', 'display_title': '错误名称', 'deleted_at': '2026-10-09'})
        self.assertEqual(self.nav()['tasks'][0]['runs'][0]['title'], '原始运行')

    def test_global_deleted_groups_by_source_and_retains_normal_ancestors(self):
        self.mark(deleted_at='2026-10-09')
        data = self.app.catalog.list_deleted()
        self.assertEqual(data['count'], 1)
        project = data['projects'][0]
        self.assertEqual(project['project_id'], PID)
        self.assertFalse(project['deleted'])
        self.assertFalse(project['tasks'][0].get('deleted'))
        self.assertTrue(project['tasks'][0]['runs'][0]['deleted'])

    def test_deleted_project_includes_context_and_counts_only_deleted_objects(self):
        readme = self.ws / 'dmy_vault/项目/README.md'
        readme.write_text(readme.read_text(encoding='utf-8').replace('status: "active"', 'status: "active"\ndeleted_at: 2026-10-09'), encoding='utf-8')
        data = self.app.catalog.list_deleted()
        self.assertEqual(data['count'], 1)
        self.assertTrue(data['projects'][0]['deleted'])
        self.assertEqual(data['projects'][0]['tasks'][0]['runs'][0]['title'], '原始运行')

    def test_deleted_orphan_run_is_collected_but_hidden_from_normal_nav(self):
        orphan = self.ws / 'runtime/project_src/项目/loose/runs/orphan'
        write_json(orphan / 'run.json', {'run_id': 'orphan', 'title': '孤立运行', 'status': 'completed'})
        write_json(orphan / 'run-management.json', {'run_id': 'orphan', 'deleted_at': '2026-10-09'})
        self.assertEqual(self.nav()['orphan_runs'], [])
        self.assertEqual(self.app.catalog.list_deleted()['projects'][0]['orphan_runs'][0]['run_id'], 'orphan')
