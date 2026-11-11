# DUMMYSYS

DUMMYSYS 是面向 Agent 辅助工作的本地文件组织与工作记录工具。它用 Project、Task、Run 明确文件归属、工作目标与执行来源，让人和不同 Agent 工具在切换会话、代码仓库或机器后，沿清晰的阅读边界恢复上下文。

它通过工作约定、CLI 受管操作和校验约束工作资料。Project 是持续主题，Task 是一项工作的当前记录，Run 是一次执行的证据；这些身份独立于工具会话和当前工作目录。源码仓库通过本机绑定关联，运行环境和原始证据留在工作区 runtime。

本候选保留两个来源目录：`dummysys/apps/workbench` 是浏览器 Workbench；`dummysys-cli/apps/cli` 与 `dummysys-cli/packages/core` 是 CLI 和共享规则。默认提供完整工作流，文件和 CLI/JSON 可独立使用。

两个目录由一个 Git 仓库管理，统一提交和验证，构建三个安装包；没有子仓库或 submodule。个人配置与资料留在外部工作区。见 [开发主线与维护方式](docs/development.md)。

## 使用与维护边界

这个实现从作者的个人工作流长出，后续迭代继续服务该工作流。计划分享方法论与代码，不承诺面向使用者的升级迁移、版本兼容或稳定性维护；使用者负责自己的部署、备份和数据。

当前按私有仓库开发，代码与示例保持脱敏；项目许可证尚未确定，尚未公开发布。Windows 是参考实现，已具备本机 CLI、浏览器 Workbench 与项目离线导入导出；macOS 独立运行和跨平台互通仍待实现或验证。两机通信、自动同步与同时写入不在当前范围。第三方声明见 [THIRD_PARTY.md](THIRD_PARTY.md)，平台范围见 [双平台与数据互通](docs/platform-and-data.md)。

## 从这里开始

1. [工作方法](docs/workflow.md)：文件归属、Project/Task/Run 与跨会话接续。
2. [安装](INSTALL.md)：从源码构建三个包，在独立工作区安装。
3. [入门演练](docs/quickstart.md)：用合成资料完成创建、执行、记录与阅读。
4. [备份与恢复](docs/backup-restore.md)：保留哪些资料、如何验证项目恢复、哪些场景不能自动恢复。

源码目录只保存源码、测试、构建声明与通用说明；演练结果、日志和安装环境都在源码之外。

目录位置配置见 [存储位置](docs/storage.md)；资料包的过滤、限制、身份与冲突规则见 [导入导出](docs/transfer.md)。恢复和迁移前先做隔离演练，核对外部依赖与证据。

