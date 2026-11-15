"""目录版本、授权范围和治理格式的公共接口回归。"""
from __future__ import annotations

import tempfile
import unittest
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from pathlib import Path
from dummysys_core.operations import native_path

from tests.helpers import build_workspace, write_json
from tests.test_catalog import _create_dir_link
from workbench.catalog import Catalog, CatalogError, InvalidTarget, SnapshotStore, StaleCursor


class CatalogRegressionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.ws = build_workspace(self.base, {
            "project": {"project_id": "p", "docs_root": "docs", "resource_root": "resources"},
        })
        self.docs = self.ws / "docs"
        self.catalog = Catalog({"workspace_root": self.ws})
        self.target = {"project_id": "p", "root_id": "docs", "relative_path": ""}

    def test_broken_project_json_and_yaml_are_isolated_diagnostics(self):
        for name, content in {"bad-json": "{", "list-json": "[]", "no-id": "{}",
                              "bad-id": '{"project_id": ["x"]}'}.items():
            path = self.ws / "runtime/project_src" / name / "project.json"
            path.parent.mkdir(parents=True)
            path.write_text(content, encoding="utf-8")
        write_json(self.ws / "runtime/project_src/bad-yaml/project.json", {
            "project_id": "broken", "docs_root": "bad-yaml", "resource_root": "r"})
        (self.ws / "bad-yaml").mkdir()
        (self.ws / "bad-yaml/README.md").write_text("---\nproject_id: [\n---\n", encoding="utf-8")
        result = self.catalog.list_projects()
        self.assertEqual([p["project_id"] for p in result["projects"]], ["p"])
        self.assertEqual({d["project"] for d in result["diagnostics"]},
                         {"bad-json", "list-json", "no-id", "bad-id", "bad-yaml"})
        self.assertTrue(all(d["message"] for d in result["diagnostics"]))

    def test_insert_delete_invalidate_cursor_and_change_snapshot(self):
        for name in ("a.txt", "b.txt", "c.txt"):
            (self.docs / name).write_text(name, encoding="utf-8")
        first = self.catalog.list_directory(self.target, limit=1)
        (self.docs / "0.txt").write_text("new", encoding="utf-8")
        with self.assertRaises(StaleCursor):
            self.catalog.list_directory(self.target, cursor=first["next_cursor"])
        second = self.catalog.list_directory(self.target, limit=1)
        self.assertNotEqual(first["snapshot_id"], second["snapshot_id"])
        (self.docs / "b.txt").unlink()
        with self.assertRaises(StaleCursor):
            self.catalog.list_directory(self.target, cursor=second["next_cursor"])

    def test_sort_by_file_count_uses_all_directories_before_paging(self):
        (self.docs / "a-empty").mkdir()
        (self.docs / "b-single" / "nested").mkdir(parents=True)
        (self.docs / "c-two").mkdir()
        (self.docs / "b-single" / "one.txt").touch()
        (self.docs / "b-single" / "nested" / "ignored.txt").touch()
        for name in ("one.txt", "two.txt"):
            (self.docs / "c-two" / name).touch()
        first = self.catalog.list_directory(self.target, sort="file_count_desc", limit=1)
        second = self.catalog.list_directory(
            self.target, sort="file_count_desc", limit=1, cursor=first["next_cursor"])
        ascending = self.catalog.list_directory(self.target, sort="file_count", limit=1)
        self.assertEqual((first["entries"][0]["name"], first["entries"][0]["file_count"]), ("c-two", 2))
        self.assertEqual((second["entries"][0]["name"], second["entries"][0]["file_count"]), ("b-single", 1))
        self.assertEqual(ascending["entries"][0]["file_count"], 0)

    def bind_repo(self, paths=None, legacy=False):
        self.repo = self.base / "repo"
        for name in ("apps/workbench", "apps/private", "packages/core", "private"):
            (self.repo / name).mkdir(parents=True, exist_ok=True)
        binding = {"project_id": "p", "docs_root": "docs", "resource_root": "resources",
                   "repositories": ([{"role": "源码", "path": str(self.repo)}] if legacy else
                                    [{"repo_id": "code", "paths": paths}])}
        write_json(self.ws / "runtime/project_src/project/project.json", binding)
        write_json(self.ws / "runtime/state/workspace/repositories.json",
                   {"checkouts": {"code": {"path": str(self.repo)}}})
        return {**self.target, "root_id": "repo:code"}

    def link(self, relative, destination):
        link = self.repo / relative
        if not _create_dir_link(link, destination):
            self.skipTest("无法创建目录链接")
        def remove():
            if link.is_symlink():
                link.unlink()
            elif link.is_junction():
                link.rmdir()
        self.addCleanup(remove)

    def test_legacy_role_path_preserves_path_digest_identity(self):
        self.bind_repo(legacy=True)
        roots = self.catalog.list_roots("p")["roots"]
        self.assertEqual(len(roots), 3)
        expected = hashlib.sha256(os.path.normcase(self.repo.resolve().as_posix()).encode()).hexdigest()[:12]
        self.assertEqual(roots[-1]["root_id"], "repo:" + expected)
        self.assertIn("源码", roots[-1]["label"])
        self.assertEqual(roots[-1]["native_path"], str(self.repo.resolve()))

    def test_explicit_refresh_reloads_checkout_and_invalidates_cursor(self):
        target = self.bind_repo(["."])
        first = self.catalog.list_directory(target, limit=1)
        replacement = self.base / "new-repo"
        replacement.mkdir()
        (replacement / "new.txt").write_text("x", encoding="utf-8")
        write_json(self.ws / "runtime/state/workspace/repositories.json",
                   {"checkouts": {"code": {"path": str(replacement)}}})
        self.assertEqual(Path(self.catalog.resolve_target(target)["path"]), self.repo)
        self.catalog.refresh()
        self.assertEqual(Path(self.catalog.resolve_target(target)["path"]), replacement)
        with self.assertRaises(StaleCursor):
            self.catalog.list_directory(target, cursor=first["next_cursor"])

    def test_multiple_subpaths_only_expose_navigation_branches(self):
        target = self.bind_repo(["apps/workbench", "packages/core"])
        for rel, expected in (("", ["apps", "packages"]), ("apps", ["workbench"]),
                              ("packages", ["core"])):
            with self.subTest(rel=rel):
                page = self.catalog.list_directory({**target, "relative_path": rel}, include_file_counts=True)
                self.assertEqual([e["name"] for e in page["entries"]], expected)
                self.assertTrue(page["target"]["navigation_only"])
                self.assertTrue(page["target"]["available"])
                self.assertEqual(page["target"]["native_path"], str(Path(page["target"]["path"])))
                for entry in page["entries"]:
                    self.assertEqual(entry['file_count'], None if entry['navigation_only'] else 0)
        leaf = self.catalog.resolve_target({**target, "relative_path": "apps/workbench"})
        self.assertFalse(leaf["navigation_only"])
        self.assertEqual(leaf["native_path"], str(self.repo / "apps/workbench"))

    def test_real_subpath_escape_and_ancestor_links_are_blocked_in_entries(self):
        target = self.bind_repo(["apps/workbench", "packages/core"])
        self.link("apps/workbench/escape", self.repo / "private")
        self.link("apps/workbench/back", self.repo / "apps/workbench")
        self.link("apps/workbench/allowed", self.repo / "packages/core")
        page = self.catalog.list_directory({**target, "relative_path": "apps/workbench"}, include_file_counts=True)
        entries = {e["name"]: e for e in page["entries"]}
        self.assertTrue(all(entry['file_count'] is None for entry in entries.values()))
        for name in ("escape", "back"):
            self.assertTrue(entries[name]["is_link"])
            self.assertFalse(entries[name]["available"])
            self.assertIsNone(entries[name]["native_path"])
            self.assertTrue(entries[name]["reason"])
            with self.assertRaises(CatalogError) as raised:
                self.catalog.resolve_target({**target, "relative_path": "apps/workbench/" + name})
            self.assertIn("TargetForbidden", [cls.__name__ for cls in type(raised.exception).__mro__])
        self.assertTrue(entries["allowed"]["available"])
        self.assertEqual(entries["allowed"]["canonical_path"], (self.repo / "packages/core").as_posix())

    def test_missing_resolves_but_directory_listing_is_not_found(self):
        target = {**self.target, "relative_path": "missing"}
        resolved = self.catalog.resolve_target(target)
        self.assertEqual(resolved["kind"], "missing")
        self.assertFalse(resolved["available"])
        with self.assertRaises(CatalogError) as raised:
            self.catalog.list_directory(target)
        self.assertIn("TargetNotFound", [cls.__name__ for cls in type(raised.exception).__mro__])

    def test_cursor_bound_to_filter_and_directory(self):
        for name in ("a.txt", "b.txt", "c.md"):
            (self.docs / name).write_text(name, encoding="utf-8")
        (self.docs / "child").mkdir()
        (self.docs / "child/a.txt").write_text("x", encoding="utf-8")
        first = self.catalog.list_directory(self.target, name_filter=".TXT", limit=1)
        second = self.catalog.list_directory(self.target, name_filter=".txt", cursor=first["next_cursor"])
        self.assertEqual([e["name"] for e in second["entries"]], ["b.txt"])
        for target, filter_value in ((self.target, ".md"), (self.target, None),
                                     ({**self.target, "relative_path": "child"}, ".txt")):
            with self.assertRaises(StaleCursor):
                self.catalog.list_directory(target, name_filter=filter_value, cursor=first["next_cursor"])

    def test_expiration_uses_monotonic_time_and_does_not_extend_on_access(self):
        now = [100.0]
        store = SnapshotStore(ttl=5, clock=lambda: now[0])
        catalog = Catalog({"workspace_root": self.ws}, store)
        (self.docs / "a.txt").write_text("x", encoding="utf-8")
        first = catalog.list_directory(self.target, limit=1)
        now[0] = 104.0
        second = catalog.list_directory(self.target, cursor=first["next_cursor"])
        self.assertEqual(first["snapshot_id"], second["snapshot_id"])
        now[0] = 105.0
        with self.assertRaises(StaleCursor):
            catalog.list_directory(self.target, cursor=first["next_cursor"])
        fresh = catalog.list_directory(self.target)
        self.assertNotEqual(first["snapshot_id"], fresh["snapshot_id"])

    def test_directory_metadata_and_unfiltered_changes_invalidate_cursor(self):
        for name in ("a.txt", "b.txt", "hidden.md"):
            (self.docs / name).write_text("x", encoding="utf-8")
        first = self.catalog.list_directory(self.target, name_filter=".txt", limit=1)
        changed = self.docs / "hidden.md"
        old = changed.stat()
        os.utime(changed, ns=(old.st_atime_ns, old.st_mtime_ns + 1000000))
        with self.assertRaises(StaleCursor):
            self.catalog.list_directory(self.target, name_filter=".txt", cursor=first["next_cursor"])
        fresh = self.catalog.list_directory(self.target, name_filter=".txt")
        self.assertNotEqual(first["snapshot_id"], fresh["snapshot_id"])

    def test_returned_pages_are_detached_and_parallel_readers_agree(self):
        for i in range(8):
            (self.docs / f"{i}.txt").write_text("x", encoding="utf-8")
        first = self.catalog.list_directory(self.target, limit=2)
        first["entries"][0]["name"] = "调用者修改"
        with ThreadPoolExecutor(max_workers=6) as executor:
            pages = list(executor.map(lambda _: self.catalog.list_directory(self.target, limit=2), range(18)))
        self.assertEqual({p["snapshot_id"] for p in pages}, {first["snapshot_id"]})
        self.assertTrue(all(p["entries"][0]["name"] == "0.txt" for p in pages))
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda i: self.catalog.refresh() if i % 2 else
                                        self.catalog.list_directory(self.target), range(12)))
        self.assertTrue(all(r is None or len(r["entries"]) == 9 for r in results))

    def test_malformed_cursors_are_stale(self):
        (self.docs / "a.txt").write_text("x", encoding="utf-8")
        first = self.catalog.list_directory(self.target, limit=1)
        for cursor in ({}, [], "bad", {**first["next_cursor"], "offset": "1"},
                       {**first["next_cursor"], "offset": True},
                       {**first["next_cursor"], "offset": -1},
                       {**first["next_cursor"], "offset": 999}):
            with self.subTest(cursor=cursor), self.assertRaises(StaleCursor):
                self.catalog.list_directory(self.target, cursor=cursor)

    def test_root_and_entries_have_native_paths_and_availability(self):
        (self.docs / "中文 空格[1].txt").write_text("x", encoding="utf-8")
        page = self.catalog.list_directory(self.target)
        self.assertEqual(page["target"]["native_path"], str(self.docs))
        entry = next(e for e in page["entries"] if e["name"] == "中文 空格[1].txt")
        self.assertEqual(entry["native_path"], str(self.docs / entry["name"]))
        self.assertTrue(entry["available"])
        self.assertIsNone(entry["reason"])
        self.assertFalse(entry["navigation_only"])
        roots = self.catalog.list_roots("p")["roots"]
        self.assertEqual(roots[0]["native_path"], str(self.docs))
        self.assertFalse(roots[1]["available"])

    def test_permission_denied_is_forbidden_not_missing(self):
        real_stat = Path.stat
        def denied(path, *args, **kwargs):
            if native_path(path) == native_path(self.docs / "denied"):
                raise PermissionError("访问被拒绝")
            return real_stat(path, *args, **kwargs)
        (self.docs / "denied").mkdir()
        with patch.object(Path, "stat", denied):
            with self.assertRaises(CatalogError) as raised:
                self.catalog.resolve_target({**self.target, "relative_path": "denied"})
            self.assertIn("TargetForbidden", [c.__name__ for c in type(raised.exception).__mro__])
            entry = next(e for e in self.catalog.list_directory(self.target)["entries"] if e["name"] == "denied")
            self.assertFalse(entry["available"])
            self.assertNotEqual(entry["kind"], "missing")

    def test_single_registered_subpath_link_cannot_escape_checkout(self):
        target = self.bind_repo(["escape"])
        outside = self.base / "outside"
        outside.mkdir()
        self.link("escape", outside)
        roots = self.catalog.list_roots("p")["roots"]
        self.assertFalse(roots[-1]["available"])
        self.assertIsNone(roots[-1]["native_path"])
        with self.assertRaises(CatalogError):
            self.catalog.resolve_target(target)

    def test_broken_link_is_missing_and_retargeting_invalidates_cursor(self):
        target = self.bind_repo(["."])
        destination = self.repo / "destination"
        destination.mkdir()
        self.link("linked", destination)
        first = self.catalog.list_directory(target, limit=1)
        destination.rmdir()
        with self.assertRaises(StaleCursor):
            self.catalog.list_directory(target, cursor=first["next_cursor"])
        page = self.catalog.list_directory(target)
        entry = next(e for e in page["entries"] if e["name"] == "linked")
        self.assertEqual(entry["kind"], "missing")
        self.assertTrue(entry["is_link"])
        self.assertFalse(entry["available"])

    def test_windows_reserved_and_rooted_names_are_invalid(self):
        for rel in ("/", "\\", "NUL", "CON.txt", "aux", "COM1.log", "a.", "a ", 'a"b'):
            with self.subTest(rel=rel), self.assertRaises(InvalidTarget):
                self.catalog.resolve_target({**self.target, "relative_path": rel})

    def test_yaml_delimiters_inside_quoted_values_are_content(self):
        (self.docs / "README.md").write_text(
            '---\nproject_id: p\ntitle: "正常---标题"\n---\n# 内容\n', encoding="utf-8")
        result = self.catalog.list_projects()
        self.assertEqual(result["diagnostics"], [])
        self.assertEqual(result["projects"][0]["title"], "正常---标题")

    def test_alias_to_allowed_ancestor_only_lists_real_allowed_branches(self):
        target = self.bind_repo(["apps/workbench", "packages/core"])
        (self.repo / "packages/secret").mkdir()
        self.link("apps/workbench/package-nav", self.repo / "packages")
        page = self.catalog.list_directory({**target, "relative_path": "apps/workbench/package-nav"})
        self.assertTrue(page["target"]["navigation_only"])
        self.assertEqual(page["target"]["native_path"], str(Path(page["target"]["path"])))
        self.assertEqual([e["name"] for e in page["entries"]], ["core"])

    def test_docs_and_resources_cannot_register_outside_workspace(self):
        outside = self.base / "outside"
        outside.mkdir()
        write_json(self.ws / "runtime/project_src/project/project.json", {
            "project_id": "p", "docs_root": str(outside), "resource_root": "../outside"})
        roots = self.catalog.list_roots("p")["roots"]
        self.assertEqual(len(roots), 2)
        for root in roots:
            self.assertFalse(root["available"])
            self.assertIsNone(root["native_path"])
            self.assertTrue(root["reason"])
            with self.assertRaises(CatalogError) as raised:
                self.catalog.resolve_target({**self.target, "root_id": root["root_id"]})
            self.assertIn("TargetForbidden", [c.__name__ for c in type(raised.exception).__mro__])

    def test_metadata_subpath_traversal_cannot_expand_repo_root(self):
        for paths in (["../"], ["apps/workbench", "../outside"], ["C:/"]):
            with self.subTest(paths=paths):
                target = self.bind_repo(paths)
                with self.assertRaises(InvalidTarget):
                    self.catalog.resolve_target(target)

    def test_invalid_project_roots_do_not_break_navigation_or_read_outside(self):
        outside = self.base / "outside"
        outside.mkdir()
        for reference in ("../outside", str(outside)):
            with self.subTest(reference=reference):
                write_json(self.ws / "runtime/project_src/project/project.json", {
                    "project_id": "p", "docs_root": reference, "resource_root": reference})
                with patch('workbench.catalog._frontmatter', side_effect=AssertionError('outside read')):
                    listed = self.catalog.list_projects()
                    self.assertEqual(listed['projects'], [])
                    self.assertEqual(len(listed['diagnostics']), 1)
                    nav = self.catalog.list_project_nav('p')
                    self.assertEqual(nav['tasks'], [])
                    self.assertEqual(nav['orphan_runs'], [])
                    self.assertTrue(all(not r['available'] for r in nav['roots']))
                    self.catalog.refresh()
                    self.assertEqual(self.catalog.search('outside')['results'], [])


if __name__ == "__main__":
    unittest.main()
