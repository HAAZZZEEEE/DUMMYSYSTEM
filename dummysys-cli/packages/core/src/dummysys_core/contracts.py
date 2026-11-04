"""供 CLI 与适配器发现的公共治理契约；执行校验仍由 core 完成。"""
from ._actions import ACTIONS, TRANSITIONS, CONTRACT_VERSION, ERROR_CODES
from ._records import TASK_STATUSES, RUN_STATUSES

ORIGINS = ('user', 'agent')
RUN_FINISH_STATUSES = ('completed', 'failed', 'cancelled')

_RECOVERY = {
    'INIT_FAILED': ('stop', '保留初始化现场，核对 init.json；修复原因后选择新的空目录'),
    'WORKSPACE_NOT_EMPTY': ('fix_input', '已有工作区直接接续；首次初始化选择新的空目录'),
    'INVALID_ARGUMENT': ('fix_input', '使用限定 capabilities 或 --help 核对输入'),
    'ACTOR_REQUIRED': ('fix_input', '提供实际执行者的 --actor 或 CODEX_THREAD_ID'),
    'REQUEST_REQUIRED': ('fix_input', '提供稳定 request_id；同一操作重试保持该值与原参数'),
    'VERSION_REQUIRED': ('requery', '使用对应 show 查询当前 version 后再提交'),
    'INVALID_CONFIG': ('fix_input', '核对显式 --config 和工作区绝对路径'),
    'CONFIG_REQUIRED': ('fix_input', '提供 --workspace 或有效的本机 CLI 配置'),
    'INVALID_WORKSPACE': ('fix_input', '核对 --workspace 指向包含 dmy_vault 的工作区'),
    'INVALID_STATE': ('stop', '保留诊断记录，核对工作区记录与运行环境'),
    'INTERNAL_ERROR': ('stop', '使用诊断编号定位内部错误，保留现场'),
    'INCOMPATIBLE_DIAGNOSTIC': ('stop', '保留诊断副本并核对生成该事件的版本'),
    'NOT_FOUND': ('requery', '重新查询对象身份及保留期，不按历史路径猜测'),
    'OWNER_CONFLICT': ('stop', '核对当前 owner 与实际交接授权'),
    'STATE_CONFLICT': ('requery', '检查当前状态与文件占用，核对已完成操作后再决定重试'),
    'SCOPE_VIOLATION': ('stop', '核对 Task 声明范围与实际授权，不绕过范围执行'),
    'PATH_OUTSIDE_ROOT': ('stop', '核对登记根和链接边界，不采用越界路径'),
    'REPOSITORY_SCOPE_CONFLICT': ('stop', '核对 Repo 关联、Task 范围和实际 checkout'),
    'UNSUPPORTED_PLATFORM': ('stop', '使用本机 Windows 的受管运行环境'),
    'LOCK_FAILED': ('stop', '检查本机互斥量与权限环境，保留原请求'),
    'INCOMPATIBLE_OPERATION': ('stop', '使用 Operation 记录对应的原发行核查并恢复'),
    'RECOVERY_CORRUPT': ('stop', '保留损坏现场与 before/after 证据，不继续提交或删除记录'),
    'CAPABILITY_UNAVAILABLE': ('stop', '核对能力声明和所需依赖，完成环境修复后再操作'),
    'VERSION_CONFLICT': ('requery', '重新查询对象，理解差异后用最新 version 发起新请求'),
    'PLAN_CONFLICT': ('replan', '重新 dry-run 核对计划后提交；保持原操作意图'),
    'REQUEST_CONFLICT': ('fix_input', '同一 request_id 恢复原参数；新意图使用新 request_id'),
    'LOCK_BUSY': ('same_request', '稍后使用相同 request_id 和参数重试'),
    'RESULT_UNKNOWN': ('inspect_operation', '按原 request_id 查询 Operation；确认结果后决定是否重试'),
    'RECOVERY_REQUIRED': ('recover', '先 operation show 核对阶段与证据，再按对应版本恢复'),
    'RECOVERY_CONFLICT': ('stop', '保留现场，核对后续修改与 before/after 证据'),
    'INSTALLATION_CHANGED': ('stop', '核对登记发行和实际执行器，处理旧 Operation 后切换版本'),
}


def error_policy(code):
    retry, next_action = _RECOVERY.get(code, ('fix_input', '按错误详情定位对象；使用限定 capabilities 或 --help 检查输入'))
    return dict(retry=retry, next_action=next_action)


def surface():
    return dict(contract_version=CONTRACT_VERSION,
                actions={name: dict(params=dict(s['params']), requires_plan=s['requires_plan'],
                                    version_kind=s['version_kind'], description=s['description'])
                         for name, s in ACTIONS.items()},
                transitions={k: {s: sorted(v) for s,v in states.items()} for k,states in TRANSITIONS.items()},
                statuses=dict(task=sorted(TASK_STATUSES), run=sorted(RUN_STATUSES),
                              run_finish=list(RUN_FINISH_STATUSES), origins=list(ORIGINS)),
                error_codes=sorted(ERROR_CODES | _RECOVERY.keys()),
                error_policies={k: error_policy(k) for k in sorted(ERROR_CODES | _RECOVERY.keys())})
