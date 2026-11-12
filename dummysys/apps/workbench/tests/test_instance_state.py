"""状态缺失、损坏与可确认退出的隔离回归。"""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from workbench.lifecycle import Lifecycle, write_json
from workbench.platform_runtime import InstanceMutex


class InstanceStateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.life = Lifecycle({"task_root": self.tmp.name, "workspace_root": self.tmp.name})
        self.life.pipe.request = Mock()
        self.path = self.life.instance.instance_path
        self.path.parent.mkdir(parents=True)

    def record(self):
        self.life.instance.write(os.getpid(), 45678, "test")
        return self.life.instance.read()

    def test_corrupt_record_never_means_no_instance(self):
        for body in (b'{', b'', b'[]', b'null', b'{}', b'\xff'):
            with self.subTest(body=body):
                self.path.write_bytes(body)
                with self.assertRaises(RuntimeError):
                    self.life.stop()
                self.assertEqual(self.path.read_bytes(), body)
        self.life.pipe.request.assert_not_called()

    def test_confirmed_exited_record_is_cleaned_without_stop_message(self):
        record = self.record()
        with patch("workbench.lifecycle.process_identity", return_value=None):
            result = self.life.stop()
        self.assertTrue(result["stopping"])
        self.assertTrue(result["stopped"])
        self.assertTrue(result["stale_record_cleared"])
        self.assertEqual(result["instance_id"], record["instance_id"])
        self.assertFalse(self.path.exists())
        self.life.pipe.request.assert_not_called()

    def test_missing_and_no_service_preserves_compatibility(self):
        self.assertEqual(self.life.stop(), {"stopping": False, "reason": "没有运行中的工作台实例"})
        self.life.pipe.request.assert_not_called()

    def test_missing_but_service_or_launch_mutex_present_is_unknown(self):
        for purpose in ("serve", "launch"):
            mutex = InstanceMutex(self.tmp.name, purpose=purpose)
            self.assertTrue(mutex.acquire())
            try:
                with self.subTest(purpose=purpose), self.assertRaises(RuntimeError):
                    self.life.stop()
            finally:
                mutex.release()
        self.life.pipe.request.assert_not_called()

    def test_unreadable_is_not_missing(self):
        with patch.object(Path, "read_text", side_effect=PermissionError("denied")):
            self.assertEqual(self.life.instance.read_state()["state"], "unreadable")
            with self.assertRaises(RuntimeError):
                self.life.stop()
        self.life.pipe.request.assert_not_called()

    def test_incomplete_or_foreign_identity_is_never_cleaned(self):
        record = self.record()
        variants = [{key: value for key, value in record.items() if key != missing}
                    for missing in ("pid", "process_created_at", "user_sid", "instance_id")]
        variants += [{**record, "user_sid": "other"}, {**record, "task_root": "C:/foreign"},
                     {**record, "app_id": "other"}, {**record, "schema_version": 999}]
        with patch("workbench.lifecycle.process_identity", return_value=None):
            for variant in variants:
                write_json(self.path, variant)
                with self.subTest(fields=list(variant)), self.assertRaises(RuntimeError):
                    self.life.stop()
                self.assertEqual(self.life.instance.read(), variant)
        self.life.pipe.request.assert_not_called()

    def test_process_lookup_failure_preserves_record(self):
        record = self.record()
        with patch("workbench.lifecycle.process_identity", side_effect=RuntimeError("denied")):
            with self.assertRaises(RuntimeError):
                self.life.stop()
        self.assertEqual(self.life.instance.read(), record)
        self.life.pipe.request.assert_not_called()

    def test_pid_reuse_cleans_old_record_without_controlling_new_process(self):
        record = self.record()
        actual = {**record, "process_created_at": str(int(record["process_created_at"]) + 1)}
        with patch("workbench.lifecycle.process_identity", return_value=actual):
            self.assertTrue(self.life.stop()["stale_record_cleared"])
        self.assertFalse(self.path.exists())
        self.life.pipe.request.assert_not_called()

    def test_same_creation_but_wrong_sid_is_unknown_not_exited(self):
        record = self.record()
        with patch("workbench.lifecycle.process_identity", return_value={**record, "user_sid": "other"}):
            with self.assertRaises(RuntimeError):
                self.life.stop()
        self.assertEqual(self.life.instance.read(), record)
        self.life.pipe.request.assert_not_called()

    def test_exited_record_but_mutex_held_is_not_cleaned(self):
        record = self.record()
        mutex = InstanceMutex(self.tmp.name)
        self.assertTrue(mutex.acquire())
        try:
            with patch("workbench.lifecycle.process_identity", return_value=None), self.assertRaises(RuntimeError):
                self.life.stop()
        finally:
            mutex.release()
        self.assertEqual(self.life.instance.read(), record)

    def test_replaced_record_before_cleanup_is_preserved(self):
        record = self.record()
        replacement = {**record, "instance_id": "replacement"}
        def changed():
            write_json(self.path, replacement)
            return True
        with patch("workbench.lifecycle.process_identity", return_value=None), patch.object(
                self.life.launch_mutex, "acquire", side_effect=changed):
            with self.assertRaises(RuntimeError):
                self.life.stop()
        self.assertEqual(self.life.instance.read(), replacement)
        self.life.pipe.request.assert_not_called()

    def test_cleanup_failure_is_not_success_and_releases_mutexes(self):
        self.record()
        with patch("workbench.lifecycle.process_identity", return_value=None), patch.object(
                Path, "unlink", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                self.life.stop()
        self.assertTrue(self.path.exists())
        self.assertTrue(self.life.mutex.acquire())
        self.life.mutex.release()
        self.assertTrue(self.life.launch_mutex.acquire())
        self.life.launch_mutex.release()

    def test_corrupt_status_preserves_evidence(self):
        self.path.write_bytes(b'{')
        status = self.life.status()
        self.assertEqual(status["record_state"], "corrupt")
        self.assertTrue(status["stale_record"])


if __name__ == "__main__":
    unittest.main()
