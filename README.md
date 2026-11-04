# DUMMYSYS

DUMMYSYS 是面向 Agent 辅助工作的本地文件组织与工作记录工具。它用 Project、Task、Run 明确文件归属、工作目标与执行来源，让人和不同 Agent 工具在切换会话、代码仓库或机器后，沿清晰的阅读边界恢复上下文。

它通过工作约定、CLI 受管操作和校验约束工作资料。Project 是持续主题，Task 是一项工作的当前记录，Run 是一次执行的证据；这些身份独立于工具会话和当前工作目录。源码仓库通过本机绑定关联，运行环境和原始证据留在工作区 runtime。

本候选保留两个来源目录：`dummysys/apps/workbench` 是浏览器 Workbench；`dummysys-cli/apps/cli` 与 `dummysys-cli/packages/core` 是 CLI 和共享规则。默认提供完整工作流，文件和 CLI/JSON 可独立使用。

## 使用与维护边界

这个实现从作者的个人工作流长出，后续迭代继续服务该工作流。计划分享方法论与代码，不承诺面向使用者的升级迁移、版本兼容或稳定性维护；使用者负责自己的部署、备份和数据。

当前为第一轮脱敏与独立运行候选，Windows 浏览器工作流是本轮验证目标。项目许可证尚未确定，尚未公开发布；第三方资源声明见 [THIRD_PARTY.md](THIRD_PARTY.md)。macOS、现用资料迁移、跨设备同步、最终仓库组织后续处理。

安装与验证见 [INSTALL.md](INSTALL.md)。初始化生成独立工作区，候选代码目录只保存源码、测试、构建声明和通用说明。

