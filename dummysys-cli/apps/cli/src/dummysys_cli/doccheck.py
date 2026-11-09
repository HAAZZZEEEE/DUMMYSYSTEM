"""当前文档维护映射、显式路径和生成式命令参考检查。"""

from dummysys_core import locations as loc
import json
import hashlib
from pathlib import Path
import re
from urllib.parse import unquote


def _matches(base, pattern):
    # 仅 * 和 ? 是通配符；[task n] 始终是字面目录，缺失时不能匹配 t 等字符。
    literal=loc.resolve(base, pattern)
    if literal.exists(): return [literal]
    if '*' not in pattern and '?' not in pattern: return []
    parts=Path(pattern).parts
    if parts and parts[0] in ('dmy_vault','runtime'):
        base=loc.resolve(base, parts[0]); pattern=Path(*parts[1:]).as_posix()
    return list(base.glob(pattern.replace('[','[[]')))


def _inside(base, path):
    try:
        return path.resolve().is_relative_to(loc.boundary(base, loc.relative(base, path)))
    except ValueError:
        return False


def command_reference():
    from .parser import build_parser, capabilities
    value=capabilities(build_parser())
    lines=['# CLI 命令参考', '', '由命令声明生成；使用 scripts/command_reference.py --check 核对。', '',
           '全局参数：'+'、'.join('`'+x+'`' for x in value['global_options']), '',
           '退出码：0 成功；1 检查发现问题；2 参数、状态或执行错误。', '']
    for command in value['commands']:
        lines += ['## '+command['command'], '']
        for arg in command['arguments']:
            label=' / '.join(arg['flags']) or arg['name']
            choices='；取值 '+', '.join(map(str,arg['choices'])) if arg['choices'] else ''
            default='；默认 '+json.dumps(arg['default'],ensure_ascii=False) if arg['default'] is not None else ''
            lines.append('- `'+label+'`：'+('必填' if arg['required'] else '可选')+'；类型 '+arg['type']+choices+default)
        lines.append('')
    return '\n'.join(lines)


