# 验证

用独立环境安装构建包，再从本目录运行 `python -B -m unittest discover -s tests -p "test_*.py"`。TMP 与 TEMP 指向 runtime。跨包投影从已安装的 Workbench 导入；不要把原仓加入 PYTHONPATH。

CLI 契约、治理、恢复、路径、初始化和投影都属于拆分回归范围。`python -B scripts/command_reference.py --check` 校验命令参考。安装集成另验从不同 cwd 启动、实际导入路径、完整 doctor、中文空格路径与现用配置不变。失败保留日志，修复后用新 Run。

