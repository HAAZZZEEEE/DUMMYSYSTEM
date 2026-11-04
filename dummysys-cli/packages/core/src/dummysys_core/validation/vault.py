#!/usr/bin/env python3
"""校验 DUMMYSYS Obsidian Vault 的 Properties、链接、Base 和状态契约。"""

from __future__ import annotations

from dummysys_core import locations as loc

from collections import defaultdict
from datetime import date
from pathlib import Path, PurePosixPath
import re
import sys
import argparse
import json
from urllib.parse import unquote


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.DOTALL)
FENCED_CODE = re.compile(r"(?ms)^\s*(```|~~~).*?^\s*\1\s*$")
INLINE_CODE = re.compile(r"`[^`\n]*`")
WIKILINK = re.compile(r"!?\[\[([^\n]+?)\]\]")
MARKDOWN_LINK = re.compile(r"!?\[[^\]\n]*\]\(([^)\n]+)\)")
PROJECT_STATUS_LABELS = {
    "active": "进行中",
    "paused": "已暂停",
    "archived": "已归档",
}
TYPE_STATUSES = {
    "home": {"active"},
    "glossary": {"active"},
    "system": {"active", "superseded"},
    "decision": {"proposed", "accepted", "superseded"},
    "moc": {"active"},
    "knowledge": {"draft", "recorded", "verified", "deprecated"},
    "project": {"active", "paused", "archived"},
    "task": {"active", "blocked", "awaiting_acceptance", "completed", "cancelled"},
    "project-reference": {"current", "superseded"},
    "project-note": {"draft", "current", "superseded"},
    "project-log": {"recorded"},
    "project-conclusion": {"draft", "final"},
    "inbox": {"untriaged", "processing"},
}
COMMON_REQUIRED = ("type", "title", "status", "created", "updated")
DATE_PROPERTIES = ("created", "updated", "verified")
LIST_PROPERTIES = ("aliases", "tags")
PROJECT_CHILD_TYPES = {
    "task",
    "project-reference",
    "project-note",
    "project-log",
    "project-conclusion",
}
AGENT_CANONICAL = PurePosixPath("10-系统/Codex工作区指令.md")
KNOWN_VAULT_SUFFIXES = {
    ".md", ".base", ".canvas", ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".svg", ".pdf", ".mp3", ".wav", ".m4a", ".mp4", ".webm", ".html", ".htm",
}
BASE_SCOPES = {
    PurePosixPath("20-知识/知识库.base"): 'file.inFolder("20-知识")',
    PurePosixPath("30-项目/项目库.base"): 'file.inFolder("30-项目")',
    PurePosixPath("99-收件箱/收件箱.base"): 'file.inFolder("99-收件箱")',
}


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def parse_frontmatter(text: str) -> tuple[dict[str, object], str] | None:
    """解析本 Vault 使用的扁平 Obsidian Properties 子集。"""
    match = FRONTMATTER.match(text.replace("\r\n", "\n"))
    if not match:
        return None
    properties: dict[str, object] = {}
    current_list: str | None = None
    for number, raw in enumerate(match.group(1).splitlines(), start=2):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        list_match = re.fullmatch(r"\s+-\s+(.+?)\s*", raw)
        if list_match and current_list:
            value = properties[current_list]
            assert isinstance(value, list)
            value.append(_unquote(list_match.group(1)))
            continue
        key_match = re.fullmatch(r"([A-Za-z][A-Za-z0-9_-]*):(?:\s*(.*))?", raw)
        if not key_match:
            raise ValueError(f"第 {number} 行不是受支持的扁平 Property：{raw}")
        key, raw_value = key_match.groups()
        if key in properties:
            raise ValueError(f"Property 重复：{key}")
        if raw_value is None or not raw_value.strip():
            properties[key] = []
            current_list = key
        else:
            properties[key] = _unquote(raw_value)
            current_list = None
    return properties, match.group(0)


def expected_type(path: PurePosixPath) -> str | None:
    parts = path.parts
    if parts and parts[0] == '30-项目':
        if len(parts) > 1 and parts[1] == 'archive':
            parts = parts[:1] + parts[2:]
        if len(parts) > 2 and parts[2] == 'archive':
            parts = parts[:2] + parts[3:]
    if path == PurePosixPath("CONTEXT.md"):
        return "glossary"
    if path == AGENT_CANONICAL:
        return None
    if not parts:
        return None
    if len(parts) == 1:
        return None
    if parts[0] == "00-入口":
        return "home" if path.name == "DUMMYSYS.md" else "system"
    if parts[0] == "10-系统":
        return "decision" if "决策" in parts else "system"
    if parts[0] == "20-知识":
        return "moc" if path.name == "知识库索引.md" else "knowledge"
    if parts[0] == "30-项目":
        if path.name == "项目索引.md":
            return "moc"
        if len(parts) == 3 and path.name == "README.md":
            return "project"
        if len(parts) == 4 and re.fullmatch(r"\[task [1-9]\d*\]\[\d{8}\].+", parts[2]) and path.name == "README.md":
            return "task"
        if "日志" in parts:
            return "project-log"
        if "reference" in parts:
            return "project-reference"
        if path.name == "结项.md":
            return "project-conclusion"
        return "project-note"
    if parts[0] == "80-附件":
        return "system"
    if parts[0] == "90-模板":
        return None
    if parts[0] == "99-收件箱":
        return "moc" if path.name == "收件箱.md" else "inbox"
    return None


