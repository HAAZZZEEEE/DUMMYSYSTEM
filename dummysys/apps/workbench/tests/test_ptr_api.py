"""治理读写 HTTP 契约：/api/v1/ptr/* 一律经 dmy 子进程，不直写记录。"""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.fake_dmy import RecordingDmy
from tests.helpers import build_application, build_workspace
from tests.test_web import WebTestBase, PID_A
from workbench import dmy
from workbench.dmy import _cap_cache
from workbench.web import create_app

TASK_ID = "22222222-2222-4222-8222-222222222222"
RUN_ID = "33333333-3333-4333-8333-333333333333"


class PtrWebTestBase(WebTestBase):
    """在 WebTestBase 上注入 RecordingDmy 并预置负责人。"""

    def setUp(self):
        super().setUp()
        _cap_cache.clear()  # 防止 capabilities 缓存跨测试串数据
        self.dmy = RecordingDmy(data={'ok': True})
        self.application, _ = build_application(self.ws, self.task_root, dmy=self.dmy,
                                                obsidian_vault_path=str(self.ws / "d" / "vault"))
        self.application.set_preferences_path(self.task_root / "state" / "preferences.json")
        self.app = create_app(self.application, self.instance, lambda: "tok-gen",
                              static_dir=self.static)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        self.csrf = self._session()
        self.client.patch('/api/v1/preferences', json={'actor': 'alice'},
                          headers={'X-CSRF-Token': self.csrf})

    def create_body(self, **extra):
        return {'project': PID_A, 'title': '探查', 'origin': 'user', 'goal': '验证写路径',
                'request_id': 'req-1', **extra}


# 与 dmy.WORKBENCH_ACTIONS 同步；CLI capabilities 里的动作全部接线 → 全 ready。
_READY_ACTIONS = tuple(sorted(dmy.WORKBENCH_ACTIONS))
_ALL_OPS = [f'{kind}.{op}' for kind in ('project', 'task', 'run')
            for op in ('create', 'update', 'rename', 'move', 'archive', 'unarchive',
                       'delete', 'undelete', 'pause', 'resume', 'start', 'finish', 'handoff')]


def _cap_data(actions=()):
    """构造 capabilities data，只含指定 actions（模拟 dmy capabilities 自述）。"""
    return {'version': '0.1.0', 'contract_version': 2,
            'actions': {a: {'params': {}, 'requires_plan': False,
                            'version_kind': None, 'description': ''} for a in actions},
            'transitions': {}, 'error_codes': []}


class SurfaceTest(PtrWebTestBase):
    def setUp(self):
        super().setUp()
        self.dmy.capabilities = _cap_data(_ALL_OPS)  # CLI 自述全部动作

    def test_surface_lists_ready_and_missing_ops(self):
        response = self.client.get('/api/v1/ptr/surface')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()['data']
        # CLI 有且工作台已接 → ready
        for action in _READY_ACTIONS:
            kind, op = action.split('.', 1)
            self.assertEqual(data[kind][op]['status'], 'ready', action)
        # CLI 有但工作台未接（如 project.move）→ missing/未接线
        for action in _ALL_OPS:
            if action in _READY_ACTIONS:
                continue
            kind, op = action.split('.', 1)
            if data[kind].get(op):
                self.assertEqual(data[kind][op]['status'], 'missing', action)
        self.assertEqual(data['origins'], ['user', 'agent'])
        self.assertIn('active', data['task_statuses'])
        self.assertEqual(data['run_finish_statuses'], ['completed', 'failed', 'cancelled'])

    def test_surface_reports_resolved_cli(self):
        data = self.client.get('/api/v1/ptr/surface').get_json()['data']
        self.assertIn('command', data['cli'])
        self.assertIn(data['cli']['source'], ('env', 'registered', 'venv'))

    def test_surface_missing_reasons(self):
        # 已接线但 CLI 不支持 → 工具版本不支持
        self.dmy.capabilities = _cap_data(['task.create'])
        _cap_cache.clear()
        data = self.client.get('/api/v1/ptr/surface').get_json()['data']
        self.assertEqual(data['task']['create']['status'], 'ready')
        self.assertEqual(data['task']['update']['status'], 'missing')
        self.assertIn('不支持', data['task']['update'].get('reason', ''))
        # CLI 不可读 → 依赖未就绪
        self.dmy.capabilities = None
        self.dmy.error = ('CLI_UNAVAILABLE', 'dmy 不可用')
        _cap_cache.clear()
        data = self.client.get('/api/v1/ptr/surface').get_json()['data']
        for action in _READY_ACTIONS:
            kind, op = action.split('.', 1)
            self.assertEqual(data[kind][op]['status'], 'missing', action)
            self.assertIn('无法读取', data[kind][op].get('reason', ''))


