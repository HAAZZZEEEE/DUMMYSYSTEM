"""临时工作区契约：通过公共 Workspace 与真实子进程验证。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from dummysys_core import _records as records
from dummysys_core.operations import GovernanceError, Operations, digest
from dummysys_core.workspace import Workspace
from dummysys_core.compat import exports
from dummysys_core import _repositories as repos
from dummysys_core.operations import _held


class GovernanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        doc = self.root / 'dmy_vault/30-项目/00-Playground/README.md'
        doc.parent.mkdir(parents=True)
        doc.write_text('---\ntype: project\ncreated: 2026-09-22\nstatus: active\n---\n# 测试\n', encoding='utf-8')
        self.ws = Workspace(self.root)

    def create(self, title='语义验证'):
        return self.ws.mutate('task.create', dict(title=title, origin='agent', goal='验证契约'),
                              actor='tester', request_id=str(uuid4()))['result']['task_id']

    def test_delegated_closeout_keeps_execution_identity_and_requires_authorization(self):
        task = self.create()
        rid = self.ws.mutate('run.create', dict(task=task, title='历史执行', command='fixture',
                            host='local', source='fixture', inputs='fixture'), actor='tester',
                            request_id='delegated-create')['result']['run_id']
        params = dict(task=task, run=rid, status='cancelled', result='用户确认不继续；未执行不记通过',
                      evidence=['fixture-report'])
        version = self.ws.run(task, rid)['version']
        for authorization in (None, '   '):
            with self.assertRaises(ValueError):
                self.ws.mutate('run.finish', dict(params, authorization=authorization), actor='delegate',
                               request_id=str(uuid4()), if_version=version)
        with self.assertRaises(ValueError):
            self.ws.mutate('run.finish', dict(params, authorization='用户当前消息', evidence=[]),
                           actor='delegate', request_id=str(uuid4()), if_version=version)
        self.assertEqual(self.ws.run(task, rid)['version'], version)
        receipt = self.ws.mutate('run.finish', dict(params, authorization='用户当前消息'),
                                 actor='delegate', request_id='delegated-finish', if_version=version)
        self.assertEqual(receipt['actor'], 'delegate')
        closed = self.ws.run(task, rid)
        self.assertEqual(closed['actor'], 'tester')
        self.assertEqual(closed['command'], 'fixture')
        self.assertEqual(closed['closeout']['actor'], 'delegate')
        self.assertEqual(closed['closeout']['authorization'], '用户当前消息')
        self.assertEqual(closed['status'], 'cancelled')
        retry = self.ws.mutate('run.finish', dict(params, authorization='用户当前消息'),
                              actor='delegate', request_id='delegated-finish', if_version=version)
        self.assertEqual(receipt, retry)
        with self.assertRaises(ValueError):
            self.ws.mutate('run.finish', dict(params, authorization='用户当前消息'), actor='delegate',
                           request_id=str(uuid4()), if_version=closed['version'])

    def test_complete_lifecycle_and_readonly_queries(self):
        task = self.create()
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        ctx = self.ws.context(task)
        self.assertEqual(ctx['goal'], '验证契约')
        self.ws.check(); self.ws.sync_preview(); self.ws.projects()
        after = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        r = self.ws.mutate('run.create', dict(task=task, title='执行', command='fixture', host='local', source='fixture', inputs='fixture'), actor='tester', request_id='run-create')['result']['run_id']
        self.ws.mutate('run.start', dict(task=task, run=r), actor='tester', request_id='run-start', if_version=self.ws.run(task, r)['version'])
        with self.assertRaises(ValueError):
            self.ws.mutate('task.update', dict(task=task, status='completed', note='还有Run'), actor='tester', request_id='bad-finish', if_version=self.ws.task(task)['version'])
        self.ws.mutate('run.finish', dict(task=task, run=r, status='completed', result='仅验证契约', exit_code=0, evidence=[str(self.root/'dmy_vault/30-项目/00-Playground/README.md')]), actor='tester', request_id='run-finish', if_version=self.ws.run(task,r)['version'])
        self.ws.mutate('task.update', dict(task=task, status='completed', note='验证完成'), actor='tester', request_id='task-finish', if_version=self.ws.task(task)['version'])
        self.assertTrue(self.ws.check()['ok'], self.ws.check())

    def test_idempotency_versions_and_handoff(self):
        p=dict(title='重复请求', origin='agent', goal='验证')
        first=self.ws.mutate('task.create',p,actor='tester',request_id='same')
        second=self.ws.mutate('task.create',p,actor='tester',request_id='same')
        self.assertEqual(first, second)
        with self.assertRaises(GovernanceError) as error:
            self.ws.mutate('task.create',dict(p,title='另一个'),actor='tester',request_id='same')
        self.assertEqual(error.exception.code,'REQUEST_CONFLICT')
        task=first['result']['task_id']; old=self.ws.task(task)['version']
        self.ws.mutate('task.handoff',dict(task=task,owner='next',note='用户要求接手',authorization='当前用户消息'),actor='next',request_id='handoff',if_version=old)
        with self.assertRaises(GovernanceError) as error:
            self.ws.mutate('task.update',dict(task=task,status='blocked',note='过期'),actor='tester',request_id='stale',if_version=old)
        self.assertEqual(error.exception.code,'VERSION_CONFLICT')
        self.assertEqual(self.ws.task(task)['owner'],'next')

    def test_context_returns_entrypoints_not_historical_execution_payloads(self):
        task=self.create()
        run=self.ws.mutate('run.create',dict(task=task,title='概要',command='lengthy-command',host='local',source='fixture',inputs='large-input-description'),actor='tester',request_id='context-run')['result']['run_id']
        context=self.ws.context(task)
        self.assertNotIn('runs',context['task'])
        self.assertEqual(context['active_runs'][0]['run_id'],run)
        self.assertNotIn('command',context['active_runs'][0])
        self.assertNotIn('inputs',context['active_runs'][0])
        self.assertTrue(context['reading'])

    def worker(self, script):
        return subprocess.Popen([sys.executable,'-c',script,str(self.root)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def finish_worker(self, process):
        stdout,stderr=process.communicate(timeout=45)
        self.assertEqual(process.returncode,0,(stdout+stderr).decode(errors='replace'))
        return stdout

    def test_two_process_number_allocation_and_same_request(self):
        script="from dummysys_core.workspace import Workspace;import sys; w=Workspace(sys.argv[1]);print(w.mutate('task.create',{'title':'parallel','origin':'agent','goal':'test'},actor='worker',request_id=REQUEST)['result']['task_id'])"
        a=self.worker(script.replace('REQUEST',repr('parallel-a')))
        b=self.worker(script.replace('REQUEST',repr('parallel-b')))
        self.finish_worker(a);self.finish_worker(b)
        self.assertEqual(sorted(t['task_number'] for t in self.ws.tasks()),['1','2'])
        a=self.worker(script.replace('REQUEST',repr('duplicate')))
        b=self.worker(script.replace('REQUEST',repr('duplicate')))
        self.assertEqual(self.finish_worker(a),self.finish_worker(b))
        self.assertEqual(len(self.ws.tasks()),3)

    def test_completion_and_run_creation_compete(self):
        task=self.create(); version=self.ws.task(task)['version']
        base="from dummysys_core.workspace import Workspace;import sys;w=Workspace(sys.argv[1]);\ntry:\n ACTION\nexcept ValueError: pass\n"
        a=self.worker(base.replace('ACTION',f"w.mutate('task.update',{{'task':{task!r},'status':'completed','note':'done'}},actor='tester',request_id='finish',if_version={version!r})"))
        b=self.worker(base.replace('ACTION',f"w.mutate('run.create',{{'task':{task!r},'title':'race','command':'test','host':'local','source':'test','inputs':'test'}},actor='tester',request_id='run')"))
        self.finish_worker(a);self.finish_worker(b)
        self.assertFalse(self.ws.task(task)['status']=='completed' and self.ws.runs(task))
        self.assertTrue(self.ws.check()['ok'],self.ws.check())

    def crash(self, request, phase):
        script=f"""import os,sys