def _iso_date(value: object) -> date | None:
    text = str(value)
    if text == "{{date}}":
        return None
    return date.fromisoformat(text)


def _without_code(text: str) -> str:
    text = FENCED_CODE.sub("", text)
    return INLINE_CODE.sub("", text)


def _normalize_path(path: PurePosixPath) -> PurePosixPath:
    parts: list[str] = []
    for part in path.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return PurePosixPath(*parts)


def _target_candidates(
    source: PurePosixPath,
    target: str,
    all_paths: dict[str, PurePosixPath],
    stems: dict[str, list[PurePosixPath]],
    aliases: dict[str, list[PurePosixPath]],
) -> list[PurePosixPath]:
    normalized = unquote(target.strip()).replace("\\", "/")
    if not normalized:
        return []
    normalized = normalized.split("#", 1)[0].split("^", 1)[0].strip()
    if not normalized:
        return [source]
    key = normalized.lower()
    if "/" in normalized or PurePosixPath(normalized).suffix:
        direct = _normalize_path(PurePosixPath(normalized))
        exact = all_paths.get(direct.as_posix().lower())
        if exact:
            return [exact]
        if not any(normalized.lower().endswith(suffix) for suffix in KNOWN_VAULT_SUFFIXES):
            direct = PurePosixPath(f"{direct.as_posix()}.md")
        result = all_paths.get(direct.as_posix().lower())
        if result:
            return [result]
        relative = _normalize_path(source.parent / direct)
        result = all_paths.get(relative.as_posix().lower())
        return [result] if result else []

    local = source.parent / f"{normalized}.md"
    result = all_paths.get(local.as_posix().lower())
    if result:
        return [result]
    return stems.get(key, []) or aliases.get(key, [])


def _markdown_target(source: PurePosixPath, raw: str) -> PurePosixPath | None:
    raw = raw.strip()
    target = raw[1:raw.index('>')] if raw.startswith('<') and '>' in raw else raw.split(maxsplit=1)[0]
    target = unquote(target).split("#", 1)[0]
    if not target or target.startswith(("http://", "https://", "mailto:", "obsidian://", "#")):
        return None
    if re.match(r"^[A-Za-z]:[/\\]", target) or target.startswith("/"):
        return None
    return _normalize_path(source.parent / PurePosixPath(target.replace("\\", "/")))


BASE_DEPENDENCY_UNAVAILABLE = '校验 .base 需要 PyYAML'


def _load_base(path: Path) -> tuple[object | None, str | None]:
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return None, BASE_DEPENDENCY_UNAVAILABLE
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        return None, str(error)
    return value, None


def _strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)


