"""Windows 适配：应用探测、外部打开、单实例互斥与命名管道。

生产实现真正打开应用；测试注入记录型适配器。Obsidian 使用官方 URI open 动作，
路径参数独立编码；VS Code 使用参数数组调用 Code.exe；资源管理器使用 explorer.exe
定位。shell 适配器只接收结构化目标与预设动作，不能接收命令文本。

命名管道用于启动器与服务之间交换一次性 bootstrap token/控制消息；管道名绑定用户
SID 与 task_root 摘要，令牌不进入日志、配置文件或服务启动参数。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

from .ports import AppUnavailable, OpenFailed
from .action_policy import SCRIPT_EXTENSIONS
from .processes import spawn_background
from .instance_control import (InstanceMutex, PipeControl, instance_digest, mutex_name,
                               pipe_name, _user_sid, _close_handle)
from .windows_identity import process_identity, current_user_sid
from .window_control import activate_edge_window, activate_native_window, native_window_handle, public_url

APP_UNAVAILABLE_MSG = "应用不可用或未配置"

def detect_vscode() -> str | None:
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Microsoft VS Code/Code.exe",
        Path("C:/Program Files/Microsoft VS Code/Code.exe"),
        Path("C:/Program Files (x86)/Microsoft VS Code/Code.exe"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def detect_edge() -> str | None:
    candidates = [
        Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
        Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


class WindowsOpener:
    """生产打开适配器：真正调用本机应用。"""

    supports_native_window = True

    def __init__(self, config: dict):
        apps = config.get("apps", {})
        self.vscode_exe = apps.get("vscode_exe") or detect_vscode()
        self.edge_exe = apps.get("edge_exe") or detect_edge()
        self.window_launcher_exe = apps.get("window_launcher_exe")
        self.obsidian_vault = apps.get("obsidian_vault_path")
        self._events: list[dict] = []

    def open_browser(self, url, profile_dir=None):
        return self.edge_app_mode(url, profile_dir)

    def activate_browser(self, url, profile_dir):
        return self.activate_edge_app(url, profile_dir)

    # ---- 探测 ----
    def probe(self) -> dict:
        vscode = self.vscode_exe or detect_vscode()
        edge = self.edge_exe or detect_edge()
        vscode_ok = bool(vscode and Path(vscode).is_file())
        edge_ok = bool(edge and Path(edge).is_file())
        return {
            "vscode": {"available": vscode_ok,
                       "exe": vscode if vscode_ok else None,
                       "reason": None if vscode_ok else "未探测到 VS Code 可执行文件"},
            "edge": {"available": edge_ok,
                     "exe": edge if edge_ok else None,
                     "reason": None if edge_ok else "未探测到 Edge 可执行文件"},
            "obsidian": {"available": self.obsidian_vault is not None,
                         "vault": self.obsidian_vault,
                         "reason": None if self.obsidian_vault else "未配置 Obsidian Vault 路径"},
        }

    # ---- 打开动作 ----
    def _require_vscode(self) -> str:
        exe = self.vscode_exe or detect_vscode()
        if not exe or not Path(exe).is_file():
            raise AppUnavailable("VS Code 不可用")
        return exe

    def _require_edge(self) -> str:
        exe = self.edge_exe or detect_edge()
        if not exe or not Path(exe).is_file():
            raise AppUnavailable("Edge 不可用")
        return exe

    def vscode_open(self, path: str) -> None:
        exe = self._require_vscode()
        if not os.path.exists(path):
            raise OpenFailed("目标不存在，未调用编辑器")
        self._events.append({"action": "vscode_open", "target": path})
        self._spawn([exe, path])

    def explorer_open(self, path: str) -> None:
        if not os.path.exists(path):
            raise OpenFailed("目标不存在")
        self._events.append({"action": "explorer_open", "target": path})
        self._spawn(["explorer.exe", os.path.normpath(path)])

    def explorer_reveal(self, path: str) -> None:
        if not os.path.exists(path):
            raise OpenFailed("目标不存在")
        self._events.append({"action": "explorer_reveal", "target": path})
        self._spawn(["explorer.exe", "/select,", os.path.normpath(path)])

    def obsidian_open(self, path: str) -> None:
        if not self.obsidian_vault:
            raise AppUnavailable("未配置 Obsidian Vault 路径")
        if not os.path.exists(path):
            raise OpenFailed("目标不存在，未发起打开")
        encoded = quote(path, safe="")
        uri = f"obsidian://open?path={encoded}"
        self._events.append({"action": "obsidian_open", "target": path, "uri": uri})
        try:
            os.startfile(uri)
        except OSError as error:
            raise OpenFailed(f"Obsidian 打开失败：{error}") from error

    def system_open(self, path: str) -> None:
        if not os.path.exists(path):
            raise OpenFailed("目标不存在，未发起打开")
        ext = Path(path).suffix.casefold()
        if ext in SCRIPT_EXTENSIONS:
            raise AppUnavailable("可执行或脚本文件不提供系统默认打开")
        self._events.append({"action": "system_open", "target": path})
        try:
            os.startfile(path)  # 固定结构化目标，非命令文本
        except OSError as error:
            raise OpenFailed(f"系统默认应用打开失败：{error}") from error

    def activate_edge_app(self, url: str, profile_dir: str) -> bool:
        return activate_edge_window(profile_dir, self._require_edge(), public_url(url))

    def activate_native_app(self, record: dict) -> bool:
        return activate_native_window(record)

    def native_app_ready(self, record: dict) -> bool:
        return native_window_handle(record) is not None

    def native_app_mode(self, config_path: str, instance_id: str) -> None:
        if self.window_launcher_exe:
            if not Path(self.window_launcher_exe).is_file():
                raise OpenFailed("配置的工作台窗口启动器不存在")
            args = [self.window_launcher_exe]
        else:
            args = ([sys.executable] if getattr(sys, "frozen", False)
                    else [sys.executable, "-B", "-m", "workbench"])
        args += ["window", "--config", config_path, "--instance-id", instance_id]
        self._spawn(args, detach=True)

    def edge_app_mode(self, url: str, profile_dir: str | None = None) -> None:
        exe = self._require_edge()
        args = [exe, f"--app={url}"]
        if profile_dir:
            args.append(f"--user-data-dir={profile_dir}")
        self._events.append({"action": "edge_app_mode", "url": public_url(url)})
        self._spawn(args, detach=True)

    @staticmethod
    def _spawn(args: list[str], detach: bool = False) -> subprocess.Popen:
        try:
            return spawn_background(args, independent=detach,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        except OSError as error:
            raise OpenFailed("进程创建失败") from None

    def events(self) -> list[dict]:
        return list(self._events)


class RecordingOpener:
    """测试打开适配器：只记录动作和目标，不真正打开应用。"""

    def open_browser(self, url, profile_dir=None):
        return self.edge_app_mode(url, profile_dir)

    def __init__(self, probe_result: dict | None = None):
        self._events: list[dict] = []
        self._probe = probe_result or {
            "vscode": {"available": True, "exe": "Code.exe", "reason": None},
            "edge": {"available": True, "exe": "msedge.exe", "reason": None},
            "obsidian": {"available": True, "vault": "vault", "reason": None},
        }

    def probe(self) -> dict:
        return self._probe

    def _record(self, action: str, target: str, **extra) -> None:
        self._events.append({"action": action, "target": target, **extra})

    def vscode_open(self, path: str) -> None:
        self._record("vscode_open", path)

    def explorer_open(self, path: str) -> None:
        self._record("explorer_open", path)

    def explorer_reveal(self, path: str) -> None:
        self._record("explorer_reveal", path)

    def obsidian_open(self, path: str) -> None:
        self._record("obsidian_open", path)

    def system_open(self, path: str) -> None:
        self._record("system_open", path)

    def edge_app_mode(self, url: str, profile_dir: str | None = None) -> None:
        self._record("edge_app_mode", public_url(url), profile_dir=profile_dir)

    def events(self) -> list[dict]:
        return list(self._events)
