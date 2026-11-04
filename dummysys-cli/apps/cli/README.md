# dmy

`--workspace` 优先，其次显式 `--config` 或 DMY_CONFIG。没有全局配置回退，也不按当前目录猜测。

输出 `{schema_version, tool_version, data, diagnostic_id, trace_id}` 或同结构 error；退出码 0 成功、1 检查发现问题、2 输入或执行失败。init 仅支持显式绝对路径，拒绝非空目录。

写操作提供 --actor、--request-id，更新时提供 --if-version。保留原有可选 CODEX_THREAD_ID 适配；显式 actor 适用于任意工具。创建结果在 data.result。context 是阅读入口，不自动注入上下文。

命令声明见 [commands.md](docs/commands.md)。

