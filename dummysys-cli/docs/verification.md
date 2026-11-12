# 验证

用独立环境安装构建包，再从本目录运行 `python -B -m unittest discover -s tests -p "test_*.py"`。TMP 与 TEMP 指向 runtime。跨包投影从已安装的 Workbench 导入；不要把原仓加入 PYTHONPATH。

CLI 契约、治理、恢复、路径、初始化和投影都属于拆分回归范围。`python -B scripts/command_reference.py --check` 校验命令参考。安装集成另验从不同 cwd 启动、实际导入路径、完整 doctor、中文空格路径与现用配置不变。失败保留日志，修复后用新 Run。


macOS 安装集成：将 `DUMMYSYS_TEST_WHEELS` 设为本机 `build.py --desktop` 的 wheelhouse 绝对路径，`DUMMYSYS_HOST_PYTHON` 指向带 pip 的宿主解释器，再执行 `tests.test_macos_install`。用例在临时中文空格目录验证非空拒绝、空目标安装、固定入口、其他 cwd、PYTHONHOME/PYTHONPATH 隔离、已有项目保留和重复发行拒绝。默认无 wheelhouse 时明确跳过；不能把这个跳过当作安装已验证。
