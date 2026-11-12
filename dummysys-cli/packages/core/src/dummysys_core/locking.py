"""工作区独占锁契约和本机实现；事务流程只依赖 acquire/release。"""
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import sys
from typing import Protocol

from .local_lock import FileLock, mac_path_digest


class WorkspaceMutex(Protocol):
    def acquire(self, timeout: float = 0) -> bool: ...
    def release(self) -> None: ...


class WindowsMutex:
    def __init__(self, root):
        key = os.path.normcase(str(Path(root).resolve()))
        self.name = 'Global\\DUMMYSYS-' + hashlib.sha256(key.encode()).hexdigest()
        self.handle = None
        self.api = ctypes.WinDLL('kernel32', use_last_error=True)
        self.api.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self.api.CreateMutexW.restype = wintypes.HANDLE
        self.api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.api.WaitForSingleObject.restype = wintypes.DWORD
        self.api.ReleaseMutex.argtypes = [wintypes.HANDLE]
        self.api.ReleaseMutex.restype = wintypes.BOOL
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.api.CloseHandle.restype = wintypes.BOOL

    def acquire(self, timeout=0):
        if self.handle is not None:
            return False
        handle = self.api.CreateMutexW(None, False, self.name)
        if not handle:
            raise OSError(ctypes.get_last_error(), '创建工作区互斥量失败')
        result = self.api.WaitForSingleObject(handle, int(timeout * 1000))
        if result in (0, 0x80):  # abandoned mutex also grants ownership
            self.handle = handle
            return True
        self.api.CloseHandle(handle)
        if result == 0x102:
            return False
        raise OSError(ctypes.get_last_error(), '获取工作区互斥量失败')

    def release(self):
        if self.handle is not None:
            handle, self.handle = self.handle, None
            try:
                self.api.ReleaseMutex(handle)
            finally:
                self.api.CloseHandle(handle)


def supported_platform():
    return os.name == 'nt' or sys.platform == 'darwin'


def workspace_mutex(root) -> WorkspaceMutex:
    if os.name == 'nt':
        return WindowsMutex(root)
    if sys.platform == 'darwin':
        # 固定位置使不同 TMPDIR 的调用者仍共用锁；文件永不主动删除。
        return FileLock(Path('/private/tmp') / ('dummysys-workspace-' + mac_path_digest(root) + '.lock'))
    raise OSError('受管操作仅支持 Windows 和 macOS')
