"""Choose the native window backend without leaking Cocoa/Windows into the host."""
import sys

def host_backend():
    if sys.platform == 'darwin':
        from . import macos_window
        return macos_window
    if sys.platform == 'win32':
        from . import windows_window
        return windows_window
    raise RuntimeError('Native windows require Windows or macOS')
