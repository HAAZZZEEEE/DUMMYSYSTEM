#!/usr/bin/env python3
"""建立可读的 Task/Run 记录，检查身份、配对及声明范围；不执行作业或限制宿主权限。"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys
from uuid import UUID, uuid4

from ._paths import project_docs, project_readmes, task_dirs, project_link

ROOT = None  # 由工作区参数或兼容入口提供，不按安装目录推断。
TASK_PATTERN = r'\[task ([1-9]\d*)\]\[(\d{8})\](.+)'
TASK_STATUSES = {'active', 'blocked', 'awaiting_acceptance', 'completed', 'cancelled'}
RUN_STATUSES = {'planned', 'running', 'completed', 'failed', 'cancelled'}


def now():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def properties(path):
    from ._frontmatter import read
    raw = read(path)
    # 兼容旧调用方：统一转字符串表示，列表保持列表
    result = {}
    for k, v in raw.items():
        if isinstance(v, list):
            result[k] = v
        elif v is None:
            result[k] = ''
        elif isinstance(v, bool):
            result[k] = str(v).lower()
        else:
            result[k] = str(v)
    return result


def set_properties(path, values):
    from ._frontmatter import update
    update(path, values)


def valid_id(value):
    return str(UUID(value)) == value


def safe_name(name):
    if not name or name in {'.', '..'} or re.search(r'[<>:"/\\|?*\x00-\x1f]', name) or name.endswith((' ', '.')):
        raise ValueError('标题必须是有效的单层目录名')
    return name


def paired(root, name):
    safe_name(name)
    docs = project_docs(root, name)
    resources = root / 'runtime/project_src' / name
    for path in (docs, resources):
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('项目路径越出工作区')
    return docs, resources


def initialize_project(root, name):
    docs, resources = paired(root, name)
    props = properties(docs / 'README.md')
    project_id = props.get('project_id')
    if not project_id:
        project_id = str(uuid4())
        set_properties(docs / 'README.md', {'project_id': project_id})
    if not valid_id(project_id):
        raise ValueError(f'project_id 非法：{name}')
    path = resources / 'project.json'
    binding = read_json(path) if path.exists() else {'schema_version': 1, 'project_id': project_id, 'repositories': []}
    if binding.get('project_id') != project_id:
        raise ValueError(f'项目配对身份冲突：{name}')
    binding.update(docs_root=docs.relative_to(root).as_posix(), resource_root=resources.relative_to(root).as_posix())
    write_json(path, binding)
    for task in task_dirs(docs):
        task_resource = resources / task.name
        meta_path = task_resource / 'task.json'
        if meta_path.exists():
            meta = read_json(meta_path)
            if meta.get('task_id') != properties(task / 'README.md').get('task_id') or meta.get('project_id') != project_id:
                raise ValueError(f'Task 配对身份冲突：{task.name}')
            meta.update(docs_root=task.relative_to(root).as_posix(), resource_root=task_resource.relative_to(root).as_posix())
            write_json(meta_path, meta)
    return project_id


def refresh(root, name):
    from ._entries import expected
    for path, content in expected(root, name).items():
        if not path.exists() or path.read_text(encoding='utf-8') != content:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')


def unique_name(docs, resources, base, identity):
    safe_name(base)
    name = base
    if (docs / name).exists() or (resources / name).exists():
        name += '-' + identity[:8]
    if (docs / name).exists() or (resources / name).exists():
        raise ValueError('目录名冲突，请重试')
    return name


def create_task(root, project, title, origin, owner, goal, read_paths=(), write_paths=(), requires_acceptance=False):
    safe_name(title)
    if origin not in {'user', 'agent'} or not owner.strip() or not goal.strip():
        raise ValueError('Task 必须有来源、单一负责者和目标')
    docs, resources = paired(root, project)
    if properties(docs / 'README.md').get('status') != 'active':
        raise ValueError('先恢复项目为 active，再创建 Task')
    project_id = initialize_project(root, project)
    task_id = str(uuid4())
    numbers = [int(match[1]) for base in (docs, docs / 'archive', resources) if base.exists() for path in base.iterdir() if (match := re.fullmatch(TASK_PATTERN, path.name))]
    binding_path = resources / 'project.json'
    binding = read_json(binding_path)
    number = max(max(numbers, default=0), int(binding.get('task_number_high_watermark', 0))) + 1
    binding['task_number_high_watermark'] = number
    write_json(binding_path, binding)
    name = unique_name(docs, resources, f'[task {number}][{datetime.now():%Y%m%d}]{safe_name(title)}', task_id)
    doc = docs / name / 'README.md'
    resource = resources / name
    scope = {'read_paths': [str(Path(p).resolve()) for p in read_paths],
             'write_paths': [str(Path(p).resolve()) for p in write_paths], 'remote_resources': []}
    doc.parent.mkdir(parents=True)
    values = {'type': 'task', 'title': title, 'status': 'active', 'created': now()[:10], 'updated': now()[:10],
              'project': f'[[30-项目/{project}/README]]', 'project_id': project_id, 'task_id': task_id,
              'task_number': str(number), 'origin': origin, 'owner': owner, 'requires_acceptance': str(requires_acceptance).lower()}
    front = '\n'.join(f'{k}: {json.dumps(v, ensure_ascii=False)}' for k, v in values.items())
    doc.write_text(f'---\n{front}\n---\n\n# {title}\n\n来源：{"用户发起" if origin == "user" else "Agent 生成"}。\n\n## 目标与完成条件\n\n{goal}\n\n## 进展、产物与检查结果\n\n待记录；可链接已有权威报告。\n\n## 变更记录\n\n- {now()} 创建；负责者 `{owner}`。\n', encoding='utf-8')
    write_json(resource / 'task.json', {'schema_version': 1, 'task_id': task_id, 'project_id': project_id, 'scope': scope, 'docs_root': doc.parent.relative_to(root).as_posix(), 'resource_root': resource.relative_to(root).as_posix()})
    (resource / 'runs').mkdir(exist_ok=True)
    refresh(root, project)
    return {'task_id': task_id, 'document': str(doc), 'resources': str(resource)}


def locate_task(root, task_id):
    matches = []
    for doc in (task / 'README.md' for project in project_readmes(root) for task in task_dirs(project.parent)):
        if not re.fullmatch(TASK_PATTERN, doc.parent.name):
            continue
        props = properties(doc)
        if props.get('task_id') == task_id:
            matches.append((doc, props))
    if len(matches) != 1:
        raise ValueError(f'Task ID 应唯一匹配，实际 {len(matches)} 个')
    doc, props = matches[0]
    project = next(p.parent.name for p in project_readmes(root) if properties(p).get('project_id') == props['project_id'])
    resource = paired(root, project)[1] / doc.parent.name
    return doc, resource, props


def update_task(root, task_id, actor, status=None, owner=None, note='', accepted=False):
    doc, resource, props = locate_task(root, task_id)
    if actor != props['owner']:
        raise ValueError('仅当前负责者维护 Task 状态；其他会话提供 Run/证据')
    if not note.strip():
        raise ValueError('状态变化或交接须记录原因与结果')
    updates = {'updated': now()[:10]}
    if status:
        if status == 'active' and (doc.parent.parent.name == 'archive' or properties(project_docs(root, resource.parent.name) / 'README.md').get('status') == 'archived'):
            raise ValueError('先用归档工具恢复文档，再继续 Task')
        if status not in TASK_STATUSES:
            raise ValueError('Task 状态无效')
        if status == 'completed' and props.get('requires_acceptance') == 'true' and not accepted:
            raise ValueError('此 Task 明确要求用户验收；请先记录验收事实')
        if status == 'completed' and any(read_json(p)['status'] in {'planned', 'running'} for p in resource.glob('runs/*/run.json')):
            raise ValueError('还有未结束 Run，先核对实际执行状态')
        updates['status'] = status
    if owner is not None:
        if not owner.strip():
            raise ValueError('负责者不能为空')
        updates['owner'] = owner
    set_properties(doc, updates)
    with doc.open('a', encoding='utf-8') as stream:
        stream.write(f'\n- {now()} `{actor}`：{note}；{json.dumps(updates, ensure_ascii=False)}。\n')
    return str(doc)


def create_run(root, task_id, title, actor, command, host, source, inputs, retry_of=None):
    doc, resource, props = locate_task(root, task_id)
    if props.get('owner') == 'unassigned':
        raise ValueError('先登记历史 Task 的当前负责者，再创建新 Run')
    if props['status'] in {'completed', 'cancelled'}:
        raise ValueError('先恢复原 Task，再创建 Run')
    if not all(x.strip() for x in (actor, command, host, source, inputs)):
        raise ValueError('Run 必须记录执行者、命令、节点、源码身份和输入身份；未知请明确写 unknown')
    if retry_of and not any(read_json(p).get('run_id') == retry_of for p in resource.glob('runs/*/run.json')):
        raise ValueError('retry_of 必须指向同一 Task 已有 Run')
    run_id = str(uuid4())
    name = unique_name(resource / 'runs', resource / 'runs', f'[{datetime.now():%Y%m%d-%H%M%S}]{safe_name(title)}', run_id)
    path = resource / 'runs' / name / 'run.json'
    write_json(path, {'schema_version': 1, 'run_id': run_id, 'task_id': task_id, 'project_id_at_start': props['project_id'],
                     'title': title, 'actor': actor, 'status': 'planned', 'created_at': now(), 'started_at': None,
                     'finished_at': None, 'host': host, 'source': source, 'inputs': inputs, 'command': command,
                     'retry_of': retry_of, 'exit_code': None, 'result': None, 'evidence': []})
    return {'run_id': run_id, 'record': str(path)}


def update_run(root, task_id, run_id, actor, status, result='', exit_code=None, evidence=()):
    """旧签名兼容；实际语义委托给 mutate_run。"""
    return mutate_run(root, task_id, run_id, actor, status=status, result=result or None,
                      exit_code=exit_code, evidence=list(evidence) or None)


def mutate_run(root, task_id, run_id, actor, *, status=None, result=None, exit_code=None,
               evidence=None, host=None, source=None, inputs=None, command=None, add_evidence=None,
               finish_authorization=None):
    """Run 更新：planned 可改输入；running 仅补写 result/追加 evidence；terminal 拒绝执行事实修改。"""
    from ._management import read_sidecar, is_deleted
    _, resource, _ = locate_task(root, task_id)
    matches = [p for p in resource.glob('runs/*/run.json') if read_json(p).get('run_id') == run_id]
    if len(matches) != 1:
        raise ValueError('Run ID 不唯一或不存在')
    path = matches[0]
    record = read_json(path)
    sidecar = read_sidecar(path)
    if is_deleted(sidecar):
        raise ValueError('已删除 Run 仅允许查询和 undelete')
    current = record['status']
    delegated = actor != record['actor']
    if delegated:
        if not (finish_authorization or '').strip():
            raise ValueError('Run 由其执行者维护；代收尾须提供用户授权来源')
        if current not in {'planned', 'running'} or status not in {'completed', 'failed', 'cancelled'}:
            raise ValueError('授权代收尾仅适用于未结束 Run 的终态登记')
        if any(v is not None for v in (host, source, inputs, command)) or add_evidence is not None:
            raise ValueError('授权代收尾不可修改执行输入')
        if not evidence or not (result or '').strip():
            raise ValueError('授权代收尾须记录结果边界与证据')
    if status and status != current:
        allowed = {'planned': {'running', 'cancelled'}, 'running': {'completed', 'failed', 'cancelled'}}
        if status not in allowed.get(current, set()):
            raise ValueError('Run 状态转换无效；已结束执行重试应新建 Run')
        if status in {'completed', 'failed', 'cancelled'} and not (result or record.get('result', '')).strip():
            raise ValueError('结束 Run 必须记录结果及未验证边界')
        if status == 'completed':
            final_evidence = list(record.get('evidence', []))
            if add_evidence:
                for item in add_evidence:
                    if item not in final_evidence:
                        final_evidence.append(item)
            if evidence:
                final_evidence = list(evidence)
            if exit_code != 0 or not final_evidence:
                raise ValueError('完成执行须记录退出码 0 和证据；质量验收在 result 中单独说明')
        if status == 'running' and record['started_at'] is None:
            record['started_at'] = now()
        if status in {'completed', 'failed', 'cancelled'}:
            record['finished_at'] = now()
        record['status'] = status
    elif current == 'running' and any(v is not None for v in (host, source, inputs, command)):
        raise ValueError('running Run 仅可补写 result 和追加 evidence')
    elif current in {'completed', 'failed', 'cancelled'} and any(v is not None for v in (host, source, inputs, command, exit_code)):
        raise ValueError('terminal Run 拒绝执行事实修改')
    if host is not None:
        record['host'] = host
    if source is not None:
        record['source'] = source
    if inputs is not None:
        record['inputs'] = inputs
    if command is not None:
        record['command'] = command
    if result is not None:
        record['result'] = result
    if exit_code is not None:
        record['exit_code'] = exit_code
    if evidence is not None:
        record['evidence'] = list(evidence)
    if add_evidence:
        existing = record.setdefault('evidence', [])
        for item in add_evidence:
            if item not in existing:
                existing.append(item)
    if delegated:
        record['closeout'] = dict(actor=actor, authorization=finish_authorization.strip(),
                                  recorded_at=now(), previous_status=current)
    write_json(path, record)
    return str(path)


def rename_run(root, task_id, run_id, actor, title):
    """仅改展示名称到 sidecar display_title；原 title 和证据目录保留。"""
    from ._management import write_sidecar, read_sidecar, is_deleted
    _, resource, _ = locate_task(root, task_id)
    matches = [p for p in resource.glob('runs/*/run.json') if read_json(p).get('run_id') == run_id]
    if len(matches) != 1:
        raise ValueError('Run ID 不唯一或不存在')
    path = matches[0]
    record = read_json(path)
    sidecar = read_sidecar(path)
    if is_deleted(sidecar):
        raise ValueError('已删除 Run 仅允许查询和 undelete')
    if actor != record['actor']:
        raise ValueError('Run 由其执行者维护')
    if not title.strip():
        raise ValueError('展示名称不能为空')
    write_sidecar(path, {'display_title': title})
    return str(path)


def manage_run(root, task_id, run_id, actor, action, reason):
    """Run 管理操作：archive/unarchive/delete/undelete（sidecar）。"""
    from ._management import write_sidecar, read_sidecar, is_deleted, is_archived, now as mgmt_now
    _, resource, _ = locate_task(root, task_id)
    matches = [p for p in resource.glob('runs/*/run.json') if read_json(p).get('run_id') == run_id]
    if len(matches) != 1:
        raise ValueError('Run ID 不唯一或不存在')
    path = matches[0]
    record = read_json(path)
    sidecar = read_sidecar(path)
    if not reason.strip():
        raise ValueError('管理操作必须记录原因')
    is_run_actor = actor == record['actor']
    if action in ('archive', 'delete'):
        if not is_run_actor:
            raise ValueError('仅 Run 执行者可归档或删除')
        if record['status'] in ('planned', 'running'):
            raise ValueError('归档/删除仅接受 terminal Run')
        if is_deleted(sidecar) and action == 'archive':
            raise ValueError('已删除 Run 不可归档')
        if action == 'archive':
            write_sidecar(path, {'archived_at': mgmt_now(), 'archived_by': actor, 'archive_reason': reason})
        else:
            write_sidecar(path, {'deleted_at': mgmt_now(), 'deleted_by': actor,
                                 'delete_reason': reason, 'delete_operation_id': ''})
    elif action == 'unarchive':
        if is_deleted(sidecar):
            raise ValueError('先 undelete 再 unarchive')
        if not is_archived(sidecar):
            raise ValueError('Run 未归档')
        write_sidecar(path, {'archived_at': None, 'archived_by': None, 'archive_reason': None})
    elif action == 'undelete':
        if not is_deleted(sidecar):
            raise ValueError('Run 未删除')
        write_sidecar(path, {'deleted_at': None, 'deleted_by': None,
                             'delete_reason': None, 'delete_operation_id': None})
    else:
        raise ValueError(f'未知管理操作：{action}')
    return str(path)


def create_project(root, title, created=None):
    """创建完整项目（文档 + 资源配对）。"""
    safe_name(title)
    date_part = (created or now()[:10]).replace('-', '')
    if not re.fullmatch(r'\d{8}', date_part):
        raise ValueError('created 必须是 YYYY-MM-DD 格式')
    name = f'[{date_part}]{title}'
    docs = root / 'dmy_vault/30-项目' / name
    resources = root / 'runtime/project_src' / name
    if docs.exists() or resources.exists():
        raise ValueError('项目目录名已占用')
    docs.mkdir(parents=True)
    resources.mkdir(parents=True)
    project_id = str(uuid4())
    values = {'type': 'project', 'title': title, 'status': 'active',
              'created': f'{date_part[:4]}-{date_part[4:6]}-{date_part[6:]}',
              'updated': now()[:10], 'project_id': project_id}
    front = '\n'.join(f'{k}: {json.dumps(v, ensure_ascii=False)}' for k, v in values.items())
    (docs / 'README.md').write_text(
        f'---\n{front}\n---\n\n# {title}\n\n## 文档与资源入口\n\n'
        f'- 项目资源根：`{resources.relative_to(root).as_posix()}`。\n',
        encoding='utf-8')
    write_json(resources / 'project.json', {
        'schema_version': 1, 'project_id': project_id,
        'docs_root': docs.relative_to(root).as_posix(),
        'resource_root': resources.relative_to(root).as_posix(),
        'repositories': [], 'task_number_high_watermark': 0,
    })
    return {'project_id': project_id, 'document': str(docs / 'README.md'), 'name': name}


def update_project(root, name, title=None, aliases=None, description=None):
    """更新展示标题、aliases 和受管说明段，不移动目录。"""
    docs, resources = paired(root, name)
    readme = docs / 'README.md'
    updates = {'updated': now()[:10]}
    if title is not None:
        if not title.strip():
            raise ValueError('标题不能为空')
        updates['title'] = title
    if aliases is not None:
        updates['aliases'] = aliases if isinstance(aliases, list) else [aliases]
    if description is not None:
        updates['description'] = description
    set_properties(readme, updates)
    return str(readme)


def set_project_status(root, name, status, actor, reason):
    """Project 生命周期：active↔paused。归档/删除走专用入口。"""
    docs, resources = paired(root, name)
    readme = docs / 'README.md'
    props = properties(readme)
    if props.get('deleted_at'):
        raise ValueError('已删除对象仅允许查询和 undelete')
    current = props.get('status')
    if name == '00-Playground' and status != 'active':
        raise ValueError('Playground 保持常设 active')
    transitions = {'active': {'paused'}, 'paused': {'active'}}
    if status not in transitions.get(current, set()):
        raise ValueError(f'项目状态转换无效：{current} → {status}')
    if not reason.strip():
        raise ValueError('状态变化须记录原因')
    set_properties(readme, {'status': status, 'updated': now()[:10]})
    with readme.open('a', encoding='utf-8') as stream:
        stream.write(f'\n- {now()} `{actor}`：{reason}；status={status}。\n')
    return str(readme)


def delete_object(root, kind, identity, actor, reason, operation_id=''):
    """逻辑删除 P/T/R；写标记即可，不搬目录、不删除文件。"""
    from ._management import set_deleted, read_sidecar, is_deleted
    if not reason.strip():
        raise ValueError('删除必须记录原因')
    if kind == 'run':
        task_id, run_id = identity
        _, resource, _ = locate_task(root, task_id)
        matches = [p for p in resource.glob('runs/*/run.json') if read_json(p).get('run_id') == run_id]
        if len(matches) != 1:
            raise ValueError('Run ID 不唯一或不存在')
        path = matches[0]
        record = read_json(path)
        sidecar = read_sidecar(path)
        if is_deleted(sidecar):
            raise ValueError('已删除')
        if record['status'] in ('planned', 'running'):
            raise ValueError('删除要求目标及全部后代无 planned/running Run')
        set_deleted(path, actor, reason, operation_id, is_sidecar=True)
        return str(path)
    if kind == 'task':
        doc, resource, props = locate_task(root, identity)
        if props.get('deleted_at'):
            raise ValueError('已删除')
        for run_path in resource.glob('runs/*/run.json'):
            run = read_json(run_path)
            if run.get('status') in ('planned', 'running'):
                raise ValueError('存在未结束 Run，不可删除')
        set_deleted(doc, actor, reason, operation_id)
        return str(doc)
    if kind == 'project':
        docs, resources = paired(root, identity)
        if identity == '00-Playground':
            raise ValueError('Playground 不允许删除')
        readme = docs / 'README.md'
        props = properties(readme)
        if props.get('deleted_at'):
            raise ValueError('已删除')
        for task_dir in task_dirs(docs):
            task_res = resources / task_dir.name
            for run_path in task_res.glob('runs/*/run.json'):
                run = read_json(run_path)
                if run.get('status') in ('planned', 'running'):
                    raise ValueError('存在未结束 Run，不可删除')
        set_deleted(readme, actor, reason, operation_id)
        return str(readme)
    raise ValueError(f'未知对象类型：{kind}')


def undelete_object(root, kind, identity, actor, reason):
    """恢复逻辑删除；仅撤销本对象标记。"""
    from ._management import clear_deleted, read_sidecar, is_deleted
    if not reason.strip():
        raise ValueError('恢复必须记录原因')
    if kind == 'run':
        task_id, run_id = identity
        _, resource, _ = locate_task(root, task_id)
        matches = [p for p in resource.glob('runs/*/run.json') if read_json(p).get('run_id') == run_id]
        if len(matches) != 1:
            raise ValueError('Run ID 不唯一或不存在')
        path = matches[0]
        if not is_deleted(read_sidecar(path)):
            raise ValueError('Run 未删除')
        clear_deleted(path, is_sidecar=True)
        return str(path)
    if kind == 'task':
        doc, resource, props = locate_task(root, identity)
        if not props.get('deleted_at'):
            raise ValueError('Task 未删除')
        # 祖先删除时拒绝单独恢复
        project_name = resource.parent.name
        project_docs, _ = paired(root, project_name)
        project_props = properties(project_docs / 'README.md')
        if project_props.get('deleted_at'):
            raise ValueError('先恢复父项目，再恢复 Task')
        clear_deleted(doc)
        return str(doc)
    if kind == 'project':
        docs, resources = paired(root, identity)
        readme = docs / 'README.md'
        props = properties(readme)
        if not props.get('deleted_at'):
            raise ValueError('项目未删除')
        clear_deleted(readme)
        return str(readme)
    raise ValueError(f'未知对象类型：{kind}')


def scope_report(scope, reads=(), writes=()):
    findings = []
    for action, paths, declared in [('read', reads, scope['read_paths'] + scope['write_paths']), ('write', writes, scope['write_paths'])]:
        roots = [Path(p).resolve() for p in declared]
        for raw in paths:
            resolved = Path(raw).resolve()
            findings.append({'action': action, 'path': str(resolved), 'within_declared_scope': any(resolved.is_relative_to(p) for p in roots)})
    return {'mode': 'report_only', 'coverage': '仅检查调用方提供的本机路径；未审计实际执行或远端权限',
            'findings': findings, 'all_within_declared_scope': all(x['within_declared_scope'] for x in findings) if findings else None}


def resolve_evidence(root, value):
    path = Path(value)
    registry = root / 'runtime/state/workspace/retired-paths.json'
    mappings = read_json(registry) if registry.exists() else []
    # 保留历史执行记录的原始路径，按最长前缀逐步解析已登记迁移。
    visited = set()
    for _ in range(len(mappings) + 1):
        if path.exists() or str(path) in visited:
            return path
        visited.add(str(path))
        for entry in sorted(mappings, key=lambda x: len(x['source']), reverse=True):
            source = Path(entry['source'])
            if path.is_relative_to(source):
                path = Path(entry['target']) / path.relative_to(source)
                break
        else:
            return path
    return path


def check(root):
    failures, seen = [], set()
    def identity(value, label):
        try:
            if not valid_id(value) or value in seen:
                raise ValueError()
            seen.add(value)
        except (ValueError, TypeError, AttributeError):
            failures.append(f'身份无效或重复：{label}')
    for readme in project_readmes(root):
        try:
            name = readme.parent.name
            docs, resources = paired(root, name)
            props = properties(readme)
            if (props.get('status') == 'archived') != (docs.parent.name == 'archive'):
                failures.append(f'项目状态与归档位置不一致：{name}')
            pid = props.get('project_id')
            identity(pid, name)
            binding = read_json(resources / 'project.json')
            if binding.get('project_id') != pid or binding.get('docs_root') != docs.relative_to(root).as_posix() or binding.get('resource_root') != resources.relative_to(root).as_posix():
                failures.append(f'项目绑定不一致：{name}')
            for base in (docs, resources):
                for child in base.iterdir():
                    if child.name == 'tasks' or re.match(r'^(stage|topic)\d+', child.name):
                        failures.append(f'旧任务目录尚未迁移：{child}')
            doc_paths = {p.name: p for p in task_dirs(docs)}
            doc_names = set(doc_paths)
            if len(task_dirs(docs)) != len(doc_paths):
                failures.append(f'Task 同时存在于活动区和归档区：{name}')
            res_names = {p.name for p in resources.iterdir() if p.name.startswith('[task ')}
            numbers = [re.fullmatch(TASK_PATTERN, n)[1] for n in doc_names if re.fullmatch(TASK_PATTERN, n)]
            if len(numbers) != len(set(numbers)):
                failures.append(f'Task 编号重复：{name}')
            if doc_names != res_names:
                failures.append(f'Task 两侧目录不一致：{name}')
            for task_name in sorted(doc_names):
                try:
                    if not re.fullmatch(TASK_PATTERN, task_name):
                        failures.append(f'Task 名称不可读：{task_name}')
                    task = properties(doc_paths[task_name] / 'README.md')
                    identity(task.get('task_id'), task_name)
                    match = re.fullmatch(TASK_PATTERN, task_name)
                    if not match or match[2] != task.get('created', '').replace('-', '') or match[1] != task.get('task_number'):
                        failures.append(f'Task 日期与 created 不一致：{task_name}')
                    resource = resources / task_name
                    meta = read_json(resource / 'task.json')
                    if task.get('project_id') != pid or meta.get('project_id') != pid or meta.get('task_id') != task.get('task_id'):
                        failures.append(f'Task 配对身份不一致：{task_name}')
                    if task.get('project') != project_link(root, docs) or task.get('origin') not in {'user', 'agent'} or not task.get('owner') or task.get('status') not in TASK_STATUSES:
                        failures.append(f'Task 归属、来源、负责者或状态无效：{task_name}')
                    if 'docs_root' in meta and (meta['docs_root'] != doc_paths[task_name].relative_to(root).as_posix() or meta.get('resource_root') != resource.relative_to(root).as_posix()):
                        failures.append(f'Task 路径绑定不一致：{task_name}')
                    if (doc_paths[task_name].parent.name == 'archive'
                            and task.get('status') not in {'completed', 'cancelled'}
                            and task.get('archive_unfinished_confirmed') is not True):
                        failures.append(f'未完成 Task 归档缺少显式确认：{task_name}')
                    if (docs.parent.name == 'archive'
                            and task.get('status') not in {'completed', 'cancelled'}
                            and props.get('archive_unfinished_confirmed') is not True):
                        failures.append(f'项目含未完成 Task，归档缺少显式确认：{task_name}')
                    scope = meta['scope']
                    for key in ('read_paths', 'write_paths', 'remote_resources'):
                        if not isinstance(scope.get(key), list):
                            failures.append(f'Task 范围缺少列表 {key}：{task_name}')
                    for key in ('read_paths', 'write_paths'):
                        if any(not Path(p).is_absolute() for p in scope.get(key, [])):
                            failures.append(f'Task 声明范围应为绝对路径：{task_name}')
                    runs = []
                    for folder in (resource / 'runs').iterdir():
                        record = read_json(folder / 'run.json')
                        runs.append(record)
                        if any(not record.get(k) for k in ('host', 'source', 'inputs', 'command', 'created_at')):
                            failures.append(f'Run 输入或执行身份记录不全：{folder.name}')
                        if record.get('status') in {'running', 'completed', 'failed'} and not record.get('started_at'):
                            failures.append(f'Run 缺少实际开始时间：{folder.name}')
                        if record.get('status') in {'completed', 'failed', 'cancelled'} and (not record.get('finished_at') or not record.get('result')):
                            failures.append(f'Run 缺少结束时间或结果：{folder.name}')
                        for evidence in record.get('evidence', []):
                            if Path(evidence).is_absolute() and not resolve_evidence(root, evidence).exists():
                                failures.append(f'Run 本机证据不存在：{evidence}')
                        identity(record.get('run_id'), folder.name)
                        if not re.fullmatch(r'\[\d{8}-\d{6}\].+', folder.name):
                            failures.append(f'Run 名称不可读：{folder.name}')
                        if record.get('task_id') != task.get('task_id') or record.get('status') not in RUN_STATUSES or not record.get('actor'):
                            failures.append(f'Run 归属或状态无效：{folder.name}')
                        if not valid_id(record.get('project_id_at_start', '')):
                            failures.append(f'Run 缺少执行时项目身份：{folder.name}')
                        if record.get('status') == 'completed' and (record.get('exit_code') != 0 or not record.get('evidence') or not record.get('result')):
                            failures.append(f'Run 完成记录不全：{folder.name}')
                    ids = {r['run_id'] for r in runs}
                    if any(r.get('retry_of') and (r['retry_of'] not in ids or r['retry_of'] == r['run_id']) for r in runs):
                        failures.append(f'Run 重试关系无效：{task_name}')
                    if task.get('status') == 'completed' and any(r['status'] in {'planned', 'running'} for r in runs):
                        failures.append(f'已完成 Task 仍有未结束 Run：{task_name}')
                except (ValueError, KeyError, TypeError, AttributeError, OSError) as error:
                    failures.append(f'Task 记录错误 {task_name}：{error}')
        except (ValueError, KeyError, TypeError, AttributeError, OSError) as error:
            failures.append(f'项目记录错误 {readme.parent.name}：{error}')
    from ._repositories import check as check_repositories
    failures.extend(check_repositories(root))
    return failures


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    sub = parser.add_subparsers(dest='operation', required=True)
    sub.add_parser('check', help='只读检查全部 Project/Task/Run')
    task = sub.add_parser('task', help='创建 Task；未指定项目时归入 Playground')
    task.add_argument('--project', default='00-Playground')
    task.add_argument('--title', required=True)
    task.add_argument('--origin', choices=['user', 'agent'], required=True)
    task.add_argument('--owner', required=True)
    task.add_argument('--goal', required=True)
    task.add_argument('--read-path', action='append', default=[])
    task.add_argument('--write-path', action='append', default=[])
    task.add_argument('--requires-acceptance', action='store_true')
    update = sub.add_parser('task-update', help='当前负责者更新状态、交接或恢复同一 Task')
    update.add_argument('--task', required=True)
    update.add_argument('--actor', required=True)
    update.add_argument('--status', choices=sorted(TASK_STATUSES))
    update.add_argument('--owner')
    update.add_argument('--note', required=True)
    update.add_argument('--accepted', action='store_true', help='记录已经发生的用户验收；不代表工具代替用户批准')
    run = sub.add_parser('run', help='创建 planned 记录；不提交或启动执行')
    run.add_argument('--task', required=True)
    for key in ['title', 'actor', 'command', 'host', 'source', 'inputs']:
        run.add_argument('--' + key, required=True)
    run.add_argument('--retry-of')
    finish = sub.add_parser('run-update', help='记录实际开始、观察或结束结果')
    for key in ['task', 'run', 'actor']:
        finish.add_argument('--' + key, required=True)
    finish.add_argument('--status', choices=sorted(RUN_STATUSES), required=True)
    finish.add_argument('--result', default='')
    finish.add_argument('--exit-code', type=int)
    finish.add_argument('--evidence', action='append', default=[])
    scope = sub.add_parser('scope-check', help='只报告所提供路径与 Task 声明范围的关系')
    scope.add_argument('--task', required=True)
    scope.add_argument('--read-path', action='append', default=[])
    scope.add_argument('--write-path', action='append', default=[])
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        if args.operation == 'check':
            failures = check(root)
            result = {'ok': not failures, 'failures': failures}
        elif args.operation == 'task':
            result = create_task(root, args.project, args.title, args.origin, args.owner, args.goal, args.read_path, args.write_path, args.requires_acceptance)
        elif args.operation == 'task-update':
            result = update_task(root, args.task, args.actor, args.status, args.owner, args.note, args.accepted)
        elif args.operation == 'run':
            result = create_run(root, args.task, args.title, args.actor, args.command, args.host, args.source, args.inputs, args.retry_of)
        elif args.operation == 'run-update':
            result = update_run(root, args.task, args.run, args.actor, args.status, args.result, args.exit_code, args.evidence)
        else:
            _, resource, _ = locate_task(root, args.task)
            result = scope_report(read_json(resource / 'task.json')['scope'], args.read_path, args.write_path)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if args.operation == 'check' and failures else 0
    except (ValueError, KeyError, OSError) as error:
        parser.exit(2, f'记录失败：{error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