def check_docs(workspace, roots=None):
    workspace=Path(workspace)
    failures=[]
    if roots is None:
        roots=[workspace]
        selection=loc.runtime(workspace) / 'state/workspace/doccheck.json'
        mapping=loc.runtime(workspace) / 'state/workspace/repositories.json'
        if selection.exists():
            try:
                data=json.loads(selection.read_text(encoding='utf-8-sig'))
                if not isinstance(data,dict) or data.get('schema_version') != 1:
                    raise ValueError('文档检查配置须为 schema_version=1 的对象')
                selected=data.get('roots')
                if not isinstance(selected,list) or not all(isinstance(p,str) and p.strip() for p in selected):
                    raise ValueError('roots 必须是非空路径字符串的数组')
                # 相对路径以工作区为基准；本机源码绑定不进入公开源码。
                roots.extend(Path(p) if Path(p).is_absolute() else workspace/p for p in selected)
            except (OSError,ValueError,TypeError) as error:
                failures.append(dict(code='DOC_ROOTS_INVALID',path=str(selection),message=str(error)))
        elif mapping.exists():
            try:
                data=json.loads(mapping.read_text(encoding='utf-8-sig'))
                if not isinstance(data,dict) or not isinstance(data.get('checkouts'),dict): raise ValueError('仓库映射必须包含 checkouts 对象')
                for key in ('dummysys','dummysys-cli'):
                    entry=data['checkouts'].get(key,{})
                    if not isinstance(entry,dict): raise ValueError('checkout 必须是对象')
                    path=entry.get('path')
                    if path: roots.append(Path(path))
            except (OSError,ValueError,TypeError) as error:
                failures.append(dict(code='MAPPING_INVALID',path=str(mapping),message=str(error)))
    checked=0; mappings=[]; unavailable=[]; review_required=[]; derived_checked=0
    for base in dict.fromkeys(Path(p).resolve() for p in roots):
        manifest=base/'.dummysys-docs.json'
        if not manifest.is_file():
            unavailable.append(str(manifest)); continue
        try:
            spec=json.loads(manifest.read_text(encoding='utf-8'))
            if not isinstance(spec,dict): raise ValueError('维护映射必须是对象')
            if spec.get('schema_version') != 1: raise ValueError('不支持的文档映射版本')
            if not isinstance(spec.get('documents'),list) or not all(isinstance(p,str) for p in spec['documents']): raise ValueError('documents 必须是路径数组')
            files=set()
            for pattern in spec['documents']:
                matched=[p for p in _matches(base,pattern) if p.is_file()]
                if not matched:
                    failures.append(dict(code='DOC_MISSING',path=str(manifest),target=pattern))
                files.update(matched)
            for rule in spec.get('maintenance',[]):
                mappings.append(dict(root=str(base),**rule))
                for field in ('implementation','documents','tests'):
                    for pattern in rule[field]:
                        if not _matches(base,pattern):
                            failures.append(dict(code='MAPPING_MISSING',path=str(manifest),target=pattern,field=field))
            for path in sorted(files):
                if not _inside(base,path):
                    failures.append(dict(code='DOC_OUTSIDE_ROOT',path=str(path))); continue
                checked+=1
                fenced=False
                for line_no,line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(),1):
                    if line.lstrip().startswith(('```','~~~')):
                        fenced=not fenced; continue
                    if fenced: continue
                    for match in re.finditer(r'!?\[[^\]]*\]\((<[^>]+>|[^)]+)\)',line):
                        raw=match.group(1).strip().strip('<>')
                        if not raw or raw.startswith(('#','http:','https:','mailto:','obsidian:','codex:','data:')): continue
                        target=unquote(raw.split('#',1)[0])
                        if not target: continue
                        linked=Path(target)
                        if not linked.is_absolute(): linked=path.parent/linked
                        if not linked.exists():
                            failures.append(dict(code='BROKEN_LINK',path=str(path),line=line_no,target=raw))
            generated=spec.get('generated_commands')
            if generated:
                path=base/generated
                if not path.is_file() or path.read_text(encoding='utf-8') != command_reference():
                    failures.append(dict(code='REFERENCE_STALE',path=str(path),next_action='运行 scripts/command_reference.py 后核对差异'))
            for derived in spec.get('derived_documents', []):
                output = loc.resolve(base, derived['output'])
                if not _inside(base, output) or not output.is_file():
                    failures.append(dict(code='DERIVED_OUTPUT_MISSING', path=str(output)))
                    continue
                if not isinstance(derived.get('rebuild'), str) or not derived['rebuild'].strip() or not derived.get('sources'):
                    raise ValueError('派生文档须声明非空 sources 和 rebuild 入口')
                derived_checked += 1
                for source in derived['sources']:
                    path = loc.resolve(base, source['path'])
                    if not _inside(base, path) or not path.is_file():
                        failures.append(dict(code='DERIVED_SOURCE_MISSING', path=str(output), target=str(path)))
                        continue
                    expected = source['sha256']
                    if not isinstance(expected, str) or not re.fullmatch('[a-f0-9]{64}', expected):
                        raise ValueError('派生来源 sha256 必须为 64 位小写摘要')
                    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                        review_required.append(dict(code='SOURCE_CHANGED', path=str(output), source=str(path),
                            next_action=derived['rebuild'], meaning='来源变化；尚未判断内容是否过时或可采纳'))
                for coverage in derived.get('coverage', []):
                    actual = {loc.relative(base, p).as_posix() for p in _matches(base, coverage['pattern']) if p.is_file()}
                    declared = set(coverage['included'])
                    if actual != declared:
                        review_required.append(dict(code='COVERAGE_CHANGED', path=str(output),
                            added=sorted(actual-declared), removed=sorted(declared-actual),
                            next_action=derived['rebuild'], meaning='范围变化；收录与审核按项目规则判断'))
        except (OSError,ValueError,KeyError,TypeError) as error:
            failures.append(dict(code='DOC_CHECK_FAILED',path=str(manifest),message=str(error)))
    return dict(ok=not failures and not unavailable, checked_documents=checked, failures=failures,
                unavailable=unavailable, maintenance=mappings,
                derived_checked=derived_checked, review_required=review_required,
                coverage='检查维护映射、显式 Markdown 链接、命令参考和已声明派生来源；语义、审核与 Wiki Link 另行审阅')
