"""macOS opening uses argv, preserving Unicode and shell metacharacters."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from workbench.macos import MacOpener
from workbench.ports import AppUnavailable

class MacOpenerTest(unittest.TestCase):
    def test_finder_paths_remain_single_literal_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'中文 空格 $(ignored) [1].txt';target.write_text('text')
            opener=MacOpener({'apps':{}})
            with patch('workbench.macos.subprocess.run') as run:
                opener.explorer_reveal(str(target))
                self.assertEqual(run.call_args.args[0], ['/usr/bin/open','-R','--',str(target)])
                opener.system_open(str(target))
                self.assertEqual(run.call_args.args[0], ['/usr/bin/open','--',str(target)])
                self.assertNotIn('shell', run.call_args.kwargs)

    def test_script_and_executable_default_open_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            opener=MacOpener({'apps':{}})
            script=Path(directory)/'payload.sh';script.write_text('synthetic')
            binary=Path(directory)/'program';binary.write_text('synthetic');binary.chmod(0o700)
            for path in (script,binary,Path(directory)):
                with self.assertRaises(AppUnavailable): opener.system_open(str(path))

    def test_missing_optional_editor_reports_capability(self):
        with patch('workbench.macos._find_app', return_value=None), patch('workbench.macos.shutil.which',return_value=None):
            opener=MacOpener({'apps':{}})
        self.assertFalse(opener.probe()['vscode']['available'])
        with self.assertRaises(AppUnavailable): opener.vscode_open('/missing')
