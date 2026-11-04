"""首页配置、页面包边界和 HTTP 隔离行为。"""
import json
from urllib.parse import quote

from tests.helpers import write_json
from tests.test_web import PID_A, WebTestBase


class HomepageTests(WebTestBase):
    def setUp(self):
        super().setUp()
        self.resources = self.ws / 'r/proj'
        self.pages = self.resources / '页面 包#&'
        self.pages.mkdir(parents=True)
        (self.pages / '首页.html').write_text('<h1>首页</h1>', encoding='utf-8')
        (self.pages / 'data.json').write_text('{"值": 1}', encoding='utf-8')
        self.config = self.resources / 'workbench.json'
        self.configure()
        self._session()

    def configure(self, root='resources', path='页面 包#&/首页.html'):
        write_json(self.config, {'schema_version': 1, 'homepage': {'root_id': root, 'path': path}})

    def home(self):
        return self.client.get('/api/v1/homepage', query_string={'project_id': PID_A})

    def test_missing_and_invalid_config_do_not_break_roots(self):
        self.config.unlink()
        response = self.client.get('/api/v1/roots', query_string={'project_id': PID_A})
        self.assertIsNone(response.json['data']['homepage'])
        self.config.write_text('{broken', encoding='utf-8')
        response = self.client.get('/api/v1/roots', query_string={'project_id': PID_A})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['data']['homepage']['error'])
        self.assertEqual(self.home().status_code, 400)

    def test_html_and_relative_data_work_from_opaque_origin(self):
        response = self.home()
        self.assertEqual(response.status_code, 200)
        url = response.json['data']['url']
        for address in (url, url.rsplit('/', 1)[0] + '/data.json'):
            asset = self.client.get(address, headers={'Origin': 'null'})
            self.assertEqual(asset.status_code, 200)
            self.assertEqual(asset.headers['Access-Control-Allow-Origin'], 'null')
            self.assertIn('sandbox allow-scripts;', asset.headers['Content-Security-Policy'])
            self.assertNotIn('allow-same-origin', asset.headers['Content-Security-Policy'])
            self.assertEqual(asset.headers['Cache-Control'], 'no-store')
            asset.close()

    def test_homepage_metadata_requires_session_and_api_rejects_null_origin(self):
        client = self.app.test_client()
        self.assertEqual(client.get('/api/v1/homepage?project_id=' + PID_A).status_code, 401)
        self.assertEqual(self.client.get('/api/v1/projects', headers={'Origin': 'null'}).status_code, 403)
        self.assertEqual(self.client.get('/project-pages/unknown/index.html').status_code, 403)

    def test_capability_cannot_escape_or_read_hidden_or_executable_files(self):
        url = self.home().json['data']['url'].rsplit('/', 1)[0]
        (self.resources / 'secret.json').write_text('private', encoding='utf-8')
        (self.pages / '.env').write_text('private', encoding='utf-8')
        (self.pages / 'run.py').write_text('private', encoding='utf-8')
        for relative in ('../secret.json', '%2e%2e/secret.json', '.env', 'run.py', 'C:/test.html'):
            with self.subTest(relative=relative):
                response = self.client.get(url + '/' + relative)
                self.assertIn(response.status_code, (400, 403))
        self.configure(path='../outside.html')
        self.assertEqual(self.home().status_code, 400)

    def test_config_change_revokes_old_page_capability(self):
        url = self.home().json['data']['url']
        (self.pages / 'other.html').write_text('other', encoding='utf-8')
        self.configure(path='页面 包#&/other.html')
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_page_symlink_cannot_read_sibling_package(self):
        outside = self.resources / 'other'
        outside.mkdir()
        (outside / 'private.json').write_text('private', encoding='utf-8')
        try:
            (self.pages / 'alias').symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest(f'本机未授予符号链接创建权限：{error}')
        url = self.home().json['data']['url'].rsplit('/', 1)[0]
        self.assertEqual(self.client.get(url + '/alias/private.json').status_code, 403)

    def test_homepage_last_location_persists_without_directory_resolution(self):
        value = {'project_id': PID_A, 'root_id': 'homepage', 'relative_path': ''}
        self.application.save_preferences({'last_location': value})
        self.assertEqual(self.application.load_preferences()['last_location'], value)

    def test_repo_homepage_respects_registered_subpaths(self):
        repo = self.root / 'repo'
        (repo / 'allowed/pages').mkdir(parents=True)
        (repo / 'allowed/pages/index.html').write_text('repo', encoding='utf-8')
        write_json(self.ws / 'runtime/state/workspace/repositories.json', {'checkouts': {'demo': {'path': str(repo)}}})
        binding_path = self.ws / 'runtime/project_src/proj/project.json'
        binding = json.loads(binding_path.read_text(encoding='utf-8'))
        binding['repositories'] = [{'repo_id': 'demo', 'paths': ['allowed', 'second']}]
        write_json(binding_path, binding)
        self.application.catalog.refresh()
        self.configure('repo:demo', 'allowed/pages/index.html')
        response = self.home()
        self.assertEqual(response.status_code, 200)
        asset = self.client.get(response.json['data']['url'])
        self.assertEqual(asset.status_code, 200)
        asset.close()
        declaration = json.loads(self.config.read_text(encoding='utf-8'))
        declaration['homepage']['references'] = {'repoReport': {'root_id':'repo:demo','path':'allowed/pages'}}
        write_json(self.config, declaration)
        base = self.home().json['data']['url'].rsplit('/', 1)[0]
        asset = self.client.get(base + '/_refs/repoReport/index.html')
        self.assertEqual(asset.status_code, 200)
        asset.close()
        declaration['homepage']['references']['repoReport']['path'] = 'outside'
        write_json(self.config, declaration)
        self.assertEqual(self.home().status_code, 403)
        self.configure('repo:demo', 'outside/index.html')
        self.assertEqual(self.home().status_code, 403)

    def reference(self, **options):
        original = self.resources / '原始报告 [1]#&'
        (original / 'pages').mkdir(parents=True, exist_ok=True)
        (original / 'pages/report.html').write_text('<html><head></head><body>原件</body></html>', encoding='utf-8')
        (original / 'data.json').write_text('{"原件":1}', encoding='utf-8')
        config = json.loads(self.config.read_text(encoding='utf-8'))
        config['homepage']['references'] = {
            'reports': {'root_id': 'resources', 'path': original.name, **options}}
        write_json(self.config, config)
        return original

    def test_reference_and_package_assets_coexist_and_source_edits_are_live(self):
        original = self.reference()
        base = self.home().json['data']['url'].rsplit('/', 1)[0]
        address = base + '/_refs/reports/pages/report.html'
        response = self.client.get(address, headers={'Origin': 'null'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, (original / 'pages/report.html').read_bytes())
        self.assertNotIn('allow-same-origin', response.headers['Content-Security-Policy'])
        response.close()
        (original / 'pages/report.html').write_text('原件已更新', encoding='utf-8')
        response = self.client.get(address)
        self.assertEqual(response.data.decode('utf-8'), '原件已更新')
        response.close()
        for path in ('data.json', '_refs/reports/data.json'):
            response = self.client.get(base + '/' + path)
            self.assertEqual(response.status_code, 200)
            response.close()

    def test_reference_can_include_package_styles_and_scripts_without_changing_original(self):
        original = self.reference(styles=['阅读.css'], scripts=['reader.js'])
        (self.pages / '阅读.css').write_text('h1{color:green}', encoding='utf-8')
        (self.pages / 'reader.js').write_text('document.title="阅读"', encoding='utf-8')
        source = (original / 'pages/report.html').read_bytes()
        base = self.home().json['data']['url'].rsplit('/', 1)[0]
        response = self.client.get(base + '/_refs/reports/pages/report.html')
        self.assertEqual(response.status_code, 200)
        self.assertIn(base + '/' + quote('阅读.css'), response.data.decode('utf-8'))
        self.assertIn(base + '/reader.js', response.data.decode('utf-8'))
        self.assertEqual(source, (original / 'pages/report.html').read_bytes())
        response.close()
        (self.pages / 'reader.js').unlink()
        self.assertEqual(self.client.get(base + '/_refs/reports/pages/report.html').status_code, 404)

    def test_reference_does_not_authorize_other_directories_or_file_types(self):
        original = self.reference()
        (original / '.private.json').write_text('private', encoding='utf-8')
        (original / 'run.py').write_text('private', encoding='utf-8')
        (self.resources / 'private.json').write_text('private', encoding='utf-8')
        base = self.home().json['data']['url'].rsplit('/', 1)[0]
        for path in ('_refs/missing/data.json', '_refs/reports', '_refs/reports/.private.json',
                     '_refs/reports/run.py', '_refs/reports/../private.json',
                     '_refs/reports/%2e%2e/private.json', '_refs/private.json'):
            with self.subTest(path=path):
                self.assertIn(self.client.get(base + '/' + path).status_code, (400, 403))

    def test_reference_binding_change_revokes_existing_capability(self):
        self.reference()
        base = self.home().json['data']['url'].rsplit('/', 1)[0]
        config = json.loads(self.config.read_text(encoding='utf-8'))
        config['homepage']['references']['reports']['path'] = self.pages.name
        write_json(self.config, config)
        self.assertEqual(self.client.get(base + '/_refs/reports/data.json').status_code, 403)
        self.assertEqual(self.client.get(base + '/data.json').status_code, 403)

    def test_missing_reference_directory_does_not_break_package_files(self):
        self.reference()
        config = json.loads(self.config.read_text(encoding='utf-8'))
        config['homepage']['references']['reports']['path'] = '尚未存在的目录'
        write_json(self.config, config)
        response = self.home()
        self.assertEqual(response.status_code, 200)
        base = response.json['data']['url'].rsplit('/', 1)[0]
        response = self.client.get(base + '/data.json')
        self.assertEqual(response.status_code, 200)
        response.close()
        self.assertEqual(self.client.get(base + '/_refs/reports/report.html').status_code, 404)

    def test_invalid_reference_declarations_and_includes_are_rejected(self):
        for options in ({'styles':['../style.css']}, {'scripts':['https://other/a.js']},
                        {'scripts':['.hidden/a.js']}, {'styles':['_refs/reports/a.css']},
                        {'scripts':[None]}, {'styles':{}}, {'unexpected':True}):
            with self.subTest(options=options):
                self.reference(**options)
                self.assertEqual(self.home().status_code, 400)
        self.reference()
        config = json.loads(self.config.read_text(encoding='utf-8'))
        config['homepage']['references']['../escape'] = config['homepage']['references'].pop('reports')
        write_json(self.config, config)
        self.assertEqual(self.home().status_code, 400)

    def test_reference_symlink_cannot_escape_declared_directory(self):
        original = self.reference()
        outside = self.resources / 'outside'
        outside.mkdir()
        (outside / 'private.json').write_text('private', encoding='utf-8')
        try:
            (original / 'alias').symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest(f'本机未授予符号链接创建权限：{error}')
        base = self.home().json['data']['url'].rsplit('/', 1)[0]
        self.assertEqual(self.client.get(base + '/_refs/reports/alias/private.json').status_code, 403)
