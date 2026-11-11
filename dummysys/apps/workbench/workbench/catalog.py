"""项目、Repo、根及文件定位。

向 application 提供 list_projects、list_roots、resolve_target、list_directory；
web 模块不直接访问任意文件系统路径。项目发现只读取 runtime/project_src 下一级
各项目的 project.json，不递归扫描。目录链接越界标识 blocked_link，不继续浏览。
"""
from __future__ import annotations

from dummysys_core import locations as loc
from dummysys_core.operations import GovernanceError, native_path as io_path

import hashlib
import json
import ntpath
import os
import re
import stat as stat_module
import time
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path, PureWindowsPath
from threading import RLock
from typing import Iterator
from uuid import uuid4

from . import metadata
from .navigation_records import NavigationRecords, TASK_PATTERN, RUN_PATTERN, NAV_HIDDEN_FILES

PAGE_SIZE = 200
MAX_PAGE_SIZE = 500
SNAPSHOT_TTL = 30.0
PROJECT_SRC = "runtime/project_src"
REPOSITORIES_JSON = "runtime/state/workspace/repositories.json"
INVALID_RELATIVE = ("..",)
ADS_COLON = ":"
# 与 dummysys-cli 同规则的本地副本；workbench 不依赖该包。
_NUMERIC_CHUNK = re.compile(r"(\d+)")


def natural_key(name: str) -> tuple:
    """目录名的自然排序键：数字段按数值比较，其余按大小写不敏感字典序。

    否则 `[task 11]` 的 `1`(0x31) 会排在 `[task 1]` 的 `]`(0x5D) 之前，
    得到 11/12/13/1 这样的字符串序。
    """
    chunks = []
    for part in _NUMERIC_CHUNK.split(name):
        if part.isdigit():
            chunks.append((1, int(part), ""))
        else:
            chunks.append((0, 0, part.casefold()))
    return tuple(chunks)

# 全局搜索：服务端语料缓存（TTL）与结果限额。文件只搜文件名、限制条数。
SEARCH_TTL = 5.0
SEARCH_TYPES = ("project", "task", "run", "file")
SEARCH_LIMITS = {"file": 12}
SEARCH_FILE_DEPTH = 2
SEARCH_FILE_MIN_LEN = 2


class CatalogError(Exception):
    """目录解析错误。"""


class TargetNotFound(CatalogError):
    """目标不存在，HTTP 层可映射为 404。"""


class TargetForbidden(CatalogError):
    """目标不可访问，HTTP 层可映射为 403。"""


class ProjectNotFound(TargetNotFound):
    pass


class RootNotFound(TargetNotFound):
    pass


class InvalidTarget(CatalogError):
    pass


class PathOutsideRoot(TargetForbidden):
    pass


class BlockedLink(TargetForbidden):
    pass


class StaleCursor(CatalogError):
    pass


def _read_json(path: Path) -> dict:
    return metadata.read_json(path, CatalogError)


def _frontmatter(path: Path) -> dict:
    return metadata.frontmatter(path, CatalogError)


def _list_str(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x) for x in value]
    return [str(value)]


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def _digest(path: str) -> str:
    return hashlib.sha256(os.path.normcase(str(path)).encode("utf-8")).hexdigest()[:12]


def _synchronized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._lock, metadata.reading():
            return method(self, *args, **kwargs)
    return call


class SnapshotStore:
    """按目标、过滤条件及真实内容版本保存不可变快照；访问时清理过期项。"""

    def __init__(self, ttl: float = SNAPSHOT_TTL, clock=None):
        self._ttl = ttl
        self._clock = clock or time.monotonic
        self._lock = RLock()
        self._store: dict[str, tuple[float, str, str, str]] = {}

    def capture(self, key: str, version: str, entries: list[dict],
                snapshot_id: str | None = None) -> tuple[str, list[dict]]:
        with self._lock:
            now = self._clock()
            self._store = {k: v for k, v in self._store.items() if now - v[0] < self._ttl}
            entry = self._store.get(key)
            if snapshot_id is not None:
                if not entry or entry[1] != snapshot_id or entry[2] != version:
                    raise StaleCursor("目录快照已失效，请刷新后重试")
            if not entry or entry[2] != version:
                entry = (now, str(uuid4()), version, json.dumps(entries, ensure_ascii=False))
                self._store[key] = entry
            return entry[1], json.loads(entry[3])

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


