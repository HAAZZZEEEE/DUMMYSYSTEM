"""Git 历史、忽略文件和精确复核的公开源码审计回归。"""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("audit_public", Path(__file__).resolve().parents[1] / "scripts/audit_public.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class PublicAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "src"
        self.root.mkdir()
        self.deny = self.base / "deny.json"
        self.deny.write_text(json.dumps(["synthetic-value-42"]), encoding="utf-8")
        self.git("init", "--quiet", "--template=", "--initial-branch=main")

    def git(self, *args):
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("GIT_AUTHOR_", "GIT_COMMITTER_"))}
        return subprocess.check_output(
            ["git", "-c", "user.name=Example", "-c", "user.email=example@example.invalid",
             "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
            cwd=self.root, env=env, stderr=subprocess.PIPE)

    def commit(self):
        self.git("add", "--", ".")
        self.git("commit", "--quiet", "--no-gpg-sign", "-m", "example")

    def scan(self, extra=()):
        report = self.base / "report.json"
        with contextlib.redirect_stdout(io.StringIO()):
            exit_code = audit.main(["--source", str(self.root), "--deny-file", str(self.deny),
                                    "--report", str(report), *extra])
        return exit_code, json.loads(report.read_text(encoding="utf-8"))

    def test_unreachable_commit_is_not_hidden_by_clean_working_tree(self):
        (self.root / "README.md").write_text("synthetic-value-42", encoding="utf-8")
        self.commit()
        self.git("checkout", "--orphan", "clean")
        (self.root / "README.md").write_text("clean", encoding="utf-8")
        self.commit()
        self.git("branch", "-D", "main")
        code, report = self.scan(["--git-history"])
        self.assertEqual(code, 1)
        self.assertTrue(any(f["rule"] == "private_deny_token" and f["path"].startswith("git:") for f in report["unresolved"]))

    def test_ignored_files_are_still_checked(self):
        (self.root / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
        (self.root / "ignored.txt").write_text("synthetic-value-42", encoding="utf-8")
        self.commit()
        code, report = self.scan(["--git-history"])
        self.assertEqual(code, 1)
        self.assertTrue(any(f.get("path") == "ignored.txt" for f in report["unresolved"]))

    def test_review_is_bound_to_bytes_for_worktree_and_git(self):
        source = self.root / "README.md"
        source.write_text("https://" + "example:fixture@127.0.0.1", encoding="utf-8")
        self.commit()
        reviewed = self.base / "reviewed.json"
        reviewed.write_text(json.dumps([dict(path="README.md", line=1, rule="internal_service",
            sha256=hashlib.sha256(source.read_bytes()).hexdigest(), reason="synthetic fixture")]), encoding="utf-8")
        extra = ["--git-history", "--reviewed", str(reviewed)]
        code, report = self.scan(extra)
        self.assertEqual(code, 0)
        self.assertEqual(len(report["reviewed"]), 2)
        source.write_text(source.read_text(encoding="utf-8") + " changed", encoding="utf-8")
        self.assertEqual(self.scan(extra)[0], 1)

    def test_git_metadata_requires_explicit_history_audit(self):
        (self.root / "README.md").write_text("example", encoding="utf-8")
        self.commit()
        self.assertEqual(self.scan()[0], 1)
        self.assertEqual(self.scan(["--git-history"])[0], 0)

