"""应用层：打开规则、防重与偏好原子写入。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from workbench.application import Application
from workbench.catalog import Catalog, CatalogError, InvalidTarget
from workbench.windows import RecordingOpener
from tests.helpers import build_workspace

PID_A = "11111111-1111-4111-8111-111111111111"


def _vault_path(ws: Path) -> Path:
    return ws / "d" / "vault"


def _app(ws: Path, vault: str | None) -> tuple[Application, RecordingOpener]:
    config = {
        "workspace_root": ws,
        "task_root": ws / "task",
        "apps": {"obsidian_vault_path": vault},
    }
    catalog = Catalog(config)
    opener = RecordingOpener()
    application = Application(catalog, opener)
    application.set_preferences_path(ws / "state" / "preferences.json")
    return application, opener


def _file(ws: Path, rel: str) -> dict:
    return {"project_id": PID_A, "root_id": "docs", "relative_path": rel}


class ActionRulesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ws = build_workspace(self.root, {
            "proj": {"project_id": PID_A, "docs_root": "d/vault", "resource_root": "r/proj",
                     "repositories": []},
        })
        self.vault = _vault_path(self.ws)
        self.vault.mkdir(parents=True, exist_ok=True)
        self.outside = self.root / "outside"
        self.outside.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _actions_for(self, path: str, kind: str = "file") -> dict:
        from workbench.application import Application
        return Application._actions_for(None, {"path": str(path), "kind": kind})

    def test_markdown_in_vault_defaults_to_obsidian(self):
        resolved = {"path": str(self.vault / "笔记.md"), "kind": "file"}
        application, _ = _app(self.ws, str(self.vault))
        actions = application._actions_for(resolved)
        self.assertEqual(actions["default_action"], "obsidian_open")
        self.assertEqual(actions["available_actions"][:2], ["obsidian_open", "vscode_open"])

    def test_markdown_outside_vault_defaults_to_vscode(self):
        resolved = {"path": str(self.outside / "note.md"), "kind": "file"}
        application, _ = _app(self.ws, str(self.vault))
        actions = application._actions_for(resolved)
        self.assertEqual(actions["default_action"], "vscode_open")

    def test_no_vault_configured_uses_vscode(self):
        resolved = {"path": str(self.vault / "笔记.md"), "kind": "file"}
        application, _ = _app(self.ws, None)
        self.assertEqual(application._actions_for(resolved)["default_action"], "vscode_open")

    def test_code_defaults_to_vscode(self):
        application, _ = _app(self.ws, None)
        for name in ("main.py", "app.js", "config.json", "Dockerfile.txt"):
            actions = application._actions_for({"path": str(self.outside / name), "kind": "file"})
            self.assertEqual(actions["default_action"], "vscode_open", name)

    def test_documents_media_html_default_to_system(self):
        application, _ = _app(self.ws, None)
        for name in ("a.pdf", "b.png", "c.html", "d.docx"):
            actions = application._actions_for({"path": str(self.outside / name), "kind": "file"})
            self.assertEqual(actions["default_action"], "system_open", name)
            self.assertIn("vscode_open", actions["available_actions"])

    def test_binary_executable_no_default(self):
        application, _ = _app(self.ws, None)
        for name in ("a.exe", "b.com", "c.msi", "d.lnk"):
            actions = application._actions_for({"path": str(self.outside / name), "kind": "file"})
            self.assertIsNone(actions["default_action"], name)
            self.assertNotIn("system_open", actions["available_actions"])

    def test_script_files_never_offer_system_open(self):
        application, _ = _app(self.ws, None)
        for name in ("s.py", "s.bat", "s.cmd", "s.ps1", "s.sh", "s.js"):
            actions = application._actions_for({"path": str(self.outside / name), "kind": "file"})
            self.assertEqual(actions["default_action"], "vscode_open", name)
            self.assertNotIn("system_open", actions["available_actions"], name)

    def test_directory_actions(self):
        application, _ = _app(self.ws, None)
        actions = application._actions_for({"path": str(self.vault), "kind": "dir"})
        self.assertEqual(actions["default_action"], "browse")
        self.assertEqual(actions["available_actions"], ["vscode_open", "explorer_open"])

    def test_missing_file_no_default(self):
        application, _ = _app(self.ws, None)
        actions = application._actions_for({"path": str(self.outside / "nope.py"), "kind": "missing"})
        self.assertIsNone(actions["default_action"])
        self.assertEqual(actions["available_actions"], [])


class OpenFlowTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ws = build_workspace(self.root, {
            "proj": {"project_id": PID_A, "docs_root": "d/vault", "resource_root": "r/proj",
                     "repositories": []},
        })
        self.vault = _vault_path(self.ws)
        self.vault.mkdir(parents=True, exist_ok=True)
        (self.vault / "a.py").write_text("x", encoding="utf-8")
        (self.vault / "b.md").write_text("x", encoding="utf-8")
        self.application, self.opener = _app(self.ws, str(self.vault))

    def tearDown(self):
        self._tmp.cleanup()

    def test_open_vscode_dispatches(self):
        result = self.application.open(_file(self.ws, "a.py"), "vscode_open")
        self.assertEqual(result["status"], "dispatched")
        self.assertEqual(result["action"], "vscode_open")
        self.assertEqual(self.opener.events()[0]["action"], "vscode_open")

    def test_duplicate_request_id_deduped(self):
        rid = "req-1"
        self.application.open(_file(self.ws, "a.py"), "vscode_open", rid)
        result = self.application.open(_file(self.ws, "a.py"), "vscode_open", rid)
        self.assertEqual(self.opener.events().__len__(), 1)
        self.assertEqual(result["status"], "dispatched")

    def test_different_request_id_opens_twice(self):
        self.application.open(_file(self.ws, "a.py"), "vscode_open", "r1")
        self.application.open(_file(self.ws, "a.py"), "vscode_open", "r2")
        self.assertEqual(len(self.opener.events()), 2)

    def test_unsupported_action_rejected(self):
        with self.assertRaises(InvalidTarget):
            self.application.open(_file(self.ws, "a.py"), "obsidian_open")
        with self.assertRaises(InvalidTarget):
            self.application.open(_file(self.ws, "b.md"), "system_open")

    def test_directory_rejects_obsidian(self):
        with self.assertRaises(InvalidTarget):
            self.application.open(_file(self.ws, ""), "obsidian_open")
        result = self.application.open(_file(self.ws, ""), "vscode_open")
        self.assertEqual(result["status"], "dispatched")

    def test_available_actions_endpoint(self):
        actions = self.application.available_actions(_file(self.ws, "b.md"))
        self.assertEqual(actions["default_action"], "obsidian_open")


class PreferencesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ws = build_workspace(self.root, {
            "proj": {"project_id": PID_A, "docs_root": "d/vault", "resource_root": "r/proj",
                     "repositories": []},
        })

    def tearDown(self):
        self._tmp.cleanup()

    def test_default_preferences(self):
        application, _ = _app(self.ws, None)
        prefs = application.load_preferences()
        self.assertEqual(prefs["pinned_project_ids"], [])
        self.assertEqual(prefs["directory_columns"], [])
        self.assertEqual(prefs["schema_version"], 1)

    def test_save_load_roundtrip(self):
        application, _ = _app(self.ws, None)
        application.save_preferences({"pinned_project_ids": [PID_A], "project_order": ["x", PID_A]})
        loaded = application.load_preferences()
        self.assertEqual(loaded["pinned_project_ids"], [PID_A])
        self.assertEqual(loaded["project_order"], ["x", PID_A])

    def test_save_filters_empty_and_stringifies(self):
        application, _ = _app(self.ws, None)
        application.save_preferences({"pinned_project_ids": [None, "", 42, PID_A]})
        loaded = application.load_preferences()
        self.assertEqual(loaded["pinned_project_ids"], ["42", PID_A])

    def test_atomic_write_no_tmp_left(self):
        application, _ = _app(self.ws, None)
        application.save_preferences({"pinned_project_ids": [PID_A]})
        path = application._preferences_path
        self.assertTrue(path.is_file())
        tmp = path.with_suffix(".json.tmp")
        self.assertFalse(tmp.is_file())
        # 原子写入产物可被 JSON 解析
        json.loads(path.read_text(encoding="utf-8"))

    def test_save_without_path_raises(self):
        application = Application(Catalog({"workspace_root": self.ws, "apps": {}}), RecordingOpener())
        with self.assertRaises(CatalogError):
            application.save_preferences({"pinned_project_ids": []})

    def test_corrupt_preferences_file_falls_back(self):
        application, _ = _app(self.ws, None)
        application.save_preferences({"pinned_project_ids": [PID_A]})
        application._preferences_path.write_text("{broken", encoding="utf-8")
        loaded = application.load_preferences()
        self.assertEqual(loaded["pinned_project_ids"], [])


if __name__ == "__main__":
    unittest.main()
