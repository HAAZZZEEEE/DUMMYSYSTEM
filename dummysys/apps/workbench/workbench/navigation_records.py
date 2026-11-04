"""导航读取投影：Task/Run 配对、管理状态和孤立记录，不持有业务状态副本。"""
from pathlib import Path
import re
from . import metadata
from dummysys_core.operations import native_path

TASK_PATTERN = re.compile(r"\[task ([1-9]\d*)\]\[(\d{8})\](.+)")
RUN_PATTERN = re.compile(r"\[(\d{8}-\d{6})\](.+)")
NAV_HIDDEN_FILES = frozenset({'README.md','AGENTS.md'})


class NavigationRecords:
    def __init__(self,error):
        self.error=error

    @staticmethod
    def _nav_target(project_id: str, root_id: str, relative_path: str) -> dict:
        return {"project_id": project_id, "root_id": root_id, "relative_path": relative_path}

    def _nav_meta(self, path: Path) -> dict:
        try:
            return metadata.frontmatter(path, self.error) if native_path(path).is_file() else {}
        except self.error:
            return {}

    def _nav_json(self, path: Path) -> dict:
        try:
            data = metadata.read_json(path, self.error) if native_path(path).is_file() else {}
        except self.error:
            return {}
        return data if isinstance(data, dict) else {}

    def _scan_runs(self, project_id: str, root_id: str, root_path: Path,
                   owner_rel: str, include_deleted: bool = False) -> list[dict]:
        """owner_rel 是 runs 的父目录相对根路径；空串表示资源根下的 runs/。"""
        runs_dir = (root_path / owner_rel / "runs") if owner_rel else (root_path / "runs")
        runs_dir = native_path(runs_dir)
        runs: list[dict] = []
        if not runs_dir.is_dir():
            return runs
        try:
            entries = sorted(runs_dir.iterdir(), key=lambda p: p.name)
        except OSError:
            return runs
        for run_dir in entries:
            if not run_dir.is_dir():
                continue
            matched = RUN_PATTERN.fullmatch(run_dir.name)
            meta = self._nav_json(run_dir / "run.json")
            management = self._nav_json(run_dir / "run-management.json")
            if management.get("run_id") != meta.get("run_id"):
                management = {}
            deleted = bool(management.get("deleted_at"))
            if deleted and not include_deleted:
                continue
            archived = bool(management.get("archived_at"))
            title = management.get("display_title") or meta.get("title")
            if not isinstance(title, str) or not title.strip():
                title = matched.group(2).strip() if matched else run_dir.name
            created = meta.get("created_at")
            if not isinstance(created, str) or not created.strip():
                created = f"{matched.group(1)}" if matched else None
            run_id = meta.get("run_id") if isinstance(meta.get("run_id"), str) else None
            exit_code = meta.get("exit_code")
            if type(exit_code) is not int:
                exit_code = None
            relative = f"{owner_rel}/runs/{run_dir.name}" if owner_rel else f"runs/{run_dir.name}"
            runs.append({
                "name": run_dir.name,
                "run_id": run_id,
                "title": title,
                "status": "deleted" if deleted else "archived" if archived else meta.get("status") if isinstance(meta.get("status"), str) else None,
                "execution_status": meta.get("status"),
                "archived": archived,
                "deleted": deleted,
                "created_at": created,
                "finished_at": meta.get("finished_at") if isinstance(meta.get("finished_at"), str) else None,
                "exit_code": exit_code,
                "retry_of": meta.get("retry_of") if isinstance(meta.get("retry_of"), str) else None,
                "available": (run_dir / "run.json").is_file(),
                "target": self._nav_target(project_id, root_id, relative),
            })
        return runs

    def _scan_tasks(self, project_id: str, docs: dict | None,
                    resources: dict | None) -> tuple[list[dict], list[dict], list[dict]]:
        """docs/resources 根同名配对；返回 (tasks, orphan_runs, nav_hidden)。"""
        found: dict[str, dict] = {}
        hidden: list[dict] = []
        docs_path = native_path(docs["path"]) if docs else None
        resources_path = native_path(resources["path"]) if resources else None

        def hide(root_id: str, relative: str) -> None:
            hidden.append({"root_id": root_id, "relative_path": relative})

        def add_task(name: str, match: re.Match, side: str, root_id: str,
                     relative: str, archived: bool) -> None:
            record = found.get(name)
            if record is None:
                record = {"name": name, "task_number": int(match.group(1)),
                          "date": match.group(2), "title": match.group(3).strip(),
                          "status": None, "task_id": None, "archived": archived,
                          "docs": None, "resource": None, "runs": []}
                found[name] = record
            record["archived"] = record["archived"] or archived
            record[side] = self._nav_target(project_id, root_id, relative)

        def scan_side(base: Path | None, side: str, root_id: str | None,
                      prefix: str, archived: bool) -> None:
            # prefix 为空表示根一级；只有根一级过滤治理文件与任务目录。
            if base is None or root_id is None or not base.is_dir():
                return
            try:
                entries = sorted(base.iterdir(), key=lambda p: p.name)
            except OSError:
                return
            for entry in entries:
                if not prefix and entry.is_file() and entry.name in NAV_HIDDEN_FILES:
                    hide(root_id, entry.name)
                    continue
                if not entry.is_dir():
                    continue
                matched = TASK_PATTERN.fullmatch(entry.name)
                if matched and prefix in ("", "archive/"):
                    relative = f"{prefix}{entry.name}"
                    add_task(entry.name, matched, side, root_id, relative, archived)
                    hide(root_id, relative)
                elif not prefix and side == "docs" and entry.name == "archive":
                    scan_side(entry, side, root_id, "archive/", True)

        scan_side(docs_path, "docs", docs["root_id"] if docs else None, "", False)
        scan_side(resources_path, "resource", resources["root_id"] if resources else None, "", False)

        def decorate(record: dict) -> None:
            # 标题/状态优先取 docs 侧 README frontmatter；缺失则保留目录名派生值。
            if docs_path is None or record["docs"] is None:
                return
            props = self._nav_meta(docs_path / record["docs"]["relative_path"] / "README.md")
            record["deleted"] = bool(props.get("deleted_at"))
            if not props:
                return
            if isinstance(props.get("title"), str) and props["title"].strip():
                record["title"] = props["title"].strip()
            if isinstance(props.get("status"), str) and props["status"].strip():
                record["status"] = props["status"].strip()
            if isinstance(props.get("task_id"), str) and props["task_id"].strip():
                record["task_id"] = props["task_id"].strip()

        for record in found.values():
            decorate(record)

        orphans: list[dict] = []
        if resources_path and resources_path.is_dir():
            try:
                top = sorted(resources_path.iterdir(), key=lambda p: p.name)
            except OSError:
                top = []
            for entry in top:
                if not entry.is_dir() or not (entry / "runs").is_dir():
                    continue
                owner_rel = entry.name
                if TASK_PATTERN.fullmatch(entry.name):
                    record = found.get(entry.name)
                    if record is not None:
                        all_runs = self._scan_runs(project_id, resources["root_id"],
                                                   resources_path, owner_rel, include_deleted=True)
                        record["runs"] = [run for run in all_runs if not run["deleted"]]
                        record["deleted_runs"] = [run for run in all_runs if run["deleted"]]
                        meta = self._nav_json(entry / "task.json")
                        if not record["task_id"] and isinstance(meta.get("task_id"), str):
                            record["task_id"] = meta["task_id"]
                    continue
                for run in self._scan_runs(project_id, resources["root_id"], resources_path, owner_rel, include_deleted=True):
                    orphans.append({**run, "parent_name": entry.name,
                                    "location_hint": f"{entry.name}/runs/{run['name']}"})
            # 资源根直接挂 runs/ 的也算孤立 run。
            for run in self._scan_runs(project_id, resources["root_id"], resources_path, "", include_deleted=True):
                orphans.append({**run, "parent_name": "",
                                "location_hint": f"runs/{run['name']}"})

        tasks = []
        for record in found.values():
            record["target"] = record["docs"] or record["resource"]
            record["docs_missing"] = record["docs"] is None
            tasks.append(record)
        tasks.sort(key=lambda r: (r["date"], r["task_number"], r["name"]))
        return tasks, orphans, hidden
