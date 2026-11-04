"""受限本机诊断事件；UUID 关联，默认不保存参数、正文和身份。"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import time
from uuid import UUID

from dummysys_core.operations import GovernanceError
from dummysys_core import __version__

RETENTION_SECONDS = 14 * 86400
MAX_BYTES = 100 * 1024 * 1024


def _read_event(path):
    value=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value,dict) or value.get('schema_version') != 1:
        raise GovernanceError('INCOMPATIBLE_DIAGNOSTIC','不支持的诊断事件格式，保留副本并核对原版本',path=str(path))
    if not all(isinstance(value.get(k),str) for k in ('diagnostic_id','trace_id','timestamp','command','outcome')):
        raise GovernanceError('INCOMPATIBLE_DIAGNOSTIC','诊断事件缺少必要字段',path=str(path))
    return value


def directory(root):
    return Path(root) / 'runtime/logs/cli/diagnostics'


def validate_id(value):
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise GovernanceError('INVALID_ARGUMENT', '诊断编号必须为 UUID') from None


def prune(folder, *, now=None, max_bytes=MAX_BYTES):
    now = time.time() if now is None else now
    entries=[]
    for path in folder.glob('*.json'):
        try:
            validate_id(path.stem)
            info=path.stat()
            entries.append((info.st_mtime, info.st_size, path))
        except (OSError, GovernanceError):
            continue
    total=sum(e[1] for e in entries)
    for modified, size, path in sorted(entries):
        if modified < now - RETENTION_SECONDS or total > max_bytes:
            try:
                path.unlink(); total -= size
            except FileNotFoundError:
                pass


def save(root, *, diagnostic_id, trace_id, command, code, outcome, error_code,
         duration_ms, source, stages, operation_id=None):
    folder=directory(root); folder.mkdir(parents=True, exist_ok=True)
    value=dict(schema_version=1, diagnostic_id=validate_id(diagnostic_id), trace_id=validate_id(trace_id),
               tool_version=__version__,
               timestamp=datetime.now(timezone.utc).isoformat(), command=command, exit_code=code,
               outcome=outcome, error_code=error_code, duration_ms=duration_ms,
               source=source, stages=stages, operation_id=operation_id,
               operation_record=str(Path(root)/'runtime/state/workspace/operations'/operation_id/'operation.json') if operation_id else None)
    fd, temporary=tempfile.mkstemp(prefix='.event-', dir=folder)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False)
        os.replace(temporary, folder/(diagnostic_id+'.json'))
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
    # 一分钟至多清理一次；事件先写后清理，并发只允许更积极清理诊断副本。
    marker=folder/'.pruned'
    if not marker.exists() or time.time()-marker.stat().st_mtime >= 60:
        prune(folder); marker.touch()


def show(root, identity):
    identity=validate_id(identity); folder=directory(root)
    path=folder/(identity+'.json')
    matched_by='diagnostic_id'
    try:
        value=_read_event(path)
    except FileNotFoundError:
        matches=[]
        for candidate in folder.glob('*.json'):
            try:
                record=_read_event(candidate)
                if record.get('trace_id')==identity: matches.append(record)
            except (OSError,ValueError,AttributeError):
                continue
        if not matches:
            raise GovernanceError('NOT_FOUND', '该编号没有 CLI 结束事件；可能仅本地读取、尚未结束或已过保留期', diagnostic_id=identity) from None
        value=max(matches,key=lambda r:r.get('timestamp',''));matched_by='trace_id'
    related=[]
    for other in folder.glob('*.json'):
        try:
            record=_read_event(other)
            if record.get('trace_id') == value['trace_id']:
                related.append(dict(diagnostic_id=record['diagnostic_id'], timestamp=record['timestamp'],
                                    command=record['command'], outcome=record['outcome']))
        except (OSError, ValueError, KeyError):
            continue
    return dict(event=value, attempts=sorted(related,key=lambda x:x['timestamp']),matched_by=matched_by,
                coverage='仅包含保留期内、已完成记录的 CLI 尝试；工作台纯本地读取与强制终止可能没有结束事件')
