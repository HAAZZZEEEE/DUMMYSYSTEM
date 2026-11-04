"""归档任务独立分组、默认折叠和展开后的真实导航行为。"""
import json

from browser_fixture import A, B, BrowserCase, expect


class ArchivedTasksTests(BrowserCase):
    def test_task_actions_follow_archive_and_deletion_flags(self):
        self._tasks()
        ordinary = self.page.get_by_test_id('task-node').filter(has_text='普通任务')
        ordinary.get_by_test_id('target-menu').click()
        expect(self.page.get_by_test_id('archive-task')).to_be_visible()
        expect(self.page.get_by_test_id('unarchive-task')).to_have_count(0)
        expect(self.page.get_by_test_id('undelete-task')).to_have_count(0)
        self.page.keyboard.press('Escape')
        box = self.page.get_by_test_id('archived-tasks')
        box.locator('summary').click()
        box.get_by_test_id('task-node').get_by_test_id('target-menu').click()
        expect(self.page.get_by_test_id('unarchive-task')).to_be_visible()
        expect(self.page.get_by_test_id('archive-task')).to_have_count(0)
        expect(self.page.get_by_test_id('move-task')).to_have_count(0)

    def _tasks(self):
        for project in (A, B):
            for archived, title in ((False, "普通任务"), (True, "历史任务")):
                name = f"[task {2 if archived else 1}][20261009]{title}"
                path = ("archive/" if archived else "") + name
                docs = self.docs[project] / path
                docs.mkdir(parents=True)
                (docs / "README.md").write_text(f"---\ntitle: {title}\n---\n", encoding="utf-8")
                run = self.ws / f"runtime/project_src/项目 {'A' if project == A else 'B'}" / name / "runs/[20261009-090000]验证"
                run.mkdir(parents=True)
                (run / "run.json").write_text(json.dumps({"run_id": project + title, "title": "验证", "status": "running"}), encoding="utf-8")
        self.project()

    def test_group_default_collapsed_and_survives_style_and_task_toggle(self):
        self._tasks()
        box = self.page.get_by_test_id("archived-tasks")
        archived = box.get_by_test_id("task-node")
        expect(box.locator("summary")).to_have_text("归档任务（1）")
        expect(archived).to_be_hidden()
        expect(self.page.get_by_test_id("task-node").filter(has_text="普通任务")).to_be_visible()
        box.locator("summary").click()
        expect(archived).to_be_visible()
        archived.locator(".tv-toggle").click()
        expect(box).to_have_attribute("open", "")
        expect(archived).to_have_attribute("aria-expanded", "false")
        self.page.locator("#btn-settings").click()
        self.page.get_by_test_id("task-view-select").select_option("cards")
        self.page.locator("#settings-close").click()
        expect(archived).to_be_visible()
        archived.locator(".tv-toggle").click()
        expect(box.get_by_test_id("run-node")).to_be_visible()
        archived.locator(".tv-label").click()
        self.ready("archive/[task 2][20261009]历史任务")

    def test_keyboard_toolbar_and_project_defaults(self):
        self._tasks()
        box = self.page.get_by_test_id("archived-tasks")
        summary = box.locator("summary")
        summary.focus()
        summary.press("Space")
        expect(box.get_by_test_id("task-node")).to_be_visible()
        self.page.get_by_test_id("nav-toggle-all").click()
        expect(box.get_by_test_id("task-node")).to_be_hidden()
        self.page.get_by_test_id("nav-toggle-all").click()
        expect(box.get_by_test_id("run-node")).to_be_visible()
        self.project(B)
        expect(box.get_by_test_id("task-node")).to_be_hidden()
        self.project(A)
        expect(box.get_by_test_id("task-node")).to_be_visible()
