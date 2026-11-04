#!/usr/bin/env python3
"""登记 Repo、绑定本机 checkout、关联 Project/Task，并保存 Run 的源码证据。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile

from ._records import (ROOT, locate_task, now, paired, properties, read_json,
                          refresh, write_json)
from ._paths import project_readmes, task_dirs
from .layout import governance_paths, wiki


def repo_key(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z0-9][a-z0-9._-]*', value):
        raise ValueError('repo_id 必须是稳定的小写字母、数字、点、横线或下划线标识')
    return value


def catalog(root):
    result = {}
    for path in sorted(governance_paths(root)['repositories'].glob('*.md')):
        meta = properties(path)
        key = repo_key(meta.get('repo_id'))
        if key in result:
            raise ValueError(f'Repo 身份重复：{key}')
        result[key] = dict(meta, document=path.relative_to(root).as_posix())
    return result


def mapping_path(root):
    return root / 'runtime/state/workspace/repositories.json'


def mappings(root):
    path = mapping_path(root)
    data = read_json(path) if path.exists() else {'schema_version': 1, 'checkouts': {}}
    if not isinstance(data, dict) or data.get('schema_version') != 1 or not isinstance(data.get('checkouts'), dict):
        raise ValueError('本机 Repo 映射格式无效')
    return data


def git(path, *args, check=True):
    proc = subprocess.run(['git', '-C', str(path), *args], capture_output=True)
    if check and proc.returncode:
        raise ValueError(proc.stderr.decode('utf-8', errors='replace').strip())
    return proc


def checkout_root(path):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError('checkout 必须是绝对路径')
    path = path.resolve(strict=True)
    top = Path(git(path, 'rev-parse', '--show-toplevel').stdout.decode('utf-8').strip()).resolve()
    if top != path:
        raise ValueError('绑定必须指向 Git checkout 根，不能是仓库内子目录')
    return path


def register(root, key, title, purpose):
    key = repo_key(key)
    if key in catalog(root):
        raise ValueError('Repo 已登记；修改权威登记文档即可，不重建身份')
    if not title.strip() or not purpose.strip():
        raise ValueError('Repo 必须有标题和用途')
    path = governance_paths(root)['repositories'] / f'{key}.md'
    if path.exists():
        raise ValueError('登记文档已存在')
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = dict(type='system', title=title, status='active', created=now()[:10], updated=now()[:10], repo_id=key)
    front = '\n'.join(f'{k}: {json.dumps(v, ensure_ascii=False)}' for k, v in fields.items())
    path.write_text(f'---\n{front}\n---\n\n# {title}\n\n{purpose}\n\n'
                    f'关联与定位规则见 {wiki(root, governance_paths(root)["policy"])}。本机 checkout 由 runtime 映射解析。\n', encoding='utf-8')
    return str(path)


def bind(root, key, path):
    if repo_key(key) not in catalog(root):
        raise ValueError('先登记 Repo 身份')
    path = checkout_root(path)
    data = mappings(root)
    for other, value in data['checkouts'].items():
        if other != key and Path(value['path']).resolve() == path:
            raise ValueError('同一个 checkout 已绑定其他 repo_id')
    data['checkouts'][key] = {'path': str(path)}
    write_json(mapping_path(root), data)
    return data['checkouts'][key]


def validate_paths(paths):
    if not isinstance(paths, list) or not paths:
        raise ValueError('paths 必须是非空列表；整个仓库使用 ["."]')
    for value in paths:
        if not isinstance(value, str) or not value or '\\' in value or ':' in value or value.startswith('/') or '..' in value.split('/'):
            raise ValueError(f'仓库子路径必须是仓库内的相对路径：{value}')


def validate_refs(root, refs, parent=None):
    if not isinstance(refs, list):
        raise ValueError('repositories 必须是列表')
    known, seen = catalog(root), set()
    for ref in refs:
        if not isinstance(ref, dict):
            raise ValueError('repositories 每项必须是对象')
        key = ref.get('repo_id')
        if key is None:
            if not isinstance(ref.get('path'), str) or not Path(ref['path']).is_absolute():
                raise ValueError('旧绑定必须包含绝对 path')
            continue  # 保持历史 role/path 兼容，不强制登记旧仓库。
        if repo_key(key) not in known or key in seen:
            raise ValueError(f'Repo 未登记或重复引用：{key}')
        seen.add(key)
        paths = ref.get('paths', ['.'])
        validate_paths(paths)
        if parent is not None:
            base = next((r for r in parent if r.get('repo_id') == key), None)
            if base is None:
                raise ValueError(f'Task Repo 不在 Project 范围内：{key}')
            allowed = base.get('paths', ['.'])
            for path in paths:
                if not any(Path(path).is_relative_to(Path(p)) for p in allowed):
                    raise ValueError(f'Task 子路径超出 Project 范围：{path}')


def references(root, project=None, task=None):
    if task:
        _, resource, _ = locate_task(root, task)
        base = read_json(resource.parent / 'project.json').get('repositories', [])
        validate_refs(root, base)
        refs = read_json(resource / 'task.json').get('repositories', base)
        validate_refs(root, refs, base)
    else:
        _, resource = paired(root, project)
        refs = read_json(resource / 'project.json').get('repositories', [])
        validate_refs(root, refs)
    return refs


def associate(root, key, paths, project=None, task=None):
    ref = {'repo_id': repo_key(key), 'paths': paths}
    if task:
        _, resource, _ = locate_task(root, task)
        path = resource / 'task.json'
        parent = read_json(resource.parent / 'project.json').get('repositories', [])
        name = resource.parent.name
    else:
        _, resource = paired(root, project)
        path, parent, name = resource / 'project.json', None, project
    data = read_json(path)
    refs = [r for r in data.get('repositories', []) if r.get('repo_id') != key] + [ref]
    validate_refs(root, refs, parent)
    if not task:
        docs, _ = paired(root, name)
        for folder in task_dirs(docs):
            meta = read_json(resource / folder.name / 'task.json')
            if 'repositories' in meta:
                validate_refs(root, meta['repositories'], refs)
    data['repositories'] = refs
    write_json(path, data)
    refresh(root, name)
    return refs


def resolve(root, project=None, task=None):
    result, local = [], mappings(root)['checkouts']
    for ref in references(root, project, task):
        key = ref.get('repo_id')
        if key and key not in local:
            raise ValueError(f'Repo 尚未绑定本机 checkout：{key}')
        path = checkout_root(local[key]['path'] if key else ref['path'])
        paths = ref.get('paths', ['.'])
        validate_paths(paths)
        for sub in paths:
            target = (path / sub).resolve(strict=True)
            if not target.is_relative_to(path):
                raise ValueError(f'子路径经链接越出仓库：{sub}')
        result.append(dict(ref, path=str(path)))
    return result


def navigation(root, refs):
    """生成逻辑导航；本机路径从映射解析，派生区块不拥有身份或关联。"""
    lines = []
    for ref in refs:
        key = ref.get('repo_id')
        if key:
            record = catalog(root).get(key)
            if record is None:
                raise ValueError(f'Repo 未登记：{key}')
            target = Path(record['document']).relative_to('dmy_vault').with_suffix('').as_posix()
            lines.append(f'- [[{target}|{key}]]：`' + '`、`'.join(ref.get('paths', ['.'])) + '`。')
    return ['### 代码仓库', '', *lines, '', '本机位置使用 `repository_records.py resolve` 解析；关联不等于写入授权。', ''] if lines else []


def capture(refs, destination):
    """在调用方准备目录采集 Git 证据，不修改工作树。"""
    records = []
    for index, ref in enumerate(refs):
        path = Path(ref['path'])
        head = git(path, 'rev-parse', 'HEAD').stdout.decode().strip()
        branch = git(path, 'symbolic-ref', '--quiet', '--short', 'HEAD', check=False).stdout.decode().strip() or None
        status = git(path, 'status', '--porcelain=v1', '-z', '--untracked-files=all').stdout
        diff = git(path, 'diff', '--binary', '--no-ext-diff', '--no-textconv', 'HEAD', '--').stdout
        untracked = git(path, 'ls-files', '--others', '--exclude-standard', '-z').stdout
        folder = destination / str(index)
        folder.mkdir(parents=True)
        (folder / 'worktree.patch').write_bytes(diff)
        (folder / 'status.bin').write_bytes(status)
        untracked_hashes = {}
        with zipfile.ZipFile(folder / 'untracked.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
            for raw in untracked.split(b'\0'):
                if raw:
                    name = raw.decode('utf-8')
                    source = path / name
                    if source.is_symlink() or not source.resolve().is_relative_to(path):
                        raise ValueError(f'未跟踪文件含外链或符号链接，需单独取证：{name}')
                    payload = source.read_bytes()
                    archive.writestr(name, payload)
                    untracked_hashes[name] = hashlib.sha256(payload).hexdigest()
        if any(hashlib.sha256((path / name).read_bytes()).hexdigest() != digest for name, digest in untracked_hashes.items()):
            raise ValueError('取证期间未跟踪源码发生变化，请停写后创建新的 Run')
        if git(path, 'status', '--porcelain=v1', '-z', '--untracked-files=all').stdout != status or git(path, 'diff', '--binary', '--no-ext-diff', '--no-textconv', 'HEAD', '--').stdout != diff or git(path, 'rev-parse', 'HEAD').stdout.decode().strip() != head:
            raise ValueError('取证期间源码发生变化，请停写后创建新的 Run')
        hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
        records.append(dict(ref, commit=head, branch=branch, dirty=bool(status), captured_at=now(),
                            evidence='source-snapshot/' + str(index), sha256=hashes,
                            scope='HEAD + 工作区补丁 + 未忽略的未跟踪文件；不包含忽略文件、子模块内部或LFS对象'))
    return records


def verify_capture(records, destination):
    """提交证据前核对实际源码仍与采集结果相同。"""
    for index, record in enumerate(records):
        path = Path(record['path'])
        folder = destination / str(index)
        if (git(path, 'rev-parse', 'HEAD').stdout.decode().strip() != record['commit']
                or git(path, 'status', '--porcelain=v1', '-z', '--untracked-files=all').stdout != (folder / 'status.bin').read_bytes()
                or git(path, 'diff', '--binary', '--no-ext-diff', '--no-textconv', 'HEAD', '--').stdout != (folder / 'worktree.patch').read_bytes()):
            raise ValueError('取证期间源码发生变化，请停写后重新提交')
        with zipfile.ZipFile(folder / 'untracked.zip') as archive:
            for name in archive.namelist():
                source = path / name
                if source.is_symlink() or not source.resolve().is_relative_to(path.resolve()) or source.read_bytes() != archive.read(name):
                    raise ValueError('取证期间未跟踪源码发生变化')


def check(root):
    failures = []
    try:
        known = catalog(root)
        for key, value in mappings(root)['checkouts'].items():
            if key not in known:
                raise ValueError(f'本机绑定没有对应登记：{key}')
            checkout_root(value['path'])
    except (ValueError, OSError, KeyError, TypeError) as error:
        failures.append(f'Repo 登记或本机绑定错误：{error}')
    for readme in project_readmes(root):
        name = readme.parent.name
        try:
            refs = references(root, project=name)
            local = mappings(root)['checkouts']
            for ref in refs:
                key = ref.get('repo_id')
                if key:
                    if key not in local:
                        raise ValueError(f'Repo 缺少本机映射：{key}')
                    path = checkout_root(local[key]['path'])
                    for sub in ref.get('paths', ['.']):
                        if not (path / sub).resolve(strict=True).is_relative_to(path):
                            raise ValueError(f'Repo 子路径越出仓库：{sub}')
            for folder in task_dirs(readme.parent):
                task_id = properties(folder / 'README.md')['task_id']
                task_refs = references(root, task=task_id)
                if task_refs and all(r.get('repo_id') for r in task_refs):
                    resolve(root, task=task_id)
        except (ValueError, OSError, KeyError, TypeError) as error:
            failures.append(f'Repo 关联错误 {name}：{error}')
    return failures


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    sub = parser.add_subparsers(dest='operation', required=True)
    p = sub.add_parser('register', help='登记稳定 Repo 身份，不创建 Git 仓库')
    for key in ('repo', 'title', 'purpose'):
        p.add_argument('--' + key, required=True)
    p = sub.add_parser('bind', help='登记或更新本机 checkout')
    p.add_argument('--repo', required=True)
    p.add_argument('--path', type=Path, required=True)
    for command in ('link', 'resolve'):
        p = sub.add_parser(command, help='关联仓库' if command == 'link' else '解析有效仓库位置')
        target = p.add_mutually_exclusive_group(required=True)
        target.add_argument('--project')
        target.add_argument('--task')
        if command == 'link':
            p.add_argument('--repo', required=True)
            p.add_argument('--subpath', action='append', default=[])
    p = sub.add_parser('snapshot', help='保存 running Run 的源码版本与未提交改动')
    for key in ('task', 'run', 'actor'):
        p.add_argument('--' + key, required=True)
    sub.add_parser('check', help='检查身份、本机绑定和关联契约')
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        if args.operation == 'register':
            result = register(root, args.repo, args.title, args.purpose)
        elif args.operation == 'bind':
            result = bind(root, args.repo, args.path)
        elif args.operation == 'link':
            result = associate(root, args.repo, args.subpath or ['.'], args.project, args.task)
        elif args.operation == 'resolve':
            result = resolve(root, args.project, args.task)
        elif args.operation == 'snapshot':
            result = snapshot(root, args.task, args.run, args.actor)
        else:
            failures = check(root)
            result = {'ok': not failures, 'failures': failures}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return int(args.operation == 'check' and bool(failures))
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(2, f'Repo 操作失败：{error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
