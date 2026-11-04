"""生成命令参考或只读检查；运行时数据不进入仓库。"""
import argparse
from pathlib import Path
import sys

root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'apps/cli/src'),str(root/'packages/core/src')]
from dummysys_cli.doccheck import command_reference

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--check',action='store_true',help='只读比较，过期时返回 1')
args=parser.parse_args()
path=root/'apps/cli/docs/commands.md'; expected=command_reference()
if args.check:
    ok=path.is_file() and path.read_text(encoding='utf-8')==expected
    print('命令参考：'+('通过' if ok else '待更新'))
    raise SystemExit(0 if ok else 1)
path.parent.mkdir(parents=True,exist_ok=True)
path.write_text(expected,encoding='utf-8')
print(str(path))
