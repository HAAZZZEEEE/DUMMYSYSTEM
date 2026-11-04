"""从明确相邻的候选目录调用 wheel 安装器，不再建立 editable 安装。"""
import argparse
from pathlib import Path
import subprocess
import sys

CODE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CODE_ROOT.parent.parent


def resolve_cli_src(override=None):
    root = Path(override).resolve() if override else REPO_ROOT.parent / "dummysys-cli"
    if not (root / "scripts/install.py").is_file():
        raise ValueError("相邻候选 CLI 不存在；显式传 --cli-root")
    return root


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli-root", type=Path)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--wheels", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    args = parser.parse_args(argv)
    installer = resolve_cli_src(args.cli_root) / "scripts/install.py"
    return subprocess.call([sys.executable, "-I", "-B", str(installer), "--workspace", str(args.workspace),
                            "--wheels", str(args.wheels), "--release-id", args.release_id])


if __name__ == "__main__":
    raise SystemExit(main())
