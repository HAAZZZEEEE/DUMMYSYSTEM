"""已安装入口保持显式配置、独立于源码与当前目录。"""
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / "scripts" / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


entry = load("public_entry", "launch_source.py")
setup = load("public_setup", "setup_source.py")


class SourceEntryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.runtime = Path(self.tmp.name) / "runtime/workbench"
        self.runtime.mkdir(parents=True)
        self.python = self.runtime.parent / "envs/test/Scripts/python.exe"
        self.python.parent.mkdir(parents=True)
        self.python.touch()
        self.config = self.runtime / "config.json"
        self.config.write_text("{}")
        self.record = self.runtime / "source.json"
        self.record.write_text(json.dumps(dict(mode="wheel", python=str(self.python), config=str(self.config))))

    def test_launch_uses_installed_interpreter_and_saved_config(self):
        with patch.dict(os.environ, {"PYTHONPATH": "unrelated-source", "DMY_EXE": "unrelated-cli"}):
            for command in entry.COMMANDS:
                with self.subTest(command=command), patch.object(entry.subprocess, "call", return_value=0) as call:
                    self.assertEqual(entry.main(["--runtime-root", str(self.runtime), command]), 0)
                    args = call.call_args.args[0]
                    self.assertEqual(args[:6], [str(self.python), "-I", "-B", "-m", "workbench", command])
                    self.assertEqual(args[-2:], ["--config", str(self.config)])
                    self.assertNotIn("PYTHONPATH", call.call_args.kwargs["env"])
                    self.assertNotIn("DMY_EXE", call.call_args.kwargs["env"])

    def test_invalid_or_source_record_does_not_launch(self):
        for record in ("[]", "{}", "invalid", '{"mode":"source"}'):
            self.record.write_text(record)
            with patch.object(entry.subprocess, "call") as call, patch.object(entry, "_report"):
                self.assertEqual(entry.main(["--runtime-root", str(self.runtime)]), 1)
                call.assert_not_called()

    def test_missing_or_outside_interpreter_does_not_launch(self):
        self.python.unlink()
        with patch.object(entry.subprocess, "call") as call, patch.object(entry, "_report"):
            self.assertEqual(entry.main(["--runtime-root", str(self.runtime)]), 1)
            call.assert_not_called()
        self.record.write_text(json.dumps(dict(mode="wheel", python=str(Path(os.sys.executable)), config=str(self.config))))
        with patch.object(entry.subprocess, "call") as call, patch.object(entry, "_report"):
            self.assertEqual(entry.main(["--runtime-root", str(self.runtime)]), 1)
            call.assert_not_called()

    def test_installer_resolves_only_explicit_sibling(self):
        self.assertEqual(setup.resolve_cli_src(), setup.REPO_ROOT.parent / "dummysys-cli")
        with self.assertRaises(ValueError):
            setup.resolve_cli_src(self.runtime / "missing")

    def test_browser_launch_uses_authenticated_lifecycle_without_native_dependency(self):
        from argparse import Namespace
        from workbench.__main__ import cmd_launch
        with patch('workbench.__main__._config', return_value={'apps': {}}), patch('workbench.__main__._print'), patch('workbench.lifecycle.Lifecycle') as lifecycle:
            lifecycle.return_value.launch.return_value = {'window_dispatched': True}
            self.assertEqual(cmd_launch(Namespace(config='explicit.json', browser=True)), 0)
            opener = lifecycle.return_value.launch.call_args.kwargs['opener']
            self.assertFalse(opener.supports_native_window)
