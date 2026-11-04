import importlib.util
import json
from pathlib import Path
import unittest
import os
import tempfile
import shutil
from dummysys_core._migration import hash_tree

spec = importlib.util.spec_from_file_location('recovery', Path(__file__).parents[1] / 'scripts/recover_long_paths.py')
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


class RecoveryTests(unittest.TestCase):
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
