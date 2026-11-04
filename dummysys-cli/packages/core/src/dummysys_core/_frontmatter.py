"""类型化 Frontmatter 读写：保留未知字段、注释与非目标正文。

支持 YAML 标量子集（字符串、布尔、日期、整数、行内列表、块列表），
拒绝重复键与不支持的结构。内部统一 Python 类型；旧适配层可再转 string/boolean。
"""
from __future__ import annotations

import re
from datetime import date, datetime

_FM_RE = re.compile(r'\A---\n(.*?)\n---', re.S)
_KEY_RE = re.compile(r'^([\w-]+):\s*(.*)$')
_LIST_ITEM_RE = re.compile(r'^\s+-\s+(.*)$')
_COMMENT_RE = re.compile(r'^\s*#')
_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


class FrontmatterError(ValueError):
    """字段级解析或写入错误。"""

    def __init__(self, message, field=None):
        super().__init__(message)
        self.field = field


def _parse_scalar(raw):
    raw = raw.strip()
    if raw == '':
        return None
    if (raw.startswith('"') and raw.endswith('"') and len(raw) >= 2) or \
       (raw.startswith("'") and raw.endswith("'") and len(raw) >= 2):
        return raw[1:-1]
    if raw in ('true', 'True'):
        return True
    if raw in ('false', 'False'):
        return False
    if raw in ('null', 'Null', '~'):
        return None
    if _DATE_RE.match(raw):
        return raw  # 保持 ISO 日期字符串，调用方按需转 date
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


def _parse_inline_list(raw):
    inner = raw.strip()[1:-1].strip()
    if not inner:
        return []
    items = []
    for part in re.split(r',\s*', inner):
        items.append(_parse_scalar(part))
    return items


def parse(text):
    """解析 frontmatter，返回 (props: dict, body: str, raw_front: str)。

    props 的值类型：str、int、float、bool、None、list。
    """
    match = _FM_RE.match(text)
    if not match:
        raise FrontmatterError('缺少 Properties 块')
    raw_front = match[1]
    props = {}
    lines = raw_front.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i]
        if _COMMENT_RE.match(line) or not line.strip():
            i += 1
            continue
        key_match = _KEY_RE.match(line)
        if not key_match:
            raise FrontmatterError(f'无法解析 frontmatter 行：{line}', field=None)
        key, rest = key_match.group(1), key_match.group(2).strip()
        if key in props:
            raise FrontmatterError(f'重复键：{key}', field=key)
        if rest == '':
            # 可能是块列表
            items = []
            j = i + 1
            while j < len(lines):
                item_match = _LIST_ITEM_RE.match(lines[j])
                if item_match:
                    items.append(_parse_scalar(item_match.group(1)))
                    j += 1
                elif not lines[j].strip() or _COMMENT_RE.match(lines[j]):
                    j += 1
                else:
                    break
            if items:
                props[key] = items
                i = j
            else:
                props[key] = None
                i += 1
        elif rest.startswith('[') and rest.endswith(']'):
            props[key] = _parse_inline_list(rest)
            i += 1
        else:
            props[key] = _parse_scalar(rest)
            i += 1
    return props, text[match.end():], raw_front


def _format_value(value):
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    text = str(value)
    if text == '' or text != text.strip() or any(c in text for c in ':#{}[]&*!|>%@`') \
       or text.startswith(('-', '?', '"', "'")) or _DATE_RE.match(text) \
       or text in ('true', 'false', 'null', 'True', 'False', 'Null', '~'):
        return '"' + text.replace('\\', '\\\\').replace('"', '\\"') + '"'
    return text


def _format_list(items):
    if not items:
        return '[]'
    return None  # 非空列表统一块格式，兼容 Vault 校验器，保留带逗号的单个值。


def _render_front(props, raw_front):
    """根据原始 front 行结构替换或追加目标键，保留注释和未知行。"""
    lines = raw_front.split('\n')
    result = []
    handled = set()
    i = 0
    while i < len(lines):
        line = lines[i]
        key_match = _KEY_RE.match(line) if line.strip() and not _COMMENT_RE.match(line) else None
        if key_match and key_match.group(1) in props:
            key = key_match.group(1)
            value = props[key]
            handled.add(key)
            # 跳过原块列表行
            j = i + 1
            rest = key_match.group(2).strip()
            if rest == '':
                while j < len(lines) and (_LIST_ITEM_RE.match(lines[j]) or not lines[j].strip() or _COMMENT_RE.match(lines[j])):
                    if _LIST_ITEM_RE.match(lines[j]):
                        j += 1
                    elif not lines[j].strip() or _COMMENT_RE.match(lines[j]):
                        # 只跳过紧随列表项之间的空行/注释
                        if j < len(lines) and (_LIST_ITEM_RE.match(lines[j]) or (j + 1 < len(lines) and _LIST_ITEM_RE.match(lines[j + 1]))):
                            j += 1
                        else:
                            break
                    else:
                        break
            if isinstance(value, list):
                inline = _format_list(value)
                if inline is not None:
                    result.append(f'{key}: {inline}')
                else:
                    result.append(f'{key}:')
                    for item in value:
                        result.append(f'  - {_format_value(item)}')
            else:
                result.append(f'{key}: {_format_value(value)}')
            i = j
        else:
            result.append(line)
            i += 1
    for key, value in props.items():
        if key in handled:
            continue
        if isinstance(value, list):
            inline = _format_list(value)
            if inline is not None:
                result.append(f'{key}: {inline}')
            else:
                result.append(f'{key}:')
                for item in value:
                    result.append(f'  - {_format_value(item)}')
        else:
            result.append(f'{key}: {_format_value(value)}')
    return '\n'.join(result)


def read(path):
    from .operations import native_path
    path = native_path(path)
    text = path.read_text(encoding='utf-8')
    props, body, _ = parse(text)
    return props


def update(path, values):
    """就地更新 frontmatter 键，保留注释、未知字段和正文。"""
    from .operations import native_path
    path = native_path(path)
    text = path.read_text(encoding='utf-8')
    props, body, raw_front = parse(text)
    # 检查重复键在 parse 已做
    for key, value in values.items():
        props[key] = value
    new_front = _render_front(props, raw_front)
    path.write_text('---\n' + new_front + '\n---' + body, encoding='utf-8')
    return props


def write(path, props, body=''):
    """完整写入 frontmatter + 正文。"""
    front = _render_front(props, '')
    path.write_text('---\n' + front + '\n---' + body, encoding='utf-8')
