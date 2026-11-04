"""活动区与归档区的文档定位；资源根始终不移动。"""

from dummysys_core import locations as loc
from pathlib import Path
import re

TASK_PATTERN = r'\[task ([1-9]\d*)\]\[(\d{8})\](.+)'


def project_readmes(root):
    from ._records import properties
    base = loc.vault(Path(root)) / '30-项目'
    def managed(path):
        if not path.read_text(encoding='utf-8-sig').startswith('---'):
            return False
        meta = properties(path)
        return meta.get('type') == 'project' or (not meta.get('type') and bool(meta.get('project_id')))
    return sorted(p for p in [*base.glob('*/README.md'), *base.glob('archive/*/README.md')] if managed(p))


def project_docs(root, name):
    if not name or name in {'.', '..', 'archive'} or '/' in name or '\\' in name:
        raise ValueError('项目名称必须是单个目录名')
    base = loc.vault(Path(root)) / '30-项目'
    candidates = [base / name, base / 'archive' / name]
    found = [p for p in candidates if p.exists()]
    if len(found) > 1:
        raise ValueError(f'项目同时存在于活动区和归档区：{name}')
    return found[0] if found else candidates[0]


def task_dirs(docs):
    return sorted(p for base in (docs, docs / 'archive') if base.is_dir()
                  for p in base.iterdir() if p.is_dir() and re.fullmatch(TASK_PATTERN, p.name))


def project_link(root, docs):
    return '[[' + (docs / 'README').relative_to(loc.vault(Path(root))).as_posix() + ']]'
