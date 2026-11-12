"""原生窗口使用显式本机图标与独立任务栏身份，不携带私人图像。"""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from workbench.window_host import show, window_icon
from workbench.windows_identity import WORKBENCH_APP_ID, set_workbench_app_id

class Event(list):
    def __iadd__(self, handler):
        self.append(handler)
        return self

class WindowBrandingTest(unittest.TestCase):
    def test_icon_and_identity_reach_the_real_window_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            icon = root / '图标 文件.ico'
            icon.write_bytes(b'synthetic fixture; webview adapter mocked')
            config = {'apps': {'window_icon_path': str(icon)}, 'task_root': str(root)}
            record = {'instance_id': 'test-instance', 'port': 45678}
            identity = {'pid': 42, 'process_created_at': '1', 'user_sid': 'test-user'}
            order = []
            window = SimpleNamespace(events=SimpleNamespace(shown=Event(), closed=Event()))
            webview = Mock()
            webview.create_window.side_effect = lambda *a, **k: (order.append('create') or window)
            webview.start.side_effect = lambda **k: window.events.shown[0]()
            with patch.dict('sys.modules', {'clr': Mock(), 'webview': webview}), \
                    patch('workbench.window_host.Lifecycle') as constructor, \
                    patch('workbench.window_host.process_identity', return_value=identity), \
                    patch('workbench.windows_window.set_workbench_app_id', side_effect=lambda: order.append('identity')), \
                    patch('workbench.window_host.host_backend', return_value=__import__('workbench.windows_window', fromlist=['run'])):
                life = constructor.return_value
                life.instance.is_healthy.return_value = record
                life.instance.state = root / 'state'
                life.instance.window_path = root / 'state/window.json'
                life.pipe.request.return_value = {'instance_id': 'test-instance', 'token': 'synthetic-token'}
                show(config, 'test-instance')
            self.assertEqual(order, ['identity', 'create'])
            self.assertEqual(webview.start.call_args.kwargs['icon'], str(icon))
            saved = json.loads((root / 'state/window.json').read_text(encoding='utf-8'))
            self.assertEqual(saved['icon_path'], str(icon))
            self.assertEqual(saved['app_user_model_id'], WORKBENCH_APP_ID)
            self.assertNotIn('synthetic-token', json.dumps(saved))

    def test_missing_explicit_icon_is_not_silently_replaced_with_python_icon(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, '图标不存在'):
                window_icon({'apps': {'window_icon_path': str(Path(directory) / 'missing.ico')}})

    def test_non_windows_does_not_call_shell32(self):
        with patch('workbench.windows_identity.os.name', 'posix'), patch('ctypes.WinDLL', create=True) as library:
            set_workbench_app_id()
        library.assert_not_called()

    def test_failed_windows_identity_is_reported(self):
        api = Mock()
        api.SetCurrentProcessExplicitAppUserModelID.return_value = -1
        with patch('workbench.windows_identity.os.name', 'nt'), patch('ctypes.WinDLL', return_value=api, create=True):
            with self.assertRaisesRegex(RuntimeError, '窗口身份'):
                set_workbench_app_id()

