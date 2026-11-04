"""仅激活经过 profile、服务地址、进程树与窗口归属核验的 Edge 窗口。"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import gc
import os
from urllib.parse import urlsplit, urlunsplit

from .windows_identity import current_user_sid, identity_matches, process_identity


def public_url(url: str) -> str:
    """供结果/日志使用的地址：剔除 fragment、查询和 userinfo。"""
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
        return urlunsplit((parts.scheme, host + port, parts.path, "", ""))
    except ValueError:
        return ""


def _path(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


def _argv(command: str) -> list[str]:
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    shell.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    kernel.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel.LocalFree.restype = wintypes.HLOCAL
    count = ctypes.c_int()
    result = shell.CommandLineToArgvW(command, ctypes.byref(count))
    if not result:
        raise RuntimeError("无法解析 Edge 进程参数")
    try:
        return [result[index] for index in range(count.value)]
    finally:
        kernel.LocalFree(result)


def _read_edge_snapshot() -> tuple[list[dict], str | None]:
    """COM 代理只属于此帧；不让异常 traceback 将代理带出此作用域。"""
    import win32com.client
    try:
        service = win32com.client.GetObject("winmgmts:")
        result = []
        for proc in service.ExecQuery(
                "SELECT ProcessId, ParentProcessId, ExecutablePath, CommandLine "
                "FROM Win32_Process WHERE Name='msedge.exe'"):
            identity = process_identity(int(proc.ProcessId))
            if identity and proc.ExecutablePath and proc.CommandLine:
                result.append({**identity, "parent_pid": int(proc.ParentProcessId),
                               "exe": str(proc.ExecutablePath), "argv": _argv(str(proc.CommandLine))})
        return result, None
    except Exception as error:
        # 仅返回错误类型，不保留原异常/回溯或可能含凭据的命令行。
        return [], type(error).__name__


def edge_processes() -> list[dict]:
    """只读 WMI 快照；COM 代理及异常引用必须先于 apartment 释放。"""
    import pythoncom
    pythoncom.CoInitialize()
    try:
        result, error_type = _read_edge_snapshot()
        if error_type:
            raise RuntimeError(f"无法读取 Edge 进程快照（{error_type}）")
        return result
    finally:
        # helper 已退出，局部代理不再存活；收集异常路径产生的引用环。
        # 不调用 CDispatch._Release_：部分 pywin32 的 PyIDispatch 不公开 Release。
        try:
            gc.collect()
        finally:
            pythoncom.CoUninitialize()


def verified_edge_tree(processes: list[dict], profile_dir: str, exe: str, url: str,
                       user_sid: str) -> dict[int, dict]:
    """纯函数：根须同时匹配 profile 与 app URL，后代须同 exe/SID 且晚于父进程。"""
    candidates = {p["pid"]: p for p in processes
                  if p.get("user_sid") == user_sid and _path(p.get("exe", "")) == _path(exe)}
    tree = {}
    for pid, proc in candidates.items():
        args = proc.get("argv", [])
        profiles = [a.split("=", 1)[1] for a in args if a.startswith("--user-data-dir=")]
        apps = [a.split("=", 1)[1] for a in args if a.startswith("--app=")]
        if (len(profiles) == len(apps) == 1 and _path(profiles[0]) == _path(profile_dir)
                and public_url(apps[0]) == public_url(url)):
            tree[pid] = proc
    while True:
        added = {pid: p for pid, p in candidates.items() if pid not in tree
                 and p.get("parent_pid") in tree
                 and int(p["process_created_at"]) >= int(tree[p["parent_pid"]]["process_created_at"])}
        if not added:
            return tree
        tree.update(added)


def activate_edge_window(profile_dir: str, exe: str, url: str) -> bool:
    """不能核实或不能置前时返回 False；不按标题匹配、不关闭或终止任何窗口。"""
    if os.name != "nt":
        return False
    try:
        import win32con
        import win32gui
        import win32process
        tree = verified_edge_tree(edge_processes(), profile_dir, exe, url, current_user_sid())
        windows = []

        def visit(hwnd, _):
            if (win32gui.IsWindowVisible(hwnd) and
                    win32gui.GetClassName(hwnd) == "Chrome_WidgetWin_1" and
                    not win32gui.GetWindow(hwnd, win32con.GW_OWNER)):
                pid = win32process.GetWindowThreadProcessId(hwnd)[1]
                if pid in tree:
                    windows.append((hwnd, pid))

        win32gui.EnumWindows(visit, None)
        if not windows:
            return False
        # 同一实例 profile 可以已有多扇 app 窗口；候选都已通过进程树、窗口类和
        # owner 检查，不因数量大于一而让调用方继续开新窗口。不读取标题来授权。
        foreground = win32gui.GetForegroundWindow()
        hwnd, pid = next((item for item in windows if item[0] == foreground), windows[0])
        # 再核对全树，避免 PID/父进程退出重用或 EnumWindows 后窗口替换。
        if not all(identity_matches(process_identity(p), expected) for p, expected in tree.items()):
            return False
        if (not win32gui.IsWindow(hwnd) or win32process.GetWindowThreadProcessId(hwnd)[1] != pid
                or win32gui.GetClassName(hwnd) != "Chrome_WidgetWin_1"):
            return False
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        return win32gui.GetForegroundWindow() == hwnd
    except Exception:
        return False


def native_window_handle(record: dict) -> int | None:
    """Find the recorded host's top-level window without trusting its title."""
    if os.name != "nt" or not identity_matches(record, record):
        return None
    try:
        import win32con
        import win32gui
        import win32process
        if record.get("user_sid") != current_user_sid():
            return None
        if not identity_matches(process_identity(record["pid"]), record):
            return None
        windows = []

        def visit(hwnd, _):
            if (win32gui.IsWindowVisible(hwnd) and
                    win32gui.GetClassName(hwnd).startswith("WindowsForms10.Window.") and
                    not win32gui.GetWindow(hwnd, win32con.GW_OWNER) and
                    win32process.GetWindowThreadProcessId(hwnd)[1] == record["pid"]):
                windows.append(hwnd)

        win32gui.EnumWindows(visit, None)
        if not windows or not identity_matches(process_identity(record["pid"]), record):
            return None
        return windows[0]
    except Exception:
        return None


def activate_native_window(record: dict) -> bool:
    """Activate only the recorded Workbench host process and its own WinForms window."""
    hwnd = native_window_handle(record)
    if hwnd is None:
        return False
    try:
        import win32con
        import win32gui
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        return win32gui.GetForegroundWindow() == hwnd
    except Exception:
        return False
