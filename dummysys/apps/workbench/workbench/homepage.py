"""项目首页声明与页面包解析；只读取登记根内的独立配置。"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from .catalog import CatalogError, InvalidTarget, TargetForbidden, TargetNotFound

CONFIG_NAME = 'workbench.json'
REFERENCE_PREFIX = '_refs'
ASSET_TYPES = frozenset({'.html', '.htm', '.css', '.js', '.mjs', '.json', '.csv', '.tsv',
                         '.txt', '.svg', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico',
                         '.woff', '.woff2', '.ttf', '.otf', '.pdf', '.mp4', '.webm'})


class Homepage:
    def __init__(self, catalog):
        self.catalog = catalog

    def _config(self, project_id):
        info = self.catalog.resolve_target({'project_id': project_id, 'root_id': 'resources',
                                            'relative_path': CONFIG_NAME})
        if not info['available']:
            return None
        try:
            if Path(info['path']).stat().st_size > 64 * 1024:
                raise InvalidTarget('workbench.json 超过 64KB')
            raw = Path(info['path']).read_bytes()
            config = json.loads(raw.decode('utf-8-sig'))
        except (OSError, ValueError) as error:
            raise InvalidTarget('workbench.json 无法读取，请检查 JSON 格式') from error
        if not isinstance(config, dict) or config.get('schema_version') != 1:
            raise InvalidTarget('workbench.json 需要 schema_version: 1')
        return config.get('homepage')

    def resolve(self, project_id):
        home = self._config(project_id)
        if home is None:
            return None
        if (not isinstance(home, dict) or not {'root_id', 'path'} <= set(home)
                or set(home) - {'root_id', 'path', 'references'}
                or not isinstance(home.get('root_id'), str) or not home['root_id']
                or not isinstance(home.get('path'), str)):
            raise InvalidTarget('homepage 需要 root_id 和相对入口 path')
        info = self.catalog.resolve_target({'project_id': project_id, 'root_id': home['root_id'],
                                            'relative_path': home['path']})
        if info['navigation_only']:
            raise TargetForbidden('首页入口必须位于登记的可读范围')
        if not info['available'] or info['kind'] != 'file':
            raise TargetNotFound('首页入口文件不存在')
        path = Path(info['path'])
        if path.suffix.lower() not in ('.html', '.htm'):
            raise InvalidTarget('首页入口必须是 HTML 文件')
        # 默认资源仍限制在入口目录；其他原件目录必须逐项声明。
        parent = PurePosixPath(info['relative_path']).parent.as_posix()
        base = self.catalog.resolve_target({'project_id': project_id, 'root_id': home['root_id'],
                                            'relative_path': '' if parent == '.' else parent})
        if base['navigation_only'] or not path.is_relative_to(Path(base['path'])):
            raise TargetForbidden('首页页面包超出登记范围')
        return {'project_id': project_id, 'root_id': home['root_id'],
                'directory': '' if parent == '.' else parent,
                'entry': PurePosixPath(info['relative_path']).name,
                'base': str(Path(base['path'])),
                'references': self._references(project_id, home.get('references', {}))}

    def _references(self, project_id, declarations):
        if not isinstance(declarations, dict):
            raise InvalidTarget('homepage.references 需要引用名称与目录映射')
        references = {}
        for name, item in declarations.items():
            if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', name):
                raise InvalidTarget('引用名称仅支持字母、数字、下划线和连字符，且须以字母或数字开头')
            if (not isinstance(item, dict) or not {'root_id', 'path'} <= set(item)
                    or set(item) - {'root_id', 'path', 'styles', 'scripts'}
                    or not isinstance(item.get('root_id'), str) or not item['root_id']
                    or not isinstance(item.get('path'), str)):
                raise InvalidTarget('引用需要 root_id 和相对目录 path，可选 styles、scripts')
            info = self.catalog.resolve_target({'project_id': project_id,
                                                'root_id': item['root_id'],
                                                'relative_path': item['path']})
            if info['navigation_only'] or any(p.startswith('.') for p in PurePosixPath(info['relative_path']).parts):
                raise TargetForbidden('引用目录必须位于登记的可读范围')
            if info['available'] and info['kind'] != 'dir':
                raise InvalidTarget('引用的 path 必须是目录')
            references[name] = {'root_id': item['root_id'], 'directory': info['relative_path'],
                                'base': str(Path(info['path'])),
                                'styles': self._includes(item.get('styles', []), {'.css'}),
                                'scripts': self._includes(item.get('scripts', []), {'.js', '.mjs'})}
        return references

    def _includes(self, paths, types):
        if not isinstance(paths, list):
            raise InvalidTarget('引用的 styles/scripts 需要包内相对路径列表')
        result = []
        for path in paths:
            relative = self.catalog._validate_relative(path)
            parts = PurePosixPath(relative).parts
            if (not parts or parts[0] == REFERENCE_PREFIX or any(p.startswith('.') for p in parts)
                    or PurePosixPath(relative).suffix.lower() not in types):
                raise InvalidTarget('引用附加的样式或脚本必须是首页包内的 CSS/JS 文件')
            result.append(relative)
        return result

    def describe(self, project_id):
        try:
            home = self.resolve(project_id)
            return {'configured': True, 'error': None} if home else None
        except CatalogError as error:
            return {'configured': True, 'error': str(error)}

    def asset(self, grant, relative):
        # 每次重核配置及链接，旧能力在配置变更后失效。
        current = self.resolve(grant['project_id'])
        if current != grant:
            raise TargetForbidden('首页配置已变化，请刷新项目首页')
        rel = self.catalog._validate_relative(relative)
        parts = PurePosixPath(rel).parts
        if not parts or any(part.startswith('.') for part in parts):
            raise TargetForbidden('页面包不提供隐藏文件或目录列表')
        if PurePosixPath(rel).suffix.lower() not in ASSET_TYPES:
            raise TargetForbidden('该文件类型不属于页面资源')
        location = grant
        if parts[0] == REFERENCE_PREFIX:
            if len(parts) < 3 or parts[1] not in grant['references']:
                raise TargetForbidden('该引用未在首页声明或未指定文件')
            location = grant['references'][parts[1]]
            rel = PurePosixPath(*parts[2:]).as_posix()
        path = '/'.join(filter(None, (location['directory'], rel)))
        info = self.catalog.resolve_target({'project_id': grant['project_id'],
                                            'root_id': location['root_id'], 'relative_path': path})
        resolved = Path(info['path'])
        if info['navigation_only'] or not resolved.is_relative_to(Path(location['base'])):
            raise TargetForbidden('页面资源超出页面包或已声明引用目录的范围')
        if not info['available'] or info['kind'] != 'file':
            raise TargetNotFound('页面资源不存在')
        return resolved

    def render_reference(self, grant, relative, path, prefix):
        """按声明附加包内阅读资产；每次读取原件，不生成磁盘副本。"""
        parts = PurePosixPath(self.catalog._validate_relative(relative)).parts
        if parts[0] != REFERENCE_PREFIX or path.suffix.lower() not in {'.html', '.htm'}:
            return None
        reference = grant['references'][parts[1]]
        tags = []
        for kind in ('styles', 'scripts'):
            for asset in reference[kind]:
                self.asset(grant, asset)
                url = html.escape(prefix + quote(asset, safe='/'), quote=True)
                if kind == 'styles':
                    tags.append(f'<link rel="stylesheet" href="{url}">')
                else:
                    module = ' type="module"' if asset.endswith('.mjs') else ''
                    tags.append(f'<script{module} src="{url}"></script>')
        if not tags:
            return None
        try:
            text = path.read_text(encoding='utf-8-sig')
        except UnicodeError as error:
            raise InvalidTarget('加载包内阅读资产的引用 HTML 需要使用 UTF-8 编码') from error
        additions = ''.join(tags)
        if re.search(r'</head\s*>', text, re.IGNORECASE):
            return re.sub(r'</head\s*>', lambda m: additions + m[0], text,
                          count=1, flags=re.IGNORECASE)
        if re.search(r'<html\b', text, re.IGNORECASE):
            return re.sub(r'(<html\b[^>]*>)', lambda m: m[0] + additions, text,
                          count=1, flags=re.IGNORECASE)
        return f'<!doctype html><html><head><meta charset="utf-8">{additions}</head><body>{text}</body></html>'
