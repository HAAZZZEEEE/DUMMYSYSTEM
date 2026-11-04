"""后台调用从无控制台宿主启动时，不得新建控制台。"""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from workbench.windows import WindowsOpener, OpenFailed
from workbench.processes import run_background


class BackgroundContractTest(unittest.TestCase):
    def test_output_exit_status_and_arguments_survive(self):
        result = run_background([sys.executable, '-c',
                                 'import sys; print(sys.argv[1]); print("错误", file=sys.stderr); sys.exit(7)',
                                 '中文 & 空格'], capture_output=True, encoding='utf-8',
                                env=dict(os.environ, PYTHONIOENCODING='utf-8'), timeout=10)
        self.assertEqual(result.returncode, 7)
        self.assertEqual(result.stdout.strip(), '中文 & 空格')
        self.assertEqual(result.stderr.strip(), '错误')

    def test_timeout_is_not_swallowed(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            run_background([sys.executable, '-c', 'import time; time.sleep(10)'],
                           capture_output=True, timeout=0.2)

    def test_non_windows_preserves_options(self):
        with patch('workbench.processes.os.name', 'posix'), patch('subprocess.run') as run:
            run_background(['command'], timeout=3)
        run.assert_called_once_with(['command'], timeout=3)


@unittest.skipUnless(os.name == 'nt', 'Windows 控制台回归')
class BackgroundProcessTest(unittest.TestCase):
    def test_conflicting_flags_rejected(self):
        for flag in (subprocess.DETACHED_PROCESS, subprocess.CREATE_NEW_CONSOLE):
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                run_background(['unused'], creationflags=flag)

    def test_gui_spawn_does_not_request_console(self):
        with patch('subprocess.Popen') as spawn:
            WindowsOpener._spawn(['example.exe'])
        self.assertEqual(spawn.call_args.kwargs['creationflags'], subprocess.CREATE_NO_WINDOW)

    def test_cli_from_detached_host_has_no_console(self):
        probe = "import ctypes,json; print(json.dumps({'schema_version':1,'data':{'console':bool(ctypes.windll.kernel32.GetConsoleWindow())}}))"
        worker = f"""
import json,sys
from unittest.mock import patch
from workbench.dmy import run_dmy
with patch('workbench.dmy.resolve_command', return_value=([sys.executable, '-c', {probe!r}], 'probe')):
    print(json.dumps(run_dmy([], workspace='.', timeout=10)))
"""
        result = subprocess.run([sys.executable, '-c', worker],
                                cwd=Path(__file__).resolve().parents[1],
                                creationflags=subprocess.DETACHED_PROCESS,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)['console'], '后台 CLI 创建了控制台')

    def test_obsidian_uses_uri_shell_dispatch(self):
        opener = WindowsOpener({'apps': {'obsidian_vault_path': 'vault'}})
        with patch('os.path.exists', return_value=True), patch('os.startfile') as start, patch('subprocess.Popen') as spawn:
            opener.obsidian_open('C:/笔记/a & b.md')
        start.assert_called_once_with('obsidian://open?path=C%3A%2F%E7%AC%94%E8%AE%B0%2Fa%20%26%20b.md')
        spawn.assert_not_called()

    def test_obsidian_dispatch_error_is_reported(self):
        opener = WindowsOpener({'apps': {'obsidian_vault_path': 'vault'}})
        with patch('os.path.exists', return_value=True), patch('os.startfile', side_effect=OSError('missing handler')):
            with self.assertRaises(OpenFailed):
                opener.obsidian_open('C:/a.md')
