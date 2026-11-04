"""创建空工作区；只允许首次初始化，失败保留现场。"""
from datetime import date
from pathlib import Path
from uuid import uuid4
import json
import os

from .operations import GovernanceError, workspace_lock, save
from . import _records as records
from .layout import governance_paths


def _note(title, body, kind="system", status="active", **properties):
    values = dict(type=kind, title=title, status=status,
                  created=date.today().isoformat(), updated=date.today().isoformat(), **properties)
    front = "\n".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in values.items())
    return f"---\n{front}\n---\n\n# {title}\n\n{body.rstrip()}\n"


def initialize(workspace):
    requested = Path(workspace)
    if not requested.is_absolute():
        raise GovernanceError("INVALID_ARGUMENT", "--workspace 必须为绝对路径")
    if requested.is_symlink() or (hasattr(requested, "is_junction") and requested.is_junction()):
        raise GovernanceError("INVALID_ARGUMENT", "初始化目标不能是目录链接")
    root = requested.resolve()
    with workspace_lock(root):
        if root.exists() and (not root.is_dir() or any(root.iterdir())):
            raise GovernanceError("WORKSPACE_NOT_EMPTY", "初始化目标必须不存在或为空；已保留原内容",
                                  workspace=str(root), next_action="选择新的空目录；已有工作区使用显式 --workspace 接续")
        workspace_id = str(uuid4())
        receipt = root / "runtime/state/workspace/init.json"
        stage = "创建目录"
        try:
            root.mkdir(parents=True, exist_ok=True)
            for relative in ("dmy_vault/00-入口", "dmy_vault/10-系统/仓库", "dmy_vault/20-知识",
                             "dmy_vault/30-项目/00-Playground", "dmy_vault/80-附件",
                             "dmy_vault/90-模板", "dmy_vault/99-收件箱",
                             "runtime/project_src", "runtime/cache", "runtime/logs", "runtime/tmp",
                             "runtime/state/workspace", "runtime/workbench"):
                (root / relative).mkdir(parents=True, exist_ok=True)
            save(receipt, dict(schema_version=1, workspace_id=workspace_id, status="initializing"))
            stage = "生成通用规则与模板"
            rules = governance_paths(root)
            instructions = """# 工作区执行入口

本文件所在 Vault 的上一级是工作区根；命令显式传 --workspace 或使用 runtime/state/cli/bin/dmy.cmd。
读取 00-入口/DUMMYSYS.md 了解用途。选择文件位置时读 10-系统/DUMMYSYS目录与资源治理.md；
创建或接续 Task、执行 Run 时读 10-系统/项目与任务执行规范.md；编辑知识时读 10-系统/Obsidian知识库规范.md。
先读取所属项目 README 与 AGENTS，再按需进入 Task 当前摘要和证据。普通阅读不要求登记 Task。
源码和测试放在关联代码仓库；当前正文放入 Vault；环境、日志、缓存、配置和原始证据放入 runtime。
Project/Task/Run 结构通过 CLI 修改；分析正文按职责编辑。保留稳定身份、已有资料与历史失败事实。
交付前记录实际结果、证据与未验证范围，更新当前正文和直接入口。用户当前指令优先。
"""
            rules["instructions"].write_text(instructions, encoding="utf-8")
            # 现有布局要求根入口与 Vault 权威说明为同一文件。
            os.link(rules["instructions"], root / "AGENTS.md")
            rules["home"].write_text(_note("DUMMYSYS",
                "DUMMYSYS 用 Project/Task/Run 组织 Agent 辅助工作中的文件、工作记录与阅读入口。\n\n"
                "Project 表达持续主题，Task 保存一项工作的目标、范围和当前摘要，Run 保留一次执行的来源、输入、结果和证据。"
                "它们独立于工具会话与当前目录；接续时先读当前摘要，再按需查证据。\n\n"
                "默认项目：[[30-项目/00-Playground/README|Playground]]。\n"
                "规则：[[10-系统/DUMMYSYS目录与资源治理]]、[[10-系统/项目与任务执行规范]]、"
                "[[10-系统/Obsidian知识库规范]]。\n\n"
                "普通记录和浏览可直接使用文件、CLI 与浏览器 Workbench。"
                "改名、移动和归档依赖 Obsidian 更新链接，缺少应用时明确拒绝。", "home"), encoding="utf-8")
            rules["policy"].write_text(_note("目录与资源治理",
                "源码、测试和构建声明进入独立代码仓库；机器绑定通过 repo bind 登记。\n\n"
                "dmy_vault 保存当前可读正文：20-知识、30-项目、80-附件、99-收件箱。"
                "runtime 保存本机配置、缓存、环境和证据；项目资源按 runtime/project_src 配对。\n\n"
                "一个事实维护一个权威正文，其余链接。普通专题不因目录存在而建立 Task/Run。"
                "工作约定、CLI 受管操作和校验共同治理；范围声明不是操作系统权限隔离。"), encoding="utf-8")
            rules["protocol"].write_text(_note("项目与任务执行规范",
                "需要持续执行、交接或验证证据时建立 Task。先查询最新记录与范围，写入携带实际 --actor、稳定 --request-id；"
                "更新时用最新 --if-version。同一写入重试沿用 request_id，新意图生成新 ID。\n\n"
                "Run 先 create，实际执行开始后 start，结束后 finish。completed 必须有 exit-code=0、结果和证据；"
                "失败保留原 Run，重试新建 Run。Run 完成不代表质量验收或公开发布。\n\n"
                "context --task <ID> --section reading --json 提供可选阅读入口，不注入会话、不替代授权。"
                "命令契约通过 capabilities --command 查询。交付更新 Task 当前摘要和直接入口，随后 check。\n\n"
                "改名、移动、归档先 dry-run，再凭 if-plan、if-version 提交；保留 Obsidian 链接更新检查。"), encoding="utf-8")
            rules["knowledge"].write_text(_note("知识库规范",
                "Markdown 使用 type、title、status、created、updated Properties；项目子笔记用 project 链接关联项目 README。\n\n"
                "普通知识区分记录、验证和废弃；资料收录不表示审核通过。附件进入 80-附件，待归类资料进入 99-收件箱。"
                "内部链接以 Vault 根路径定位，模板在 90-模板。使用包内校验器检查目录、Properties 和链接。"), encoding="utf-8")
            for title, body in {
                "知识模板": "## 背景\n\n填写问题和适用范围。\n\n## 结论与证据\n\n区分直接证据、推断与未验证内容。",
                "项目笔记模板": "## 当前摘要\n\n记录背景和当前结论；使用时补充 project 链接和匹配的 type/status。",
            }.items():
                (rules["templates"] / (title + ".md")).write_text(_note(title, body), encoding="utf-8")
            stage = "生成空项目与入口"
            readme = root / "dmy_vault/30-项目/00-Playground/README.md"
            readme.write_text(_note("Playground", "用于尚未归入长期项目的工作。", "project"), encoding="utf-8")
            project_id = records.initialize_project(root, "00-Playground")
            records.refresh(root, "00-Playground")
            manifest = dict(schema_version=1, documents=["AGENTS.md", "dmy_vault/00-入口/*.md", "dmy_vault/10-系统/*.md"])
            save(root / ".dummysys-docs.json", manifest)
            (root / ".gitignore").write_text("runtime/\n", encoding="utf-8")
            (root / "runtime/README.md").write_text("# 本机运行资料\n\n环境、配置、缓存、日志与项目执行证据存于此目录。\n", encoding="utf-8")
            stage = "生成目标工作区配置"
            config = root / "runtime/state/workspace/cli.json"
            save(config, dict(schema_version=1, workspace=str(root)))
            wb_config = root / "runtime/workbench/config.json"
            save(wb_config, dict(schema_version=1, workspace_root=str(root),
                                task_root=str(root / "runtime/workbench"), port=0, apps={}))
            save(root / "runtime/workbench/source.json", dict(schema_version=1, mode="wheel", config=str(wb_config)))
            result = dict(schema_version=1, workspace_id=workspace_id, status="completed",
                          workspace=str(root), project_id=project_id, config=str(config), workbench_config=str(wb_config))
            save(receipt, result)
            return result
        except Exception as error:
            # 不清理目标目录：保留已完成文件和失败位置，供用户核对。
            details = dict(schema_version=1, workspace_id=workspace_id, status="failed", stage=stage,
                           error_type=type(error).__name__, workspace=str(root),
                           next_action="保留此目录核对 runtime/state/workspace/init.json；修复原因后选择另一个空目录初始化，不在非空目录重试")
            try:
                save(receipt, details)
            except OSError:
                pass
            raise GovernanceError("INIT_FAILED", "初始化失败，现场已保留", **details) from error

