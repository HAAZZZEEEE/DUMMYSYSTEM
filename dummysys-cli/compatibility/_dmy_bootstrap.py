"""定位固定发行的共享核心；失败时明确报错，不回退旧实现。"""
import json
from pathlib import Path
import sys

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'dmy_vault').is_dir())
manifest = ROOT / 'runtime/state/workspace/cli-install.json'
if not manifest.is_file():
    raise RuntimeError('DUMMYSYS CLI 未安装；请按 CLI 仓库安装说明恢复固定发行')
installed = json.loads(manifest.read_text(encoding='utf-8-sig'))
if installed.get('schema_version') != 1:
    raise RuntimeError('CLI 安装记录版本不支持')
site = Path(installed['core_path'])
if not (site / 'dummysys_core/__init__.py').is_file():
    raise RuntimeError('固定发行的 dummysys-core 不可用；请重新安装已验收发行包')
sys.path.insert(0, str(site))
import dummysys_core
if dummysys_core.__version__ != installed['version']:
    raise RuntimeError('CLI 安装记录与核心版本不匹配')
from dummysys_core.compat import exports
from dummysys_core.operations import external_writer
