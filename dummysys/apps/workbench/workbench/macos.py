"""通过 Launch Services 打开浏览器、Finder 与已安装的编辑器。"""
import os
from pathlib import Path
import shutil
import subprocess
from urllib.parse import quote

from .action_policy import SCRIPT_EXTENSIONS
from .ports import AppUnavailable, OpenFailed


def _find_app(name):
    return next((str(root / name) for root in (Path('/Applications'), Path.home() / 'Applications')
                 if (root / name).is_dir()), None)


class MacOpener:
    supports_native_window = True

    def __init__(self, config):
        self.config = config
        apps = config.get('apps', {})
        self.vscode_exe = apps.get('vscode_exe') or shutil.which('code')
        self.vscode_app = _find_app('Visual Studio Code.app') if not self.vscode_exe else None
        self.obsidian_app = _find_app('Obsidian.app')
        self.obsidian_vault = apps.get('obsidian_vault_path')

    def probe(self):
        vscode = self.vscode_app or (self.vscode_exe if self.vscode_exe
                                    and os.path.isfile(self.vscode_exe)
                                    and os.access(self.vscode_exe, os.X_OK) else None)
        obsidian = bool(self.obsidian_app and self.obsidian_vault and Path(self.obsidian_vault).is_dir())
        return {
            'browser': {'available': True, 'reason': None},
            'vscode': {'available': bool(vscode), 'exe': vscode,
                       'reason': None if vscode else '未探测到 VS Code'},
            'obsidian': {'available': obsidian, 'vault': self.obsidian_vault,
                         'reason': None if obsidian else 'Obsidian 不可用或未配置 Vault'},
        }

    @staticmethod
    def _open(args):
        try:
            subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, check=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            raise OpenFailed('本机应用未能打开目标') from None

    @staticmethod
    def _target(path):
        target = Path(path)
        if not target.is_absolute() or not target.exists():
            raise OpenFailed('目标不存在或不是绝对路径')
        return str(target)

    def open_browser(self, url, profile_dir=None):
        self._open(['/usr/bin/open', '--', url])

    def activate_browser(self, url, profile_dir):
        return False

    def native_app_ready(self, record):
        from .macos_window import native_ready
        return native_ready(record)

    def activate_native_app(self, record):
        from .macos_window import activate
        return activate(self.config, record)

    def native_app_mode(self, config_path, instance_id):
        import sys
        from .processes import spawn_background
        args = ([sys.executable] if getattr(sys, "frozen", False)
                else [sys.executable, "-I", "-B", "-m", "workbench"])
        spawn_background([*args, "window", "--config", config_path, "--instance-id", instance_id],
                         independent=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def explorer_open(self, path):
        self._open(['/usr/bin/open', '-a', 'Finder', '--', self._target(path)])

    def explorer_reveal(self, path):
        self._open(['/usr/bin/open', '-R', '--', self._target(path)])

    def vscode_open(self, path):
        if not self.probe()['vscode']['available']:
            raise AppUnavailable('VS Code 不可用')
        target = self._target(path)
        if self.vscode_exe:
            self._open([self.vscode_exe, target])
        else:
            self._open(['/usr/bin/open', '-a', self.vscode_app, '--', target])

    def obsidian_open(self, path):
        if not self.probe()['obsidian']['available']:
            raise AppUnavailable('Obsidian 不可用或未配置 Vault')
        uri = 'obsidian://open?path=' + quote(self._target(path), safe='')
        self._open(['/usr/bin/open', '-a', self.obsidian_app, '--', uri])

    def system_open(self, path):
        target = self._target(path)
        if Path(target).suffix.casefold() in SCRIPT_EXTENSIONS or Path(target).is_dir() or os.access(target, os.X_OK):
            raise AppUnavailable('可执行文件或应用包不提供系统默认打开')
        self._open(['/usr/bin/open', '--', target])
