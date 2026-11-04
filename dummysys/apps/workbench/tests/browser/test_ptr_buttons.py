"""治理按钮的前置条件、确认超时、能力加载和补写字段边界。"""
import json
from unittest import mock

from browser_fixture import A, B, BrowserCase, expect
from tests.fake_dmy import RecordingDmy
from workbench.dmy import WORKBENCH_ACTIONS
from workbench.preferences import Preferences

TASK = '[task 1][20261009]按钮任务'


class PtrButtonsTests(BrowserCase):
    def setUp(self):
        patch = mock.patch('workbench.dmy.capabilities', return_value={'contract_version': 2,
            'actions': {name: {} for name in WORKBENCH_ACTIONS}, 'transitions': {}})
        patch.start()
        self.addCleanup(patch.stop)
        super().setUp()
        self.dmy = RecordingDmy(data={'version': 'v1', 'title': '按钮任务', 'owner': 'alice',
            'status': 'completed', 'host': 'local', 'source': 'source', 'inputs': 'input',
            'command': 'echo test', 'exit_code': 0, 'result': '原始结果'})
        self.application._dmy_runner = self.dmy
        docs = self.docs[A] / TASK
        docs.mkdir()
        (docs / 'README.md').write_text('---\ntitle: 按钮任务\ntask_id: task-id\nstatus: completed\n---\n', encoding='utf-8')
        run = self.ws / 'runtime/project_src/项目 A' / TASK / 'runs/[20261009-090000]按钮运行'
        run.mkdir(parents=True)
        (run / 'run.json').write_text(json.dumps({'run_id': 'run-id', 'title': '按钮运行', 'status': 'running'}), encoding='utf-8')
        self.project()

    def actor(self):
        self.page.locator('#btn-settings').click()
        with self.page.expect_response(lambda r: r.url.endswith('/api/v1/preferences') and r.request.method == 'PATCH'):
            self.page.get_by_test_id('actor-input').fill('alice')
            self.page.get_by_test_id('actor-input').press('Tab')
        self.page.locator('#settings-close').click()

    def task_menu(self, button):
        self.page.get_by_test_id('task-node').get_by_test_id('target-menu').click()
        self.page.get_by_test_id(button).click()

    def test_missing_actor_has_visible_feedback_without_uncaught_errors(self):
        # 防御旧服务仍返回空身份的情况；正常偏好读取已提供默认身份。
        self.page.route('**/api/v1/preferences', lambda route: route.fulfill(json={
            'schema_version': 1, 'data': {**Preferences.defaults(), 'actor': ''}}))
        self.page.reload()
        self.ready()
        for button in ['edit-task', 'rename-task', 'move-task', 'archive-task', 'delete-task', 'handoff-task', 'new-run']:
            self.task_menu(button)
            expect(self.page.locator('#toast')).to_have_text('请先在设置里填写当前负责人')
            expect(self.page.locator('#ptr-dialog')).not_to_be_visible()
        for button in ['finish-run', 'update-run', 'rename-run', 'archive-run', 'unarchive-run', 'delete-run', 'undelete-run']:
            self.page.get_by_test_id('run-node').get_by_test_id('target-menu').click()
            self.page.get_by_test_id(button).click()
            expect(self.page.locator('#toast')).to_have_text('请先在设置里填写当前负责人')
        self.assertEqual(self.page_errors, [])

    def test_default_actor_is_visible_and_used_without_setup(self):
        self.page.locator('#btn-settings').click()
        expect(self.page.get_by_test_id('actor-input')).to_have_value('workbench')
        self.page.locator('#settings-close').click()
        self.task_menu('archive-task')
        expect(self.page.locator('#ptr-dialog')).to_be_visible()
        self.page.locator('#ptr-cancel').click()

    def test_capabilities_are_requested_after_authentication(self):
        codes = []
        self.page.on('response', lambda r: codes.append(r.status) if r.url.endswith('/api/v1/ptr/surface') else None)
        self.context.clear_cookies()
        self.page.goto('about:blank')
        self.page.goto(self.origin + '/#token=' + self.app.extensions['bootstrap_issuer']())
        expect(self.page.locator('#app')).to_be_visible()
        self.project()
        self.page.get_by_test_id('project-menu').click()
        expect(self.page.get_by_role('menuitem', name='新建项目', exact=True)).to_be_enabled()
        self.assertEqual(codes, [200])

    def test_confirmation_timeout_allows_rearming_and_plan_submission(self):
        self.actor()
        self.dmy.data = {'version': 'v1', 'title': '按钮任务', 'status': 'active', 'plan_token': 'plan-1', 'plan': {}}
        self.task_menu('archive-task')
        self.page.locator('#ptr-field-reason').fill('测试归档')
        self.page.clock.install()
        self.page.locator('#ptr-submit').click()
        self.page.clock.fast_forward(4100)
        expect(self.page.locator('#ptr-submit')).to_have_text('归档任务')
        self.page.locator('#ptr-submit').click()
        with self.page.expect_response(lambda r: r.url.endswith('/api/v1/ptr/plan')):
            self.page.locator('#ptr-submit').click()
        expect(self.page.locator('#ptr-status')).to_have_attribute('data-state', 'plan')
        with self.page.expect_response(lambda r: r.url.endswith('/api/v1/ptr/task/archive')) as saved:
            self.page.locator('#ptr-submit').click()
        self.assertTrue(json.loads(saved.value.request.post_data)['allow_unfinished'])
        self.assertEqual(json.loads(saved.value.request.post_data)['reason'], '测试归档')
        expect(self.page.locator('#ptr-dialog')).not_to_be_visible()

    def test_unfinished_project_shows_tasks_and_requires_an_extra_confirmation(self):
        self.actor()
        readme = self.docs[A] / TASK / 'README.md'
        readme.write_text(readme.read_text(encoding='utf-8').replace('status: completed', 'status: active'), encoding='utf-8')
        self.dmy.data = {'version': 'v1', 'title': '项目 A', 'plan_token': 'plan-project', 'plan': {}}
        self.page.get_by_test_id('project-menu').click()
        self.page.get_by_role('menuitem', name='归档项目…', exact=True).click()
        expect(self.page.locator('#ptr-description')).to_contain_text('1 个未完成 Task')
        expect(self.page.locator('#ptr-description')).to_contain_text('按钮任务（进行中）')
        self.page.locator('#ptr-field-reason').fill('   ')
        self.page.locator('#ptr-submit').click()
        expect(self.page.locator('#ptr-submit')).to_have_text('仍然归档（保留Task状态）')
        self.assertFalse(any('project' in call and 'archive' in call for call in self.dmy.calls))
        with self.page.expect_response(lambda r: r.url.endswith('/api/v1/ptr/plan')) as planned:
            self.page.locator('#ptr-submit').click()
        self.assertTrue(json.loads(planned.value.request.post_data)['allow_unfinished'])
        self.assertEqual(json.loads(planned.value.request.post_data)['reason'], '用户手动归档')
        expect(self.page.locator('#ptr-status')).to_have_attribute('data-state', 'plan')
        with self.page.expect_response(lambda r: r.url.endswith('/api/v1/ptr/project/archive')) as saved:
            self.page.locator('#ptr-submit').click()
        self.assertEqual(json.loads(saved.value.request.post_data)['reason'], '用户手动归档')

    def test_finished_task_archive_needs_no_unfinished_confirmation(self):
        self.actor()
        self.dmy.data = {'version': 'v1', 'title': '按钮任务', 'status': 'completed', 'plan_token': 'plan-done', 'plan': {}}
        self.task_menu('archive-task')
        self.assertFalse(self.page.locator('#ptr-field-reason').evaluate('el => el.required'))
        with self.page.expect_response(lambda r: r.url.endswith('/api/v1/ptr/plan')) as planned:
            self.page.locator('#ptr-submit').click()
        self.assertNotIn('allow_unfinished', json.loads(planned.value.request.post_data))
        self.assertEqual(json.loads(planned.value.request.post_data)['reason'], '用户手动归档')
        expect(self.page.locator('#ptr-status')).to_have_attribute('data-state', 'plan')
        with self.page.expect_response(lambda r: r.url.endswith('/api/v1/ptr/task/archive')) as saved:
            self.page.locator('#ptr-submit').click()
        self.assertEqual(json.loads(saved.value.request.post_data)['reason'], '用户手动归档')

    def test_run_archive_uses_default_reason_when_blank(self):
        self.actor()
        self.page.get_by_test_id('run-node').get_by_test_id('target-menu').click()
        self.page.get_by_test_id('archive-run').click()
        self.assertFalse(self.page.locator('#ptr-field-reason').evaluate('el => el.required'))
        self.page.locator('#ptr-submit').click()
        with self.page.expect_response(lambda r: r.url.endswith('/api/v1/ptr/run/archive')) as saved:
            self.page.locator('#ptr-submit').click()
        self.assertEqual(json.loads(saved.value.request.post_data)['reason'], '用户手动归档')

    def test_terminal_run_submission_contains_only_added_evidence(self):
        self.actor()
        self.page.get_by_test_id('run-node').get_by_test_id('target-menu').click()
        self.page.get_by_test_id('update-run').click()
        expect(self.page.locator('#ptr-field-status')).to_be_disabled()
        expect(self.page.locator('#ptr-field-host')).to_be_disabled()
        self.page.locator('#ptr-field-add_evidence').fill('C:/evidence/check.json')
        with self.page.expect_response(lambda r: r.url.endswith('/api/v1/ptr/run/update')) as saved:
            self.page.locator('#ptr-submit').click()
        body = json.loads(saved.value.request.post_data)
        self.assertEqual(body['add_evidence'], ['C:/evidence/check.json'])
        self.assertEqual(set(body), {'task', 'run', 'request_id', 'if_version', 'add_evidence'})

    def test_deleted_task_recovery_button_remains_reachable(self):
        self.actor()
        readme = self.docs[A] / TASK / 'README.md'
        readme.write_text(readme.read_text(encoding='utf-8').replace('status: completed', 'status: completed\ndeleted_at: 2026-10-09'), encoding='utf-8')
        self.page.reload()
        self.ready()
        trash = self.page.get_by_test_id('deleted-items')
        trash.locator(':scope > summary').click()
        trash.get_by_test_id('deleted-project-group').locator(':scope > summary').click(position={'x': 8, 'y': 10})
        box = trash.get_by_test_id('deleted-task-group')
        expect(box).to_contain_text('按钮任务')
        self.page.locator('#btn-settings').click()
        self.page.get_by_test_id('task-view-select').select_option('cards')
        self.page.locator('#settings-close').click()
        expect(box).to_be_visible()
        box.get_by_test_id('trash-restore-task').click()
        self.page.locator('#ptr-field-reason').fill('恢复任务')
        self.page.locator('#ptr-submit').click()
        with self.page.expect_response(lambda r: r.url.endswith('/api/v1/ptr/task/undelete')):
            self.page.locator('#ptr-submit').click()

    def test_deleted_run_recovery_button_remains_reachable(self):
        self.actor()
        run = self.ws / 'runtime/project_src/项目 A' / TASK / 'runs/[20261009-090000]按钮运行'
        (run / 'run-management.json').write_text(json.dumps({'run_id': 'run-id', 'deleted_at': '2026-10-09'}), encoding='utf-8')
        self.page.reload()
        self.ready()
        trash = self.page.get_by_test_id('deleted-items')
        trash.locator(':scope > summary').click()
        trash.get_by_test_id('deleted-project-group').locator(':scope > summary').click(position={'x': 8, 'y': 10})
        box = trash.get_by_test_id('deleted-task-group')
        box.locator(':scope > summary').click(position={'x': 8, 'y': 10})
        box.get_by_test_id('trash-restore-run').click()
        self.page.locator('#ptr-field-reason').fill('恢复运行')
        self.page.locator('#ptr-submit').click()
        with self.page.expect_response(lambda r: r.url.endswith('/api/v1/ptr/run/undelete')):
            self.page.locator('#ptr-submit').click()

    def test_deleted_project_recovery_button_remains_reachable(self):
        self.actor()
        readme = self.docs[A] / 'README.md'
        readme.write_text(readme.read_text(encoding='utf-8').replace('status: "active"', 'status: "active"\ndeleted_at: 2026-10-09'), encoding='utf-8')
        self.page.reload()
        self.ready()
        self.project(B)
        trash = self.page.get_by_test_id('deleted-items')
        trash.locator(':scope > summary').click()
        box = trash.get_by_test_id('deleted-project-group')
        expect(box).to_contain_text('项目 A（项目已删除）')
        box.get_by_test_id('trash-restore-project').click()
        self.page.locator('#ptr-field-reason').fill('恢复项目')
        self.page.locator('#ptr-submit').click()
        with self.page.expect_response(lambda r: r.url.endswith('/api/v1/ptr/project/undelete')) as saved:
            self.page.locator('#ptr-submit').click()
        self.assertEqual(json.loads(saved.value.request.post_data)['project'], A)
