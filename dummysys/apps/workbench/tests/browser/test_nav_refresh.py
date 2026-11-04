"""外部新增 Task/Run 刷新，以及已选中任务的标题折叠。"""
from browser_fixture import A, B, BrowserCase, expect
from tests.helpers import write_json

TASK = '[task 1][20261021]已有任务'
NEW_TASK = '[task 2][20261021]新增任务'
RUN = '[20261021-120000]新增运行'


class NavRefreshTests(BrowserCase):
    def prepare(self):
        self.resources = self.ws / 'runtime/project_src/项目 A'
        for base in (self.docs[A], self.resources):
            (base / TASK / '子目录').mkdir(parents=True)
        self.project()
        expect(self.page.get_by_test_id('task-node')).to_have_count(1)
        expect(self.page.get_by_test_id('nav-task-summary')).to_have_text('1 任务 · 0 运行')

    def check_refresh(self, button):
        self.prepare()
        self.enter(TASK)
        for base in (self.docs[A], self.resources):
            (base / NEW_TASK).mkdir()
        write_json(self.resources / TASK / 'runs' / RUN / 'run.json', {
            'schema_version': 1, 'run_id': 'new-run', 'title': '新增运行', 'status': 'running',
        })
        self.page.locator(button).click()
        self.ready(TASK)
        expect(self.page.get_by_test_id('task-node')).to_have_count(2)
        expect(self.page.get_by_test_id('task-number')).to_have_text(['#1', '#2'])
        expect(self.page.get_by_test_id('nav-task-summary')).to_have_text('2 任务 · 1 运行')
        expect(self.page.get_by_test_id('run-node').filter(has_text='新增运行')).to_be_visible()
        # 已识别的 Task 不得同时出现在「其他路径」里。
        expect(self.node(NEW_TASK)).to_have_count(0)
        expect(self.page.get_by_test_id('task-node').filter(has_text='已有任务')).to_have_attribute('aria-selected', 'true')

    def test_sidebar_refresh_reloads_tasks_and_runs(self):
        self.check_refresh('#btn-project-refresh')

    def test_directory_refresh_reloads_tasks_and_runs(self):
        self.check_refresh('#btn-refresh')

    def test_selected_task_title_toggles_from_child_and_resources(self):
        self.prepare()
        self.enter(TASK)
        self.enter(TASK + '/子目录')
        head = self.page.get_by_test_id('task-node')
        expect(head).to_have_attribute('aria-selected', 'true')
        expect(head).to_have_attribute('aria-expanded', 'true')
        head.click()
        expect(head).to_have_attribute('aria-expanded', 'false')
        self.ready(TASK + '/子目录')
        head.click()
        expect(head).to_have_attribute('aria-expanded', 'true')
        self.page.get_by_role('tab', name='根目录：项目资源', exact=True).click()
        self.ready(TASK + '/子目录', root='resources')
        head.click()
        expect(head).to_have_attribute('aria-expanded', 'false')
        self.ready(TASK + '/子目录', root='resources')
        head.focus()
        self.page.keyboard.press('Enter')
        expect(head).to_have_attribute('aria-expanded', 'true')
        self.ready(TASK + '/子目录', root='resources')

    def test_selected_task_title_toggles_from_run_in_cards_view(self):
        self.prepare()
        write_json(self.resources / TASK / 'runs' / RUN / 'run.json', {
            'schema_version': 1, 'run_id': 'new-run', 'title': '新增运行', 'status': 'running',
        })
        self.page.locator('#btn-project-refresh').click()
        run = self.page.get_by_test_id('run-node')
        expect(run).to_be_visible()
        self.page.locator('#btn-settings').click()
        self.page.get_by_test_id('task-view-select').select_option('cards')
        self.page.locator('#settings-close').click()
        run.click()
        relative = TASK + '/runs/' + RUN
        self.ready(relative, root='resources')
        head = self.page.get_by_test_id('task-node')
        expect(head).to_have_attribute('aria-selected', 'true')
        head.click()
        expect(head).to_have_attribute('aria-expanded', 'false')
        self.ready(relative, root='resources')

    def test_late_refresh_nav_does_not_replace_new_project(self):
        self.prepare()
        self.delay('nav')
        self.page.locator('#btn-project-refresh').click()
        self.delay_ready()
        self.project(B)
        self.release()
        self.ready(project=B)
        expect(self.page.get_by_test_id('task-node')).to_have_count(0)
        expect(self.page.get_by_test_id('nav-task-summary')).to_have_text('0 任务 · 0 运行')
