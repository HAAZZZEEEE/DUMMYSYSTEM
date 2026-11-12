# 开发主线与维护方式

本仓库是 DUMMYSYS 通用实现后续开发的主线。保留两个来源目录，不在其中建立嵌套 Git 仓库：

- `dummysys/apps/workbench`：浏览器 Workbench。
- `dummysys-cli/apps/cli` 与 `dummysys-cli/packages/core`：CLI、共享记录规则和初始化。
- `docs/`：跨包设计与维护约定。

CLI/core 与 Workbench 通过安装包连接，仍构建三个业务 wheel。既有安装可以继续运行原发行；切换到本仓库构建的包是独立的部署动作。通用修复进入本仓库，个人工作区的配置、知识正文、项目记录、运行证据和缓存留在源码之外。不要将它们复制进仓库以“同步版本”。

## 实现职责

| 位置 | 职责 |
|---|---|
| core/workspace.py 与 contracts.py | 记录查询、受管动作与版本契约 |
| core/operations.py | 写入互斥、事务记录、统一文件 I/O 与恢复 |
| core/locations.py | 工作区根、Vault/runtime 位置和稳定逻辑引用 |
| core/transfer.py | 项目资料包校验、预演、导入导出；不负责安装或传输网络 |
| cli/parser.py、__main__.py | 参数和 JSON 契约，把结构动作交给 core |
| workbench/catalog.py、application.py | 目录读取与浏览功能；结构写入经治理接入层调用 CLI |
| workbench/lifecycle.py、instance_control.py、windows.py | 当前 Windows 的实例管理、本机控制和外部应用打开 |
| dummysys-cli/scripts/build.py、install.py | 三包构建与明确工作区内的安装 |

表中 core/cli 路径分别位于 packages/core/src/dummysys_core 和 apps/cli/src/dummysys_cli，Workbench 位于 dummysys/apps/workbench/workbench。核心规则不复制到 UI；文件 I/O 优先复用 operations 中的能力。不要仅因一个文件较长而拆出缺乏独立职责的包装层。

## 验证与推送准备

修改前检查工作树，保留其他工作。提交使用 `feat|fix|refactor|test|build|docs(范围): 中文目的`，只包含本次变化；正文记录通用行为与验证边界，不带私人 Task/Run 身份、本机路径、会话、内网地址或凭据。私人执行来源保存在源码外的工作记录。提交身份与 Git 历史也属于公开前审查范围；当前本地候选使用通用提交身份，发布身份另定。

构建输出与测试环境必须通过绝对路径放在源码外的 runtime。验证实际导入位置，避免测试时由源码工作目录遮蔽 wheel。测试按 [CLI/core](../dummysys-cli/docs/verification.md) 和 [Workbench](../dummysys/apps/workbench/docs/verification.md) 的检查入口进行。

审计已初始化的仓库时，在 `audit_public.py` 参数中加入 `--git-history`。它检查工作树（含隐藏及被忽略的文件）、本地全部 Git 对象（含不可达提交）、提交/标签元数据与配置/引用日志；根 .git 作为元数据处理，嵌套仓库仍禁止。外部拒绝词表和人工复核表只保存在私人 runtime，不收入源码。提交后再扫描最终历史及发行包，不仅检查当前工作树。

本项目围绕作者的工作流演进，不承诺升级迁移、版本兼容或持续稳定性维护。跨平台与数据导入的设计范围见 [双平台与数据互通](platform-and-data.md)。当前只交付已经验证的 Windows 候选；自有代码和随附方法论文档采用 [MIT 许可证](../LICENSE.txt)，公开发布身份另行确定。

当前按单个私仓开发。私仓也不收入工作区资料、凭据、原始日志或本机绑定。可推送的本地状态应满足：提交目的明确、工作树干净、从干净源码完成构建与隔离安装、示例和恢复演练通过、源码/Git/选定制品脱敏检查通过。目标远端与可见性另行核对；不要在通用脚本中自动创建仓库或推送。公开发布前仍须确定公开身份，并完成第三方权利复核。

