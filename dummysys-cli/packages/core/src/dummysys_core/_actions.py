"""动作契约：集中参数类型、状态前置条件和计划要求。"""
from __future__ import annotations

# 参数类型声明
STR = 'str'
INT = 'int'
BOOL = 'bool'
LIST = 'list'
OPT_STR = 'opt_str'

# 状态转换表
PROJECT_TRANSITIONS = {
    'active': {'paused', 'archived', 'deleted'},
    'paused': {'active', 'archived', 'deleted'},
    'archived': {'unarchived', 'deleted'},
    'deleted': {'undeleted'},
}

TASK_TRANSITIONS = {
    'active': {'blocked', 'awaiting_acceptance', 'completed', 'cancelled', 'archived', 'deleted'},
    'blocked': {'active', 'cancelled', 'deleted'},
    'awaiting_acceptance': {'active', 'completed', 'cancelled', 'deleted'},
    'completed': {'archived', 'deleted'},
    'cancelled': {'archived', 'deleted'},
}

RUN_TRANSITIONS = {
    'planned': {'running', 'cancelled', 'updated', 'renamed', 'archived', 'deleted'},
    'running': {'running', 'completed', 'failed', 'cancelled', 'updated', 'deleted'},
    'completed': {'updated_terminal_denied', 'renamed', 'archived', 'deleted'},
    'failed': {'updated_terminal_denied', 'renamed', 'archived', 'deleted'},
    'cancelled': {'updated_terminal_denied', 'renamed', 'archived', 'deleted'},
}

