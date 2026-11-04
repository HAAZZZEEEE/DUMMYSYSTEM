"""在显式输出目录构建 wheel；源码树保持只读。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

CLI_ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="全新的 runtime 构建目录")
    parser.add_argument("--workbench-root", type=Path, help="默认同候选区的 dummysys/apps/workbench")
    args = parser.parse_args(argv)
    if not args.output.is_absolute():
        parser.error("--output 必须为绝对路径")
    output = args.output.resolve()
    wb = (args.workbench_root or CLI_ROOT.parent / "dummysys/apps/workbench").resolve()
    packages = [CLI_ROOT / "packages/core", CLI_ROOT / "apps/cli", wb]
    for p in packages:
        if not (p / "pyproject.toml").is_file():
            parser.error(f"缺少明确的相邻源码：{p}；可用 --workbench-root 覆盖")
        if output.is_relative_to(p):
            parser.error("构建输出必须在源码目录之外")
    if output.exists():
        parser.error("输出目录已存在；使用新目录保留历史构建")
    output.mkdir(parents=True)
    env = os.environ.copy()
    env.update(PIP_CACHE_DIR=str(output / "cache"), TEMP=str(output / "tmp"), TMP=str(output / "tmp"),
               PYTHONDONTWRITEBYTECODE="1")
    (output / "tmp").mkdir()
    (output / "wheels").mkdir()
    def run(command, name, cwd=None):
        completed = subprocess.run(command, env=env, cwd=cwd, capture_output=True)
        (output / (name + ".log")).write_bytes(completed.stdout + completed.stderr)
        if completed.returncode:
            raise RuntimeError(f"{name} 失败，退出码 {completed.returncode}；现场保留于 {output}")
    run([sys.executable, "-m", "venv", str(output / "env")], "venv")
    python = output / "env/Scripts/python.exe"
    run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "setuptools>=68", "wheel"], "build-deps")
    staged = []
    for i, p in enumerate(packages):
        destination = output / "sources" / str(i)
        shutil.copytree(p, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info", ".git", "build", "dist"))
        staged.append(str(destination))
    # 直接调用构建后端，避免 pip 临时缓存额外嵌套的长路径。
    for i, stage in enumerate(staged):
        run([str(python), "-B", "-c", "import sys; from setuptools.build_meta import build_wheel; build_wheel(sys.argv[1])",
             str(output / "wheels")], f"package-{i}", cwd=stage)
    built = sorted((output / "wheels").glob("*.whl"))
    run([str(python), "-m", "pip", "download", "--disable-pip-version-check", "--only-binary=:all:",
         "--dest", str(output / "wheels"), *map(str, built)], "dependencies")
    receipt = dict(schema_version=1, status="completed",
                   wheels={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((output / "wheels").glob("*.whl"))})
    (output / "build.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(dict(ok=True, wheels=str(output / "wheels"), receipt=str(output / "build.json")), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError) as error:
        print(json.dumps(dict(ok=False, error=str(error)), ensure_ascii=False))
        raise SystemExit(2)
