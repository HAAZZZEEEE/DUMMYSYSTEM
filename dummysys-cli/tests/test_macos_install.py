"""Opt-in real wheel installation; DUMMYSYS_TEST_WHEELS points outside the repo."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

@unittest.skipUnless(sys.platform == 'darwin' and os.environ.get('DUMMYSYS_TEST_WHEELS'), 'requires macOS wheelhouse integration fixture')
class MacInstallTest(unittest.TestCase):
    def test_install_unicode_space_isolation_existing_workspace_and_refusal(self):
        script = Path(__file__).resolve().parents[1] / 'scripts/install.py'
        host = os.environ.get('DUMMYSYS_HOST_PYTHON', sys._base_executable)
        with tempfile.TemporaryDirectory(prefix='安装 演练 ') as directory:
            base=Path(directory);workspace=base/'中文 工作区'
            def install(root,release):
                return subprocess.run([host,'-I','-B',str(script),'--workspace',str(root),'--wheels',os.environ['DUMMYSYS_TEST_WHEELS'],
                                       '--release-id',release,'--desktop'],cwd=base,capture_output=True,text=True,timeout=120)
            denied=base/'已有文件';denied.mkdir();(denied/'保留.txt').write_text('unchanged')
            result=install(denied,'refused')
            self.assertEqual(result.returncode,2,result.stdout+result.stderr)
            self.assertEqual(list(denied.iterdir()),[denied/'保留.txt'])
            first=install(workspace,'first')
            self.assertEqual(first.returncode,0,first.stdout+first.stderr)
            receipt=json.loads(first.stdout)
            env={**os.environ,'PYTHONPATH':str(base/'poison'),'PYTHONHOME':str(base/'invalid')}
            def cli(args):
                result=subprocess.run([receipt['launcher'],*args,'--json'],cwd=base,env=env,capture_output=True,text=True,timeout=20)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                return json.loads(result.stdout)['data']
            self.assertTrue(cli(['check'])['ok'])
            created=cli(['--actor','integration','--request-id','create-fixture','project','create','--title','测试 项目'])['result']['project_id']
            second=install(workspace,'second')
            self.assertEqual(second.returncode,0,second.stdout+second.stderr)
            self.assertEqual(cli(['project','show',created])['title'],'测试 项目')
            imports=subprocess.run([json.loads(second.stdout)['python'],'-I','-B','-c',
                'import dummysys_core,dummysys_cli,workbench,json;print(json.dumps([m.__file__ for m in [dummysys_core,dummysys_cli,workbench]]))'],
                cwd=base,env=env,capture_output=True,text=True,check=True)
            for file in json.loads(imports.stdout): self.assertTrue(Path(file).is_relative_to(workspace/'runtime/envs/second'))
            duplicate=install(workspace,'second')
            self.assertEqual(duplicate.returncode,2)