# 动作定义：action_name -> {params, requires_plan, version_kind, description}
ACTIONS = {
    'project.import': {
        'params': {'bundle': STR, 'repo_paths': LIST},
        'requires_plan': True, 'version_kind': None,
        'description': '校验离线项目资料包，预演后受管导入；保留稳定身份并拒绝覆盖',
    },
    'governance.relocate': {
        'params': {'project': STR, 'section': STR, 'reason': STR},
        'requires_plan': True, 'version_kind': 'project',
        'description': '将一个旧治理分区收入项目；保持正文、身份和执行证据',
    },
    'governance.rollback': {
        'params': {'project': STR, 'operation': STR, 'reason': STR},
        'requires_plan': True, 'version_kind': 'project',
        'description': '核对无后续修改后回滚一个治理分区迁移；须按逆序执行',
    },
    'project.create': {
        'params': {'title': STR, 'created': OPT_STR},
        'requires_plan': False, 'version_kind': None,
        'description': '创建完整项目（文档 + 资源配对）',
    },
    'project.update': {
        'params': {'project': STR, 'title': OPT_STR, 'aliases': OPT_STR, 'description': OPT_STR},
        'requires_plan': False, 'version_kind': 'project',
        'description': '更新展示标题、aliases 和受管说明段，不移动目录',
    },
    'project.pause': {
        'params': {'project': STR, 'reason': STR},
        'requires_plan': False, 'version_kind': 'project',
        'description': '暂停项目；拒绝新建 Task/Run',
    },
    'project.resume': {
        'params': {'project': STR, 'reason': STR},
        'requires_plan': False, 'version_kind': 'project',
        'description': '恢复项目为 active',
    },
    'project.rename': {
        'params': {'project': STR, 'title': STR, 'reason': STR},
        'requires_plan': True, 'version_kind': 'project',
        'description': '同步展示标题及目录标题部分；保留 UUID、created',
    },
    'project.archive': {
        'params': {'project': STR, 'reason': STR, 'allow_unfinished': BOOL},
        'requires_plan': True, 'version_kind': 'project',
        'description': '归档项目并保留Task状态；未完成Task需allow_unfinished确认，禁止未结束Run',
    },
    'project.unarchive': {
        'params': {'project': STR, 'reason': STR},
        'requires_plan': True, 'version_kind': 'project',
        'description': '取消项目归档，恢复归档前 active/paused 状态',
    },
    'project.delete': {
        'params': {'project': STR, 'reason': STR},
        'requires_plan': False, 'version_kind': 'project',
        'description': '逻辑删除；不搬目录、不删除文件',
    },
    'project.undelete': {
        'params': {'project': STR, 'reason': STR},
        'requires_plan': False, 'version_kind': 'project',
        'description': '恢复逻辑删除',
    },
    'task.create': {
        'params': {'project': OPT_STR, 'title': STR, 'origin': STR, 'goal': STR,
                    'owner': OPT_STR, 'requires_acceptance': BOOL,
                    'read_paths': LIST, 'write_paths': LIST},
        'requires_plan': False, 'version_kind': None,
        'description': '创建 Task',
    },
    'task.update': {
        'params': {'task': STR, 'status': OPT_STR, 'owner': OPT_STR, 'note': STR,
                    'accepted': BOOL, 'title': OPT_STR, 'goal': OPT_STR,
                    'read_paths': LIST, 'write_paths': LIST, 'remote_resources': OPT_STR},
        'requires_plan': False, 'version_kind': 'task',
        'description': '更新 Task 状态、目标、标题（仅展示）',
    },
    'task.handoff': {
        'params': {'task': STR, 'owner': STR, 'note': STR, 'authorization': OPT_STR},
        'requires_plan': False, 'version_kind': 'task',
        'description': '交接负责者',
    },
    'task.rename': {
        'params': {'task': STR, 'title': STR, 'reason': STR},
        'requires_plan': True, 'version_kind': 'task',
        'description': '配对修改目录和标题；保留 UUID、编号、created',
    },
    'task.move': {
        'params': {'task': STR, 'to_project': STR, 'reason': STR, 'authorization': OPT_STR},
        'requires_plan': True, 'version_kind': 'task',
        'description': '跨项目配对移动、分配目标编号',
    },
    'task.archive': {
        'params': {'task': STR, 'reason': STR, 'allow_unfinished': BOOL},
        'requires_plan': True, 'version_kind': 'task',
        'description': '保留Task状态归档；未完成需allow_unfinished确认，禁止未结束Run',
    },
    'task.unarchive': {
        'params': {'task': STR, 'reason': STR},
        'requires_plan': True, 'version_kind': 'task',
        'description': '取消 Task 归档，保留原业务状态和负责者',
    },
    'task.delete': {
        'params': {'task': STR, 'reason': STR},
        'requires_plan': False, 'version_kind': 'task',
        'description': '逻辑删除 Task；不搬目录',
    },
    'task.undelete': {
        'params': {'task': STR, 'reason': STR},
        'requires_plan': False, 'version_kind': 'task',
        'description': '恢复逻辑删除 Task',
    },
    'run.create': {
        'params': {'task': STR, 'title': STR, 'command': STR, 'host': STR,
                    'source': STR, 'inputs': STR, 'retry_of': OPT_STR},
        'requires_plan': False, 'version_kind': None,
        'description': '创建 planned Run',
    },
    'run.start': {
        'params': {'task': STR, 'run': STR},
        'requires_plan': False, 'version_kind': 'run',
        'description': 'planned→running',
    },
    'run.finish': {
        'params': {'task': STR, 'run': STR, 'status': STR, 'result': STR,
                    'exit_code': INT, 'evidence': LIST, 'authorization': OPT_STR},
        'requires_plan': False, 'version_kind': 'run',
        'description': '结束 Run（completed/failed/cancelled）',
    },
    'run.update': {
        'params': {'task': STR, 'run': STR, 'status': OPT_STR, 'host': OPT_STR, 'source': OPT_STR,
                    'inputs': OPT_STR, 'command': OPT_STR, 'result': OPT_STR,
                    'exit_code': INT, 'add_evidence': LIST},
        'requires_plan': False, 'version_kind': 'run',
        'description': '切换 Run 状态并补写进展与证据；planned 可改输入，running 仅补写结果，terminal 拒绝执行事实修改',
    },
    'run.rename': {
        'params': {'task': STR, 'run': STR, 'title': STR},
        'requires_plan': False, 'version_kind': 'run',
        'description': '仅改展示名称（sidecar display_title）',
    },
    'run.archive': {
        'params': {'task': STR, 'run': STR, 'reason': STR},
        'requires_plan': False, 'version_kind': 'run',
        'description': '归档 terminal Run（sidecar）',
    },
    'run.unarchive': {
        'params': {'task': STR, 'run': STR, 'reason': STR},
        'requires_plan': False, 'version_kind': 'run',
        'description': '恢复归档 Run',
    },
    'run.delete': {
        'params': {'task': STR, 'run': STR, 'reason': STR},
        'requires_plan': False, 'version_kind': 'run',
        'description': '逻辑删除 Run（sidecar）',
    },
    'run.undelete': {
        'params': {'task': STR, 'run': STR, 'reason': STR},
        'requires_plan': False, 'version_kind': 'run',
        'description': '恢复逻辑删除 Run',
    },
    'operation.recover': {
        'params': {'id': STR, 'mode': OPT_STR},
        'requires_plan': False, 'version_kind': None,
        'description': '恢复未决 Operation；--mode rollback 回退已记录步骤',
    },
}

