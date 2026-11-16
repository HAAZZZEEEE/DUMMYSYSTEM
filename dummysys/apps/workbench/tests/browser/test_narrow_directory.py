"""真实分隔条缩窄文件列表时，表头和文件名称必须保留可用空间。"""
from browser_fixture import A, MANY, BrowserCase, expect


class NarrowDirectoryTests(BrowserCase):
    def test_directory_sort_applies_before_paging(self):
        (self.docs[A] / MANY / '终点大文件.txt').write_bytes(b'x' * 200)
        self.application.save_preferences({'directory_columns': ['size']})
        self.page.reload()
        self.project()
        self.enter(MANY)
        self.page.get_by_test_id('directory-columns-toggle').click()
        sort = self.page.get_by_label('目录排序', exact=True)
        header = self.page.locator('th[data-column="size"]')
        rows = self.page.get_by_test_id('directory-entry')
        sort.select_option('name_desc')
        expect(rows.first).to_contain_text('终点大文件.txt')
        sort.select_option('size')
        expect(header).to_have_attribute('aria-sort', 'ascending')
        expect(rows.first).to_contain_text('000')
        sort.select_option('size_desc')
        expect(header).to_have_attribute('aria-sort', 'descending')
        expect(rows.first).to_contain_text('终点大文件.txt')
        expect(rows).to_have_count(200)

    def test_hidden_columns_keep_their_position_when_shown(self):
        self.project()
        trigger = self.page.get_by_test_id('directory-columns-toggle')
        panel = self.page.get_by_role('dialog', name='目录设置')
        headings = self.page.locator('.entries thead [data-column]')
        choices = panel.locator('.directory-column-option label')
        trigger.click()
        expect(panel.get_by_role('checkbox', name='名称', exact=True)).to_be_disabled()
        panel.get_by_role('button', name='文件数上移').click()
        expect(choices).to_have_text(['名称', '类型', '修改时间', '文件数', '大小'])
        expect(headings).to_have_text(['名称'])
        self.page.reload()
        self.ready()
        trigger.click()
        expect(choices).to_have_text(['名称', '类型', '修改时间', '文件数', '大小'])
        panel.get_by_role('checkbox', name='大小', exact=True).check()
        count = panel.get_by_role('checkbox', name='文件数', exact=True)
        count.check()
        expect(headings).to_have_text(['名称', '文件数', '大小'])
        count.uncheck()
        expect(headings).to_have_text(['名称', '大小'])
        count.check()
        expect(headings).to_have_text(['名称', '文件数', '大小'])
        self.page.screenshot(path=str(self.output / 'directory-column-order.png'))

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
        panel = self.page.get_by_role('dialog', name='目录设置')
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

    def test_directory_header_combines_name_search_and_settings(self):
        self.project()
        heading = self.page.get_by_role('columnheader', name='名称', exact=True)
        filter_field = self.page.get_by_test_id('directory-filter')
        trigger = self.page.get_by_test_id('directory-columns-toggle')
        panel = self.page.get_by_role('dialog', name='目录设置', exact=True)
        kind = panel.get_by_label('筛选条目类型', exact=True)
        sort = panel.get_by_label('目录排序', exact=True)
        expect(kind).to_be_hidden()
        expect(sort).to_be_hidden()
        for width in (1440, 900, 390):
            with self.subTest(width=width):
                self.page.set_viewport_size({'width': width, 'height': 760})
                label_box, filter_box, trigger_box = [
                    locator.bounding_box() for locator in
                    (heading.locator('#directory-name-heading'), filter_field, trigger)
                ]
                self.assertGreaterEqual(filter_box['x'], label_box['x'] + label_box['width'])
                self.assertGreaterEqual(trigger_box['x'], filter_box['x'] + filter_box['width'])
                self.assertAlmostEqual(filter_box['y'] + filter_box['height'] / 2,
                                       trigger_box['y'] + trigger_box['height'] / 2, delta=2)
                self.assertAlmostEqual(label_box['y'] + label_box['height'] / 2,
                                       trigger_box['y'] + trigger_box['height'] / 2, delta=2)
                self.page.screenshot(path=self.output / f'directory-header-{width}.png', animations='disabled')

        trigger.press('Enter')
        expect(kind).to_be_focused()
        expect(sort).to_be_visible()
        kind.select_option('dir')
        expect(self.page.get_by_test_id('directory-entry')).to_have_count(2)
        expect(kind).to_be_focused()
        expect(panel).to_be_visible()
        self.page.screenshot(path=self.output / 'directory-settings-390.png', animations='disabled')
        self.page.keyboard.press('Escape')
        expect(panel).to_be_hidden()
        expect(trigger).to_be_focused()

        self.page.keyboard.press('/')
        expect(filter_field).to_be_focused()
        filter_field.fill('205')
        expect(self.page.get_by_test_id('directory-entry')).to_have_count(1)
        expect(self.page.get_by_test_id('directory-entry')).to_contain_text(MANY)
        self.page.get_by_role('button', name='清除筛选').click()
        expect(filter_field).to_have_value('')
        expect(self.page.get_by_test_id('directory-entry')).to_have_count(6)

        self.page.emulate_media(color_scheme='dark')
        expect(self.page.locator('html')).to_have_attribute('data-theme', 'dark')
        trigger.click()
        expect(panel).to_be_visible()
        self.page.screenshot(path=self.output / 'directory-settings-dark.png', animations='disabled')

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

    def test_single_line_name_reveals_full_text_on_keyboard_focus(self):
        name = '[task 12][20261028]核对中文长路径、预览区和可选列启用后的文件名称显示效果及键盘导航'
        filename = '验收报告 Workbench 浏览器目录与文件预览长名称显示及键盘操作记录.md'
        (self.docs[A] / name).mkdir()
        (self.docs[A] / filename).write_text('验收记录\n', encoding='utf-8')
        self.project()
        self.page.get_by_test_id('preview-toggle').click()
        task = self.row(name)
        file = self.row(filename)
        label = task.locator('.name-text')
        metadata = task.locator('.entry-record-meta')
        expect(label).to_have_css('font-weight', '400')
        expect(metadata).to_have_text('任务 #12 · 2026-10-28')
        self.assertGreater(metadata.bounding_box()['y'], label.bounding_box()['y'])
        self.assertAlmostEqual(metadata.bounding_box()['x'], label.bounding_box()['x'], delta=1)
        self.assertGreater(task.bounding_box()['height'], file.bounding_box()['height'])

        self.page.set_viewport_size({'width': 390, 'height': 760})
        expect(label).to_have_attribute('title', name)
        expect(task).to_have_accessible_name('目录：' + name)
        self.assertGreater(metadata.bounding_box()['y'], label.bounding_box()['y'])
        self.assertGreater(task.bounding_box()['height'], file.bounding_box()['height'])
        self.assertTrue(label.evaluate('e => e.scrollWidth > e.clientWidth'))
        expect(label).to_have_css('text-overflow', 'ellipsis')
        file_label = file.locator('.name-text')
        expect(file_label).to_have_css('white-space', 'nowrap')
        expect(file_label).to_have_attribute('title', filename)
        name_height = label.bounding_box()['height']
        task.press('ArrowDown')
        self.page.keyboard.press('ArrowUp')
        expect(task).to_be_focused()
        expect(label).to_have_css('white-space', 'normal')
        self.assertGreater(label.bounding_box()['height'], name_height)
        self.page.keyboard.press('Enter')
        self.ready(name)

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
        expect(self.page.get_by_role('dialog', name='目录设置')).to_be_visible()
        self.page.keyboard.press('Escape')
        scroll = directory.evaluate("e => ({client:e.clientWidth, full:e.scrollWidth})")
        self.assertGreater(scroll["full"], scroll["client"])
        directory.evaluate("e => e.scrollLeft = e.scrollWidth")
        action = self.page.locator(".entries tbody tr").first.locator("td").last
        self.assertLessEqual(action.bounding_box()["x"] + action.bounding_box()["width"], directory.bounding_box()["x"] + directory.bounding_box()["width"], "横向滚动后操作列仍无法完整访问")
        self.page.keyboard.press('/')
        expect(self.page.get_by_test_id('directory-filter')).to_be_focused()
        self.assertEqual(directory.evaluate('e => e.scrollLeft'), 0)
        handle.dblclick()
        self.assertGreaterEqual(self.page.locator(".entries th").first.bounding_box()["width"], 140)
        self.assertEqual(self.page_errors, [])
