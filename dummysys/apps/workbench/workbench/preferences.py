"""工作台偏好的合并更新；一次进程内事务对应一次原子文件替换。"""
from __future__ import annotations

import json
import hashlib
import re
import threading
from pathlib import Path, PureWindowsPath

from .catalog import CatalogError, InvalidTarget
from .file_io import write_json


class PreferenceConflict(CatalogError):
    """读取后偏好发生变化，调用方须重新读取并计算更新。"""


class Preferences:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()

    @staticmethod
    def defaults() -> dict:
        return {'schema_version': 1, 'pinned_project_ids': [], 'project_order': [],
                'theme': 'system', 'accent_color': '#0066cc', 'workspace_name': '', 'last_location': None,
                'pinned_locations': [], 'recent_locations': [], 'sidebar_width': None,
                'preview_width': None, 'preview_visible': True, 'task_view': 'indent', 'actor': 'workbench',
                'density': 'comfortable', 'directory_columns': [], 'directory_column_order': [], 'nav_sort': 'default',
                'homepage_pins': {}, 'homepage_overrides': {}}

    @staticmethod
    def _location(value: dict) -> dict:
        fields = ('project_id', 'root_id', 'relative_path')
        if (not isinstance(value, dict) or set(value) != set(fields)
                or any(not isinstance(value[k], str) or len(value[k]) > 4096
                       or any(ord(c) < 32 for c in value[k]) for k in fields)
                or not value['project_id'] or not value['root_id']):
            raise InvalidTarget('位置必须包含项目、根和相对路径')
        relative = PureWindowsPath(value['relative_path'])
        if relative.drive or relative.root or '..' in relative.parts:
            raise InvalidTarget('位置必须在登记根内，不能使用绝对路径或上级跳转')
        # 这里只保存导航引用；失效固定目录仍可移除，打开时由 Catalog 重新核验范围。
        return {'project_id': value['project_id'], 'root_id': value['root_id'],
                'relative_path': relative.as_posix() if relative.parts else ''}

    def read(self) -> dict:
        with self._lock:
            data = self.defaults()
            try:
                saved = json.loads(self.path.read_text(encoding='utf-8'))
                # 过期视图值回退到默认样式，同时保留同一偏好文件中的其他设置。
                if isinstance(saved, dict) and saved.get('task_view') not in ('indent', 'cards'):
                    saved = {key: value for key, value in saved.items() if key != 'task_view'}
                if isinstance(saved, dict):
                    for key in ('directory_columns', 'directory_column_order'):
                        if key in saved:
                            try:
                                self._directory_columns(saved[key])
                            except InvalidTarget:
                                saved.pop(key)
                data.update(self._validate(saved))
            except (OSError, ValueError, CatalogError):
                pass
            return data

    @staticmethod
    def _directory_columns(value) -> list[str]:
        allowed = ('type', 'modified', 'size', 'file_count')
        if (not isinstance(value, list) or len(value) > len(allowed)
                or any(column not in allowed for column in value)
                or len(set(value)) != len(value)):
            raise InvalidTarget('目录列必须由不重复的类型、修改时间、大小或文件数组成')
        return value

    @staticmethod
    def _validate(patch: dict) -> dict:
        if not isinstance(patch, dict):
            raise InvalidTarget('偏好必须是 JSON 对象')
        # 0.3 的收藏字段作为输入别名兼容；读取和下次写入统一使用 pin 命名。
        patch = dict(patch)
        if 'bookmarked_locations' in patch:
            legacy = patch.pop('bookmarked_locations')
            patch.setdefault('pinned_locations', legacy)
        if set(patch) - set(Preferences.defaults()):
            raise InvalidTarget('偏好包含未知字段')
        out = {}
        for key, value in patch.items():
            if key == 'schema_version':
                if value != 1:
                    raise InvalidTarget('不支持的偏好版本')
            elif key in ('pinned_project_ids', 'project_order'):
                if not isinstance(value, list):
                    raise InvalidTarget(f'{key} 必须是列表')
                out[key] = list(dict.fromkeys(str(x) for x in value if x))
            elif key == 'homepage_pins':
                if not isinstance(value, dict) or len(value) > 1000:
                    raise InvalidTarget('首页收藏必须按项目保存')
                pins = {}
                for project, items in value.items():
                    if (not isinstance(project, str) or not 1 <= len(project) <= 128
                            or not isinstance(items, list) or len(items) > 1000
                            or any(not isinstance(item, str) or not 1 <= len(item) <= 512
                                   or any(ord(c) < 32 for c in item) for item in items)):
                        raise InvalidTarget('首页收藏项目或条目格式无效')
                    pins[project] = list(dict.fromkeys(items))
                out[key] = pins
            elif key == 'homepage_overrides':
                if not isinstance(value, dict) or len(value) > 1000:
                    raise InvalidTarget('首页显示修改必须按项目保存')
                projects = {}
                for project, items in value.items():
                    if (not isinstance(project, str) or not 1 <= len(project) <= 128
                            or not isinstance(items, dict) or len(items) > 1000):
                        raise InvalidTarget('首页显示修改项目格式无效')
                    entries = {}
                    for identity, fields in items.items():
                        if (not isinstance(identity, str) or not 1 <= len(identity) <= 512
                                or any(ord(c) < 32 for c in identity)
                                or not isinstance(fields, dict) or set(fields) - {'name', 'description'}):
                            raise InvalidTarget('首页显示修改条目格式无效')
                        entry = {}
                        for field, text in fields.items():
                            if (not isinstance(text, str) or len(text) > (120 if field == 'name' else 2000)
                                    or any(ord(c) < 32 and c != '\n' for c in text)
                                    or (field == 'name' and '\n' in text)):
                                raise InvalidTarget('名称最多120字，介绍最多2000字')
                            if text.strip():
                                entry[field] = text.strip()
                        if entry:
                            entries[identity] = entry
                    projects[project] = entries
                out[key] = projects
            elif key == 'theme':
                if value not in ('system', 'light', 'dark'):
                    raise InvalidTarget('主题必须是 system、light 或 dark')
                out[key] = value
            elif key == 'density':
                if value not in ('comfortable', 'compact'):
                    raise InvalidTarget('目录行距必须是 comfortable 或 compact')
                out[key] = value
            elif key in ('directory_columns', 'directory_column_order'):
                out[key] = Preferences._directory_columns(value)
            elif key == 'nav_sort':
                if value not in ('default', 'name', 'name_desc', 'newest', 'oldest'):
                    raise InvalidTarget('不支持的导航排序方式')
                out[key] = value
            elif key == 'accent_color':
                if not isinstance(value, str) or re.fullmatch(r'#[0-9a-fA-F]{6}', value) is None:
                    raise InvalidTarget('重点色必须是六位十六进制颜色，例如 #0066cc')
                out[key] = value.lower()
            elif key == 'sidebar_width':
                if value is not None and (type(value) is not int or not 200 <= value <= 640):
                    raise InvalidTarget('侧栏宽度必须是 200 到 640 之间的像素值')
                out[key] = value
            elif key == 'preview_visible':
                if type(value) is not bool:
                    raise InvalidTarget('预览栏开关必须是布尔值')
                out[key] = value
            elif key == 'preview_width':
                if value is not None and (type(value) is not int or not 240 <= value <= 800):
                    raise InvalidTarget('预览边栏宽度必须是 240 到 800 之间的像素值')
                out[key] = value
            elif key == 'task_view':
                if value in ('indent', 'cards'):
                    out[key] = value
                else:
                    raise InvalidTarget('任务视图必须是 indent 或 cards')
            elif key == 'workspace_name':
                if (not isinstance(value, str) or len(value) > 40
                        or any(ord(c) < 32 or ord(c) == 127 for c in value)):
                    raise InvalidTarget('工作空间名称必须是不超过 40 字符的单行文本')
                out[key] = value.strip()
            elif key == 'actor':
                # 新设置与旧空身份均使用工作台默认操作人，保留已有自定义身份。
                if not isinstance(value, str) or len(value) > 64 or any(ord(c) < 32 for c in value):
                    raise InvalidTarget('负责人必须是不超过 64 字符的单行文本')
                out[key] = value.strip() or Preferences.defaults()['actor']
            elif key == 'last_location':
                out[key] = Preferences._location(value) if value is not None else None
            elif key in ('pinned_locations', 'recent_locations'):
                limit = 30 if key == 'pinned_locations' else 8
                if not isinstance(value, list) or len(value) > limit:
                    raise InvalidTarget(f'{key} 必须是最多 {limit} 个位置的列表')
                locations = [Preferences._location(item) for item in value]
                out[key] = list({tuple(item.values()): item for item in locations}.values())
        return out

    @staticmethod
    def revision(data: dict) -> str:
        encoded = json.dumps(data, sort_keys=True, separators=(',', ':')).encode('utf-8')
        return '"' + hashlib.sha256(encoded).hexdigest() + '"'

    def patch(self, patch: dict, expected_revision: str | None = None) -> dict:
        update = self._validate(patch)
        with self._lock:
            data = self.read()
            if expected_revision is not None and expected_revision != self.revision(data):
                raise PreferenceConflict('偏好已在其他窗口更新，请重试')
            data.update(update)
            write_json(self.path, data)
            return data
