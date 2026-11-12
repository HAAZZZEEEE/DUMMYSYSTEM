"""搜索输入、过滤与异步偏好保存的交互回归。"""
from browser_fixture import A, B, BrowserCase, expect


class SearchInteractionTests(BrowserCase):
    def test_file_result_opens_parent_and_previews_text(self):
        (self.docs[A] / '项目报告.md').write_text('# 文件搜索预览', encoding='utf-8')
        self.project()
        self.page.locator('#global-search').fill('项目报告')
        result = self.page.locator('#search-results button').filter(has_text='项目报告.md')
        expect(result).to_be_visible()
        result.click()
        self.ready()
        expect(self.page.locator('#preview-body')).to_contain_text('文件搜索预览')

    def test_quick_jump_keeps_sidebar_and_resets_query(self):
        self.project()
        self.page.keyboard.press('ControlOrMeta+k')
        self.page.locator('#project-search').fill('项目 B')
        expect(self.page.get_by_test_id('project-link')).to_have_count(2)
        self.page.locator('#project-search').press('Enter')
        self.ready(project=B)
        expect(self.page.locator('#project-search')).to_have_value('')
        expect(self.page.locator('#project-search')).not_to_have_attribute('aria-activedescendant', 'quick-option-0')

    def test_search_type_filter_and_preferences_do_not_replace_results(self):
        (self.docs[A] / '项目报告.md').write_text('# 报告', encoding='utf-8')
        self.delay('preferences')
        self.project()
        self.delay_ready()
        self.page.locator('#global-search').fill('项目')
        expect(self.page.locator('#search-results')).to_contain_text('项目报告.md')
        with self.page.expect_response(lambda r: '/api/v1/search?' in r.url and 'types=file' in r.url) as response:
            self.page.locator('#search-filters [data-type="file"]').click()
        self.assertEqual(response.value.status, 200)
        expect(self.page.locator('#search-results')).to_contain_text('项目报告.md')
        self.release()
        expect(self.page.locator('#search-results')).to_contain_text('项目报告.md')
        self.page.keyboard.press('Escape')
        expect(self.page.locator('#global-search')).to_have_attribute('aria-expanded', 'false')
