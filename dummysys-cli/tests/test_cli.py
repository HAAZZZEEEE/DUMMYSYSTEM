"""命令行进程契约。"""
import json
from pathlib import Path
import subprocess
import sys
import unittest
if __package__:
    from . import test_governance as fixtures
else:
    import test_governance as fixtures

class CliTests(unittest.TestCase):
    setUp = fixtures.GovernanceTests.setUp
    create = fixtures.GovernanceTests.create

    def cli(self, *args, cwd=None):
        result = subprocess.run([sys.executable, '-m', 'dummysys_cli', '--workspace', str(self.root), '--json', *args],
                                cwd=cwd, capture_output=True, text=True, encoding='utf-8')
        return result, json.loads(result.stdout)

    def test_json_errors_and_configuration(self):
        p,data=self.cli('task','create','--title','test','--origin','agent','--goal','test','--actor','tester')
        self.assertEqual(p.returncode,2);self.assertEqual(data['error']['code'],'REQUEST_REQUIRED')
        p,data=self.cli('task','show','missing')
        self.assertEqual(p.returncode,2);self.assertIn('error',data)
        p,data=self.cli('capabilities');self.assertEqual(p.returncode,0)
        self.assertTrue(any(c['command']=='dmy repo snapshot' for c in data['data']['commands']))

    def test_context_from_another_cwd(self):
        task = self.create()
        result, data = self.cli('context', '--task', task, cwd=Path.home())
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(data['data']['task']['task_id'], task)

    def test_archive_allow_unfinished_flag_and_capabilities(self):
        task = self.create()
        denied, value = self.cli('task', 'archive', '--task', task, '--reason', '收起', '--dry-run', '--actor', 'tester')
        self.assertEqual(denied.returncode, 2)
        accepted, value = self.cli('task', 'archive', '--task', task, '--reason', '收起', '--dry-run',
            '--allow-unfinished', '--actor', 'tester')
        self.assertEqual(accepted.returncode, 0, value)
        self.assertTrue(value['data']['plan']['allow_unfinished'])
        _, caps = self.cli('capabilities')
        for entity in ('task', 'project'):
            self.assertEqual(caps['data']['actions'][entity + '.archive']['params']['allow_unfinished'], 'bool')
