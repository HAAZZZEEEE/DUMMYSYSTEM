"""同一工作区的进程互斥、线程互斥和异常退出恢复。"""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from dummysys_core.operations import GovernanceError, workspace_lock
from dummysys_core.locking import supported_platform


@unittest.skipUnless(supported_platform(), '需要 Windows 或 macOS')
class WorkspaceLockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / '中文 工作区'

    def child(self):
        return subprocess.run([sys.executable, '-I', '-B', '-c', """
import sys
from dummysys_core.operations import workspace_lock, GovernanceError
try:
    with workspace_lock(sys.argv[1], timeout=.1, snapshot_locations=False):
        print('acquired')
except GovernanceError as error:
    print(error.code)
""", str(self.root)], capture_output=True, text=True, timeout=10, check=True).stdout.strip()

    def test_same_process_nested_and_other_process_excluded(self):
        with workspace_lock(self.root, snapshot_locations=False):
            with workspace_lock(self.root, snapshot_locations=False):
                self.assertEqual(self.child(), 'LOCK_BUSY')
        self.assertEqual(self.child(), 'acquired')
        self.assertFalse(self.root.exists())

    def test_other_thread_excluded(self):
        def contender():
            with self.assertRaises(GovernanceError) as error:
                with workspace_lock(self.root, timeout=.05, snapshot_locations=False):
                    pass
            return error.exception.code
        with workspace_lock(self.root, snapshot_locations=False):
            with ThreadPoolExecutor(max_workers=1) as pool:
                self.assertEqual(pool.submit(contender).result(timeout=5), 'LOCK_BUSY')

    def test_crashed_owner_releases_lock(self):
        child = subprocess.Popen([sys.executable, '-I', '-B', '-c', """
import sys,time
from dummysys_core.operations import workspace_lock
with workspace_lock(sys.argv[1], snapshot_locations=False):
    print('locked',flush=True)
    time.sleep(30)
""", str(self.root)], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), 'locked')
            self.assertEqual(self.child(), 'LOCK_BUSY')
        finally:
            child.kill()
            child.wait(timeout=5)
            child.stdout.close()
        self.assertEqual(self.child(), 'acquired')

    @unittest.skipUnless(sys.platform == 'darwin', 'Darwin 文件锁')
    def test_symlink_lock_refused_and_target_preserved(self):
        from dummysys_core.local_lock import FileLock
        target = Path(self.temp.name) / 'target'
        target.write_text('preserve', encoding='utf-8')
        link = Path(self.temp.name) / 'link'
        link.symlink_to(target)
        with self.assertRaises(OSError):
            FileLock(link).acquire()
        self.assertEqual(target.read_text(encoding='utf-8'), 'preserve')
