"""Run 管理 sidecar、删除标记和编号高水位。"""
from __future__ import annotations

from dummysys_core import locations as loc

import json
from pathlib import Path

from ._records import read_json, write_json, now


def sidecar_path(run_record):
    return Path(run_record).parent / 'run-management.json'


def read_sidecar(run_record):
    path = sidecar_path(run_record)
    if not path.exists():
        return {'schema_version': 1, 'run_id': read_json(run_record).get('run_id')}
    return read_json(path)


def write_sidecar(run_record, updates):
    path = sidecar_path(run_record)
    data = read_sidecar(run_record)
    data.update(updates)
    data.setdefault('schema_version', 1)
    data.setdefault('run_id', read_json(run_record).get('run_id'))
    write_json(path, data)
    return data


def effective_status(record, sidecar):
    """返回 (effective_status, blocked_reasons)。"""
    blocked = []
    status = record.get('status', 'unknown')
    if sidecar.get('deleted_at'):
        blocked.append('对象已逻辑删除，仅允许查询和 undelete')
        return 'deleted', blocked
    if sidecar.get('archived_at'):
        if status in ('planned', 'running'):
            blocked.append('归档 Run 必须是终态')
        return 'archived', blocked
    return status, blocked


def set_deleted(doc_or_sidecar_path, actor, reason, operation_id, is_sidecar=False):
    fields = {'deleted_at': now(), 'deleted_by': actor,
              'delete_reason': reason, 'delete_operation_id': operation_id}
    if is_sidecar:
        write_sidecar(doc_or_sidecar_path, fields)
    else:
        from ._frontmatter import update
        update(doc_or_sidecar_path, fields)
    return fields


def clear_deleted(doc_or_sidecar_path, is_sidecar=False):
    if is_sidecar:
        write_sidecar(doc_or_sidecar_path, {'deleted_at': None, 'deleted_by': None,
                                            'delete_reason': None, 'delete_operation_id': None})
    else:
        from ._frontmatter import update
        update(doc_or_sidecar_path, {'deleted_at': None, 'deleted_by': None,
                                     'delete_reason': None, 'delete_operation_id': None})


def is_deleted(props_or_sidecar):
    return bool(props_or_sidecar.get('deleted_at'))


def is_archived(props_or_sidecar):
    return bool(props_or_sidecar.get('archived_at') or props_or_sidecar.get('status') == 'archived')


def high_watermark_path(root, project_name):
    return loc.runtime(Path(root)) / 'project_src' / project_name / 'project.json'


def ensure_high_watermark(root, project_name, docs, resources):
    """惰性初始化 task_number_high_watermark；返回当前值。"""
    path = high_watermark_path(root, project_name)
    binding = read_json(path) if path.exists() else {}
    if 'task_number_high_watermark' in binding:
        return binding['task_number_high_watermark']
    import re
    from ._records import TASK_PATTERN
    numbers = []
    for base in (docs, docs / 'archive', resources):
        if base.exists():
            for child in base.iterdir():
                match = re.fullmatch(TASK_PATTERN, child.name)
                if match:
                    numbers.append(int(match.group(1)))
    watermark = max(numbers, default=0)
    binding['task_number_high_watermark'] = watermark
    write_json(path, binding)
    return watermark


def peek_high_watermark(root, project_name):
    """只读预览下一个编号；不写任何文件。

    --dry-run 用：预演不得推进高水位，否则提交时会二次推进。
    """
    import re
    from ._records import TASK_PATTERN, paired
    path = high_watermark_path(root, project_name)
    binding = read_json(path) if path.exists() else {}
    if 'task_number_high_watermark' in binding:
        return binding['task_number_high_watermark'] + 1
    docs, resources = paired(root, project_name)
    numbers = []
    for base in (docs, docs / 'archive', resources):
        if base.exists():
            for child in base.iterdir():
                match = re.fullmatch(TASK_PATTERN, child.name)
                if match:
                    numbers.append(int(match.group(1)))
    return max(numbers, default=0) + 1


def bump_high_watermark(root, project_name):
    """分配下一个编号并推进高水位；并发安全由工作区锁保证。"""
    from ._records import paired
    docs, resources = paired(root, project_name)
    current = ensure_high_watermark(root, project_name, docs, resources)
    new_number = current + 1
    path = high_watermark_path(root, project_name)
    binding = read_json(path)
    binding['task_number_high_watermark'] = new_number
    write_json(path, binding)
    return new_number
