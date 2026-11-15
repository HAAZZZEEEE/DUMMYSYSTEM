"""系统沙盘、实际导航与迟到响应隔离。"""
from unittest.mock import patch

from playwright.sync_api import expect
from tests.browser.browser_fixture import BrowserCase, A
from tests.helpers import write_json


class OverviewBrowserTests(BrowserCase):
    def test_server_inventory_and_narrow_layout(self):
        write_json(self.ws / 'runtime/servers/profiles.json', dict(schema_version=1,
            profiles=[dict(alias='test-server', tags=['example'],
                hardware=dict(generation='Example Gen', product='Example Server（待核）', chip='Example Chip', checked_at='2026-10-27'), ssh=dict(
                host='192.0.2.1', user='root', password='secret-sentinel')),
                dict(alias='offline-server', tags=[], ssh=dict(host='192.0.2.2', user='root'),
                     hardware=dict(reason='SSH超时', checked_at='2026-10-27'))]))
        self.page.get_by_role('button', name='↻ 刷新沙盘', exact=True).click()
        panel = self.page.get_by_role('region', name='服务器档案', exact=True)
        expect(panel).to_contain_text('test-server')
        expect(panel).to_contain_text('Example Server')
        expect(panel.get_by_role('columnheader', name='代际', exact=True)).to_be_visible()
        expect(panel.get_by_role('columnheader', name='产品', exact=True)).to_be_visible()
        expect(panel.get_by_role('columnheader', name='芯片', exact=True)).to_be_visible()
        expect(panel.get_by_role('columnheader', name='宿主服务器型号')).to_have_count(0)
        expect(panel).not_to_contain_text('offline-server')
        toggle = panel.get_by_role('button', name='显示无法连接的服务器')
        toggle.click()
        expect(toggle).to_have_attribute('aria-pressed', 'true')
        expect(panel).to_contain_text('offline-server')
        toggle.click()
        expect(panel).not_to_contain_text('offline-server')
        expect(panel).to_contain_text('192.0.2.1:22')
        expect(panel).to_contain_text('ssh.password')
        expect(panel).not_to_contain_text('secret-sentinel')
        self.page.set_viewport_size(dict(width=700, height=900))
        self.assertTrue(panel.evaluate('(e) => e.scrollWidth <= e.clientWidth + 1'))
        self.page.screenshot(path=str(self.output / 'servers-narrow.png'), full_page=True)

    def test_storage_cached_then_background_refresh(self):
        import threading
        from collections import namedtuple
        from workbench.storage import StorageMonitor
        gate = threading.Event()
        entered = threading.Event()
        self.addCleanup(gate.set)
        usage = namedtuple('Usage', 'total used free')

        def probe(path):
            entered.set()
            gate.wait(10)
            return usage(100 * 1024**3, 30 * 1024**3, 70 * 1024**3)

        monitor = StorageMonitor(self.ws, probe=probe)
        monitor._sample = dict(total=100 * 1024**3, used=80 * 1024**3, free=20 * 1024**3,
                               volume='C:\\', updated_at='2026-10-22T00:00:00Z')
        monitor._ranking = dict(top=[dict(project_id='small', title='较小项目', bytes=5 * 1024**3, partial=False),
                                    dict(project_id=A, title='项目 A', bytes=10 * 1024**3, partial=False)],
                                workspace_bytes=100 * 1024**3, projects_bytes=20 * 1024**3,
                                project_count=3, incomplete=False, updated_at='2026-10-22T00:00:00Z')
        self.application.storage = monitor
        self.page.get_by_role('button', name='↻ 刷新沙盘', exact=True).click()
        panel = self.page.get_by_role('region', name='存储空间看板')
        expect(panel).to_contain_text('DUMMYSYS 总占用')
        expect(panel.locator('.ov-storage-summary > strong')).to_have_text('100 GiB')
        expect(panel).not_to_contain_text('工作区所在磁盘')
        self.assertTrue(entered.wait(2))
        expect(panel.get_by_role('button', name='正在采集…')).to_be_disabled()
        gate.set()
        expect(panel.get_by_role('region', name='项目空间 TOP 5')).to_contain_text('10 GiB')
        expect(panel.get_by_role('button', name='刷新容量')).to_be_enabled()
        expect(panel.locator('.ov-storage-ranking button').first).to_have_text('项目 A')
        self.assertEqual(panel.locator('.ov-storage-bar > span').evaluate_all('(els) => els.map(e => e.style.width)'), ['10%', '5%'])
        expect(panel.get_by_role('img')).to_have_attribute('aria-label', '项目 A 10.0%，较小项目 5.0%，其他项目 5.0%，公共资源 80.0%')
        self.page.screenshot(path=str(self.output / 'storage-light.png'), full_page=True)
        self.page.set_viewport_size(dict(width=700, height=900))
        self.assertTrue(panel.evaluate('(e) => e.scrollWidth <= e.clientWidth + 1'))
        self.page.screenshot(path=str(self.output / 'storage-narrow.png'), full_page=True)

    def setUp(self):
        super().setUp()
        name = '[task 1][20261022]推进中的工作'
        docs = self.docs[A] / name
        docs.mkdir()
        (docs / 'README.md').write_text('---\ntitle: 推进中的工作\nstatus: blocked\n---\n', encoding='utf-8')
        write_json(self.ws / 'runtime/project_src/项目 A' / name / 'runs/[20261022-120000]功能验证/run.json',
                   dict(run_id='overview-run', title='功能验证', status='running', created_at='2026-10-22T12:00:00Z'))
        self.stats_patch = patch.object(self.application, '_ptr_read', return_value=dict(total_calls=15,
            started_at='2026-10-22T10:00:00Z', commands=[dict(command='dmy project list', calls=10), dict(command='dmy check', calls=5)]))
        self.stats_patch.start()
        self.addCleanup(self.stats_patch.stop)
        self.page.get_by_role('button', name='回到首页', exact=True).click()
        expect(self.page.locator('.ov-project')).to_have_count(2)
        expect(self.page.locator('.ov-ranking li')).to_have_count(2)

    def test_filters_project_navigation_and_return(self):
        self.page.get_by_role('button', name='有待推进', exact=True).click()
        expect(self.page.locator('.ov-project')).to_have_count(1)
        self.page.get_by_role('button', name='打开项目：项目 A', exact=True).click()
        expect(self.page.locator('#empty-state')).to_be_hidden()
        expect(self.page.locator('#project-title')).to_have_text('项目 A')
        self.page.get_by_role('button', name='回到首页', exact=True).click()
        expect(self.page.locator('.ov-project')).to_have_count(1)
        self.page.get_by_role('button', name='全部', exact=True).click()
        expect(self.page.locator('.ov-project')).to_have_count(2)
        self.page.get_by_role('button', name='有运行中记录', exact=True).click()
        expect(self.page.locator('.ov-project')).to_have_count(1)
        self.page.locator('.ov-activity-row').first.click()
        expect(self.page.locator('#dir-summary')).to_contain_text('功能验证')

    def test_refresh_failure_retry_and_late_response(self):
        self.page.route('**/api/v1/overview', lambda route: route.fulfill(status=503,
            content_type='application/json', body='{"error":{"message":"暂时无法读取"}}'))
        self.page.get_by_role('button', name='↻ 刷新沙盘', exact=True).click()
        expect(self.page.locator('.ov-notice')).to_contain_text('暂时无法读取')
        self.page.unroute('**/api/v1/overview')
        self.page.get_by_role('button', name='重新读取', exact=True).click()
        expect(self.page.locator('.ov-project')).to_have_count(2)
        self.page.add_script_tag(content='''window.__overviewPending = null;
          const original = window.fetch;
          window.fetch = async (...args) => {
            const result = await original(...args);
            if (String(args[0]).endsWith('/overview')) {
              await new Promise(resolve => window.__overviewPending = resolve);
            }
            return result;
          };''')
        self.page.get_by_role('button', name='↻ 刷新沙盘', exact=True).click()
        self.page.wait_for_function('window.__overviewPending !== null')
        self.page.get_by_role('button', name='打开项目：项目 A', exact=True).click()
        self.page.evaluate('window.__overviewPending()')
        expect(self.page.locator('#project-title')).to_have_text('项目 A')
        expect(self.page.locator('#empty-state')).to_be_hidden()

    def test_themes_narrow_layout_and_keyboard(self):
        self.page.screenshot(path=str(self.output / 'overview-light.png'), full_page=True)
        self.page.locator('.ov-project').first.focus()
        self.page.keyboard.press('Enter')
        expect(self.page.locator('#empty-state')).to_be_hidden()
        self.page.get_by_role('button', name='回到首页', exact=True).click()
        expect(self.page.locator('.ov-project')).to_have_count(2)
        self.page.get_by_role('button', name='设置', exact=True).click()
        self.page.get_by_role('radio', name='深色', exact=True).click()
        self.page.get_by_role('button', name='关闭设置', exact=True).click()
        expect(self.page.locator('html')).to_have_attribute('data-theme', 'dark')
        self.page.screenshot(path=str(self.output / 'overview-dark.png'), full_page=True)
        self.page.set_viewport_size(dict(width=900, height=900))
        self.assertTrue(self.page.locator('#empty-state').evaluate('(e) => e.scrollWidth <= e.clientWidth + 1'))
        self.page.screenshot(path=str(self.output / 'overview-narrow.png'), full_page=True)
