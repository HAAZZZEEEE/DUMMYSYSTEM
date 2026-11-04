"""同步后台命令的公共启动入口；不改变调用方的输出与错误契约。"""
import os
import subprocess


def run_background(args, **kwargs):
    """Windows 后台命令不创建控制台；非 Windows 保留原行为。"""
    if os.name == 'nt':
        flags = kwargs.get('creationflags', 0)
        if flags & (subprocess.CREATE_NEW_CONSOLE | subprocess.DETACHED_PROCESS):
            raise ValueError('后台命令不能同时请求新控制台或分离控制台')
        kwargs['creationflags'] = flags | subprocess.CREATE_NO_WINDOW
    return subprocess.run(args, **kwargs)
