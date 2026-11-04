"""快捷方式安装与撤销：清单记录与目标匹配删除。"""
from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from workbench.lifecycle import Instance
from workbench.windows import OpenFailed

PID_A = "11111111-1111-4111-8111-111111111111"


def _fake_win32com(target_path: str):
    """用可预测 TargetPath 的桩替换 win32com.client。"""
    client = types.ModuleType("win32com.client")

    class FakeLnk:
        def __init__(self, _path):
            self._target = target_path

        @property
        def TargetPath(self):
            return self._target

    class FakeShell:
        def CreateShortCut(self, path):
            return FakeLnk(path)

    client.Dispatch = lambda progid: FakeShell()
    mod = types.ModuleType("win32com")
    mod.client = client
    return mock.patch.dict(sys.modules, {"win32com": mod, "win32com.client": client})


class ShortcutsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.config = {"task_root": str(self.root / "task"), "config_path": str(self.root / "c.json"),
                       "workspace_root": str(self.root)}
        self.instance = Instance(self.config)
        self.launcher = self.root / "WorkbenchLauncher.exe"
        self.launcher.write_text("placeholder", encoding="utf-8")
        self.desktop = self.root / "Desktop"
        self.start_menu = self.root / "Start Menu"
        self.desktop.mkdir()
        self.start_menu.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _patch_dirs(self):
        patches = [
            mock.patch("workbench.shortcuts._desktop_dir", lambda: self.desktop),
            mock.patch("workbench.shortcuts._start_menu_dir", lambda: self.start_menu),
            mock.patch("workbench.shortcuts._create_shortcut",
                       side_effect=lambda lnk, target, args: Path(lnk).write_text("lnk", encoding="utf-8")),
        ]
        for p in patches:
            p.start()
        self.addCleanup(mock.patch.stopall)
        return patches

    def test_install_writes_manifest(self):
        self._patch_dirs()
        from workbench.shortcuts import install_shortcuts
        result = install_shortcuts(self.instance, str(self.launcher))
        self.assertEqual(len(result["entries"]), 2)
        self.assertTrue(all(e["created"] for e in result["entries"]))
        manifest_path = Path(result["manifest"])
        self.assertTrue(manifest_path.is_file())
        import json
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(len(manifest), 2)
        for path, info in manifest.items():
            self.assertTrue(Path(path).is_file())
            self.assertEqual(info["target"], str(self.launcher))
            self.assertEqual(info["app_user_model_id"], "dummysys.workbench")

    def test_install_missing_launcher_fails(self):
        self._patch_dirs()
        from workbench.shortcuts import install_shortcuts
        with self.assertRaises(OpenFailed):
            install_shortcuts(self.instance, str(self.root / "absent.exe"))

    def test_uninstall_removes_matching(self):
        self._patch_dirs()
        self.enterContext(_fake_win32com(str(self.launcher)))
        from workbench.shortcuts import install_shortcuts, uninstall_shortcuts
        install_shortcuts(self.instance, str(self.launcher))
        result = uninstall_shortcuts(self.instance)
        self.assertEqual(len(result["entries"]), 2)
        self.assertTrue(all(e["removed"] for e in result["entries"]))
        self.assertFalse((self.desktop / "DUMMYSYS 工作台.lnk").exists())
        # 清单清空后文件删除
        self.assertFalse((self.instance.install_path / "install-manifest.json").exists())

    def test_uninstall_keeps_mismatched_target(self):
        self._patch_dirs()
        self.enterContext(_fake_win32com(str(self.root / "OTHER.exe")))
        from workbench.shortcuts import install_shortcuts, uninstall_shortcuts
        install_shortcuts(self.instance, str(self.launcher))
        result = uninstall_shortcuts(self.instance)
        self.assertTrue(all(not e["removed"] for e in result["entries"]))
        self.assertTrue((self.desktop / "DUMMYSYS 工作台.lnk").exists())
        # 清单保留
        self.assertTrue((self.instance.install_path / "install-manifest.json").is_file())

    def test_uninstall_without_manifest(self):
        from workbench.shortcuts import uninstall_shortcuts
        result = uninstall_shortcuts(self.instance)
        self.assertEqual(result["entries"], [])


if __name__ == "__main__":
    unittest.main()
