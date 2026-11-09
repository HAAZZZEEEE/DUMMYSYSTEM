# CLI 与共享核心

apps/cli 提供 dmy 与 JSON 契约；packages/core 管理 Project/Task/Run、目录投影、幂等操作和恢复。

工作区必须显式指定。`dmy init --workspace <绝对路径> --json` 初始化空目录；命令参数用 `capabilities --command` 查询。安装与构建见候选根 INSTALL.md。写操作使用实际 actor、稳定 request_id 和最新 version，身份不要求来自特定 Agent 工具。

验证入口见 [docs/verification.md](docs/verification.md)，当前命令参考见 [commands.md](apps/cli/docs/commands.md)。

文档检查可在目标 runtime 的 `state/workspace/doccheck.json` 显式配置源码根：`{"schema_version":1,"roots":["repos/dummysys","repos/dummysys-cli"]}`。工作区自身始终检查，roots 为追加检查的目录，相对路径以工作区为基准，支持绝对路径与空数组（只检查工作区）。每个根须有 `.dummysys-docs.json`；缺失会报告不可用，配置错误会失败，不回退到旧仓。未提供此文件时保留既有仓库映射行为。此配置属于本机 runtime，不随源码发布；Python 调用显式传入 roots 时优先使用该参数。

