# 工作区与资料位置

工作区根是配置入口，Vault 保存可读正文，runtime 保存本机状态和执行证据。Vault 和 runtime 可以分别改名、放在工作区外或使用不同磁盘；源码仓库不充当资料目录。

首次初始化：

```powershell
dmy init --workspace "D:\Work\Example" --vault-root "正文" --runtime-root "E:\Records\Example" --json
```

工作区、Vault、runtime 三处目标均须不存在或为空。所有目标预检通过后才开始初始化；重复初始化不会覆盖。失败保留现场，并返回回执位置和恢复建议。

初始化将位置保存到工作区根 `.dummysys-workspace.json`：

```json
{
  "schema_version": 1,
  "vault_root": "正文",
  "runtime_root": "E:\\Records\\Example"
}
```

相对路径始终相对工作区根，绝对路径使用本机位置；不依赖命令当前目录。不声明配置的已有工作区继续使用 `dmy_vault` 和 `runtime`。非法配置明确报错，不回退到默认目录。两处资料根不能重合、嵌套、包含工作区根或通过链接指向别处。

CLI、Workbench、校验器和安装器使用同一份位置声明。Workbench 的 `task_root` 是工作台自身状态目录，`apps.obsidian_vault_path` 是可选应用配置，均不替代上述资料位置声明。

Project/Task 配对字段中的 `dmy_vault/...` 和 `runtime/...` 是稳定逻辑引用；core 将它们解析到实际目录。Project、Task、Run ID 不随资料根改名。查询返回的 `document`、`record` 和 Workbench 目标是实际物理路径；`doctor` 也返回当前位置。

配置文件只负责定位，不搬运或合并资料。已有工作区改位置必须先停止写入、处理待恢复操作，并使用已验证的迁移流程；不要仅改配置后把空目录视为迁移成功。操作回执记录当时的位置，配置变化后不能将待恢复写入应用到新目录。

runtime 内的项目记录和 Run 证据属于持久资料，不能当作缓存删除。环境、缓存和浏览器状态可以重建；备份范围应区分这些内容。根 AGENTS 与 Vault 的权威规则在同卷时使用硬链接，跨卷时使用明确的导航入口，不维护两份规则正文。
