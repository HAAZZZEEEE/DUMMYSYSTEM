import importlib.util
import json
from pathlib import Path
import unittest
import os
import tempfile
import shutil
from unittest.mock import patch
from dummysys_core._migration import hash_tree

spec = importlib.util.spec_from_file_location('recovery', Path(__file__).parents[1] / 'scripts/recover_long_paths.py')
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


class RecoveryTests(unittest.TestCase):
    def test_io_conversion_never_resolves_links(self):
        from dummysys_core.operations import native_path
        path = Path(tempfile.gettempdir()) / 'junction' / 'file'
        with patch.object(Path, 'resolve', side_effect=AssertionError('must not follow link')):
            converted = native_path(path)
        self.assertEqual(converted.name, 'file')
        self.assertEqual(converted.parent.name, 'junction')

    @unittest.skipUnless(os.name == 'nt', 'Windows 长目录受管提交')
    def test_commit_and_recovery_of_deep_empty_directories(self):
        from dummysys_core.initialize import initialize
        from dummysys_core.workspace import Workspace
        from dummysys_core.operations import native_path
        with tempfile.TemporaryDirectory(dir=native_path(tempfile.gettempdir())) as directory:
            root = Path(directory.removeprefix('\\\\?\\')) / ('workspace' * 7)
            initialize(native_path(root))
            ws = Workspace(root)
            relative = Path('runtime') / ('segment' * 20) / ('nested' * 20) / 'empty'
            target = root / relative
            self.assertGreater(len(str(target)), 260)
            def prepare(stage):
                (stage / relative).mkdir(parents=True)
                return {'path': str(stage / relative)}
            def crash(step, index):
                if step == 'prepared':
                    raise RuntimeError('interruption')
            with self.assertRaises(RuntimeError):
                ws.operations.execute('fixture', {}, 'tester', prepare, request_id='long-directory', checkpoint=crash)
            record = ws.operations.pending()[0]
            ws.operations.recover(record['operation_id'])
            self.assertTrue(native_path(target).is_dir())

    def test_frontmatter_lists_use_vault_block_format(self):
        from dummysys_core._frontmatter import _render_front, parse
        rendered = _render_front({'aliases': ['old, name', '旧名']}, '')
        self.assertIn('aliases:\n  - ', rendered)
        self.assertEqual(parse('---\n' + rendered.strip() + '\n---')[0]['aliases'], ['old, name', '旧名'])

    @unittest.skipUnless(os.name == 'nt', 'Windows 长路径契约')
    def test_hash_tree_includes_over_260_characters(self):
        root = Path(tempfile.mkdtemp())
        extended = Path('\\\\?\\' + str(root))
        try:
            item = extended / ('a' * 100) / ('b' * 100) / ('c' * 60) / 'proof.txt'
            item.parent.mkdir(parents=True)
            item.write_bytes(b'evidence')
            self.assertEqual(hash_tree(root), recovery.inventory(root))
            self.assertEqual(len(hash_tree(root)), 1)
        finally:
            shutil.rmtree(extended)

    def test_only_exact_union_is_accepted(self):
        source = '/' + 'x' * 260
        self.assertEqual(recovery.verify({'a': '1'}, {'b': '2'}, {'a': '1', 'b': '2'}, source), {'a': '1', 'b': '2'})
        for actual in ({'a': 'changed', 'b': '2'}, {'a': '1'}, {'a': '1', 'b': '2', 'c': '3'}):
            with self.assertRaises(ValueError):
                recovery.verify({'a': '1'}, {'b': '2'}, actual, source)

    def test_conflicting_and_short_evidence_rejected(self):
        with self.assertRaises(ValueError):
            recovery.verify({'a': '1'}, {'a': '2'}, {'a': '2'}, '/' + 'x' * 260)
        with self.assertRaises(ValueError):
            recovery.verify({}, {'a': '2'}, {'a': '2'}, '/short')
