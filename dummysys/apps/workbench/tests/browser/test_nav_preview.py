"""项目导航两组渲染、双视图切换与主区双栏预览。"""
from __future__ import annotations

from browser_fixture import A, B, BrowserCase, expect

TASK = "[task 1][20260921]工作台需求"
TASK_B = "[task 2][20260922]无运行任务"
TASK_ARC = "[task 3][20260920]归档任务"
TASK_C = "[task 4][20260919]已闭环任务"
TASK_D = "[task 5][20260918]失败任务"
RUN_1 = "[20260922-203515]Agent 入口"
RUN_2 = "[20260922-210000]修订文档"
RUN_C1 = "[20260919-090000]首轮验证"
RUN_C2 = "[20260920-100000]复跑确认"
RUN_D1 = "[20260918-080000]失败运行"
ORPHAN = "[20260922-220000]孤立运行"


class NavPreviewTests(BrowserCase):
    def _build_tasks(self):
        docs = self.docs[A]
        res = self.ws / "runtime/project_src/项目 A"
        res.mkdir(parents=True, exist_ok=True)
        (docs / "AGENTS.md").write_text("# 项目约定\n", encoding="utf-8")
        (res / "README.md").write_text("# 资源说明\n", encoding="utf-8")
        (res / "AGENTS.md").write_text("# 资源约定\n", encoding="utf-8")
        (docs / "笔记").mkdir()
        (docs / "笔记" / "README.md").write_text("# 子目录说明\n", encoding="utf-8")
        (docs / "Agent.md").write_text("# 不过滤\n", encoding="utf-8")
        (docs / TASK).mkdir()
        (docs / TASK / "README.md").write_text("---\ntitle: 需求标题\nstatus: active\n---\n", encoding="utf-8")
        (docs / TASK / "task.md").write_text("# 任务说明\n\n请看 [说明](https://example.org) 和 `code`。\n\n```python\ndef demo():\n    return 1\n```\n", encoding="utf-8")
        (res / TASK).mkdir()
        for name, status in ((RUN_1, "completed"), (RUN_2, "running")):
            run = res / TASK / "runs" / name
            run.mkdir(parents=True)
            (run / "run.json").write_text(
                '{"schema_version":1,"run_id":"%s","title":"%s","status":"%s","created_at":"2026-09-22T20:35:15+00:00"}'
                % (name, name, status), encoding="utf-8")
        (docs / TASK_B).mkdir()
        arc = docs / "archive"
        arc.mkdir()
        (arc / TASK_ARC).mkdir()
        (res / "loose").mkdir()
        orphan = res / "loose" / "runs" / ORPHAN
        orphan.mkdir(parents=True)
        (orphan / "run.json").write_text(
            '{"schema_version":1,"run_id":"orphan-1","title":"孤立运行","status":"failed"}',
            encoding="utf-8")

    def test_two_groups_and_declared_filtering(self):
        self._build_tasks()
        self.project()
        panel = self.page.get_by_test_id("nav-panel")
        expect(panel).to_be_visible()
        expect(self.page.get_by_test_id("task-node")).to_have_count(3)
        expect(self.page.get_by_test_id("run-node")).to_have_count(2)
        expect(self.page.get_by_test_id("orphan-run-node")).to_have_count(1)
        expect(self.page.get_by_test_id('task-number')).to_have_text(['#1', '#2', '#3'])
        summary = self.page.get_by_test_id('nav-task-summary')
        expect(summary).to_have_text('3 任务 · 3 运行')
        expect(summary).to_have_attribute('title', '普通任务 2 · 归档任务 1\n运行中 1 · 失败 1 · 孤立运行 1')
        self.page.screenshot(path=str(self.output / 'task-numbers-and-counts.png'))
        # README/AGENTS 仅规定位置过滤；子目录与 Agent.md 保留。
        expect(self.node()).to_be_visible()
        expect(self.node("Agent.md")).to_be_visible()
        expect(self.node("笔记")).to_be_visible()
        for name in ("README.md", "AGENTS.md", TASK, TASK_B):
            expect(self.node(name)).to_have_count(0)
        self.assertFalse(any(call["target"]["relative_path"].startswith("[task ") for call in self.list_calls))

    def test_filter_run_retains_owning_task_and_selection(self):
        self._build_tasks()
        self.project()
        query = self.page.get_by_test_id('task-filter-query')
        query.fill('修订文档')
        expect(self.page.get_by_test_id('task-node')).to_have_count(1)
        task = self.target_locator('task-node', TASK)
        expect(task).to_contain_text('需求标题')
        relative = TASK + '/runs/' + RUN_2
        run = self.target_locator('run-node', relative, root='resources')
        task.focus()
        self.page.keyboard.press('ArrowDown')
        expect(self.target_locator('run-node', TASK + '/runs/' + RUN_1, root='resources')).to_be_focused()
        self.page.keyboard.press('ArrowDown')
        expect(run).to_be_focused()
        self.page.keyboard.press('Enter')
        self.ready(relative, root='resources')
        expect(run).to_have_attribute('aria-selected', 'true')
        expect(task).to_have_attribute('aria-selected', 'true')
        expect(query).to_have_value('修订文档')
        self.project(B)
        expect(query).to_have_value('')

    def test_task_without_runs_and_orphan_listed(self):
        self._build_tasks()
        self.project()
        expect(self.page.get_by_text("暂无运行", exact=True)).to_have_count(2)
        expect(self.page.get_by_text("暂无运行", exact=True).first).to_be_visible()
        expect(self.page.get_by_test_id("orphan-run-node")).to_be_visible()

    def test_task_and_run_right_click_show_their_own_actions(self):
        self._build_tasks()
        self.project()
        task = self.page.get_by_test_id("task-node").filter(has_text="需求标题")
        task.click(button="right")
        expect(self.page.get_by_test_id("edit-task")).to_be_visible()
        expect(self.page.get_by_test_id("new-run")).to_be_visible()
        self.page.keyboard.press("Escape")
        run = self.page.get_by_test_id("run-node").filter(has_text="修订文档")
        run.click(button="right")
        expect(self.page.get_by_test_id("finish-run")).to_be_visible()
        expect(self.page.get_by_test_id("update-run")).to_be_visible()

    def test_task_view_styles_switch_and_persist(self):
        self._build_tasks()
        self.project()
        view = self.page.get_by_test_id("task-view")
        expect(view).to_have_attribute("data-task-view", "indent")
        options = self.page.locator("#task-view-select option").evaluate_all("nodes => nodes.map(node => node.value)")
        self.assertEqual(options, ["indent", "cards"])
        self.page.locator("#btn-settings").click()
        self.page.get_by_test_id("task-view-select").select_option("cards")
        expect(view).to_have_attribute("data-task-view", "cards")
        self.page.locator("#settings-close").click()
        self.page.reload()
        self.ready()
        expect(self.page.get_by_test_id("task-view")).to_have_attribute("data-task-view", "cards")

    def _add_task(self, name, runs):
        docs = self.docs[A]
        res = self.ws / "runtime/project_src/项目 A"
        (docs / name).mkdir()
        (res / name).mkdir()
        for run_name, status, created in runs:
            run = res / name / "runs" / run_name
            run.mkdir(parents=True)
            (run / "run.json").write_text(
                '{"schema_version":1,"run_id":"%s","title":"%s","status":"%s","created_at":"%s"}'
                % (run_name, run_name, status, created), encoding="utf-8")

    def test_settled_runs_fold_to_one_line_summary(self):
        self._build_tasks()
        self._add_task(TASK_C, [(RUN_C1, "completed", "2026-09-19T09:00:00+00:00"),
                                (RUN_C2, "cancelled", "2026-09-20T10:00:00+00:00")])
        self._add_task(TASK_D, [(RUN_D1, "failed", "2026-09-18T08:00:00+00:00")])
        self.project()
        settled = self.page.get_by_test_id("task-node").filter(has_text="已闭环任务")
        expect(settled).to_have_attribute("aria-expanded", "false")
        summary = self.page.get_by_test_id("run-summary")
        expect(summary).to_be_visible()
        expect(summary).to_contain_text("1 完成")
        expect(summary).to_contain_text("1 取消")
        expect(summary).to_contain_text("09-19→09-20")
        # 折叠时该 Task 的 Run 不逐条渲染；未收口的 failed 仍展开。
        expect(self.page.get_by_test_id("run-node")).to_have_count(3)
        expect(self.page.get_by_test_id("task-node").filter(has_text="失败任务")).to_have_attribute("aria-expanded", "true")
        settled.locator("button.tv-toggle").click()
        expect(settled).to_have_attribute("aria-expanded", "true")
        expect(self.page.get_by_test_id("run-node")).to_have_count(5)
        expect(self.page.get_by_test_id("run-summary")).to_have_count(0)

    def test_reclick_selected_collapses_and_toolbar_toggles(self):
        self._build_tasks()
        self.project()
        self.enter(TASK)
        self.ready(TASK)
        head = self.page.get_by_test_id("task-node").filter(has_text="需求标题")
        expect(head).to_have_attribute("aria-expanded", "true")
        head.click()
        expect(head).to_have_attribute("aria-expanded", "false")
        toggle = self.page.get_by_test_id("nav-toggle-all")
        # 仍有其它展开节点，单按钮本次动作是全部折叠。
        toggle.click()
        expect(head).to_have_attribute("aria-expanded", "false")
        # 全折叠后单按钮动作翻转为全部展开。
        toggle.click()
        expect(head).to_have_attribute("aria-expanded", "true")
        # 折叠不改变当前导航位置。
        self.ready(TASK)

    def test_markdown_renders_in_preview_and_themes_accent(self):
        self._build_tasks()
        self.project()
        self.enter(TASK)
        self.ready(TASK)
        self.row(TASK + "/task.md").click()
        body = self.page.get_by_test_id("preview-pane")
        expect(body).to_have_attribute("data-state", "ready")
        expect(body.locator(".markdown-body h1")).to_have_text("任务说明")
        expect(body.locator(".markdown-body code.hljs")).to_be_visible()
        expect(body.locator(".markdown-body .hljs-keyword").first).to_be_visible()
        color = body.locator(".markdown-body a").first.evaluate("el => getComputedStyle(el).color")
        accent = self.page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()")
        self.assertTrue(color, "链接应有强调色")
        self.assertTrue(accent, "应存在 --accent")
        # 自定义重点色跟随主题变量，而非硬编码主题文件。
        self.page.locator("#btn-settings").click()
        self.page.get_by_test_id("accent-hex").fill("#7c3aed")
        self.page.get_by_test_id("accent-hex").press("Enter")
        expect(self.page.locator(":root")).to_have_attribute("data-accent-color", "#7c3aed")
        self.page.locator("#settings-close").click()
        self.assertEqual(self.page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--hl-keyword').trim()"),
                         self.page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()"))

    def test_preview_width_persists(self):
        self._build_tasks()
        self.project()
        handle = self.page.get_by_test_id("preview-resizer")
        handle.focus()
        initial_width = self.page.locator('#preview-pane').evaluate('el => Math.round(el.getBoundingClientRect().width)')
        self.delay('preferences')
        for _ in range(6):
            self.page.keyboard.press("ArrowRight")
        self.delay_ready()
        width = self.page.locator("#preview-pane").evaluate("el => Math.round(el.getBoundingClientRect().width)")
        self.assertEqual(width, initial_width + 6 * 16)
        self.release()
        expect(handle).to_have_attribute('aria-busy', 'false')
        self.assertEqual(self.page.locator('#preview-pane').evaluate('el => Math.round(el.getBoundingClientRect().width)'), width)
        self.page.reload()
        self.ready()
        restored = self.page.locator("#preview-pane").evaluate("el => Math.round(el.getBoundingClientRect().width)")
        self.assertEqual(restored, width)
        handle.dblclick()
        expect(handle).to_have_attribute('aria-busy', 'false')
        reset = self.page.locator("#preview-pane").evaluate("el => Math.round(el.getBoundingClientRect().width)")
        self.assertLess(reset, width)
