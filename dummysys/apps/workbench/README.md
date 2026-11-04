# Workbench

本机浏览器工作台：按 Project/Task/Run 浏览文档、资源和执行结果，提供受管治理入口。配置显式提供 workspace_root、task_root，路径相对配置文件解析。

完整构建安装见候选根 INSTALL.md。使用 `workbench launch --browser --config <配置>` 启动浏览器工作台，`status` 查询状态，`stop` 停止。启动入口通过当前用户管道取得一次性令牌；裸 URL 不建立认证会话。普通浏览无需 Obsidian 或 pywebview；可选应用缺失只限制相应打开/迁移动作。

配置、临时文件与状态放入目标工作区 runtime/workbench；共享规则来自安装的 dummysys-core，写入调用配套 CLI。验证见 [verification.md](docs/verification.md)。
