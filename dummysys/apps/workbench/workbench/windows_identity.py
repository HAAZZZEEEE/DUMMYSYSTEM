"""Windows 进程身份：PID + 原始 FILETIME + 用户 SID，查询失败时拒绝信任。"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os


WORKBENCH_APP_ID = 'DUMMYSYS.Workbench'


def set_workbench_app_id():
    """GUI 创建前声明应用身份，避免任务栏将工作台归入 Python 进程组。"""
    if os.name != 'nt':
        return
    api = ctypes.WinDLL('shell32')
    api.SetCurrentProcessExplicitAppUserModelID.argtypes = [wintypes.LPCWSTR]
    api.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
    if api.SetCurrentProcessExplicitAppUserModelID(WORKBENCH_APP_ID) < 0:
        raise RuntimeError('无法设置工作台窗口身份')


def _kernel32():
    if os.name != "nt":
        raise RuntimeError("进程身份查询仅支持 Windows")
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    api.OpenProcess.restype = wintypes.HANDLE
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.WaitForSingleObject.restype = wintypes.DWORD
    api.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    api.GetProcessTimes.restype = wintypes.BOOL
    return api


def process_identity(pid: int) -> dict | None:
    """返回 {pid, process_created_at, user_sid}；已退出返回 None，无法核实抛错。

    process_created_at 为 GetProcessTimes 原始 64 位 FILETIME 的十进制字符串，
    不经过浮点、时区或微秒转换。句柄在时间与 SID 取证期间始终持有。
    """
    if type(pid) is not int or not 0 < pid <= 0xFFFFFFFF:
        raise ValueError("无效的进程 PID")
    import win32security
    api = _kernel32()
    handle = api.OpenProcess(0x1000 | 0x00100000, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error == 87:  # ERROR_INVALID_PARAMETER：PID 不存在
            return None
        raise RuntimeError("无法核实进程身份")
    try:
        wait = api.WaitForSingleObject(handle, 0)
        if wait == 0:
            return None
        if wait != 258:
            raise RuntimeError("无法核实进程运行状态")
        created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
        if not api.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                   ctypes.byref(kernel), ctypes.byref(user)):
            raise RuntimeError("无法读取进程创建时间")
        token = win32security.OpenProcessToken(handle, win32security.TOKEN_QUERY)
        try:
            sid = win32security.ConvertSidToStringSid(
                win32security.GetTokenInformation(token, win32security.TokenUser)[0])
        finally:
            token.Close()
        if not sid:
            raise RuntimeError("无法读取进程用户 SID")
        return {"pid": pid, "process_created_at": str((created.dwHighDateTime << 32) | created.dwLowDateTime),
                "user_sid": sid}
    except Exception:
        raise RuntimeError("无法核实进程身份") from None
    finally:
        api.CloseHandle(handle)


def current_user_sid() -> str:
    identity = process_identity(os.getpid())
    if not identity or not identity.get("user_sid"):
        raise RuntimeError("无法读取当前用户 SID")
    return identity["user_sid"]


from .identity import identity_matches

def process_alive(pid: int) -> bool:
    try:
        return process_identity(pid) is not None
    except (OSError, RuntimeError, ValueError):
        return False
