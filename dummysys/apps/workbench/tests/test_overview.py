"""总览读取实际导航记录；CLI 统计失败不影响项目展示。"""
from unittest.mock import patch

from tests.test_web import WebTestBase, PID_A
from tests.helpers import write_json
from workbench.dmy import DmyError


class OverviewTests(WebTestBase):
    def task(self, number, status, archived=False, deleted=False):
        name = f'[task {number}][20261022]任务{number}'
        docs = self.ws / 'd/vault' / ('archive' if archived else '') / name
        docs.mkdir(parents=True, exist_ok=True)
        body = f'---\ntask_id: task-{number}\ntitle: 任务{number}\nstatus: {status}\n'
        if deleted:
            body += 'deleted_at: 2026-10-22\n'
        (docs / 'README.md').write_text(body + '---\n', encoding='utf-8')
        return self.ws / 'r/proj' / name

    def test_summary_scope_targets_and_top_five(self):
        self._session()
        task = self.task(1, 'blocked')
        self.task(2, 'completed', archived=True)
        self.task(3, 'active', archived=True)
        self.task(4, 'active', deleted=True)
        write_json(task / 'runs/[20261022-120000]运行/run.json',
                   dict(run_id='run-1', title='运行', status='running', created_at='2026-10-22T12:00:00Z'))
        write_json(self.ws / 'r/proj/历史资产/runs/[20261022-130000]旧运行/run.json',
                   dict(run_id='run-2', title='旧运行', status='completed', created_at='2026-10-22T13:00:00Z'))
        stats = dict(total_calls=28, commands=[dict(command=f'dmy test{i}', calls=7-i) for i in range(7)])
        with patch.object(self.application, '_ptr_read', return_value=stats) as read:
            response = self.client.get('/api/v1/overview')
        self.assertEqual(response.status_code, 200, response.get_json())
        read.assert_called_once_with(['stats'])
        data = response.get_json()['data']
        self.assertEqual(data['totals'], dict(projects=1, tasks=3, completed=1, open_tasks=1, running=1, runs=2))
        self.assertEqual(data['attention_total'], 1)
        self.assertEqual(data['attention'][0]['target']['project_id'], PID_A)
        self.assertEqual(data['recent_runs'][0]['title'], '旧运行')
        self.assertEqual(len(data['usage']['top']), 5)
        self.assertEqual(data['usage']['total_calls'], 28)

    def test_cli_unavailable_is_a_partial_result(self):
        self._session()
        with patch.object(self.application, '_ptr_read', side_effect=DmyError('CLI_UNAVAILABLE', '不可用')):
            response = self.client.get('/api/v1/overview')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()['data']
        self.assertFalse(data['usage']['available'])
        self.assertEqual(data['totals']['projects'], 1)

    def test_authentication_and_origin_are_required(self):
        self.assertEqual(self.client.get('/api/v1/overview').status_code, 401)
        self._session()
        self.assertEqual(self.client.get('/api/v1/overview', headers={'Origin': 'http://evil.invalid'}).status_code, 403)

    def test_archived_projects_are_outside_current_overview(self):
        readme = self.ws / 'd/vault/README.md'
        readme.write_text(readme.read_text(encoding='utf-8').replace('status: "active"', 'status: "archived"'), encoding='utf-8')
        with patch.object(self.application, '_ptr_read', return_value=dict(total_calls=0, commands=[])):
            data = self.application.overview()
        self.assertEqual(data['totals']['projects'], 0)
        self.assertEqual(data['projects'], [])