class TaskWriteTest(PtrWebTestBase):
    def test_create_task_forwards_argv_and_ids(self):
        with mock.patch.object(self.application.catalog, 'refresh') as refresh:
            response = self._post('/api/v1/ptr/task/create', self.create_body(), csrf=self.csrf)
        self.assertEqual(response.status_code, 200)
        argv = self.dmy.last
        body = argv[argv.index('task'):]
        self.assertEqual(body[:2], ['task', 'create'])
        self.assertEqual(self.dmy.flags('--workspace'), [str(self.ws)])
        self.assertEqual(self.dmy.flags('--actor'), ['alice'])
        self.assertEqual(self.dmy.flags('--request-id'), ['req-1'])
        self.assertNotIn('--if-version', argv)
        self.assertEqual(self.dmy.flags('--origin'), ['user'])
        self.assertEqual(self.dmy.flags('--goal'), ['验证写路径'])
        refresh.assert_called_once()

    def test_update_requires_if_version_and_note(self):
        response = self._post('/api/v1/ptr/task/update',
                              {'task': TASK_ID, 'note': 'x', 'request_id': 'req-2'},
                              csrf=self.csrf)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['error']['code'], 'VERSION_REQUIRED')
        self.assertEqual(self.dmy.calls, [])

    def test_update_passes_status_owner_and_scope(self):
        response = self._post('/api/v1/ptr/task/update', {
            'task': TASK_ID, 'note': '推进中', 'if_version': 'v1', 'request_id': 'req-3',
            'status': 'blocked', 'owner': 'bob', 'accepted': True,
            'read_paths': ['C:/a'], 'clear_write_paths': True,
        }, csrf=self.csrf)
        self.assertEqual(response.status_code, 200)
        argv = self.dmy.last
        for flag, value in (('--task', TASK_ID), ('--note', '推进中'), ('--if-version', 'v1'),
                            ('--status', 'blocked'), ('--owner', 'bob'), ('--read-path', 'C:/a')):
            self.assertEqual(self.dmy.flags(flag), [value], flag)
        self.assertIn('--accepted', argv)
        self.assertIn('--clear-write-paths', argv)

    def test_task_status_must_be_enum(self):
        response = self._post('/api/v1/ptr/task/update', {
            'task': TASK_ID, 'note': 'x', 'if_version': 'v1', 'request_id': 'req-4',
            'status': 'archived',
        }, csrf=self.csrf)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.dmy.calls, [])

    def test_origin_must_be_user_or_agent(self):
        response = self._post('/api/v1/ptr/task/create',
                              self.create_body(origin='sysadmin'), csrf=self.csrf)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.dmy.calls, [])

    def test_handoff_forwards_authorization(self):
        response = self._post('/api/v1/ptr/task/handoff', {
            'task': TASK_ID, 'owner': 'bob', 'note': '移交', 'authorization': '会议纪要',
            'if_version': 'v1', 'request_id': 'req-5',
        }, csrf=self.csrf)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.dmy.flags('--authorization'), ['会议纪要'])
        self.assertEqual(self.dmy.flags('--owner'), ['bob'])


