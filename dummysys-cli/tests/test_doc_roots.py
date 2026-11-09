"""文档源码选择与旧仓隔离。"""
import json
from pathlib import Path
import tempfile
import unittest
from dummysys_cli.doccheck import check_docs
from dummysys_core import locations as loc

class DocRootsTests(unittest.TestCase):
    def test_selection_and_invalid_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'dmy_vault').mkdir()
            manifest=json.dumps(dict(schema_version=1,documents=[]))
            (root/'.dummysys-docs.json').write_text(manifest)
            source=root/'中文 源码';source.mkdir()
            (source/'.dummysys-docs.json').write_text(manifest)
            state=loc.runtime(root)/'state/workspace';state.mkdir(parents=True)
            (state/'repositories.json').write_text('invalid old mapping')
            config=state/'doccheck.json'
            for selected in ([source.name],[str(source)],[]):
                config.write_text(json.dumps(dict(schema_version=1,roots=selected)))
                self.assertTrue(check_docs(root)['ok'])
            for bad in ([],{},dict(schema_version=2,roots=[]),dict(schema_version=1,roots='x'),dict(schema_version=1,roots=[''])):
                config.write_text(json.dumps(bad))
                result=check_docs(root)
                self.assertFalse(result['ok'])
                self.assertEqual([f['code'] for f in result['failures']],['DOC_ROOTS_INVALID'])
                self.assertTrue(check_docs(root,roots=[root])['ok'])
            config.write_text(json.dumps(dict(schema_version=1,roots=['absent'])))
            self.assertFalse(check_docs(root)['ok'])
            self.assertEqual(len(check_docs(root)['unavailable']),1)

    def test_external_runtime(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'workspace';root.mkdir()
            vault=Path(temp)/'资料';vault.mkdir()
            runtime=Path(temp)/'运行';runtime.mkdir()
            (root/'.dummysys-workspace.json').write_text(json.dumps(dict(schema_version=1,vault_root=str(vault),runtime_root=str(runtime))))
            (root/'.dummysys-docs.json').write_text(json.dumps(dict(schema_version=1,documents=[])))
            state=loc.runtime(root)/'state/workspace';state.mkdir(parents=True)
            (state/'repositories.json').write_text('invalid mapping')
            (state/'doccheck.json').write_text(json.dumps(dict(schema_version=1,roots=[])))
            self.assertTrue(check_docs(root)['ok'])

