"""本机 POSIX 文件锁。锁文件保留，以便所有进程始终锁定同一 inode。"""
from hashlib import sha256
import os
from pathlib import Path
import stat
import time
import unicodedata


def mac_path_digest(path):
    # 默认 APFS 上大小写和 Unicode 的等价拼写必须共用锁。
    canonical = unicodedata.normalize('NFC', str(Path(path).resolve())).casefold()
    return sha256(os.fsencode(canonical)).hexdigest()


class FileLock:
    def __init__(self, path):
        self.path = path
        self.fd = None

    def acquire(self, timeout=0):
        import fcntl

        if self.fd is not None:
            return False
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise PermissionError('锁文件必须是当前用户私有的普通文件')
            deadline = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self.fd = fd
                    return True
                except BlockingIOError:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return False
                    time.sleep(min(0.025, remaining))
        finally:
            if self.fd is None:
                os.close(fd)

    def release(self):
        if self.fd is not None:
            fd, self.fd = self.fd, None
            os.close(fd)
