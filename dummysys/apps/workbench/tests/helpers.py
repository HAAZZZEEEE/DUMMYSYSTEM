"""测试夹具：构造临时治理工作区。

真实 project.json 的 docs_root/resource_root 相对 workspace_root 解析；
repositories.json 的 checkout 路径为绝对路径。README 使用 YAML Properties，
与 Obsidian 知识库规范一致。
"""
from __future__ import annotations

import json
from pathlib import Path


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _yaml_scalar(value) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(json.dumps(v, ensure_ascii=False) for v in value) + "]"
    return str(value)


def build_workspace(root: Path, projects: dict, checkouts: dict | None = None) -> Path:
    """构造 workspace。

    projects: {name: {project_id, docs_root, resource_root, repositories, status,
                      title, aliases, readme_frontmatter_extra}}
    返回 workspace 根目录（workspace_root）。
    """
    ws = root / "workspace"
    for name, spec in projects.items():
        entry = ws / "runtime" / "project_src" / name
        binding = {"schema_version": 1, "project_id": spec["project_id"]}
        if spec.get("docs_root"):
            binding["docs_root"] = spec["docs_root"]
        if spec.get("resource_root"):
            binding["resource_root"] = spec["resource_root"]
        if spec.get("repositories") is not None:
            binding["repositories"] = spec["repositories"]
        write_json(entry / "project.json", binding)
        if spec.get("docs_root"):
            readme = ws / spec["docs_root"] / "README.md"
            readme.parent.mkdir(parents=True, exist_ok=True)
            front = ["---"]
            front.append(f"project_id: {_yaml_scalar(spec['project_id'])}")
            front.append(f"title: {_yaml_scalar(spec.get('title', name))}")
            front.append(f"status: {_yaml_scalar(spec.get('status', 'active'))}")
            if spec.get("aliases"):
                front.append(f"aliases: {_yaml_scalar(spec['aliases'])}")
            for k, v in (spec.get("frontmatter_extra") or {}).items():
                front.append(f"{k}: {_yaml_scalar(v)}")
            front.append("---")
            readme.write_text("\n".join(front) + f"\n# {name}\n", encoding="utf-8")
    if checkouts:
        write_json(ws / "runtime/state/workspace/repositories.json", {"schema_version": 1, "checkouts": checkouts})
    return ws


def build_application(workspace: Path, task_root: Path, dmy=None, **apps):
    """构造可注入 web 测试的 Application（RecordingOpener、RecordingDmy）。"""
    from workbench.application import Application
    from workbench.catalog import Catalog
    from workbench.windows import RecordingOpener

    config = {
        "schema_version": 1,
        "workspace_root": workspace,
        "task_root": task_root,
        "port": 0,
        "apps": {
            "vscode_exe": apps.get("vscode_exe", "Code.exe"),
            "edge_exe": apps.get("edge_exe", "msedge.exe"),
            "obsidian_vault_path": apps.get("obsidian_vault_path"),
        },
        "config_path": str(task_root / "configs" / "workbench.local.json"),
    }
    catalog = Catalog(config)
    opener = RecordingOpener()
    application = Application(catalog, opener, dmy_runner=dmy)
    application.set_preferences_path(task_root / "state" / "preferences.json")
    return application, opener
