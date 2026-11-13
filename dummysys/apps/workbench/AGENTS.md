# 工作台实现入口

所有 Workbench 开发与 UI 设计默认兼顾 Windows/macOS。先读 [默认双平台开发规则](../../../docs/development.md#默认双平台开发)；自行识别本机环境，不能把开发机平台视为需求范围，无需用户另行提醒解耦。

业务和页面保持共用；系统能力由 `ports.py`、`platform_runtime.py`、`native_host.py` 及各平台实现承接，前端系统习惯集中在 `static/platform-ui.js`。新增或修改能力先检查两边契约与实现，避免在共享模块散落平台分支。验证和交付遵循 [工作台验证](docs/verification.md) 的双平台要求。

配置与安装改动验证 config、source_entry、release_info；治理接入验证 ptr_api、dfx 与 CLI/core 的 projection；目录浏览验证 catalog 和浏览器夹具。平台打开由适配器承担，不把机器路径写进业务模块。测试输出显式指向 runtime。共用行为在两平台复用；Windows 原生 API 用例只在 Windows 执行，Mac 控制与服务用例只在 macOS 执行，不把跳过记为实测。

