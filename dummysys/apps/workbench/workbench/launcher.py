"""WorkbenchLauncher 窗口化入口（无控制台）。

快捷方式把 --config <绝对路径> 作为参数传入；缺省时按可执行文件位置推导
TASK_ROOT（发行布局 state/install/current/WorkbenchLauncher/WorkbenchLauncher.exe
向上四级）并加载 configs/workbench.local.json。launch 的子进程分支（serve）
也走本入口，由子命令分发。错误写入 exe 同目录 launcher.log 并弹窗提示。
"""
from __future__ import annotations

import sys
from pathlib import Path

SUBCOMMANDS = {
    "doctor", "launch", "serve", "window", "status", "stop", "restart",
    "install-shortcuts", "uninstall-shortcuts",
}


def _exe_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def default_config_path() -> Path:
    # 发行布局：.../task_root/state/install/current/WorkbenchLauncher/WorkbenchLauncher.exe
    exe_dir = _exe_dir()
    task_root = exe_dir.parent.parent.parent.parent
    return task_root / "configs" / "workbench.local.json"


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in SUBCOMMANDS:
        command = argv[0]
        rest = argv[1:]
    else:
        command = "launch"
        rest = argv
    config = None
    if "--config" in rest:
        index = rest.index("--config")
        if index + 1 < len(rest):
            config = rest[index + 1]
    if not config:
        config = str(default_config_path())
    args = [command, "--config", config, *rest]
    # 窗口化程序从快捷方式/任务栏启动时无继承的控制台句柄，sys.stdout 为 None；
    # 用空输出对象占位，避免子命令 print 结果时崩溃弹错。
    if sys.stdout is None:
        sys.stdout = _null_stream()
    if sys.stderr is None:
        sys.stderr = _null_stream()
    try:
        from .__main__ import main as cli_main
        exit_code = cli_main(args)
        if exit_code:
            _report_error(RuntimeError(f'{command} 执行失败，请查看工作台运行记录'))
        return exit_code
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    except Exception as error:  # 窗口化程序无控制台，错误必须可见
        _report_error(error)
        return 1


def _null_stream() -> object:
    import io
    return io.StringIO()


def _report_error(error: Exception) -> None:
    try:
        log = _exe_dir() / "launcher.log"
        log.write_text(str(error) + "\n", encoding="utf-8")
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, str(error), "DUMMYSYS 工作台启动失败", 0x10)
    except Exception:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
