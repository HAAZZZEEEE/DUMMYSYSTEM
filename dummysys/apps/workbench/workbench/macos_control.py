"""当前用户私有的 Unix socket 和 Workbench 实例锁。"""
import json
import os
from pathlib import Path
import socket
import stat
import struct
import threading
import time

from dummysys_core.local_lock import FileLock, mac_path_digest
from .control_protocol import ControlProtocol
from .macos_identity import current_user_sid, identity_matches, process_identity


def _control_dir():
    path = Path('/private/tmp') / f'dmy-wb-{os.geteuid()}'
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise PermissionError('工作台控制目录必须是当前用户私有目录')
    return path


class InstanceMutex:
    def __init__(self, task_root, purpose='serve'):
        self.lock = FileLock(_control_dir() / f'{mac_path_digest(task_root)[:32]}-{purpose}.lock')
        self.guard = threading.Lock()

    def acquire(self, timeout_ms=0):
        with self.guard:
            return self.lock.acquire(timeout_ms / 1000)

    def release(self):
        with self.guard:
            self.lock.release()


def _peer(connection):
    # SDK: sys/un.h, SOL_LOCAL=0, LOCAL_PEERPID=2. The kernel supplies this PID.
    pid, = struct.unpack('i', connection.getsockopt(0, 2, struct.calcsize('i')))
    actual = process_identity(pid)
    if not actual or actual['user_sid'] != current_user_sid():
        raise ConnectionError('控制连接的对端用户身份不匹配')
    return actual


def _receive(connection, limit, timeout):
    deadline = time.monotonic() + timeout
    data = bytearray()
    while len(data) <= limit:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('控制消息读取超时')
        connection.settimeout(remaining)
        part = connection.recv(min(1024, limit + 1 - len(data)))
        if not part:
            break
        data.extend(part)
        if data.endswith(b'\n') and len(data) <= limit:
            return data.decode('utf-8')
    raise ConnectionError('控制消息过长或不完整')


class PipeControl(ControlProtocol):

    def __init__(self, task_root, purpose="control"):
        self._ownership = InstanceMutex(task_root, purpose)
        self.path = _control_dir() / (mac_path_digest(task_root)[:32] + '-' + purpose + '.sock')
        self._server = None
        self._thread = None
        self._stop = threading.Event()
        self._instance_id = None
        self._token_provider = None
        self._stop_callback = None

    def start_server(self, token_provider, instance_id, stop_callback=None):
        if not instance_id or self._thread is not None:
            raise RuntimeError('控制实例无效或已启动')
        if not self._ownership.acquire():
            raise RuntimeError("控制服务已经运行")
        try:
            self._start(token_provider, instance_id, stop_callback)
        except BaseException:
            self._ownership.release()
            raise

    def _start(self, token_provider, instance_id, stop_callback):
        # Lifecycle holds the service lock here. A crashed service may leave its socket path.
        try:
            existing = self.path.lstat()
        except FileNotFoundError:
            pass
        else:
            if not stat.S_ISSOCK(existing.st_mode) or existing.st_uid != os.geteuid():
                raise RuntimeError('控制路径被非工作台 socket 占用')
            self.path.unlink()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server.bind(str(self.path))
            self.path.chmod(0o600)
            server.listen(8)
            server.settimeout(0.2)
        except OSError:
            server.close()
            raise
        self._server = server
        self._instance_id = instance_id
        self._token_provider = token_provider
        self._stop_callback = stop_callback
        self._stop.clear()
        self._thread = threading.Thread(target=self._serve_loop, daemon=True)
        self._thread.start()

    def _serve_loop(self):
        while not self._stop.is_set():
            try:
                client, _ = self._server.accept()
            except TimeoutError:
                continue
            with client:
                try:
                    peer = _peer(client)
                    data = _receive(client, self.MAX_MESSAGE, self.CLIENT_TIMEOUT)
                    if not identity_matches(_peer(client), peer):
                        raise ConnectionError('控制客户端身份已改变')
                    response = self._dispatch(data)
                    client.sendall(response.encode('utf-8') + b'\n')
                    if json.loads(response).get('stopping') and self._stop_callback:
                        self._stop_callback()
                except (OSError, RuntimeError, ValueError):
                    # 控制消息可能包含一次性令牌，禁止输出原文。
                    continue

    def stop_server(self):
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join(timeout=self.CLIENT_TIMEOUT + 1)
        if self._thread.is_alive():
            raise RuntimeError('控制 socket 未能停止')
        self._server.close()
        self.path.unlink(missing_ok=True)
        self._server = self._thread = None
        self._ownership.release()

    def request(self, action, timeout_ms=10000, *, expected_instance_id, expected_process):
        if not expected_instance_id or not identity_matches(expected_process, expected_process):
            raise ValueError('控制请求必须指定完整的实例和进程身份')
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(timeout_ms / 1000)
            client.connect(str(self.path))
            if not identity_matches(_peer(client), expected_process):
                raise ConnectionError('控制服务进程身份不匹配')
            message = {'action': action, 'expected_instance_id': expected_instance_id}
            client.sendall(json.dumps(message).encode('utf-8') + b'\n')
            response = json.loads(_receive(client, self.MAX_MESSAGE, timeout_ms / 1000))
        if (not isinstance(response, dict) or response.get('instance_id') != expected_instance_id
                or response.get('error')):
            raise ConnectionError('控制响应被拒绝或实例身份不匹配')
        return response
