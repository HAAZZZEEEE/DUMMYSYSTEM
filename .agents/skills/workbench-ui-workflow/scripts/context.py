#!/usr/bin/env python3
"""Resolve a DUMMYSYS workspace and its Workbench workflow without mutations."""
import argparse
import json
from pathlib import Path


def resolve(workspace: Path) -> dict:
    workspace = workspace.expanduser().resolve()
    manifest = json.loads((workspace / ".dummysys-workspace.json").read_text())
    def location(value):
        path = Path(value).expanduser()
        return path.resolve() if path.is_absolute() else (workspace / path).resolve()
    runtime = location(manifest["runtime_root"])
    vault = location(manifest["vault_root"])
    registry = json.loads((runtime / "state/workspace/repositories.json").read_text())
    repo = Path(registry["checkouts"]["dummysystem"]["path"]).expanduser().resolve()
    app = repo / "dummysys/apps/workbench"
    if not (app / "workbench/static/index.html").is_file():
        raise ValueError("The bound checkout does not contain Workbench.")
    tools = runtime / "design-tools"
    return {
        "workspace": str(workspace), "vault": str(vault), "runtime": str(runtime),
        "repo": str(repo), "app": str(app), "tools_root": str(tools),
        "product": str(app / "PRODUCT.md"), "design": str(app / "DESIGN.md"),
        "installed_tools": str(tools / "installed.json"),
        "browser": str(tools / "bin/agent-browser"),
        "impeccable": str(tools / "bin/impeccable"),
        "variate": str(tools / "bin/variate"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = resolve(args.workspace)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"Cannot resolve Workbench: {error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
