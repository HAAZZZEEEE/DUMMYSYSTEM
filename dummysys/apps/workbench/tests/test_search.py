"""全局搜索：项目/任务/运行/文件 聚合、类型过滤、缓存失效与排序。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from workbench.catalog import InvalidTarget
from tests.helpers import build_application, build_workspace, write_json

PID = "11111111-1111-4111-8111-111111111111"
TASK = "[task 1][20260921]需求分析"
RUN = "[20260922-203515]Agent 运行"


def _run_json(path: Path, **overrides) -> None:
    payload = {"schema_version": 1, "run_id": "run-1", "task_id": "task-1",
               "title": overrides.pop("title", "Agent 运行"), "status": "completed",
               "created_at": "2026-09-22T20:35:15+00:00"}
    payload.update(overrides)
    write_json(path, payload)


class SearchTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ws = build_workspace(self.root, {
            "proj": {"project_id": PID, "docs_root": "d/vault", "resource_root": "r/proj",
                     "repositories": []},
        })
        self.docs = self.ws / "d" / "vault"
        self.res = self.ws / "r" / "proj"
        self.docs.mkdir(parents=True, exist_ok=True)
        self.res.mkdir(parents=True, exist_ok=True)
        (self.docs / "README.md").write_text(
            "---\nproject_id: %s\ntitle: 工作台项目\nstatus: active\n---\n" % PID, encoding="utf-8")
        # 任务：docs + resource 同名配对 + 一个 run。
        (self.docs / TASK).mkdir()
        (self.docs / TASK / "README.md").write_text(
            "---\ntask_id: task-1\ntitle: 需求分析\nstatus: active\n---\n", encoding="utf-8")
        (self.res / TASK).mkdir()
        write_json(self.res / TASK / "task.json",
                   {"schema_version": 1, "task_id": "task-1", "project_id": PID})
        _run_json(self.res / TASK / "runs" / RUN / "run.json")
        # 一个普通文件（命中文件名搜索）。
        (self.docs / "分析报告.md").write_text("x", encoding="utf-8")
        self.application, _ = build_application(self.ws, self.ws / "task")

    def tearDown(self):
        self.doCleanups()
        self._tmp.cleanup()

    def _search(self, q, **kw):
        return self.application.catalog.search(q, **kw)["results"]

    def test_finds_all_types(self):
        types = sorted(x["type"] for x in self._search("分析"))
        self.assertIn("task", types)      # 需求分析（任务标题）
        self.assertIn("file", types)      # 分析报告.md / 需求分析 目录名
        # 项目标题「工作台项目」不含「分析」，但任务命中已覆盖 task 类型。
        self.assertIn("task", types)
        # run 标题「Agent 运行」含「运行」，用 run 关键词查询应命中。
        run_types = sorted(x["type"] for x in self._search("Agent"))
        self.assertIn("run", run_types)

    def test_type_filter(self):
        files = self._search("分析", types=["file"])
        self.assertTrue(files)
        self.assertTrue(all(x["type"] == "file" for x in files))
        tasks = self._search("分析", types=["task"])
        self.assertTrue(all(x["type"] == "task" for x in tasks))
        self.assertTrue(tasks)

    def test_invalid_type_raises(self):
        with self.assertRaises(InvalidTarget):
            self.application.catalog.search("x", types=["bogus"])

    def test_empty_or_short_query_skips_files(self):
        # 空查询返回空。
        self.assertEqual(self.application.catalog.search("")["results"], [])
        self.assertEqual(self.application.catalog.search(None)["results"], [])
        # 短查询（<2 字符）跳过文件，但项目/任务标题命中仍保留。
        hits = self._search("分")
        self.assertNotIn("file", [x["type"] for x in hits])

    def test_project_id_scope(self):
        results = self._search("分析", project_id=PID)
        self.assertTrue(results)
        self.assertTrue(all(x["project_id"] == PID for x in results))

    def test_file_cap(self):
        # 造超过 12 个命中文件名的文件，验证封顶。
        for i in range(20):
            (self.docs / f"分析-{i}.md").write_text("x", encoding="utf-8")
        files = self._search("分析-", types=["file"])
        self.assertLessEqual(len(files), 12)

    def test_refresh_invalidates_cache(self):
        # p/t/r 语料走 TTL 缓存：先搜索建立缓存，再新增一个任务，refresh 前查不到、refresh 后能查到。
        self.assertEqual(self._search("缓存验证", types=["task"]), [])
        new_task = self.docs / "[task 2][20260923]缓存验证"
        new_task.mkdir()
        (new_task / "README.md").write_text(
            "---\ntask_id: task-2\ntitle: 缓存验证\nstatus: active\n---\n", encoding="utf-8")
        # TTL 5s 内缓存未失效——仍查不到（任务语料已缓存）。
        self.assertEqual(self._search("缓存验证", types=["task"]), [])
        self.application.catalog.refresh()
        hits = self._search("缓存验证", types=["task"])
        self.assertTrue(hits)
        self.assertTrue(all(x["title"] == "缓存验证" for x in hits))

    def test_result_order_by_type(self):
        # 「分析」同时命中任务「需求分析」与文件「分析报告.md」，验证类型序 project→task→run→file。
        order = [x["type"] for x in self._search("分析")]
        index = {t: i for i, t in enumerate(order)}
        self.assertIn("task", index)
        self.assertIn("file", index)
        self.assertLess(index["task"], index["file"])


if __name__ == "__main__":
    unittest.main()
