"""窗口测试只使用快照与 API mock；绝不打开真实 GUI。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from workbench.window_control import _argv, activate_edge_window, edge_processes, public_url, verified_edge_tree
from workbench.windows import WindowsOpener, RecordingOpener, SCRIPT_EXTENSIONS
from workbench.action_policy import SCRIPT_EXTENSIONS as POLICY_SCRIPTS


@unittest.skipUnless(__import__("os").name == "nt", "Windows native window APIs")
class WindowControlTest(unittest.TestCase):
    def _check_com_release(self, fail_query=False):
        events = []
        active = {"value": False}

        class Proxy:
            def __init__(self, name):
                self.name = name
                self.released = False
            def _Release_(self):
                if not self.released:
                    events.append((self.name, active["value"]))
                    self.released = True
            def __del__(self):
                self._Release_()

        class Row(Proxy):
            ProcessId = 10
            ParentProcessId = 1
            ExecutablePath = "C:/Edge/msedge.exe"
            @property
            def CommandLine(self):
                if fail_query:
                    raise RuntimeError("模拟属性查询失败")
                return "msedge.exe"

        class Rows(Proxy):
            def __iter__(self):
                yield Row("row")

        class Service(Proxy):
            def ExecQuery(self, query):
                return Rows("rows")

        def initialize():
            active["value"] = True

        def uninitialize():
            events.append(("uninitialize", True))
            active["value"] = False

        with patch("pythoncom.CoInitialize", side_effect=initialize), patch(
                "pythoncom.CoUninitialize", side_effect=uninitialize), patch(
                "win32com.client.GetObject", side_effect=lambda *args: Service("service")), patch(
                "workbench.window_control.process_identity", return_value={"pid": 10}), patch(
                "workbench.window_control._argv", return_value=["msedge.exe"]):
            if fail_query:
                with self.assertRaises(RuntimeError):
                    edge_processes()
            else:
                self.assertEqual(len(edge_processes()), 1)
        self.assertEqual({name for name, live in events if live}, {"row", "rows", "service", "uninitialize"})
        self.assertTrue(all(live for name, live in events), events)
        self.assertEqual(events[-1][0], "uninitialize")

    def test_com_proxies_released_before_uninitialize(self):
        self._check_com_release()

    def test_com_proxies_released_on_property_failure(self):
        self._check_com_release(fail_query=True)

    def test_windows_argument_parser_keeps_profile_path(self):
        self.assertEqual(_argv('msedge.exe "--user-data-dir=C:\\space folder\\profile" --app=http://127.0.0.1:1234/'),
                         ['msedge.exe', '--user-data-dir=C:\\space folder\\profile', '--app=http://127.0.0.1:1234/'])

    def processes(self):
        return [
            {"pid": 10, "parent_pid": 1, "exe": "C:/Edge/msedge.exe", "user_sid": "sid",
             "process_created_at": "100", "argv": ["msedge.exe", "--user-data-dir=C:/profile",
                                                        "--app=http://127.0.0.1:1234/#token=secret"]},
            {"pid": 11, "parent_pid": 10, "exe": "C:/Edge/msedge.exe", "user_sid": "sid",
             "process_created_at": "101", "argv": ["msedge.exe", "--type=renderer"]},
        ]

    def tree(self, processes):
        return verified_edge_tree(processes, "C:/profile", "C:/Edge/msedge.exe", "http://127.0.0.1:1234/", "sid")

    def test_tree_needs_profile_origin_exe_sid_and_creation_order(self):
        self.assertEqual(set(self.tree(self.processes())), {10, 11})
        for key, value in [("exe", "C:/other.exe"), ("user_sid", "other"),
                           ("argv", ["--app=http://127.0.0.1:1234/", "--user-data-dir=C:/other"])]:
            with self.subTest(key=key):
                processes = self.processes()
                processes[0][key] = value
                self.assertEqual(self.tree(processes), {})
        processes = self.processes()
        processes[1]["process_created_at"] = "99"
        self.assertEqual(set(self.tree(processes)), {10})

    def test_title_alone_never_activates(self):
        with patch("workbench.window_control.edge_processes", return_value=[]), patch(
                "workbench.window_control.current_user_sid", return_value="sid"), patch(
                "win32gui.EnumWindows", side_effect=lambda callback, arg: callback(55, arg)), patch(
                "win32gui.IsWindowVisible", return_value=True), patch(
                "win32gui.GetClassName", return_value="Chrome_WidgetWin_1"), patch(
                "win32gui.GetWindow", return_value=0), patch(
                "win32process.GetWindowThreadProcessId", return_value=(1, 999)), patch(
                "win32gui.SetForegroundWindow") as foreground:
            self.assertFalse(activate_edge_window("C:/profile", "C:/Edge/msedge.exe", "http://127.0.0.1:1234/"))
            foreground.assert_not_called()

    def test_verified_window_activated_without_spawning(self):
        processes = self.processes()
        with patch("workbench.window_control.edge_processes", return_value=processes), patch(
                "workbench.window_control.current_user_sid", return_value="sid"), patch(
                "workbench.window_control.process_identity", side_effect=lambda pid: next(p for p in processes if p["pid"] == pid)), patch(
                "win32gui.EnumWindows", side_effect=lambda callback, arg: callback(55, arg)), patch(
                "win32gui.IsWindowVisible", return_value=True), patch(
                "win32gui.GetClassName", return_value="Chrome_WidgetWin_1"), patch(
                "win32gui.GetWindow", return_value=0), patch(
                "win32process.GetWindowThreadProcessId", return_value=(1, 11)), patch(
                "win32gui.IsWindow", return_value=True), patch(
                "win32gui.IsIconic", return_value=False), patch(
                "win32gui.SetForegroundWindow") as foreground, patch(
                "win32gui.GetForegroundWindow", return_value=55):
            self.assertTrue(activate_edge_window("C:/profile", "C:/Edge/msedge.exe", "http://127.0.0.1:1234/"))
            foreground.assert_called_once_with(55)
            foreground.reset_mock()
            with patch("workbench.window_control.process_identity", return_value=None):
                self.assertFalse(activate_edge_window("C:/profile", "C:/Edge/msedge.exe", "http://127.0.0.1:1234/"))
                foreground.assert_not_called()
            with patch("win32gui.EnumWindows", side_effect=lambda callback, arg: [callback(55, arg), callback(56, arg)]):
                self.assertTrue(activate_edge_window("C:/profile", "C:/Edge/msedge.exe", "http://127.0.0.1:1234/"))
                foreground.assert_called_once_with(55)
                foreground.reset_mock()
                with patch("win32gui.GetForegroundWindow", return_value=56):
                    self.assertTrue(activate_edge_window("C:/profile", "C:/Edge/msedge.exe", "http://127.0.0.1:1234/"))
                    foreground.assert_called_once_with(56)
                foreground.reset_mock()
                with patch("win32gui.GetForegroundWindow", side_effect=[999, 55]):
                    self.assertTrue(activate_edge_window("C:/profile", "C:/Edge/msedge.exe", "http://127.0.0.1:1234/"))
                    foreground.assert_called_once_with(55)

    def test_public_result_and_events_do_not_contain_credentials(self):
        url = "http://user:password@127.0.0.1:1234/?credential=query#token=secret"
        self.assertEqual(public_url(url), "http://127.0.0.1:1234/")
        opener = WindowsOpener({"apps": {}})
        with patch.object(opener, "_require_edge", return_value="msedge.exe"), patch.object(opener, "_spawn"):
            opener.edge_app_mode(url, "profile")
        recording = RecordingOpener()
        recording.edge_app_mode(url, "profile")
        events = json.dumps(opener.events() + recording.events())
        for secret in ("password", "secret", "query", "user:"):
            self.assertNotIn(secret, events)
        self.assertIs(SCRIPT_EXTENSIONS, POLICY_SCRIPTS)


if __name__ == "__main__":
    unittest.main()
