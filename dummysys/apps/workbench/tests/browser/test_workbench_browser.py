"""通过真实 DOM 行为验证工作台；独立 unittest discover，不纳入普通单元测试。"""
from browser_fixture import A, B, DEEP, MANY, SAME, SPECIAL, BrowserCase, expect


class WorkbenchBrowserTests(BrowserCase):
    def test_refresh_without_browser_storage_restores_authenticated_writes(self):
        self.project()
        self.enter(SPECIAL)
        self.page.evaluate("sessionStorage.clear(); localStorage.clear()")
        self.page.reload()
        self.ready(SPECIAL)
        self.enter(SPECIAL + '/第二层 [深]#&')
        self.ready(SPECIAL + '/第二层 [深]#&')

    def test_history_back_forward_refresh_and_preference_restore(self):
        self.project()
        self.enter(SPECIAL)
        self.enter(SPECIAL + "/第二层 [深]#&")
        self.enter(DEEP)
        self.page.go_back()
        self.ready(SPECIAL + "/第二层 [深]#&")
        self.page.go_forward()
        self.ready(DEEP)
        self.page.reload()
        self.ready(DEEP)
        expect(self.row(DEEP + "/" + SAME)).to_be_visible()
        self.page.locator("#btn-up").click()
        self.ready(SPECIAL + "/第二层 [深]#&")
        self.page.get_by_test_id("history-back").click()
        self.ready(DEEP)
        # URL 无位置时，恢复服务端保存的最后成功位置。
        self.page.wait_for_function("document.querySelector('#dir-view').getAttribute('aria-busy') === 'false'")
        with self.page.expect_response(lambda response: response.url.endswith('/api/v1/preferences') and response.request.method == 'PATCH'):
            self.page.locator("#btn-refresh").click()
        self.ready(DEEP)
        self.page.goto(self.origin + "/")
        self.ready(DEEP)

    def test_root_tabs_and_home_history(self):
        self.project()
        self.target_locator("root-tab", root="resources").click()
        self.ready(root="resources")
        self.page.go_back()
        self.ready()
        self.page.get_by_test_id("home").click()
        expect(self.page.locator("#empty-state")).to_be_visible()
        self.page.go_back()
        self.ready()

    def test_old_actions_response_cannot_open_new_project(self):
        filename = '外部文件.bin'
        for root in self.docs.values():
            (root / filename).write_bytes(b'\x00\x01')
        self.project()
        self.delay("actions", project=A, relative=filename)
        self.row(filename).click()
        self.delay_ready()
        self.project(B)
        self.release()
        expect(self.row(filename, B)).to_be_visible()
        self.assertEqual(self.open_calls, [], "A 旧动作响应不应发送任何 open")
        self.assertEqual(self.opener.events(), [])
        # 正对照：B 的用户点击必须准确打开 B，避免以动作全部失效获得假绿。
        with self.page.expect_response(lambda response: response.url.endswith('/api/v1/open')):
            self.row(filename, B).click()
        events = self.opener.events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["target"], (self.docs[B] / filename).as_posix())

    def test_old_menu_response_cannot_attach_to_new_project(self):
        self.project()
        self.delay("actions", project=A, relative=SAME)
        self.row(SAME).get_by_test_id("target-menu").click()
        self.delay_ready()
        self.project(B)
        self.release()
        expect(self.page.get_by_role("menu")).to_have_count(0)
        self.assertEqual(self.open_calls, [])
        self.assertEqual(self.opener.events(), [])

    def test_loading_same_directory_blocks_old_rows_and_filter_wins(self):
        self.project()
        self.enter(MANY)
        expect(self.page.get_by_test_id("directory-entry")).to_have_count(200)
        self.delay("list", project=A, relative=MANY, cursor=True)
        self.page.locator("#btn-more").click()
        self.delay_ready()
        expect(self.page.get_by_test_id("directory-view")).to_have_attribute("aria-busy", "true")
        old = self.row(MANY + "/文件 000[条目]#&.txt")
        expect(old).to_have_attribute("aria-disabled", "true")
        expect(old.get_by_test_id("target-menu")).to_be_disabled()
        # 键盘可到达旧行；loading 时 Enter 不允许激活动作。
        old.focus()
        self.page.keyboard.press("Enter")
        self.assertEqual(self.open_calls, [])
        self.page.get_by_test_id("directory-filter").fill("204")
        self.ready(MANY)
        expect(self.page.get_by_test_id("directory-entry")).to_have_count(1)
        self.release()
        expect(self.page.get_by_test_id("directory-entry")).to_have_count(1)
        expect(self.row(MANY + "/文件 204[条目]#&.txt")).to_be_visible()
        expect(self.page.locator("#btn-more")).to_be_hidden()
        self.assertEqual(self.opener.events(), [])

    def test_out_of_order_filters_do_not_overwrite_latest(self):
        self.project()
        original_url = self.page.url
        self.delay("list", project=A, relative="", filter="筛选-甲")
        self.page.get_by_test_id("directory-filter").fill("筛选-甲")
        self.delay_ready()
        self.page.get_by_test_id("directory-filter").fill("筛选-乙")
        expect(self.row("筛选-乙.txt")).to_be_visible()
        self.release()
        expect(self.page.get_by_test_id("directory-entry")).to_have_count(1)
        expect(self.row("筛选-甲.txt")).to_have_count(0)
        expect(self.page.get_by_test_id("directory-filter")).to_have_value("筛选-乙")
        self.assertEqual(self.page.url, original_url)

    def test_tree_lazy_expand_collapse_and_list_sync(self):
        self.project()
        expect(self.node(SPECIAL)).to_be_visible()
        self.assertFalse(any(call["target"]["relative_path"] == SPECIAL for call in self.list_calls))
        self.target_locator("tree-toggle", SPECIAL).click()
        child = SPECIAL + "/第二层 [深]#&"
        expect(self.node(child)).to_be_visible()
        self.ready()  # 展开只读树，不改变当前列表。
        self.node(child).locator(":scope > .tree-label").click()
        self.ready(child)
        expect(self.node(child)).to_have_attribute("aria-selected", "true")
        expect(self.row(DEEP)).to_be_visible()
        self.enter(DEEP)
        expect(self.node(DEEP)).to_have_attribute("aria-selected", "true")
        expect(self.node(DEEP + "/" + SAME)).to_be_visible()
        self.target_locator("tree-toggle", SPECIAL).click()
        expect(self.node(child)).to_have_count(0)
        self.ready(DEEP)

    def test_tree_node_pagination_and_refresh(self):
        self.project()
        self.target_locator("tree-toggle", MANY).click()
        first = MANY + "/文件 000[条目]#&.txt"
        last = MANY + "/文件 204[条目]#&.txt"
        expect(self.node(first)).to_be_attached()
        expect(self.node(last)).to_have_count(0)
        self.target_locator("tree-more", MANY).click()
        expect(self.node(last)).to_be_attached()
        expect(self.target_locator("tree-more", MANY)).to_have_count(0)
        self.assertEqual(self.node(MANY).get_by_role("treeitem").count(), 205)
        self.ready()
        self.enter(MANY)
        new = "000新增 [刷新]#&.txt"
        (self.docs[A] / MANY / new).write_text("刷新", encoding="utf-8")
        self.page.locator("#btn-refresh").click()
        self.ready(MANY)
        expect(self.row(MANY + "/" + new)).to_be_visible()
        expect(self.node(MANY + "/" + new)).to_be_attached()
        expect(self.node(last)).to_have_count(0)  # 刷新丢弃树的第二页。

    def test_tree_keyboard_navigation_and_menu_escape_focus(self):
        self.project()
        expect(self.node(SPECIAL)).to_be_visible()
        folder = self.node(SPECIAL)
        folder.focus()
        self.page.keyboard.press("ArrowRight")
        expect(folder).to_have_attribute("aria-expanded", "true")
        child = self.node(SPECIAL + "/第二层 [深]#&")
        expect(child).to_be_attached()
        self.page.keyboard.press("ArrowRight")
        expect(child).to_be_focused()
        self.page.keyboard.press("ArrowLeft")
        expect(folder).to_be_focused()
        self.page.keyboard.press("ArrowLeft")
        expect(folder).to_have_attribute("aria-expanded", "false")
        self.page.keyboard.press("Space")
        expect(folder).to_have_attribute("aria-expanded", "true")
        self.page.keyboard.press("Enter")
        self.ready(SPECIAL)
        expect(folder).to_have_attribute("aria-selected", "true")
        folder.focus()
        self.page.keyboard.press("Home")
        expect(self.node()).to_be_focused()
        self.page.keyboard.press("ArrowDown")
        focused = self.page.locator('[role="treeitem"]:focus').get_attribute("data-target")
        self.page.keyboard.press("ArrowUp")
        expect(self.node()).to_be_focused()
        self.assertIsNotNone(focused)
        self.page.keyboard.press("End")
        expect(self.page.get_by_role("treeitem").last).to_be_focused()
        trigger = self.row(SPECIAL + "/" + SAME).get_by_test_id("target-menu")
        trigger.click()
        expect(self.page.get_by_test_id("action-vscode_open")).to_be_visible()
        self.page.keyboard.press("Escape")
        expect(self.page.get_by_role("menu")).to_have_count(0)
        expect(trigger).to_be_focused()

    def test_right_click_uses_target_actions_and_preserves_navigation(self):
        self.project()
        self.enter(SPECIAL)
        file_row = self.row(SPECIAL + "/" + SAME)
        file_row.click(button="right")
        expect(self.page.get_by_role("menu")).to_be_visible()
        expect(self.page.get_by_test_id("preview-target")).to_be_visible()
        expect(self.page.get_by_test_id("copy-target")).to_be_visible()
        self.ready(SPECIAL)
        self.page.keyboard.press("Escape")
        folder = self.node(SPECIAL)
        folder.click(button="right")
        expect(self.page.get_by_test_id("copy-target")).to_be_visible()
        self.ready(SPECIAL)

    def test_page_declares_served_workbench_icon(self):
        self.project()
        icon = self.page.locator('link[rel="icon"]')
        expect(icon).to_have_attribute("href", "/icons/app-icon.png")
        response = self.page.request.get(self.origin + "/icons/app-icon.png")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers.get("content-type"), "image/png")

    def test_copy_success_records_exact_native_path(self):
        self.project()
        self.enter(SPECIAL)
        self.clipboard()
        self.page.get_by_test_id("copy-directory").click()
        expect(self.page.locator("#toast")).to_have_text("已复制完整路径")
        self.row(SPECIAL + "/" + SAME).get_by_test_id("target-menu").click()
        self.page.get_by_test_id("copy-target").click()
        expected = [str(self.docs[A] / SPECIAL), str(self.docs[A] / SPECIAL / SAME)]
        self.page.wait_for_function("expected => JSON.stringify(window.__clipboardWrites) === JSON.stringify(expected)", arg=expected)
        expect(self.page.get_by_test_id("copy-dialog")).to_be_hidden()

    def test_copy_permission_denied_shows_selected_fallback_text(self):
        self.project()
        self.enter(SPECIAL)
        self.clipboard(reject=True)
        self.row(SPECIAL + "/" + SAME).get_by_test_id("target-menu").click()
        self.page.get_by_test_id("copy-target").click()
        expect(self.page.get_by_test_id("copy-dialog")).to_be_visible()
        field = self.page.get_by_test_id("copy-path")
        expected = str(self.docs[A] / SPECIAL / SAME)
        expect(field).to_have_value(expected)
        expect(field).to_be_focused()
        self.assertEqual(field.evaluate("e => [e.selectionStart, e.selectionEnd]"), [0, len(expected)])
        self.assertEqual(self.page.evaluate("window.__clipboardWrites"), [])
        self.page.keyboard.press("Escape")
        expect(self.page.get_by_test_id("copy-dialog")).to_be_hidden()

    def test_theme_three_states_persist_and_follow_system_with_screenshots(self):
        self.project()
        self.enter(SPECIAL)
        select = self.page.get_by_test_id("theme-select")
        html = self.page.locator("html")
        for preference in ("light", "dark", "system"):
            self.page.locator('#btn-settings').click()
            with self.page.expect_response(lambda response: response.url.endswith('/api/v1/preferences') and response.request.method == 'PATCH' and response.request.post_data_json.get('theme') == preference):
                select.select_option(preference)
            self.page.reload()
            self.ready(SPECIAL)
            expect(select).to_have_value(preference)
            expect(html).to_have_attribute("data-theme-preference", preference)
            for system in ("light", "dark"):
                self.page.emulate_media(color_scheme=system)
                actual = system if preference == "system" else preference
                expect(html).to_have_attribute("data-theme", actual)
                if preference == "system":
                    expect(self.node(SPECIAL)).to_have_attribute("aria-selected", "true")
                    self.page.screenshot(path=str(self.output / f"workbench-{actual}.png"), full_page=True)
        self.assertEqual(self.application.load_preferences()["theme"], "system")

    def test_sidebar_resizer_keyboard_persist_and_double_click_reset(self):
        self.project()
        handle = self.page.get_by_test_id("sidebar-resizer")
        sidebar = self.page.locator(".sidebar")
        base = sidebar.evaluate("e => e.getBoundingClientRect().width")
        handle.focus()
        with self.page.expect_response(lambda response: response.url.endswith('/api/v1/preferences') and response.request.method == 'PATCH' and isinstance(response.request.post_data_json.get('sidebar_width'), int)):
            self.page.keyboard.press("ArrowRight")
        grown = sidebar.evaluate("e => e.getBoundingClientRect().width")
        self.assertAlmostEqual(grown, min(base + 16, 640), delta=1)
        self.assertEqual(self.application.load_preferences()["sidebar_width"], round(grown))
        self.page.reload()
        self.ready()
        self.assertAlmostEqual(sidebar.evaluate("e => e.getBoundingClientRect().width"), grown, delta=1)
        with self.page.expect_response(lambda response: response.url.endswith('/api/v1/preferences') and response.request.method == 'PATCH' and response.request.post_data_json.get('sidebar_width') is None):
            handle.dblclick()
        self.assertIsNone(self.application.load_preferences()["sidebar_width"])
        self.assertAlmostEqual(sidebar.evaluate("e => e.getBoundingClientRect().width"), base, delta=1)

    def test_stale_cursor_clears_list_pages_and_reloads_first_page(self):
        self.project()
        self.enter(MANY)
        expect(self.page.get_by_test_id("directory-entry")).to_have_count(200)
        removed = MANY + "/文件 000[条目]#&.txt"
        (self.docs[A] / removed).unlink()
        added = MANY + "/000新增 [过期]#&.txt"
        (self.docs[A] / added).write_text("触发真实游标失效", encoding="utf-8")
        self.page.locator("#btn-more").click()
        expect(self.row(added)).to_be_visible()
        expect(self.page.get_by_test_id("directory-entry")).to_have_count(200)
        expect(self.row(removed)).to_have_count(0)
        expect(self.page.locator("#toast")).to_contain_text("分页已失效")
        self.assertIn(409, self.response_codes)
        self.page.locator("#btn-more").click()
        expect(self.page.get_by_test_id("directory-entry")).to_have_count(205)
        paths = self.page.get_by_test_id("directory-entry").evaluate_all("rows => rows.map(row => row.dataset.target)")
        self.assertEqual(len(paths), len(set(paths)))

    def test_stale_cursor_clears_tree_pages_and_reloads_first_page(self):
        self.project()
        self.target_locator("tree-toggle", MANY).click()
        more = self.target_locator("tree-more", MANY)
        expect(more).to_be_attached()
        removed = MANY + "/文件 000[条目]#&.txt"
        (self.docs[A] / removed).unlink()
        added = MANY + "/000新增 [过期]#&.txt"
        (self.docs[A] / added).write_text("树的真实游标失效", encoding="utf-8")
        more.click()
        expect(self.node(added)).to_be_attached()
        expect(self.node(removed)).to_have_count(0)
        self.assertEqual(self.node(MANY).get_by_role("treeitem").count(), 200)
        self.assertIn(409, self.response_codes)
        more.click()
        expect(self.node(MANY + "/文件 204[条目]#&.txt")).to_be_attached()
        self.assertEqual(self.node(MANY).get_by_role("treeitem").count(), 205)
        self.ready()
