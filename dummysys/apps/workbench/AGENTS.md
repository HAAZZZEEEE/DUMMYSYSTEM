# 工作台实现入口

配置与安装改动验证 config、source_entry、release_info；治理接入验证 ptr_api、dfx 与 CLI/core 的 projection；目录浏览验证 catalog 和浏览器夹具。平台打开由适配器承担，不把机器路径写进业务模块。测试输出显式指向 runtime。共用行为在两平台复用；Windows 原生 API 用例只在 Windows 执行，Mac 控制与服务用例只在 macOS 执行，不把跳过记为实测。

