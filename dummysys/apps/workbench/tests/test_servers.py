"""服务器展示不泄露密码，坏档案不阻断首页。"""
import json
import tempfile
import unittest
from pathlib import Path

from workbench.servers import server_inventory


class ServerInventoryTests(unittest.TestCase):
    def test_projection_and_refresh_without_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            path = workspace / 'runtime/servers/profiles.json'
            path.parent.mkdir(parents=True)
            profile = dict(alias='test-server', model='Example Server',
                           ssh=dict(host='192.0.2.1', user='root', password='secret-sentinel'),
                           notes='secret-notes', verification=dict(status='verified', checked_at='2026-10-27'))
            path.write_text(json.dumps(dict(schema_version=1, profiles=[profile])), encoding='utf-8')
            result = server_inventory(workspace)
            row = result['servers'][0]
            self.assertEqual(row['model'], 'Example Server')
            self.assertEqual(row['account'], 'root')
            self.assertEqual(row['ip'], '192.0.2.1')
            self.assertTrue(row['reachable'])
            self.assertIn('ssh.password', row['password_access'])
            self.assertNotIn('secret', json.dumps(result))
            profile['hardware'] = dict(generation='Example Gen', product='Example Server（产品待核）',
                                       chip='Example Chip', product_form='超节点',
                                       host_model='Example Host（DMI，待核）', evidence='private-evidence')
            path.write_text(json.dumps(dict(schema_version=1, profiles=[profile])), encoding='utf-8')
            result = server_inventory(workspace)
            self.assertEqual(result['servers'][0]['model'], 'Example Gen / Example Server（产品待核） / Example Chip')
            self.assertEqual(result['servers'][0]['product_form'], '超节点')
            self.assertEqual(result['servers'][0]['host_model'], 'Example Host（DMI，待核）')
            self.assertNotIn('private-evidence', json.dumps(result))
            self.assertFalse(result['servers'][0]['reachable'])
            profile['hardware']['checked_at'] = '2026-10-27'
            path.write_text(json.dumps(dict(schema_version=1, profiles=[profile])), encoding='utf-8')
            self.assertTrue(server_inventory(workspace)['servers'][0]['reachable'])
            profile['hardware']['reason'] = '连接失败'
            path.write_text(json.dumps(dict(schema_version=1, profiles=[profile])), encoding='utf-8')
            self.assertFalse(server_inventory(workspace)['servers'][0]['reachable'])
            profile.pop('hardware')
            profile['ssh'].pop('password')
            profile.pop('model', None)
            path.write_text(json.dumps(dict(schema_version=1, profiles=[profile])), encoding='utf-8')
            row = server_inventory(workspace)['servers'][0]
            self.assertEqual(row['model'], '未登记')
            self.assertIn('管理员', row['password_access'])

    def test_missing_and_invalid_files(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            self.assertEqual(server_inventory(workspace)['servers'], [])
            path = workspace / 'runtime/servers/profiles.json'
            path.parent.mkdir(parents=True)
            for content in ['invalid', '{"schema_version":1,"profiles":[null]}']:
                path.write_text(content, encoding='utf-8')
                self.assertFalse(server_inventory(workspace)['available'])
