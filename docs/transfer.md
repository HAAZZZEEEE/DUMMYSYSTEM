# 项目资料导入导出

资料包用于离线交接一个项目。两端各自在本机运行，不需要通信或同步服务。先预演、核对文件与依赖，再导入。当前仅在 Windows 验证；来源路径解析兼顾 Windows 与 POSIX，未据此宣称 macOS 已验证。

本页说明格式与命令契约。可复制执行的合成示例见 [备份与恢复](backup-restore.md)；资料包不等同于整个工作区备份。

## 导出

```powershell
dmy project export --workspace D:/Example/source --project <project_id> --dry-run --json
dmy project export --workspace D:/Example/source --project <project_id> --output D:/Example/packages/project.zip --json
```

默认包含项目正文、Project/Task/Run 记录、已解析到项目资源内的 Run 证据、正文通过完整 `[[80-附件/...]]` 引用的附件，以及关联 Repo 的逻辑登记文档。`transfer-history` 中的原件与导入收据随再次导出保留。

额外资源使用可重复的 `--include-resource`，路径相对该项目的资源目录，例如 `--include-resource reports`。未选择的资源入口、外部证据、外部正文链接与 Repo checkout 会列入报告；不要把文件数量当作资料完整性的证明。普通 Markdown 附件链接目前列为依赖，需要手工整理或显式收入资源，工具不猜测其他笔记库的附件布局。

环境、缓存、应用状态、Git 元数据和已知凭据文件名排除；源码 checkout 不随 Repo 关联复制。过滤规则无法判断任意正文中的秘密，资料包包含私人内容与来源路径，**不是公开发行物**，分享前仍需自行检查。默认包内单文件上限 64 MiB、总解压量 256 MiB、文件数量 20000；大模型、环境和大型实验输出应独立搬运。

存在未结束 Run 或待恢复操作时拒绝导出。导出使用同一工作区锁，并复验读取文件的哈希；手动编辑器等不使用该锁的写入者应在导出期间停止编辑。目标必须是新的绝对文件路径，已有包不会被覆盖。

## 导入

先初始化并安装目标工作区。Vault 与 runtime 的物理位置由目标 `.dummysys-workspace.json` 决定。

```powershell
dmy project import --workspace D:/Example/target --bundle D:/Example/packages/project.zip --actor human --dry-run --json
dmy project import --workspace D:/Example/target --bundle D:/Example/packages/project.zip --actor human --request-id import-example-1 --if-plan <plan_token> --json
```

预演返回目标文件映射、可复用的相同附件/Repo 文档、未绑定仓库、遗漏项、依赖与 `plan_token`。包或目标记录在提交前变化时重新预演。相同写入意图重试保持原 request ID、计划和参数；不同包不能复用同一请求。

若本机已有 checkout，在两步命令中都增加相同的 `--repo-path example=D:/Example/repos/example`。导入不下载源码，也不替换已有的不同 Repo 绑定。缺少 checkout 时允许资料落盘，但收据与上下文会明确报告；在完成 `repo bind` 前，不应将相关治理检查视为通过。

Project/Task/Run ID、状态和执行结果保留。项目绑定与随包证据引用转换到目标位置；Task 范围仅自动重绑定项目自身路径，其他机器目录及远端权限列为待核对项，不自动授予。未收入包的绝对证据引用在当前记录中标为 `external:`。被调整文件的原始字节保存在项目资源的 `transfer-history/<包哈希>/originals/`，`report.json` 记录差异和未解决项，原始清单保留哈希。

新导入的正文、脚本和 AGENTS 内容都是待审阅资料；工具不执行包内代码，也不将它们提升为目标工作区全局规则。当前正文中的普通绝对链接不批量改写，报告列出依赖；派生项目入口由 core 重建。

## 冲突与恢复

相同 Project/Task/Run 身份、已有项目目录、大小写冲突或不同内容的同名附件均拒绝。首版不合并项目、不覆盖资料、不重分配身份。ZIP 越级路径、保留名称、重复项、链接、特殊文件、加密内容、超限内容及哈希不符会被拒绝。资料包校验通过仅说明格式与内容完整，不证明内容可信。

导入走现有 core Operation 日志。提交中断后使用 `operation list/show/recover` 查看并接续；恢复前仍会核对目标文件和存储位置，发生后续修改时拒绝覆盖。保留失败现场，不通过删除整个工作区回滚。

导入后检查 `project show`、`context --task ... --section reading`、`check --json` 和浏览器 Workbench。收据中的 `unresolved`、`missing_repos`、`dependencies`、`omitted` 需要逐项判断；命令成功不等于所有外部依赖均已搬迁。
