"""治理资料的唯一定位契约；项目身份不随显示目录名变化。"""

from dummysys_core import locations as loc
import json
from pathlib import Path

from .operations import GovernanceError, safe_target

LEGACY = {'entry': '00-入口', 'system': '10-系统', 'templates': '90-模板'}
DESTINATIONS = {'entry': '文档', 'system': '治理', 'templates': '模板'}


def manifest(root):
    path = Path(root) / '.dummysys-docs.json'
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {'schema_version': 1, 'documents': []}
        if not isinstance(value, dict) or value.get('schema_version') != 1:
            raise ValueError('文档维护映射须为 schema_version 1 的对象')
        return value
    except (OSError, ValueError) as error:
        raise GovernanceError('INVALID_CONFIG', str(error), path=str(path)) from error


def governance_paths(root):
    """无布局声明时兼容旧工作区；显式声明无效时拒绝静默回退。"""
    from ._paths import project_readmes
    from ._records import properties
    # 保留调用方的路径拼写；Windows 8.3 别名与长路径不能混用于 relative_to。
    root = Path(root)
    vault = loc.vault(root)
    result = {key: vault / value for key, value in LEGACY.items()}
    declared = manifest(root).get('governance')
    if declared is not None:
        if not isinstance(declared, dict) or not isinstance(declared.get('sections'), list) or not declared.get('project_id'):
            raise GovernanceError('INVALID_CONFIG', 'governance 必须声明 project_id 和已迁移 sections')
        sections = declared['sections']
        if len(sections) != len(set(sections)) or any(key not in LEGACY for key in sections):
            raise GovernanceError('INVALID_CONFIG', '治理分区声明无效或重复')
        matches = [p.parent for p in project_readmes(root) if properties(p).get('project_id') == declared['project_id']]
        if len(matches) != 1:
            raise GovernanceError('INVALID_CONFIG', '治理所属 Project 身份必须唯一', project=declared['project_id'])
        for key in sections:
            target = matches[0] / DESTINATIONS[key]
            safe_target(root, loc.relative(root, target))
            if not target.is_dir() or (vault / LEGACY[key]).exists():
                raise GovernanceError('INVALID_CONFIG', '治理目录缺失或新旧入口并存', path=str(target))
            result[key] = target
    result.update(instructions=result['system'] / 'Codex工作区指令.md',
                  policy=result['system'] / 'DUMMYSYS目录与资源治理.md',
                  protocol=result['system'] / '项目与任务执行规范.md',
                  knowledge=result['system'] / 'Obsidian知识库规范.md',
                  repositories=result['system'] / '仓库',
                  home=result['entry'] / 'DUMMYSYS.md')
    return result


def wiki(root, path, label=None):
    target = Path(path).relative_to(loc.vault(Path(root))).with_suffix('').as_posix()
    return '[[' + target + ('|' + label if label else '') + ']]'
