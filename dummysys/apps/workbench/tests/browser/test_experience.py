"""工作台布局与效率功能的真实浏览器回归。"""
import re
from browser_fixture import A, B, MANY, BrowserCase, expect


class ExperienceTests(BrowserCase):
    def test_many_quick_results_keep_readable_height(self):
        locations = [{"project_id": A, "root_id": "docs", "relative_path": f"目录 {n}"}
                     for n in range(30)]
        self.application.save_preferences({"pinned_locations": locations})
        self.page.reload()
        expect(self.page.locator('#app')).to_be_visible()
        self.page.keyboard.press("Control+k")
        rows = self.page.get_by_test_id("quick-result")
        expect(rows).to_have_count(32)
        sizes = rows.evaluate_all("rows => rows.map(row => row.getBoundingClientRect().height)")
        self.assertGreaterEqual(min(sizes), 56, f"两行条目高度被挤压：{min(sizes)}")
        self.assertTrue(self.page.locator('#quick-results').evaluate(
            "el => el.scrollHeight > el.clientHeight"), "结果应滚动，而非压缩条目")

    def test_global_search_covers_sticky_table_headers(self):
        for n in range(12):
            (self.docs[A] / f'项目报告{n}.md').write_text('# 报告', encoding='utf-8')
        self.project()
        self.page.locator('#global-search').fill('项目')
        expect(self.page.locator('#search-popover')).to_have_class(re.compile(r'\bopen\b'))
        expect(self.page.locator('#search-results')).to_contain_text('项目报告')
        result = self.page.evaluate("""() => {
          const popup = document.querySelector('#search-popover').getBoundingClientRect();
          const th = document.querySelector('.entries th').getBoundingClientRect();
          const table = document.querySelector('.entries').getBoundingClientRect();
          const x = Math.max(popup.left, table.left) + 8;
          const y = th.top + th.height / 2;
          return {overlap: x < popup.right && y < popup.bottom && y > popup.top,
            covered: !!document.elementFromPoint(x, y)?.closest('#search-popover')};
        }""")
        self.assertTrue(result['overlap'], '夹具必须制造搜索浮层与表头重叠')
        self.assertTrue(result['covered'], '表头不能盖住搜索结果')

    def test_directory_sort_type_reset_and_count(self):
        self.project()
        self.page.locator('#directory-kind').select_option('file')
        expect(self.page.locator('#entries-body .dir-row')).to_have_count(0)
        expect(self.page.locator('#directory-status')).to_contain_text('0 个文件夹')
        self.page.locator('#dir-filter').fill('不存在')
        expect(self.page.locator('#directory-status')).to_contain_text('0 / 0 项')
        self.page.locator('#directory-reset').click()
        expect(self.page.locator('#dir-filter')).to_have_value('')
        expect(self.page.locator('#entries-body .dir-row')).to_have_count(2)
        self.enter(MANY)
        self.page.locator('#directory-sort').select_option('name_desc')
        expect(self.page.locator('#entries-body tr').first).to_contain_text('204')
        expect(self.page.locator('#directory-status')).to_contain_text('200 / 205 项')
        self.page.locator('#btn-more').click()
        expect(self.page.locator('#directory-status')).to_contain_text('205 / 205 项')
        expect(self.page.locator('#entries-body tr').last).to_contain_text('000')

    def test_focus_shortcuts_and_density_survive_reload(self):
        self.project()
        self.page.locator('#btn-focus').click()
        expect(self.page.locator('#sidebar')).to_be_hidden()
        self.page.keyboard.press('Control+k')
        expect(self.page.locator('#sidebar')).to_be_visible()
        expect(self.page.locator('#project-search')).to_be_focused()
        self.page.keyboard.press('Escape')
        self.page.locator('#btn-shortcuts').click()
        expect(self.page.locator('#shortcuts-dialog')).to_be_visible()
        self.page.keyboard.press('Escape')
        expect(self.page.locator('#btn-shortcuts')).to_be_focused()
        self.page.locator('#btn-settings').click()
        with self.page.expect_response(lambda r: r.url.endswith('/preferences') and r.request.method == 'PATCH'):
            self.page.locator('#density-select').select_option('compact')
        self.page.locator('#settings-close').click()
        self.page.reload()
        self.ready()
        expect(self.page.locator('html')).to_have_attribute('data-density', 'compact')
        self.assertLessEqual(self.page.locator('#entries-body tr').first.bounding_box()['height'], 34)

    def test_visual_states_and_reduced_motion(self):
        self.project()
        self.page.screenshot(path=str(self.output / 'workspace-light.png'))
        self.page.locator('#btn-settings').click()
        self.page.locator('#theme-select').select_option('dark')
        self.page.locator('#settings-close').click()
        expect(self.page.locator('html')).to_have_attribute('data-theme', 'dark')
        self.page.screenshot(path=str(self.output / 'workspace-dark.png'))
        self.page.set_viewport_size({'width': 1024, 'height': 768})
        self.page.emulate_media(reduced_motion='reduce')
        self.page.keyboard.press('Control+k')
        expect(self.page.locator('#quick-results button').first).to_be_visible()
        self.assertEqual(self.page.locator('#quick-popover').evaluate('e => getComputedStyle(e).transitionDuration'), '0s')
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), 1024)
        self.page.screenshot(path=str(self.output / 'workspace-narrow.png'))