def validate(root: Path, *, unavailable=None) -> list[str]:
    vault = loc.vault(root)
    if not vault.is_dir():
        return ['缺少 dmy_vault 目录，未执行 Vault 检查']
    failures: list[str] = []
    from dummysys_core.layout import governance_paths
    try:
        layout = governance_paths(root)
    except (ValueError, OSError) as error:
        return [f'治理布局无法解析：{error}']
    canonical = PurePosixPath(layout['instructions'].relative_to(vault).as_posix())
    template_root = PurePosixPath(layout['templates'].relative_to(vault).as_posix())
    def legacy_type_path(relative):
        # 治理职责不因收进项目目录变成业务 project-note。
        for key, legacy in [('entry', '00-入口'), ('system', '10-系统'), ('templates', '90-模板')]:
            prefix = PurePosixPath(layout[key].relative_to(vault).as_posix())
            if relative.is_relative_to(prefix):
                return PurePosixPath(legacy) / relative.relative_to(prefix)
        return relative
    markdown = sorted(vault.rglob("*.md"))
    all_files = sorted(
        path for path in vault.rglob("*")
        if path.is_file() and ".obsidian" not in path.relative_to(vault).parts
    )
    relative_files = [PurePosixPath(path.relative_to(vault).as_posix()) for path in all_files]
    all_paths = {path.as_posix().lower(): path for path in relative_files}
    stems: dict[str, list[PurePosixPath]] = defaultdict(list)
    aliases: dict[str, list[PurePosixPath]] = defaultdict(list)
    parsed: dict[PurePosixPath, tuple[dict[str, object], str]] = {}
    graph: dict[PurePosixPath, set[PurePosixPath]] = defaultdict(set)

    for path in markdown:
        relative = PurePosixPath(path.relative_to(vault).as_posix())
        text = path.read_text(encoding="utf-8")
        stems[path.stem.lower()].append(relative)
        try:
            result = parse_frontmatter(text)
        except ValueError as error:
            failures.append(f"{relative}: Properties 无法解析：{error}")
            continue
        if result is None:
            if relative != canonical:
                failures.append(f"{relative}: 缺少 Properties")
            continue
        properties, block = result
        parsed[relative] = (properties, text)
        if len(relative.parts) == 1 and relative != PurePosixPath("CONTEXT.md"):
            failures.append(f"{relative}: Vault 根部只保留 CONTEXT.md；普通笔记进入既定分区")
        for alias in properties.get("aliases", []):
            aliases[str(alias).lower()].append(relative)

        for key in COMMON_REQUIRED:
            if not properties.get(key):
                failures.append(f"{relative}: 缺少必填 Property `{key}`")
        note_type = str(properties.get("type", ""))
        status = str(properties.get("status", ""))
        if note_type not in TYPE_STATUSES:
            failures.append(f"{relative}: 未知 type `{note_type}`")
        elif status not in TYPE_STATUSES[note_type]:
            failures.append(f"{relative}: type `{note_type}` 不允许 status `{status}`")
        inferred = expected_type(legacy_type_path(relative))
        if inferred and note_type != inferred:
            failures.append(f"{relative}: 路径要求 type `{inferred}`，实际为 `{note_type}`")
        for key in LIST_PROPERTIES:
            if key in properties and not isinstance(properties[key], list):
                failures.append(f"{relative}: `{key}` 必须使用 YAML 列表")
        dates: dict[str, date] = {}
        for key in DATE_PROPERTIES:
            if key not in properties:
                continue
            try:
                value = _iso_date(properties[key])
                if value:
                    dates[key] = value
            except ValueError:
                failures.append(f"{relative}: `{key}` 必须使用 YYYY-MM-DD")
        if dates.get("updated") and dates.get("created") and dates["updated"] < dates["created"]:
            failures.append(f"{relative}: updated 早于 created")
        if dates.get("verified") and dates.get("updated") and dates["verified"] > dates["updated"]:
            failures.append(f"{relative}: verified 晚于 updated")
        if note_type == "knowledge" and status == "verified" and not properties.get("verified"):
            failures.append(f"{relative}: verified 知识缺少 `verified` 日期")
        if note_type in PROJECT_CHILD_TYPES:
            project = str(properties.get("project", ""))
            if not project:
                failures.append(f"{relative}: 项目子笔记缺少 `project` Link")
            elif not re.fullmatch(r"\[\[30-项目/(?:archive/)?[^/\n]+/README(?:\|[^\n]+)?\]\]", project):
                failures.append(f"{relative}: `project` 必须链接项目根 README")
        commit = str(properties.get("source_commit", ""))
        if commit and not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
            failures.append(f"{relative}: `source_commit` 必须是完整 40 位 commit")
        if not re.search(r"(?m)^#\s+\S", text[len(block):]):
            failures.append(f"{relative}: 正文缺少一级标题")

    for alias, paths in aliases.items():
        if len(paths) > 1:
            joined = "、".join(str(path) for path in paths)
            failures.append(f"alias `{alias}` 指向多个笔记：{joined}")

    linked_files: set[PurePosixPath] = set()
    for source, (_, text) in parsed.items():
        if source.is_relative_to(template_root):
            continue
        scan = _without_code(text)
        for raw in WIKILINK.findall(scan):
            target = raw.split("|", 1)[0].strip()
            candidates = _target_candidates(source, target, all_paths, stems, aliases)
            if not candidates:
                failures.append(f"{source}: Wiki Link 无法解析：[[{target}]]")
            elif len(candidates) > 1:
                joined = "、".join(str(path) for path in candidates)
                failures.append(f"{source}: Wiki Link 有歧义：[[{target}]] -> {joined}")
            else:
                linked_files.add(candidates[0])
                graph[source].add(candidates[0])
        for raw in MARKDOWN_LINK.findall(scan):
            value = raw.strip()
            value = value[1:value.index('>')] if value.startswith('<') and '>' in value else value.split(maxsplit=1)[0]
            value = unquote(value).split('#', 1)[0]
            # 工作区外仓库链接由其仓库维护；本工作区资源入口在此核验实际可达性。
            if re.match(r'^[A-Za-z]:[/\\]', value) or value.startswith('/'):
                local = Path(value)
                if any(local.resolve().is_relative_to(base) for base in (root.resolve(), loc.vault(root), loc.runtime(root))) and not local.exists():
                    failures.append(f'{source}: 工作区资源链接无法解析：{value}')
                continue
            target = _markdown_target(source, raw)
            if target is None:
                continue
            normalized = PurePosixPath(target.as_posix())
            if normalized.as_posix().lower() not in all_paths and value.lower() in all_paths:
                # Obsidian 的绝对链接格式是相对 Vault 根，不以 / 开头。
                normalized = PurePosixPath(value)
            if normalized.as_posix().lower() not in all_paths:
                failures.append(f"{source}: Markdown 本地链接无法解析：{raw}")
            else:
                resolved = all_paths[normalized.as_posix().lower()]
                linked_files.add(resolved)
                graph[source].add(resolved)

    for path in vault.rglob("*.base"):
        relative = PurePosixPath(path.relative_to(vault).as_posix())
        value, error = _load_base(path)
        if error:
            if error == BASE_DEPENDENCY_UNAVAILABLE and unavailable is not None:
                unavailable.append(dict(check='base_yaml',path=str(relative),reason=error,
                                        next_action='使用已安装 PyYAML 的解释器运行同一校验器，或补齐该解释器依赖'))
                continue
            failures.append(f"{relative}: Base YAML 无法解析：{error}")
            continue
        if not isinstance(value, dict) or not isinstance(value.get("views"), list) or not value["views"]:
            failures.append(f"{relative}: Base 必须包含至少一个 view")
        required_scope = BASE_SCOPES.get(relative)
        if required_scope and required_scope not in set(_strings(value)):
            failures.append(f"{relative}: Base 缺少目录范围过滤 `{required_scope}`")
        if relative not in linked_files:
            failures.append(f"{relative}: Base 未被任何 MOC 嵌入或链接")

    for path in all_files:
        relative = PurePosixPath(path.relative_to(vault).as_posix())
        if relative.parts and relative.parts[0] == "80-附件" and path.suffix.lower() != ".md":
            if relative not in linked_files:
                failures.append(f"{relative}: 附件未被任何笔记引用")

    for relative, (properties, text) in parsed.items():
        if properties.get("type") != "project":
            continue
        match = re.search(r"(?m)^\| 管理状态 \|\s*([^|]+?)\s*\|$", text)
        if not match:
            continue
        status = str(properties.get("status", ""))
        expected = PROJECT_STATUS_LABELS.get(status)
        actual = match.group(1).strip()
        if expected and actual != expected:
            failures.append(
                f"{relative}: Properties status `{status}` 与生命周期表“{actual}”不一致"
            )

    # 首页与各 Project README 都是独立阅读入口。创建项目无需手工修改
    # 全局首页；每个项目内部仍检查显式链接可达性。
    home = PurePosixPath("00-入口/DUMMYSYS.md")
    if home in parsed:
        reachable = {home} | {path for path, (props, _) in parsed.items() if props.get('type') == 'project'}
        pending = list(reachable)
        while pending:
            source = pending.pop()
            for target in graph.get(source, set()):
                if target not in reachable:
                    reachable.add(target)
                    pending.append(target)
        for relative, (properties, _) in parsed.items():
            if relative == home or relative.parts[0] in {"90-模板", "99-收件箱"}:
                continue
            if properties.get("type") == "inbox":
                continue
            if relative not in reachable:
                failures.append(f"{relative}: 无法沿显式链接从 Vault 首页到达")

    return failures


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True,help='显式指定待检查工作区')
    parser.add_argument('--json',action='store_true',help='输出结构化检查结果')
    args=parser.parse_args(argv)
    root = args.root.resolve()
    unavailable=[]
    failures = validate(root,unavailable=unavailable)
    if args.json:
        print(json.dumps(dict(schema_version=1,ok=not failures and not unavailable,failures=failures,
                              unavailable=unavailable,workspace=str(root),
                              coverage='Properties、链接、附件与项目状态；Base YAML 覆盖见 unavailable'),ensure_ascii=False))
        return 1 if failures or unavailable else 0
    if failures or unavailable:
        print("DUMMYSYS Vault 检查：失败")
        for failure in failures:
            print(f"- {failure}")
        for item in unavailable:
            print(f"- 无法执行 {item['check']}：{item['path']}；{item['reason']}；{item['next_action']}")
        return 1
    print("DUMMYSYS Vault 检查：通过")
    print("规则：Properties、链接、Base、附件引用和项目状态均满足契约。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
