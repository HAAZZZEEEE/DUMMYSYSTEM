"""配置加载与校验。

schema_version=1；必填 workspace_root、task_root；apps 含 vscode_exe、edge_exe、
obsidian_vault_path；服务只监听 127.0.0.1，port 默认 0 由系统分配。未知键报配置错误；
缺少单个应用只禁用对应动作，不能阻断目录浏览。路径全部由配置文件位置或绝对根解析，
不依赖 cwd。
"""
from __future__ import annotations

import json
from pathlib import Path
from dummysys_core import locations as loc

SCHEMA_VERSION = 1
DEFAULT_PORT = 0
REQUIRED_KEYS = ("workspace_root", "task_root")
APP_KEYS = ("vscode_exe", "edge_exe", "obsidian_vault_path", "window_launcher_exe")
KNOWN_KEYS = {"schema_version", "workspace_root", "task_root", "port", "apps"}


class ConfigError(ValueError):
    """配置非法。"""


def _resolve_path(base: Path, raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else (base / path).resolve()


def load_config(config_path: str | Path) -> dict:
    path = Path(config_path)
    if not path.is_file():
        raise ConfigError(f"配置文件不存在：{path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ConfigError(f"配置文件不是合法 JSON：{error}") from error
    if not isinstance(raw, dict):
        raise ConfigError("配置文件顶层必须是 JSON 对象")
    unknown = set(raw) - KNOWN_KEYS
    if unknown:
        raise ConfigError(f"配置包含未知键：{', '.join(sorted(unknown))}")
    schema = raw.get("schema_version")
    if schema != SCHEMA_VERSION:
        raise ConfigError(f"不支持的 schema_version：{schema!r}")
    missing = [k for k in REQUIRED_KEYS if not raw.get(k)]
    if missing:
        raise ConfigError(f"缺少必填键：{', '.join(missing)}")
    base = path.resolve().parent
    workspace_root = _resolve_path(base, str(raw["workspace_root"]))
    task_root = _resolve_path(base, str(raw["task_root"]))
    if not workspace_root.is_dir():
        raise ConfigError(f"workspace_root 不存在：{workspace_root}")
    try:
        loc.load(workspace_root)
    except ValueError as error:
        raise ConfigError(f"工作区资料位置无效：{error}") from error
    apps_raw = raw.get("apps")
    if apps_raw is None:
        apps_raw = {}
    if not isinstance(apps_raw, dict):
        raise ConfigError("apps 必须是 JSON 对象")
    apps = {}
    for key in APP_KEYS:
        value = apps_raw.get(key)
        if value in (None, ""):
            apps[key] = None
        else:
            apps[key] = str(value)
    port = raw.get("port", DEFAULT_PORT)
    if not isinstance(port, int) or isinstance(port, bool) or not (0 <= port <= 65535):
        raise ConfigError(f"port 必须是 0..65535 的整数：{port!r}")
    return {
        "schema_version": SCHEMA_VERSION,
        "workspace_root": workspace_root,
        "task_root": task_root,
        "port": port,
        "apps": apps,
        "config_path": path,
    }


def write_example_config(path: str | Path) -> None:
    """示例按配置文件位置解析；实际绝对配置由 dmy init 生成。"""
    example = dict(schema_version=1, workspace_root="../..", task_root=".", port=0, apps={})
    with Path(path).open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(example, ensure_ascii=False, indent=2) + "\n")
