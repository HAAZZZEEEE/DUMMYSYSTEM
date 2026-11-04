"""命令退出码必须反映实际的启动、退出结果。"""
import argparse
import unittest
from unittest import mock

from workbench import __main__ as cli


class CliResultsTest(unittest.TestCase):
    def setUp(self):
        self.args = argparse.Namespace(config='unused')
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(cli, '_config', return_value={}).start()
        mock.patch.object(cli, '_print').start()
        self.lifecycle = mock.patch('workbench.lifecycle.Lifecycle').start().return_value

    def test_failed_window_is_nonzero(self):
        self.lifecycle.launch.return_value = {'window_dispatched': False}
        self.assertEqual(cli.cmd_launch(self.args), 1)

    def test_confirmed_window_is_zero(self):
        self.lifecycle.launch.return_value = {'window_dispatched': True}
        self.assertEqual(cli.cmd_launch(self.args), 0)

    def test_failed_stop_is_nonzero(self):
        self.lifecycle.stop.return_value = {'stopping': False, 'reason': '超时'}
        self.assertEqual(cli.cmd_stop(self.args), 1)

    def test_confirmed_stop_is_zero(self):
        self.lifecycle.stop.return_value = {'stopping': True}
        self.assertEqual(cli.cmd_stop(self.args), 0)
