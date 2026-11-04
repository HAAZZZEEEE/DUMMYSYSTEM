# 工作台验证

用独立安装环境运行相关测试。测试 wheel 时先以 `-I` 导入已安装的应用，再加入测试目录，防止当前源码目录遮蔽安装包：

```powershell
& $python -I -B -c "import workbench,dummysys_core,dummysys_cli,sys,unittest; print(workbench.__file__); sys.path.insert(0,sys.argv[1]); unittest.main(module=None,argv=['unittest',*sys.argv[2:]])" "$candidate\dummysys\apps\workbench" tests.test_config tests.test_source_entry tests.test_release_info tests.test_dfx tests.test_ptr_api tests.test_application tests.test_catalog tests.test_service_regressions
```

浏览器测试使用 tests/browser/browser_fixture.py 与 Playwright，WORKBENCH_TEST_OUTPUT、TMP、TEMP 显式指向 runtime。记录实际导入路径、测试模块和退出码。

CLI/core 投影与 Workbench 必须配套安装。应用缺失、配置位置与安装来源需要覆盖。替身只证明派发参数；真实资源管理器、桌面窗口、Obsidian 链接迁移各自记录实测范围。浏览器服务通过不代表原生桌面或 macOS 通过。
