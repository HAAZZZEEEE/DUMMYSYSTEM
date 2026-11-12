"""单实例、会话与任务栏闭环：launch/serve/status/stop 与快捷方式安装。

平台适配器按用户与 task_root 摘要序列化 launch；state/instance.json
保存 PID、进程创建时间、端口、instance_id，PID 不能单独作为归属依据。启动器与服务
通过当前用户控制通道交换 bootstrap token/控制消息。快捷方式指向稳定
WorkbenchLauncher.exe，安装清单记录创建位置与目标。
"""
from __future__ import annotations

import json
import http.client
import os
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .platform_runtime import (InstanceMutex, PipeControl, process_identity, identity_matches,
                               current_user_sid, process_alive, create_opener)
from .processes import spawn_background
from .file_io import write_json

APP_ID = "dummysys.workbench"
SCHEMA_VERSION = 1
READY_TIMEOUT = 10.0
POLL_INTERVAL = 0.2


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, RecursionError):
        return {}


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def state_dir(config: dict) -> Path:
    return Path(config["task_root"]) / "state"


class Instance:
    """本工作台实例身份与状态。"""

    def __init__(self, config: dict):
        self.config = config
        self.task_root = Path(config["task_root"])
        self.state = state_dir(config)
        self.instance_path = self.state / "instance.json"
        self.preferences_path = self.state / "preferences.json"
        self.window_path = self.state / "window.json"
        self.install_path = self.state / "install"
        self.instance_id = str(uuid4())

    def read(self) -> dict:
        # 兼容读取入口；控制决策必须使用保留缺失/损坏差异的 read_state。
        return self.read_state()["record"] or {}

    def read_state(self) -> dict:
        """读取状态文件，区分 missing / corrupt / unreadable / present。

        present 只说明 JSON 为非空对象；是否属于当前实例域还需 valid_record。
        不把解析或访问异常当作无实例，也不将文件内容带入异常/日志。
        """
        try:
            body = self.instance_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            state = "unreadable" if os.path.lexists(self.instance_path) else "missing"
            return {"state": state, "record": None}
        except UnicodeError:
            return {"state": "corrupt", "record": None}
        except OSError:
            return {"state": "unreadable", "record": None}
        try:
            value = json.loads(body)
        except (ValueError, RecursionError):
            return {"state": "corrupt", "record": None}
        if not isinstance(value, dict) or not value:
            return {"state": "corrupt", "record": None}
        return {"state": "present", "record": value}

    def write(self, pid: int, port: int, started_at: str) -> None:
        identity = process_identity(pid)
        if not identity or identity["user_sid"] != current_user_sid():
            raise RuntimeError("无法确认本实例进程身份")
        write_json(self.instance_path, {
            "app_id": APP_ID, "schema_version": SCHEMA_VERSION,
            "instance_id": self.instance_id, **identity,
            "host": "127.0.0.1", "port": port, "started_at": started_at,
            "task_root": str(self.task_root),
        })

    def clear(self) -> None:
        # 仅服务自己可以删除自己的记录；旧实例收尾不能删除新实例状态。
        if self.read().get("instance_id") == self.instance_id:
            self.instance_path.unlink(missing_ok=True)

    def valid_record(self, record: dict) -> bool:
        """验证本应用、工作目录、用户和完整进程身份，不以 HTTP 可用性代替身份。"""
        if (record.get("app_id") != APP_ID or type(record.get("schema_version")) is not int
                or record.get("schema_version") != SCHEMA_VERSION
                or not isinstance(record.get("instance_id"), str) or not record["instance_id"]
                or record.get("host") != "127.0.0.1"
                or type(record.get("port")) is not int or not 0 < record["port"] < 65536
                or not isinstance(record.get("process_created_at"), str)
                or not record["process_created_at"].isdigit()
                or not identity_matches(record, record)
                or record["pid"] > 0xFFFFFFFF
                or not isinstance(record.get("task_root"), str)):
            return False
        return (os.path.normcase(str(Path(record["task_root"]).resolve())) ==
                os.path.normcase(str(self.task_root.resolve()))
                and record.get("user_sid") == current_user_sid())

    def is_healthy(self) -> dict | None:
        record = self.read()
        try:
            if not self.valid_record(record):
                return None
            if not identity_matches(process_identity(record.get("pid")), record):
                return None
            if not health_matches(health_probe(record["port"]), record):
                return None
            if not identity_matches(process_identity(record["pid"]), record):
                return None
        except (OSError, RuntimeError, ValueError, TypeError):
            return None
        return record

    def launch_url(self) -> str | None:
        record = self.is_healthy()
        if not record:
            return None
        return f"http://127.0.0.1:{record['port']}/"


