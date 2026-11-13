# 工作台验证

## 每次变更的双平台检查

遵循 [默认双平台开发规则](../../../../docs/development.md#默认双平台开发)，先按变化选择相关验证，不因开发机是 Windows 或 macOS 而省略另一平台的影响审查。

| 变化 | 验证责任 |
|---|---|
| 共享业务、HTTP/JSON 契约、页面与交互 | 运行相关共享用例；新增回归不绑定本机路径、单一快捷键或系统应用名称 |
| 系统能力及其适配接口 | 检查 Windows/macOS 两侧契约；运行本机对应测试，另一平台原生测试未运行时列出具体待验证项 |
| 快捷键、字体、滚动、窗口、应用打开、图标及打包 | 按影响分别检查浏览器与原生宿主；浏览器截图或派发替身不替代 WebView2/Cocoa、Finder/资源管理器及安装后行为 |
| 仅文档、说明或开发约定 | 检查规则一致性、路径与链接；无需为措辞新增自动化测试或运行无关桌面回归 |

交付分别标注 Windows/macOS 的已执行检查、结果、跳过与未验证项。本机相关检查通过可以交付有明确验证边界的改动，但不能据此宣称双平台原生验收完成。

## 测试环境与通用回归

用独立安装环境运行相关测试。测试 wheel 时先以 `-I` 导入已安装的应用，再加入测试目录，防止当前源码目录遮蔽安装包：

```powershell
& $python -I -B -c "import workbench,dummysys_core,dummysys_cli,sys,unittest; print(workbench.__file__); sys.path.insert(0,sys.argv[1]); unittest.main(module=None,argv=['unittest',*sys.argv[2:]])" "$candidate\dummysys\apps\workbench" tests.test_config tests.test_source_entry tests.test_release_info tests.test_dfx tests.test_ptr_api tests.test_application tests.test_catalog tests.test_service_regressions
```

浏览器测试使用 tests/browser/browser_fixture.py 与 Playwright，WORKBENCH_TEST_OUTPUT、TMP、TEMP 显式指向 runtime。记录实际导入路径、测试模块和退出码。

CLI/core 投影与 Workbench 必须配套安装。应用缺失、配置位置与安装来源需要覆盖。替身只证明派发参数；真实资源管理器、桌面窗口、Obsidian 链接迁移各自记录实测范围。浏览器服务通过不代表原生桌面或 macOS 通过。

多仓库与长名称根选项卡使用 tests/browser/test_root_tabs.py：验证代码仓库下拉列表的长名称完整换行、菜单边界及纵向滚动、当前选择、键盘开关与选择、点击外部关闭、窗口尺寸变化、单仓库和跨项目切换；同时回归 test_root_context.py 与 test_workbench_browser.py 中的历史导航用例。自动化夹具的 RecordingOpener 不替代真实应用打开验证。

选中动画回归直接统计浏览器 animationstart/animationend：延迟加载完成后保持一次播放，刷新和重复点击当前分类不重播。

tests/test_file_io.py 使用真实 Windows 文件句柄覆盖偏好、实例与统计缓存三处保存：短时占用释放后写入成功，持续占用明确报错并保留旧值，临时文件被清理。它不识别实际占用进程，也不承诺绕过持久权限限制。统计 HTTP 测试收尾须等待容量与项目两个后台任务结束，再清理夹具。

## macOS 回归

在已安装三包的隔离环境中先导入包，再将测试目录加入 sys.path；设置 TMPDIR 与 WORKBENCH_TEST_OUTPUT 到仓库外。`tests.test_macos_control` 验证真实对端身份、错误实例拒绝、重复服务、超时客户端与残留 socket；`tests.test_macos_smoke` 验证真实服务认证、正常退出和杀死测试子进程后的恢复；`tests.test_macos_opener` 检查结构化参数和可选应用错误。

浏览器夹具在 Windows 使用 Edge，macOS 使用 `python -m playwright install chromium` 安装的 Chromium。快捷键用 Playwright 的 ControlOrMeta，覆盖 Mac 的 ⌘K / ⌘⇧F。性能样本环形缓冲有上限，逐次收集完成的刷新，不假设历史样本永久保留。

真实 `.app` 验收另行检查应用身份、项目/Task/Run、预览、搜索、Finder、重复启动、关闭恢复、⌘Q 与重启。不要把 RecordingOpener 或 Chromium 夹具说成 Cocoa/系统应用实测。Windows 专属 API 用例在 Mac 明确跳过。
