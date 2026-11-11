"""Workbench JSON 写入：复用 core 原子替换，保留调用方的 I/O 错误契约。"""
import errno

from dummysys_core.operations import GovernanceError, save


def write_json(path, value):
    try:
        save(path, value)
    except GovernanceError as error:
        if error.code != 'STATE_CONFLICT':
            raise
        raise PermissionError(errno.EACCES, '目标文件持续被占用，写入未完成', str(path)) from error
