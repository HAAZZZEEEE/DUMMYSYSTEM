"""恢复 0.1.1 长路径清单漏项；使用原固定发行 Python 执行，默认只核验。"""
import argparse
import hashlib
import json
import os
from pathlib import Path

from dummysys_core.operations import Operations, workspace_lock
from dummysys_core._migration import MigrationJournal


def inventory(path):
    base = Path('\\\\?\\' + str(Path(path).resolve())) if os.name == 'nt' else Path(path)
    result = {}
    for item in base.rglob('*'):
        if item.is_symlink() or (hasattr(item, 'is_junction') and item.is_junction()):
            raise ValueError('不支持链接')
        if item.is_file():
            result[item.relative_to(base).as_posix()] = hashlib.sha256(item.read_bytes()).hexdigest()
    return result


def verify(original, supplement, actual, source):
    if not supplement or any(len(str(Path(source) / k)) < 260 for k in supplement):
        raise ValueError('补充清单必须仅包含原路径超长的文件')
    if any(Path(k).is_absolute() or '..' in Path(k).parts for k in supplement):
        raise ValueError('补充路径越界')
    if any(k in original and original[k] != v for k, v in supplement.items()):
        raise ValueError('补充清单与原清单冲突')
    expected = original | supplement
    if expected != actual:
        raise ValueError('完整清单不一致，拒绝恢复')
    return expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--operation', required=True)
    parser.add_argument('--supplement', type=Path, required=True)
    parser.add_argument('--actor', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    root = args.workspace.resolve()
    with workspace_lock(root):
        op = Operations(root).show(args.operation)
        if op['tool_version'] != '0.1.1' or op['actor'] != args.actor or op['kind'] != 'migration':
            raise ValueError('仅原负责者可恢复 0.1.1 迁移')
        journal = MigrationJournal(root, args.operation)
        data = journal.load()
        if data['stage'] != 'needs_recovery':
            raise ValueError('操作未处于待判定阶段')
        steps = data['steps']
        if not any(x['stage'] == 'docs_moved' and x['detail'].get('done') for x in steps):
            raise ValueError('文档移动未完成')
        if any(x['stage'] == 'records_updated' for x in steps):
            raise ValueError('记录更新已开始，不适用本恢复命令')
        prepared = next(x['detail'] for x in steps if x['stage'] == 'prepared' and x['detail'].get('done'))
        intent = next(x for x in reversed(steps) if x['stage'] == 'resources_moved' and x['detail'].get('intent'))
        moves = intent['detail']['moves']
        if len(moves) != 1:
            raise ValueError('仅支持单一资源根迁移')
        source, target = map(Path, moves[0])
        if not all(p.resolve().is_relative_to(root / 'runtime/project_src') for p in (source, target)):
            raise ValueError('资源路径越界')
        if source.exists() or not target.is_dir():
            raise ValueError('资源移动尚未完成或源目标冲突')
        proof = args.supplement.resolve()
        if not proof.is_relative_to(root / 'runtime') or proof.stat().st_mtime >= intent['at']:
            raise ValueError('须提供移动前保存在 runtime 的独立清单')
        raw = proof.read_bytes()
        supplement = json.loads(raw.decode('utf-8-sig'))
        full = verify(prepared['inventory'][str(source)], supplement, inventory(target), source)
        detail = dict(done=True, recovery='0.1.1-windows-long-paths', actor=args.actor,
                      evidence=str(proof), evidence_sha256=hashlib.sha256(raw).hexdigest(),
                      verified_inventory=full)
        if args.apply:
            journal.record('resources_moved', detail)
        print(json.dumps(dict(verified_files=len(full), applied=args.apply), ensure_ascii=False))


if __name__ == '__main__':
    main()
