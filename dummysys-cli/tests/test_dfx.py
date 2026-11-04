"""DFX 公共行为：限定查询、历史兼容、诊断隐私与故障降级。"""
from contextlib import redirect_stdout, redirect_stderr
import io
import ast
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from dummysys_cli import diagnostics, usage
from dummysys_cli.__main__ import main
from dummysys_cli.doccheck import check_docs, command_reference
from dummysys_cli.health import workbench_state, doctor
from dummysys_core.operations import GovernanceError
from dummysys_core.telemetry import capture
from dummysys_core.workspace import Workspace
from dummysys_core import contracts


class DfxTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve(); (self.root/'dmy_vault').mkdir()

    def cli(self,*args):
        output,errors=io.StringIO(),io.StringIO()
        with redirect_stdout(output),redirect_stderr(errors):
            code=main(['--workspace',str(self.root),'--json',*args])
        return code,json.loads(output.getvalue()),errors.getvalue()

    def test_limited_capabilities_and_action(self):
        code,result,_=self.cli('capabilities','--command','task create')
        self.assertEqual(code,0)
        self.assertEqual([c['command'] for c in result['data']['commands']],['dmy task create'])
        self.assertEqual(list(result['data']['actions']),['task.create'])
        self.assertEqual(self.cli('capabilities','--action','run.start')[0],0)
        args=self.cli('capabilities','--command','context')[1]['data']['commands'][0]['arguments']
        section=next(a for a in args if a['name']=='section')
        self.assertEqual((section['type'],section['default']),('str','all'))
        self.assertEqual(self.cli('capabilities','--action','absent')[1]['error']['code'],'INVALID_ARGUMENT')

    def test_scope_check_keeps_existing_command_contract(self):
        doc=self.root/'dmy_vault/30-项目/00-Playground/README.md';doc.parent.mkdir(parents=True)
        doc.write_text('---\ntype: project\ncreated: 2026-10-23\nstatus: active\n---\n# 测试\n',encoding='utf-8')
        ws=Workspace(self.root)
        task=ws.mutate('task.create',dict(title='范围',origin='agent',goal='验证',write_paths=[str(self.root)]),
                       actor='tester',request_id=str(uuid4()))['result']['task_id']
        code,result,_=self.cli('scope','check','--task',task,'--write-path',str(self.root/'target'))
        self.assertEqual(code,0,result)
        self.assertTrue(result['data']['all_within_declared_scope'])

    def test_old_counts_and_result_categories(self):
        usage.record(self.root,'dmy check',0)
        usage.record(self.root,'dmy check',1,duration_ms=60,source='workbench')
        usage.record(self.root,'dmy task update',2,duration_ms=15,error_code='VERSION_CONFLICT')
        summary=usage.summary(self.root)
        check=next(r for r in summary['commands'] if r['command']=='dmy check')
        self.assertEqual((check['calls'],check['unknown_calls'],check['measured_calls']),(2,1,1))
        self.assertEqual(check['outcomes'],{'issues_found':1})
        self.assertEqual(check['latency']['p95_upper_ms'],100)
        self.assertEqual(check['sources'],{'workbench':1})

    def test_known_subcommand_parse_errors_are_counted(self):
        self.assertEqual(self.cli('task','update')[0],2)
        self.assertEqual(self.cli('task','update','--task','t','--note','n','--status','bad')[0],2)
        row=usage.summary(self.root)['commands'][0]
        self.assertEqual((row['command'],row['calls'],row['outcomes']),('dmy task update',2,{'invalid_input':2}))
        self.assertEqual(len(list(diagnostics.directory(self.root).glob('*.json'))),2)
        self.cli('task','absent')
        self.assertEqual(usage.summary(self.root)['total_calls'],2)

    def test_health_invalid_shapes_are_unavailable(self):
        source=self.root/'runtime/workbench/source.json';source.parent.mkdir(parents=True)
        config=self.root/'config.json';state=self.root/'task/state/instance.json';state.parent.mkdir(parents=True)
        source.write_text(json.dumps(dict(config=str(config))))
        config.write_text(json.dumps(dict(workspace_root=str(self.root),task_root=str(self.root/'task'))))
        state.write_text(json.dumps(dict(port=12345,instance_id='i',app_id='a',schema_version=1)))
        for value in (None,[]):
            with patch('dummysys_cli.health.urlopen') as opened:
                opened.return_value.__enter__.return_value=io.StringIO(json.dumps(dict(data=value)))
                self.assertEqual(workbench_state(self.root)['status'],'unavailable')
        with patch('dummysys_cli.health.urlopen') as opened:
            opened.return_value.__enter__.return_value=io.StringIO(json.dumps(dict(schema_version=999,data=dict(schema_version=999,instance_id='i',app_id='a',ready=True))))
            self.assertEqual(workbench_state(self.root)['reason'],'INCOMPATIBLE_SCHEMA')
        with patch('dummysys_cli.health.subprocess.run') as run,patch('dummysys_cli.health.workbench_state',return_value=dict(status='not_running')):
            run.return_value.stdout='[]';run.return_value.returncode=0
            value=doctor(Workspace(self.root),full=True)
        self.assertEqual([c['status'] for c in value['checks'] if c['name'] in ('layout','vault')],['unavailable','unavailable'])
        with patch('dummysys_cli.health.subprocess.run') as run,patch('dummysys_cli.health.workbench_state',return_value=dict(status='not_running')):
            run.return_value.stdout=json.dumps(dict(ok=False,failures=[],unavailable=[dict(check='base_yaml')]))
            run.return_value.returncode=1
            value=doctor(Workspace(self.root),full=True)
        self.assertEqual([c['status'] for c in value['checks'] if c['name'] in ('layout','vault')],['unavailable','unavailable'])

    def test_trace_attempts_privacy_and_readonly_diagnose(self):
        trace=str(uuid4()); secret='private-test-body'
        first=self.cli('--trace-id',trace,'context','--task',secret)[1]
        second=self.cli('--trace-id',trace,'context','--task',secret)[1]
        self.assertNotEqual(first['diagnostic_id'],second['diagnostic_id'])
        before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        code,record,_=self.cli('diagnose','show',first['diagnostic_id'])
        self.assertEqual(code,0); self.assertEqual(len(record['data']['attempts']),2)
        trace_record=self.cli('diagnose','show',trace)[1]['data']
        self.assertEqual(trace_record['matched_by'],'trace_id')
        self.assertEqual(len(trace_record['attempts']),2)
        self.assertEqual(before,{p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.assertNotIn(secret,b''.join(before.values()).decode('utf-8',errors='ignore'))
        self.assertEqual(self.cli('diagnose','show','../../bad')[1]['error']['code'],'INVALID_ARGUMENT')

    def test_diagnostic_failure_keeps_business_exit(self):
        with patch.object(diagnostics,'save',side_effect=OSError('read only')):
            code,result,errors=self.cli('capabilities')
        self.assertEqual(code,0); self.assertIn('data',result); self.assertTrue(errors)

    def test_retention_only_removes_owned_events(self):
        folder=diagnostics.directory(self.root); folder.mkdir(parents=True)
        old=folder/(str(uuid4())+'.json'); old.write_text('{}')
        retained=folder/'user.json';retained.write_text('keep')
        os.utime(old,(1,1))
        diagnostics.prune(folder,now=diagnostics.RETENTION_SECONDS+2)
        self.assertFalse(old.exists());self.assertTrue(retained.exists())

    def test_docs_report_broken_link_and_reference_drift(self):
        (self.root/'.dummysys-docs.json').write_text(json.dumps(dict(schema_version=1,documents=['README.md'],generated_commands='commands.md')))
        (self.root/'README.md').write_text('[入口](absent.md)\n',encoding='utf-8')
        result=check_docs(self.root,roots=[self.root])
        self.assertEqual({r['code'] for r in result['failures']},{'BROKEN_LINK','REFERENCE_STALE'})
        (self.root/'README.md').write_text('[参考](commands.md)\n',encoding='utf-8')
        (self.root/'commands.md').write_text(command_reference(),encoding='utf-8')
        self.assertTrue(check_docs(self.root,roots=[self.root])['ok'])

    def test_docs_literal_bracket_path_and_missing_declaration(self):
        relative='[task 1]/README.md'
        target=self.root/relative;target.parent.mkdir()
        target.write_text('# 当前入口\n',encoding='utf-8')
        manifest=self.root/'.dummysys-docs.json'
        manifest.write_text(json.dumps(dict(schema_version=1,documents=[relative],
            maintenance=[dict(implementation=[relative],documents=[relative],tests=[relative])])),encoding='utf-8')
        result=check_docs(self.root,roots=[self.root])
        self.assertTrue(result['ok'],result)
        self.assertEqual(result['checked_documents'],1)
        manifest.write_text(json.dumps(dict(schema_version=1,documents=['[task 1]/*.md'])),encoding='utf-8')
        self.assertTrue(check_docs(self.root,roots=[self.root])['ok'])
        decoy=self.root/'t/README.md';decoy.parent.mkdir()
        decoy.write_text('# 不能替代缺失的正式入口\n',encoding='utf-8')
        target.unlink()
        result=check_docs(self.root,roots=[self.root])
        self.assertIn('DOC_MISSING',[failure['code'] for failure in result['failures']])
        manifest.write_text(json.dumps(dict(schema_version=1,documents=[relative])),encoding='utf-8')
        self.assertIn('DOC_MISSING',[f['code'] for f in check_docs(self.root,roots=[self.root])['failures']])

    def test_invalid_doc_metadata_reports_structured_failures(self):
        manifest=self.root/'.dummysys-docs.json';manifest.write_text('[]')
        self.assertEqual(check_docs(self.root,roots=[self.root])['failures'][0]['code'],'DOC_CHECK_FAILED')
        mapping=self.root/'runtime/state/workspace/repositories.json';mapping.parent.mkdir(parents=True);mapping.write_text('[]')
        value=check_docs(self.root)
        self.assertIn('MAPPING_INVALID',[r['code'] for r in value['failures']])

    def test_recovery_failures_have_explicit_stop_policy(self):
        for code in ('RECOVERY_CORRUPT','INCOMPATIBLE_OPERATION','LOCK_FAILED'):
            self.assertIn(code,contracts.surface()['error_codes'])
            self.assertEqual(contracts.error_policy(code)['retry'],'stop')
        emitted=set()
        for path in Path(contracts.__file__).parent.glob('*.py'):
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
                if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='GovernanceError' and node.args and isinstance(node.args[0],ast.Constant):
                    emitted.add(node.args[0].value)
        self.assertFalse(emitted-set(contracts.surface()['error_codes']))

    def test_doctor_reports_corrupt_operation_without_crashing(self):
        path=self.root/'runtime/state/workspace/operations'/('a'*64)/'operation.json'
        path.parent.mkdir(parents=True);path.write_text('[]')
        value=doctor(Workspace(self.root))
        self.assertFalse(value['ok'])
        self.assertEqual(next(c['status'] for c in value['checks'] if c['name']=='operations'),'failed')

    def test_unknown_event_schema_is_rejected(self):
        result=self.cli('capabilities')[1]
        path=diagnostics.directory(self.root)/(result['diagnostic_id']+'.json')
        value=json.loads(path.read_text(encoding='utf-8'));value['schema_version']=999
        path.write_text(json.dumps(value))
        self.assertEqual(self.cli('diagnose','show',result['diagnostic_id'])[1]['error']['code'],'INCOMPATIBLE_DIAGNOSTIC')

    def test_doctor_rejects_mismatched_installation(self):
        manifest=self.root/'runtime/state/workspace/cli-install.json';manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps(dict(schema_version=999,version='0.2.0',python='C:/other/python.exe',core_path='C:/other/site-packages')))
        value=doctor(Workspace(self.root))
        self.assertFalse(value['ok'])
        self.assertEqual(next(c['status'] for c in value['checks'] if c['name']=='installation'),'failed')

    def test_doctor_full_marks_missing_checks_unavailable(self):
        code,result,_=self.cli('doctor','--full')
        self.assertEqual(code,1)
        checks=result['data']['checks']
        self.assertTrue(any(c['status']=='unavailable' for c in checks))
        self.assertTrue(result['data']['next_actions'])
        self.assertTrue(all(c.get('next_action') for c in checks if c['status'] not in ('passed','not_running')))
        self.assertIn('lock_wait',diagnostics.show(self.root,result['diagnostic_id'])['event']['stages'])

    def test_run_list_preserves_versions_with_one_lookup(self):
        ws=Workspace(self.root); resources=self.root/'runtime/project_src/p/t'
        for n in range(4):
            p=resources/'runs'/str(n)/'run.json';p.parent.mkdir(parents=True)
            p.write_text(json.dumps(dict(run_id=str(n),status='completed')))
        with patch('dummysys_core.workspace.records.locate_task',return_value=(self.root/'README.md',resources,{})) as locate:
            with capture() as stages:
                rows=ws.runs('t')
            self.assertEqual(locate.call_count,1)
            for row in rows:self.assertEqual(row['version'],ws.version('run',row['run_id'],'t'))
        self.assertEqual(stages['run_scan']['calls'],1)
        duplicate=resources/'runs/duplicate/run.json';duplicate.parent.mkdir()
        duplicate.write_text(json.dumps(dict(run_id='0')))
        with patch('dummysys_core.workspace.records.locate_task',return_value=(self.root/'README.md',resources,{})):
            with self.assertRaisesRegex(GovernanceError,'Run ID 重复'):
                ws.runs('t')
            duplicate.write_text('{}')
            with self.assertRaisesRegex(GovernanceError,'缺少有效身份'):
                ws.runs('t')
