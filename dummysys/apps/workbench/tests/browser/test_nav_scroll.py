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

    def test_bottom_fade_only_while_each_pane_has_more_content(self):
        (self.docs[A] / "长预览.txt").write_text("可滚动的预览内容\n" * 220, encoding="utf-8")
        self._long_navigation()
        navigation = self.page.locator("#project-navigation")
        directory = self.page.get_by_test_id("directory-view")
        projects = self.page.locator("#sidebar-scroll")
        preview = self.page.locator("#preview-body")
        for pane in (navigation, directory):
            expect(pane).not_to_have_css("mask-image", "none")
        expect(projects).to_have_css("mask-image", "none")
        expect(preview).to_have_css("mask-image", "none")
        self.page.screenshot(path=self.output / "scroll-fades-light.png", animations="disabled")

        navigation.evaluate("el => el.scrollTop = el.scrollHeight")
        expect(navigation).to_have_css("mask-image", "none")
        expect(directory).not_to_have_css("mask-image", "none")
        directory.evaluate("el => el.scrollTop = el.scrollHeight")
        expect(directory).to_have_css("mask-image", "none")

        self.row("长预览.txt").click()
        expect(preview).not_to_have_css("mask-image", "none")
        self.page.emulate_media(color_scheme="dark")
        expect(self.page.locator("html")).to_have_attribute("data-theme", "dark")
        self.page.screenshot(path=self.output / "scroll-fades-dark.png", animations="disabled")
        self.row("README.md").click()
        expect(preview).to_have_css("mask-image", "none")

        directory.evaluate("el => el.scrollTop = 0")
        expect(directory).not_to_have_css("mask-image", "none")
        self.page.keyboard.press("/")
        search = self.page.get_by_test_id("directory-filter")
        expect(search).to_be_focused()
        expect(directory).to_have_css("mask-image", "none")
        search.fill("长预览")
        expect(self.page.get_by_test_id("directory-entry")).to_have_count(1)
        search.blur()
        expect(directory).to_have_css("mask-image", "none")
