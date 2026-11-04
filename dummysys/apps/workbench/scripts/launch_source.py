"""兼容的显式入口：仅启动目标 runtime 登记的 wheel 安装。"""
import argparse
import json
import os
from pathlib import Path
import subprocess

COMMANDS = ("serve", "launch", "status", "stop", "restart", "doctor")


def _report(message):
    print(json.dumps(dict(ok=False, error=message), ensure_ascii=False))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("command", choices=COMMANDS, nargs="?", default="serve")
    args, remaining = parser.parse_known_args(argv)
    try:
        if not args.runtime_root.is_absolute():
            raise ValueError("--runtime-root 必须为绝对路径")
        runtime = args.runtime_root.resolve()
        saved = json.loads((runtime / "source.json").read_text(encoding="utf-8"))
        if not isinstance(saved, dict) or saved.get("mode") != "wheel":
            raise ValueError("需要目标工作区的 wheel 安装记录")
        python, config = Path(saved["python"]), Path(saved["config"])
        workspace_runtime = runtime.parent
        if not python.is_absolute() or not config.is_absolute() or not python.resolve().is_relative_to(workspace_runtime) or not config.resolve().is_relative_to(runtime):
            raise ValueError("安装记录越出目标 runtime")
        if not python.is_file() or not config.is_file():
            raise ValueError("登记解释器或配置不存在")
        if "--config" in remaining:
            raise ValueError("入口配置固定于目标工作区；独立实例直接使用 workbench --config")
        env = os.environ.copy()
        for key in ("PYTHONPATH", "DMY_EXE", "DMY_CONFIG"):
            env.pop(key, None)
        return subprocess.call([str(python), "-I", "-B", "-m", "workbench", args.command,
                                *remaining, "--config", str(config)], cwd=runtime, env=env)
    except (OSError, ValueError, KeyError, TypeError) as error:
        _report(str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
