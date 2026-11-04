"""多仓库和长名称的根选项卡布局与可达性。"""
import json

from browser_fixture import A, BrowserCase, expect
from tests.helpers import write_json


class RootTabsTests(BrowserCase):
    def prepare(self, count=16, long_names=True):
        self.repo_ids = [('repository-with-a-very-long-name-' + str(i) * 12) if long_names else f'repo-{i}' for i in range(count)]
        checkouts = {}
        for repo_id in self.repo_ids:
            path = self.ws.parent / repo_id
            path.mkdir()
            checkouts[repo_id] = {'path': str(path)}
        write_json(self.ws / 'runtime/state/workspace/repositories.json', {'checkouts': checkouts})
        path = self.ws / 'runtime/project_src/项目 A/project.json'
        binding = json.loads(path.read_text(encoding='utf-8'))
        binding['repositories'] = [{'repo_id': repo_id, 'paths': ['.']} for repo_id in self.repo_ids]
        if long_names:
            binding['repositories'].append({'path': str(path.parent), 'role': '中文超长仓库名称测试' * 8})
        write_json(path, binding)
        self.page.locator('#btn-project-refresh').click()
        self.project()
        expect(self.page.get_by_role('tab')).to_have_count(count + 2 + int(long_names))

    def test_long_names_stay_single_line_and_do_not_widen_page(self):
        self.prepare()
        for width in (1440, 960, 760):
            with self.subTest(width=width):
                self.page.set_viewport_size({'width': width, 'height': 1000})
                metrics = self.page.locator('#root-tabs').evaluate('''host => ({
                    pageWidth: document.documentElement.scrollWidth,
                    viewport: innerWidth,
                    height: host.clientHeight,
                    tabHeight: host.firstElementChild.offsetHeight,
                    widths: [...host.children].map(tab => tab.getBoundingClientRect().width),
                    lines: [...host.children].map(tab => getComputedStyle(tab).whiteSpace)
                })''')
                self.assertLessEqual(metrics['pageWidth'], metrics['viewport'])
                self.assertLessEqual(metrics['height'], metrics['tabHeight'] + 2)
                self.assertTrue(all(width <= 220 for width in metrics['widths']), metrics)
                self.assertTrue(all(line == 'nowrap' for line in metrics['lines']), metrics)
        self.page.screenshot(path=str(self.output / 'root-tabs-narrow.png'))

    def assert_visible_in_strip(self, selector):
        self.page.wait_for_function('''selector => {
            const host = document.getElementById('root-tabs').getBoundingClientRect();
            const tab = document.querySelector(selector)?.getBoundingClientRect();
            return tab && tab.left >= host.left - 1 && tab.right <= host.right + 1;
        }''', arg=selector)

    def test_scroll_buttons_keyboard_selection_and_resize(self):
        self.prepare()
        previous = self.page.locator('#root-tabs-prev')
        following = self.page.locator('#root-tabs-next')
        expect(previous).to_be_visible()
        expect(previous).to_be_disabled()
        expect(following).to_be_enabled()
        following.click()
        self.assertGreater(self.page.locator('#root-tabs').evaluate('host => host.scrollLeft'), 0)
        expect(previous).to_be_enabled()
        # 普通目录刷新不应重置用户手动查看后方选项卡的位置。
        self.page.locator('#btn-refresh').click()
        self.ready()
        self.assertGreater(self.page.locator('#root-tabs').evaluate('host => host.scrollLeft'), 0)
        # DOM click 不触发 Playwright 的自动滚动，验证产品自身使当前项可见。
        self.page.locator('#root-tabs .root-tab').nth(-2).evaluate('tab => tab.click()')
        self.ready(root='repo:' + self.repo_ids[-1])
        self.assert_visible_in_strip('#root-tabs .active')
        self.page.locator('#root-tabs .active').focus()
        self.page.keyboard.press('End')
        self.assert_visible_in_strip('#root-tabs .root-tab:last-child')
        self.page.keyboard.press('Enter')
        expect(self.page.locator('#root-tabs .root-tab:last-child')).to_have_attribute('aria-selected', 'true')
        self.assert_visible_in_strip('#root-tabs .active')
        expect(following).to_be_disabled()
        for width in (960, 760, 1440):
            self.page.set_viewport_size({'width': width, 'height': 1000})
            self.assert_visible_in_strip('#root-tabs .active')
        self.page.keyboard.press('Home')
        self.assert_visible_in_strip('#root-tabs .root-tab:first-child')
        expect(previous).to_be_disabled()
        self.page.keyboard.press('Enter')
        self.ready()
        self.assert_visible_in_strip('#root-tabs .active')
        self.page.emulate_media(color_scheme='dark', reduced_motion='reduce')
        self.page.screenshot(path=str(self.output / 'root-tabs-dark.png'))

    def test_short_list_hides_scroll_controls(self):
        self.prepare(count=1, long_names=False)
        expect(self.page.locator('#root-tabs-prev')).to_be_hidden()
        expect(self.page.locator('#root-tabs-next')).to_be_hidden()
        self.page.get_by_role('tab').last.click()
        self.ready(root='repo:' + self.repo_ids[0])
        self.assert_visible_in_strip('#root-tabs .active')
        expect(self.page.get_by_role('tab').last).to_have_attribute('title', '代码 ' + self.repo_ids[0])
