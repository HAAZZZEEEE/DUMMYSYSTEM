"""隔离生命周期回归：临时状态、mock spawn、仅测试自己创建的 HTTP 服务。"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

from workbench.lifecycle import (APP_ID, Instance, Lifecycle, find_free_port, health_probe,
                                 health_matches, port_ready, process_exited, state_dir, write_json)
from workbench.windows_identity import process_identity


class InstanceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = {"task_root": self.tmp.name, "workspace_root": self.tmp.name,
                       "config_path": str(Path(self.tmp.name) / "config.json"), "apps": {}}
        self.instance = Instance(self.config)

    def record(self):
        self.instance.write(os.getpid(), 45678, "display-time")
        return self.instance.read()

    def health(self, record):
        return {"schema_version": 1, "data": {"app_id": APP_ID, "schema_version": 1,
                "instance_id": record["instance_id"], "ready": True}}

    def test_write_read_clear_and_foreign_record_preserved(self):
        record = self.record()
        self.assertEqual(state_dir(self.config), Path(self.tmp.name) / "state")
        self.assertEqual(record["process_created_at"], process_identity(os.getpid())["process_created_at"])
        self.assertEqual(record["host"], "127.0.0.1")
        self.assertEqual(record["started_at"], "display-time")
        other = Instance(self.config)
        other.clear()
        self.assertEqual(other.read(), record)
        self.instance.clear()
        self.assertEqual(self.instance.read(), {})

    def test_identity_and_http_health_required(self):
        record = self.record()
        with patch("workbench.lifecycle.health_probe", return_value=self.health(record)) as probe:
            self.assertEqual(self.instance.is_healthy(), record)
            for field, value in [("process_created_at", "1"), ("pid", 0), ("user_sid", "wrong"),
                                 ("schema_version", True), ("port", True), ("host", "localhost")]:
                with self.subTest(field=field):
                    write_json(self.instance.instance_path, {**record, field: value})
                    self.assertIsNone(self.instance.is_healthy())
            write_json(self.instance.instance_path, record)
            for field, value in [("app_id", "foreign"), ("instance_id", "foreign"),
                                 ("schema_version", True), ("ready", False)]:
                response = self.health(record)
                response["data"][field] = value
                probe.return_value = response
                self.assertIsNone(self.instance.is_healthy())

    def test_pid_changes_during_health_is_rejected(self):
        record = self.record()
        with patch("workbench.lifecycle.health_probe", return_value=self.health(record)), patch(
                "workbench.lifecycle.process_identity", side_effect=[record, None]):
            self.assertIsNone(self.instance.is_healthy())

    def test_health_get_actual_local_server(self):
        record = self.record()
        payload = self.health(record)
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append((self.command, self.path))
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            self.assertTrue(health_matches(health_probe(server.server_port), record))
            self.assertEqual(requests, [("GET", "/healthz")])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_socket_only_is_not_health(self):
        import socket
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen()
            self.assertTrue(port_ready(sock.getsockname()[1]))
            self.assertEqual(health_probe(sock.getsockname()[1], timeout=0.03), {})
        self.assertTrue(0 < find_free_port() < 65536)

    def test_unreadable_process_is_not_reported_exited(self):
        record = self.record()
        with patch("workbench.lifecycle.process_identity", side_effect=RuntimeError("denied")):
            with self.assertRaises(RuntimeError):
                process_exited(record)

    def test_stop_requires_identity_response_exit_and_cleanup(self):
        record = self.record()
        life = Lifecycle(self.config)
        life.instance.is_healthy = Mock(return_value=record)
        life.pipe.request = Mock(return_value={"instance_id": record["instance_id"], "stopping": True})
        with patch("workbench.lifecycle.process_exited", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "超时"):
                life.stop(wait_stopped=0.001)
        life.pipe.request.assert_called_with(life.pipe.REQUEST_STOP, timeout_ms=5000,
                                            expected_instance_id=record["instance_id"], expected_process=record)
        with patch("workbench.lifecycle.process_exited", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "超时"):
                life.stop(wait_stopped=0.001)  # 状态仍存在
            self.instance.clear()
            self.assertTrue(life.stop()["stopped"])
        life.pipe.request.return_value = {"instance_id": "wrong", "stopping": True}
        with self.assertRaises(RuntimeError):
            life.stop()

    def test_stop_stale_never_sends(self):
        self.record()
        life = Lifecycle(self.config)
        life.instance.is_healthy = Mock(return_value=None)
        life.pipe.request = Mock()
        with self.assertRaisesRegex(RuntimeError, "未发送"):
            life.stop()
        life.pipe.request.assert_not_called()

    def test_launch_window_reuse_and_token_redaction(self):
        record = self.record()
        life = Lifecycle(self.config)
        life.pipe.request = Mock(return_value={"instance_id": record["instance_id"], "token": "TOPSECRET"})
        opener = Mock()
        opener.activate_edge_app.return_value = True
        # 未成功 dispatch 的实例即使窗口看起来可激活，也必须先 bootstrap。
        initial = life._open_window(record, opener)
        self.assertTrue(initial["window_dispatched"])
        self.assertFalse(initial["window_reused"])
        self.assertEqual(opener.edge_app_mode.call_args.args[1],
                         str(life.instance.state / "edge-profile" / record["instance_id"]))
        opener.activate_edge_app.assert_not_called()
        self.assertEqual(life.instance.window_path.is_file(), True)
        life.pipe.request.reset_mock()
        opener.edge_app_mode.reset_mock()
        self.assertTrue(life._open_window(record, opener)["window_reused"])
        self.assertEqual(opener.activate_edge_app.call_args.args[1],
                         str(life.instance.state / "edge-profile" / record["instance_id"]))
        life.pipe.request.assert_not_called()
        opener.edge_app_mode.assert_not_called()
        opener.activate_edge_app.return_value = False
        result = life._open_window(record, opener)
        self.assertFalse(result["window_reused"])
        self.assertTrue(result["window_dispatched"])
        self.assertNotIn("TOPSECRET", json.dumps(result))
        self.assertNotIn("#", result["url"])
        self.assertIn("#token=TOPSECRET", opener.edge_app_mode.call_args.args[0])
        opener.edge_app_mode.side_effect = RuntimeError("TOPSECRET")
        self.assertNotIn("TOPSECRET", json.dumps(life._open_window(record, opener)))

    def test_native_window_waits_for_verified_host_and_reuses_it(self):
        record = self.record()
        life = Lifecycle(self.config)
        opener = Mock(supports_native_window=True)
        opener.native_app_ready.return_value = True
        window = {"schema_version": 1, "kind": "native", "instance_id": record["instance_id"],
                  "port": record["port"], **process_identity(os.getpid())}
        opener.native_app_mode.side_effect = lambda *_: write_json(life.instance.window_path, window)
        first = life._open_window(record, opener)
        self.assertTrue(first["window_dispatched"])
        self.assertFalse(first["window_reused"])
        opener.native_app_mode.assert_called_once_with(self.config["config_path"], record["instance_id"])
        life.pipe.request = Mock()
        second = life._open_window(record, opener)
        self.assertTrue(second["window_reused"])
        opener.activate_native_app.assert_called_once_with(window)
        life.pipe.request.assert_not_called()  # The host obtains its own one-time token.

    def test_same_port_new_instance_needs_bootstrap_not_old_window(self):
        record = self.record()
        life = Lifecycle(self.config)
        life.pipe.request = Mock(return_value={"instance_id": record["instance_id"], "token": "FIRST"})
        opener = Mock()
        opener.activate_edge_app.return_value = True
        self.assertTrue(life._open_window(record, opener)["window_dispatched"])
        old_profile = Path(opener.edge_app_mode.call_args.args[1])
        old_profile.mkdir(parents=True)
        old_asset = old_profile / "retained.txt"
        old_asset.write_text("保留旧 profile", encoding="utf-8")
        other = {**record, "instance_id": "restarted-instance"}
        life.pipe.request.return_value = {"instance_id": other["instance_id"], "token": "SECOND"}
        opener.reset_mock()
        result = life._open_window(other, opener)
        self.assertFalse(result["window_reused"])
        self.assertTrue(result["window_dispatched"])
        opener.activate_edge_app.assert_not_called()
        life.pipe.request.assert_called_with(life.pipe.REQUEST_TOKEN, expected_instance_id=other["instance_id"],
                                            expected_process=other)
        self.assertIn("#token=SECOND", opener.edge_app_mode.call_args.args[0])
        self.assertEqual(opener.edge_app_mode.call_args.args[1],
                         str(life.instance.state / "edge-profile" / other["instance_id"]))
        self.assertNotEqual(Path(opener.edge_app_mode.call_args.args[1]), old_profile)
        self.assertEqual(old_asset.read_text(encoding="utf-8"), "保留旧 profile")
        window = json.loads(life.instance.window_path.read_text(encoding="utf-8"))
        self.assertEqual(window["instance_id"], other["instance_id"])
        self.assertNotIn("SECOND", json.dumps(window))
        life.pipe.request.reset_mock()
        self.assertTrue(life._open_window(other, opener)["window_reused"])
        life.pipe.request.assert_not_called()

    def test_failed_dispatch_does_not_authorize_instance_reuse(self):
        record = self.record()
        life = Lifecycle(self.config)
        life.pipe.request = Mock(return_value={"instance_id": record["instance_id"], "token": "SECRET"})
        opener = Mock()
        opener.activate_edge_app.return_value = True
        opener.edge_app_mode.side_effect = RuntimeError("failed")
        result = life._open_window(record, opener)
        self.assertFalse(result["window_dispatched"])
        self.assertFalse(life.instance.window_path.exists())
        opener.activate_edge_app.assert_not_called()

    def test_corrupt_window_record_requires_bootstrap(self):
        record = self.record()
        life = Lifecycle(self.config)
        life.instance.window_path.write_bytes(b'\xff')
        life.pipe.request = Mock(return_value={"instance_id": record["instance_id"], "token": "SECRET"})
        opener = Mock()
        opener.activate_edge_app.return_value = True
        result = life._open_window(record, opener)
        self.assertTrue(result["window_dispatched"])
        self.assertFalse(result["window_reused"])
        opener.activate_edge_app.assert_not_called()

    def test_concurrent_launch_spawns_once(self):
        record = self.record()
        ready = threading.Event()
        def spawn(*args, **kwargs):
            ready.set()
            return Mock()
        lives = [Lifecycle(self.config), Lifecycle(self.config)]
        for life in lives:
            life.instance.is_healthy = Mock(side_effect=lambda: record if ready.is_set() else None)
            life._open_window = Mock(return_value={"window_reused": True})
        errors = []
        def run(life):
            try:
                life.launch(wait_ready=2)
            except Exception as error:
                errors.append(error)
        with patch("workbench.lifecycle.subprocess.Popen", side_effect=spawn) as popen:
            threads = [threading.Thread(target=run, args=(life,)) for life in lives]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(4)
            self.assertTrue(all(not t.is_alive() for t in threads))
            self.assertEqual(errors, [])
            popen.assert_called_once()

    def test_launch_waits_existing_serve_without_spawning(self):
        from workbench.instance_control import InstanceMutex
        mutex = InstanceMutex(self.tmp.name)
        self.assertTrue(mutex.acquire())
        try:
            life = Lifecycle(self.config)
            life.instance.is_healthy = Mock(return_value=None)
            with patch("workbench.lifecycle.subprocess.Popen") as popen:
                with self.assertRaisesRegex(RuntimeError, "超时"):
                    life.launch(wait_ready=0.001)
                popen.assert_not_called()
        finally:
            mutex.release()

    def test_serve_factory_receives_origin_and_cleans_state(self):
        life = Lifecycle(self.config)
        app = Mock(extensions={"bootstrap_issuer": lambda: "test-token"})
        factory = Mock(return_value=app)
        server = Mock()
        with patch("waitress.create_server", return_value=server), patch(
                "workbench.lifecycle.port_ready", return_value=False):
            life.serve(factory, port=43210)
        identity = factory.call_args.args[1]
        self.assertEqual(identity["host"], "127.0.0.1")
        self.assertEqual(identity["port"], 43210)
        self.assertFalse(life.instance.instance_path.exists())
        self.assertIsNone(life.pipe._thread)
        self.assertIsNone(life.mutex._handle)


if __name__ == "__main__":
    unittest.main()
