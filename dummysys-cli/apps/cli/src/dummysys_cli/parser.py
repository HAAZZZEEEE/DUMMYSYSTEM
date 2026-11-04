"""命令声明、解析与能力自述；命令参考由同一声明生成。"""
import argparse
from dummysys_core import __version__, contracts
from dummysys_core import _records as records
from dummysys_core.operations import GovernanceError

class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise GovernanceError('INVALID_ARGUMENT', message, next_action='使用 --help 查看参数')

    def format_help(self):
        return super().format_help().replace('usage:', '用法：').replace('options:', '选项：').replace('positional arguments:', '位置参数：').replace('show this help message and exit', '显示帮助并退出')


def argument(parser, name, **kwargs):
    return parser.add_argument('--' + name.replace('_', '-'), **kwargs)


def command_path(parser, argv):
    """只识别声明树中的命令词，不解析或记录参数值。"""
    words=['dmy']
    remaining=iter(argv)
    while True:
        sub=next((a for a in parser._actions if isinstance(a,argparse._SubParsersAction)),None)
        if sub is None: return ' '.join(words)
        word=next(remaining,None)
        if word not in sub.choices: return None
        words.append(word);parser=sub.choices[word]


def build_parser():
    parser = Parser(prog='dmy', description=__doc__)
    groups = parser.add_subparsers(dest='group', required=True, parser_class=Parser)
    for name, help_text in [('capabilities', '查询命令契约'), ('doctor', '只读检查本机运行条件'), ('check', '只读检查治理记录')]:
        child = groups.add_parser(name, help=help_text)
        if name == 'capabilities':
            argument(child, 'command', dest='query_command', help='限定命令，例如 task create')
            argument(child, 'action', dest='query_action', help='限定动作，例如 task.create')
        elif name == 'doctor':
            argument(child, 'full', action='store_true', help='汇总治理、文档和本机工作台检查')
        else:
            argument(child, 'docs', action='store_true', help='仅检查当前文档与生成式参考')
    init = groups.add_parser('init', help='在显式 --workspace 空目录创建工作区；非空拒绝')
    argument(init, 'vault_root', default='dmy_vault', help='Vault 位置；相对工作区或绝对路径')
    argument(init, 'runtime_root', default='runtime', help='runtime 位置；相对工作区或绝对路径')
    context = groups.add_parser('context', help='查询 Task 字段与阅读入口，不自动注入会话')
    argument(context, 'task', required=True)
    argument(context, 'section', choices=('all','reading','repositories','summary'), default='all', help='限定返回范围')
    stats = groups.add_parser('stats', help='查询本机命令调用次数（查询本身不计数）')
    argument(stats, 'days', type=int, help='最近 N 个 UTC 自然日，包含今天；省略显示全部')
    diagnose = groups.add_parser('diagnose', help='查询保留期内的诊断尝试与证据入口')
    show = diagnose.add_subparsers(dest='command', required=True, parser_class=Parser).add_parser('show')
    show.add_argument('id')
    governance = groups.add_parser('governance', help='治理资料收拢与受保护回滚')
    changes = governance.add_subparsers(dest='command', required=True, parser_class=Parser)
    for name in ('relocate', 'rollback'):
        child = changes.add_parser(name)
        argument(child, 'project', required=True)
        argument(child, 'reason', required=True)
        argument(child, 'dry_run', action='store_true')
        argument(child, 'if_plan')
        if name == 'relocate':
            argument(child, 'section', choices=('entry', 'system', 'templates'), required=True)
        else:
            argument(child, 'operation', required=True)
    for group, commands in {
        'project': ['list', 'show', 'create', 'update', 'pause', 'resume', 'rename', 'archive', 'unarchive', 'delete', 'undelete', 'sync', 'export', 'import'],
        'task': ['list', 'show', 'create', 'update', 'handoff', 'rename', 'move', 'archive', 'unarchive', 'delete', 'undelete'],
        'run': ['list', 'show', 'create', 'start', 'finish', 'update', 'rename', 'archive', 'unarchive', 'delete', 'undelete'],
        'repo': ['list', 'show', 'register', 'bind', 'link', 'resolve', 'snapshot'],
        'scope': ['check'], 'operation': ['list', 'show', 'recover'],
    }.items():
        base = groups.add_parser(group)
        sub = base.add_subparsers(dest='command', required=True, parser_class=Parser)
        for command in commands:
            p = sub.add_parser(command)
            if command == 'show' or group == 'operation' and command == 'recover':
                p.add_argument('id')
            if group == 'project':
                if command == 'export':
                    argument(p, 'project', required=True)
                    argument(p, 'output', help='新资料包的绝对路径；已存在拒绝覆盖')
                    argument(p, 'include_resource', action='append', default=[], help='额外收入包中的项目资源相对路径')
                    argument(p, 'dry_run', action='store_true', help='仅列出数量、依赖和排除项，不生成包')
                elif command == 'import':
                    argument(p, 'bundle', required=True, help='资料包的绝对路径')
                    argument(p, 'repo_path', dest='repo_paths', action='append', default=[], help='repo_id=本机 checkout 绝对路径')
                    argument(p, 'dry_run', action='store_true')
                    argument(p, 'if_plan')
                elif command == 'sync':
                    argument(p, 'project')
                    argument(p, 'apply', action='store_true')
                elif command == 'create':
                    argument(p, 'title', required=True)
                    argument(p, 'created')
                elif command == 'list':
                    argument(p, 'include_archived', action='store_true')
                    argument(p, 'include_deleted', action='store_true')
                elif command == 'update':
                    argument(p, 'project', required=True)
                    argument(p, 'title')
                    argument(p, 'aliases', help='JSON 数组')
                    argument(p, 'description')
                elif command in ('pause', 'resume'):
                    argument(p, 'project', required=True)
                    argument(p, 'reason', required=True)
                elif command == 'rename':
                    argument(p, 'project', required=True)
                    argument(p, 'title', required=True)
                    argument(p, 'reason', required=True)
                    argument(p, 'dry_run', action='store_true')
                    argument(p, 'if_plan')
                elif command in ('archive', 'unarchive'):
                    argument(p, 'project', required=True)
                    argument(p, 'reason', required=True)
                    argument(p, 'dry_run', action='store_true')
                    argument(p, 'if_plan')
                    if command == 'archive':
                        argument(p, 'allow_unfinished', action='store_true')
                elif command in ('delete', 'undelete'):
                    argument(p, 'project', required=True)
                    argument(p, 'reason', required=True)
            if group == 'task':
                if command in ('list', 'create'):
                    argument(p, 'project')
                if command == 'list':
                    argument(p, 'include_archived', action='store_true')
                    argument(p, 'include_deleted', action='store_true')
                if command == 'create':
                    for name in ('title', 'origin', 'goal'):
                        argument(p, name, required=True)
                    argument(p, 'owner')
                    argument(p, 'requires_acceptance', action='store_true')
                if command in ('update', 'handoff'):
                    argument(p, 'task', required=True)
                    argument(p, 'note', required=True)
                    argument(p, 'status', choices=sorted(records.TASK_STATUSES))
                    argument(p, 'owner', required=command == 'handoff')
                    argument(p, 'accepted', action='store_true')
                    if command == 'handoff':
                        argument(p, 'authorization', help='新负责者接手时记录实际用户授权来源')
                    if command == 'update':
                        argument(p, 'title')
                        argument(p, 'goal')
                if command in ('create', 'update'):
                    argument(p, 'read_path', action='append')
                    argument(p, 'write_path', action='append')
                    if command == 'update':
                        argument(p, 'remote_resources', help='JSON 数组；勿包含凭据')
                        argument(p, 'clear_read_paths', action='store_true')
                        argument(p, 'clear_write_paths', action='store_true')
                if command == 'rename':
                    argument(p, 'task', required=True)
                    argument(p, 'title', required=True)
                    argument(p, 'reason', required=True)
                    argument(p, 'dry_run', action='store_true')
                    argument(p, 'if_plan')
                if command == 'move':
                    argument(p, 'task', required=True)
                    argument(p, 'to_project', required=True)
                    argument(p, 'reason', required=True)
                    argument(p, 'authorization')
                    argument(p, 'dry_run', action='store_true')
                    argument(p, 'if_plan')
                if command in ('archive', 'unarchive'):
                    argument(p, 'task', required=True)
                    argument(p, 'reason', required=True)
                    argument(p, 'dry_run', action='store_true')
                    argument(p, 'if_plan')
                    if command == 'archive':
                        argument(p, 'allow_unfinished', action='store_true')
                if command in ('delete', 'undelete'):
                    argument(p, 'task', required=True)
                    argument(p, 'reason', required=True)
            if group == 'run':
                argument(p, 'task', required=True)
                if command in ('start', 'finish', 'update', 'rename', 'archive', 'unarchive', 'delete', 'undelete'):
                    argument(p, 'run', required=True)
                if command == 'create':
                    for name in ('title', 'host', 'source', 'inputs'):
                        argument(p, name, required=True)
                    argument(p, 'command', dest='execution_command', required=True)
                    argument(p, 'retry_of')
                if command == 'finish':
                    argument(p, 'authorization')
                    argument(p, 'status', required=True, choices=['completed', 'failed', 'cancelled'])
                    argument(p, 'result', required=True)
                    argument(p, 'exit_code', type=int)
                    argument(p, 'evidence', action='append', default=[])
                if command == 'update':
                    # --status 即「更新=切换状态」：planned→running/cancelled，
                    # running→completed/failed/cancelled，终态拒绝；落点校验在 mutate_run。
                    argument(p, 'status', choices=sorted(records.RUN_STATUSES))
                    argument(p, 'host')
                    argument(p, 'source')
                    argument(p, 'inputs')
                    argument(p, 'command', dest='execution_command')
                    argument(p, 'result')
                    argument(p, 'exit_code', type=int)
                    argument(p, 'add_evidence', action='append', default=[])
                if command == 'rename':
                    argument(p, 'title', required=True)
                if command in ('archive', 'unarchive', 'delete', 'undelete'):
                    argument(p, 'reason', required=True)
            if group == 'repo':
                if command in ('register', 'bind', 'link'):
                    argument(p, 'repo', required=True)
                if command == 'register':
                    argument(p, 'title', required=True)
                    argument(p, 'purpose', required=True)
                if command == 'bind':
                    argument(p, 'path', required=True)
                if command in ('link', 'resolve'):
                    target = p.add_mutually_exclusive_group(required=True)
                    argument(target, 'task')
                    argument(target, 'project')
                if command == 'link':
                    argument(p, 'subpath', action='append')
                if command == 'snapshot':
                    argument(p, 'task', required=True)
                    argument(p, 'run', required=True)
                    argument(p, 'checkout', action='append', help='repo_id=绝对路径；可重复')
            if group == 'scope':
                argument(p, 'task', required=True)
                argument(p, 'read_path', action='append', default=[])
                argument(p, 'write_path', action='append', default=[])
    return parser


