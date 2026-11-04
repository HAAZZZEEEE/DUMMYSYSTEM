"""真实 Windows API 回归仅使用随机临时名称和自己创建的进程/线程。"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from workbench.instance_control import (InstanceMutex, PipeControl, current_user_sid,
                                        mutex_name, user_security_attributes)
from workbench.windows_identity import process_identity


@unittest.skipUnless(os.name == "nt", "需要 Windows")
class WindowsIdentityTest(unittest.TestCase):
    def test_creation_time_stable_exact_and_own_child_exit(self):
        first = process_identity(os.getpid())
        self.assertEqual(first, process_identity(os.getpid()))
        self.assertRegex(first["process_created_at"], r"^[0-9]{18,}$")
        self.assertEqual(first["user_sid"], current_user_sid())
        child = subprocess.Popen([sys.executable, "-B", "-c", "import time; time.sleep(30)"],
                                 creationflags=subprocess.CREATE_NO_WINDOW,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            identity = process_identity(child.pid)
            self.assertEqual(identity["pid"], child.pid)
            self.assertEqual(identity["user_sid"], first["user_sid"])
        finally:
            child.terminate()  # 仅结束本测试创建且持有句柄的子进程
            child.wait(timeout=5)
        self.assertIsNone(process_identity(child.pid))

    def test_sid_failure_is_fail_closed(self):
        with patch("workbench.windows_identity.process_identity", return_value=None):
            with self.assertRaises(RuntimeError):
                current_user_sid()

    def test_explicit_single_user_protected_dacl(self):
        import win32security
        attributes = user_security_attributes()
        descriptor = attributes.SECURITY_DESCRIPTOR
        acl = descriptor.GetSecurityDescriptorDacl()
        self.assertEqual(acl.GetAceCount(), 1)
        self.assertEqual(win32security.ConvertSidToStringSid(acl.GetAce(0)[2]), current_user_sid())
        self.assertTrue(descriptor.GetSecurityDescriptorControl()[0] & win32security.SE_DACL_PROTECTED)


@unittest.skipUnless(os.name == "nt", "需要 Windows")
class MutexTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_existence_closes_handles_and_launch_is_separate(self):
        first = InstanceMutex(self.tmp.name)
        second = InstanceMutex(self.tmp.name)
        launch = InstanceMutex(self.tmp.name, purpose="launch")
        self.assertTrue(first.acquire())
        try:
            for _ in range(8):
                self.assertFalse(second.acquire())
                self.assertIsNone(second._handle)
            self.assertTrue(launch.acquire())
        finally:
            first.release()
            launch.release()
        self.assertTrue(second.acquire())
        second.release()

    def test_creation_error_never_returns_success(self):
        mutex = InstanceMutex(self.tmp.name)
        with patch("win32event.CreateMutex", side_effect=OSError("failure")):
            with self.assertRaises(RuntimeError):
                mutex.acquire()
        self.assertIsNone(mutex._handle)

    def test_existing_handle_closed(self):
        mutex = InstanceMutex(self.tmp.name)
        with patch("win32event.CreateMutex", return_value=123), patch(
                "win32api.GetLastError", return_value=183), patch(
                "workbench.instance_control._close_handle") as close:
            self.assertFalse(mutex.acquire())
            close.assert_called_once_with(123)


@unittest.skipUnless(os.name == "nt", "需要 Windows")
class PipeControlTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pipe = PipeControl(self.tmp.name)
        self.identity = process_identity(os.getpid())
        self.token = Mock(return_value="private-test-token")
        self.stopped = threading.Event()

    def start(self):
        self.pipe.start_server(self.token, "test-instance", self.stopped.set)
        self.addCleanup(self.pipe.stop_server)

    def request(self, action, **kwargs):
        return self.pipe.request(action, timeout_ms=1000,
                                 expected_instance_id=kwargs.get("instance_id", "test-instance"),
                                 expected_process=kwargs.get("identity", self.identity))

    def test_token_stop_and_thread_cleanup(self):
        self.start()
        self.assertEqual(self.request(self.pipe.REQUEST_TOKEN)["token"], "private-test-token")
        self.assertTrue(self.request(self.pipe.REQUEST_STOP)["stopping"])
        self.assertTrue(self.stopped.wait(1))
        self.pipe.stop_server()
        self.assertIsNone(self.pipe._server_handle)
        self.assertIsNone(self.pipe._thread)

    def test_missing_instance_malformed_and_wrong_instance_have_no_side_effect(self):
        self.start()
        for message in ['[]', 'null', '{', '{"action":"request-stop"}',
                        '{"action":"request-token","expected_instance_id":"other"}']:
            self.assertIn("error", json.loads(self.pipe._dispatch(message)))
        with self.assertRaises(ConnectionError):
            self.request(self.pipe.REQUEST_STOP, instance_id="other")
        self.assertFalse(self.stopped.is_set())
        self.token.assert_not_called()

    def test_server_identity_mismatch_prevents_write(self):
        self.start()
        for field, wrong in [("pid", 1), ("process_created_at", "1"), ("user_sid", "S-1-0-0")]:
            with self.subTest(field=field), patch.object(self.pipe, "_write") as write:
                # _write also belongs to server: no payload arrives, therefore neither end writes.
                with self.assertRaises(ConnectionError):
                    self.request(self.pipe.REQUEST_STOP, identity={**self.identity, field: wrong})
                write.assert_not_called()
        self.assertFalse(self.stopped.is_set())

    def test_response_instance_mismatch_rejected(self):
        self.start()
        with patch.object(self.pipe, "_dispatch", return_value='{"instance_id":"other","token":"secret"}'):
            with self.assertRaisesRegex(ConnectionError, "响应实例"):
                self.request(self.pipe.REQUEST_TOKEN)

    def test_client_sid_and_pid_validation(self):
        with patch("win32pipe.GetNamedPipeClientProcessId", return_value=77), patch(
                "workbench.instance_control.process_identity", return_value=None):
            with self.assertRaises(ConnectionError):
                self.pipe._verify_peer(1)
        with patch("win32pipe.GetNamedPipeClientProcessId", return_value=77), patch(
                "workbench.instance_control.process_identity", return_value={"user_sid": "other"}):
            with self.assertRaises(ConnectionError):
                self.pipe._verify_peer(1)

    def test_pipe_creation_flags_and_security(self):
        with patch("win32pipe.CreateNamedPipe", return_value=1) as create, patch(
                "threading.Thread"):
            self.pipe.start_server(self.token, "test-instance")
        args = create.call_args.args
        self.assertTrue(args[1] & 0x80000)
        self.assertTrue(args[2] & 0x8)
        self.assertIsNotNone(args[-1].SECURITY_DESCRIPTOR)

    def test_idle_connected_client_cannot_block_cleanup(self):
        from workbench.instance_control import _close_handle
        self.start()
        handle = self.pipe._connect(1000)
        try:
            self.pipe.stop_server()
            self.assertIsNone(self.pipe._server_handle)
            self.assertIsNone(self.pipe._thread)
        finally:
            _close_handle(handle)


if __name__ == "__main__":
    unittest.main()
