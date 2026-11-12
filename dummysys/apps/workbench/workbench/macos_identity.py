"""使用 Darwin libproc 读取 PID、启动时间和有效 UID。"""
import ctypes
import errno
import os

from .identity import identity_matches


class ProcBSDInfo(ctypes.Structure):
    # SDK: sys/proc_info.h, struct proc_bsdinfo (PROC_PIDTBSDINFO).
    _fields_ = [
        ('flags', ctypes.c_uint32),
        ('status', ctypes.c_uint32),
        ('exit_status', ctypes.c_uint32),
        ('pid', ctypes.c_uint32),
        ('ppid', ctypes.c_uint32),
        ('uid', ctypes.c_uint32),
        ('gid', ctypes.c_uint32),
        ('ruid', ctypes.c_uint32),
        ('rgid', ctypes.c_uint32),
        ('svuid', ctypes.c_uint32),
        ('svgid', ctypes.c_uint32),
        ('reserved', ctypes.c_uint32),
        ('command', ctypes.c_char * 16),
        ('name', ctypes.c_char * 32),
        ('nfiles', ctypes.c_uint32),
        ('pgid', ctypes.c_uint32),
        ('pjobc', ctypes.c_uint32),
        ('tdev', ctypes.c_uint32),
        ('tpgid', ctypes.c_uint32),
        ('nice', ctypes.c_int32),
        ('start_sec', ctypes.c_uint64),
        ('start_usec', ctypes.c_uint64),
    ]


def process_identity(pid):
    if type(pid) is not int or not 0 < pid <= 0x7fffffff:
        raise ValueError('无效的进程 PID')
    proc_pidinfo = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True).proc_pidinfo
    proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
    proc_pidinfo.restype = ctypes.c_int
    info = ProcBSDInfo()
    ctypes.set_errno(0)
    size = proc_pidinfo(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info))
    if size <= 0 and ctypes.get_errno() == errno.ESRCH:
        return None
    if size != ctypes.sizeof(info) or info.pid != pid or not info.start_sec:
        raise RuntimeError('无法核实进程身份')
    if info.status == 5:  # SZOMB: the child has exited and awaits collection.
        return None
    return {'pid': pid, 'process_created_at': str(info.start_sec * 1_000_000 + info.start_usec),
            'user_sid': f'uid:{info.uid}'}


def current_user_sid():
    return f'uid:{os.geteuid()}'


def process_alive(pid):
    try:
        return process_identity(pid) is not None
    except (OSError, RuntimeError, ValueError):
        return False
