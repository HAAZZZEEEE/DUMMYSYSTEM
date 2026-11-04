"""物理位置变化不能改变逻辑身份、受管写入边界与恢复目标。"""
import errno
import json
import os
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from dummysys_core import locations as loc
from dummysys_core.initialize import initialize
from dummysys_core.operations import GovernanceError, digest, safe_target
from dummysys_core.workspace import Workspace
from dummysys_core.validation import layout, vault
from dummysys_cli.doccheck import check_docs


class LocationTests(unittest.TestCase):
    def setUp(self):
        directory = str(Path(tempfile.gettempdir()).resolve())
        if os.name == 'nt' and not directory.startswith('\\\\?\\'):
            directory = '\\\\?\\UNC\\' + directory[2:] if directory.startswith('\\\\') else '\\\\?\\' + directory
        temporary = tempfile.TemporaryDirectory(dir=directory)
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()

    def test_complete_workflow_in_renamed_and_external_locations(self):
        from workbench.catalog import Catalog
        for external in (False, True):
            root = self.base / str(external) / '工作 空间'
            v = str(root.parent / '外部 正文') if external else '资料 正文'
            r = '../外部 运行' if external else '运行 资料'
            initialize(root, vault_root=v, runtime_root=r)
            locations = loc.load(root)
            ws = Workspace(root)
            def mutate(action, values, version=None):
                return ws.mutate(action, values, actor='tester', request_id=str(uuid4()), if_version=version)['result']
            pid = mutate('project.create', dict(title='配置路径'))['project_id']
            tid = mutate('task.create', dict(project=pid, title='接续', origin='user', goal='验证'))['task_id']
            rid = mutate('run.create', dict(task=tid, title='验证', host='local', source='fixture', inputs='fixture', command='fixture'))['run_id']
            mutate('run.start', dict(task=tid, run=rid), ws.run(tid, rid)['version'])
            mutate('run.finish', dict(task=tid, run=rid, status='completed', result='通过', exit_code=0, evidence=['fixture']), ws.run(tid, rid)['version'])
            task = ws.task(tid)
            self.assertTrue(Path(task['document']).is_relative_to(locations.vault))
            self.assertTrue(Path(ws.run(tid, rid)['record']).is_relative_to(locations.runtime))
            self.assertTrue(task['binding']['docs_root'].startswith('dmy_vault/'))
            self.assertTrue(task['binding']['resource_root'].startswith('runtime/'))
            self.assertFalse((root / 'runtime').exists())
            self.assertFalse((root / 'dmy_vault').exists())
            self.assertTrue(ws.check()['ok'], ws.check())
            self.assertEqual(layout.validate(root), [])
            self.assertEqual(vault.validate(root), [])
            self.assertTrue(check_docs(root)['ok'], check_docs(root))
            catalog = Catalog(dict(workspace_root=root))
            self.assertEqual(catalog.list_project_nav(pid)['tasks'][0]['runs'][0]['run_id'], rid)
            roots = catalog._roots_for_binding(ws.project(pid)['binding'])
            self.assertEqual(roots[0]['_boundary'], locations.vault.as_posix())
            self.assertEqual(roots[1]['_boundary'], locations.runtime.as_posix())

    def test_init_rejects_nonempty_external_target_before_any_write(self):
        occupied = self.base / 'existing'
        occupied.mkdir()
        (occupied / 'keep.txt').write_bytes(b'original')
        root = self.base / 'new'
        with self.assertRaises(GovernanceError) as error:
            initialize(root, vault_root=str(occupied))
        self.assertEqual(error.exception.code, 'WORKSPACE_NOT_EMPTY')
        self.assertFalse(root.exists())
        self.assertEqual((occupied / 'keep.txt').read_bytes(), b'original')

    def test_gitignore_treats_runtime_directory_as_literal(self):
        root = self.base / 'ignore'
        initialize(root, runtime_root='[运行] #!目录')
        subprocess.run(['git', 'init', '--quiet', '--template='], cwd=root, check=True, capture_output=True)
        result = subprocess.run(['git', 'check-ignore', '--no-index', '--', '[运行] #!目录/synthetic.txt'], cwd=root, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        with self.assertRaises(GovernanceError):
            loc.configured(root, '正文\nother', 'runtime')

    def test_invalid_configuration_never_falls_back(self):
        for vault_root, runtime_root in (('.', 'runtime'), ('a', 'a/b'), ('a/b', 'a'), ('runtime', 'dmy_vault')):
            with self.assertRaises(GovernanceError):
                loc.configured(self.base, vault_root, runtime_root)
        (self.base / loc.CONFIG_NAME).write_text('{broken', encoding='utf-8')
        with self.assertRaises(GovernanceError):
            Workspace(self.base)

    def test_dangling_config_and_entry_links_are_rejected_before_read(self):
        from dummysys_core._governance import _hardlink
        original = Path.is_symlink
        def linked(path):
            return path.name in (loc.CONFIG_NAME, '.dmy-agents-link') or original(path)
        with patch.object(Path, 'is_symlink', linked):
            with self.assertRaises(GovernanceError) as error:
                loc.load(self.base)
            self.assertEqual(error.exception.code, 'INVALID_CONFIG')
            with self.assertRaises(GovernanceError) as error:
                _hardlink(self.base, self.base / 'rules.md', [None])
            self.assertEqual(error.exception.code, 'PATH_OUTSIDE_ROOT')

    @unittest.skipUnless(os.name == 'nt', 'Windows 路径语义')
    def test_ambiguous_windows_rooted_path_is_rejected(self):
        for value in ('\\正文', 'C:正文'):
            with self.assertRaises(GovernanceError):
                loc.configured(self.base, value, 'runtime')

    def test_reused_workspace_writes_receipts_to_rebound_runtime(self):
        initialize(self.base)
        ws = Workspace(self.base)
        target = self.base / '证据'
        self.assertTrue(target.is_relative_to(self.base))
        (self.base / 'runtime').rename(target)
        (self.base / loc.CONFIG_NAME).write_text(json.dumps(dict(schema_version=1, runtime_root='证据')), encoding='utf-8')
        receipt = ws.mutate('project.create', dict(title='重绑定'), actor='tester', request_id='rebound')
        self.assertTrue((target / 'state/workspace/operations' / receipt['operation_id'] / 'operation.json').is_file())
        self.assertFalse((self.base / 'runtime').exists())

    def test_cross_volume_pointer_retries_interrupted_replace(self):
        from dummysys_core._governance import _hardlink
        initialize(self.base)
        entry = self.base / 'AGENTS.md'
        canonical = loc.vault(self.base) / '10-系统/Codex工作区指令.md'
        entry.unlink()
        with patch('dummysys_core._governance.os.link', side_effect=OSError(errno.EXDEV, 'cross volume')):
            with patch('dummysys_core._governance.os.replace', side_effect=OSError('interrupted')):
                with self.assertRaises(OSError):
                    _hardlink(self.base, canonical, [None])
            _hardlink(self.base, canonical, [None])
        self.assertEqual(entry.read_text(encoding='utf-8'), loc.entry_pointer(self.base, canonical))
        self.assertFalse((self.base / '.dmy-agents-link').exists())

    def test_external_storage_ranking_counts_each_location_once(self):
        from workbench.catalog import Catalog
        from workbench.storage import StorageMonitor
        root = self.base / 'w'
        initialize(root, vault_root='../v', runtime_root='../r')
        ws = Workspace(root)
        pid = ws.mutate('project.create', dict(title='统计'), actor='tester', request_id='storage')['result']['project_id']
        binding = ws.project(pid)['binding']
        resource = loc.resolve(root, binding['resource_root'])
        (resource / 'data.bin').write_bytes(b'x' * 100)
        expected = sum(p.stat().st_size for p in resource.rglob('*') if p.is_file())
        monitor = StorageMonitor(root, projects=Catalog(dict(workspace_root=root)).list_projects)
        monitor._collect_projects()
        result = monitor.snapshot()['ranking']
        row = next(p for p in result['top'] if p['project_id'] == pid)
        self.assertEqual(row['bytes'], expected)
        self.assertFalse(result['incomplete'])
        self.assertGreater(result['workspace_bytes'], result['projects_bytes'])

    def test_cross_volume_entry_is_a_pointer_not_a_second_authority(self):
        with patch('dummysys_core.initialize.os.link', side_effect=OSError(errno.EXDEV, 'cross volume')):
            initialize(self.base)
        self.assertEqual(layout.validate(self.base), [])
        self.assertIn('跨卷导航入口', (self.base / 'AGENTS.md').read_text(encoding='utf-8'))

    def test_prepared_write_recovers_only_with_original_locations(self):
        initialize(self.base, vault_root='正文', runtime_root='证据')
        ws = Workspace(self.base)
        request = 'interrupted'
        def checkpoint(stage, index):
            if stage == 'prepared':
                raise RuntimeError('interruption')
        with self.assertRaises(RuntimeError):
            ws.mutate('project.create', dict(title='恢复'), actor='tester', request_id=request, checkpoint=checkpoint)
        config = self.base / loc.CONFIG_NAME
        original = config.read_bytes()
        config.write_text(json.dumps(dict(schema_version=1, vault_root='另一正文', runtime_root='证据')), encoding='utf-8')
        with self.assertRaises(GovernanceError) as error:
            ws.operations.recover(digest(request.encode()))
        self.assertEqual(error.exception.code, 'INCOMPATIBLE_OPERATION')
        self.assertFalse((self.base / '另一正文').exists())
        config.write_bytes(original)
        result = ws.operations.recover(digest(request.encode()))
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(ws.projects()), 2)
        with self.assertRaises(GovernanceError):
            safe_target(self.base, 'runtime/../../escape')
