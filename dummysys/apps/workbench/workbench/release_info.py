"""源码位置与提交只读展示，不参与实例身份判断。"""
from __future__ import annotations

import json
import hashlib
import subprocess
import sys
from pathlib import Path

from . import __version__
from .processes import run_background


def release_info(config: dict | None = None) -> dict:
    source_path = Path(__file__).resolve().parent.parent
    sha = None
    version = __version__
    checkout = (source_path / "pyproject.toml").is_file()
    source = "source-checkout" if checkout else "wheel"
    if getattr(sys, "frozen", False):
        source = "frozen"
        try:
            saved = json.loads((source_path / "release.json").read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                sha, version = saved.get("sha"), saved.get("version") or version
        except (OSError, ValueError):
            pass
    elif checkout and (source_path.parents[1] / ".git").exists():
        try:
            result = run_background(["git", "rev-parse", "HEAD"], cwd=source_path,
                                    capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                sha = result.stdout.strip() or None
        except (OSError, subprocess.TimeoutExpired):
            pass
    fingerprint=hashlib.sha256()
    try:
        for file in sorted((source_path/'workbench').glob('*.py')):
            fingerprint.update(file.name.encode()); fingerprint.update(file.read_bytes())
        signature=fingerprint.hexdigest()
    except OSError:
        signature=None
    return {"source_fingerprint":signature, "python":sys.executable, "version": version, "sha": sha, "short_sha": str(sha)[:7] if sha else None,
            "source": source, "source_path": str(source_path),
            "install_source": {"source-checkout": "源码检出 ", "frozen": "冻结安装包 ", "wheel": "wheel 安装包 "}[source] + str(source_path)}
