"""以真实 Windows 共享句柄验证短时占用与持续占用，不伪造替换异常。"""
import ctypes
from ctypes import wintypes
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from workbench.lifecycle import write_json
from workbench.preferences import Preferences
from workbench.storage import StorageMonitor


@unittest.skipUnless(os.name == 'nt', 'Windows 文件共享语义')
class JsonSharingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
            ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        self.kernel.CreateFileW.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL

    def writers(self):
        preferences = Preferences(self.root / 'preferences.json')
        state = self.root / 'instance.json'
        storage = StorageMonitor(self.root)
        return [(preferences.path, lambda: preferences.patch({'theme': 'dark'})),
                (state, lambda: write_json(state, {'state': 'new'})),
                (storage.path, storage._save_locked)]

    @contextmanager
    def held(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"original":true}', encoding='utf-8')
        handle = self.kernel.CreateFileW(str(path), 0x80000000, 3,
                                         None, 3, 0x80, None)
        self.assertNotEqual(handle, wintypes.HANDLE(-1).value, ctypes.get_last_error())
        def close():
            nonlocal handle
            if handle is not None:
                self.kernel.CloseHandle(handle)
                handle = None
        try:
            yield close
        finally:
            close()

    def test_short_lived_reader_allows_eventual_atomic_write(self):
        for path, writer in self.writers():
            with self.subTest(path=path.name), self.held(path) as close:
                denied = threading.Event()
                errors = []
                original_replace = os.replace
                def observed_replace(*args, **kwargs):
                    try:
                        return original_replace(*args, **kwargs)
                    except PermissionError as error:
                        errors.append(error.winerror)
                        denied.set()
                        raise
                def release():
                    denied.wait(2)
                    time.sleep(.06)
                    close()
                reader = threading.Thread(target=release)
                reader.start()
                try:
                    with patch('os.replace', side_effect=observed_replace):
                        writer()
                    self.assertIn(5, errors)
                    self.assertNotIn('original', json.loads(path.read_text(encoding='utf-8')))
                finally:
                    denied.set()
                    reader.join()

    def test_persistent_reader_reports_failure_and_preserves_old_data(self):
        for path, writer in self.writers():
            with self.subTest(path=path.name), self.held(path):
                with self.assertRaises(PermissionError):
                    writer()
                self.assertEqual(json.loads(path.read_text(encoding='utf-8')), {'original': True})
                self.assertEqual(list(path.parent.glob('*.tmp')), [])
                self.assertEqual(list(path.parent.glob('.dmy-*')), [])

    def test_closed_reader_allows_atomic_write(self):
        for path, writer in self.writers():
            with self.subTest(path=path.name), self.held(path) as close:
                close()
                writer()
                self.assertNotIn('original', json.loads(path.read_text(encoding='utf-8')))