from dummysys_core.workspace import Workspace
def stop(phase,index):
 if phase == {phase!r}: os._exit(77)
Workspace(sys.argv[1]).mutate('task.create',{{'title':'crash','origin':'agent','goal':'test'}},actor='tester',request_id={request!r},checkpoint=stop)
"""
        p=self.worker(script); p.communicate(timeout=45); self.assertEqual(p.returncode,77)

    def test_termination_at_each_persistence_phase(self):
        for phase in ('preparing','prepared','file'):
            request='crash-'+phase;self.crash(request,phase)
            result=self.ws.operations.recover(digest(request.encode()))
            self.assertIn(result['status'],('completed','aborted'))
            if result['status']=='aborted':
                self.ws.mutate('task.create',dict(title='crash',origin='agent',goal='test'),actor='tester',request_id=request)
            self.assertTrue(self.ws.check()['ok'],self.ws.check())

    def test_recovery_does_not_overwrite_later_edit(self):
        self.crash('conflict','file')
        record=self.ws.operations.show(digest(b'conflict'))
        entry=next(e for e in record['files'] if (self.root/e['path']).is_file())
        path=self.root/entry['path'];path.write_bytes(b'later edit')
        with self.assertRaises(GovernanceError) as error:
            self.ws.operations.recover(record['operation_id'])
        self.assertEqual(error.exception.code,'RECOVERY_CONFLICT')
        self.assertEqual(path.read_bytes(),b'later edit')

    def test_legacy_and_new_calls_share_core(self):
        legacy=exports('task_records',self.root)
        t=legacy['create_task'](self.root,'00-Playground','旧入口','agent','tester','验证')
        self.assertEqual(self.ws.task(t['task_id'])['owner'],'tester')
        self.ws.mutate('task.update',dict(task=t['task_id'],status='blocked',note='新入口'),actor='tester',request_id='new',if_version=self.ws.task(t['task_id'])['version'])
        legacy['update_task'](self.root,t['task_id'],'tester',status='active',note='旧入口恢复')
        self.assertEqual(self.ws.task(t['task_id'])['status'],'active')
        self.assertTrue(self.ws.check()['ok'])

    def test_dirty_snapshot_and_per_run_worktree(self):
        repo=self.root/'code/中文 空格[仓库]';repo.mkdir(parents=True)
        repos.git(repo,'init');(repo/'a.txt').write_text('original\n')
        repos.git(repo,'add','.');repos.git(repo,'-c','user.name=Test','-c','user.email=test@example.invalid','commit','-m','fixture')
        other=self.root/'worktree';repos.git(repo,'worktree','add','--detach',str(other))
        (other/'a.txt').write_text('changed\n');(other/'new.txt').write_text('new')
        task=self.ws.mutate('task.create',dict(title='源码取证',origin='agent',goal='验证',read_paths=[str(self.root)]),actor='tester',request_id='source-task')['result']['task_id']
        self.ws.mutate('repo.register',dict(repo='demo',title='测试',purpose='验证'),actor='tester',request_id='register')
        self.ws.mutate('repo.bind',dict(repo='demo',path=str(repo)),actor='tester',request_id='bind',if_version=self.ws.version('repo','demo'))
        self.ws.mutate('repo.link',dict(repo='demo',project='00-Playground'),actor='tester',request_id='link',if_version=self.ws.version('project','00-Playground'))
        run=self.ws.mutate('run.create',dict(task=task,title='取证',command='test',host='local',source='demo',inputs='fixture'),actor='tester',request_id='run')['result']['run_id']
        self.ws.mutate('run.start',dict(task=task,run=run),actor='tester',request_id='start',if_version=self.ws.run(task,run)['version'])
        capture=repos.capture
        def unlocked(*args):
            self.assertFalse(_held.get(), '源码采集不能占用治理写锁')
            return capture(*args)
        version=self.ws.run(task,run)['version']
        params=dict(task=task,run=run,checkouts={'demo':str(other)})
        with patch.object(repos,'capture',unlocked):
            receipt=self.ws.mutate('repo.snapshot',params,actor='tester',request_id='snapshot',if_version=version)
        self.assertEqual(receipt,self.ws.mutate('repo.snapshot',params,actor='tester',request_id='snapshot',if_version=version))
        evidence=self.ws.run(task,run)
        self.assertEqual(evidence['repositories'][0]['path'],str(other))
        self.assertTrue(evidence['repositories'][0]['dirty'])
        self.assertEqual(repos.mappings(self.root)['checkouts']['demo']['path'],str(repo))
        self.assertIn(b'+changed', (Path(evidence['record']).parent/'source-snapshot/0/worktree.patch').read_bytes())
        self.assertTrue(self.ws.check()['ok'],self.ws.check())

    def test_operation_version_and_snapshot_integrity(self):
        self.crash('corrupt','prepared')
        identifier=digest(b'corrupt');record=self.ws.operations.show(identifier)
        folder=self.ws.operations.base/identifier
        (folder/record['files'][0]['blob']).write_bytes(b'corrupt')
        with self.assertRaises(GovernanceError) as error:self.ws.operations.recover(identifier)
        self.assertEqual(error.exception.code,'RECOVERY_CORRUPT')
        record['tool_version']='future';(folder/'operation.json').write_text(json.dumps(record))
        with self.assertRaises(GovernanceError) as error:self.ws.operations.recover(identifier)
        self.assertEqual(error.exception.code,'INCOMPATIBLE_OPERATION')


if __name__=='__main__': unittest.main()
