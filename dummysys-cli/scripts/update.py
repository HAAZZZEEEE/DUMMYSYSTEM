"""从干净的 Git 提交构建并更新显式指定的已安装工作区。"""
from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import shlex
import site
import stat
import subprocess
import sys
import time
import urllib.request
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from install import atomic, contained, stage_release, wheel_packages
from packaging_env import packaging_environment


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def json_text(data):
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def run(args, *, cwd, log=None, allowed=(0,)):
    result = subprocess.run(list(map(str, args)), cwd=cwd, capture_output=True, timeout=600)
    if log:
        log.write_bytes(result.stdout + result.stderr)
    if result.returncode not in allowed:
        raise RuntimeError(f"命令退出 {result.returncode}，详情：{log or result.stderr.decode(errors='replace')}")
    return result.stdout.decode("utf-8")


def regular_file(path, runtime):
    if not path.resolve().is_relative_to(runtime) or any(
        p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
        for p in (path, *path.parents)
    ) or not path.is_file():
        raise ValueError(f"安装控制文件缺失或不在实际 runtime 中：{path}")


def launcher_bytes(path, old_python, python):
    text = path.read_bytes()
    if os.name == "nt":
        old = str(old_python.relative_to(old_python.parents[3])).encode()
        new = str(python.relative_to(python.parents[3])).encode()
    else:
        old = shlex.quote(str(old_python)).encode()
        new = shlex.quote(str(python)).encode()
    if text.count(old) != 1:
        raise ValueError(f"启动入口与现用发行登记不匹配：{path}")
    return text.replace(old, new)


def service_projects(lifecycle, python):
    from workbench.control_protocol import ControlProtocol

    record = lifecycle.instance.is_healthy()
    if not record:
        raise RuntimeError("Workbench 实例未就绪")
    origin = f"http://127.0.0.1:{record['port']}"
    client = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), urllib.request.ProxyHandler({})
    )
    with client.open(origin + "/healthz", timeout=5) as response:
        health = json.load(response)["data"]
    release = health["running_release"]
    if health["instance_id"] != record["instance_id"] or Path(release["python"]) != python:
        raise RuntimeError("Workbench 实际解释器或实例身份不匹配")
    token = lifecycle.pipe.request(
        ControlProtocol.REQUEST_TOKEN, expected_instance_id=record["instance_id"], expected_process=record
    )["token"]
    request = urllib.request.Request(
        origin + "/api/v1/session",
        data=json_text({"bootstrap_token": token}).encode(),
        headers={"Origin": origin, "Content-Type": "application/json"},
    )
    with client.open(request, timeout=5) as response:
        response.read()
    with client.open(origin + "/api/v1/projects", timeout=10) as response:
        projects = json.load(response)["data"]
    return {"instance_id": record["instance_id"], "release": release, "projects": len(projects["projects"])}


def start_service(lifecycle, python, config, runtime, log):
    from workbench.processes import spawn_background

    with log.open("wb") as output:
        process = spawn_background(
            [str(python), "-I", "-B", "-m", "workbench", "serve", "--config", str(config)],
            independent=True, stdin=subprocess.DEVNULL, stdout=output, stderr=output,
            env=packaging_environment(runtime),
        )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and process.poll() is None:
        if lifecycle.instance.is_healthy():
            return service_projects(lifecycle, python)
        time.sleep(0.2)
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=5)
    raise RuntimeError(f"Workbench 服务启动失败，详情：{log}")


