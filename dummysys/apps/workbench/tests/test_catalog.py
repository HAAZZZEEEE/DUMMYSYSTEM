"""Catalog：项目发现、根解析、目标解析与目录列表。"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from workbench.catalog import (
    BlockedLink,
    Catalog,
    CatalogError,
    InvalidTarget,
    PathOutsideRoot,
    ProjectNotFound,
    RootNotFound,
    StaleCursor,
)
from tests.helpers import build_workspace, write_json

PID_A = "11111111-1111-4111-8111-111111111111"
PID_B = "22222222-2222-4222-8222-222222222222"
PID_C = "33333333-3333-4333-8333-333333333333"
PID_DUP = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"


def _catalog(ws: Path) -> Catalog:
    return Catalog({"workspace_root": ws, "task_root": ws / "task", "apps": {}})


def _create_dir_link(link: Path, target: Path) -> bool:
    """优先符号链接；无权限时退回目录联接（junction），两者都可用于越界测试。"""
    try:
        os.symlink(str(target), str(link), target_is_directory=True)
        return True
    except OSError:
        pass
    import subprocess
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                            capture_output=True)
    return result.returncode == 0 and link.exists()


class ProjectDiscoveryTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _ws(self, projects):
        return build_workspace(self.root, projects)

    def test_basic_discovery(self):
        ws = self._ws({
            "alpha": {"project_id": PID_A, "docs_root": "d/vault-a", "resource_root": "r/alpha",
                      "title": "项目甲", "aliases": ["甲甲", "A-A"]},
            "beta": {"project_id": PID_B, "docs_root": "d/vault-b", "resource_root": "r/beta"},
        })
        result = _catalog(ws).list_projects()
        self.assertEqual(result["diagnostics"], [])
        self.assertEqual([p["project_id"] for p in result["projects"]], [PID_A, PID_B])
        self.assertEqual(result["projects"][0]["title"], "项目甲")
        self.assertEqual(result["projects"][0]["aliases"], ["甲甲", "A-A"])
        self.assertEqual(result["projects"][0]["archived"], False)

    def test_query_matches_title_and_alias(self):
        ws = self._ws({
            "alpha": {"project_id": PID_A, "docs_root": "d/a", "resource_root": "r/a",
                      "title": "工作台", "aliases": ["wb"]},
            "beta": {"project_id": PID_B, "docs_root": "d/b", "resource_root": "r/b",
                     "title": "量化", "aliases": []},
        })
        catalog = _catalog(ws)
        self.assertEqual([p["project_id"] for p in catalog.list_projects("wb")["projects"]], [PID_A])
        self.assertEqual([p["project_id"] for p in catalog.list_projects("工作")["projects"]], [PID_A])
        self.assertEqual(catalog.list_projects("不存在")["projects"], [])

    def test_archived_hidden_by_default(self):
        ws = self._ws({
            "alpha": {"project_id": PID_A, "docs_root": "d/a", "resource_root": "r/a"},
            "old": {"project_id": PID_B, "docs_root": "d/b", "resource_root": "r/b",
                    "status": "archived"},
        })
        catalog = _catalog(ws)
        self.assertEqual([p["project_id"] for p in catalog.list_projects()["projects"]], [PID_A])
        self.assertEqual(len(catalog.list_projects(None, include_archived=True)["projects"]), 2)

    def test_duplicate_id_is_diagnostic_not_fatal(self):
        ws = self._ws({
            "first": {"project_id": PID_DUP, "docs_root": "d/f", "resource_root": "r/f"},
            "second": {"project_id": PID_DUP, "docs_root": "d/s", "resource_root": "r/s"},
        })
        result = _catalog(ws).list_projects()
        self.assertEqual(len(result["projects"]), 1)
        self.assertEqual(len(result["diagnostics"]), 1)
        self.assertIn("重复", result["diagnostics"][0]["message"])

    def test_broken_metadata_produces_diagnostics(self):
        ws = self._ws({
            "good": {"project_id": PID_A, "docs_root": "d/g", "resource_root": "r/g"},
        })
        # 缺 README
        write_json(ws / "runtime/project_src/noreadme/project.json",
                   {"project_id": "no-readme", "docs_root": "d/nr", "resource_root": "r/nr"})
        # README 无 project_id
        (ws / "d/nid").mkdir(parents=True)
        (ws / "d/nid/README.md").write_text("# 无 id\n", encoding="utf-8")
        write_json(ws / "runtime/project_src/noid/project.json",
                   {"project_id": "no-id", "docs_root": "d/nid", "resource_root": "r/nid"})
        # ID 不匹配
        (ws / "d/mismatch").mkdir(parents=True)
        (ws / "d/mismatch/README.md").write_text("---\nproject_id: other\n---\n# x\n", encoding="utf-8")
        write_json(ws / "runtime/project_src/mismatch/project.json",
                   {"project_id": "mismatch", "docs_root": "d/mismatch", "resource_root": "r/m"})
        # 缺 docs_root
        write_json(ws / "runtime/project_src/nodocs/project.json",
                   {"project_id": "no-docs", "resource_root": "r/nd"})
        # 缺 resource_root
        (ws / "d/nores").mkdir(parents=True)
        (ws / "d/nores/README.md").write_text("---\nproject_id: no-res\n---\n# nores\n", encoding="utf-8")
        write_json(ws / "runtime/project_src/nores/project.json",
                   {"project_id": "no-res", "docs_root": "d/nores"})
        # README Properties 是非法 YAML
        (ws / "d/badyaml").mkdir(parents=True)
        (ws / "d/badyaml/README.md").write_text("---\nproject_id: [unclosed\n---\n# y\n", encoding="utf-8")
        write_json(ws / "runtime/project_src/badyaml/project.json",
                   {"project_id": "bad-yaml", "docs_root": "d/badyaml", "resource_root": "r/by"})
        result = _catalog(ws).list_projects()
        self.assertEqual(len(result["projects"]), 1)
        messages = " | ".join(d["message"] for d in result["diagnostics"])
        self.assertIn("缺少 README", messages)
        self.assertIn("project_id", messages)
        self.assertIn("ID 不匹配", messages)
        self.assertIn("docs_root", messages)
        self.assertIn("resource_root", messages)
        self.assertIn("Properties 解析失败", messages)

    def test_empty_project_src(self):
        ws = self.root / "empty-ws"
        (ws / "runtime").mkdir(parents=True)
        result = _catalog(ws).list_projects()
        self.assertEqual(result["projects"], [])
        self.assertEqual(result["diagnostics"], [])


class RootsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = self.root / "repo"
        (self.repo / "apps" / "workbench").mkdir(parents=True)
        (self.repo / "packages" / "core").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _ws(self, repositories):
        return build_workspace(self.root, {
            "proj": {"project_id": PID_A, "docs_root": "d/vault", "resource_root": "r/proj",
                     "repositories": repositories},
        }, checkouts={"dummysys": {"path": str(self.repo)}})

    def test_roots_include_docs_resources_and_repo(self):
        ws = self._ws([{"repo_id": "dummysys", "paths": ["apps/workbench"]}])
        roots = _catalog(ws).list_roots(PID_A)["roots"]
        ids = [r["root_id"] for r in roots]
        self.assertEqual(ids, ["docs", "resources", "repo:dummysys"])
        repo_root = next(r for r in roots if r["root_id"] == "repo:dummysys")
        self.assertEqual(Path(repo_root["path"]).resolve(), (self.repo / "apps" / "workbench").resolve())

    def test_multi_subpath_repo_keeps_subpaths(self):
        ws = self._ws([{"repo_id": "dummysys", "paths": ["apps/workbench", "packages/core"]}])
        roots = _catalog(ws).list_roots(PID_A)["roots"]
        repo_root = next(r for r in roots if r["kind"] == "repo")
        self.assertEqual(repo_root["path"], self.repo.resolve().as_posix())
        self.assertEqual(set(repo_root["subpaths"]), {"apps/workbench", "packages/core"})

    def test_unknown_project(self):
        ws = self._ws([])
        with self.assertRaises(ProjectNotFound):
            _catalog(ws).list_roots("nope")

    def test_unbound_repo_is_diagnostic_in_roots(self):
        ws = self._ws([{"repo_id": "missing-repo", "paths": ["apps"]}])
        roots = _catalog(ws).list_roots(PID_A)["roots"]
        self.assertEqual([r["root_id"] for r in roots], ["docs", "resources"])

    def test_empty_repositories(self):
        ws = self._ws([])
        roots = _catalog(ws).list_roots(PID_A)["roots"]
        self.assertEqual([r["root_id"] for r in roots], ["docs", "resources"])


class ResolveTargetTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ws = build_workspace(self.root, {
            "proj": {"project_id": PID_A, "docs_root": "d/vault", "resource_root": "r/proj",
                     "repositories": []},
        })
        self.docs = self.ws / "d" / "vault"
        self.catalog = _catalog(self.ws)

    def tearDown(self):
        self._tmp.cleanup()

    def _target(self, rel: str = "") -> dict:
        return {"project_id": PID_A, "root_id": "docs", "relative_path": rel}

    def test_special_character_paths(self):
        names = ["中文 文件.txt", "方括号[1].md", "井号#文件.md", "与&符号.txt", "普通.py"]
        for name in names:
            (self.docs / name).write_text("x", encoding="utf-8")
            resolved = self.catalog.resolve_target(self._target(name))
            self.assertEqual(resolved["kind"], "file")
            self.assertEqual(Path(resolved["path"]).name, name)

    def test_directory_with_spaces(self):
        (self.docs / "子 目录").mkdir()
        resolved = self.catalog.resolve_target(self._target("子 目录"))
        self.assertEqual(resolved["kind"], "dir")

    def test_root_itself(self):
        resolved = self.catalog.resolve_target(self._target(""))
        self.assertEqual(resolved["kind"], "dir")
        self.assertEqual(resolved["relative_path"], "")

    def test_missing_path_kind(self):
        resolved = self.catalog.resolve_target(self._target("不存在.txt"))
        self.assertEqual(resolved["kind"], "missing")

    def test_absolute_path_rejected(self):
        for bad in (r"C:\Windows\win.ini", "/etc/passwd", r"\\server\share", "C:/foo"):
            with self.assertRaises(InvalidTarget, msg=bad):
                self.catalog.resolve_target(self._target(bad))

    def test_traversal_rejected(self):
        for bad in ("../..", "a/../b", "a/./b", "..", "a//b", "/abs"):
            with self.assertRaises(InvalidTarget, msg=bad):
                self.catalog.resolve_target(self._target(bad))

    def test_nul_and_ads_rejected(self):
        with self.assertRaises(InvalidTarget):
            self.catalog.resolve_target(self._target("a\x00b"))
        with self.assertRaises(InvalidTarget):
            self.catalog.resolve_target(self._target("file.txt:stream"))

    def test_backslash_normalized(self):
        (self.docs / "a" / "b.txt").parent.mkdir(parents=True)
        (self.docs / "a" / "b.txt").write_text("x", encoding="utf-8")
        resolved = self.catalog.resolve_target(self._target(r"a\b.txt"))
        self.assertEqual(resolved["kind"], "file")

    def test_missing_project_and_root(self):
        with self.assertRaises(ProjectNotFound):
            self.catalog.resolve_target({"project_id": "x", "root_id": "docs", "relative_path": ""})
        with self.assertRaises(RootNotFound):
            self.catalog.resolve_target({"project_id": PID_A, "root_id": "nope", "relative_path": ""})

    def test_missing_target_fields(self):
        with self.assertRaises(InvalidTarget):
            self.catalog.resolve_target({"project_id": PID_A})
        with self.assertRaises(InvalidTarget):
            self.catalog.resolve_target({"root_id": "docs", "relative_path": ""})

    def test_link_escape_blocked(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("s", encoding="utf-8")
        link = self.docs / "escape-link"
        if not _create_dir_link(link, outside):
            self.skipTest("无法创建符号链接或目录联接")
        self.addCleanup(lambda: (link.unlink() if link.exists() else None))
        with self.assertRaises(BlockedLink):
            self.catalog.resolve_target(self._target("escape-link"))
        with self.assertRaises(BlockedLink):
            self.catalog.resolve_target(self._target("escape-link/secret.txt"))

    def test_link_inside_stays_allowed(self):
        inner = self.docs / "inner"
        inner.mkdir()
        (inner / "ok.txt").write_text("o", encoding="utf-8")
        link = self.docs / "inner-link"
        if not _create_dir_link(link, inner):
            self.skipTest("无法创建符号链接或目录联接")
        self.addCleanup(lambda: (link.unlink() if link.exists() else None))
        resolved = self.catalog.resolve_target(self._target("inner-link/ok.txt"))
        self.assertEqual(resolved["kind"], "file")

    def test_link_flagged_in_listing(self):
        inner = self.docs / "inner"
        inner.mkdir()
        link = self.docs / "linked-dir"
        if not _create_dir_link(link, inner):
            self.skipTest("无法创建符号链接或目录联接")
        self.addCleanup(lambda: (link.unlink() if link.exists() else None))
        result = self.catalog.list_directory(self._target(""))
        entry = next(e for e in result["entries"] if e["name"] == "linked-dir")
        self.assertTrue(entry["is_link"])


class SubpathsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = self.root / "repo"
        (self.repo / "apps" / "workbench").mkdir(parents=True)
        (self.repo / "packages" / "core").mkdir(parents=True)
        (self.repo / "other").mkdir(parents=True)
        (self.repo / "apps" / "workbench" / "README.md").write_text("r", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _make(self, paths: list[str]):
        ws = build_workspace(self.root, {
            "proj": {"project_id": PID_A, "docs_root": "d/vault", "resource_root": "r/proj",
                     "repositories": [{"repo_id": "dummysys", "paths": paths}]},
        }, checkouts={"dummysys": {"path": str(self.repo)}})
        return _catalog(ws)

    def _target(self, rel: str = "") -> dict:
        return {"project_id": PID_A, "root_id": "repo:dummysys", "relative_path": rel}

    def test_within_subpath_allowed(self):
        catalog = self._make(["apps/workbench", "packages/core"])
        resolved = catalog.resolve_target(self._target("apps/workbench/README.md"))
        self.assertEqual(resolved["kind"], "file")

    def test_outside_subpath_blocked(self):
        catalog = self._make(["apps/workbench", "packages/core"])
        # 越界相对路径先被通用校验拒绝
        with self.assertRaises(InvalidTarget):
            catalog.resolve_target(self._target("../other/x.txt"))
        # 未越界但超出登记子路径
        with self.assertRaises(PathOutsideRoot):
            catalog.resolve_target(self._target("other/x.txt"))
        with self.assertRaises(PathOutsideRoot):
            catalog.resolve_target(self._target("apps/secret.txt"))
        with self.assertRaises(PathOutsideRoot):
            catalog.resolve_target(self._target("README.md"))

    def test_single_path_repo_root_is_subpath(self):
        # 单子路径仓库：根即子路径，允许其内部任意相对路径
        catalog = self._make(["apps/workbench"])
        resolved = catalog.resolve_target(self._target("README.md"))
        self.assertEqual(resolved["kind"], "file")
        missing = catalog.resolve_target(self._target("other/x.txt"))
        self.assertEqual(missing["kind"], "missing")


class ListDirectoryTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ws = build_workspace(self.root, {
            "proj": {"project_id": PID_A, "docs_root": "d/vault", "resource_root": "r/proj",
                     "repositories": []},
        })
        self.docs = self.ws / "d" / "vault"
        self.catalog = _catalog(self.ws)
        self.target = {"project_id": PID_A, "root_id": "docs", "relative_path": ""}

    def tearDown(self):
        self._tmp.cleanup()

    def _make(self, names: list[str], dirs: list[str] | None = None):
        for d in dirs or []:
            (self.docs / d).mkdir(parents=True)
        for n in names:
            (self.docs / n).write_text("x", encoding="utf-8")

    def test_entries_sorted_dirs_first(self):
        self._make(["b.txt", "a.txt"], dirs=["z-dir", "a-dir"])
        result = self.catalog.list_directory(self.target)
        names = [e["name"] for e in result["entries"]]
        # README.md 由夹具写入 docs 根，属正常文件
        self.assertEqual(names, ["a-dir", "z-dir", "a.txt", "b.txt", "README.md"])
        self.assertIsNone(result["next_cursor"])
        self.assertIn("snapshot_id", result)
        self.assertEqual(result["target"]["relative_path"], "")

    def test_project_content_directories_do_not_become_execution_records(self):
        self._make([], dirs=['文档', '治理', '模板', '专题'])
        for name in ('文档', '治理', '模板', '专题'):
            (self.docs / name / 'README.md').write_text('# 长期可读内容\n', encoding='utf-8')
        rows = self.catalog.list_directory(self.target)['entries']
        self.assertTrue({'文档', '治理', '模板', '专题'}.issubset({r['name'] for r in rows}))
        self.assertEqual(self.catalog.list_project_nav(PID_A)['tasks'], [])
        self.assertEqual(len(self.catalog.list_projects()['projects']), 1)
        self.assertFalse((self.ws / 'r/proj/专题').exists())

    def test_entries_natural_numeric_order(self):
        # 任务目录序号按数值比较：2 在 11 之前，不能得到 11/12/13/1 的字符串序。
        self._make([], dirs=["[task 1]甲", "[task 11]乙", "[task 12]丙", "[task 2]丁"])
        result = self.catalog.list_directory(self.target)
        names = [e["name"] for e in result["entries"] if e["name"].startswith("[task")]
        self.assertEqual(names, ["[task 1]甲", "[task 2]丁", "[task 11]乙", "[task 12]丙"])

    def test_filter_case_insensitive(self):
        self._make(["Alpha.md", "beta.md", "gamma.txt"])
        result = self.catalog.list_directory(self.target, name_filter="alpha")
        self.assertEqual([e["name"] for e in result["entries"]], ["Alpha.md"])

    def test_pagination_with_cursor(self):
        # 24 个文件 + 夹具 README.md = 25 项；每页 10 → 10/10/5
        self._make([f"f{i:03}.txt" for i in range(24)])
        page1 = self.catalog.list_directory(self.target, limit=10)
        self.assertEqual(len(page1["entries"]), 10)
        cursor = page1["next_cursor"]
        self.assertIsNotNone(cursor)
        page2 = self.catalog.list_directory(self.target, cursor=cursor, limit=10)
        self.assertEqual(len(page2["entries"]), 10)
        self.assertEqual(page2["entries"][0]["name"], "f010.txt")
        self.assertNotEqual(page2["entries"][0]["name"], page1["entries"][0]["name"])
        page3 = self.catalog.list_directory(self.target, cursor=page2["next_cursor"], limit=10)
        self.assertEqual(len(page3["entries"]), 5)
        self.assertEqual(page3["entries"][0]["name"], "f020.txt")
        self.assertIsNone(page3["next_cursor"])

    def test_modified_sort_applies_before_pagination(self):
        self._make(["z-old.txt", "a-new.txt", "m-middle.txt"])
        for name, stamp in (("z-old.txt", 1600000000), ("m-middle.txt", 1700000000),
                            ("a-new.txt", 1800000000)):
            os.utime(self.docs / name, (stamp, stamp))
        first = self.catalog.list_directory(self.target, sort="modified_asc", name_filter=".txt", limit=1)
        self.assertEqual([e["name"] for e in first["entries"]], ["z-old.txt"])
        second = self.catalog.list_directory(self.target, sort="modified_asc", name_filter=".txt",
                                             limit=1, cursor=first["next_cursor"])
        self.assertEqual([e["name"] for e in second["entries"]], ["m-middle.txt"])
        newest = self.catalog.list_directory(self.target, sort="modified", name_filter=".txt", limit=1)
        self.assertEqual([e["name"] for e in newest["entries"]], ["a-new.txt"])
        with self.assertRaises(StaleCursor):
            self.catalog.list_directory(self.target, sort="modified", name_filter=".txt",
                                        limit=1, cursor=first["next_cursor"])

    def test_stale_cursor_snapshot_mismatch(self):
        self._make(["a.txt"])
        page1 = self.catalog.list_directory(self.target, limit=1)
        cursor = page1["next_cursor"]
        stale = {**cursor, "snapshot_id": "wrong"}
        with self.assertRaises(StaleCursor):
            self.catalog.list_directory(self.target, cursor=stale)

    def test_cursor_target_mismatch(self):
        self._make(["a.txt"])
        page1 = self.catalog.list_directory(self.target, limit=1)
        cursor = {**page1["next_cursor"], "project_id": "other"}
        with self.assertRaises(StaleCursor):
            self.catalog.list_directory(self.target, cursor=cursor)

    def test_limit_clamped_to_max(self):
        self._make([f"f{i:03}.txt" for i in range(30)])
        result = self.catalog.list_directory(self.target, limit=9999)
        self.assertLessEqual(len(result["entries"]), 500)

    def test_target_not_directory(self):
        self._make(["a.txt"])
        with self.assertRaises(CatalogError):
            self.catalog.list_directory(
                {"project_id": PID_A, "root_id": "docs", "relative_path": "a.txt"})


if __name__ == "__main__":
    unittest.main()
