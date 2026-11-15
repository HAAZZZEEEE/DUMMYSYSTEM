"""预览开关的真实浏览器交互与保存失败回退。"""
from browser_fixture import A, SAME, BrowserCase, expect


class PreviewToggleTests(BrowserCase):
    def test_narrow_preview_returns_to_file_navigation(self):
        self.project()
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.row(SAME).click()
        expect(self.page.get_by_test_id('preview-pane')).to_have_attribute('data-state', 'ready')
        expect(self.page.get_by_test_id('preview-pane')).to_be_visible()
        expect(self.page.locator('#file-navigation')).to_be_hidden()
        self.page.locator('#btn-files-toggle').click()
        expect(self.page.locator('#file-navigation')).to_be_visible()
        expect(self.row(SAME)).to_have_attribute('aria-current', 'true')
        self.page.locator('#btn-show-projects').click()
        expect(self.page.get_by_test_id('project-link').first).to_be_visible()
        self.page.locator('#btn-show-browser').click()
        expect(self.row(SAME)).to_be_visible()

    def test_visibility_persists_and_restores_content_width(self):
        (self.ws / 'dmy_vault' / '项目 A' / '预览.md').write_text('# 预览内容', encoding='utf-8')
        self.project()
        self.row('预览.md').click()
        pane = self.page.get_by_test_id('preview-pane')
        toggle = self.page.get_by_test_id('preview-toggle')
        handle = self.page.get_by_test_id('preview-resizer')
        expect(pane).to_have_attribute('data-state', 'ready')
        handle.focus()
        self.page.keyboard.press('ArrowRight')
        expect(handle).to_have_attribute('aria-busy', 'false')
        width = pane.evaluate('el => Math.round(el.getBoundingClientRect().width)')
        toggle.focus()
        self.page.keyboard.press('Space')
        expect(toggle).to_have_attribute('aria-busy', 'false')
        expect(toggle).to_have_attribute('aria-pressed', 'false')
        expect(pane).to_be_hidden()
        expect(handle).to_be_hidden()
        self.assertEqual(self.application.load_preferences()['preview_visible'], False)
        self.assertEqual(self.page.locator('.split-list').evaluate('el => Math.round(el.getBoundingClientRect().width)'),
                         self.page.locator('#main-split').evaluate('el => Math.round(el.getBoundingClientRect().width)'))
        toggle.click()
        expect(toggle).to_have_attribute('aria-busy', 'false')
        expect(pane.locator('h1')).to_have_text('预览内容')
        self.assertEqual(pane.evaluate('el => Math.round(el.getBoundingClientRect().width)'), width)
        toggle.click()
        expect(toggle).to_have_attribute('aria-busy', 'false')
        self.page.reload()
        self.ready()
        expect(toggle).to_have_attribute('aria-pressed', 'false')
        expect(pane).to_be_hidden()
        self.page.locator('#btn-focus').click()
        self.page.locator('#btn-focus').click()
        expect(pane).to_be_hidden()
        toggle.click()
        expect(pane).to_be_visible()

    def test_save_failure_restores_saved_visibility(self):
        self.project()
        self.page.route('**/api/v1/preferences', lambda route: route.fulfill(
            status=500, content_type='application/json',
            body='{"error":{"code":"TEST_FAILURE","message":"保存失败"}}')
            if route.request.method == 'PATCH' else route.continue_())
        toggle = self.page.get_by_test_id('preview-toggle')
        toggle.click()
        expect(toggle).to_have_attribute('aria-busy', 'false')
        expect(toggle).to_have_attribute('aria-pressed', 'true')
        expect(self.page.get_by_test_id('preview-pane')).to_be_visible()
        expect(self.page.get_by_text('预览开关未保存', exact=False)).to_be_visible()