def cutover(root, runtime, evidence, commit, release_id, python, core_path, hashes, identity, old):
    from dummysys_core import __version__
    from dummysys_core.operations import Operations, atomic_write, inventory, workspace_lock
    from dummysys_core.workspace import Workspace
    from workbench.config import load_config
    from workbench.lifecycle import Lifecycle

    manifest, source, cli, workbench = old["paths"]
    previous, registration = old["manifest"], old["source"]
    old_python = Path(previous["python"])
    config_path = Path(registration["config"])
    config = load_config(config_path)
    if Path(config["workspace_root"]).resolve() != root:
        raise ValueError("Workbench 配置指向其他工作区")
    lifecycle = Lifecycle(config)
    marker = runtime / "state/workspace/update-pending.json"
    replacement = {
        manifest: json_text(dict(schema_version=1, version=__version__, source_commit=identity,
                                 git_commit=commit, python=str(python), core_path=str(core_path),
                                 previous=previous, wheels=hashes)).encode(),
        source: json_text(dict(registration, env=str(python.parent.parent), python=str(python),
                               release_id=release_id)).encode(),
        cli: launcher_bytes(cli, old_python, python),
        workbench: launcher_bytes(workbench, old_python, python),
    }

    def write_controls(controls):
        for path, data in controls.items():
            regular_file(path, runtime)
            atomic_write(path, data)
            if os.name != "nt":
                path.chmod(modes[path])

    def stopped_controls(controls):
        guard = lifecycle.launch_mutex
        if not guard.acquire(timeout_ms=5000):
            raise RuntimeError("另一个 Workbench 启动请求正在执行")
        try:
            if lifecycle.instance.read_state()["state"] != "missing":
                raise RuntimeError("Workbench 未完全停止")
            if not lifecycle.mutex.acquire():
                raise RuntimeError("Workbench 正在启动")
            try:
                write_controls(controls)
            finally:
                lifecycle.mutex.release()
        finally:
            guard.release()

    baseline = json.loads(run([cli, "check", "--json"], cwd=evidence, log=evidence / "old-check.json",
                              allowed=(0, 1)))["data"]
    with workspace_lock(root):
        if marker.exists() or Operations(root).pending():
            raise RuntimeError("存在未完成的发行切换或治理 Operation，请先恢复")
        if any(path.read_bytes() != data for path, data in old["bytes"].items()):
            raise RuntimeError("固定入口在构建期间发生变化，请重新读取目标")
        controls = old["bytes"]
        modes = {path: stat.S_IMODE(path.stat().st_mode) for path in controls}
        checked = Workspace(root).check()
        stable_failures = lambda data: {json.dumps(item, sort_keys=True) for item in data["failures"]}
        if stable_failures(checked) - stable_failures(baseline) or checked["pending_operations"]:
            raise RuntimeError("候选发行新增治理问题，保留现用版本")
        before = {name: hashlib.sha256(data).hexdigest() for name, data in inventory(root).items()}
        was_running = lifecycle.status()["running"]
        if was_running:
            service_projects(lifecycle, old_python)

        for index, (path, data) in enumerate(controls.items()):
            (evidence / f"{index}.before").write_bytes(data)
            (evidence / f"{index}.after").write_bytes(replacement[path])
        atomic(evidence / "controls.json", json_text({"paths": [str(p) for p in controls],
                                                       "modes": list(modes.values()), "was_running": was_running}))
        atomic(marker, json_text({"commit": commit, "evidence": str(evidence)}))
        try:
            lifecycle.stop()
            stopped_controls(replacement)
            run([cli, "capabilities", "--json"], cwd=evidence, log=evidence / "fixed-cli.json")
            service = start_service(lifecycle, python, config_path, runtime, evidence / "new-service.log")
            status = json.loads(run([workbench, "status"], cwd=evidence, log=evidence / "fixed-workbench.json"))
            if status["instance_id"] != service["instance_id"]:
                raise RuntimeError("Workbench 固定入口未连接新版服务")
            if not was_running:
                lifecycle.stop()
            after = {name: hashlib.sha256(data).hexdigest() for name, data in inventory(root).items()}
            if before != after or any(path.read_bytes() != data for path, data in replacement.items()):
                raise RuntimeError("更新期间资料或控制入口发生并行变化")
            result = dict(ok=True, status="updated", commit=commit, release=release_id,
                          previous=registration["release_id"], wheels=hashes,
                          governance_failures=len(checked["failures"]), verified_records=len(before), service=service)
            atomic(evidence / "result.json", json_text(result))
            marker.unlink()
            return result
        except BaseException as error:
            failure = {"ok": False, "error": str(error), "rollback_verified": False}
            try:
                lifecycle.stop()
                if Operations(root).pending() or any(
                    path.read_bytes() not in (data, replacement[path]) for path, data in controls.items()
                ):
                    raise RuntimeError("存在并行写入，请按备份核对现场")
                stopped_controls(controls)
                if was_running:
                    start_service(lifecycle, old_python, config_path, runtime, evidence / "restore-service.log")
                run([cli, "capabilities", "--json"], cwd=evidence, log=evidence / "restore-cli.json")
                if any(path.read_bytes() != data for path, data in controls.items()):
                    raise RuntimeError("回退后的固定入口与备份不一致")
                failure["rollback_verified"] = True
                marker.unlink()
            except Exception as rollback_error:
                failure["rollback_error"] = str(rollback_error)
            atomic(evidence / "failure.json", json_text(failure))
            raise RuntimeError(f"更新失败，回退已验证：{failure['rollback_verified']}。详情：{evidence}") from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True, help="现用工作区绝对路径")
    parser.add_argument("--wheelhouse", type=Path, help="供构建复用的离线 wheel 目录")
    parser.add_argument("--desktop", action="store_true", help="随新发行安装原生窗口依赖")
    args = parser.parse_args()
    if not args.workspace.is_absolute() or not args.workspace.is_dir():
        parser.error("--workspace 必须是已有工作区的绝对路径")
    if os.name != "nt" and sys.platform != "darwin":
        parser.error("支持 Windows 和 macOS")
    root = args.workspace.resolve()
    if root != args.workspace or (hasattr(root, "is_junction") and root.is_junction()):
        parser.error("使用工作区的实际路径")
    repo = Path(__file__).resolve().parents[2]
    if run(["git", "status", "--porcelain"], cwd=repo).strip():
        raise ValueError("从目标提交建立干净的 Git worktree 后执行")
    commit = run(["git", "rev-parse", "HEAD"], cwd=repo).strip()

    # 用仓内现行位置契约识别已有安装，阶段性构建不执行 dmy init。
    core = repo / "dummysys-cli/packages/core/src"
    sys.path.insert(0, str(core))
    from dummysys_core.locations import load
    locations = load(root)
    runtime = locations.runtime
    if not locations.vault.is_dir() or not runtime.is_dir():
        raise ValueError("目标工作区缺少 Vault 或 runtime")
    suffix = ".cmd" if os.name == "nt" else ""
    paths = (
        runtime / "state/workspace/cli-install.json", runtime / "workbench/source.json",
        runtime / f"state/cli/bin/dmy{suffix}", runtime / f"workbench/bin/workbench{suffix}",
    )
    for path in paths:
        regular_file(path, runtime)
    controls = {path: path.read_bytes() for path in paths}
    manifest, source = [json.loads(controls[path].decode("utf-8-sig")) for path in paths[:2]]
    old_python = Path(manifest["python"])
    old_env = Path(source["env"])
    if (source["mode"] != "wheel" or old_python != Path(source["python"])
            or old_python.parent.parent != old_env or old_env.parent != runtime / "envs"
            or not old_python.is_file()):
        raise ValueError("CLI 与 Workbench 未指向同一受管发行")
    if (runtime / "state/workspace/update-pending.json").exists():
        raise RuntimeError("存在未完成的发行切换，请按 update-pending.json 核对恢复")
    old = dict(paths=paths, bytes=controls, manifest=manifest, source=source)

    if manifest.get("git_commit") == commit:
        for path in paths[2:]:
            launcher_bytes(path, old_python, old_python)
        run([paths[2], "capabilities", "--json"], cwd=root)
        run([paths[3], "status"], cwd=root)
        return dict(ok=True, status="already_current", commit=commit, release=source["release_id"])

    release_id = f"git-{commit[:12]}-{uuid.uuid4().hex[:6]}"
    evidence = contained(runtime / "state/cli/updates" / release_id, runtime)
    evidence.mkdir(parents=True)
    build = contained(evidence / "build", runtime)
    command = [sys.executable, "-I", "-B", repo / "dummysys-cli/scripts/build.py", "--output", build]
    if args.wheelhouse:
        command.extend(["--wheelhouse", args.wheelhouse])
    desktop = args.desktop or run(
        [old_python, "-I", "-B", "-c", "from importlib.util import find_spec; print(int(find_spec('webview') is not None))"],
        cwd=evidence,
    ).strip() == "1"
    if desktop:
        command.append("--desktop")
    run(command, cwd=repo, log=evidence / "build.log")
    if run(["git", "status", "--porcelain"], cwd=repo).strip() or run(
        ["git", "rev-parse", "HEAD"], cwd=repo
    ).strip() != commit:
        raise RuntimeError("源码在构建期间发生变化")
    wheels = build / "wheels"
    destination = contained(runtime / "envs" / release_id, runtime)
    python, core_path, hashes, identity = stage_release(
        runtime, destination, evidence / "install", wheels, wheel_packages(wheels), desktop
    )
    # 切换只加载刚核验的发行。此处尚未加载 core 的治理实现。
    for name in tuple(sys.modules):
        if name == "dummysys_core" or name.startswith("dummysys_core."):
            del sys.modules[name]
    sys.path.remove(str(core))
    sys.path.insert(0, str(core_path))
    site.addsitedir(str(core_path))
    return cutover(root, runtime, evidence, commit, release_id, python, core_path, hashes, identity, old)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    try:
        print(json_text(main()), end="")
    except Exception as error:
        print(json_text({"ok": False, "error": str(error)}), file=sys.stderr, end="")
        raise SystemExit(2)
