"""从构建包安装完整工作流；只写显式目标工作区的 runtime。"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False) as stream:
        stream.write(text)
        temporary = stream.name
    os.replace(temporary, path)


def contained(path, runtime):
    path = path.resolve()
    if not path.is_relative_to(runtime.resolve()):
        raise ValueError("安装输出必须在目标工作区 runtime 内")
    return path


def wheel_packages(directory):
    selected = []
    for name in ("dummysys_core", "dummysys_cli", "dummysys_workbench"):
        matches = list(directory.glob(name + "-*.whl"))
        if len(matches) != 1:
            raise ValueError(f"wheel 目录必须有且只有一个 {name} 构建包")
        selected.append(matches[0])
    return selected


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--wheels", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--evidence", type=Path, help="默认 runtime/state/cli/installations/<release-id>")
    parser.add_argument("--config", type=Path, help="默认 runtime/state/workspace/cli.json，必须在目标 runtime 内")
    args = parser.parse_args(argv)
    if os.name != "nt":
        raise ValueError("本轮安装器只验证 Windows；macOS 支持另行实施")
    if not args.workspace.is_absolute() or not args.wheels.is_absolute():
        raise ValueError("--workspace 和 --wheels 必须为绝对路径")
    if not args.release_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_" for c in args.release_id) or args.release_id in (".", ".."):
        raise ValueError("release-id 必须为单层标识")
    root = args.workspace.resolve()
    wheels = args.wheels.resolve()
    packages = wheel_packages(wheels)
    runtime = root / "runtime"
    if not (root / "dmy_vault").is_dir():
        if root.exists() and (not root.is_dir() or any(root.iterdir())):
            raise ValueError("目标非空且尚未初始化，已保留原内容；选择新的空目录")
        command = "import sys; sys.path[:0]=sys.argv[1:3]; from dummysys_cli.__main__ import main; raise SystemExit(main(['init','--workspace',sys.argv[3],'--json']))"
        process = subprocess.run([sys.executable, "-I", "-B", "-c", command, str(packages[0]), str(packages[1]), str(root)], capture_output=True)
        if process.returncode:
            sys.stdout.buffer.write(process.stdout)
            raise ValueError("工作区初始化失败；保留现场并查看 init.json")
    init_record = root / "runtime/state/workspace/init.json"
    if not init_record.is_file() or json.loads(init_record.read_text(encoding="utf-8")).get("status") != "completed":
        raise ValueError("目标未完成 dmy init；本安装器不迁移现用工作区")
    destination = contained(runtime / "envs" / args.release_id, runtime)
    evidence = contained(args.evidence or runtime / "state/cli/installations" / args.release_id, runtime)
    config = contained(args.config or runtime / "state/workspace/cli.json", runtime)
    if destination.exists() or evidence.exists():
        raise ValueError("发行或安装证据目录已存在；使用新 release-id，保留失败与回滚现场")
    if config.exists():
        value = json.loads(config.read_text(encoding="utf-8-sig"))
        if value.get("schema_version") != 1 or Path(value.get("workspace", "")).resolve() != root:
            raise ValueError("既有配置指向其他工作区，已保留原文件")
    evidence.mkdir(parents=True)
    env = os.environ.copy()
    for key in ("PYTHONPATH", "DMY_CONFIG", "DMY_EXE"):
        env.pop(key, None)
    env.update(PIP_CACHE_DIR=str(runtime / "cache/pip"), TEMP=str(runtime / "tmp"), TMP=str(runtime / "tmp"),
               PYTHONDONTWRITEBYTECODE="1")
    (runtime / "tmp").mkdir(exist_ok=True)
    def run(command, log):
        process = subprocess.run(command, env=env, capture_output=True)
        (evidence / log).write_bytes(process.stdout + process.stderr)
        if process.returncode:
            raise ValueError(f"安装步骤 {log} 失败（{process.returncode}）；保留现场，请使用新 release-id 重试")
        return process.stdout
    # 使用宿主 pip 驱动目标解释器，避免 ensurepip 在深层路径解包自身。
    run([sys.executable, "-m", "venv", "--without-pip", str(destination)], "venv.log")
    python = destination / "Scripts/python.exe"
    run([sys.executable, "-I", "-m", "pip", "--python", str(python), "install", "--disable-pip-version-check", "--no-compile", "--no-index", "--find-links", str(wheels), *map(str, packages)], "install.log")
    run([str(python), "-I", "-B", "-m", "dummysys_cli", "capabilities", "--json"], "installed-capabilities.json")
    actual = json.loads(run([str(python), "-I", "-c",
        "import json,sys,dummysys_core,dummysys_cli,workbench; print(json.dumps(dict(python=sys.executable,core=dummysys_core.__file__,cli=dummysys_cli.__file__,workbench=workbench.__file__)))"], "imports.json"))
    for name in ("core", "cli", "workbench"):
        if not Path(actual[name]).resolve().is_relative_to(destination):
            raise ValueError("安装模块未隔离在目标发行环境")
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in packages}
    identity = "wheel-sha256:" + hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    manifest_path = runtime / "state/workspace/cli-install.json"
    previous = json.loads(manifest_path.read_text(encoding="utf-8-sig")) if manifest_path.exists() else None
    sys.path.insert(0, str(destination / "Lib/site-packages"))
    from dummysys_core import __version__
    from dummysys_core.operations import workspace_lock, Operations
    with workspace_lock(root):
        if Operations(root).pending():
            raise ValueError("存在待恢复 Operation；先用原发行恢复，再安装")
        wb_config = runtime / "workbench/config.json"
        if not wb_config.is_file():
            raise ValueError("缺少初始化生成的 Workbench 配置")
        manifest = dict(schema_version=1, version=__version__, source_commit=identity, python=str(python),
                        core_path=str(destination / "Lib/site-packages"), previous=previous, wheels=hashes)
        atomic(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2))
        if not config.exists():
            atomic(config, json.dumps(dict(schema_version=1, workspace=str(root)), ensure_ascii=False, indent=2))
        launcher = runtime / "state/cli/bin/dmy.cmd"
        # Keep batch source ASCII: cmd decodes literal Chinese paths using its code page.
        # %~dp0 expands the Unicode launcher location without guessing the caller's CWD.
        atomic(launcher, '@echo off\nsetlocal DisableDelayedExpansion\n"%~dp0..\\..\\..\\envs\\' + args.release_id + '\\Scripts\\python.exe" -I -B -m dummysys_cli --workspace "%~dp0..\\..\\..\\.." %*\n')
        wb_launch = runtime / "workbench/bin/workbench.cmd"
        atomic(wb_launch, '@echo off\nsetlocal DisableDelayedExpansion\n"%~dp0..\\..\\envs\\' + args.release_id + '\\Scripts\\python.exe" -I -B -m workbench %* --config "%~dp0..\\config.json"\n')
        atomic(runtime / "workbench/source.json", json.dumps(dict(schema_version=1, mode="wheel",
               config=str(wb_config), env=str(destination), python=str(python), release_id=args.release_id), ensure_ascii=False, indent=2))
    result = dict(ok=True, launcher=str(launcher), workbench_launcher=str(wb_launch), python=str(python),
                  config=str(config), workbench_config=str(wb_config), manifest=str(manifest_path), evidence=str(evidence))
    atomic(evidence / "receipt.json", json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        print(json.dumps(dict(ok=False, error=str(error)), ensure_ascii=False))
        raise SystemExit(2)
