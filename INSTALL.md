# 安装 DUMMYSYS（Windows / macOS）

已安装工作区从指定 Git 版本更新，见 [更新指南](docs/update.md)。

这是供使用者和 Agent 执行的安装入口。目标是安装独立 CLI 和 Workbench、验证项目读写与启停，并保留可核对的安装回执。源码仓库、构建目录、使用者工作区是三个独立位置；不要把源码当作工作区初始化。

## Agent 先检查这些信息

1. 读取根 `AGENTS.md`；确认系统、架构、Python 3.11+ 与宿主 pip（须支持 `--python`）。macOS 原生应用打包还需 Xcode Command Line Tools 的 `codesign` / `iconutil` / `sips`。先使用已安装的合适解释器；不要自动升级系统 Python。
2. 确定用户要求的工作区绝对路径。未指定时可建议 `~/DUMMYSYSTEM`。检查目标：不存在或空目录可初始化；存在 `.dummysys-workspace.json` 时读取它并保留 Vault/runtime 的实际位置；非空且未初始化则停止该次安装，不能清空目录。
3. 构建目录放在仓库和工作区之外，每次使用新目录、新 `release-id`。若升级已有安装，先通过登记入口 `stop`，确认 `status` 不再运行，处理未决 Operation，并保留备份和旧发行环境。
4. 默认安装本机原生窗口依赖（`--desktop`）。需要浏览器模式时可同时省略构建和安装的 `--desktop`；Windows 使用 Edge，macOS 使用系统默认浏览器。
5. 全程检查退出码，失败保留现场与日志。安装完成后执行下方验收，不以“pip 成功”作为完成。

macOS 已在 Apple Silicon / Python 3.11 上做安装与功能验证；Intel Mac、其他 Python 版本及本次变更后的 Windows 桌面行为还需对应机器实测。两平台各自构建依赖，不互拷 venv、浏览器资料或 `.app/.exe`。

## macOS：构建与安装

以下为 zsh/bash 示例。替换 `repo`；`workspace` 使用用户指定位置。命令失败即停止后续步骤，保留当前目录。

```sh
set -e
repo="/absolute/path/to/DUMMYSYSTEM-source"
workspace="$HOME/DUMMYSYSTEM"
build="$HOME/Library/Caches/DUMMYSYS/build-$(date +%Y%m%d-%H%M%S)"
release="mac-$(date +%Y%m%d-%H%M%S)"
python_bin="$(command -v python3.11)"
"$python_bin" -I -m pip --version
"$python_bin" -I -B "$repo/dummysys-cli/scripts/build.py" --desktop --output "$build"
"$python_bin" -I -B "$repo/dummysys-cli/scripts/install.py" \
  --workspace "$workspace" --wheels "$build/wheels" --release-id "$release" --desktop \
  > "$build/install-receipt.json"
cat "$build/install-receipt.json"
```

若没有 `python3.11`，将 `python_bin` 指向已检查兼容的 Python 绝对路径。安装器返回 `launcher`、`python`、`workbench_launcher`、`workbench_config` 和日志路径。后续使用回执值，避免猜测自定义 runtime 的位置。

```sh
installed_python=$("$python_bin" -I -c 'import json,sys;print(json.load(open(sys.argv[1]))["python"])' "$build/install-receipt.json")
dmy=$("$python_bin" -I -c 'import json,sys;print(json.load(open(sys.argv[1]))["launcher"])' "$build/install-receipt.json")
workbench=$("$python_bin" -I -c 'import json,sys;print(json.load(open(sys.argv[1]))["workbench_launcher"])' "$build/install-receipt.json")
config=$("$python_bin" -I -c 'import json,sys;print(json.load(open(sys.argv[1]))["workbench_config"])' "$build/install-receipt.json")
"$dmy" check --json
"$workbench" doctor
"$workbench" launch
"$workbench" status
```

这时已有 Cocoa/WebKit 原生窗口。正式 `.app` 还会提供独立应用名称、图标与 Dock 身份。关闭窗口会隐藏窗口；再次启动可恢复；⌘Q 停止本工作区的服务并退出。`stop` 也会关闭旧窗口。

### 安装 DUMMYSYS.app

在独立的打包环境中安装同一批 wheel 和打包器，避免污染运行环境；打包器只从当前已安装包取代码，不从源码工作目录导入。

```sh
pack="$build/app-env"
"$python_bin" -I -m venv "$pack"
"$pack/bin/python" -I -m pip install --no-index --find-links "$build/wheels" 'dummysys-workbench[desktop]'
"$pack/bin/python" -I -m pip install 'PyInstaller>=6.22.3'
"$pack/bin/python" -I -B "$repo/dummysys-cli/scripts/build_macos_app.py" \
  --output "$build/native" --config "$config" --install-to "$HOME/Applications/DUMMYSYS.app"
open "$HOME/Applications/DUMMYSYS.app"
```

