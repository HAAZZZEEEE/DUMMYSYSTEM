"""Finder metadata must not make a healthy workspace fail everyday validation."""
from pathlib import Path
import tempfile
import unittest
from dummysys_core.initialize import initialize
from dummysys_core.validation.layout import validate

class FinderMetadataTest(unittest.TestCase):
    def test_only_plain_ds_store_files_are_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'workspace';initialize(root)
            for parent in (root,root/'dmy_vault',root/'runtime',root/'runtime/project_src',root/'runtime/project_src/00-Playground'):
                (parent/'.DS_Store').write_bytes(b'synthetic metadata')
            self.assertEqual(validate(root),[])
            unexpected=root/'dmy_vault/.unexpected.bin';unexpected.write_bytes(b'not metadata')
            self.assertTrue(any('.unexpected.bin' in error for error in validate(root)))
            unexpected.unlink()
            meta=root/'dmy_vault/.DS_Store';meta.unlink()
            try: meta.symlink_to(root/'.DS_Store')
            except OSError: return  # Some Windows users cannot create symlinks.
            self.assertTrue(any('.DS_Store' in error for error in validate(root)))
