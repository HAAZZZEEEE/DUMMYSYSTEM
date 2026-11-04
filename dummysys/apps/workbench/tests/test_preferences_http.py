"""浏览器跨窗口更新以 HTTP 版本契约原子防止覆盖。"""
from tests.test_web import WebTestBase


class PreferencesHTTPTests(WebTestBase):
    def test_etag_if_match_conflict_and_retry_preserve_fields(self):
        csrf = self._session()
        response = self.client.get('/api/v1/preferences')
        revision = response.headers['ETag']
        headers = {'X-CSRF-Token': csrf, 'If-Match': revision}
        saved = self.client.patch('/api/v1/preferences', json={'theme': 'dark'}, headers=headers)
        self.assertEqual(saved.status_code, 200)
        conflict = self.client.patch('/api/v1/preferences', json={'pinned_locations': [self._target()]}, headers=headers)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.get_json()['error']['code'], 'PREFERENCE_CONFLICT')
        headers['If-Match'] = saved.headers['ETag']
        retried = self.client.patch('/api/v1/preferences', json={'pinned_locations': [self._target()]}, headers=headers)
        self.assertEqual(retried.status_code, 200)
        self.assertEqual(retried.get_json()['data']['theme'], 'dark')
        self.assertEqual(retried.get_json()['data']['pinned_locations'], [self._target()])
