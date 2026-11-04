"""真实分隔条缩窄文件列表时，表头和文件名称必须保留可用空间。"""
from browser_fixture import BrowserCase


class NarrowDirectoryTests(BrowserCase):
    def test_narrow_list_keeps_header_text_inside_its_column(self):
        self.project()
        handle = self.page.get_by_test_id("preview-resizer")
        handle.focus()
        for _ in range(28):
            self.page.keyboard.press("ArrowRight")
        bounds = self.page.locator(".entries thead th").evaluate_all("""cells => cells.filter(e => e.textContent.trim()).map(e => {
            const rect = e.getBoundingClientRect();
            const range = document.createRange(); range.selectNodeContents(e);
            const text = range.getBoundingClientRect();
            return {label:e.textContent,width:rect.width,textRight:text.right,right:rect.right};
        })""")
        self.page.screenshot(path=str(self.output / "narrow-directory.png"))
        print(bounds)
        for cell in bounds:
            self.assertLessEqual(cell["textRight"], cell["right"], cell["label"] + "越过自身列边界")
        self.assertGreaterEqual(bounds[0]["width"], 140, "名称列被固定宽度辅助列挤空")

    def test_horizontal_scroll_reaches_actions_and_wide_layout_stays_readable(self):
        self.project()
        initial = self.page.locator(".entries th").first.bounding_box()["width"]
        self.assertGreaterEqual(initial, 140)
        handle = self.page.get_by_test_id("preview-resizer")
        handle.focus()
        for _ in range(28):
            self.page.keyboard.press("ArrowRight")
        directory = self.page.get_by_test_id("directory-view")
        scroll = directory.evaluate("e => ({client:e.clientWidth, full:e.scrollWidth})")
        self.assertGreater(scroll["full"], scroll["client"])
        directory.evaluate("e => e.scrollLeft = e.scrollWidth")
        action = self.page.locator(".entries tbody tr").first.locator("td").last
        self.assertLessEqual(action.bounding_box()["x"] + action.bounding_box()["width"], directory.bounding_box()["x"] + directory.bounding_box()["width"], "横向滚动后操作列仍无法完整访问")
        handle.dblclick()
        self.assertGreaterEqual(self.page.locator(".entries th").first.bounding_box()["width"], 140)
        self.assertEqual(self.page_errors, [])
