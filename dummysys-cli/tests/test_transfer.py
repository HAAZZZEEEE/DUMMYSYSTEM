"""离线资料的往返、冲突拒绝、恶意包与受管恢复。"""
import json
import os
from pathlib import Path
import tempfile
import subprocess
import unittest
from uuid import uuid4
import zipfile

from dummysys_core import locations as loc
from dummysys_core.initialize import initialize
from dummysys_core.workspace import Workspace
from dummysys_core.operations import GovernanceError, digest, native_path
from dummysys_core.transfer import export_project, read_bundle, json_bytes


class TransferTests(unittest.TestCase):
    def setUp(self):
        directory = str(Path(tempfile.gettempdir()).resolve())
        if os.name == 'nt' and not directory.startswith('\\\\?\\'):
            directory = '\\\\?\\' + directory
        temporary = tempfile.TemporaryDirectory(dir=directory)
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        initialize(self.base / 'source')
        target = self.base / '目标 空间'
        target = Path(str(target).removeprefix('\\\\?\\')) if os.name == 'nt' else target
        initialize(target, vault_root='../正文', runtime_root='../运行')
        self.source = Workspace(self.base / 'source')
        self.target = Workspace(target)
        self.pid = self.write(self.source, 'project.create', title='离线交接')['project_id']
        project = self.source.project(self.pid)
        resource = loc.resolve(self.source.root, project['binding']['resource_root'])
        self.resource = resource
        self.tid = self.write(self.source, 'task.create', project=self.pid, title='验证', origin='user', goal='保留资料',
                              read_paths=[str(resource)], write_paths=[str(self.base / 'external')])['task_id']
        self.rid = self.write(self.source, 'run.create', task=self.tid, title='一次执行', host='local', source='fixture', inputs='fixture', command='fixture')['run_id']
        self.write(self.source, 'run.start', task=self.tid, run=self.rid)
        record = Path(self.source.run(self.tid, self.rid)['record'])
        self.evidence = record.parent / '结果.bin'
        self.evidence.write_bytes(b'\x00\xffevidence')
        self.write(self.source, 'run.finish', task=self.tid, run=self.rid, status='completed', exit_code=0, result='已验证', evidence=[str(self.evidence)])
        self.original_run = record.read_bytes()
        (resource / '.env').write_text('SYNTHETIC=never-export')
        (resource / 'extra.txt').write_text('optional')
        self.bundle = self.base / 'project.zip'
        export_project(self.source, self.pid, self.bundle)

    def write(self, ws, action, **params):
        version = ws.run(params['task'], params['run'])['version'] if action in ('run.start', 'run.finish') else None
        return ws.mutate(action, params, actor='tester', request_id=str(uuid4()), if_version=version)['result']

    def preview(self, bundle=None):
        return self.target.plan('project.import', dict(bundle=str(bundle or self.bundle)), actor='tester')

    def apply(self, preview, request=None, checkpoint=None):
        return self.target.mutate('project.import', dict(bundle=str(self.bundle)), actor='tester',
                                  request_id=request or str(uuid4()), if_plan=preview['plan_token'], checkpoint=checkpoint)

    def rewrite(self, change):
        manifest, files, _ = read_bundle(self.bundle)
        change(manifest, files)
        manifest['files'] = {path: dict(size=len(data), sha256=digest(data)) for path, data in files.items()}
        with zipfile.ZipFile(self.bundle, 'w') as archive:
            archive.writestr('manifest.json', json_bytes(manifest))
            for path, data in files.items():
                archive.writestr(path, data)

    def test_roundtrip_stable_ids_external_layout_and_originals(self):
        preview = self.preview()
        self.assertEqual(len(self.target.projects()), 1)  # 初始化的 Playground
        result = self.apply(preview)['result']
        self.assertTrue(self.target.check()['ok'], self.target.check())
        from dummysys_core.validation.layout import validate
        self.assertEqual(validate(self.target.root), [])
        run = self.target.run(self.tid, self.rid)
        evidence = Path(run['evidence'][0])
        self.assertTrue(evidence.is_relative_to(loc.runtime(self.target.root)))
        self.assertEqual(evidence.read_bytes(), self.evidence.read_bytes())
        task = self.target.task(self.tid)
        self.assertEqual(task['binding']['scope']['write_paths'], [])
        self.assertTrue(task['binding']['scope']['read_paths'][0].startswith(str(loc.runtime(self.target.root))))
        report = Path(result['report'])
        originals = list(native_path(report.parent / 'originals').rglob('run.json.bin'))
        self.assertEqual(len(originals), 1)
        self.assertEqual(originals[0].read_bytes(), self.original_run)
        self.assertTrue(any(x['kind'] == 'scope' for x in result['unresolved']))
        self.assertTrue(all(x['exists'] for x in self.target.context(self.tid)['reading'][:4]))
        self.assertFalse((evidence.parents[3] / '.env').exists())
        # 从已导入工作区再次导出，可以继续导入第三个工作区。
        again = self.base / 'again.zip'
        export_project(self.target, self.pid, again)
        initialize(self.base / 'third')
        third = Workspace(self.base / 'third')
        p = third.plan('project.import', dict(bundle=str(again)), actor='tester')
        third.mutate('project.import', dict(bundle=str(again)), actor='tester', request_id='third', if_plan=p['plan_token'])
        self.assertTrue(third.check()['ok'], third.check())
        self.assertTrue(list(native_path(loc.runtime(third.root)).rglob('run.json.bin')))

    def test_idempotent_replay_and_collision_rejection(self):
        preview = self.preview()
        first = self.apply(preview, 'same-intent')
        second = self.apply(preview, 'same-intent')
        self.assertEqual(first['operation_id'], second['operation_id'])
        with self.assertRaises(GovernanceError) as error:
            self.preview()
        self.assertEqual(error.exception.code, 'STATE_CONFLICT')
        self.rewrite(lambda m, f: f.update({'documents/new.md': b'changed'}))
        with self.assertRaises(GovernanceError) as error:
            self.apply(preview, 'same-intent')
        self.assertEqual(error.exception.code, 'REQUEST_CONFLICT')

    def test_target_changes_invalidate_plan(self):
        preview = self.preview()
        self.write(self.target, 'project.create', title='新项目')
        with self.assertRaises(GovernanceError) as error:
            self.apply(preview)
        self.assertEqual(error.exception.code, 'PLAN_CONFLICT')
        self.assertNotIn(self.pid, [p['project_id'] for p in self.target.projects()])

    def test_prepared_interruption_recovers_binary_evidence(self):
        preview = self.preview()
        def crash(stage, index):
            if stage == 'prepared':
                raise RuntimeError('simulated interruption')
        with self.assertRaises(RuntimeError):
            self.apply(preview, 'recovery', crash)
        pending = self.target.operations.pending()
        self.assertEqual(len(pending), 1)
        result = self.target.operations.recover(pending[0]['operation_id'])
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(Path(self.target.run(self.tid, self.rid)['evidence'][0]).read_bytes(), self.evidence.read_bytes())

    def test_reject_traversal_case_collisions_reserved_and_bad_hash(self):
        original = self.bundle.read_bytes()
        for path in ('documents/../escape', 'documents/CON.txt', 'documents/readme.md', 'documents/a./x'):
            self.bundle.write_bytes(original)
            self.rewrite(lambda m, f: f.update({path: b'attack'}))
            with self.assertRaises(GovernanceError):
                self.preview()
        self.bundle.write_bytes(original)
        with zipfile.ZipFile(self.bundle) as archive:
            content = {name: archive.read(name) for name in archive.namelist()}
        content['documents/README.md'] += b'tamper'
        with zipfile.ZipFile(self.bundle, 'w') as archive:
            for name, data in content.items():
                archive.writestr(name, data)
        with self.assertRaises(GovernanceError):
            self.preview()

    def test_invalid_records_abort_before_business_write(self):
        def alter(manifest, files):
            path = next(p for p in files if p.endswith('/task.json'))
            data = json.loads(files[path]); data['project_id'] = str(uuid4())
            files[path] = json_bytes(data)
        self.rewrite(alter)
        with self.assertRaises(GovernanceError):
            self.apply(self.preview())
        self.assertNotIn(self.pid, [p['project_id'] for p in self.target.projects()])
        self.assertEqual(self.target.operations.pending(), [])

    def test_export_selection_and_existing_output_refused(self):
        _, files, _ = read_bundle(self.bundle)
        self.assertFalse(any(p.endswith(('.env', 'extra.txt')) for p in files))
        other = self.base / 'extra.zip'
        export_project(self.source, self.pid, other, include_resource=['extra.txt', '.env'])
        manifest, files, _ = read_bundle(other)
        self.assertIn('resources/extra.txt', files)
        self.assertNotIn('resources/.env', files)
        self.assertTrue(manifest['omitted'])
        before = other.read_bytes()
        with self.assertRaises(GovernanceError):
            export_project(self.source, self.pid, other)
        self.assertEqual(before, other.read_bytes())

    def test_shared_attachment_is_reused_only_if_identical(self):
        docs = Path(self.source.project(self.pid)['document']).parent
        attachments = loc.vault(self.source.root) / '80-附件'
        attachments.mkdir(exist_ok=True)
        (attachments / '图.png').write_bytes(b'image-fixture')
        (docs / '图片.md').write_text('![[80-附件/图.png]]', encoding='utf-8')
        bundle = self.base / 'attachments.zip'
        export_project(self.source, self.pid, bundle)
        self.bundle = bundle
        target = loc.vault(self.target.root) / '80-附件/图.png'
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(b'conflict')
        with self.assertRaises(GovernanceError) as error:
            self.preview()
        self.assertEqual(error.exception.code, 'STATE_CONFLICT')
        target.write_bytes(b'image-fixture')
        self.apply(self.preview())
        self.assertEqual(target.read_bytes(), b'image-fixture')

    def test_foreign_posix_paths_rebound_on_windows(self):
        if os.name != 'nt':
            self.skipTest('此用例在 Windows 核对 POSIX 来源；不声称 macOS 实测')
        source = loc.load(self.source.root)
        def alter(manifest, files):
            manifest['source'] = dict(workspace='/Volumes/example/work', vault_root='/Volumes/example/docs', runtime_root='/Volumes/example/data')
            for path, data in list(files.items()):
                if path.startswith('resources/') and path.endswith('.json'):
                    text = data.decode('utf-8')
                    for old, new in ((str(source.vault), '/Volumes/example/docs'), (str(source.runtime), '/Volumes/example/data')):
                        text = text.replace(json.dumps(old, ensure_ascii=False)[1:-1], new)
                    # 原 Windows 分隔符也随来源规范转换。
                    files[path] = text.replace('\\\\', '/').encode('utf-8')
        self.rewrite(alter)
        self.apply(self.preview())
        run = self.target.run(self.tid, self.rid)
        self.assertEqual(Path(run['evidence'][0]).read_bytes(), self.evidence.read_bytes())

    def test_repo_identity_can_be_rebound_without_copying_checkout(self):
        checkout = self.base / 'checkout'
        checkout.mkdir()
        subprocess.run(['git', 'init', '--quiet', '--template=', str(checkout)], check=True, capture_output=True)
        self.write(self.source, 'repo.register', repo='example', title='示例仓库', purpose='验证绑定')
        self.source.mutate('repo.link', dict(project=self.pid, repo='example', subpaths=['.']), actor='tester',
                           request_id=str(uuid4()), if_version=self.source.project(self.pid)['version'])
        self.bundle = self.base / 'repo.zip'
        export_project(self.source, self.pid, self.bundle)
        preview = self.preview()
        self.assertEqual(preview['plan']['missing_repos'], ['example'])
        params = dict(bundle=str(self.bundle), repo_paths=['example=' + str(checkout)])
        preview = self.target.plan('project.import', params, actor='tester')
        self.target.mutate('project.import', params, actor='tester', request_id=str(uuid4()), if_plan=preview['plan_token'])
        self.assertTrue(self.target.check()['ok'], self.target.check())
        self.assertFalse(any(p.name == '.git' for p in loc.runtime(self.target.root).rglob('*')))

    def test_project_relative_evidence_uses_exported_resolution(self):
        def alter(manifest, files):
            path = next(p for p in files if p.endswith('/run.json'))
            data = json.loads(files[path])
            data['evidence'] = ['extra.txt']
            files[path] = json_bytes(data)
            files['resources/extra.txt'] = b'project-relative'
            manifest['evidence_files'] = [dict(run_id=self.rid, reference='extra.txt', path='resources/extra.txt')]
        self.rewrite(alter)
        self.apply(self.preview())
        self.assertEqual(Path(self.target.run(self.tid, self.rid)['evidence'][0]).read_bytes(), b'project-relative')

    def test_invalid_management_metadata_rejected_in_preview(self):
        original = self.bundle.read_bytes()
        def sidecar(manifest, files):
            path = next(p for p in files if p.endswith('/run.json'))
            files[path.replace('run.json', 'run-management.json')] = b'[]'
        def watermark(manifest, files):
            record = json.loads(files['resources/project.json'])
            record['task_number_high_watermark'] = 'broken'
            files['resources/project.json'] = json_bytes(record)
        for alter in (sidecar, watermark):
            self.bundle.write_bytes(original)
            self.rewrite(alter)
            with self.assertRaises(GovernanceError) as error:
                self.preview()
            self.assertEqual(error.exception.code, 'INVALID_ARGUMENT')

    def test_checkout_environment_cache_and_env_variants_excluded(self):
        checkout = self.resource / 'source-code'
        checkout.mkdir()
        subprocess.run(['git', 'init', '--quiet', '--template=', str(checkout)], check=True, capture_output=True)
        (checkout / 'implementation.py').write_bytes(b'print(1)')
        (self.resource / '.env.production').write_bytes(b'SYNTHETIC=private')
        (self.resource / 'cache').mkdir()
        (self.resource / 'cache/item').write_bytes(b'cache')
        environment = self.resource / 'custom-environment'
        environment.mkdir()
        (environment / 'pyvenv.cfg').write_bytes(b'fixture')
        (environment / 'app').write_bytes(b'environment')
        output = self.base / 'excluded.zip'
        export_project(self.source, self.pid, output, include_resource=['source-code/implementation.py', '.env.production', 'cache', 'custom-environment'])
        manifest, files, _ = read_bundle(output)
        self.assertFalse(any('implementation.py' in p or '.env.production' in p or 'cache/item' in p or 'custom-environment' in p for p in files))
        self.assertGreaterEqual(len(manifest['omitted']), 4)

    def test_dated_wiki_targets_are_not_truncated(self):
        docs = Path(self.source.project(self.pid)['document']).parent
        (docs / '链接.md').write_text('[[30-项目/[20200101]Other/README#heading|label]]', encoding='utf-8')
        output = self.base / 'links.zip'
        export_project(self.source, self.pid, output)
        manifest, _, _ = read_bundle(output)
        links = [x['reference'] for x in manifest['dependencies'] if x['kind'] == 'wiki_link']
        self.assertIn('30-项目/[20200101]Other/README', links)
        self.assertNotIn('30-项目/[20200101', links)

    def test_resource_json_named_like_records_is_not_rewritten(self):
        original = b'{"repositories": [{"path": "example"}], "scope": {}}'
        def alter(manifest, files):
            for name in ('project.json', 'task.json', 'run.json'):
                files['resources/results/' + name] = original
        self.rewrite(alter)
        self.apply(self.preview())
        resource = loc.resolve(self.target.root, self.target.project(self.pid)['binding']['resource_root'])
        for name in ('project.json', 'task.json', 'run.json'):
            self.assertEqual((resource / 'results' / name).read_bytes(), original)

    def test_dry_run_never_recovers_unrelated_pending_write(self):
        def crash(stage, index):
            if stage == 'prepared':
                raise RuntimeError('simulated interruption')
        with self.assertRaises(RuntimeError):
            self.target.mutate('project.create', dict(title='未决项目'), actor='tester', request_id='pending-other', checkpoint=crash)
        before = self.target.projects()
        with self.assertRaises(GovernanceError) as error:
            self.preview()
        self.assertEqual(error.exception.code, 'RECOVERY_REQUIRED')
        self.assertEqual(before, self.target.projects())
        self.assertEqual(len(self.target.operations.pending()), 1)

    def test_repository_snapshot_is_exported_as_historical_evidence(self):
        record = Path(self.source.run(self.tid, self.rid)['record'])
        snapshot = record.parent / 'source-snapshot/0'
        snapshot.mkdir(parents=True)
        (snapshot / 'status.bin').write_bytes(b'historical-state')
        data = json.loads(record.read_bytes())
        data['repositories'] = [dict(repo_id='historical', evidence='source-snapshot/0', path='Z:/example/old-checkout')]
        record.write_bytes(json_bytes(data))
        self.bundle = self.base / 'snapshot.zip'
        export_project(self.source, self.pid, self.bundle)
        _, files, _ = read_bundle(self.bundle)
        self.assertTrue(any(path.endswith('/source-snapshot/0/status.bin') for path in files))
        self.apply(self.preview())
        imported = self.target.run(self.tid, self.rid)
        self.assertEqual(imported['repositories'], data['repositories'])
        self.assertEqual((Path(imported['record']).parent / 'source-snapshot/0/status.bin').read_bytes(), b'historical-state')

    def test_long_names_import_context_and_navigation(self):
        pid = self.write(self.source, 'project.create', title='深层资料项目' * 4)['project_id']
        tid = self.write(self.source, 'task.create', project=pid, title='长名称资料接续' * 4, origin='user', goal='长路径')['task_id']
        # 文件名本身使目标超过 260 字符，不依赖测试器的临时根碰巧足够长。
        rid = self.write(self.source, 'run.create', task=tid, title='完整执行验证记录' * 20, host='local', source='fixture', inputs='fixture', command='fixture')['run_id']
        self.write(self.source, 'run.start', task=tid, run=rid)
        record = Path(self.source.run(tid, rid)['record'])
        evidence = record.parent / 'result.txt'
        evidence.write_bytes(b'long path evidence')
        self.write(self.source, 'run.finish', task=tid, run=rid, status='completed', exit_code=0, result='pass', evidence=[str(evidence)])
        self.bundle = self.base / 'long-names.zip'
        export_project(self.source, pid, self.bundle)
        self.apply(self.preview())
        self.assertTrue(self.target.check()['ok'], self.target.check())
        imported = self.target.run(tid, rid)
        self.assertGreater(len(imported['record']), 260)
        self.assertEqual(native_path(imported['evidence'][0]).read_bytes(), b'long path evidence')
        from workbench.catalog import Catalog
        catalog = Catalog(dict(workspace_root=self.target.root))
        nav = catalog.list_project_nav(pid)
        self.assertEqual(nav['tasks'][0]['runs'][0]['run_id'], rid)
        from workbench.application import Application
        target = dict(nav['tasks'][0]['runs'][0]['target'])
        listing = catalog.list_directory(target)
        self.assertTrue(any(entry['name'] == 'result.txt' for entry in listing['entries']))
        target['relative_path'] += '/result.txt'
        self.assertEqual(Application(catalog, None).read_text(target)['text'], 'long path evidence')
        self.target.mutate('run.rename', dict(task=tid, run=rid, title='导入后接续'), actor='tester', request_id='long-run-rename',
                           if_version=imported['version'])
        self.assertEqual(self.target.run(tid, rid)['management']['display_title'], '导入后接续')


if __name__ == '__main__':
    unittest.main()
