"""同层级排序、时间顺序、分页请求及持久化。"""
from browser_fixture import A, BrowserCase, expect


class NavSortTests(BrowserCase):
    def tasks(self):
        for number, title, date in ((1, 'Zulu', '20260901'), (2, 'Alpha', '20261001'), (3, 'Beta', '20260915')):
            name = f'[task {number}][{date}]{title}'
            docs = self.docs[A] / name
            docs.mkdir()
            (docs / 'README.md').write_text(f'---\ntitle: {title}\nstatus: active\n---\n', encoding='utf-8')
        self.project()

    def titles(self):
        return self.page.get_by_test_id('task-node').locator('.tv-label').all_text_contents()

    def test_task_sort_modes_and_reload_preserve_selection(self):
        self.tasks()
        expect(self.page.get_by_test_id('task-node')).to_have_count(3)
        sort = self.page.get_by_test_id('nav-sort')
        self.assertEqual(self.titles(), ['Zulu', 'Beta', 'Alpha'])
        for mode, titles in [('name', ['Alpha', 'Beta', 'Zulu']), ('name_desc', ['Zulu', 'Beta', 'Alpha']),
                             ('newest', ['Alpha', 'Beta', 'Zulu']), ('oldest', ['Zulu', 'Beta', 'Alpha'])]:
            with self.page.expect_response(lambda r: r.url.endswith('/api/v1/preferences') and r.request.method == 'PATCH'):
                sort.select_option(mode)
            expect(self.page.get_by_test_id('task-node').locator('.tv-label')).to_have_text(titles)
        self.page.reload()
        self.ready()
        expect(sort).to_have_value('oldest')
        expect(self.page.get_by_test_id('task-node').locator('.tv-label')).to_have_text(['Zulu', 'Beta', 'Alpha'])

    def test_project_name_order_and_path_request_sort(self):
        self.project()
        with self.page.expect_response(lambda r: r.url.endswith('/api/v1/preferences') and r.request.method == 'PATCH'):
            self.page.get_by_test_id('nav-sort').select_option('name_desc')
        expect(self.page.get_by_test_id('project-link')).to_have_text(['项目 B', '项目 A'])
        self.page.wait_for_function("Array.from(document.querySelectorAll('[data-testid=tree-node]')).some(el => el.getAttribute('aria-busy') === 'false')")
        self.assertTrue(any(call.get('sort') == 'name_desc' for call in self.list_calls), '树分页请求必须携带排序参数')

    def test_same_day_tasks_use_number_for_time_sort(self):
        for number, title, date in ((2, 'Alpha', '20261001'), (10, 'Zulu', '20261001'),
                                    (11, 'Beta', '20260930')):
            docs = self.docs[A] / f'[task {number}][{date}]{title}'
            docs.mkdir()
            (docs / 'README.md').write_text(f'---\ntitle: {title}\nstatus: active\n---\n', encoding='utf-8')
        self.project()
        sort = self.page.get_by_test_id('nav-sort')
        for mode, numbers in [('newest', ['#10', '#2', '#11']),
                              ('oldest', ['#11', '#2', '#10']),
                              ('name', ['#2', '#11', '#10'])]:
            sort.select_option(mode)
            expect(self.page.get_by_test_id('task-number')).to_have_text(numbers)
