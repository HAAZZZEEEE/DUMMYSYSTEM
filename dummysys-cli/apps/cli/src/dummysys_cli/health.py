"""只读分层健康检查；不可执行明确报告，不启动或恢复业务。"""

from dummysys_core import locations as loc
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.request import urlopen

from dummysys_core.locking import supported_platform
from dummysys_core import __version__
from dummysys_core import workspace as core_workspace
from .doccheck import check_docs


def workbench_state(root):
    source=loc.runtime(root) / 'workbench/source.json'
    if not source.is_file(): return dict(status='unavailable',next_action='核对工作台源码入口登记')
    try:
        config_path=Path(json.loads(source.read_text(encoding='utf-8'))['config'])
        config=json.loads(config_path.read_text(encoding='utf-8'))
        configured_root=Path(config['workspace_root'])
        if not configured_root.is_absolute(): configured_root=config_path.parent/configured_root
        if configured_root.resolve() != root.resolve():
            return dict(status='failed',next_action='源码入口绑定了其他工作区，请核对配置')
        task_root=Path(config['task_root'])
        if not task_root.is_absolute(): task_root=config_path.parent/task_root
        state=task_root/'state/instance.json'
        if not state.exists(): return dict(status='not_running',coverage='未发现实例记录')
        saved=json.loads(state.read_text(encoding='utf-8'))
        port=int(saved['port'])
        if not 0 < port < 65536: raise ValueError('端口无效')
        with urlopen(f'http://127.0.0.1:{port}/healthz',timeout=2) as response:
            envelope=json.load(response)
        if not isinstance(envelope,dict): raise ValueError('健康响应必须是对象')
        value=envelope['data']
        if not isinstance(value,dict): raise ValueError('健康响应必须包含 data 对象')
        if envelope.get('schema_version') != 1 or value.get('schema_version') != 1 or saved.get('schema_version') != 1:
            return dict(status='failed',reason='INCOMPATIBLE_SCHEMA',next_action='工作台健康协议版本不匹配，请核对配套实例')
        ok=value.get('instance_id') == saved.get('instance_id') and value.get('app_id') == saved.get('app_id') and value.get('ready') is True
        return dict(status='passed' if ok else 'failed',instance_id=saved.get('instance_id'),
                    started_at=saved.get('started_at'),running_release=value.get('running_release'),
                    identity_coverage='启动代码身份可读' if value.get('running_release') else '实例未提供启动代码身份，需使用配套版本重启后复核',
                    next_action=None if ok else '核对实例与实际进程身份；保留未知进程')
    except (OSError,ValueError,KeyError,TypeError):
        return dict(status='unavailable',next_action='检查实例记录、服务健康与当前配置')


def doctor(ws, full=False):
    pending_error=None
    try:
        pending=ws.operations.pending()
    except (OSError,ValueError) as error:
        pending=[];pending_error=type(error).__name__
    root=ws.root
    checks=[dict(name='platform',status='passed' if supported_platform() else 'failed'),
            dict(name='git',status='passed' if shutil.which('git') else 'failed'),
            dict(name='operations',status='failed' if pending or pending_error else 'passed',
                 pending=[{k:p.get(k) for k in ('operation_id','action','status','source_commit')} for p in pending],
                 error_type=pending_error,
                 next_action='使用原发行 operation show 核对状态与恢复证据' if pending or pending_error else None)]
    registered=None
    actual_core=Path(core_workspace.__file__).resolve().parent
    manifest=loc.runtime(root) / 'state/workspace/cli-install.json'
    if manifest.is_file():
        try:
            value=json.loads(manifest.read_text(encoding='utf-8-sig'))
            if not isinstance(value,dict): raise ValueError('登记记录必须是对象')
            registered={k:value.get(k) for k in ('version','source_commit','python','core_path')}
            matched=(value.get('schema_version')==1 and value.get('version')==__version__
                     and isinstance(value.get('core_path'),str) and isinstance(value.get('python'),str)
                     and (Path(value['core_path'])/'dummysys_core').resolve()==actual_core
                     and Path(value['python']).resolve()==Path(sys.executable).resolve())
            checks.append(dict(name='installation',status='passed' if matched else 'failed',
                               actual_core_path=str(actual_core),
                               next_action=None if matched else '实际运行环境与登记发行不匹配；使用固定入口核对原发行'))
        except (OSError,ValueError):
            checks.append(dict(name='installation',status='failed',next_action='核对 CLI 登记文件'))
    else:
        checks.append(dict(name='installation',status='passed',mode='development-unverified',actual_core_path=str(actual_core)))
    if full:
        try:
            governance=ws.check(); checks.append(dict(name='governance',status='passed' if governance['ok'] else 'failed',result=governance))
        except (OSError,ValueError):
            checks.append(dict(name='governance',status='unavailable',next_action='单独 check 定位无法读取的治理记录'))
        docs=check_docs(root); checks.append(dict(name='docs',status='passed' if docs['ok'] else 'failed',result=docs))
        checks.append(dict(name='workbench',**workbench_state(root)))
        for name in ('layout', 'vault'):
            try:
                p=subprocess.run([sys.executable,'-I','-B','-m','dummysys_core.validation.'+name,'--root',str(root),'--json'],
                                 capture_output=True,text=True,encoding='utf-8',timeout=60,
                                 creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                data=json.loads(p.stdout)
                if not isinstance(data,dict) or p.returncode not in (0,1) or not isinstance(data.get('ok'),bool): raise ValueError('校验输出不合法')
                checks.append(dict(name=name,status='unavailable' if data.get('unavailable') else ('passed' if data['ok'] and p.returncode==0 else 'failed'),result=data))
            except (OSError,ValueError,subprocess.TimeoutExpired):
                checks.append(dict(name=name,status='unavailable',next_action='单独运行校验器检查环境与 JSON 契约'))
    guidance=dict(platform='使用 Windows 或 macOS 的本机受管入口执行',git='核对 Git 安装与 PATH',
                  governance='运行 dmy check --json，逐项核对对象与派生入口；不要自动补造历史事实',
                  docs='运行 dmy check --docs --json，按维护映射修正文档、链接或生成式参考',
                  layout='使用安装环境运行 -m dummysys_core.validation.layout --root <工作区> --json，核对归属后处置',
                  vault='使用安装环境运行 -m dummysys_core.validation.vault --root <工作区> --json，区分旧问题与本次新增')
    for check in checks:
        if check['status'] not in ('passed','not_running') and not check.get('next_action'):
            check['next_action']=guidance.get(check['name'],'单独核对该检查的输入、环境与证据')
    return dict(ok=all(c['status'] in ('passed','not_running') for c in checks),
                checked_at=datetime.now(timezone.utc).isoformat(),full=full,checks=checks,
                tool_version=__version__,python=sys.executable,workspace=str(root),registered=registered,
                locations=loc.load(root).as_dict(),
                pending_operations=checks[2]['pending'],
                next_actions=[dict(check=c['name'],action=c['next_action']) for c in checks if c['status'] not in ('passed','not_running')],
                coverage='本机 CLI、Operation'+('、当前文档、公共校验器与工作台健康；不验证桌面交互或远端' if full else '；完整检查使用 --full'))