def capabilities(parser, command=None, action=None):
    commands = []
    def walk(p, prefix):
        sub = next((a for a in p._actions if isinstance(a, argparse._SubParsersAction)), None)
        if sub:
            for key, child in sub.choices.items():
                walk(child, [*prefix, key])
        else:
            commands.append({'command': ' '.join(prefix), 'arguments': [
                {'name': a.dest, 'flags': a.option_strings, 'required': a.required,
                 'choices': list(a.choices) if a.choices else None,
                 'type': 'bool' if isinstance(a,(argparse._StoreTrueAction,argparse._StoreFalseAction)) else getattr(a.type,'__name__','str'),
                 'default': a.default}
                for a in p._actions if a.dest != 'help']})
    walk(parser, ['dmy'])
    if command:
        name = command if command.startswith('dmy ') else 'dmy ' + command
        commands = [c for c in commands if c['command'] == name or c['command'].startswith(name+' ')]
        if not commands: raise GovernanceError('INVALID_ARGUMENT', '命令未匹配', command=command)
    contract = contracts.surface()
    if action:
        if action not in contract['actions']:
            raise GovernanceError('INVALID_ARGUMENT', '动作不存在', action=action)
        contract['actions'] = {action: contract['actions'][action]}
        if not command:
            commands = [c for c in commands if c['command'] == 'dmy ' + action.replace('.', ' ')]
    elif command:
        names={c['command'][4:].replace(' ', '.') for c in commands}
        contract['actions'] = {k:v for k,v in contract['actions'].items() if k in names}
    return dict(version=__version__, platform='Windows', commands=commands,
                global_options=['--workspace','--config','--json','--actor','--request-id','--if-version','--trace-id'],
                write_contract='写请求使用稳定 request_id；更新已有对象携带查询得到的 if_version',
                version_sources={'task':'task show','run':'run show','project':'project show','repo':'repo show'},
                context='可选的当前字段与入口查询；规则仍按 AGENTS 路由阅读',
                recovery='结果未知先查 Operation；恢复仅处理治理记录', **contract)
