# 备份与恢复

源码仓库不是个人资料备份，项目 ZIP 也不是整个工作区的备份。本页覆盖当前 Windows 实现、同一套已验证安装包的恢复方式；不承诺跨版本升级、旧数据格式兼容或 macOS 恢复。

## 先决定要保留什么

| 内容 | 是否应保留 | 恢复方式 |
|---|---|---|
| 源码、Git 提交、当次 wheel 与 build.json | 保留准确版本与包哈希 | 同版本重建或离线安装 |
| Vault 正文、附件、规则、模板、Properties | 持久资料 | 项目包只包含所选范围；其他资料另行备份 |
| runtime/project_src 中 Project/Task/Run 配对、原始结果、源码快照、transfer-history | 持久资料 | 按项目导出范围核对，遗漏资源单独保存 |
| runtime/state/workspace 中 Operation 原件、迁移日志、旧路径记录和 Repo 绑定 | 恢复现场与本机状态 | 原工作区保留；不要在新机器直接重放 |
| 工作区根位置声明、文档维护映射、根入口、本机应用配置 | 恢复所需配置 | 冷备保存；换位置时重新核对绑定 |
| Python 环境、缓存、浏览器用户数据、进程/锁/认证状态 | 可重建或机器专用 | 新环境重新安装与启动，不当作可移植资料 |

如果 Vault/runtime 位于工作区之外，复制工作区根并没有复制它们。先通过 `doctor --json` 查看 `locations.vault_root` 和 `locations.runtime_root`。

## 项目备份：可实际演练的恢复单位

下面接续 [入门演练](quickstart.md) 的变量，使用同一套构建包和已完成的 Run。正式资料导出前停止手动编辑与其他写入者，处理未结束 Run 和待恢复 Operation。Workbench 停止并不会自动停止其他 Agent 或编辑器。

### 导出并保存哈希

```powershell
$raw = & $python -I -X utf8 -B -m dummysys_cli --workspace $workspace project export --project $example.project_id --dry-run --json
if ($LASTEXITCODE -ne 0) { throw ($raw -join "`n") }
$exportPlan = ($raw | ConvertFrom-Json).data
$exportPlan | ConvertTo-Json -Depth 12
```

检查 `dependencies` 与 `omitted`：是否有包外证据、未包含资源、附件或 checkout。默认不会把任意大文件、环境或源码 checkout 打进包。需要增加项目资源时，两次导出都传相同的 `--include-resource <项目资源内相对路径>`。规则与大小限制见 [导入导出](transfer.md)。

```powershell
$bundle = Join-Path $workRoot 'packages\intro-01.zip'
$raw = & $python -I -X utf8 -B -m dummysys_cli --workspace $workspace project export --project $example.project_id --output $bundle --json
if ($LASTEXITCODE -ne 0) { throw ($raw -join "`n") }
$exported = ($raw | ConvertFrom-Json).data
$archiveHash = (Get-FileHash -LiteralPath $bundle -Algorithm SHA256).Hash.ToLowerInvariant()
if ($archiveHash -ne $exported.sha256) { throw '资料包哈希不一致' }
$archiveHash
```

使用新的包名；已有包拒绝覆盖。把 ZIP、哈希和当次安装包留在独立备份位置。ZIP 含正文与历史路径，可能有秘密；过滤已知文件名不等于内容脱敏，不能提交到源码仓库。

### 恢复到新的隔离工作区

恢复演练始终选新目录，原工作区保持原位。以下同时验证 Vault/runtime 改位置，不手改旧包：

```powershell
$restoreWorkspace = Join-Path $workRoot '恢复 工作区'
$restoreVault = Join-Path $workRoot '恢复 正文'
$restoreRuntime = Join-Path $workRoot '恢复 运行'
$raw = & py -3.13 -X utf8 -B "$candidate\dummysys-cli\scripts\install.py" --workspace $restoreWorkspace --vault-root $restoreVault --runtime-root $restoreRuntime --wheels "$build\wheels" --release-id restore-01
if ($LASTEXITCODE -ne 0) { throw ($raw -join "`n") }
$restoreSetup = $raw | ConvertFrom-Json
$restorePython = $restoreSetup.python

