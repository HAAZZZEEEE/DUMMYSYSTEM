# 从一个合成项目开始

本例只处理合成数字 2、3、5，不需要真实项目、Agent 账号、代码仓库关联或 Obsidian。参考环境为 Windows、PowerShell 7、Python 3.13；软件声明的 Python 最低版本是 3.11，其他版本并未据此视为已实测。

下面的目录均为虚构示例。把整个代码块中的路径替换成你的**源码之外**的绝对路径。选择较短目录；失败现场保留，重试使用新的工作区或新的 release-id。

## 1. 安装到新工作区

先按 [INSTALL.md](../INSTALL.md) 构建。保留该次 wheel 目录及 build.json，后续恢复使用同一套包。以下在同一个 PowerShell 会话中执行：

```powershell
$candidate = 'C:\code\dummysys-public'
$build = 'C:\dmy-build\runtime\candidate-01'
$workRoot = 'C:\dmy-demo'
$workspace = Join-Path $workRoot '示例 工作区'

$raw = & py -3.13 -X utf8 -B "$candidate\dummysys-cli\scripts\install.py" --workspace $workspace --wheels "$build\wheels" --release-id example-01
if ($LASTEXITCODE -ne 0) { throw ($raw -join "`n") }
$setup = $raw | ConvertFrom-Json
$python = $setup.python
$dmy = $setup.launcher
$workbench = $setup.workbench_launcher
```

安装器初始化必要目录和新身份，安装固定包，返回目标解释器与入口。不要把这些本机回执提交进源码仓库。若使用外置 Vault/runtime，以返回的路径为准，不自行拼接安装路径。

## 2. 创建 Project、Task，执行一次 Run

演练脚本通过公开 CLI 创建和更新记录，直接写入的只有普通结果与摘要。它拒绝在已有业务项目或 Task 的工作区重跑。

```powershell
$raw = & $python -I -X utf8 -B "$candidate\examples\first_project.py" --workspace $workspace --actor example-person
if ($LASTEXITCODE -ne 0) { throw ($raw -join "`n") }
$example = $raw | ConvertFrom-Json
$example | Select-Object project_id, task_id, run_id, task_document, evidence, check_ok
Get-Content -LiteralPath $example.evidence
```

预期：

- 一个名为“入门演练”的 Project，一个“统计示例数据”Task。
- 一个 completed Run，其 result.json 是 `{"inputs":[2,3,5],"count":3,"total":10}`。
- Task 当前摘要说明统计完成，下一步演练导出与恢复；Task 仍为 active。
- `check_ok` 为 true。

[脚本源码](../examples/first_project.py) 展示了完整顺序：project create → task create → run create → run start → 写结果 → run finish → 更新 Task → context/check。创建结果来自 `data.result`，更新前重新 show 读取 version；所有示例身份由初始化或创建操作生成。

## 3. 理解写入契约

```powershell
& $dmy capabilities --command 'task create' --json
if ($LASTEXITCODE -ne 0) { throw '能力查询失败' }
& $dmy task show $example.task_id --json
if ($LASTEXITCODE -ne 0) { throw 'Task 查询失败' }
& $dmy run show $example.run_id --task $example.task_id --json
if ($LASTEXITCODE -ne 0) { throw 'Run 查询失败' }
```

- 每次写入使用实际 `--actor` 和独立 `--request-id`。同一写入结果未知时保留原请求，先查 Operation；不要随意换 ID 重发。
- 更新已有对象时传查询所得 `--if-version`；普通正文修改也可能改变 version。
- JSON 成功数据位于 `data`，失败位于 `error`。退出码 0 表示命令成功，1 表示检查发现问题，2 表示参数、状态或执行错误；先检查退出码再取字段。
- 自动化或带特殊符号的正文参数建议直接调用目标 Python 的 `-m dummysys_cli`，用参数数组传递，避免额外经过 cmd 的转义。示例脚本采用这种方式。

命令清单见 [CLI 参考](../dummysys-cli/apps/cli/docs/commands.md)。不要手改 Properties、run.json 或 task.json 来绕过状态和版本检查。

## 4. 在另一会话接续

离开代码仓库后，显式工作区仍可定位到同一资料：

```powershell
Push-Location $workRoot
try {
    & $python -I -X utf8 -B -m dummysys_cli --workspace $workspace context --task $example.task_id --section reading --json
    if ($LASTEXITCODE -ne 0) { throw '上下文查询失败' }
    Get-Content -LiteralPath $example.task_document
} finally {
    Pop-Location
}
```

新的 Agent 只需要工作区位置、Task ID、当前目标和授权范围。先看 Task 当前摘要，再按需读 Run 结果，不需要粘贴整段历史会话。

## 5. 浏览与检查

```powershell
& $dmy check --json
if ($LASTEXITCODE -ne 0) { throw '记录检查未通过' }
& $dmy check --docs --json
if ($LASTEXITCODE -ne 0) { throw '文档检查未通过' }
& $workbench launch --browser
if ($LASTEXITCODE -ne 0) { throw '浏览器启动失败' }
```

在 Workbench 中打开“入门演练”，查看文档、Task、Run 与 result.json。普通浏览无需启动 Obsidian。浏览器仅连接本机；不要分享启动令牌或把裸 URL 当作可复用登录链接。结束演练时：

```powershell
& $workbench stop
if ($LASTEXITCODE -ne 0) { throw '服务停止未确认' }
```

下一步按 [备份与恢复](backup-restore.md) 导出这个项目，再恢复到另一个工作区。两端同时存在相同逻辑项目只适合隔离演练，不要将它当作已实现的多端同步。

