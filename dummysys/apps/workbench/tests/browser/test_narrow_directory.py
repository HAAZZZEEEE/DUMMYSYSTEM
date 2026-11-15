"""真实分隔条缩窄文件列表时，表头和文件名称必须保留可用空间。"""
from browser_fixture import A, BrowserCase, expect


class NarrowDirectoryTests(BrowserCase):
    def test_column_choices_and_order_survive_reload(self):
        folder = self.docs[A] / '统计示例'
        (folder / '子目录').mkdir(parents=True)
        (folder / '外层.txt').write_text('x', encoding='utf-8')
        (folder / '子目录' / '内层.txt').write_text('x', encoding='utf-8')
        (self.docs[A] / '预览.md').write_bytes(b'# Preview\n')
        self.project()
        headers = self.page.locator('.entries thead [data-column]')
        expect(headers).to_have_text(['名称'])
        self.assertFalse(any(call.get('include_file_counts') for call in self.list_calls))
        self.row('预览.md').click()
        expect(self.page.locator('#preview-title')).to_have_text('预览.md')

        trigger = self.page.get_by_test_id('directory-columns-toggle')
        panel = self.page.get_by_role('dialog', name='列设置')
        trigger.press('Enter')
        expect(panel).to_be_visible()
        expect(panel.get_by_role('checkbox', name='名称', exact=True)).to_be_disabled()
        panel.get_by_role('checkbox', name='大小', exact=True).check()
        expect(headers).to_have_text(['名称', '大小'])
        panel.get_by_role('checkbox', name='文件数', exact=True).check()
        expect(self.row('统计示例').locator('[data-column="file_count"]')).to_have_text('1')
        expect(self.row('预览.md').locator('[data-column="size"]')).to_have_text('10 B')
        expect(self.page.locator('#preview-title')).to_have_text('预览.md')

        panel.get_by_role('button', name='文件数上移').press('Enter')
        expect(headers).to_have_text(['名称', '文件数', '大小'])
        self.page.keyboard.press('Escape')
        expect(panel).to_be_hidden()
        expect(trigger).to_be_focused()
        self.page.reload()
        self.ready()
        expect(headers).to_have_text(['名称', '文件数', '大小'])
        trigger.click()
        panel.get_by_role('button', name='恢复默认').click()
        expect(headers).to_have_text(['名称'])
        self.assertEqual(self.application.load_preferences()['directory_columns'], [])

    def test_filename_filter_sits_right_of_directory_controls(self):
        self.project()
        filter_field = self.page.get_by_test_id('directory-filter')
        sort = self.page.get_by_label('目录排序', exact=True)
        filter_box, sort_box = filter_field.bounding_box(), sort.bounding_box()
        self.assertGreater(filter_box['x'], sort_box['x'] + sort_box['width'])
        self.assertAlmostEqual(filter_box['y'] + filter_box['height'] / 2,
                               sort_box['y'] + sort_box['height'] / 2, delta=2)
        self.assertGreaterEqual(filter_field.evaluate(
            'el => parseFloat(getComputedStyle(el).borderTopLeftRadius)'), filter_box['height'] / 2)
        self.page.keyboard.press('/')
        expect(filter_field).to_be_focused()
        filter_field.fill('筛选-甲')
        expect(self.page.get_by_test_id('directory-entry')).to_have_count(1)

    def test_record_labels_preserve_raw_targets_and_invalid_names(self):
        name = '[task 12][20261028]核对中文长路径与项目浏览器显示的一致性'
        invalid = '[task 13][20260230]原样显示的目录'
        run_name = '[20261028-234505]复查中文目录'
        (self.docs[A] / name / 'runs' / run_name).mkdir(parents=True)
        (self.docs[A] / invalid).mkdir()
        self.project()
        task = self.row(name)
        expect(task.locator('.entry-record-meta')).to_have_text('任务 #12 · 2026-10-28')
        expect(task.locator('.name-text')).to_have_attribute('title', name)
        expect(self.row(invalid).locator('.name-text')).to_have_text(invalid)
        self.enter(name)
        self.enter(name + '/runs')
        expect(self.row(name + '/runs/' + run_name).locator('.entry-record-meta')).to_have_text('2026-10-28 · 23:45')
        self.enter(name + '/runs/' + run_name)

    def test_narrow_list_keeps_header_text_inside_its_column(self):
        self.project()
        handle = self.page.get_by_test_id("preview-resizer")
        handle.focus()
        for _ in range(28):
            self.page.keyboard.press("ArrowRight")
        bounds = self.page.locator(".entries thead th").evaluate_all("""cells => cells.filter(e => e.textContent.trim()).map(e => {
            const rect = e.getBoundingClientRect();
            const range = document.createRange(); range.selectNodeContents(e);
            const text = range.getBoundingClientRect();
            return {label:e.textContent,width:rect.width,textRight:text.right,right:rect.right};
        })""")
        self.page.screenshot(path=str(self.output / "narrow-directory.png"))
        print(bounds)
        for cell in bounds:
            self.assertLessEqual(cell["textRight"], cell["right"], cell["label"] + "越过自身列边界")
        self.assertGreaterEqual(bounds[0]["width"], 140, "名称列被固定宽度辅助列挤空")

    def test_horizontal_scroll_reaches_actions_and_wide_layout_stays_readable(self):
        self.application.save_preferences({'directory_columns': ['type', 'modified', 'size', 'file_count']})
        self.page.reload()
        self.project()
        initial = self.page.locator(".entries th").first.bounding_box()["width"]
        self.assertGreaterEqual(initial, 140)
        handle = self.page.get_by_test_id("preview-resizer")
        handle.focus()
        for _ in range(28):
            self.page.keyboard.press("ArrowRight")
        directory = self.page.get_by_test_id("directory-view")
        trigger = self.page.get_by_test_id('directory-columns-toggle')
        trigger.click()
        expect(self.page.get_by_role('dialog', name='列设置')).to_be_visible()
        self.page.keyboard.press('Escape')
        scroll = directory.evaluate("e => ({client:e.clientWidth, full:e.scrollWidth})")
        self.assertGreater(scroll["full"], scroll["client"])
        directory.evaluate("e => e.scrollLeft = e.scrollWidth")
        action = self.page.locator(".entries tbody tr").first.locator("td").last
        self.assertLessEqual(action.bounding_box()["x"] + action.bounding_box()["width"], directory.bounding_box()["x"] + directory.bounding_box()["width"], "横向滚动后操作列仍无法完整访问")
        handle.dblclick()
        self.assertGreaterEqual(self.page.locator(".entries th").first.bounding_box()["width"], 140)
        self.assertEqual(self.page_errors, [])
