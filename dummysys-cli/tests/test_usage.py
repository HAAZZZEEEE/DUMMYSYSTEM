"""统计的子进程、并发、隐私和故障降级契约。"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from dummysys_cli import usage
from dummysys_cli.__main__ import main


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'dmy_vault').mkdir()

    def cli(self, *args):
        return subprocess.run([sys.executable, '-m', 'dummysys_cli', '--workspace', str(self.root),
                               '--json', *args], capture_output=True, text=True, encoding='utf-8')

    def test_count_success_failure_and_no_parameters(self):
        self.assertEqual(self.cli('capabilities').returncode, 0)
        secret = 'sensitive-test-value'
        self.assertEqual(self.cli('context', '--task', secret).returncode, 2)
        self.assertEqual(self.cli('context').returncode, 2)
        self.assertEqual(self.cli('--help').returncode, 0)
        result = self.cli('stats')
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)['data']
        self.assertEqual((summary['total_calls'], summary['successes'], summary['failures']), (3, 1, 2))
        self.assertNotIn(secret.encode(), usage.database(self.root).read_bytes())
        self.assertEqual(usage.summary(self.root)['total_calls'], 3)

    def test_parallel_processes_do_not_lose_increments(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.cli('capabilities'), range(16)))
        self.assertTrue(all(p.returncode == 0 and not p.stderr for p in results))
        self.assertEqual(usage.summary(self.root)['total_calls'], 16)

    def test_empty_query_and_days_filter(self):
        self.assertEqual(usage.summary(self.root)['total_calls'], 0)
        self.assertFalse(usage.database(self.root).exists())
        usage.record(self.root, 'dmy check', 0)
        with closing(sqlite3.connect(usage.database(self.root))) as connection, connection:
            connection.execute("UPDATE usage SET day='2000-01-01'")
        self.assertEqual(usage.summary(self.root, 1)['total_calls'], 0)
        self.assertEqual(usage.summary(self.root)['total_calls'], 1)
        self.assertEqual(self.cli('stats', '--days', '0').returncode, 2)

    def test_statistics_failure_preserves_command_result(self):
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(usage, 'record', side_effect=sqlite3.OperationalError('locked')):
            with redirect_stdout(output), redirect_stderr(errors):
                code = main(['--workspace', str(self.root), '--json', 'capabilities'])
        self.assertEqual(code, 0)
        self.assertIn('data', json.loads(output.getvalue()))
        self.assertIn('统计未写入', errors.getvalue())
