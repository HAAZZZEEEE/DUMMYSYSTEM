"""缓存身份、外部修改可见性和运行版本的行为回归。"""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from workbench import dmy, metadata
from workbench.catalog import Catalog
from workbench.overview import build_overview
from workbench.tracing import trace
from workbench.web import create_app
from tests.helpers import build_workspace
from tests.test_web import WebTestBase


class CapabilityCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);dmy._cap_cache.clear()
        self.calls=[]

    def runner(self,cmd,**kwargs):
        self.calls.append((cmd,kwargs))
        return subprocess.CompletedProcess(cmd,0,json.dumps(dict(schema_version=1,data=dict(version='0.2.0',contract_version=2,actions={}))), '')

    def test_cache_reuse_and_workspace_installation_invalidation(self):
        with patch.object(dmy,'resolve_command',return_value=(['python'],'test')):
            for _ in range(3):dmy.capabilities(self.root,runner=self.runner)
            self.assertEqual(len(self.calls),1)
            manifest=self.root/'runtime/state/workspace/cli-install.json';manifest.parent.mkdir(parents=True)
            manifest.write_text('{}')
            dmy.capabilities(self.root,runner=self.runner)
            dmy.capabilities(self.root/'other',runner=self.runner)
        self.assertEqual(len(self.calls),3)

    def test_failures_and_unknown_contract_are_not_cached(self):
        with patch.object(dmy,'resolve_command',return_value=(['python'],'test')):
            with patch.object(dmy,'run_dmy',side_effect=dmy.DmyError('CLI_UNAVAILABLE','missing')):
                self.assertIsNone(dmy.capabilities(self.root))
            self.assertIsNotNone(dmy.capabilities(self.root,runner=self.runner))
            with patch.object(dmy,'run_dmy',return_value=dict(contract_version=999)):
                with self.assertRaisesRegex(dmy.DmyError,'契约版本不支持'):
                    dmy.capabilities(self.root/'new')

    def test_trace_and_source_are_forwarded_without_body(self):
        token=trace.set('11111111-1111-4111-8111-111111111111')
        try:
            with patch.object(dmy,'resolve_command',return_value=(['python'],'test')):
                dmy.run_dmy(['stats'],workspace=self.root,runner=self.runner)
        finally:trace.reset(token)
        env=self.calls[0][1]['env']
        self.assertEqual(env['DMY_CALL_SOURCE'],'workbench')
        self.assertEqual(env['DMY_TRACE_ID'],'11111111-1111-4111-8111-111111111111')


class MetadataTests(unittest.TestCase):
    def test_request_reuse_and_external_edit_next_request(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); ws=build_workspace(root,dict(p=dict(project_id='p',docs_root='docs',resource_root='resources')))
            catalog=Catalog(dict(workspace_root=str(ws)))
            with patch.object(metadata.yaml,'safe_load',wraps=metadata.yaml.safe_load) as load:
                build_overview(catalog,lambda:dict(total_calls=0,commands=[]))
                self.assertEqual(load.call_count,1)
            readme=ws/'docs/README.md';text=readme.read_text(encoding='utf-8').replace('title: "p"','title: "外部修改"');readme.write_text(text,encoding='utf-8')
            self.assertEqual(catalog.list_projects()['projects'][0]['title'],'外部修改')


class RuntimeIdentityTests(WebTestBase):
    def test_startup_identity_and_changed_checkout(self):
        before=dict(version='a',sha='a',source_fingerprint='a')
        after=dict(version='a',sha='b',source_fingerprint='b')
        with patch('workbench.web.release_info',side_effect=[before,after]):
            app=create_app(self.application,self.instance,lambda:'t',static_dir=self.static)
            client=app.test_client()
            response=client.get('/healthz')
            self.assertEqual(response.get_json()['data']['running_release'],before)
            self.assertTrue(response.headers['X-Diagnostic-ID'])
            token=app.extensions['bootstrap_issuer']()
            client.post('/api/v1/session',json=dict(bootstrap_token=token))
            value=client.get('/api/v1/meta').get_json()['data']
        self.assertTrue(value['restart_required']);self.assertEqual(value['running_release'],before)
        self.assertIsNone(trace.get())