`.app` 绑定回执中的工作区配置，并使用该工作区登记的 CLI 环境执行写入。不要在未安装 CLI 的工作区单独使用 `.app`。目标 `.app` 已存在时构建器拒绝覆盖：升级先停止旧应用，将旧 `.app` 保留到一个备份名称，再安装新应用。不要删除旧环境，因为安装清单保留回退来源。切换旧环境需要核对其数据格式兼容性与未决操作，不承诺自动降级。

本机生成的 `.app` 使用 ad-hoc 签名，并验证签名完整性；这不等于 Apple 公证或可直接分发的安装包。无需为本流程修改 Gatekeeper 配置。

## Windows：构建与安装

需要 Python 3.11+、支持 `--python` 的 pip、Git 与 Edge。下面使用 PowerShell 7 / Python 3.13 示例。浏览器模式不需要可选桌面依赖；原生 WebView2 模式在 build/install 两处添加 `--desktop`，启动时省略 `--browser`。

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

构建和安装会隔离继承的 `PIP_*` 与 pip 配置文件，避免用户配置暗中改变下载来源或安装目标。在线构建使用 pip 默认索引；需要自定义来源时，在源码外准备依赖 wheel 目录，再显式传入 `--wheelhouse`。代理与系统证书仍由本机环境提供。

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

## 安装后验收（Agent 必须记录实际结果）

- 从仓库之外的当前目录运行回执中的 `dmy check --json`、`dmy doctor --full --json`、`workbench doctor`。记录缺失的可选应用；完整 doctor 中的能力缺失不能伪装成全部通过。
- 启动 Workbench，确认页面能看到工作区项目。再次 `launch`，应报告同一个 `instance_id`、`window_reused: true`（原生模式），并且不会创建第二个服务。浏览器模式可能打开新标签页。
- 在合成项目中验证创建 Task、创建/启动/完成 Run、目录浏览、文本预览、搜索、文件管理器打开。先用 `capabilities --command "project create" --json` 等核对契约；写请求使用实际 actor、稳定 request-id，更新先 show 获取 version。创建结果位于 `data.result`；`project sync --apply` 需要 project show 的 version。
- `stop` 应报告 `stopped: true`，随后 `status` 不再运行；重新启动成功。原生 Mac 应另验关闭窗口后恢复、⌘K、⌘Q 和 Finder 操作。检查实际退出码与窗口行为，不能只看接口返回。
- 将回执、日志和测试证据保存在源码之外；汇报安装位置、入口、版本/源码 commit、实测功能、失败和未验证项。不要把用户工作区数据提交到仓库。

初始化自动创建 Playground。额外项目按用户要求创建，不自动搬移旧 Windows 资料。已有资料通过 [导入导出](docs/transfer.md) 和 [备份恢复](docs/backup-restore.md) 操作；原机器的环境、锁、进程身份、会话不迁移。项目 ID 和证据来源按资料包保留。

改名、移动和归档依赖 Obsidian CLI 及正确打开的 Vault；Mac 会探测应用包中的 CLI。缺少能力时明确失败，不能退回普通文件移动以绕过链接维护。VS Code、Obsidian 都是可选外部应用。

## 离线复现与维护

构建器隔离继承的 `PIP_*` 和 pip 配置。在线构建使用默认索引；自定义来源先准备 wheel 目录，再传 `build.py --wheelhouse <绝对路径>`。依赖版本由实际解析决定，`build.json` 记录所有 wheel 哈希；保留整个 wheel 目录与源码 commit。`proxy-tools` 的纯 Python 源码依赖会在构建阶段转成 wheel，安装阶段只使用 wheelhouse。

离线构建使用新的 `--output`、相同系统/架构/Python、原 wheelhouse；原生选项也保持相同。`.app` 打包器 PyInstaller 另需提前准备，不能把业务 wheelhouse 误当完整的离线打包工具链。

环境不自带 pip，维护时可用宿主 `python -m pip --python <目标解释器>` 定向操作；日常使用无需它。安装器不会修改 PATH 或全局 CLI 配置。Vault/runtime 可在初次安装用 `--vault-root` / `--runtime-root` 自定义，规则见 [资料位置](docs/storage.md)。

开发回归见 [CLI 验证](dummysys-cli/docs/verification.md) 与 [Workbench 验证](dummysys/apps/workbench/docs/verification.md)。测试输出必须放在源码外。跨机器双向搬迁仍需真实 Windows + Mac 机器验证，本机测试不能替代它。