class RunWriteTest(PtrWebTestBase):
    def test_create_run_requires_core_fields(self):
        response = self._post('/api/v1/ptr/run/create',
                              {'task': TASK_ID, 'title': '跑一次', 'request_id': 'req-6'},
                              csrf=self.csrf)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.dmy.calls, [])

    def test_create_run_forwards_command(self):
        response = self._post('/api/v1/ptr/run/create', {
            'task': TASK_ID, 'title': '跑一次', 'host': 'BOX', 'source': 'unknown',
            'inputs': 'unknown', 'command': 'python x.py', 'request_id': 'req-7',
        }, csrf=self.csrf)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.dmy.flags('--command'), ['python x.py'])
        self.assertEqual(self.dmy.flags('--host'), ['BOX'])

    def test_start_and_finish_need_if_version(self):
        for path, body in (
            ('/api/v1/ptr/run/start', {'task': TASK_ID, 'run': RUN_ID, 'request_id': 'r'}),
            ('/api/v1/ptr/run/finish', {'task': TASK_ID, 'run': RUN_ID, 'status': 'completed',
                                        'result': 'ok', 'request_id': 'r'}),
        ):
            response = self._post(path, body, csrf=self.csrf)
            self.assertEqual(response.status_code, 400, path)
            self.assertEqual(response.get_json()['error']['code'], 'VERSION_REQUIRED')
        self.assertEqual(self.dmy.calls, [])

    def test_finish_rejects_running_status(self):
        response = self._post('/api/v1/ptr/run/finish', {
            'task': TASK_ID, 'run': RUN_ID, 'status': 'running', 'result': 'x',
            'if_version': 'v1', 'request_id': 'req-8',
        }, csrf=self.csrf)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.dmy.calls, [])

    def test_finish_requires_result_and_forwards_evidence(self):
        response = self._post('/api/v1/ptr/run/finish', {
            'task': TASK_ID, 'run': RUN_ID, 'status': 'completed', 'result': '',
            'if_version': 'v1', 'request_id': 'req-9',
        }, csrf=self.csrf)
        self.assertEqual(response.status_code, 400)
        response = self._post('/api/v1/ptr/run/finish', {
            'task': TASK_ID, 'run': RUN_ID, 'status': 'completed', 'result': '通过',
            'exit_code': 0, 'evidence': ['C:/log.txt'], 'if_version': 'v1',
            'request_id': 'req-9',
        }, csrf=self.csrf)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.dmy.flags('--evidence'), ['C:/log.txt'])
        self.assertEqual(self.dmy.flags('--exit-code'), ['0'])


