#!/usr/bin/env python3
"""刷新项目文档/资源双向入口；默认预演，--apply 写入，--check 验证。"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from datetime import date

from ._records import initialize_project, TASK_PATTERN, read_json
from ._paths import project_docs, project_readmes, task_dirs
from .layout import governance_paths, wiki


ROOT = None  # 由工作区参数或兼容入口提供，不按安装目录推断。
START = '<!-- dummysys-entry:start -->'
END = '<!-- dummysys-entry:end -->'


def block(text: str, content: str) -> str:
    section = f'{START}\n{content.rstrip()}\n{END}'
    if START in text:
        return re.sub(re.escape(START) + r'.*?' + re.escape(END), lambda _: section, text, flags=re.S)
    return text.rstrip() + '\n\n' + section + '\n'


def link(label: str, path: Path) -> str:
    return f'[{label}](<{path.as_posix()}>)'


def expected(root: Path, name: str) -> dict[Path, str]:
    if name in {'.', '..'} or '/' in name or '\\' in name:
        raise ValueError('项目名称必须是单个目录名')
    docs = project_docs(root, name)
    vault_project = docs.relative_to(root / 'dmy_vault').as_posix()
    resource = root / 'runtime' / 'project_src' / name
    readme = docs / 'README.md'
    if not readme.is_file():
        raise ValueError(f'先按项目模板建立 README：{readme}')
    naming = re.fullmatch(r'\[(\d{8})\](.+)', name)
    if not naming and name != '00-Playground':
        raise ValueError('项目目录名必须为 [yyyymmdd]title，日期取 README 的 created')
    created = re.search(r'(?m)^created:\s*["\']?(\d{4}-\d{2}-\d{2})', readme.read_text(encoding='utf-8'))
    if not created or (naming and created.group(1).replace('-', '') != naming.group(1)):
        raise ValueError(f'项目目录日期与 README created 不一致：{name}')
    rules = governance_paths(root)
    policy, protocol = rules['policy'], rules['protocol']
    index = docs / '目录索引.md'
    navigation = [
        '## 文档与资源入口',
        '',
        f'- 项目资源根：{link("资源 README", resource / "README.md")}；`{resource.as_posix()}`。',
        f'- 执行指令：[[{vault_project}/AGENTS|项目 AGENTS]]。',
        f'- 目录规则：{wiki(root, policy, "目录与资源治理")}（选择存储位置或迁移时读取）。',
        f'- Task/Run：{wiki(root, protocol, "项目与任务执行规范")}（创建、接续或执行时读取）。',
        '- 本 README 保存项目身份、背景、总体目标与路由；人审计划和进展进入项目管理正文，技术事实进入所属 Task/Run。',
        '',
        f'- 完整目录：{wiki(root, index, "文档、Task 与日志索引")}（查找历史或非精选正文时读取）。',
    ]
    from ._repositories import navigation as repo_navigation
    binding_path = resource / 'project.json'
    repos = read_json(binding_path).get('repositories', []) if binding_path.exists() else []
    repo_links = repo_navigation(root, repos)
    if repo_links:
        navigation.extend(repo_links)
    # 仅索引文档；不遍历运行资源。补齐现有阶段、日志和项目根文档的可达性。
    complete, archived_navigation = [], []
    for p in sorted(docs.rglob('*.md')):
        rel = p.relative_to(docs)
        if p in (readme, index) or p.name == 'AGENTS.md':
            continue
        target = p.relative_to(root / 'dmy_vault').with_suffix('').as_posix()
        (archived_navigation if rel.parts[0] == 'archive' else complete).append(f'- [[{target}|{rel.as_posix()}]]')
    if archived_navigation:
        complete.extend(['', '### 已归档内容', '', *archived_navigation])
    output = {readme: block(readme.read_text(encoding='utf-8'), '\n'.join(navigation))}
    index_front = (f'---\ntype: project-note\ntitle: "{name}目录索引"\nstatus: current\n'
                   f'created: {date.today()}\nupdated: {date.today()}\nproject: "[[{vault_project}/README]]"\n---\n\n'
                   '# 完整目录索引\n\n此页由项目文档目录派生；不代表审核采纳、质量验收或发布。\n')
    if index.exists() and START not in index.read_text(encoding='utf-8'):
        raise ValueError(f'派生索引路径已被人工正文占用，保留原文件：{index}')
    output[index] = block(index.read_text(encoding='utf-8') if index.exists() else index_front,
                          '## 当前内容\n\n' + '\n'.join(complete))
    # 普通专题 README 是人工正文，不能借入口同步改写。
    for task_dir in task_dirs(docs):
        p = task_dir / 'README.md'
        if not p.is_file():
            raise ValueError(f'Task 缺少 README：{task_dir}')
        links = []
        for child in sorted(p.parent.glob('*.md')):
            if child.name in {'README.md', 'AGENTS.md'}:
                continue
            target = child.relative_to(root / 'dmy_vault').with_suffix('').as_posix()
            links.append(f'- [[{target}|{child.stem}]]')
        links.append(f'- [[{vault_project}/README|返回项目入口与资源目录]]')
        if p.parent in task_dirs(docs):
            task_resource = resource / p.parent.name
            links.append(f'- {link("Task 范围声明与 Runs", task_resource)}')
            meta_path = task_resource / 'task.json'
            task_repos = read_json(meta_path).get('repositories', repos) if meta_path.exists() else repos
            links.extend(['', *repo_navigation(root, task_repos)] if task_repos else [])
        output[p] = block(p.read_text(encoding='utf-8'), '## 本目录文档索引\n\n' + '\n'.join(links))
    read_steps = (
        f'# {name} 项目执行入口\n\n'
        f'开始工作先读 {link("项目 README", readme)} 理解背景、目标与路由，'
        f'涉及源码、资源或执行时再读 {link("资源 README", resource / "README.md")} 定位本机绑定。\n\n'
        f'创建、接手 Task 或执行 Run 时读 {link("项目与任务执行规范", protocol)}；'
        f'选择写入位置或迁移资源时读 {link("目录治理", policy)}。\n\n'
        '项目规划、分工、阶段审阅和材料整理按 README 路由读取项目管理正文；'
        '具体执行读取所属 Task 的目标、范围和证据。按变化类型更新权威正文，过程写入日期日志；'
        f'文档分工和更新触发条件见 {wiki(root, protocol, "文档维护规则")}。\n'
    )
    agent = docs / 'AGENTS.md'
    front = (f'---\ntype: project-note\ntitle: "{name}执行入口"\nstatus: current\n'
             f'created: {date.today()}\nupdated: {date.today()}\nproject: "[[{vault_project}/README]]"\n---\n\n')
    output[agent] = block(agent.read_text(encoding='utf-8') if agent.exists() else front, read_steps)
    ra = resource / 'AGENTS.md'
    output[ra] = block(ra.read_text(encoding='utf-8') if ra.exists() else '',
                       f'# 项目执行入口\n\n先读 {link("文档侧项目 AGENTS", agent)}，再按其指引工作。\n')
    rr = resource / 'README.md'
    resource_text = (
        f'# {name} 项目资源\n\n'
        f'文档入口：{link("项目 README（背景与路由）", readme)}。\n\n'
        f'执行规则：{link("项目 AGENTS", resource / "AGENTS.md")}；{link("目录治理", policy)}。\n\n'
        '| 位置 | 用途 |\n|---|---|\n'
        '| `src/`、`tests/` | 临时实验与历史脚本；持续开发的源码和测试进入正式 Repo |\n'
        '| `configs/`、`inputs/` | 配置和输入 |\n'
        '| `project.json` | 项目配对与 repositories 关联；repo_id 经本机映射定位 |\n'
        '| `[task n][yyyymmdd]任务标题/` | task.json 范围声明；runs/ 保存新执行记录及产物 |\n'
        '| `archive/` | 历史资源；保留原字节和来源 |\n\n'
        '目录按需创建。此页只导航；人审进展按项目 README 路由，执行结论进入所属 Task/Run。\n'
    )
    output[rr] = block(rr.read_text(encoding='utf-8') if rr.exists() else '', resource_text)
    for path, content in output.items():
        if path.is_relative_to(docs) and path.exists() and content != path.read_text(encoding='utf-8'):
            output[path] = re.sub(r'(?m)^updated: .*$', f'updated: {date.today()}', content, count=1)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--project')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--apply', action='store_true')
    modes.add_argument('--check', action='store_true')
    args = parser.parse_args()
    names = [args.project] if args.project else [p.parent.name for p in project_readmes(args.root)]
    changed = []
    for name in names:
        expected(args.root, name)  # 在写入身份前验证项目命名和 README
        if args.apply:
            initialize_project(args.root, name)
        for path, content in expected(args.root, name).items():
            if path.exists() and path.read_text(encoding='utf-8') == content:
                continue
            changed.append(path)
            if args.apply:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding='utf-8')
    print(f'项目入口：{len(names)} 个项目；' + ('已刷新' if args.apply else '待刷新') + f' {len(changed)} 个文件')
    if args.check and changed:
        for path in changed:
            print(f'- {path}')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
