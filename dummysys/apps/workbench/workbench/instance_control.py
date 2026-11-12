"""当前用户限定的实例 Mutex 与命名管道；所有控制消息先验证对端身份。"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import threading
import time

from .control_protocol import ControlProtocol
from .windows_identity import current_user_sid, identity_matches, process_identity


def instance_digest(task_root: str) -> str:
    root = os.path.normcase(str(Path(task_root).resolve()))
    return hashlib.sha256(root.encode("utf-8")).hexdigest()[:16]


def mutex_name(task_root: str, purpose: str = "serve") -> str:
    suffix = "" if purpose == "serve" else f"_{purpose}"
    return f"Local\\DUMMYSYSWorkbench_{current_user_sid()}_{instance_digest(task_root)}{suffix}"


def pipe_name(task_root: str) -> str:
    return f"\\\\.\\pipe\\DUMMYSYSWorkbench_{current_user_sid()}_{instance_digest(task_root)}"


def user_security_attributes():
    """显式保护 DACL：只有当前用户可访问，不继承默认安全描述符。"""
    import pywintypes
    import win32security
    attributes = pywintypes.SECURITY_ATTRIBUTES()
    attributes.bInheritHandle = False
    attributes.SECURITY_DESCRIPTOR = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        f"D:P(A;;GA;;;{current_user_sid()})", win32security.SDDL_REVISION_1)
    return attributes


def _close_handle(handle):
    import win32api
    win32api.CloseHandle(handle)


_user_sid = current_user_sid  # 原 windows 私有入口的兼容别名


class InstanceMutex:
    """通过命名对象存在性互斥；已有对象立即关闭新句柄，失败绝不视为获取成功。"""

    def __init__(self, task_root: str, purpose: str = "serve"):
        self.name = mutex_name(task_root, purpose)
        self._handle = None
        self._lock = threading.Lock()

    def acquire(self, timeout_ms: int = 0) -> bool:
        import win32api
        import win32event
        deadline = time.monotonic() + timeout_ms / 1000
        with self._lock:
            if self._handle is not None:
                return False
            while True:
                try:
                    handle = win32event.CreateMutex(user_security_attributes(), False, self.name)
                    exists = win32api.GetLastError() == 183
                except Exception:
                    raise RuntimeError("无法创建工作台互斥量") from None
                if not exists:
                    self._handle = handle
                    return True
                _close_handle(handle)
                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.025)

    def release(self) -> None:
        with self._lock:
            if self._handle is not None:
                handle, self._handle = self._handle, None
                _close_handle(handle)


class PipeControl(ControlProtocol):
    """消息必须携带 expected_instance_id；写入前检查服务 PID/FILETIME/SID。

    采用非阻塞消息管道并设置操作期限，空闲或恶意客户端不能阻塞服务退出。
    """

    def __init__(self, task_root: str):
        self.name = pipe_name(task_root)
        self._server_handle = None
        self._thread = None
        self._stop = threading.Event()
        self._instance_id = None
        self._token_provider = None
        self._stop_callback = None

    def start_server(self, token_provider, instance_id: str, stop_callback=None) -> None:
        import win32pipe
        if not instance_id or self._thread is not None:
            raise RuntimeError("管道实例无效或已启动")
        self._instance_id = instance_id
        self._token_provider = token_provider
        self._stop_callback = stop_callback
        self._stop.clear()
        # FIRST_PIPE_INSTANCE 防止管道名称被抢占；REJECT_REMOTE_CLIENTS 禁止远程访问。
        self._server_handle = win32pipe.CreateNamedPipe(
            self.name, win32pipe.PIPE_ACCESS_DUPLEX | 0x00080000,
            win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE |
            win32pipe.PIPE_NOWAIT | 0x8, 1, self.MAX_MESSAGE, self.MAX_MESSAGE, 1000,
            user_security_attributes())
        self._thread = threading.Thread(target=self._serve_loop, daemon=True)
        self._thread.start()

    def _verify_peer(self, handle, expected: dict | None = None) -> dict:
        import win32pipe
        pid = (win32pipe.GetNamedPipeServerProcessId(handle) if expected is not None
               else win32pipe.GetNamedPipeClientProcessId(handle))
        actual = process_identity(pid)
        if not actual or actual["user_sid"] != current_user_sid():
            raise ConnectionError("管道对端用户身份不匹配")
        if expected is not None and not identity_matches(actual, expected):
            raise ConnectionError("管道服务进程身份不匹配")
        return actual

    def _read(self, handle, deadline: float) -> bytes:
        import win32file
        while time.monotonic() < deadline and not self._stop.is_set():
            try:
                code, data = win32file.ReadFile(handle, self.MAX_MESSAGE)
                if code == 0 and data:
                    return data
                if code != 0:
                    raise ConnectionError("控制消息过长或无效")
            except win32file.error as error:
                if error.winerror != 232:  # 非阻塞管道暂无数据
                    raise ConnectionError("读取控制消息失败") from None
            self._stop.wait(0.01)
        raise TimeoutError("等待控制消息超时")

    @staticmethod
    def _write(handle, data: bytes) -> None:
        import win32file
        code, written = win32file.WriteFile(handle, data)
        if code or written != len(data):
            raise ConnectionError("写入控制消息失败")

    def _serve_loop(self) -> None:
        import win32pipe
        handle = self._server_handle
        try:
            while not self._stop.is_set():
                try:
                    win32pipe.ConnectNamedPipe(handle, None)
                except Exception as error:
                    if getattr(error, "winerror", None) != 535:
                        self._stop.wait(0.01)
                        continue
                try:
                    peer = self._verify_peer(handle)
                    data = self._read(handle, time.monotonic() + self.CLIENT_TIMEOUT)
                    # PID 对应进程必须仍是连接时的同一进程。
                    if not identity_matches(self._verify_peer(handle), peer):
                        raise ConnectionError("管道客户端身份已改变")
                    response = self._dispatch(data.decode("utf-8"))
                    self._write(handle, response.encode("utf-8"))
                    # DisconnectNamedPipe 会丢弃未读缓冲；等待客户端收讫后再断开。
                    try:
                        self._read(handle, time.monotonic() + self.CLIENT_TIMEOUT)
                    except (ConnectionError, TimeoutError):
                        pass
                    # 先交付响应，再触发关闭；请求和对端均已通过身份校验。
                    if json.loads(response).get("stopping") and self._stop_callback:
                        self._stop_callback()
                except Exception:
                    # 消息可能含令牌或凭据，不输出原文与异常详情。
                    pass
                finally:
                    try:
                        win32pipe.DisconnectNamedPipe(handle)
                    except Exception:
                        pass
        finally:
            _close_handle(handle)
            self._server_handle = None

    def stop_server(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=self.CLIENT_TIMEOUT + 1)
            if thread.is_alive():
                raise RuntimeError("控制管道未能停止")
            self._thread = None

    def _connect(self, timeout_ms: int):
        import win32file
        deadline = time.monotonic() + timeout_ms / 1000
        while True:
            try:
                # SECURITY_SQOS_PRESENT | SECURITY_IDENTIFICATION：不授予服务器模拟权限。
                return win32file.CreateFile(self.name, win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                                            0, None, win32file.OPEN_EXISTING, 0x00110000, None)
            except win32file.error as error:
                if error.winerror not in (2, 231) or time.monotonic() >= deadline:
                    raise ConnectionError("无法连接控制管道") from None
                time.sleep(0.01)

    def request(self, action: str, timeout_ms: int = 10000, *, expected_instance_id: str,
                expected_process: dict) -> dict:
        import win32pipe
        if not isinstance(expected_instance_id, str) or not expected_instance_id:
            raise ValueError("控制请求必须指定实例身份")
        if not identity_matches(expected_process, expected_process):
            raise ValueError("控制请求必须指定完整进程身份")
        deadline = time.monotonic() + timeout_ms / 1000
        handle = self._connect(timeout_ms)
        try:
            # 必须发生在 WriteFile 之前；响应后的实例检查无法撤销已发出的 stop。
            self._verify_peer(handle, expected_process)
            win32pipe.SetNamedPipeHandleState(
                handle, win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_NOWAIT, None, None)
            self._write(handle, json.dumps({"action": action,
                                           "expected_instance_id": expected_instance_id}).encode("utf-8"))
            response = json.loads(self._read(handle, deadline).decode("utf-8"))
            if not isinstance(response, dict) or response.get("instance_id") != expected_instance_id:
                raise ConnectionError("控制响应实例身份不匹配")
            self._write(handle, b'{"received":true}')
            if response.get("error"):
                raise ConnectionError("控制请求被拒绝")
            return response
        finally:
            _close_handle(handle)