class ErrorMappingTest(PtrWebTestBase):
    def test_dmy_codes_map_to_http_status(self):
        cases = [('VERSION_CONFLICT', 409), ('NOT_FOUND', 404), ('OWNER_CONFLICT', 403),
                 ('INVALID_ARGUMENT', 400), ('INSTALLATION_CHANGED', 409),
                 ('REQUEST_CONFLICT', 409), ('CLI_UNAVAILABLE', 502), ('INVALID_STATE', 409)]
        for code, status in cases:
            with self.subTest(code=code):
                self.dmy = RecordingDmy(error=(code, f'{code} 详情'))
                self.application, _ = build_application(self.ws, self.task_root, dmy=self.dmy,
                                                        obsidian_vault_path=str(self.ws / "d" / "vault"))
                self.application.set_preferences_path(self.task_root / "state" / "preferences.json")
                self.app = create_app(self.application, self.instance, lambda: "tok-gen",
                                      static_dir=self.static)
                self.app.config["TESTING"] = True
                self.client = self.app.test_client()
                self.csrf = self._session()
                self.client.patch('/api/v1/preferences', json={'actor': 'alice'},
                                  headers={'X-CSRF-Token': self.csrf})
                response = self._post('/api/v1/ptr/task/create', self.create_body(), csrf=self.csrf)
                self.assertEqual(response.status_code, status, code)
                self.assertEqual(response.get_json()['error']['code'], code)

    def test_empty_actor_uses_workbench_default_for_write(self):
        self.client.patch('/api/v1/preferences', json={'actor': ''},
                          headers={'X-CSRF-Token': self.csrf})
        response = self._post('/api/v1/ptr/task/create', self.create_body(), csrf=self.csrf)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.dmy.flags('--actor'), ['workbench'])

    def test_missing_request_id_is_400(self):
        body = self.create_body()
        body.pop('request_id')
        response = self._post('/api/v1/ptr/task/create', body, csrf=self.csrf)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['error']['code'], 'REQUEST_REQUIRED')
        self.assertEqual(self.dmy.calls, [])

    def test_cli_crash_is_502(self):
        self.dmy = RecordingDmy(error=('CLI_UNAVAILABLE', 'dmy 不可用'))
        self.application, _ = build_application(self.ws, self.task_root, dmy=self.dmy,
                                                obsidian_vault_path=str(self.ws / "d" / "vault"))
        self.application.set_preferences_path(self.task_root / "state" / "preferences.json")
        self.app = create_app(self.application, self.instance, lambda: "tok-gen",
                              static_dir=self.static)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        self.csrf = self._session()
        self.client.patch('/api/v1/preferences', json={'actor': 'alice'},
                          headers={'X-CSRF-Token': self.csrf})
        response = self._post('/api/v1/ptr/task/create', self.create_body(), csrf=self.csrf)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.get_json()['error']['code'], 'CLI_UNAVAILABLE')

    def test_ptr_write_requires_csrf(self):
        response = self._post('/api/v1/ptr/task/create', self.create_body(), csrf='')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.dmy.calls, [])

    def test_show_task_uses_read_path_without_actor(self):
        self.dmy = RecordingDmy(data={'title': 'x', 'version': 'v9', 'owner': 'alice'})
        self.application, _ = build_application(self.ws, self.task_root, dmy=self.dmy,
                                                obsidian_vault_path=str(self.ws / "d" / "vault"))
        self.application.set_preferences_path(self.task_root / "state" / "preferences.json")
        self.app = create_app(self.application, self.instance, lambda: "tok-gen",
                              static_dir=self.static)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        self.csrf = self._session()
        response = self.client.get(f'/api/v1/ptr/task?task={TASK_ID}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['data']['version'], 'v9')
        self.assertNotIn('--actor', self.dmy.last)
        self.assertIn('task', self.dmy.last)


class ActorPreferenceTest(WebTestBase):
    def test_actor_is_accepted_and_validated(self):
        csrf = self._session()
        saved = self.client.patch('/api/v1/preferences', json={'actor': '  alice  '},
                                  headers={'X-CSRF-Token': csrf})
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.get_json()['data']['actor'], 'alice')
        bad = self.client.patch('/api/v1/preferences', json={'actor': 'a' * 65},
                                headers={'X-CSRF-Token': csrf})
        self.assertEqual(bad.status_code, 400)
        self.assertIn('负责人', bad.get_json()['error']['message'])
        # 未知字段仍被拒绝。
        unknown = self.client.patch('/api/v1/preferences', json={'actorx': 'x'},
                                    headers={'X-CSRF-Token': csrf})
        self.assertEqual(unknown.status_code, 400)


