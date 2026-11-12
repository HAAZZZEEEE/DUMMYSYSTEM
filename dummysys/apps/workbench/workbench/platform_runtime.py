"""The single platform selection boundary. No unsupported-platform fallback."""
import sys
from .ports import Opener
from .identity import identity_matches

if sys.platform == 'win32':
    from .windows_identity import process_identity, current_user_sid, process_alive
    from .instance_control import InstanceMutex, PipeControl
    from .windows import WindowsOpener as PlatformOpener
    from .shortcuts import install_shortcuts, uninstall_shortcuts
elif sys.platform == 'darwin':
    from .macos_identity import process_identity, current_user_sid, process_alive
    from .macos_control import InstanceMutex, PipeControl
    from .macos import MacOpener as PlatformOpener
    def install_shortcuts(*args, **kwargs):
        raise RuntimeError('macOS 应用入口由 build_macos_app.py 安装；请参阅 INSTALL.md')
    def uninstall_shortcuts(*args, **kwargs):
        raise RuntimeError('macOS 不使用 Windows 快捷方式；请管理已安装的 .app')
else:
    raise RuntimeError('Workbench supports Windows and macOS')


def create_opener(config) -> Opener:
    return PlatformOpener(config)
