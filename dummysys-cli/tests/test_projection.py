"""同一临时工作区核对 core 与工作台读取投影，保留导航特有语义。"""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from uuid import uuid4

from dummysys_core.workspace import Workspace


class ProjectionTests(unittest.TestCase):
    def test_lifecycle_and_run_management_match(self):
        from workbench.catalog import Catalog
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve()
            doc=root/'dmy_vault/30-项目/00-Playground/README.md';doc.parent.mkdir(parents=True)
            doc.write_text('---\ntype: project\ncreated: 2026-10-23\nstatus: active\n---\n# 测试\n',encoding='utf-8')
            ws=Workspace(root)
            def mutate(action,p,version=None):
                return ws.mutate(action,p,actor='tester',request_id=str(uuid4()),if_version=version)['result']
            task=mutate('task.create',dict(title='投影',origin='agent',goal='核对状态'))['task_id']
            current=ws.task(task);pid=current['project_id'];catalog=Catalog(dict(workspace_root=str(root)))
            for status in ('blocked','active'):
                mutate('task.update',dict(task=task,status=status,note='测试'),ws.task(task)['version'])
                row=catalog.list_project_nav(pid)['tasks'][0]
                self.assertEqual((row['task_id'],row['status']),(task,ws.task(task)['status']))
            run=mutate('run.create',dict(task=task,title='执行',host='local',source='fixture',inputs='fixture',command='fixture'))['run_id']
            mutate('run.start',dict(task=task,run=run),ws.run(task,run)['version'])
            mutate('run.finish',dict(task=task,run=run,status='completed',result='完成',exit_code=0,evidence=['fixture']),ws.run(task,run)['version'])
            mutate('run.archive',dict(task=task,run=run,reason='测试'),ws.run(task,run)['version'])
            core=ws.run(task,run);row=catalog.list_project_nav(pid)['tasks'][0]['runs'][0]
            self.assertEqual(row['run_id'],core['run_id'])
            self.assertEqual(row['execution_status'],core['status'])
            self.assertEqual(row['status'],core['effective_status'])
            self.assertTrue(row['archived'])
            mutate('run.delete',dict(task=task,run=run,reason='测试'),ws.run(task,run)['version'])
            nav=catalog.list_project_nav(pid)
            self.assertEqual(nav['tasks'][0]['runs'],[])
            self.assertEqual(nav['tasks'][0]['deleted_runs'][0]['status'],ws.run(task,run)['effective_status'])
