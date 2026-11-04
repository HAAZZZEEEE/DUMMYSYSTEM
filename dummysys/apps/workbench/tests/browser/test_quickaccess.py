"""固定目录、最近访问与快捷跳转的真实浏览器交互。"""
import json
import re

from browser_fixture import A, B, SPECIAL, DEEP, BrowserCase, expect


class QuickAccessTests(BrowserCase):
    def test_pinned_location_persists_reload_and_home_removal(self):
        self.project()
        self.enter(SPECIAL)
        button = self.page.locator("#btn-pin-directory")
        with self.page.expect_response(lambda r: r.url.endswith('/api/v1/preferences') and r.request.method == 'PATCH' and 'pinned_locations' in r.request.post_data_json):
            button.click()
        expect(button).to_have_attribute("aria-pressed", "true")
        self.page.reload()
        self.ready(SPECIAL)
        expect(button).to_have_attribute("aria-pressed", "true")
        self.page.get_by_test_id("home").click()
        link = self.target_locator("pinned-location-link", SPECIAL)
        expect(link).to_be_visible()
        link.click()
        self.ready(SPECIAL)
        self.page.get_by_test_id("home").click()
        self.target_locator("unpin-location", SPECIAL).click()
        expect(self.target_locator("pinned-location-link", SPECIAL)).to_have_count(0)

    def test_recent_unique_success_only_and_clear(self):
        self.project()
        self.enter(SPECIAL)
        self.enter(DEEP.rsplit('/', 1)[0])
        self.page.locator("#btn-refresh").click()
        self.ready(DEEP.rsplit('/', 1)[0])
        self.page.get_by_test_id("directory-filter").fill("不存在")
        self.ready(DEEP.rsplit('/', 1)[0])
        self.page.get_by_test_id("home").click()
        links = self.page.get_by_test_id("recent-link")
        expect(links).to_have_count(3)
        expect(links.first).to_have_attribute("data-target", self.target_locator("recent-link", DEEP.rsplit('/', 1)[0]).get_attribute("data-target"))
        self.page.reload()
        self.page.get_by_test_id("home").click()
        expect(self.page.locator("#empty-state")).to_be_visible()
        expect(links).to_have_count(3)
        self.page.get_by_test_id("clear-recent").click()
        expect(links).to_have_count(0)
        expect(self.page.locator("#quick-home")).to_contain_text("还没有访问记录")

    def test_quick_keyboard_search_navigation_and_focus_return(self):
        self.project()
        self.enter(SPECIAL)
        self.page.locator("#btn-pin-directory").click()
        self.page.keyboard.press("Control+k")
        popover = self.page.locator("#quick-popover")
        search = self.page.locator("#project-search")
        expect(popover).to_have_class(re.compile(r"\bopen\b"))
        expect(search).to_be_focused()
        search.fill("项目 B")
        expect(self.page.get_by_test_id("quick-result")).to_have_count(1)
        search.press("Enter")
        self.ready(project=B)
        expect(popover).not_to_have_class(re.compile(r"\bopen\b"))
        self.page.locator("#btn-quick-switch").click()
        search.fill(SPECIAL)
        expect(self.target_locator("quick-result", SPECIAL)).to_be_visible()
        search.press("ArrowDown")
        search.press("ArrowUp")
        search.press("Escape")
        expect(popover).not_to_have_class(re.compile(r"\bopen\b"))
        expect(search).not_to_be_focused()

    def test_shortcuts_ignore_typing_and_focus_filters(self):
        project_search = self.page.get_by_test_id("project-search")
        project_search.focus()
        self.page.keyboard.type("/")
        expect(project_search).to_have_value("/")
        self.page.keyboard.press("Control+Shift+f")
        expect(self.page.get_by_test_id("global-search")).to_be_focused()
        project_search.fill("")
        project_search.press('Escape')
        self.project()
        self.page.keyboard.press("/")
        expect(self.page.get_by_test_id("directory-filter")).to_be_focused()
        self.page.get_by_test_id("directory-filter").fill("/")
        expect(self.page.get_by_test_id("directory-filter")).to_have_value("/")
        self.page.keyboard.press("Control+k")
        expect(self.page.locator("#project-search")).to_be_focused()
        self.page.locator("#project-search").fill("无匹配的项目")
        expect(self.page.get_by_test_id("quick-result")).to_have_count(0)
        expect(self.page.locator("#project-search")).not_to_have_attribute("aria-activedescendant", "quick-option-0")
        self.page.keyboard.press("ArrowDown")
        expect(self.page.locator("#project-search")).not_to_have_attribute("aria-activedescendant", "quick-option-0")
        self.page.keyboard.press("Escape")
        expect(self.page.locator("#quick-popover")).not_to_have_class(re.compile(r"\bopen\b"))

    def test_missing_pinned_location_remains_removable_and_uses_navigation_error(self):
        missing = {"project_id": A, "root_id": "docs", "relative_path": "已删除的目录"}
        self.application.save_preferences({"pinned_locations": [missing]})
        self.page.reload()
        self.page.get_by_test_id("home").click()
        self.target_locator("pinned-location-link", missing["relative_path"]).click()
        expect(self.page.locator("#error-view")).to_be_visible()
        self.page.get_by_test_id("home").click()
        self.target_locator("unpin-location", missing["relative_path"]).click()
        expect(self.target_locator("pinned-location-link", missing["relative_path"])).to_have_count(0)

    def test_full_pinned_location_list_preserved_with_message(self):
        full = [{"project_id": A, "root_id": "docs", "relative_path": f"旧固定目录/{i}"} for i in range(30)]
        self.application.save_preferences({"pinned_locations": full})
        self.page.reload()
        self.project()
        self.enter(SPECIAL)
        self.page.locator("#btn-pin-directory").click()
        expect(self.page.locator("#toast")).to_contain_text("最多固定 30 个目录")
        self.assertEqual(self.application.load_preferences()["pinned_locations"], full)
        expect(self.page.locator("#btn-pin-directory")).to_have_attribute("aria-pressed", "false")

    def test_other_dialog_keeps_its_focus_and_blocks_shortcuts(self):
        self.project()
        self.enter(SPECIAL)
        self.clipboard(reject=True)
        self.page.get_by_test_id("copy-directory").click()
        expect(self.page.get_by_test_id("copy-dialog")).to_be_visible()
        field = self.page.get_by_test_id("copy-path")
        expect(field).to_be_focused()
        for shortcut in ("Control+k", "Control+Shift+f", "/"):
            self.page.keyboard.press(shortcut)
            expect(field).to_be_focused()
            expect(self.page.locator("#quick-popover")).not_to_have_class(re.compile(r"\bopen\b"))
        self.page.keyboard.press("Escape")
        expect(self.page.get_by_test_id("copy-dialog")).to_be_hidden()

    def test_two_windows_keep_both_pinned_locations_after_stale_preferences(self):
        # 两个独立 context 共享同一个隔离服务与偏好文件，各自只在 bootstrap 读取一次偏好。
        self.project(A)
        self.enter(SPECIAL, A)
        other_context = self.browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
        self.addCleanup(other_context.close)
        other = other_context.new_page()
        other.set_default_timeout(12000)
        other_errors = []
        other.on("pageerror", lambda error: other_errors.append(str(error)))
        token = self.app.extensions["bootstrap_issuer"]()
        try:
            other.goto(self.origin + "/#token=" + token)
        except Exception:
            raise RuntimeError("第二窗口 bootstrap 导航失败（隐藏一次性令牌）。") from None
        expect(other.locator("#app")).to_be_visible()
        self.assertNotIn("#", other.url)
        other.locator(f'[data-testid="project-link"][data-id="{B}"]').click()
        other.wait_for_function("project => new URL(location.href).searchParams.get('project_id') === project", arg=B)
        expect(other.locator("#dir-view")).to_have_attribute("aria-busy", "false")
        other.locator('[data-testid="directory-entry"]').filter(has_text=SPECIAL).click()
        other.wait_for_function("path => new URL(location.href).searchParams.get('relative_path') === path", arg=SPECIAL)
        expect(other.locator("#btn-pin-directory")).to_be_enabled()
        # 导航自身的最近访问/最后位置写入先完成，随后才制造收藏的旧快照。
        other.wait_for_load_state("networkidle")
        # B 已读取空固定目录，之后不刷新；A 与 B 依次提交，防止 B 整表覆盖 A。
        with self.page.expect_response(lambda response: response.url.endswith('/api/v1/preferences')
                                       and response.request.method == 'PATCH'
                                       and 'pinned_locations' in response.request.post_data_json):
            self.page.locator("#btn-pin-directory").click()
        expect(self.page.locator("#btn-pin-directory")).to_have_attribute("aria-pressed", "true")
        with other.expect_response(lambda response: response.url.endswith('/api/v1/preferences')
                                   and response.request.method == 'PATCH'
                                   and 'pinned_locations' in response.request.post_data_json):
            other.locator("#btn-pin-directory").click()
        expect(other.locator("#btn-pin-directory")).to_have_attribute("aria-pressed", "true")
        expected = {
            json.dumps({"project_id": A, "root_id": "docs", "relative_path": SPECIAL}, sort_keys=True),
            json.dumps({"project_id": B, "root_id": "docs", "relative_path": SPECIAL}, sort_keys=True),
        }
        actual = {json.dumps(item, sort_keys=True) for item in self.application.load_preferences()["pinned_locations"]}
        self.assertEqual(actual, expected, "两个窗口各自新增的固定目录都应持久化")
        self.assertEqual(other_errors, [], "第二窗口出现未捕获的 JavaScript 异常")

    def test_home_refresh_updates_project_name_in_quick_switch(self):
        self.project(A)
        self.page.get_by_test_id("home").click()
        expect(self.page.get_by_test_id("recent-link")).to_have_count(1)
        readme = self.docs[A] / "README.md"
        content = readme.read_text(encoding="utf-8")
        self.assertIn('title: "项目 A"', content)
        readme.write_text(content.replace('title: "项目 A"', 'title: "项目 A 新名称"', 1), encoding="utf-8")
        with self.page.expect_response(lambda response: response.url.endswith('/api/v1/projects/refresh')):
            self.page.get_by_test_id("refresh-projects").click()
        expect(self.page.get_by_test_id("recent-link").first).to_contain_text("项目 A 新名称")
        self.page.keyboard.press("Control+k")
        search = self.page.locator("#project-search")
        search.fill("项目 A 新名称")
        expect(self.page.get_by_test_id("quick-result").first).to_contain_text("项目 A 新名称")
        search.fill("旧名字无结果")
        expect(self.page.get_by_test_id("quick-result")).to_have_count(0)
