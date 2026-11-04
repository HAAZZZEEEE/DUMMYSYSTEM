"""治理写入编排：校验幂等、版本与计划，成功后失效读取缓存。"""
from .dmy import DmyError


class GovernanceGateway:
    def __init__(self, preferences, execute, invalidate):
        self.preferences=preferences
        self.execute=execute
        self.invalidate=invalidate

    def actor(self):
        value=(self.preferences().get('actor') or '').strip()
        if not value: raise DmyError('ACTOR_REQUIRED','请先在设置里填写当前负责人')
        return value

    def write(self, argv, params, *, require_version, requires_plan=False):
        if requires_plan:
            plan=params.get('if_plan')
            if not isinstance(plan,str) or not plan:
                raise DmyError('PLAN_CONFLICT','迁移操作须先 dry-run 获取 plan_token，再以 --if-plan 提交')
            argv=[*argv,'--if-plan',plan]
        request=params.get('request_id')
        if not isinstance(request,str) or not request:
            raise DmyError('REQUEST_REQUIRED','缺少 request_id；重试须复用同一个 id')
        version=params.get('if_version')
        if require_version and (not isinstance(version,str) or not version):
            raise DmyError('VERSION_REQUIRED','更新已有对象必须带对应 show 返回的 if_version')
        value=self.execute(argv,actor=self.actor(),request_id=request,if_version=version,mutating=True)
        self.invalidate()
        return value
