"""排序、类型筛选、统计须基于全目录，并参与分页游标身份。"""
import os
from tests.test_web import WebTestBase


class DirectoryOptionsTests(WebTestBase):
    def query(self, **options):
        return self.client.post('/api/v1/list', json={'target': self._target(), **options},
                                headers={'X-CSRF-Token': self.csrf})

    def setUp(self):
        super().setUp()
        self.csrf = self._session()

    def test_sort_and_filter_before_pagination(self):
        root = self.ws / 'd/vault'
        for n in range(205):
            (root / f'file{n}.txt').write_text(str(n), encoding='utf-8')
        first = self.query(kind='file', sort='name_desc', limit=200).get_json()['data']
        second = self.query(kind='file', sort='name_desc', limit=200,
                            cursor=first['next_cursor']).get_json()['data']
        names = [e['name'] for e in first['entries'] + second['entries']]
        self.assertEqual(len(names), 208)
        self.assertEqual(len(names), len(set(names)))
        self.assertLess(names.index('file204.txt'), names.index('file2.txt'))
        self.assertEqual(first['summary']['files'], 208)
        self.assertEqual(first['summary']['directories'], 0)
        self.assertIsNone(second['next_cursor'])

    def test_cursor_rejects_different_sort_or_type(self):
        cursor = self.query(limit=1).get_json()['data']['next_cursor']
        for options in ({'sort': 'modified'}, {'kind': 'file'}):
            response = self.query(cursor=cursor, **options)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.get_json()['error']['code'], 'STALE_CURSOR')

    def test_modified_sort_directory_first_and_exact_summary(self):
        root = self.ws / 'd/vault'
        os.utime(root / 'a.py', (100, 100))
        os.utime(root / '笔记.md', (200, 200))
        data = self.query(sort='modified').get_json()['data']
        self.assertEqual([e['name'] for e in data['entries']], ['sub', 'README.md', '笔记.md', 'a.py'])
        self.assertEqual(data['summary']['bytes'], sum(p.stat().st_size for p in root.iterdir() if p.is_file()))
        self.assertEqual(self.query(kind='dir').get_json()['data']['summary']['total'], 1)
        self.assertEqual(self.query(filter='不存在').get_json()['data']['summary']['total'], 0)

    def test_invalid_options_are_400(self):
        for value in ('unknown', None, [], {}):
            for field in ('sort', 'kind'):
                self.assertEqual(self.query(**{field: value}).status_code, 400)

    def test_density_saved_without_losing_other_preferences(self):
        self.application.save_preferences({'theme': 'dark', 'density': 'compact'})
        self.assertEqual(self.application.load_preferences()['density'], 'compact')
        self.assertEqual(self.application.load_preferences()['theme'], 'dark')
        response = self.client.patch('/api/v1/preferences', json={'density': 'invalid'},
                                     headers={'X-CSRF-Token': self.csrf})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.application.load_preferences()['density'], 'compact')
