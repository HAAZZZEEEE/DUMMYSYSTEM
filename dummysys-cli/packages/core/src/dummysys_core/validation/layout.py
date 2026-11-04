#!/usr/bin/env python3
"""检查 DUMMYSYS Vault 内容与机器资产的目录边界。"""

from __future__ import annotations

from dummysys_core import locations as loc

from pathlib import Path
import sys
import argparse
import os
import json
import re


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


from dummysys_core._paths import project_docs, project_readmes

TEXT_DOCUMENT_SUFFIXES = {
    ".md",
    ".txt",
    ".html",
    ".htm",
}
OBSIDIAN_VIEW_SUFFIXES = {".base", ".canvas"}
ATTACHMENT_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp",
    ".pdf", ".doc", ".docx", ".odt", ".rtf", ".epub",
    ".mp3", ".wav", ".m4a", ".ogg", ".flac",
    ".mp4", ".webm", ".mov",
}
VAULT_SUFFIXES = TEXT_DOCUMENT_SUFFIXES | OBSIDIAN_VIEW_SUFFIXES | ATTACHMENT_SUFFIXES
SKIP_DIRECTORIES = {".git", ".obsidian", "runtime", ".cac", "__pycache__"}


def workspace_files(root: Path):
    """先剪枝再读文件，不进入机器环境或目录链接。"""
    locations = loc.load(root)
    for base in (root, locations.vault):
        for directory, dirs, files in os.walk(base, followlinks=False):
            dirs[:] = [name for name in dirs if name not in SKIP_DIRECTORIES
                       and Path(directory) / name not in (locations.vault, locations.runtime)
                       and not loc._linked(Path(directory) / name)]
            for name in files:
                yield Path(directory) / name


def validate_runtime(root: Path) -> list[str]:
    runtime = loc.runtime(root)
    if not runtime.exists():
        return []
    failures = []
    registry = runtime / 'state/workspace/compatibility.json'
    allowed = set()
    if registry.exists():
        try:
            entries = json.loads(registry.read_text(encoding='utf-8'))
            for entry in entries:
                source, target = Path(entry['source']), Path(entry['target'])
                loc.relative(root, source)
                loc.relative(root, target)
                allowed.add(source)
                if not source.exists() or not target.exists():
                    failures.append(f'兼容入口失效：{source}')
                elif source != runtime / 'projects' and not source.samefile(target):
                    failures.append(f'兼容入口目标不一致：{source}')
        except (ValueError, KeyError, TypeError, OSError) as error:
            failures.append(f'兼容清单无效：{error}')
    for path in runtime.iterdir():
        if path.name in {'AGENTS.md', 'README.md'} and path.is_file():
            continue
        if path.name in {'project_src', 'servers', 'cache', 'state', 'logs', 'tmp', 'inbox', 'workbench', 'envs'} and path.is_dir():
            continue
        failures.append(f'runtime 根部出现未登记资产：{path.name}')
    resources = runtime / 'project_src'
    legacy_file = runtime / 'state/workspace/legacy-project-paths.json'
    legacy = set()
    if legacy_file.exists():
        try:
            legacy = {Path(entry['path']) for entry in json.loads(legacy_file.read_text(encoding='utf-8'))}
        except (ValueError, KeyError, TypeError) as error:
            failures.append(f'历史项目路径清单无效：{error}')
    if resources.exists():
        for project in resources.iterdir():
            if project.name != '00-Playground' and not re.fullmatch(r'\[\d{8}\].+', project.name):
                failures.append(f'项目目录名应为 [yyyymmdd]title：{project.name}')
            if not project.is_dir():
                failures.append(f'项目资源根包含散文件：{project.name}')
                continue
            docs = project_docs(root, project.name)
            for path in [docs / 'README.md', docs / 'AGENTS.md', project / 'README.md', project / 'AGENTS.md']:
                if not path.is_file():
                    failures.append(f'缺少项目配对入口：{path}')
            for child in project.iterdir():
                if child in legacy:
                    continue
                if child.name in {'README.md', 'AGENTS.md', 'project.json', 'workbench.json'} and child.is_file():
                    continue
                if child.is_dir() and (child.name in {'src', 'tests', 'configs', 'inputs', 'archive', 'homepage', 'transfer-history'} or re.fullmatch(r'\[task [1-9]\d*\]\[\d{8}\].+', child.name)):
                    continue
                failures.append(f'项目根出现未登记资产：{child}')
        for readme in project_readmes(root):
            if not (resources / readme.parent.name / 'README.md').is_file():
                failures.append(f'文档项目缺少资源入口：{readme.parent.name}')
    return failures