class Catalog:
    """以登记项目为根，解析项目、根、目标与目录列表。"""

    def __init__(self, config: dict, snapshot_store: SnapshotStore | None = None):
        self.config = config
        self.navigation = NavigationRecords(CatalogError)
        self.workspace_root = Path(config["workspace_root"])
        self.project_src = loc.resolve(self.workspace_root, PROJECT_SRC)
        self.snapshots = snapshot_store or SnapshotStore()
        self._repositories: dict[str, str] | None = None
        self._search_cache: dict | None = None
        self._lock = RLock()

    @_synchronized
    def refresh(self) -> None:
        """显式重读本机 checkout 映射，同时废弃旧目录游标与搜索语料缓存。"""
        self._repositories = None
        self.snapshots.clear()
        self._search_cache = None
        self._load_repositories()

    # ---- 项目发现 ----

    def _iter_projects(self, diagnostics: list[dict] | None = None) -> Iterator[tuple[Path, dict]]:
        if not self.project_src.is_dir():
            return
        for entry in sorted(self.project_src.iterdir()):
            project_json = entry / "project.json"
            if not project_json.is_file():
                continue
            try:
                binding = _read_json(project_json)
                if not isinstance(binding, dict):
                    raise CatalogError("project.json 必须是 JSON 对象")
                if not isinstance(binding.get("project_id"), str) or not binding["project_id"].strip():
                    raise CatalogError("project.json 缺少有效的字符串 project_id")
            except CatalogError as error:
                if diagnostics is not None:
                    diagnostics.append({"project": entry.name, "code": "PROJECT_META_ERROR", "message": str(error)})
                continue
            yield entry, binding

    def _project_docs_root(self, binding: dict) -> Path | None:
        if not binding.get("docs_root"):
            return None
        root = self._project_root(binding, "docs", "文档")
        return Path(self._target_for_root(binding["project_id"], root, "")["path"])

    @_synchronized
    def list_projects(self, query: str | None = None, include_archived: bool = False) -> dict:
        projects: list[dict] = []
        deleted_projects: list[dict] = []
        diagnostics: list[dict] = []
        seen_ids: dict[str, Path] = {}
        for entry, binding in self._iter_projects(diagnostics):
            name = entry.name
            try:
                docs_root = self._project_docs_root(binding)
                if not docs_root:
                    raise CatalogError(f"{name} 缺少 docs_root")
                readme = docs_root / "README.md"
                if not readme.is_file():
                    raise CatalogError(f"缺少 README：{readme}")
                meta = _frontmatter(readme)
                meta_id = meta.get("project_id")
                json_id = binding.get("project_id")
                if not isinstance(meta_id, str) or not meta_id.strip():
                    raise CatalogError(f"{name} README 缺少 project_id")
                if meta_id != json_id:
                    raise CatalogError(f"{name} ID 不匹配：README={meta_id} JSON={json_id}")
                if meta_id in seen_ids:
                    raise CatalogError(f"{name} 项目 ID 重复：{meta_id}（与 {seen_ids[meta_id].name} 冲突）")
                seen_ids[meta_id] = entry
                resource_raw = binding.get("resource_root")
                if not isinstance(resource_raw, str) or not resource_raw:
                    raise CatalogError(f"{name} 缺少 resource_root")
                status = str(meta.get("status") or "active")
                archived = status == "archived"
                if archived and not include_archived:
                    continue
                deleted = bool(meta.get("deleted_at"))
                (deleted_projects if deleted else projects).append({
                    "project_id": meta_id,
                    "title": str(meta.get("title") or name),
                    "status": status,
                    "aliases": _list_str(meta.get("aliases")),
                    "archived": archived,
                    "created": str(meta.get("created") or ''),
                    "deleted": deleted,
                    "docs_root": docs_root.as_posix(),
                    "resource_root": self._target_for_root(json_id, self._project_root(binding, "resources", "项目资源"), "")["path"],
                })
            except (CatalogError, OSError, ValueError) as error:
                diagnostics.append({"project": name, "code": "PROJECT_META_ERROR", "message": str(error)})
        if query:
            needle = query.casefold()
            projects = [p for p in projects if needle in p["title"].casefold()
                        or any(needle in a.casefold() for a in p["aliases"])]
        return {"projects": projects, "deleted_projects": deleted_projects, "diagnostics": diagnostics}

    # ---- 根解析 ----

    def _load_repositories(self) -> dict[str, str]:
        if self._repositories is not None:
            return self._repositories
        mapping_path = loc.resolve(self.workspace_root, REPOSITORIES_JSON)
        result: dict[str, str] = {}
        if mapping_path.is_file():
            try:
                data = _read_json(mapping_path)
                if not isinstance(data, dict) or not isinstance(data.get("checkouts", {}), dict):
                    raise CatalogError("仓库映射必须包含 checkouts 对象")
                for repo_id, info in data.get("checkouts", {}).items():
                    path = info.get("path") if isinstance(info, dict) else None
                    if isinstance(path, str) and Path(path).is_absolute():
                        result[repo_id] = os.path.normpath(str(path))
            except CatalogError:
                pass
        self._repositories = result
        return result

    def _resolve_repo(self, repo_id: str, subpath: str | None) -> tuple[Path, str]:
        checkouts = self._load_repositories()
        checkout = checkouts.get(repo_id)
        if not checkout:
            raise RootNotFound(f"仓库未绑定本机 checkout：{repo_id}")
        root = Path(checkout)
        if subpath:
            root = root / subpath
        root = root.resolve()
        return root, f"repo:{repo_id}"

    def _project_root(self, binding: dict, kind: str, label: str) -> dict:
        """把绑定解析成目录根；坏引用保留为不可访问项，不降级为任意本机路径。"""
        key = "docs_root" if kind == "docs" else "resource_root"
        raw = binding.get(key)
        if not isinstance(raw, str) or not raw:
            raise RootNotFound(f"项目缺少 {key}：{binding.get('project_id')}")
        root = {"root_id": kind, "kind": kind, "label": label, "path": None}
        try:
            reference = Path(raw.replace("\\", "/"))
            # 兼容旧绝对绑定，但仍按声明的目录边界检查。
            path = reference if reference.is_absolute() else loc.resolve(self.workspace_root, reference)
            root.update(path=path.as_posix(), _boundary=loc.boundary(self.workspace_root, reference).as_posix())
        except (GovernanceError, ValueError) as error:
            root["_forbidden"] = str(error)
        return root

    def _roots_for_binding(self, binding: dict) -> list[dict]:
        roots: list[dict] = []
        if binding.get("docs_root"):
            roots.append(self._project_root(binding, "docs", "文档"))
        roots.append(self._project_root(binding, "resources", "项目资源"))
        for repo in binding.get("repositories") or []:
            repo_id = repo.get("repo_id") if isinstance(repo, dict) else None
            if not repo_id:
                if isinstance(repo, dict) and isinstance(repo.get("path"), str):
                    legacy = Path(repo["path"])
                    if legacy.is_absolute():
                        legacy = legacy.resolve()
                        roots.append({"root_id": f"repo:{_digest(legacy.as_posix())}",
                                      "kind": "repo", "label": f"代码 {repo.get('role') or '历史仓库'}",
                                      "path": legacy.as_posix()})
                continue
            paths = repo.get("paths") or ["."]
            if not isinstance(paths, list):
                raise InvalidTarget("仓库 paths 必须是相对路径列表")
            paths = [self._validate_relative(p) for p in paths]
            if isinstance(paths, list) and len(paths) == 1:
                try:
                    checkout, root_id = self._resolve_repo(repo_id, None)
                except RootNotFound:
                    continue
                root = checkout / paths[0]
                roots.append({"root_id": root_id, "kind": "repo", "label": f"代码 {repo_id}",
                              "path": root.as_posix(), "_checkout": checkout.as_posix(),
                              "_allowed": paths})
            else:
                # 多子路径：以仓库根为根，路径限制在子路径内
                try:
                    root, root_id = self._resolve_repo(repo_id, None)
                except RootNotFound:
                    continue
                allowed = [str(p).replace("\\", "/") for p in (paths or [])]
                roots.append({
                    "root_id": root_id, "kind": "repo", "label": f"代码 {repo_id}",
                    "path": root.as_posix(), "subpaths": allowed,
                })
        return roots

    @_synchronized
    def find_project(self, project_id: str) -> tuple[dict, list[dict]]:
        for entry, binding in self._iter_projects():
            if binding.get("project_id") == project_id:
                return binding, self._roots_for_binding(binding)
        raise ProjectNotFound(f"项目不存在：{project_id}")

    @_synchronized
    def list_roots(self, project_id: str) -> dict:
        _, roots = self.find_project(project_id)
        result = []
        for root in roots:
            public = {k: v for k, v in root.items() if not k.startswith("_")}
            try:
                resolved = self._target_for_root(project_id, root, "")
                public.update({k: resolved[k] for k in ("native_path", "available", "reason", "navigation_only")})
            except TargetForbidden as error:
                public.update(native_path=None, available=False, reason=str(error), navigation_only=False)
            result.append(public)
        return {"project_id": project_id, "roots": result}

    # ---- 项目导航（Task/Run 关系 + 过滤清单） ----

    _nav_target = staticmethod(NavigationRecords._nav_target)

    def _scan_tasks(self, project_id, docs, resources):
        return self.navigation._scan_tasks(project_id, docs, resources)

    @_synchronized
    def list_project_nav(self, project_id: str) -> dict:
        if not isinstance(project_id, str) or not project_id.strip():
            raise InvalidTarget("缺少 project_id")
        _, roots = self.find_project(project_id)
        public_roots = []
        for root in roots:
            item = {k: v for k, v in root.items() if not k.startswith("_")}
            try:
                resolved = self._target_for_root(project_id, root, "")
                item.update({k: resolved[k] for k in ("native_path", "available", "reason", "navigation_only")})
            except TargetForbidden as error:
                item.update(native_path=None, available=False, reason=str(error), navigation_only=False)
            public_roots.append(item)
        docs = next((r for r in public_roots if r["kind"] == "docs" and r["available"]), None)
        resources = next((r for r in public_roots if r["kind"] == "resources" and r["available"]), None)
        tasks, orphans, hidden = self._scan_tasks(project_id, docs, resources)
        return {"project_id": project_id, "tasks": [task for task in tasks if not task.get("deleted")],
                "deleted_tasks": [task for task in tasks if task.get("deleted")], "orphan_runs": [run for run in orphans if not run.get("deleted")],
                "nav_hidden": hidden, "roots": public_roots}

    @_synchronized
    def list_deleted(self) -> dict:
        """按来源项目、Task、Run聚集；正常祖先仅提供层次上下文。"""
        catalog = self.list_projects(include_archived=True)
        groups = []
        count = 0
        diagnostics = list(catalog['diagnostics'])
        for project in catalog['projects'] + catalog['deleted_projects']:
            try:
                pid = project['project_id']
                tasks, orphans, _ = self._scan_tasks(pid,
                    {'path': project['docs_root'], 'root_id': 'docs'},
                    {'path': project['resource_root'], 'root_id': 'resources'})
                collected = []
                for task in tasks:
                    runs = task.get('runs', []) + task.get('deleted_runs', [])
                    own_deleted = bool(task.get('deleted'))
                    visible = runs if project['deleted'] or own_deleted else [r for r in runs if r.get('deleted')]
                    if project['deleted'] or own_deleted or visible:
                        collected.append({**task, 'runs': visible, 'deleted_runs': []})
                    count += int(own_deleted) + sum(bool(r.get('deleted')) for r in runs)
                visible_orphans = orphans if project['deleted'] else [r for r in orphans if r.get('deleted')]
                count += int(project['deleted']) + sum(bool(r.get('deleted')) for r in orphans)
                if project['deleted'] or collected or visible_orphans:
                    groups.append({**project, 'tasks': collected, 'orphan_runs': visible_orphans})
            except (CatalogError, OSError, ValueError) as error:
                diagnostics.append({'project': project['title'], 'message': str(error)})
        return {'projects': groups, 'count': count, 'diagnostics': diagnostics}

    # ---- 全局搜索 ----

    def _project_display(self, entry: Path, binding: dict) -> dict | None:
        """项目展示信息（复用 list_projects 的 README 元数据规则，失败则跳过）。"""
        try:
            docs_root = self._project_docs_root(binding)
        except (CatalogError, OSError, ValueError):
            return None
        if not docs_root:
            return None
        readme = docs_root / "README.md"
        if not readme.is_file():
            return None
        meta = _frontmatter(readme)
        if meta.get("deleted_at"):
            return None
        meta_id = meta.get("project_id")
        json_id = binding.get("project_id")
        if not isinstance(meta_id, str) or not meta_id.strip() or meta_id != json_id:
            return None
        status = str(meta.get("status") or "active")
        return {
            "project_id": meta_id,
            "title": str(meta.get("title") or entry.name),
            "status": status,
            "aliases": _list_str(meta.get("aliases")),
        }

    def _search_roots(self, project_id: str) -> list[dict]:
        """文件搜索用的根：docs + resources（不含 repo/code 根，过大且子路径受限）。"""
        try:
            _, roots = self.find_project(project_id)
        except (CatalogError, TargetForbidden):
            return []
        available = []
        for root in roots:
            if root["kind"] not in ("docs", "resources"):
                continue
            try:
                if self._target_for_root(project_id, root, "")["available"]:
                    available.append(root)
            except TargetForbidden:
                continue
        return available

    def _search_corpus(self, project_id: str | None) -> list[dict]:
        """构建 p/t/r 扁平语料；文件命中在 search 里按需扫描，不常驻缓存。"""
        corpus: list[dict] = []
        for entry, binding in self._iter_projects():
            pid = binding.get("project_id")
            if project_id and pid != project_id:
                continue
            display = self._project_display(entry, binding)
            if display is None:
                continue
            corpus.append({
                "type": "project", "project_id": pid, "project_title": display["title"],
                "title": display["title"], "meta": f"项目 · {display['status']}",
                "status": display["status"], "aliases": display["aliases"],
                "target": self._nav_target(pid, "", ""),
            })
            docs = next((r for r in self._search_roots(pid) if r["kind"] == "docs"), None)
            resources = next((r for r in self._search_roots(pid) if r["kind"] == "resources"), None)
            docs_nav = {"path": docs["path"], "root_id": docs["root_id"]} if docs else None
            resources_nav = {"path": resources["path"], "root_id": resources["root_id"]} if resources else None
            tasks, orphans, _ = self._scan_tasks(pid, docs_nav, resources_nav)
            for task in tasks:
                if task.get("deleted"):
                    continue
                corpus.append({
                    "type": "task", "project_id": pid, "project_title": display["title"],
                    "title": task["title"], "name": task["name"],
                    "meta": f"任务 · {display['title']}",
                    "task_number": task["task_number"], "date": task["date"],
                    "status": task["status"], "target": task["target"],
                })
            for run in orphans:
                if run.get('deleted'):
                    continue
                self._corpus_run(corpus, pid, display["title"], run)
            for task in tasks:
                if task.get("deleted"):
                    continue
                for run in task.get("runs") or []:
                    self._corpus_run(corpus, pid, display["title"], run)
        return corpus

    @staticmethod
    def _corpus_run(corpus: list[dict], project_id: str, project_title: str, run: dict) -> None:
        corpus.append({
            "type": "run", "project_id": project_id, "project_title": project_title,
            "title": run["title"], "name": run["name"],
            "meta": f"运行 · {project_title}", "status": run["status"],
            "created_at": run["created_at"], "target": run["target"],
        })

    @_synchronized
    def search(self, query: str | None = None, types: list[str] | None = None,
               project_id: str | None = None) -> dict:
        """全局搜索：项目/任务/运行/文件，按类型分组排序。写路径不经此，纯只读。"""
        query = (query or '').strip()
        want = set(types) if types else set(SEARCH_TYPES)
        if not want or not want.issubset(set(SEARCH_TYPES)):
            raise InvalidTarget(f'搜索类型必须是 {"、".join(SEARCH_TYPES)} 之一')
        scope = project_id or ''
        now = time.monotonic()
        if self._search_cache is None or self._search_cache["scope"] != scope \
                or now - self._search_cache["at"] >= SEARCH_TTL:
            corpus = self._search_corpus(project_id)
            self._search_cache = {"scope": scope, "at": now, "corpus": corpus}
        else:
            corpus = self._search_cache["corpus"]
        needle = query.casefold()
        if not needle:
            return {"results": []}
        results = []
        for item in corpus:
            if item["type"] not in want:
                continue
            hay = " ".join(filter(None, [
                item["type"], item.get("title"), item.get("name"),
                item.get("meta"), item.get("project_title"),
                *[a or "" for a in (item.get("aliases") or [])],
            ])).casefold()
            if needle in hay:
                results.append(item)
        # 文件命中按需扫描（短查询跳过，结果封顶）。
        if "file" in want and len(query) >= SEARCH_FILE_MIN_LEN:
            results.extend(self._search_files(query, project_id))
        results.sort(key=lambda r: (SEARCH_TYPES.index(r["type"]), natural_key(r["title"]), r["project_title"]))
        return {"results": results}

    def _search_files(self, needle: str, project_id: str | None) -> list[dict]:
        """深度 ≤ 2 扫描 docs/resources 根的目录/文件名；命中即建 target，封顶 file 条。"""
        found: list[dict] = []
        for entry, binding in self._iter_projects():
            pid = binding.get("project_id")
            if project_id and pid != project_id:
                continue
            display = self._project_display(entry, binding)
            if display is None:
                continue
            for root in self._search_roots(pid):
                base = Path(root["path"])
                if not base.is_dir():
                    continue
                self._walk_search(base, base, root, pid, display["title"], needle, 0, found)
                if len(found) >= SEARCH_LIMITS["file"]:
                    return found
        return found

    def _walk_search(self, base: Path, current: Path, root: dict, project_id: str,
                     project_title: str, needle: str, depth: int, found: list[dict]) -> None:
        if len(found) >= SEARCH_LIMITS["file"]:
            return
        try:
            names = sorted(os.listdir(io_path(current)), key=lambda n: (natural_key(n), n))
        except OSError:
            return
        rel_dir = self._rel_of(base, current)
        for name in names:
            if len(found) >= SEARCH_LIMITS["file"]:
                return
            child = current / name
            child_rel = f"{rel_dir}/{name}" if rel_dir else name
            is_dir = child.is_dir()
            if needle in name.casefold():
                try:
                    resolved = self._target_for_root(project_id, root, self._validate_relative(child_rel))
                except (TargetForbidden, InvalidTarget, OSError):
                    continue
                if resolved["available"]:
                    found.append({
                        "type": "file", "project_id": project_id,
                        "project_title": project_title,
                        "title": name, "name": name,
                        "meta": f"文件 · {root['label']}{'/' + rel_dir if rel_dir else ''}",
                        "kind": resolved["kind"], "target": resolved,
                    })
            if is_dir and depth < SEARCH_FILE_DEPTH:
                self._walk_search(base, child, root, project_id, project_title,
                                  needle, depth + 1, found)

    @staticmethod
    def _rel_of(base: Path, current: Path) -> str:
        try:
            rel = current.relative_to(base).as_posix()
        except ValueError:
            return ""
        return "" if rel in (".", "") else rel

    @_synchronized
    def resolve_target(self, target: dict) -> dict:
        if not isinstance(target, dict):
            raise InvalidTarget("target 必须是对象")
        project_id = target.get("project_id")
        root_id = target.get("root_id")
        relative_path = target.get("relative_path", "")
        if not project_id or not root_id:
            raise InvalidTarget("缺少 project_id 或 root_id")
        binding, roots = self.find_project(project_id)
        root = next((r for r in roots if r["root_id"] == root_id), None)
        if root is None:
            raise RootNotFound(f"根不存在：{root_id}")
        rel = self._validate_relative(relative_path)
        return self._target_for_root(project_id, root, rel)

    @staticmethod
    def _access(rel: str, allowed: list[str]) -> str:
        """词法与真实路径共用范围判定；祖先只允许导航。"""
        rel = os.path.normcase(rel.replace("\\", "/")).replace("\\", "/").strip("/")
        if rel == ".":
            rel = ""
        paths = [os.path.normcase(p.replace("\\", "/")).replace("\\", "/").strip("/") for p in allowed]
        if any(p in ("", ".") or rel == p or rel.startswith(p + "/") for p in paths):
            return "allowed"
        if not rel or any(p.startswith(rel + "/") for p in paths):
            return "navigation"
        return "forbidden"

    def _target_for_root(self, project_id: str, root: dict, rel: str) -> dict:
        if root.get("_forbidden"):
            raise TargetForbidden(root["_forbidden"])
        base = Path(root["path"])
        allowed = root.get("subpaths") or [""]
        access = self._access(rel, allowed)
        if access == "forbidden":
            raise PathOutsideRoot("相对路径超出登记子路径")
        try:
            base_resolved = base.resolve()
            if root.get("_boundary"):
                self._resolve_within(base, Path(root["_boundary"]))
            if root.get("_checkout"):
                checkout = Path(root["_checkout"])
                actual = self._resolve_within(base, checkout).relative_to(checkout).as_posix()
                if self._access(actual, root["_allowed"]) != "allowed":
                    raise BlockedLink("仓库子路径链接越出登记范围")
            current = base
            ancestors = {base_resolved}
            for part in Path(rel).parts:
                current = current / part
                canonical = self._resolve_within(current, base)
                if canonical in ancestors:
                    raise BlockedLink("目录链接指向祖先，已阻止循环浏览")
                ancestors.add(canonical)
            resolved = self._resolve_within(current, base)
            actual_access = self._access(resolved.relative_to(base_resolved).as_posix(), allowed)
            if actual_access == "forbidden":
                raise BlockedLink("目录链接越出登记子路径，已阻止浏览")
            navigation = access == "navigation" or actual_access == "navigation"
            try:
                info = io_path(resolved).stat()
                kind = "dir" if stat_module.S_ISDIR(info.st_mode) else "file"
            except (FileNotFoundError, NotADirectoryError):
                kind = "missing"
            if navigation and kind == "file":
                raise TargetForbidden("登记子路径的祖先不是目录")
        except PermissionError as error:
            raise TargetForbidden("读取目标被拒绝") from error
        except (OSError, RuntimeError) as error:
            raise BlockedLink("路径或目录链接无法安全解析") from error
        return {
            "project_id": project_id,
            "root_id": root["root_id"],
            "relative_path": rel,
            "path": resolved.as_posix(),
            "canonical_path": resolved.as_posix(),
            "kind": kind,
            "native_path": str(resolved) if kind != "missing" else None,
            "available": kind != "missing",
            "reason": "目标不存在" if kind == "missing" else ("仅用于导航到登记子路径，不能外部打开" if navigation else None),
            "navigation_only": navigation,
        }

    def _validate_relative(self, relative_path: str) -> str:
        if not isinstance(relative_path, str):
            raise InvalidTarget("relative_path 必须是字符串")
        if os.path.isabs(relative_path) or relative_path.startswith(("/", "\\")):
            raise InvalidTarget("拒绝绝对路径")
        if len(relative_path) >= 2 and relative_path[1] == ":":
            raise InvalidTarget("拒绝盘符路径")
        rel = relative_path.replace("\\", "/")
        if rel in {"", "."}:
            return ""
        parts = rel.split("/")
        if any(p in INVALID_RELATIVE or not p or p == "." for p in parts):
            raise InvalidTarget("拒绝越界相对路径")
        if "\x00" in rel or ADS_COLON in rel:
            raise InvalidTarget("拒绝 NUL 或 Windows ADS 路径")
        if any(p.endswith((" ", ".")) or any(c in p for c in '<>"|?*')
               or any(ord(c) < 32 for c in p) for p in parts):
            raise InvalidTarget("拒绝 Windows 非法或歧义文件名")
        reserved = getattr(ntpath, "isreserved", lambda p: PureWindowsPath(p).is_reserved())
        if any(reserved(p) for p in parts):
            raise InvalidTarget("拒绝 Windows 保留设备名称")
        return rel

    def _resolve_within(self, candidate: Path, base: Path) -> Path:
        try:
            resolved = candidate.resolve()
        except PermissionError as error:
            raise TargetForbidden("读取路径被拒绝") from error
        except (OSError, RuntimeError) as error:
            raise BlockedLink("路径或目录链接无法安全解析") from error
        base_resolved = base.resolve()
        if resolved != base_resolved and base_resolved not in resolved.parents:
            raise BlockedLink("目录链接越出登记根，已阻止浏览")
        return resolved

    # ---- 目录列表 ----

    def _snapshot_key(self, project_id: str, root_id: str, rel: str) -> str:
        return f"{project_id}\x1f{root_id}\x1f{rel}"

    @_synchronized
    def list_directory(self, target: dict, name_filter: str | None = None,
                       cursor: dict | None = None, limit: int = PAGE_SIZE,
                       sort: str = 'name', kind: str = 'all') -> dict:
        if sort not in ('name', 'name_desc', 'modified', 'modified_asc', 'type'):
            raise InvalidTarget('不支持的目录排序方式')
        if kind not in ('all', 'dir', 'file'):
            raise InvalidTarget('目录类型必须是 all、dir 或 file')
        resolved = self.resolve_target(target)
        if resolved["kind"] == "missing":
            raise TargetNotFound("目标目录不存在")
        if resolved["kind"] != "dir":
            raise CatalogError("目标不是目录")
        if name_filter is not None and not isinstance(name_filter, str):
            raise InvalidTarget("目录过滤条件必须是字符串")
        path = Path(resolved["path"])
        _, roots = self.find_project(resolved["project_id"])
        root = next(r for r in roots if r["root_id"] == resolved["root_id"])
        needle = (name_filter or "").casefold()
        key = json.dumps([resolved["project_id"], resolved["root_id"], resolved["relative_path"], needle, sort, kind])
        if cursor is not None:
            if not isinstance(cursor, dict) or cursor.get("project_id") != resolved["project_id"] \
                    or cursor.get("root_id") != resolved["root_id"] \
                    or cursor.get("relative_path") != resolved["relative_path"] \
                    or cursor.get("filter") != needle \
                    or cursor.get('sort', 'name') != sort or cursor.get('kind', 'all') != kind \
                    or not isinstance(cursor.get("snapshot_id"), str) \
                    or not cursor["snapshot_id"]:
                raise StaleCursor("游标与目标不匹配")
            if type(cursor.get("offset")) is not int or cursor["offset"] < 0:
                raise StaleCursor("游标位置无效，请刷新后重试")
        if type(limit) is not int or limit <= 0 or limit > MAX_PAGE_SIZE:
            limit = MAX_PAGE_SIZE
        entries: list[dict] = []
        fingerprints = []
        try:
            before = self._stat_version(io_path(path).stat())
            names = sorted(os.listdir(io_path(path)), key=lambda n: (natural_key(n), n))
        except PermissionError as error:
            raise TargetForbidden("读取目录被拒绝") from error
        except (FileNotFoundError, NotADirectoryError) as error:
            raise TargetNotFound("目标目录不存在") from error
        except OSError as error:
            raise CatalogError(f"读取目录失败：{error}") from error
        for name in names:
            rel = f"{resolved['relative_path']}/{name}" if resolved["relative_path"] else name
            if self._access(rel, root.get("subpaths") or [""]) == "forbidden":
                continue
            actual_rel = (path / name).relative_to(Path(root["path"]).resolve()).as_posix()
            if self._access(actual_rel, root.get("subpaths") or [""]) == "forbidden":
                continue
            entry_path = path / name
            info = None
            is_link = False
            try:
                link_info = io_path(entry_path).lstat()
                is_link = stat_module.S_ISLNK(link_info.st_mode) or bool(getattr(link_info, "st_reparse_tag", 0))
                fingerprints.append([name, self._stat_version(link_info)])
                entry_target = self._target_for_root(resolved["project_id"], root, self._validate_relative(rel))
                if entry_target["available"]:
                    info = io_path(entry_path).stat()
                    fingerprints.append([name, self._stat_version(info)])
            except (FileNotFoundError, NotADirectoryError) as error:
                raise StaleCursor("目录内容在读取时变化，请刷新后重试") from error
            except (TargetForbidden, InvalidTarget, OSError) as error:
                entry_target = {"kind": "blocked_link" if is_link else "blocked",
                                "native_path": None, "available": False, "reason": f"目标不可访问：{error}",
                                "navigation_only": False, "canonical_path": None}
            entry = {
                "name": name,
                "relative_path": rel,
                "size": info.st_size if info and entry_target["kind"] == "file" else None,
                "modified_at": _iso(info.st_mtime) if info else None,
                "is_link": is_link,
                **{k: entry_target[k] for k in ("kind", "native_path", "available", "reason", "navigation_only", "canonical_path")},
            }
            entries.append(entry)
        try:
            after = self._stat_version(io_path(path).stat())
        except OSError as error:
            raise StaleCursor("目录在读取时变化，请刷新后重试") from error
        if before != after:
            raise StaleCursor("目录内容在读取时变化，请刷新后重试")
        entries.sort(key=lambda e: (0 if e["kind"] == "dir" else 1, natural_key(e["name"]), e["name"]))
        version = hashlib.sha256(json.dumps([resolved, root, before, fingerprints, entries], sort_keys=True).encode()).hexdigest()
        entries = [e for e in entries if not needle or needle in e["name"].casefold()]
        entries = [e for e in entries if kind == 'all' or e['kind'] == kind]
        # 在分页前排序，后续页仍遵守同一全目录顺序；目录始终优先。
        if sort == 'name_desc':
            entries.sort(key=lambda e: (natural_key(e['name']), e['name']), reverse=True)
        elif sort == 'modified':
            entries.sort(key=lambda e: e['modified_at'] or '', reverse=True)
        elif sort == 'modified_asc':
            entries.sort(key=lambda e: (not bool(e['modified_at']), e['modified_at'] or ''))
        elif sort == 'type':
            entries.sort(key=lambda e: Path(e['name']).suffix.casefold())
        entries.sort(key=lambda e: e['kind'] != 'dir')
        summary = {'total': len(entries), 'directories': sum(e['kind'] == 'dir' for e in entries),
                   'files': sum(e['kind'] == 'file' for e in entries),
                   'bytes': sum(e['size'] or 0 for e in entries)}
        snapshot_id, entries = self.snapshots.capture(
            key, version, entries, cursor["snapshot_id"] if cursor is not None else None)
        start = cursor.get("offset", 0) if isinstance(cursor, dict) else 0
        if start > len(entries):
            raise StaleCursor("游标位置超出目录内容，请刷新后重试")
        page = entries[start:start + limit]
        next_cursor = None
        if start + len(page) < len(entries):
            next_cursor = {
                "project_id": resolved["project_id"],
                "root_id": resolved["root_id"],
                "relative_path": resolved["relative_path"],
                "filter": needle,
                "sort": sort,
                "kind": kind,
                "snapshot_id": snapshot_id,
                "offset": start + len(page),
            }
        return {
            "target": resolved,
            "entries": page,
            "next_cursor": next_cursor,
            "snapshot_id": snapshot_id,
            "summary": summary,
        }

    @staticmethod
    def _stat_version(info) -> tuple:
        # 不用秒级显示时间作为内容版本，替换同名文件也必须废弃旧游标。
        return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
                info.st_mtime_ns, info.st_ctime_ns)

    @staticmethod
    def _is_junction(path: Path) -> bool:
        try:
            stat = io_path(path).lstat()
            if hasattr(stat, "st_reparse_tag"):
                return bool(stat.st_reparse_tag)
        except OSError:
            pass
        try:
            return bool(os.path.realpath(path) != str(path.resolve()))
        except OSError:
            return False