# 统一错误码
ERROR_CODES = frozenset({
    'INVALID_ARGUMENT', 'NOT_FOUND', 'OWNER_CONFLICT', 'VERSION_CONFLICT',
    'PLAN_CONFLICT', 'REQUEST_CONFLICT', 'STATE_CONFLICT',
    'REPOSITORY_SCOPE_CONFLICT', 'PATH_OUTSIDE_ROOT',
    'RECOVERY_REQUIRED', 'RECOVERY_CONFLICT',
    'INSTALLATION_CHANGED', 'CAPABILITY_UNAVAILABLE',
})

# 能力自述的格式版本：界面据此判断拿到的是新介绍还是老介绍。
CONTRACT_VERSION = 2

TRANSITIONS = {'project': PROJECT_TRANSITIONS, 'task': TASK_TRANSITIONS, 'run': RUN_TRANSITIONS}

# 动作对状态的落点，用于从转换表反推「此刻能发起哪些动作」。转换表里的
# updated/renamed/archived/deleted/unarchived/undeleted 是动作落点标记；
# updated_terminal_denied 表示终态拒绝补写。
_ACTION_TARGETS = {
    'update': ('updated',),
    'rename': ('renamed',),
    'archive': ('archived',),
    'unarchive': ('unarchived',),
    'delete': ('deleted',),
    'undelete': ('undeleted',),
    'start': ('running',),
    'finish': ('completed', 'failed', 'cancelled'),
    'pause': ('paused',),
    'resume': ('active',),
    'handoff': (),   # 不改状态
    'move': (),      # 不改状态
}


def get_action(name):
    return ACTIONS.get(name)


def requires_plan(name):
    action = ACTIONS.get(name)
    return action['requires_plan'] if action else False


def allowed_actions(kind, status, *, deleted=False, archived=False):
    """提示性清单：该对象此刻可发起的动作名。

    从 *_TRANSITIONS 推导，不含 create/show 等非状态动作；写入仍由执行器
    重验全部前置条件，本清单只用于界面点亮/置灰。
    """
    if deleted:
        return sorted([f'{kind}.undelete'])
    table = TRANSITIONS.get(kind) or {}
    reachable = set(table.get(status, ()))
    out = []
    for name, targets in _ACTION_TARGETS.items():
        action = f'{kind}.{name}'
        if action not in ACTIONS:
            continue
        if name in ('handoff', 'move'):
            if kind == 'task' and not archived:
                out.append(action)
            continue
        if name == 'undelete':
            continue
        if name == 'unarchive':
            if archived:
                out.append(action)
            continue
        if name == 'archive' and archived:
            continue
        # update/rename 不改业务状态，不受转换表落点约束；Run 终态显式拒绝补写。
        if name in ('update', 'rename'):
            if name == 'update' and 'updated_terminal_denied' in reachable:
                continue
            out.append(action)
            continue
        if not targets or any(t in reachable for t in targets):
            out.append(action)
    return sorted(out)
