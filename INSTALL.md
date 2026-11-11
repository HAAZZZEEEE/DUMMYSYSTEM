# Windows 独立安装

需要 Windows、Python 3.11+（含支持 --python 的 pip）与 Git。本文参考验证环境为 Python 3.13、PowerShell 7；3.11 是包声明的最低版本，不代表各 Python 版本都已实测。浏览器可使用现有 Edge。默认构建会下载依赖；安装只使用生成的 wheel 目录。以下路径是虚构示例，替换成自己的绝对路径。

中文和含空格路径属于本轮验证范围。建议选择较短的工作区根目录；部分正式记录路径仍受 Windows 路径长度限制，极深目录不在本轮保证范围内。构建与安装使用相同的 Python 版本和系统架构，依赖 wheel 不能直接跨平台搬用。

## 构建与安装

把候选源码放在一处，构建证据目录与目标工作区放在源码之外。构建目录必须尚不存在。

~~~powershell
$candidate = 'C:\code\dummysys-public'
$build = 'C:\dmy-build\runtime\candidate-01'
$workspace = 'C:\workspaces\我的工作区'

py -3.13 -X utf8 -B "$candidate\dummysys-cli\scripts\build.py" --output $build
if ($LASTEXITCODE -ne 0) { throw '构建失败，保留输出目录核对日志' }
$raw = & py -3.13 -X utf8 -B "$candidate\dummysys-cli\scripts\install.py" --workspace $workspace --wheels "$build\wheels" --release-id candidate-01
if ($LASTEXITCODE -ne 0) { throw ($raw -join "`n") }
$setup = $raw | ConvertFrom-Json
$python = $setup.python
~~~

构建器默认读取同一候选区相邻的 Workbench；用 `--workbench-root` 可覆盖其源码目录，不查找其他工作区。安装器从构建的 wheel 调用 `dmy init`，然后把环境、安装记录、配置与日志放进目标工作区 runtime。目标非空且未初始化时拒绝安装。已有发行保留；重试需新的 release-id，失败目录保留。

构建器在独立环境中安装后端，使用宿主 pip 定向操作，不在源码或全局环境安装项目依赖。build.json 记录本次全部 wheel 哈希和构建后端版本；wheel 目录同时保留构建后端，可用于同平台、同解释器的离线复现：

~~~powershell
$offlineBuild = 'C:\dmy-build\runtime\candidate-02'
py -3.13 -X utf8 -B "$candidate\dummysys-cli\scripts\build.py" --output $offlineBuild --wheelhouse "$build\wheels"
if ($LASTEXITCODE -ne 0) { throw '离线构建失败，保留输出目录核对日志' }
~~~

指定 `--wheelhouse` 后不会查询包索引；依赖不齐则失败。默认在线构建的依赖范围可能解析到不同版本，不能把它当作锁定版本构建。保存实际使用的源码 commit、build.json 和整个 wheel 目录；离线复现要求依赖目录中的版本明确，不混放多套发行。

在已有工作区安装新发行前，先停止 Workbench 和其他写入者、处理未决 Operation，并做好备份。安装器不是正在运行实例的自动升级或整工作区迁移器；当前工作区的人工切换不等于通用安装器具有同等回退能力。

安装环境不自带 pip。维护者如确需安装额外依赖，可用宿主 `py -m pip --python <目标解释器> ...` 明确指定目标；普通使用无需安装额外依赖。原生桌面封装的 pywebview 为可选依赖，浏览器服务无需它。

## 启动与检查

安装器返回 launcher、python、workbench_launcher 和配置路径。固定入口绑定目标工作区，不修改 PATH 或全局 CLI 配置。

~~~powershell
$dmy = $setup.launcher
$workbench = $setup.workbench_launcher
& $dmy check --json
if ($LASTEXITCODE -ne 0) { throw '记录检查失败' }
& $workbench launch --browser
if ($LASTEXITCODE -ne 0) { throw '浏览器启动失败' }
~~~

启动入口通过当前用户受限管道取得一次性令牌，打开隔离的 Edge 窗口；令牌不进入状态或日志。`workbench.cmd status` 查询状态，`workbench.cmd stop` 停止。裸 URL 不建立认证会话，`serve` 仅运行服务。服务只监听 127.0.0.1。完整检查用 `dmy doctor --full --json`，调用包内目录和 Vault 校验器。

如果已把 CLI/core 安装到独立 Python 环境，也可直接初始化尚不存在或为空的目标：

~~~powershell
& $python -I -B -m dummysys_cli init --workspace $workspace --json
~~~

重复 init 或非空目标返回 WORKSPACE_NOT_EMPTY，不覆盖既有资料。初始化失败返回 INIT_FAILED，并尽力保存 runtime/state/workspace/init.json。保留现场核对失败阶段，修复原因后选另一个空目录重试，不删除整个目标来掩盖失败。

## 工作闭环

完整的合成演练见 [入门示例](docs/quickstart.md)，同版本恢复演练见 [备份与恢复](docs/backup-restore.md)。

写入显式传实际 `--actor` 和每次意图的 `--request-id`；更新先 show 获取 `version`。创建 Project、Task、Run 的结果在 JSON 的 `data.result`。

~~~powershell
& $dmy capabilities --command "project create" --json
& $dmy capabilities --command "task create" --json
& $dmy capabilities --command "run create" --json
& $dmy context --task '<Task-ID>' --section reading --json
~~~

Run 的 create 只登记计划，实际开始后 start，完成后以退出码、结果和证据 finish。初始化、普通记录和浏览无需 Obsidian；改名、移动、归档仍要求 Obsidian CLI、正确 Vault 与链接更新设置。缺少依赖时保留明确错误，普通文件移动不能替代链接迁移。

开发验证在独立安装环境运行 CLI/core tests 与 Workbench tests；测试的临时目录、浏览器证据和缓存均通过 TMP、TEMP、WORKBENCH_TEST_OUTPUT 指向 runtime。包内检查器可用 `python -I -m dummysys_core.validation.layout --root <workspace> --json` 和 `dummysys_core.validation.vault` 单独执行。Windows 项目导入导出已具备，仍须为自己的资料做恢复演练；macOS 与跨平台互通未实测。

## 资料位置

Vault 与 runtime 可以独立配置。新工作区安装时可加 `--vault-root "正文" --runtime-root "E:\Records\Example"`；相对路径相对 `--workspace`，绝对路径可位于其他目录或磁盘。已有工作区由根 `.dummysys-workspace.json` 定位；安装参数不会搬移资料。完整规则见 [工作区与资料位置](docs/storage.md)。
