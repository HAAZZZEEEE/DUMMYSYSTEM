"""后台进程不分配控制台；保留调用方的输出、退出和进程组契约。"""
import os
import subprocess


def _background_options(kwargs, independent=False):
    if os.name == 'nt':
        flags = kwargs.get('creationflags', 0)
        if flags & (subprocess.CREATE_NEW_CONSOLE | subprocess.DETACHED_PROCESS):
            raise ValueError('后台命令不能同时请求新控制台或分离控制台')
        kwargs['creationflags'] = flags | subprocess.CREATE_NO_WINDOW
        if independent:
            kwargs['creationflags'] |= subprocess.CREATE_NEW_PROCESS_GROUP
    return kwargs


def run_background(args, **kwargs):
    """Windows 后台命令不创建控制台；非 Windows 保留原行为。"""
    return subprocess.run(args, **_background_options(kwargs))


def spawn_background(args, *, independent=False, **kwargs):
    # DETACHED_PROCESS 下 Windows venv 的转发进程可能为基础 Python 重建控制台。
    # CREATE_NO_WINDOW 同时适用于服务与具有自身原生窗口的 GUI 宿主。
    return subprocess.Popen(args, **_background_options(kwargs, independent))
