"""Shared native window for the existing local Workbench service."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

from .platform_runtime import PipeControl, process_identity
from .lifecycle import Lifecycle, SCHEMA_VERSION, write_json
import sys
from .native_host import host_backend


def window_icon(config: dict) -> str | None:
    configured = config.get('apps', {}).get('window_icon_path')
    if configured:
        icon = Path(configured)
        if not icon.is_file():
            raise RuntimeError('配置的工作台窗口图标不存在')
        return str(icon)
    if sys.platform == 'darwin' and getattr(sys, 'frozen', False):
        icon = Path(sys.executable).parent.parent / 'Resources/DUMMYSYS.icns'
        return str(icon) if icon.is_file() else None
    icon = Path(__file__).resolve().parent / 'static' / 'icons' / 'app-icon.ico'
    return str(icon) if icon.is_file() else None


def show(config: dict, instance_id: str) -> None:
    icon = window_icon(config)
    backend = host_backend()
    backend.prepare()
    import webview

    lifecycle = Lifecycle(config)
    record = lifecycle.instance.is_healthy()
    if not record or record["instance_id"] != instance_id:
        raise RuntimeError("工作台实例已变化，无法打开窗口")
    response = lifecycle.pipe.request(PipeControl.REQUEST_TOKEN,
                                      expected_instance_id=instance_id,
                                      expected_process=record)
    token = response.get("token")
    if response.get("instance_id") != instance_id or not isinstance(token, str) or not token:
        raise RuntimeError("无法获取工作台窗口启动令牌")
    url = f"http://127.0.0.1:{record['port']}/#token={quote(token, safe='')}"
    window = webview.create_window("DUMMYSYS 工作台", url, width=1320, height=850,
                                   min_size=(760, 500), background_color="#f6f5f8")
    identity = process_identity(os.getpid())
    if not identity:
        raise RuntimeError("无法确认工作台窗口进程")
    window_record = {"schema_version": SCHEMA_VERSION, "kind": "native",
                     "instance_id": instance_id, "port": record["port"], **identity,
                     "app_user_model_id": "DUMMYSYS.Workbench", "icon_path": icon}

    def shown():
        # The parent launches under the launch mutex; the GUI publishes itself only
        # after its real top-level window exists and can be independently verified.
        write_json(lifecycle.instance.window_path, window_record)
        (lifecycle.instance.state / "window-error.log").unlink(missing_ok=True)

    def closed():
        from .lifecycle import read_json
        current = read_json(lifecycle.instance.window_path)
        if current.get("instance_id") == instance_id and current.get("pid") == identity["pid"]:
            lifecycle.instance.window_path.unlink(missing_ok=True)

    window.events.shown += shown
    window.events.closed += closed
    backend.run(webview, window, lifecycle, window_record, icon)
