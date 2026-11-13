# 开发主线与维护方式

本仓库是 DUMMYSYS 通用实现后续开发的主线。保留两个来源目录，不在其中建立嵌套 Git 仓库：

- `dummysys/apps/workbench`：浏览器 Workbench。
- `dummysys-cli/apps/cli` 与 `dummysys-cli/packages/core`：CLI、共享记录规则和初始化。
- `docs/`：跨包设计与维护约定。

CLI/core 与 Workbench 通过安装包连接，仍构建三个业务 wheel。既有安装可以继续运行原发行；切换到本仓库构建的包是独立的部署动作。通用修复进入本仓库，个人工作区的配置、知识正文、项目记录、运行证据和缓存留在源码之外。不要将它们复制进仓库以“同步版本”。

## 默认双平台开发

Windows 与 macOS 是同一产品的默认支持平台。无论从哪台机器、哪个源码目录或哪项设计工作流开始，以下要求自动适用，无需用户声明“正在开发哪个平台”或再次提醒解耦。

1. **自行识别环境。** 从实际执行环境确认操作系统、架构、解释器、shell 和已配置路径，再选择本机命令。开发机系统只决定当前能运行什么，不代表需求只服务该平台；不能仅凭分支名、路径示例或上一轮会话推断支持范围。用户明确限定单平台时按该范围实现，仍保持共享契约和另一平台的既有行为。
2. **先判断两平台影响。** 修改前区分共享业务或界面变化与系统能力变化，并检查 Windows、macOS 对应实现、调用方和测试。路径、文件名大小写与 Unicode、文件占用和锁、进程身份、IPC、外部应用打开、快捷键、窗口生命周期、图标和打包是常见差异；只核对本次涉及的能力。
3. **共享行为只实现一次。** Project/Task/Run 语义留在 core；HTTP/JSON 契约、目录与预览逻辑、页面布局及交互流程保持共用。不得按操作系统复制业务模块或整套页面，也不得把本机绝对路径、shell 命令、平台专属导入或系统操作散落到共享业务层。
4. **系统差异进入已有边界。** 后端复用 `ports.py` 的小型能力契约，由 `platform_runtime.py`、`native_host.py` 选择 Windows/macOS 实现；共享生命周期代码只负责流程编排。前端快捷键符号、修饰键和文件管理器名称等系统习惯集中在 `static/platform-ui.js`，实际系统操作仍经后端适配器。新增能力优先扩展最小必要接口；若只有一平台支持，在边界明确能力缺失和界面反馈，不静默套用另一平台实现，也不为将来可能的系统建立庞大抽象。
5. **验证责任覆盖两平台。** 共享行为用平台无关的契约或业务用例验证；有意义的平台差异分别覆盖。运行本机可执行的相关回归，并审查另一平台实现、依赖、导入和打包影响。另一平台无法执行的用例明确列为未验证，说明需要的环境和检查项；跳过、替身、浏览器通过都不能替代原生平台实测。文档等低影响改动按实际风险检查，无需为措辞新增测试。
6. **按双平台影响交付。** 说明共享行为、平台差异、实际运行的验证及未验证项；受影响平台尚未实测时，不宣称双平台验收完成。开发规则随源码版本一起维护，两台机器应使用包含这些规则的仓库版本；本机工作区配置与运行环境各自保留。

平台能力与资料边界见 [双平台与数据互通](platform-and-data.md)，Workbench 的具体检查入口见 [工作台验证](../dummysys/apps/workbench/docs/verification.md)。

## 实现职责

| 位置 | 职责 |
|---|---|
| core/workspace.py 与 contracts.py | 记录查询、受管动作与版本契约 |
| core/operations.py | 写入互斥、事务记录、统一文件 I/O 与恢复 |
| core/locations.py | 工作区根、Vault/runtime 位置和稳定逻辑引用 |
| core/transfer.py | 项目资料包校验、预演、导入导出；不负责安装或传输网络 |
| cli/parser.py、__main__.py | 参数和 JSON 契约，把结构动作交给 core |
| workbench/catalog.py、application.py | 目录读取与浏览功能；结构写入经治理接入层调用 CLI |
| workbench/lifecycle.py、window_host.py | 共用实例编排与窗口认证，不实现平台身份查询或 IPC |
| workbench/platform_runtime.py、native_host.py、ports.py | 平台选择与小型能力契约 |
| workbench/windows*.py、instance_control.py / macos*.py | Windows / macOS 身份、控制通道、应用打开与窗口行为 |
| dummysys-cli/scripts/build.py、install.py | 三包构建与明确工作区内的安装 |

表中 core/cli 路径分别位于 packages/core/src/dummysys_core 和 apps/cli/src/dummysys_cli，Workbench 位于 dummysys/apps/workbench/workbench。核心规则不复制到 UI；文件 I/O 优先复用 operations 中的能力。不要仅因一个文件较长而拆出缺乏独立职责的包装层。

## 验证与推送准备

修改前检查工作树，保留其他工作。提交使用 `feat|fix|refactor|test|build|docs(范围): 中文目的`，只包含本次变化；正文记录通用行为与验证边界，不带私人 Task/Run 身份、本机路径、会话、内网地址或凭据。私人执行来源保存在源码外的工作记录。提交身份与 Git 历史也属于公开前审查范围；当前本地候选使用通用提交身份，发布身份另定。

构建输出与测试环境必须通过绝对路径放在源码外的 runtime。验证实际导入位置，避免测试时由源码工作目录遮蔽 wheel。测试按 [CLI/core](../dummysys-cli/docs/verification.md) 和 [Workbench](../dummysys/apps/workbench/docs/verification.md) 的检查入口进行。

审计已初始化的仓库时，在 `audit_public.py` 参数中加入 `--git-history`。它检查工作树（含隐藏及被忽略的文件）、本地全部 Git 对象（含不可达提交）、提交/标签元数据与配置/引用日志；根 .git 作为元数据处理，嵌套仓库仍禁止。外部拒绝词表和人工复核表只保存在私人 runtime，不收入源码。提交后再扫描最终历史及发行包，不仅检查当前工作树。

本项目围绕作者的工作流演进，不承诺升级迁移、版本兼容或持续稳定性维护。跨平台与数据导入的设计范围见 [双平台与数据互通](platform-and-data.md)。当前已增加 macOS 安装与原生窗口；本次改动后的 Windows 原生行为仍需 Windows 实测；自有代码和随附方法论文档采用 [MIT 许可证](../LICENSE.txt)，公开发布身份另行确定。

当前按单个私仓开发。私仓也不收入工作区资料、凭据、原始日志或本机绑定。可推送的本地状态应满足：提交目的明确、工作树干净、从干净源码完成构建与隔离安装、示例和恢复演练通过、源码/Git/选定制品脱敏检查通过。目标远端与可见性另行核对；不要在通用脚本中自动创建仓库或推送。公开发布前仍须确定公开身份，并完成第三方权利复核。

