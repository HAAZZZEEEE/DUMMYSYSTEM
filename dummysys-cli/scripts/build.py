"""在显式输出目录构建 wheel；源码树保持只读。"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

CLI_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from packaging_env import packaging_environment, venv_python


def package_roots(workbench_root=None):
    """单仓的三个发行包；覆盖值只改变 Workbench 的来源。"""
    workbench = (workbench_root or CLI_ROOT.parent / 'dummysys/apps/workbench').resolve()
    packages = [CLI_ROOT / 'packages/core', CLI_ROOT / 'apps/cli', workbench]
    for path in packages:
        if not (path / 'pyproject.toml').is_file():
            raise ValueError(f'缺少明确的源码包：{path}；可用 --workbench-root 指定 Workbench')
    return packages


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="全新的 runtime 构建目录")
    parser.add_argument("--workbench-root", type=Path, help="默认同候选区的 dummysys/apps/workbench")
    parser.add_argument("--wheelhouse", type=Path, help="离线依赖 wheel 目录；指定后不访问包索引")
    parser.add_argument("--desktop", action="store_true", help="包含本机原生窗口依赖")
    args = parser.parse_args(argv)
    if not args.output.is_absolute():
        parser.error("--output 必须为绝对路径")
    output = args.output.resolve()
    packages = package_roots(args.workbench_root)
    if output.is_relative_to(CLI_ROOT.parent) or output.is_relative_to(packages[-1]):
        parser.error("构建输出必须在源码仓库之外")
    dependency_options = []
    if args.wheelhouse is not None:
        if not args.wheelhouse.is_absolute() or not args.wheelhouse.is_dir():
            parser.error("--wheelhouse 必须为已有的绝对目录")
        dependency_options = ['--no-index', '--find-links', str(args.wheelhouse.resolve())]
    if output.exists():
        parser.error("输出目录已存在；使用新目录保留历史构建")
    output.mkdir(parents=True)
    env = packaging_environment(output)
    (output / "tmp").mkdir()
    (output / "wheels").mkdir()
    def run(command, name, cwd=None):
        completed = subprocess.run(command, env=env, cwd=cwd, capture_output=True)
        (output / (name + ".log")).write_bytes(completed.stdout + completed.stderr)
        if completed.returncode:
            raise RuntimeError(f"{name} 失败，退出码 {completed.returncode}；现场保留于 {output}")
        return completed.stdout
    # 复用宿主 pip 定向安装，构建环境只保留后端，不再自带第二份 pip。
    run([sys.executable, "-I", "-m", "venv", "--without-pip", str(output / "env")], "venv")
    python = venv_python(output / "env")
    pip = [sys.executable, '-I', '-m', 'pip', '--python', str(python)]
    run([*pip, 'install', '--disable-pip-version-check', '--only-binary=:all:',
         *dependency_options, 'setuptools>=68', 'wheel'], 'build-deps')
    staged = []
    for i, p in enumerate(packages):
        destination = output / "sources" / str(i)
        shutil.copytree(p, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info", ".git", "build", "dist"))
        staged.append(str(destination))
    # 直接调用构建后端，避免 pip 临时缓存额外嵌套的长路径。
    for i, stage in enumerate(staged):
        run([str(python), "-I", "-B", "-c", "import sys; from setuptools.build_meta import build_wheel; build_wheel(sys.argv[1])",
             str(output / "wheels")], f"package-{i}", cwd=stage)
    built = sorted((output / "wheels").glob("*.whl"))
    run([*pip, "wheel", "--disable-pip-version-check", "--no-build-isolation",
         "--only-binary=:all:", *(["--no-binary=proxy-tools"] if args.wheelhouse is None else []), *dependency_options,
         "--wheel-dir", str(output / "wheels"), *(str(p) + ("[desktop]" if args.desktop and p.name.startswith("dummysys_workbench-") else "") for p in built)], "dependencies")
    # 同时保留构建后端 wheel，下次可直接用此目录离线重建。
    backend = json.loads(run([str(python), '-I', '-c',
        'import importlib.metadata as m,json;print(json.dumps({n:m.version(n) for n in ("setuptools","wheel")}))'],
        'backend-versions'))
    run([*pip, 'download', '--disable-pip-version-check', '--only-binary=:all:', *dependency_options,
         '--dest', str(output / 'wheels'), *(name+'=='+version for name,version in backend.items())], 'backend-wheels')
    receipt = dict(schema_version=1, status="completed",
                   offline=args.wheelhouse is not None, desktop=args.desktop, build_backend=backend,
                   wheels={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((output / "wheels").glob("*.whl"))})
    (output / "build.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(dict(ok=True, wheels=str(output / "wheels"), receipt=str(output / "build.json")), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(json.dumps(dict(ok=False, error=str(error)), ensure_ascii=False))
        raise SystemExit(2)
