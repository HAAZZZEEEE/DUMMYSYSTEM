"""导航重绘必须保留滚动位置；真实 Edge、真实 Task/目录数据。"""
import json

from browser_fixture import A, BrowserCase, expect


class NavScrollTests(BrowserCase):
    def _long_navigation(self):
        for number in range(35):
            name = f"[task {number + 1}][20261009]任务 {number:02d}"
            docs = self.docs[A] / name
            docs.mkdir()
            (docs / "README.md").write_text(f"---\ntitle: 任务 {number:02d}\n---\n", encoding="utf-8")
            run = self.ws / "runtime/project_src/项目 A" / name / "runs/[20261009-090000]验证"
            run.mkdir(parents=True)
            (run / "run.json").write_text(json.dumps({"run_id": str(number), "title": "验证", "status": "running"}), encoding="utf-8")
            folder = self.docs[A] / f"目录 {number:02d}"
            folder.mkdir()
            (folder / "子目录").mkdir()
        self.project()
        self.page.get_by_test_id('task-list-toggle').click()
        expect(self.page.get_by_test_id("task-node")).to_have_count(35)

    def _settle(self):
        self.page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")

    def _position(self):
        return self.page.locator("#project-navigation").evaluate("el => el.scrollTop")

    def _assert_stable(self, before):
        self._settle()
        self.assertGreater(before, 300, "操作前必须已滚动离开顶部")
        self.assertAlmostEqual(self._position(), before, delta=2, msg="展开/折叠不能重置导航滚动位置")

    def test_task_expand_collapse_preserves_scroll(self):
        self._long_navigation()
        task = self.page.get_by_test_id("task-node").filter(has_text="任务 20")
        for expanded in ("false", "true"):
            button = task.locator("button.tv-toggle")
            button.scroll_into_view_if_needed()
            before = self._position()
            button.click()
            expect(task).to_have_attribute("aria-expanded", expanded)
            self._assert_stable(before)

    def test_directory_expand_collapse_preserves_scroll_and_focus(self):
        self._long_navigation()
        toggle = self.target_locator("tree-toggle", "目录 20")
        node = self.node("目录 20")
        for expanded in ("true", "false"):
            toggle.scroll_into_view_if_needed()
            before = self._position()
            toggle.click()
            expect(node).to_have_attribute("aria-expanded", expanded)
            expect(node).to_have_attribute("aria-busy", "false")
            self._assert_stable(before)
            expect(toggle).to_be_focused()
