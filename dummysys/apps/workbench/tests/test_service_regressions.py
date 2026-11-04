"""在应用和 HTTP 接口复现偏好、并发打开与错误响应缺口。"""
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from tests import test_application as fixtures
from tests.test_web import WebTestBase
from workbench.catalog import InvalidTarget
from workbench.windows import AppUnavailable, OpenFailed


_app, _file = fixtures._app, fixtures._file


class PreferenceRegression(unittest.TestCase):
    setUp = fixtures.PreferencesTest.setUp
    tearDown = fixtures.PreferencesTest.tearDown
    def test_patch_preserves_other_fields(self):
        app, _ = _app(self.ws, None)
        app.save_preferences({'project_order': ['first']})
        app.save_preferences({'pinned_project_ids': ['second']})
        self.assertEqual(app.load_preferences()['project_order'], ['first'])

    def test_parallel_patch_merges(self):
        app, _ = _app(self.ws, None)
        with ThreadPoolExecutor(2) as pool:
            results = [pool.submit(app.save_preferences, patch) for patch in
                       ({'theme': 'dark'}, {'pinned_project_ids': ['first']})]
            for result in results:
                result.result()
        prefs = app.load_preferences()
        self.assertEqual(prefs['theme'], 'dark')
        self.assertEqual(prefs['pinned_project_ids'], ['first'])

    def test_invalid_preference_rejected(self):
        app, _ = _app(self.ws, None)
        for patch in ({'theme': 'blue'}, {'secret': True}, {'project_order': 'abc'},
                      {'last_location': {'project_id': 'p'}, 'sidebar_width': 'wide'},
                      {'sidebar_width': 199}, {'sidebar_width': 641}, {'sidebar_width': True}):
            with self.subTest(patch=patch), self.assertRaises(InvalidTarget):
                app.save_preferences(patch)

    def test_sidebar_width_roundtrip_and_reset(self):
        app, _ = _app(self.ws, None)
        app.save_preferences({'sidebar_width': 320})
        self.assertEqual(app.load_preferences()['sidebar_width'], 320)
        app.save_preferences({'sidebar_width': None})
        self.assertIsNone(app.load_preferences()['sidebar_width'])


class OpenRegression(unittest.TestCase):
    setUp = fixtures.OpenFlowTest.setUp
    tearDown = fixtures.OpenFlowTest.tearDown
    def test_concurrent_duplicate_is_dispatched_once(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        def dispatch(path):
            calls.append(path)
            entered.set()
            self.assertTrue(release.wait(3))
        self.opener.vscode_open = dispatch
        with ThreadPoolExecutor(2) as pool:
            first = pool.submit(self.application.open, _file(self.ws, 'a.py'), 'vscode_open', 'same')
            self.assertTrue(entered.wait(3))
            second = pool.submit(self.application.open, _file(self.ws, 'a.py'), 'vscode_open', 'same')
            release.set()
            self.assertEqual(first.result(), second.result())
        self.assertEqual(len(calls), 1)

    def test_duplicate_changed_target_rejected(self):
        self.application.open(_file(self.ws, 'a.py'), 'vscode_open', 'same')
        with self.assertRaises(InvalidTarget):
            self.application.open(_file(self.ws, 'b.md'), 'vscode_open', 'same')

    def test_different_sessions_do_not_share_requests(self):
        for session_id in ('a', 'b'):
            self.application.open(_file(self.ws, 'a.py'), 'vscode_open', 'same', session_id=session_id)
        self.assertEqual(len(self.opener.events()), 2)


class HttpRegression(WebTestBase):
    def test_open_failures_are_json(self):
        csrf = self._session()
        for exc, status, code in ((AppUnavailable('程序缺失'), 409, 'APP_UNAVAILABLE'),
                                  (OpenFailed('启动失败'), 502, 'OPEN_FAILED')):
            with self.subTest(code=code), mock.patch.object(self.opener, 'vscode_open', side_effect=exc):
                response = self._post('/api/v1/open', {
                    'target': self._target('a.py'), 'action': 'vscode_open', 'request_id': code,
                }, csrf=csrf)
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.get_json()['error']['code'], code)

    def test_invalid_json_shapes_are_400(self):
        csrf = self._session()
        for endpoint, body in (('/api/v1/list', []), ('/api/v1/list', {}),
                               ('/api/v1/list', {'target': self._target(), 'limit': 'many'}),
                               ('/api/v1/actions', {'target': 7})):
            with self.subTest(endpoint=endpoint, body=body):
                response = self._post(endpoint, body, csrf=csrf)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json()['error']['code'], 'INVALID_REQUEST')

    def test_local_other_port_origin_is_rejected(self):
        response = self.client.post('/api/v1/session', json={'bootstrap_token': self._issue()},
                                    headers={'Origin': 'http://localhost:9876'})
        self.assertEqual(response.status_code, 403)


if __name__ == '__main__':
    unittest.main()
