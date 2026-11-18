"""根分类切换保留 Task/子目录，代码位置按项目隔离。"""
import json

from browser_fixture import A, B, SPECIAL, BrowserCase, expect
from tests.helpers import write_json

TASK = '[task 1][20260921]分类切换'


class RootContextTests(BrowserCase):
    def prepare(self, archived=False):
        self.resources = self.ws / 'runtime/project_src/项目 A'
        self.doc_task = ('archive/' if archived else '') + TASK
        for base, relative in ((self.docs[A], self.doc_task), (self.resources, TASK)):
            (base / relative / SPECIAL).mkdir(parents=True)
            (base / relative / SPECIAL / '当前位置.txt').write_text(relative, encoding='utf-8')
        (self.docs[A] / self.doc_task / 'README.md').write_text('---\ntitle: 分类切换\nstatus: active\n---\n', encoding='utf-8')
        repo = self.ws.parent / 'repo'
        (repo / 'src').mkdir(parents=True)
        write_json(self.ws / 'runtime/state/workspace/repositories.json', {'checkouts': {'demo': {'path': str(repo)}}})
        for name in ('项目 A', '项目 B'):
            path = self.ws / 'runtime/project_src' / name / 'project.json'
            binding = json.loads(path.read_text(encoding='utf-8'))
            binding['repositories'] = [{'repo_id': 'demo', 'paths': ['.']}]
            write_json(path, binding)
        self.page.locator('#btn-project-refresh').click()
        expect(self.target_locator('project-link', root='')).to_be_visible()
        self.project()
        expect(self.page.get_by_test_id('task-node')).to_have_count(1)

    def switch(self, root, relative='', project=A):
        if root.startswith('repo:'):
            self.page.get_by_role('tab', name='代码仓库', exact=True).click()
            self.page.get_by_role('menuitemradio', name='代码 demo', exact=True).click()
        else:
            self.page.get_by_role('tab', name={'docs': '根目录：文档', 'resources': '根目录：项目资源'}[root], exact=True).click()
        self.ready(relative, project, root)
        expect(self.page.locator(f'[data-testid="project-link"][data-id="{project}"]')).to_have_attribute('aria-current', 'true')
        if project == A and relative.startswith(TASK) and not self.doc_task.startswith('archive/'):
            expect(self.page.get_by_test_id('task-node')).to_have_attribute('aria-selected', 'true')

    def test_task_and_child_round_trip_history_and_reload(self):
        self.prepare()
        self.page.get_by_test_id('task-node').click()
        self.ready(TASK)
        self.switch('resources', TASK)
        self.switch('docs', TASK)
        self.enter(TASK + '/' + SPECIAL)
        self.switch('resources', TASK + '/' + SPECIAL)
        self.page.go_back()
        self.ready(TASK + '/' + SPECIAL)
        self.page.go_forward()
        self.ready(TASK + '/' + SPECIAL, root='resources')
        self.page.reload()
        self.ready(TASK + '/' + SPECIAL, root='resources')
        self.switch('docs', TASK + '/' + SPECIAL)
        self.page.screenshot(path=str(self.output / 'task-child-preserved.png'))

    def test_code_remembers_location_and_returns_to_task(self):
        self.prepare()
        self.enter(TASK)
        self.enter(TASK + '/' + SPECIAL)
        self.switch('repo:demo')
        expect(self.page.get_by_test_id('task-node')).to_have_attribute('aria-selected', 'true')
        self.target_locator('directory-entry', 'src', root='repo:demo').click()
        self.ready('src', root='repo:demo')
        self.switch('resources', TASK + '/' + SPECIAL)
        self.switch('repo:demo', 'src')
        self.switch('docs', TASK + '/' + SPECIAL)
        self.project(B)
        self.switch('repo:demo', project=B)
        self.switch('docs', project=B)
        self.project(A, relative=TASK + '/' + SPECIAL)
        self.switch('repo:demo', 'src')
        self.switch('docs', TASK + '/' + SPECIAL)  # 从首页返回内容，恢复本项目上次位置。

    def test_archived_task_uses_paired_prefix(self):
        self.prepare(archived=True)
        self.enter('archive')
        self.enter(self.doc_task)
        self.enter(self.doc_task + '/' + SPECIAL)
        self.page.locator('#btn-refresh').click()
        self.ready(self.doc_task + '/' + SPECIAL)
        self.switch('resources', TASK + '/' + SPECIAL)
        self.switch('docs', self.doc_task + '/' + SPECIAL)

    def test_run_resources_switch_to_archived_task_docs(self):
        self.prepare(archived=True)
        run = TASK + '/runs/[20261118-090000]浏览验证'
        evidence = run + '/evidence'
        (self.resources / evidence).mkdir(parents=True)
        self.enter('archive')
        self.enter(self.doc_task)
        self.switch('resources', TASK)
        for relative in (TASK + '/runs', run, evidence):
            self.target_locator('directory-entry', relative, root='resources').click()
            self.ready(relative, root='resources')
        self.page.get_by_role('tab', name='根目录：文档', exact=True).click()
        expect(self.page.get_by_test_id('directory-view')).to_have_attribute('aria-busy', 'false')
        expect(self.page.locator('#error-view')).to_be_hidden(timeout=1500)
        self.ready(self.doc_task)
        expect(self.target_locator('directory-entry', self.doc_task + '/README.md')).to_be_visible()
        self.page.go_back()
        self.ready(evidence, root='resources')
        self.page.go_forward()
        self.ready(self.doc_task)

    def test_missing_counterpart_keeps_target_and_can_return(self):
        self.prepare()
        missing = TASK + '/仅文档'
        (self.docs[A] / missing).mkdir()
        self.enter(TASK)
        self.enter(missing)
        self.page.get_by_role('tab', name='根目录：项目资源', exact=True).click()
        expect(self.page.locator('#error-view')).to_be_visible()
        self.assertIn('root_id=resources', self.page.url)
        self.page.wait_for_function('value => new URL(location.href).searchParams.get("relative_path") === value', arg=missing)
        expect(self.page.locator('#project-title')).to_have_text('项目 A')
        self.switch('docs', missing)

    def test_late_list_does_not_replace_new_project(self):
        self.prepare()
        self.enter(TASK)
        self.delay('list', project=A, relative=TASK)
        self.page.get_by_role('tab', name='根目录：项目资源', exact=True).click()
        self.delay_ready()
        self.project(B)
        self.release()
        self.ready(project=B)
        expect(self.page.locator('#project-title')).to_have_text('项目 B')
