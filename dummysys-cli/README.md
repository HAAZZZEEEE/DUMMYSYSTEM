# CLI 与共享核心

apps/cli 提供 dmy 与 JSON 契约；packages/core 管理 Project/Task/Run、目录投影、幂等操作和恢复。

工作区必须显式指定。`dmy init --workspace <绝对路径> --json` 初始化空目录；命令参数用 `capabilities --command` 查询。安装与构建见候选根 INSTALL.md。写操作使用实际 actor、稳定 request_id 和最新 version，身份不要求来自特定 Agent 工具。

验证入口见 [docs/verification.md](docs/verification.md)，当前命令参考见 [commands.md](apps/cli/docs/commands.md)。

