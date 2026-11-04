"""元数据读取真实检出提交，缺少 Git 时保持可用。"""
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from workbench.release_info import release_info


class ReleaseInfoTests(unittest.TestCase):
    def test_source_commit_and_location(self):
        sha = "a" * 40
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "apps/workbench"
            source.mkdir(parents=True)
            (source / "pyproject.toml").touch()
            (root / ".git").mkdir()
            with patch("workbench.release_info.__file__", str(source / "workbench/release_info.py")), patch("workbench.release_info.subprocess.run", return_value=subprocess.CompletedProcess([], 0, sha + "\n")):
                result = release_info()
        self.assertEqual(result["sha"], sha)
        self.assertEqual(result["short_sha"], "aaaaaaa")
        self.assertEqual(result["source"], "source-checkout")
        self.assertIn(result["source_path"], result["install_source"])

    def test_git_unavailable_or_not_a_repository(self):
        with patch("workbench.release_info.subprocess.run", side_effect=OSError("git unavailable")):
            self.assertIsNone(release_info()["sha"])
        with patch("workbench.release_info.subprocess.run", return_value=subprocess.CompletedProcess([], 128, "")):
            self.assertIsNone(release_info()["sha"])

    def test_installed_package_never_reads_surrounding_git_repository(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".git").mkdir()
            module = root / "env/Lib/site-packages/workbench/release_info.py"
            with patch("workbench.release_info.__file__", str(module)), patch("workbench.release_info.subprocess.run") as git:
                result = release_info()
        git.assert_not_called()
        self.assertEqual(result["source"], "wheel")
        self.assertIsNone(result["sha"])
