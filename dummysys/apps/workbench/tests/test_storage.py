"""缓存先读、并发合并、节流和失败保留。"""
import tempfile
import os
import threading
import unittest
from collections import namedtuple
from pathlib import Path

from workbench.storage import StorageMonitor
from tests.test_web import WebTestBase

Usage = namedtuple('Usage', 'total used free')


class StorageTests(unittest.TestCase):
    def test_workspace_and_nested_projects_are_counted_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / 'project'
            child = project / 'nested'
            child.mkdir(parents=True)
            (root / 'common').write_bytes(b'x' * 11)
            (project / 'first').write_bytes(b'x' * 5)
            (child / 'second').write_bytes(b'x' * 7)
            parent_row = dict(bytes=0, files=0, partial=False)
            child_row = dict(bytes=0, files=0, partial=False)
            assignments = {os.path.normcase(str(StorageMonitor._native_path(project))): parent_row,
                           os.path.normcase(str(StorageMonitor._native_path(child))): child_row}
            self.assertEqual(StorageMonitor._directory_size(root, assignments), (23, 3, 0))
            self.assertEqual(parent_row['bytes'], 5)
            self.assertEqual(child_row['bytes'], 7)

    @unittest.skipUnless(os.name == 'nt', 'Windows长路径契约')
    def test_windows_long_paths_are_counted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            extended = Path('\\\\?\\' + str(root))
            nested = extended.joinpath(*(['long-directory-name'] * 16))
            nested.mkdir(parents=True)
            try:
                (nested / 'data.bin').write_bytes(b'abc')
                self.assertEqual(StorageMonitor._directory_size(root), (3, 1, 0))
            finally:
                (nested / 'data.bin').unlink(missing_ok=True)
                for _ in range(16):
                    nested.rmdir()
                    nested = nested.parent

    def test_project_top_five_cache_and_independent_capacity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gate = threading.Event()
            entered = threading.Event()
            records = []
            for number in range(7):
                path = root / f'project-{number}'
                path.mkdir()
                (path / 'file').write_bytes(b'x' * (number + 1))
                records.append(dict(project_id=str(number), title=f'项目{number}', resource_root=str(path)))
            calls = []

            def projects():
                calls.append(1)
                entered.set()
                gate.wait(3)
                return dict(projects=records)

            monitor = StorageMonitor(root, probe=lambda _: Usage(100, 60, 40), projects=projects)
            monitor.snapshot(refresh=True)
            self.assertTrue(entered.wait(2))
            try:
                self.wait_finished(monitor)
                self.assertEqual(monitor.snapshot()['sample']['free'], 40)
                self.assertTrue(monitor.snapshot()['projects_refreshing'])
            finally:
                gate.set()
            import time
            deadline = time.monotonic() + 3
            while monitor.snapshot()['projects_refreshing'] and time.monotonic() < deadline:
                threading.Event().wait(.005)
            ranking = monitor.snapshot()['ranking']
            self.assertEqual([row['bytes'] for row in ranking['top']], [7, 6, 5, 4, 3])
            self.assertFalse(ranking['incomplete'])
            self.assertEqual(ranking['projects_bytes'], 28)
            self.assertGreaterEqual(ranking['workspace_bytes'], 28)
            restored = StorageMonitor(root, projects=projects)
            self.assertEqual(restored.snapshot()['ranking'], ranking)
            restored.snapshot(refresh=True)
            self.wait_finished(restored)
            self.assertEqual(len(calls), 1)

    def test_scan_counts_and_marks_unreadable_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for i in range(1100):
                (root / str(i)).write_bytes(b'ab')
            self.assertEqual(StorageMonitor._directory_size(root), (2200, 1100, 0))
            self.assertEqual(StorageMonitor._directory_size(root / 'missing'), (0, 0, 1))

    def test_cache_single_flight_throttle_failure_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            entered, release = threading.Event(), threading.Event()
            now = [0]
            calls = []

            def probe(path):
                calls.append(path)
                entered.set()
                release.wait(5)
                if len(calls) > 1:
                    raise OSError('unavailable')
                return Usage(100, 60, 40)

            monitor = StorageMonitor(Path(directory), probe=probe, clock=lambda: now[0])
            self.assertIsNone(monitor.snapshot()['sample'])
            self.assertEqual(calls, [])
            self.assertTrue(monitor.snapshot(refresh=True)['refreshing'])
            self.assertTrue(entered.wait(2))
            for _ in range(10):
                self.assertTrue(monitor.snapshot(refresh=True)['refreshing'])
            self.assertEqual(len(calls), 1)
            release.set()
            self.wait_finished(monitor)
            sample = monitor.snapshot()['sample']
            self.assertEqual(sample['free'], 40)
            monitor.snapshot(refresh=True)
            self.assertEqual(len(calls), 1)
            restored = StorageMonitor(Path(directory), probe=probe)
            self.assertEqual(restored.snapshot()['sample'], sample)
            self.assertEqual(len(calls), 1)
            now[0] = 31
            monitor.snapshot(refresh=True)
            self.wait_finished(monitor)
            self.assertEqual(monitor.snapshot()['sample'], sample)
            self.assertIn('采集失败', monitor.snapshot()['error'])
            monitor.snapshot(refresh=True)
            self.assertEqual(len(calls), 2)

    def wait_finished(self, monitor):
        import time
        deadline = time.monotonic() + 3
        while monitor.snapshot()['refreshing'] and time.monotonic() < deadline:
            threading.Event().wait(.005)
        self.assertFalse(monitor.snapshot()['refreshing'])

    def test_corrupt_cache_recovers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / 'runtime/state/workbench/storage.json'
            cache.parent.mkdir(parents=True)
            cache.write_text('{bad', encoding='utf-8')
            monitor = StorageMonitor(root, probe=lambda _: Usage(100, 60, 40))
            monitor.snapshot(refresh=True)
            self.wait_finished(monitor)
            self.assertEqual(monitor.snapshot()['sample']['total'], 100)


class StorageHttpTests(WebTestBase):
    def test_session_origin_and_csrf(self):
        self.assertEqual(self.client.get('/api/v1/storage').status_code, 401)
        csrf = self._session()
        self.assertEqual(self.client.get('/api/v1/storage').status_code, 200)
        self.assertEqual(self.client.get('/api/v1/storage', headers={'Origin': 'http://evil.invalid'}).status_code, 403)
        self.assertEqual(self.client.post('/api/v1/storage/refresh').status_code, 403)
        response = self.client.post('/api/v1/storage/refresh', headers={'X-CSRF-Token': csrf})
        self.assertEqual(response.status_code, 200)
        StorageTests().wait_finished(self.application.storage)
        self.assertIsNotNone(self.client.get('/api/v1/storage').get_json()['data']['sample'])
