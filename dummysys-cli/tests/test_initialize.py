"""空工作区、身份隔离和失败保留契约，使用安装包。"""
import io
import json
import os
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dummysys_cli.__main__ import main, configured_workspace
from dummysys_core.initialize import initialize
from dummysys_core.operations import GovernanceError
from dummysys_core.workspace import Workspace
from dummysys_core.validation import layout, vault


class InitializeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def test_new_identity_complete_layout_and_no_business_records(self):
        roots = [self.base / "中文 空间", self.base / "second"]
        results = [initialize(root) for root in roots]
        self.assertNotEqual(results[0]["workspace_id"], results[1]["workspace_id"])
        self.assertNotEqual(results[0]["project_id"], results[1]["project_id"])
        for root in roots:
            self.assertEqual(layout.validate(root), [])
            self.assertEqual(vault.validate(root), [])
            self.assertTrue(Workspace(root).check()["ok"])
            self.assertEqual(Workspace(root).tasks(), [])
            self.assertFalse((root / "tools").exists())
            self.assertTrue((root / "AGENTS.md").samefile(root / "dmy_vault/10-系统/Codex工作区指令.md"))

    def test_empty_existing_directory_allowed(self):
        root = self.base / "empty"
        root.mkdir()
        self.assertEqual(initialize(root)["status"], "completed")

    def test_new_project_is_a_reading_root_without_editing_homepage(self):
        root = self.base
        initialize(root)
        ws = Workspace(root)
        project = ws.mutate('project.create', {'title': '新主题'}, actor='tester', request_id='project')['result']['project_id']
        ws.mutate('task.create', {'project': project, 'title': '新工作', 'origin': 'user', 'goal': '验证阅读边界'}, actor='tester', request_id='task')
        self.assertEqual(vault.validate(root), [])

    def test_nonempty_and_repeat_cli_never_modify_files(self):
        for initialized in (False, True):
            root = self.base / str(initialized)
            root.mkdir()
            if initialized:
                initialize(root)
            else:
                (root / ".hidden").write_bytes(b"keep")
            before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = main(["init", "--workspace", str(root), "--json"])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out.getvalue())["error"]["code"], "WORKSPACE_NOT_EMPTY")
            self.assertEqual(before, {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()})

    def test_failure_keeps_partial_workspace_and_recovery_advice(self):
        root = self.base / "failure"
        with patch("dummysys_core.initialize.os.link", side_effect=OSError("unavailable")):
            with self.assertRaises(GovernanceError) as error:
                initialize(root)
        self.assertEqual(error.exception.code, "INIT_FAILED")
        receipt = json.loads((root / "runtime/state/workspace/init.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], "failed")
        self.assertTrue((root / "dmy_vault/10-系统/Codex工作区指令.md").exists())
        with self.assertRaises(GovernanceError):
            initialize(root)

    def test_global_configuration_is_not_implicitly_read(self):
        global_dir = self.base / "DUMMYSYS"
        global_dir.mkdir()
        (global_dir / "cli.json").write_text(json.dumps(dict(schema_version=1, workspace=str(self.base))))
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.base)}, clear=True):
            with self.assertRaises(GovernanceError) as error:
                configured_workspace()
        self.assertEqual(error.exception.code, "CONFIG_REQUIRED")


if __name__ == "__main__":
    unittest.main()