def health_probe(port: int, timeout: float = 0.5) -> dict:
    """直接回环 GET，不走代理、不跟随跳转，限制响应大小。"""
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        connection.request("GET", "/healthz", headers={"Accept": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            return {}
        body = response.read(16385)
        if len(body) > 16384:
            return {}
        value = json.loads(body)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, http.client.HTTPException):
        return {}
    finally:
        connection.close()


def health_matches(response: dict, record: dict) -> bool:
    data = response.get("data")
    return bool(type(response.get("schema_version")) is int
                and response["schema_version"] == SCHEMA_VERSION and isinstance(data, dict)
                and data.get("app_id") == APP_ID
                and type(data.get("schema_version")) is int and data["schema_version"] == SCHEMA_VERSION
                and data.get("instance_id") == record.get("instance_id") and data.get("ready") is True)


def process_exited(record: dict) -> bool:
    """原 PID 对应身份已退出；权限/查询失败抛错，不能据此报告停止成功。"""
    if not identity_matches(record, record):
        raise RuntimeError("记录缺少完整进程身份")
    actual = process_identity(record["pid"])
    if actual is None:
        return True
    if not identity_matches(actual, actual) or actual["pid"] != record["pid"]:
        raise RuntimeError("无法核实当前进程身份")
    if actual["process_created_at"] != record["process_created_at"]:
        # PID 已重用：旧实例已退出，绝不向现在占用该 PID 的进程发控制消息。
        return True
    if actual["user_sid"] != record["user_sid"]:
        raise RuntimeError("进程用户身份不匹配，无法确认退出")
    return False


_windows_process_alive = process_alive  # 旧导入兼容


def port_ready(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


class Lifecycle:
    """launch/serve/status/stop 编排。"""

    def __init__(self, config: dict):
        self.config = config
        self.instance = Instance(config)
        self.mutex = InstanceMutex(str(Path(config["task_root"])))
        self.launch_mutex = InstanceMutex(str(Path(config["task_root"])), purpose="launch")
        self.pipe = PipeControl(str(Path(config["task_root"])))

    # ---- serve（供启动器调用）----
    def serve(self, app_factory, port: int | None = None) -> None:
        if not self.mutex.acquire():
            raise RuntimeError("已有工作台实例在运行")
        server = None
        try:
            from waitress import create_server
            from .web import create_app
            from .catalog import Catalog
            from .application import Application

            catalog = Catalog(self.config)
            opener = create_opener(self.config)
            application = Application(catalog, opener)
            application.set_preferences_path(self.instance.preferences_path)

            chosen_port = port or self.config.get("port") or find_free_port()
            if port_ready(chosen_port):
                raise RuntimeError(f"端口 {chosen_port} 已被占用，请修改配置或等待释放")
            started_at = now_iso()
            app = (app_factory or create_app)(application, {
                "app_id": APP_ID,
                "schema_version": SCHEMA_VERSION,
                "instance_id": self.instance.instance_id,
                "host": "127.0.0.1", "port": chosen_port,
            }, token_provider=lambda: self._new_token())
            # 先建 server：close() 可被其他线程调用，阻塞的 run() 随即返回
            server = create_server(app, host="127.0.0.1", port=chosen_port, threads=8)

            def shutdown():
                threading.Thread(target=self._graceful_stop, args=(server,), daemon=True).start()

            def restart():
                # 派生独立进程执行 stop+launch；本进程只负责把 HTTP 响应发完。
                config_path = self.config["config_path"]
                args = ([sys.executable] if getattr(sys, "frozen", False)
                        else [sys.executable, "-B", "-m", "workbench"])
                args += ["restart", "--config", str(config_path)]
                try:
                    spawn_background(args, independent=True, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except OSError:
                    raise RuntimeError("重启服务失败：无法启动重启进程") from None

            # HTTP /api/v1/shutdown 与管道 stop 消息走同一关闭路径
            app.extensions["shutdown_hook"] = shutdown
            app.extensions["restart_hook"] = restart
            self.pipe.start_server(app.extensions["bootstrap_issuer"], self.instance.instance_id,
                                   stop_callback=shutdown)
            self.instance.write(os.getpid(), chosen_port, started_at)

            server.run()
        finally:
            try:
                self.pipe.stop_server()
            finally:
                try:
                    if server is not None:
                        server.close()
                    self.instance.clear()
                finally:
                    self.mutex.release()

    def _token_provider(self) -> str:
        import secrets
        return secrets.token_urlsafe(24)

    def _new_token(self) -> str:
        return self._token_provider()

    def _graceful_stop(self, server) -> None:
        time.sleep(0.3)
        # Move descriptor closure onto waitress's event-loop thread. Closing from
        # the IPC thread can invalidate descriptors inside select() on Darwin.
        server.task_dispatcher.shutdown()
        def close_channels():
            for obj in list(getattr(server, "_map", {}).values()):
                obj.close()
            server.close()
        server.trigger.pull_trigger(close_channels)

    # ---- launch ----
    def launch(self, opener=None, wait_ready: float = READY_TIMEOUT) -> dict:
        if not self.launch_mutex.acquire(timeout_ms=max(1, int(wait_ready * 1000))):
            raise RuntimeError("另一启动请求尚未结束，请稍后重试")
        try:
            healthy = self.instance.is_healthy()
            if healthy:
                return self._open_window(healthy, opener)
            # 服务正在启动/收尾时只等它，不重复 spawn。serve 使用独立互斥量。
            may_spawn = self.mutex.acquire()
            if may_spawn:
                self.mutex.release()
                config_path = self.config["config_path"]
                args = ([sys.executable] if getattr(sys, "frozen", False)
                        else [sys.executable, "-B", "-m", "workbench"])
                args += ["serve", "--config", str(config_path)]
                try:
                    spawn_background(args, independent=True, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except OSError:
                    raise RuntimeError("启动服务失败") from None
            deadline = time.monotonic() + wait_ready
            while time.monotonic() < deadline:
                record = self.instance.is_healthy()
                if record:
                    return self._open_window(record, opener)
                time.sleep(POLL_INTERVAL)
            raise RuntimeError("服务启动超时，请查看运行日志")
        finally:
            self.launch_mutex.release()

    def _open_window(self, record: dict, opener=None) -> dict:
        """由 launch 在 launch_mutex 内调用；只复用成功打开过的同一服务实例。"""
        url = f"http://127.0.0.1:{record['port']}/"
        profile_dir = str(self.instance.state / "browser-profile" / record["instance_id"])
        result = {"instance_id": record["instance_id"], "port": record["port"], "url": url,
                  "window_dispatched": False, "window_reused": False}
        if opener is None:
            opener = create_opener(self.config)
        if getattr(opener, "supports_native_window", False) is True:
            return self._open_native_window(record, opener, result)
        try:
            activate = getattr(opener, "activate_browser", None)
            window = read_json(self.instance.window_path)
            same_instance = (window.get("schema_version") == SCHEMA_VERSION
                             and window.get("instance_id") == record["instance_id"]
                             and window.get("port") == record["port"]
                             and window.get("profile_dir") == profile_dir)
            if same_instance and activate and activate(url, profile_dir) is True:
                return {**result, "window_dispatched": True, "window_reused": True}
            response = self.pipe.request(PipeControl.REQUEST_TOKEN,
                                         expected_instance_id=record["instance_id"],
                                         expected_process=record)
            token = response.get("token")
            if (response.get("instance_id") != record["instance_id"] or
                    not isinstance(token, str) or not token):
                return {**result, "reason": "无法获取当前实例的启动令牌"}
            from urllib.parse import quote
            opener.open_browser(f"{url}#token={quote(token, safe='')}", profile_dir)
            write_json(self.instance.window_path, {
                "schema_version": SCHEMA_VERSION, "instance_id": record["instance_id"],
                "port": record["port"], "profile_dir": profile_dir,
            })
            return {**result, "window_dispatched": True}
        except Exception:
            # 不回传底层异常：第三方适配器异常可能包含完整 URL 或进程参数。
            return {**result, "reason": "无法验证或打开工作台窗口"}

    def _open_native_window(self, record: dict, opener, result: dict) -> dict:
        try:
            window = read_json(self.instance.window_path)
            same_instance = (window.get("schema_version") == SCHEMA_VERSION
                             and window.get("kind") == "native"
                             and window.get("instance_id") == record["instance_id"]
                             and window.get("port") == record["port"])
            if same_instance and opener.native_app_ready(window):
                if not opener.activate_native_app(window):
                    return {**result, "reason": "无法唤醒工作台窗口"}
                return {**result, "window_dispatched": True, "window_reused": True}
            opener.native_app_mode(str(self.config["config_path"]), record["instance_id"])
            deadline = time.monotonic() + READY_TIMEOUT
            while time.monotonic() < deadline:
                window = read_json(self.instance.window_path)
                if (window.get("schema_version") == SCHEMA_VERSION
                        and window.get("kind") == "native"
                        and window.get("instance_id") == record["instance_id"]
                        and window.get("port") == record["port"]
                        and opener.native_app_ready(window)):
                    return {**result, "window_dispatched": True}
                time.sleep(POLL_INTERVAL)
        except Exception:
            pass
        return {**result, "reason": "无法验证或打开工作台窗口"}

    # ---- status ----
    def status(self) -> dict:
        record = self.instance.is_healthy()
        if not record:
            snapshot = self.instance.read_state()
            return {
                "running": False,
                "instance_id": None,
                "port": None,
                "stale_record": snapshot["state"] != "missing",
                "record_state": snapshot["state"],
                "task_root": str(self.instance.task_root),
            }
        return {
            "running": True,
            "instance_id": record.get("instance_id"),
            "port": record.get("port"),
            "started_at": record.get("started_at"),
            "task_root": str(self.instance.task_root),
        }

    # ---- stop ----
    def stop(self, wait_stopped: float = 5.0) -> dict:
        record = self.instance.is_healthy()
        if not record:
            return self._stop_unhealthy()
        try:
            response = self.pipe.request(PipeControl.REQUEST_STOP, timeout_ms=5000,
                                         expected_instance_id=record["instance_id"],
                                         expected_process=record)
            if response.get("instance_id") != record["instance_id"] or response.get("stopping") is not True:
                raise RuntimeError("停止响应不匹配")
            deadline = time.monotonic() + wait_stopped
            while time.monotonic() < deadline:
                # 不用端口关闭代替退出；不能停止新占用该 PID/端口的其他进程。
                if process_exited(record) and not self.instance.instance_path.exists():
                    return {"stopping": True, "stopped": True, "instance_id": record["instance_id"]}
                time.sleep(POLL_INTERVAL)
        except Exception:
            raise RuntimeError("停止未完成：控制身份核验或进程退出检查失败") from None
        raise RuntimeError("停止超时：实例进程或状态记录尚未清理")

    def _stop_unhealthy(self) -> dict:
        """缺失须确认无启动/服务；完整且可确认退出的记录才允许清理。"""
        snapshot = self.instance.read_state()
        state, record = snapshot["state"], snapshot["record"]
        if state in ("corrupt", "unreadable"):
            raise RuntimeError("实例状态文件损坏或无法读取，未发送停止消息")
        if state == "present":
            try:
                exited = self.instance.valid_record(record) and process_exited(record)
            except (OSError, RuntimeError, ValueError, TypeError):
                exited = False
            if not exited:
                raise RuntimeError("实例身份或健康状态无法核实，未发送停止消息")

        # 与 launch 和直接 serve 都互斥。服务仍在运行、启动或收尾时不能清理/报无实例。
        if not self.launch_mutex.acquire():
            raise RuntimeError("工作台正在启动，无法确认退出，未发送停止消息")
        try:
            if not self.mutex.acquire():
                raise RuntimeError("工作台服务仍持有互斥量，无法确认退出，未发送停止消息")
            try:
                if self.instance.read_state() != snapshot:
                    raise RuntimeError("实例状态已变化，未清理记录，未发送停止消息")
                if state == "missing":
                    return {"stopping": False, "reason": "没有运行中的工作台实例"}
                # 获取锁期间记录或进程可能变化；在删除前重复核实原身份已经退出。
                if not self.instance.valid_record(record) or not process_exited(record):
                    raise RuntimeError("无法确认实例已退出，未清理记录，未发送停止消息")
                if self.instance.read_state() != snapshot:
                    raise RuntimeError("实例状态已变化，未清理记录，未发送停止消息")
                self.instance.instance_path.unlink()
                return {"stopping": True, "stopped": True, "instance_id": record["instance_id"],
                        "stale_record_cleared": True}
            finally:
                self.mutex.release()
        finally:
            self.launch_mutex.release()

    # ---- 快捷方式 ----
    def install_shortcuts(self, launcher_exe: str, opener=None) -> dict:
        from .platform_runtime import install_shortcuts as _install
        return _install(self.instance, launcher_exe, opener=opener)

    def uninstall_shortcuts(self) -> dict:
        from .platform_runtime import uninstall_shortcuts as _uninstall
        return _uninstall(self.instance)
