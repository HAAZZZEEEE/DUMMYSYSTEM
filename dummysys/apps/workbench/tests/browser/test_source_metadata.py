"""源码工作台设置展示与错误边界。"""
import re
from pathlib import Path

import workbench
from browser_fixture import BrowserCase, expect


class SourceMetadataTests(BrowserCase):
    def test_settings_display_source_identity_and_no_channel_selector(self):
        self.page.locator("#btn-settings").click()
        expect(self.page.locator("#settings-dialog")).to_be_visible()
        expect(self.page.get_by_test_id("meta-version")).not_to_have_text("—")
        checkout = (Path(workbench.__file__).resolve().parents[1] / "pyproject.toml").is_file()
        expect(self.page.get_by_test_id("meta-source")).to_contain_text("源码检出" if checkout else "wheel 安装包")
        expect(self.page.get_by_test_id("meta-sha")).to_have_text(re.compile(r"^(?:[0-9a-f]{7}|—)$"))
        self.assertEqual(self.page.get_by_test_id("meta-channel").count(), 0)
        self.assertEqual(self.page_errors, [])
        self.page.locator("#settings-close").click()
        expect(self.page.locator("#settings-dialog")).not_to_be_visible()
