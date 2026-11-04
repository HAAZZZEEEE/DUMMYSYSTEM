"""大型项目默认五项、展开入口、排序和当前任务可见性。"""
from browser_fixture import A, B, BrowserCase, expect


class TaskLimitTests(BrowserCase):
    def prepare(self, count=8, archived=False):
        self.names = [f'[task {n}][20261021]任务{n:02d}' for n in range(1, count + 1)]
        for project, label in ((A, 'A'), (B, 'B')):
            for name in self.names:
                for base in (self.docs[project], self.ws / f'runtime/project_src/项目 {label}'):
                    (base / name / '子目录').mkdir(parents=True)
                (self.docs[project] / name / 'README.md').write_text(
                    f'---\ntitle: {name.split("]")[-1]}\n---\n', encoding='utf-8')
        if archived:
            path = self.docs[A] / 'archive/[task 99][20261020]历史任务'
            path.mkdir(parents=True)
        self.project()
        self.list = self.page.locator('#visible-task-list')
        self.toggle = self.page.get_by_test_id('task-list-toggle')
        expect(self.list.get_by_test_id('task-node')).to_have_count(min(count, 5))

    def test_default_five_expand_collapse_keyboard_and_geometry(self):
        self.prepare()
        original = self.page.url
        expect(self.toggle).to_have_text('展开其余 3 个任务')
        expect(self.toggle).to_have_attribute('aria-expanded', 'false')
        bounds = self.list.bounding_box()
        button = self.toggle.bounding_box()
        self.assertGreaterEqual(button['y'], bounds['y'] + bounds['height'])
        self.assertLessEqual(button['x'] + button['width'], self.page.locator('#sidebar').bounding_box()['width'])
        expect(self.toggle.locator('svg.type-icon-chevronsDown')).to_be_visible()
        self.page.screenshot(path=str(self.output / 'five-tasks-collapsed.png'))
        self.toggle.focus()
        self.page.keyboard.press('Enter')
        expect(self.list.get_by_test_id('task-node')).to_have_count(8)
        expect(self.toggle).to_have_attribute('aria-expanded', 'true')
        expect(self.toggle).to_be_focused()
        self.page.keyboard.press('Space')
        expect(self.list.get_by_test_id('task-node')).to_have_count(5)
        expect(self.toggle).to_be_focused()
        self.assertEqual(self.page.url, original)

    def test_five_or_fewer_have_no_expand_control(self):
        self.prepare(count=5)
        expect(self.toggle).to_have_count(0)
        self.list.get_by_test_id('task-node').first.click()
        self.ready(self.names[0])
        expect(self.list.get_by_test_id('task-node')).to_have_count(5)

    def test_project_isolation_refresh_and_cards(self):
        self.prepare()
        self.toggle.click()
        self.page.locator('#btn-settings').click()
        self.page.get_by_test_id('task-view-select').select_option('cards')
        self.page.locator('#settings-close').click()
        expect(self.list.locator('.tv-card')).to_have_count(8)
        self.toggle.click()
        expect(self.list.locator('.tv-card')).to_have_count(5)
        self.toggle.click()
        self.page.locator('#btn-project-refresh').click()
        self.ready()
        expect(self.list.get_by_test_id('task-node')).to_have_count(8)
        self.project(B)
        expect(self.list.get_by_test_id('task-node')).to_have_count(5)
        self.project(A)
        expect(self.list.get_by_test_id('task-node')).to_have_count(8)
        self.page.reload()
        self.ready()
        expect(self.list.locator('.tv-card')).to_have_count(5)
        self.page.screenshot(path=str(self.output / 'five-tasks-cards.png'))

    def test_sort_before_limit_and_reveal_selected_task(self):
        self.prepare()
        self.page.get_by_test_id('nav-sort').select_option('name_desc')
        expect(self.list.locator('.tv-task-head > .tv-label')).to_have_text(
            ['任务08', '任务07', '任务06', '任务05', '任务04'])
        self.enter(self.names[0])  # 主区目录进入当前被隐藏的任务。
        expect(self.list.get_by_test_id('task-node')).to_have_count(8)
        current = self.list.get_by_test_id('task-node').filter(has_text='任务01')
        expect(current).to_have_attribute('aria-selected', 'true')
        self.enter(self.names[0] + '/子目录')
        self.page.get_by_role('tab', name='根目录：项目资源', exact=True).click()
        self.ready(self.names[0] + '/子目录', root='resources')
        expect(current).to_have_attribute('aria-selected', 'true')
        self.toggle.click()
        expect(self.list.get_by_test_id('task-node')).to_have_count(5)
        self.ready(self.names[0] + '/子目录', root='resources')

    def test_archive_and_all_toggle_remain_available(self):
        self.prepare(archived=True)
        box = self.page.get_by_test_id('archived-tasks')
        expect(box).to_be_visible()
        expect(box.get_by_test_id('task-node')).to_be_hidden()
        box.locator('summary').click()
        expect(box.get_by_test_id('task-node')).to_be_visible()
        expect(self.list.get_by_test_id('task-node')).to_have_count(5)
        toolbar = self.page.get_by_test_id('nav-toggle-all')
        toolbar.click()  # 折叠全部内容。
        expect(toolbar).to_have_attribute('aria-label', '全部展开')
        toolbar.click()
        expect(self.list.get_by_test_id('task-node')).to_have_count(8)
        expect(box.get_by_test_id('task-node')).to_be_visible()
        toolbar.click()
        expect(self.list.get_by_test_id('task-node')).to_have_count(5)
        expect(box.get_by_test_id('task-node')).to_be_hidden()