class MigrationWriteTest(PtrWebTestBase):
    def test_migrate_write_requires_if_plan(self):
        response = self._post('/api/v1/ptr/task/rename', {
            'task': TASK_ID, 'title': '新名', 'reason': 'r',
            'request_id': 'mig-1', 'if_version': 'v1',
        }, csrf=self.csrf)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()['error']['code'], 'PLAN_CONFLICT')
        self.assertEqual(self.dmy.calls, [])

    def test_migrate_write_requires_if_version(self):
        response = self._post('/api/v1/ptr/task/rename', {
            'task': TASK_ID, 'title': '新名', 'reason': 'r',
            'request_id': 'mig-2', 'if_plan': 'tok',
        }, csrf=self.csrf)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.dmy.calls, [])

    def test_migrate_write_forwards_if_plan(self):
        response = self._post('/api/v1/ptr/task/rename', {
            'task': TASK_ID, 'title': '新名', 'reason': 'r',
            'request_id': 'mig-3', 'if_version': 'v1', 'if_plan': 'tok-abc',
        }, csrf=self.csrf)
        self.assertEqual(response.status_code, 200)
        self.assertIn('--if-plan', self.dmy.last)
        self.assertEqual(self.dmy.flags('--if-plan'), ['tok-abc'])

    def test_plan_endpoint_calls_dry_run(self):
        response = self._post('/api/v1/ptr/plan', {
            'action': 'task.rename', 'task': TASK_ID, 'title': '新名', 'reason': 'r',
        }, csrf=self.csrf)
        self.assertEqual(response.status_code, 200)
        self.assertIn('--dry-run', self.dmy.last)

    def test_archive_confirmation_is_forwarded_to_plan_and_commit(self):
        for entity, identity in (('task', TASK_ID), ('project', PID_A)):
            with self.subTest(entity=entity):
                body = {entity: identity, 'reason': '保留状态归档', 'allow_unfinished': True,
                    'request_id': 'archive-' + entity, 'if_version': 'v1', 'if_plan': 'token'}
                response = self._post('/api/v1/ptr/plan', {**body, 'action': entity + '.archive'}, csrf=self.csrf)
                self.assertEqual(response.status_code, 200)
                self.assertIn('--allow-unfinished', self.dmy.last)
                response = self._post('/api/v1/ptr/' + entity + '/archive', body, csrf=self.csrf)
                self.assertEqual(response.status_code, 200)
                self.assertIn('--allow-unfinished', self.dmy.last)

    def test_archive_confirmation_rejects_non_boolean(self):
        response = self._post('/api/v1/ptr/plan', {'action': 'task.archive', 'task': TASK_ID,
            'reason': 'r', 'allow_unfinished': 'true'}, csrf=self.csrf)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.dmy.calls, [])

    def test_delete_task_forwards_reason(self):
        response = self._post('/api/v1/ptr/task/delete', {
            'task': TASK_ID, 'reason': '不再需要',
            'request_id': 'del-1', 'if_version': 'v1',
        }, csrf=self.csrf)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.dmy.flags('--reason'), ['不再需要'])

    def test_run_rename_forwards_title(self):
        response = self._post('/api/v1/ptr/run/rename', {
            'task': TASK_ID, 'run': RUN_ID, 'title': '新标题',
            'request_id': 'rr-1', 'if_version': 'v1',
        }, csrf=self.csrf)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.dmy.flags('--title'), ['新标题'])

    def test_project_create_forwards_title(self):
        response = self._post('/api/v1/ptr/project/create', {
            'title': '新项目', 'request_id': 'pc-1',
        }, csrf=self.csrf)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.dmy.flags('--title'), ['新项目'])


class TimeoutSemanticTest(PtrWebTestBase):
    def test_timeout_returns_result_unknown(self):
        self.dmy = RecordingDmy(raise_from=subprocess.TimeoutExpired(['dmy'], 1))
        self.application, _ = build_application(self.ws, self.task_root, dmy=self.dmy,
                                                obsidian_vault_path=str(self.ws / "d" / "vault"))
        self.application.set_preferences_path(self.task_root / "state" / "preferences.json")
        self.app = create_app(self.application, self.instance, lambda: "tok-gen",
                              static_dir=self.static)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        self.csrf = self._session()
        self.client.patch('/api/v1/preferences', json={'actor': 'alice'},
                          headers={'X-CSRF-Token': self.csrf})
        response = self._post('/api/v1/ptr/task/create', self.create_body(), csrf=self.csrf)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.get_json()['error']['code'], 'RESULT_UNKNOWN')

    def test_check_operation_by_request_id(self):
        self.dmy = RecordingDmy(data=[{'id': 'op-1', 'request_id': 'req-lookup', 'status': 'completed'}])
        self.application, _ = build_application(self.ws, self.task_root, dmy=self.dmy,
                                                obsidian_vault_path=str(self.ws / "d" / "vault"))
        self.application.set_preferences_path(self.task_root / "state" / "preferences.json")
        self.app = create_app(self.application, self.instance, lambda: "tok-gen",
                              static_dir=self.static)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        self.csrf = self._session()
        response = self.client.get('/api/v1/ptr/operation?request_id=req-lookup')
        self.assertEqual(response.status_code, 200)


if __name__ == '__main__':
    unittest.main()