$raw = & $restorePython -I -X utf8 -B -m dummysys_cli --workspace $restoreWorkspace project import --bundle $bundle --actor example-person --dry-run --json
if ($LASTEXITCODE -ne 0) { throw ($raw -join "`n") }
$importPlan = ($raw | ConvertFrom-Json).data
$importPlan.plan | ConvertTo-Json -Depth 12
```

核对目标位置、`missing_repos`、`dependencies`、`omitted` 和复用文件列表。真实项目有 Repo 时，在预演和提交两步都传相同的 `--repo-path repo_id=本机checkout绝对路径`。新工作区的安装环境及根规则由初始化生成，不能从资料包覆盖。

确认这份计划与自己要恢复的范围一致后执行：

```powershell
$importRequest = [guid]::NewGuid().ToString()
$raw = & $restorePython -I -X utf8 -B -m dummysys_cli --workspace $restoreWorkspace project import --bundle $bundle --actor example-person --request-id $importRequest --if-plan $importPlan.plan_token --json
if ($LASTEXITCODE -ne 0) { throw ($raw -join "`n") }
$imported = ($raw | ConvertFrom-Json).data.result
$imported | ConvertTo-Json -Depth 12
```

保留 request ID、原参数和输出。相同提交重试使用同一 ID/计划；新的意图使用新 ID。已有身份或不同内容不会被覆盖或合并。被重绑定的原始记录进入 `transfer-history`，历史执行事实不改写成新机器的事实。

### 恢复成功的判定

```powershell
$raw = & $restorePython -I -X utf8 -B -m dummysys_cli --workspace $restoreWorkspace run show $example.run_id --task $example.task_id --json
if ($LASTEXITCODE -ne 0) { throw ($raw -join "`n") }
$restoredRun = ($raw | ConvertFrom-Json).data
if ($restoredRun.run_id -ne $example.run_id -or $restoredRun.task_id -ne $example.task_id -or $restoredRun.project_id_at_start -ne $example.project_id) { throw '稳定身份不一致' }
$sourceHash = (Get-FileHash -LiteralPath $example.evidence -Algorithm SHA256).Hash
$restoredHash = (Get-FileHash -LiteralPath $restoredRun.evidence[0] -Algorithm SHA256).Hash
if ($sourceHash -ne $restoredHash) { throw '结果文件哈希不一致' }
Get-Content -LiteralPath $restoredRun.evidence[0]

& $restorePython -I -X utf8 -B -m dummysys_cli --workspace $restoreWorkspace context --task $example.task_id --section reading --json
if ($LASTEXITCODE -ne 0) { throw '阅读入口检查失败' }
& $restorePython -I -X utf8 -B -m dummysys_cli --workspace $restoreWorkspace check --json
if ($LASTEXITCODE -ne 0) { throw '恢复后记录检查失败' }
```

还要阅读 `$imported.report` 指向的收据，核对 `unresolved`、`missing_repos`、`dependencies` 和 `omitted`。这个合成示例没有外部 Repo；真实资料即使 import 返回成功，也可能仍缺包外资源。可用恢复安装的 Workbench 浏览正文、Task、Run 与结果。

完成演练不代表原项目应被删除。正式迁移到新工作区需要停止旧位置写入，再明确选定哪一份继续维护。

## 整个工作区的冷备

当前没有“整个工作区一键备份/恢复”命令。需要完整保留个人知识、规则、本机配置和恢复现场时，用文件系统备份工具做一致的冷备：

1. 记录准确源码 commit、三包及依赖 wheel 哈希、解释器版本和实际目录位置。
2. 停止所有 Agent、编辑器同步和 Workbench 写入；处理未决 Operation。若已有故障而无法恢复，先完整保留故障现场，标明它不是健康快照。
3. 同时备份工作区根入口和隐藏声明、完整 Vault、完整 runtime，以及明确位于三者之外的资料和 Repo。保留文件内容、目录结构、链接关系与访问权限；根 AGENTS 可能与 Vault 正文是硬链接。
4. 在备份端生成文件清单与内容哈希，核对无遗漏。完整 runtime 可能含凭据和浏览器数据，按私人备份管理。
5. 在隔离环境验证可读性与项目恢复，再考虑替换现用工作区。备份文件存在不等于恢复已经验证。

同版本、同机器、原绝对位置的冷备恢复应在所有进程停止后，保留当前现场，恢复三处目录及链接，再从固定安装入口核对安装身份、Operation、`check` 和 `doctor --full`。不要混搭两个时间点的 Vault、runtime 或安装登记。

换位置或机器时，不能把冷备里的 Python 环境、绝对入口、锁与进程记录直接当作新安装使用。优先采用上面的“新安装＋项目导入”流程；个人知识等包外内容另行核对。任意整工作区搬迁、历史版本升级与灾难恢复自动化尚未提供，本轮演练不证明这些场景通过。

## 中断和冲突怎么办

- **导入提交中断或结果未知**：使用原安装和目标工作区查询 `operation list --json`，再 `operation show <operation_id> --json`。核对来源版本与现场后，才执行 `operation recover <operation_id> --json`；它恢复治理写入，不重新执行 Run 的业务程序。
- **恢复时检测到后续修改**：保留原包、当前资料与 Operation 原件，核对差异；不要删目录强制重试，也不要手改日志伪造完成。
- **版本或安装身份不匹配**：保留旧解释器及 wheel，回到对应发行处理未决操作；不要用新发行强行重放未知格式。
- **想恢复较旧项目**：导入到另一个空工作区比较。当前工具不把旧包覆盖到同身份的现用项目。

日常记录校验、项目 ZIP 恢复、安装回退和整工作区冷备是不同层次。只报告实际验证过的层次。