def validate(root: Path) -> list[str]:
    vault = loc.vault(root)
    failures: list[str] = []
    from dummysys_core.layout import governance_paths
    try:
        canonical_agents = governance_paths(root)['instructions']
    except (ValueError, OSError) as error:
        return [f'治理布局无法解析：{error}']

    if not vault.is_dir():
        failures.append("缺少 dmy_vault 目录")

    for path in workspace_files(root):
        if not path.is_file() and not path.is_symlink():
            continue
        relative = loc.relative(root, path)
        if any(part in SKIP_DIRECTORIES for part in relative.parts):
            continue
        in_vault = relative.parts and relative.parts[0] == "dmy_vault"
        suffix = path.suffix.lower()
        is_text_document = suffix in TEXT_DOCUMENT_SUFFIXES
        is_vault_content = suffix in VAULT_SUFFIXES

        if in_vault and not is_vault_content:
            failures.append(f"dmy_vault 内出现不受支持的文件：{relative}")
        elif in_vault and suffix in ATTACHMENT_SUFFIXES:
            # 待整理的独立来源材料可暂存在收件箱；普通附件统一进入 80-附件。
            if len(relative.parts) < 2 or relative.parts[1] not in {"80-附件", "99-收件箱"}:
                failures.append(f"Vault 附件不在 80-附件 或 99-收件箱：{relative}")
        elif not in_vault and (is_text_document or suffix in OBSIDIAN_VIEW_SUFFIXES):
            if relative == Path("AGENTS.md") and canonical_agents.is_file():
                try:
                    same_file = path.samefile(canonical_agents)
                except OSError:
                    same_file = False
                if not same_file and path.read_text(encoding='utf-8') != loc.entry_pointer(root, canonical_agents):
                    failures.append("AGENTS.md 不是知识库权威文档的同文件链接或跨卷导航入口")
            elif relative.parts[0] == 'tools' and path.name in {'README.md', 'AGENTS.md'}:
                pass
            else:
                failures.append(f"dmy_vault 外出现文档：{relative}")

    for directory, dirs, _ in os.walk(vault, followlinks=False):
        for name in list(dirs):
            path = Path(directory) / name
            if (hasattr(path, 'is_junction') and path.is_junction()) or path.is_symlink():
                failures.append(f'Vault 中出现目录链接：{loc.relative(root, path)}')
                dirs.remove(name)
            elif name == '.obsidian':
                dirs.remove(name)
    if (root / 'tests').exists():
        failures.append('根部 tests 应收编到 tools/tests')
    failures.extend(validate_runtime(root))
    return failures


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True,help='显式指定待检查工作区')
    parser.add_argument('--json',action='store_true',help='输出结构化检查结果')
    args=parser.parse_args(argv)
    root = args.root.resolve()
    vault = loc.vault(root)
    failures = validate(root)
    if args.json:
        print(json.dumps(dict(schema_version=1,ok=not failures,failures=failures,workspace=str(root)),ensure_ascii=False))
        return 1 if failures else 0
    if failures:
        print("DUMMYSYS 目录检查：失败")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("DUMMYSYS 目录检查：通过")
    print(f"知识库：{vault}")
    print("规则：笔记、Obsidian 视图和受管附件放在 dmy_vault；机器文件和运行时文件放在外部。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
