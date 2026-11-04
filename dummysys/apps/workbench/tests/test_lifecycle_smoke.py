"""无 GUI 的真实 serve/Pipe 冒烟，仅启动并清理本测试临时配置的子进程。"""
import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from workbench.config import load_config
from workbench.instance_control import PipeControl
from workbench.lifecycle import Lifecycle, write_json
from workbench.windows_identity import identity_matches, process_identity


@unittest.skipUnless(os.name == "nt", "需要 Windows")
class IsolatedServeSmokeTest(unittest.TestCase):
    def test_real_serve_pipe_token_stop_process_exit_state_cleanup(self):
        with tempfile.TemporaryDirectory(prefix="workbench-isolated-smoke-") as directory:
            root = Path(directory)
            config_path = root / "config.json"
            config_path.write_text(json.dumps({"schema_version": 1, "workspace_root": str(root),
                                              "task_root": str(root / "task"), "port": 0,
                                              "apps": {}}), encoding="utf-8")
            life = Lifecycle(load_config(config_path))
            child = subprocess.Popen(
                [sys.executable, "-B", "-m", "workbench", "serve", "--config", str(config_path)],
                cwd=Path(__file__).resolve().parents[1], creationflags=subprocess.CREATE_NO_WINDOW,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            token = None
            owned_service = None
            try:
                deadline = time.monotonic() + 12
                record = None
                while time.monotonic() < deadline and child.poll() is None:
                    record = life.instance.is_healthy()
                    if record:
                        break
                    time.sleep(0.05)
                self.assertIsNotNone(record, "隔离 serve 未能就绪")
                # Windows venv redirector 的 Popen PID 可能是服务的父进程。
                import win32api
                import win32com.client
                import win32event
                if record["pid"] != child.pid:
                    rows = list(win32com.client.GetObject("winmgmts:").ExecQuery(
                        f"SELECT ParentProcessId,CommandLine FROM Win32_Process WHERE ProcessId={record['pid']}"))
                    self.assertEqual(len(rows), 1)
                    self.assertEqual(int(rows[0].ParentProcessId), child.pid,
                                     "只允许操作本测试创建的服务子树")
                    self.assertTrue(str(config_path) in str(rows[0].CommandLine), "临时配置必须匹配")
                self.assertTrue(identity_matches(process_identity(record["pid"]), record))
                owned_service = win32api.OpenProcess(0x100001, False, record["pid"])
                self.assertTrue(identity_matches(process_identity(record["pid"]), record))
                # 真实 CLI 必须区分损坏/缺失的状态文件与已退出；不能因 JSON 损坏报成功。
                def cli_stop():
                    return subprocess.run(
                        [sys.executable, "-B", "-m", "workbench", "stop", "--config", str(config_path)],
                        cwd=Path(__file__).resolve().parents[1], creationflags=subprocess.CREATE_NO_WINDOW,
                        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8)
                try:
                    life.instance.instance_path.write_bytes(b'{')
                    self.assertNotEqual(cli_stop().returncode, 0, "损坏状态必须导致 stop 非零退出")
                    self.assertEqual(life.instance.instance_path.read_bytes(), b'{')
                    self.assertTrue(identity_matches(process_identity(record["pid"]), record))
                    life.instance.instance_path.unlink()
                    self.assertNotEqual(cli_stop().returncode, 0, "缺失状态但服务仍持锁时必须非零退出")
                    self.assertTrue(identity_matches(process_identity(record["pid"]), record))
                finally:
                    write_json(life.instance.instance_path, record)
                # 错实例 stop 在服务端拒绝，真实服务继续运行。
                with self.assertRaises(ConnectionError):
                    life.pipe.request(PipeControl.REQUEST_STOP, expected_instance_id="wrong-instance",
                                      expected_process=record, timeout_ms=2000)
                self.assertIsNone(child.poll())
                response = life.pipe.request(PipeControl.REQUEST_TOKEN,
                                             expected_instance_id=record["instance_id"],
                                             expected_process=record, timeout_ms=2000)
                token = response.get("token")
                self.assertTrue(isinstance(token, str) and len(token) > 10, "令牌签发失败")
                self.assertTrue(token not in life.instance.instance_path.read_text(encoding="utf-8"),
                                "令牌不得持久化到状态")
                connection = http.client.HTTPConnection("127.0.0.1", record["port"], timeout=2)
                try:
                    connection.request("POST", "/api/v1/session", body=json.dumps({"bootstrap_token": token}),
                                       headers={"Content-Type": "application/json",
                                                "Origin": f"http://127.0.0.1:{record['port']}"})
                    session = connection.getresponse()
                    self.assertEqual(session.status, 200, "管道令牌应由实际 HTTP 实例接受")
                    self.assertTrue(json.loads(session.read())["data"]["authenticated"])
                finally:
                    connection.close()
                stopped = life.stop(wait_stopped=8)
                self.assertTrue(stopped.get("stopped"))
                self.assertEqual(child.wait(timeout=3), 0)
                self.assertIsNone(process_identity(record["pid"]))
                self.assertFalse(life.instance.instance_path.exists())
                write_json(life.instance.instance_path, record)
                stale = cli_stop()
                self.assertEqual(stale.returncode, 0, "已退出实例的完整记录应可清理")
                cleanup = json.loads(stale.stdout)["stale_record_cleared"]
                self.assertTrue(cleanup)
                self.assertFalse(life.instance.instance_path.exists())
            finally:
                if owned_service is not None:
                    try:
                        if win32event.WaitForSingleObject(owned_service, 0) != 0:
                            win32api.TerminateProcess(owned_service, 1)
                            win32event.WaitForSingleObject(owned_service, 5000)
                    finally:
                        owned_service.Close()
                if child.poll() is None:
                    child.terminate()  # 仅本测试持有的 Popen 子进程，不查找或杀死其他进程
                    child.wait(timeout=5)
                stdout, stderr = child.communicate(timeout=2)
                if token:
                    self.assertTrue(token.encode() not in stdout + stderr, "服务日志不得含令牌")


if __name__ == "__main__":
    unittest.main()
