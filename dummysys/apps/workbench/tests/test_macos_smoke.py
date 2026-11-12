"""Installed package -> real service -> authenticated HTTP -> graceful shutdown."""
import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

@unittest.skipUnless(sys.platform == 'darwin', 'macOS service integration')
class MacServiceTest(unittest.TestCase):
    def test_service_token_session_stop_and_crash_recovery(self):
        from dummysys_core.initialize import initialize
        from workbench.config import load_config
        from workbench.lifecycle import Lifecycle
        from workbench.platform_runtime import PipeControl
        with tempfile.TemporaryDirectory(prefix='工作台 集成 ') as directory:
            root = Path(directory) / '工作区 with spaces'
            initialize(root)
            config = root / 'runtime/workbench/config.json'
            life = Lifecycle(load_config(config))
            for crash in (True, False):
                child = subprocess.Popen([sys.executable, '-I', '-B', '-m', 'workbench', 'serve', '--config', str(config)],
                                         cwd=directory, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                token = None
                try:
                    deadline = time.monotonic() + 12
                    while time.monotonic() < deadline:
                        record = life.instance.is_healthy()
                        if record: break
                        if child.poll() is not None: break
                        time.sleep(.05)
                    self.assertIsNotNone(record)
                    self.assertEqual(record['pid'], child.pid)
                    with self.assertRaises(ConnectionError):
                        life.pipe.request(PipeControl.REQUEST_STOP, expected_instance_id='wrong', expected_process=record)
                    token = life.pipe.request(PipeControl.REQUEST_TOKEN, expected_instance_id=record['instance_id'], expected_process=record)['token']
                    connection = http.client.HTTPConnection('127.0.0.1', record['port'], timeout=3)
                    try:
                        connection.request('POST', '/api/v1/session', json.dumps({'bootstrap_token':token}),
                                           {'Content-Type':'application/json','Origin':f"http://127.0.0.1:{record['port']}"})
                        response = connection.getresponse()
                        self.assertEqual(response.status, 200)
                        self.assertTrue(json.loads(response.read())['data']['authenticated'])
                    finally: connection.close()
                    if crash:
                        child.kill(); child.wait(timeout=5)
                    else:
                        self.assertTrue(life.stop(wait_stopped=8).get('stopped'))
                        self.assertEqual(child.wait(timeout=5), 0)
                        self.assertFalse(life.instance.instance_path.exists())
                finally:
                    if child.poll() is None: child.terminate(); child.wait(timeout=5)
                    out,err=child.communicate(timeout=3)
                    if token: self.assertNotIn(token.encode(),out+err)
