"""项目导航扫描：Task/Run 配对、孤立 Run、归档与治理文件过滤。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.helpers import build_application, build_workspace, write_json

PID = "11111111-1111-4111-8111-111111111111"
TASK_A = "[task 1][20260921]工作台需求"
TASK_B = "[task 2][20260922]独立任务"
TASK_ARC = "[task 3][20260920]已归档任务"
RUN_A1 = "[20260922-203515]Agent 入口"
RUN_A2 = "[20260922-210000]修订文档"


def _run_json(path: Path, **overrides) -> None:
    payload = {"schema_version": 1, "run_id": overrides.pop("run_id", f"run-{path.parent.name}"),
               "task_id": "task-1", "title": overrides.pop("title", path.parent.name),
               "status": "completed", "created_at": "2026-09-22T20:35:15+00:00",
               "finished_at": "2026-09-22T20:40:00+00:00", "exit_code": 0, "retry_of": None}
    payload.update(overrides)
    write_json(path, payload)


class ProjectNavTest(unittest.TestCase):
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
        # 项目规定位置的治理文件 + 同名文件出现在子目录（不过滤）。
        (self.docs / "README.md").write_text("---\nproject_id: %s\n---\n" % PID, encoding="utf-8")
        (self.docs / "AGENTS.md").write_text("# agents\n", encoding="utf-8")
        (self.docs / "Agent.md").write_text("# not-filtered\n", encoding="utf-8")
        (self.res / "README.md").write_text("# res readme\n", encoding="utf-8")
        (self.res / "AGENTS.md").write_text("# res agents\n", encoding="utf-8")
        sub = self.docs / "notes"
        sub.mkdir()
        (sub / "README.md").write_text("# nested readme\n", encoding="utf-8")
        (sub / "AGENTS.md").write_text("# nested agents\n", encoding="utf-8")
        # Task A：两侧同名 + 两个 run。
        (self.docs / TASK_A).mkdir()
        (self.docs / TASK_A / "README.md").write_text(
            "---\ntask_id: task-1\ntitle: 标题取自我\nstatus: active\n---\n", encoding="utf-8")
        (self.res / TASK_A).mkdir()
        write_json(self.res / TASK_A / "task.json",
                   {"schema_version": 1, "task_id": "task-1", "project_id": PID})
        _run_json(self.res / TASK_A / "runs" / RUN_A1 / "run.json", run_id="run-a1")
        _run_json(self.res / TASK_A / "runs" / RUN_A2 / "run.json", run_id="run-a2",
                  title="", status="running", exit_code=None)
        # Task B：只有 docs 侧，无 runs（task 无 run 的特殊形式）。
        (self.docs / TASK_B).mkdir()
        (self.docs / TASK_B / "README.md").write_text("---\ntitle: 仅文档任务\n---\n", encoding="utf-8")
        # 归档 Task：docs 侧 archive/ 下，resource 侧无。
        arc = self.docs / "archive"
        arc.mkdir()
        (arc / TASK_ARC).mkdir()
        (arc / TASK_ARC / "README.md").write_text("---\ntitle: 归档任务\n---\n", encoding="utf-8")
        # 孤立 run：父目录不是标准 task 名。
        orphan_owner = self.res / "loose-dir"
        orphan_owner.mkdir()
        _run_json(orphan_owner / "runs" / RUN_A1 / "run.json", run_id="orphan-1")
        # 命名不合规目录（应落进普通树，不进上组）。
        (self.docs / "not-a-task-dir").mkdir()
        (self.docs / "plain.md").write_text("text\n", encoding="utf-8")
        self.application, _ = build_application(self.ws, self.ws / "task")

    def tearDown(self):
        self.doCleanups()
        self._tmp.cleanup()

    def _nav(self):
        return self.application.project_nav(PID)

    def test_pairs_docs_and_resource_sides(self):
        tasks = {t["name"]: t for t in self._nav()["tasks"]}
        self.assertIn(TASK_A, tasks)
        record = tasks[TASK_A]
        self.assertEqual(record["docs"]["root_id"], "docs")
        self.assertEqual(record["docs"]["relative_path"], TASK_A)
        self.assertEqual(record["resource"]["root_id"], "resources")
        self.assertEqual(record["resource"]["relative_path"], TASK_A)
        self.assertFalse(record["docs_missing"])
        self.assertEqual(record["task_number"], 1)
        self.assertEqual(record["date"], "20260921")
        # 标题优先取 docs 侧 README frontmatter。
        self.assertEqual(record["title"], "标题取自我")
        self.assertEqual(record["status"], "active")
        self.assertEqual(record["task_id"], "task-1")

    def test_task_without_runs_is_listed(self):
        tasks = {t["name"]: t for t in self._nav()["tasks"]}
        self.assertIn(TASK_B, tasks)
        record = tasks[TASK_B]
        self.assertEqual(record["runs"], [])
        self.assertIsNone(record["resource"])
        self.assertTrue(record["docs_missing"] is False or record["docs"] is not None)
        self.assertEqual(record["target"]["root_id"], "docs")

    def test_runs_are_attached_with_metadata(self):
        tasks = {t["name"]: t for t in self._nav()["tasks"]}
        runs = {r["name"]: r for r in tasks[TASK_A]["runs"]}
        self.assertEqual(set(runs), {RUN_A1, RUN_A2})
        self.assertEqual(runs[RUN_A1]["run_id"], "run-a1")
        self.assertEqual(runs[RUN_A1]["status"], "completed")
        self.assertEqual(runs[RUN_A1]["exit_code"], 0)
        self.assertEqual(runs[RUN_A1]["target"]["root_id"], "resources")
        self.assertEqual(runs[RUN_A1]["target"]["relative_path"], f"{TASK_A}/runs/{RUN_A1}")
        # run.json 缺 title 时按目录名降级，不丢弃。
        self.assertTrue(runs[RUN_A2]["title"])
        self.assertIsNone(runs[RUN_A2]["exit_code"])

    def test_archived_task_from_docs_archive(self):
        tasks = {t["name"]: t for t in self._nav()["tasks"]}
        self.assertIn(TASK_ARC, tasks)
        record = tasks[TASK_ARC]
        self.assertTrue(record["archived"])
        self.assertEqual(record["docs"]["relative_path"], f"archive/{TASK_ARC}")
        self.assertIsNone(record["resource"])
        self.assertEqual(record["runs"], [])

    def test_orphan_runs_listed_separately(self):
        orphans = self._nav()["orphan_runs"]
        self.assertEqual(len(orphans), 1)
        self.assertEqual(orphans[0]["parent_name"], "loose-dir")
        self.assertEqual(orphans[0]["run_id"], "orphan-1")
        self.assertEqual(orphans[0]["location_hint"], f"loose-dir/runs/{RUN_A1}")

    def test_nav_hidden_only_at_declared_locations(self):
        hidden = {(h["root_id"], h["relative_path"]) for h in self._nav()["nav_hidden"]}
        self.assertIn(("docs", "README.md"), hidden)
        self.assertIn(("docs", "AGENTS.md"), hidden)
        self.assertIn(("resources", "README.md"), hidden)
        self.assertIn(("resources", "AGENTS.md"), hidden)
        # 任务目录整体从普通树里收走。
        self.assertIn(("docs", TASK_A), hidden)
        self.assertIn(("resources", TASK_A), hidden)
        self.assertIn(("docs", f"archive/{TASK_ARC}"), hidden)
        # 子目录同名文件、Agent.md、命名不合规目录不过滤。
        self.assertNotIn(("docs", "notes/README.md"), hidden)
        self.assertNotIn(("docs", "notes/AGENTS.md"), hidden)
        self.assertNotIn(("docs", "Agent.md"), hidden)
        self.assertNotIn(("docs", "not-a-task-dir"), hidden)
        self.assertNotIn(("docs", "plain.md"), hidden)
        # archive/ 目录本身留给普通树。
        self.assertNotIn(("docs", "archive"), hidden)

    def test_nonstandard_names_stay_out_of_task_group(self):
        names = {t["name"] for t in self._nav()["tasks"]}
        self.assertNotIn("not-a-task-dir", names)

    def test_missing_run_json_degrades_without_drop(self):
        broken = self.res / TASK_A / "runs" / "[20260922-220000]缺元数据"
        broken.mkdir()
        runs = {r["name"] for t in self._nav()["tasks"] if t["name"] == TASK_A for r in t["runs"]}
        self.assertIn("[20260922-220000]缺元数据", runs)


if __name__ == "__main__":
    unittest.main()
