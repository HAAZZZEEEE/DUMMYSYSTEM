"""工作区的物理位置和稳定逻辑路径；CLI、Workbench 与安装器共用。"""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
from contextvars import ContextVar
import json
import os
from pathlib import Path

CONFIG_NAME = '.dummysys-workspace.json'
_snapshots = ContextVar('dmy_locations', default={})


def _error(message, **details):
    from .operations import GovernanceError
    raise GovernanceError('INVALID_CONFIG', message, **details)


def _linked(path):
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


@dataclass(frozen=True)
class Locations:
    root: Path
    vault: Path
    runtime: Path

    def as_dict(self):
        return dict(vault_root=str(self.vault), runtime_root=str(self.runtime))


def configured(root, vault_root='dmy_vault', runtime_root='runtime'):
    """相对位置只相对 workspace；不相对当前目录或调用方配置文件。"""
    root = Path(root).resolve()
    values = []
    for key, raw in (('vault_root', vault_root), ('runtime_root', runtime_root)):
        if not isinstance(raw, str) or not raw.strip():
            _error('目录配置必须为非空路径', field=key)
        if any(ord(char) < 32 for char in raw):
            _error('目录配置不能包含控制字符或换行', field=key)
        path = Path(raw)
        if (path.drive or path.root) and not path.is_absolute():
            _error('不支持相对盘符或无盘符的根路径', field=key)
        path = path if path.is_absolute() else root / path
        if any(_linked(p) for p in (path, *path.parents)):
            _error('资料根及其父目录不能是链接', field=key)
        path = path.resolve()
        if root.is_relative_to(path):
            _error('资料根不能包含工作区根或与其相同', field=key)
        values.append(path)
    vault, runtime = values
    if vault.is_relative_to(runtime) or runtime.is_relative_to(vault):
        _error('Vault 与 runtime 不能重合或互相包含')
    # 逻辑名称是保留前缀，避免实路径与逻辑路径解析发生歧义。
    for path, reserved in ((vault, root / 'runtime'), (runtime, root / 'dmy_vault')):
        if path.is_relative_to(reserved):
            _error('资料根不能占用另一类资料的保留名称')
    return Locations(root, vault, runtime)


def load(root, *, fresh=False):
    cached = _snapshots.get().get(os.path.normcase(str(root)))
    if cached is not None and not fresh:
        return cached
    root = Path(root).resolve()
    config = root / CONFIG_NAME
    if _linked(config):
        _error('目录配置不能是链接', path=str(config))
    if not config.exists():
        return configured(root)
    try:
        value = json.loads(config.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as error:
        _error('目录配置无法读取', path=str(config), reason=str(error))
    if (not isinstance(value, dict) or value.get('schema_version') != 1
            or set(value) - {'schema_version', 'vault_root', 'runtime_root'}):
        _error('目录配置须为 schema_version 1，仅接受 vault_root、runtime_root', path=str(config))
    return configured(root, value.get('vault_root', 'dmy_vault'), value.get('runtime_root', 'runtime'))


@contextmanager
def snapshot(root):
    """一次受管操作共用同一解析结果；提交时仍重新核对磁盘配置。"""
    locations = load(root)
    token = _snapshots.set(dict(_snapshots.get(), **{
        os.path.normcase(str(root)): locations,
        os.path.normcase(str(locations.root)): locations,
    }))
    try:
        yield locations
    finally:
        _snapshots.reset(token)


def vault(root):
    return load(root).vault


def runtime(root):
    return load(root).runtime


def resolve(root, reference):
    """解析受管逻辑路径。dmy_vault/ 与 runtime/ 始终是逻辑前缀。"""
    reference = Path(reference)
    if reference.is_absolute() or '..' in reference.parts or ':' in str(reference):
        from .operations import GovernanceError
        raise GovernanceError('PATH_OUTSIDE_ROOT', '受管引用必须为无越级的逻辑路径', path=str(reference))
    locations = load(root)
    bases = {'dmy_vault': locations.vault, 'runtime': locations.runtime}
    base = bases.get(reference.parts[0], locations.root) if reference.parts else locations.root
    tail = reference.parts[1:] if reference.parts and reference.parts[0] in bases else reference.parts
    return base.joinpath(*tail)


def relative(root, path):
    """将物理文件位置编码为可迁移逻辑引用，不把机器绝对路径当身份。"""
    locations = load(root)
    path = Path(path)
    for prefix, base in (('dmy_vault', locations.vault), ('runtime', locations.runtime)):
        if path.is_relative_to(base):
            return Path(prefix) / path.relative_to(base)
    return path.relative_to(locations.root)


def boundary(root, reference):
    locations = load(root)
    parts = Path(reference).parts
    return {'dmy_vault': locations.vault, 'runtime': locations.runtime}.get(parts[0] if parts else '', locations.root)


def entry_pointer(root, instructions):
    return ('# 工作区执行入口\n\n'
            '先读取下列 Vault 权威规则，再开展工作；本文件仅为跨卷导航入口。\n\n'
            f'[工作区规则](<{Path(instructions).as_posix()}>)\n\n'
            f'工作区根：`{Path(root).as_posix()}`；资料位置由根目录 {CONFIG_NAME} 声明。\n')
