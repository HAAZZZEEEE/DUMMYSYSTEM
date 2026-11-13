# Workbench

开发与 UI 设计默认同时面向 Windows/macOS。开始修改先读 [实现入口](AGENTS.md) 和 [默认双平台开发规则](../../../docs/development.md#默认双平台开发)；环境识别、共享逻辑与平台适配由开发者主动处理，无需用户逐次指定。

<img src="workbench/static/icons/workbench-logo.svg" width="96" height="96" alt="Workbench 图标">

工作台侧栏使用透明底的 `workbench-logo.svg`，浏览器标签页使用白底的 `app-icon.svg`。两份 SVG 都在 `workbench/static/icons/`。Windows 原生窗口使用从同一 SVG 生成的 `app-icon.ico`。更新 SVG 时同步导出 256 × 256 的白底 PNG，再用 Pillow 生成含 16、24、32、48、64、128、256 像素图层的 ICO。

本机浏览器工作台：按 Project/Task/Run 浏览文档、资源和执行结果，提供受管治理入口。配置显式提供 workspace_root、task_root，路径相对配置文件解析。

完整构建安装见候选根 INSTALL.md。使用 `workbench launch --browser --config <配置>` 启动浏览器工作台，`status` 查询状态，`stop` 停止。启动入口通过当前用户管道取得一次性令牌；裸 URL 不建立认证会话。普通浏览无需 Obsidian 或 pywebview；可选应用缺失只限制相应打开/迁移动作。

配置、临时文件与状态放入目标工作区 runtime/workbench；共享规则来自安装的 dummysys-core，写入调用配套 CLI。验证见 [verification.md](docs/verification.md)。

可选原生窗口使用配置项 `apps.window_icon_path` 指定本机 ICO；相对路径以配置文件目录为准，不从当前目录或旧源码仓查找。明确配置的图标缺失时报告错误，未配置时使用包内自带的 Workbench 图标。个人图像留在 runtime，不因本机使用而收入发行包。原生窗口设置独立的 DUMMYSYS 任务栏身份，后台服务、窗口及重启进程不创建控制台。
