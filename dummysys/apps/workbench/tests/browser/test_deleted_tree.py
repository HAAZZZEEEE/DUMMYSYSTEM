"""统一已删除栏跨项目聚集，保持P/T/R层次和来源标识。"""
import json
from browser_fixture import A, B, BrowserCase, expect


class DeletedTreeTests(BrowserCase):
    def task(self, project, number, deleted=False, deleted_run=False):
        name = f'[task {number}][20261009]层次任务{number}'
        docs = self.docs[project] / name
        docs.mkdir()
        (docs / 'README.md').write_text(f'---\ntitle: 层次任务{number}\ntask_id: task-{number}\nstatus: completed\n'
            + ('deleted_at: 2026-10-09\n' if deleted else '') + '---\n', encoding='utf-8')
        run = self.ws / f"runtime/project_src/项目 {'A' if project == A else 'B'}" / name / 'runs/[20261009-090000]层次运行'
        run.mkdir(parents=True)
        (run / 'run.json').write_text(json.dumps({'run_id': f'run-{number}', 'title': f'层次运行{number}', 'status': 'completed'}), encoding='utf-8')
        if deleted_run:
            (run / 'run-management.json').write_text(json.dumps({'run_id': f'run-{number}', 'deleted_at': '2026-10-09'}), encoding='utf-8')

    def test_global_footer_hierarchy_and_source_projects(self):
        self.task(A, 1, deleted=True)
        self.task(A, 2, deleted_run=True)
        self.task(B, 3)
        readme = self.docs[B] / 'README.md'
        readme.write_text(readme.read_text(encoding='utf-8').replace('status: "active"', 'status: "active"\ndeleted_at: 2026-10-09'), encoding='utf-8')
        self.page.reload()
        trash = self.page.get_by_test_id('deleted-items')
        expect(trash.locator(':scope > summary')).to_have_text('已删除（3）')
        self.assertTrue(trash.evaluate('el => el === el.parentElement.lastElementChild'))
        trash.locator(':scope > summary').click()
        groups = trash.get_by_test_id('deleted-project-group')
        expect(groups).to_have_count(2)
        a = groups.filter(has_text='来源项目：项目 A')
        a.locator(':scope > summary').click(position={'x': 8, 'y': 10})
        expect(a.get_by_test_id('deleted-task-group')).to_have_count(2)
        task = a.get_by_test_id('deleted-task-group').filter(has_text='层次任务2')
        task.locator(':scope > summary').click(position={'x': 8, 'y': 10})
        expect(task.get_by_test_id('deleted-run-node')).to_contain_text('层次运行2（已删除）')
        expect(task.get_by_test_id('trash-restore-run')).to_be_enabled()
        b = groups.filter(has_text='来源项目：项目 B')
        b.locator(':scope > summary').click(position={'x': 8, 'y': 10})
        expect(b).to_contain_text('项目已删除')
        expect(b.get_by_test_id('deleted-task-group')).to_have_count(1)
        expect(self.page.get_by_test_id('deleted-tasks')).to_have_count(0)
        expect(self.page.get_by_test_id('deleted-runs')).to_have_count(0)

    def test_empty_footer_and_refresh_detect_external_changes(self):
        expect(self.page.get_by_test_id('deleted-items').locator(':scope > summary')).to_have_text('已删除（0）')
        self.task(A, 1, deleted=True)
        self.page.get_by_test_id('refresh-projects').click()
        expect(self.page.get_by_test_id('deleted-items').locator(':scope > summary')).to_have_text('已删除（1）')
