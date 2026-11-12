"""工作台 CLI：doctor / launch / serve / status / stop / restart / install-shortcuts / uninstall-shortcuts。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _config(path: str) -> dict:
    from .config import load_config
    return load_config(path)


def _print(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def cmd_doctor(args) -> int:
    from .config import load_config
    from .platform_runtime import create_opener
    config = load_config(args.config)
    opener = create_opener(config)
    probe = opener.probe()
    result = {
        "schema_version": config["schema_version"],
        "workspace_root": str(config["workspace_root"]),
        "task_root": str(config["task_root"]),
        "port": config["port"],
        "apps": probe,
    }
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    _print(result)
    return 0


def cmd_launch(args) -> int:
    from importlib.util import find_spec
    browser_mode = getattr(args, 'browser', False)
    if not browser_mode and find_spec('webview') is None:
        _print({'error': '原生窗口需要可选 desktop 依赖；可使用 launch --browser 启动浏览器工作台。',
                'code': 'OPTIONAL_APP_UNAVAILABLE'})
        return 1
    config = _config(args.config)
    from .lifecycle import Lifecycle
    lifecycle = Lifecycle(config)
    try:
        if browser_mode:
            from .platform_runtime import create_opener
            opener = create_opener(config)
            opener.supports_native_window = False
            result = lifecycle.launch(opener=opener)
        else:
            result = lifecycle.launch()
    except RuntimeError as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    _print(result)
    return 0 if result.get('window_dispatched') else 1


def cmd_serve(args) -> int:
    config = _config(args.config)
    from .lifecycle import Lifecycle
    lifecycle = Lifecycle(config)
    try:
        lifecycle.serve(None, port=args.port)
    except RuntimeError as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


def cmd_window(args) -> int:
    config = _config(args.config)
    from .window_host import show
    try:
        show(config, args.instance_id)
    except Exception as error:
        # The windowed executable has no stderr; keep a token-free diagnostic.
        from .lifecycle import state_dir
        path = state_dir(config) / "window-error.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{type(error).__name__}\n", encoding="utf-8")
        print(json.dumps({"error": "工作台窗口启动失败"}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


def cmd_status(args) -> int:
    config = _config(args.config)
    from .lifecycle import Lifecycle
    lifecycle = Lifecycle(config)
    _print(lifecycle.status())
    return 0


def cmd_stop(args) -> int:
    config = _config(args.config)
    from .lifecycle import Lifecycle
    lifecycle = Lifecycle(config)
    result = lifecycle.stop()
    _print(result)
    return 0 if result.get('stopping') or result.get('reason') == '没有运行中的工作台实例' else 1


def cmd_restart(args) -> int:
    """停止当前实例并重新启动开窗。供 /api/v1/restart 派生的子进程与命令行共用。"""
    config = _config(args.config)
    from .lifecycle import Lifecycle
    lifecycle = Lifecycle(config)
    try:
        # 旧实例可能仍在收尾，放宽停止等待；无实例时 stop 返回 reason，仍继续启动。
        lifecycle.stop(wait_stopped=15.0)
    except RuntimeError as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    try:
        result = lifecycle.launch()
    except RuntimeError as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    _print(result)
    return 0 if result.get('window_dispatched') else 1


def cmd_install_shortcuts(args) -> int:
    config = _config(args.config)
    from .lifecycle import Lifecycle
    lifecycle = Lifecycle(config)
    try:
        result = lifecycle.install_shortcuts(args.launcher)
    except Exception as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    _print(result)
    return 0


def cmd_uninstall_shortcuts(args) -> int:
    config = _config(args.config)
    from .lifecycle import Lifecycle
    lifecycle = Lifecycle(config)
    _print(lifecycle.uninstall_shortcuts())
    return 0


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    # --config 在主解析器与各子命令均可出现（启动器契约：serve --config <绝对路径>）。
    # SUPPRESS：子命令未带 --config 时不得用默认值覆盖主解析器已解析的值。
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default=argparse.SUPPRESS,
                        help="显式配置文件路径；相对配置项以该文件所在目录解析")
    parser = argparse.ArgumentParser(prog="workbench", description="DUMMYSYS 工作台", parents=[common])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("doctor", parents=[common], help="检测本机应用与配置可用性")
    p.add_argument("--output", help="预检结果 JSON 输出路径")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("launch", parents=[common], help="启动或复用工作台并打开窗口")
    p.add_argument('--browser', action='store_true', help='使用浏览器窗口；无需可选原生桌面依赖')
    p.set_defaults(func=cmd_launch)

    p = sub.add_parser("serve", parents=[common], help="仅由启动器调用：运行本地服务")
    p.add_argument("--port", type=int, default=None)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("window", parents=[common], help="仅由启动器调用：打开原生工作台窗口")
    p.add_argument("--instance-id", required=True)
    p.set_defaults(func=cmd_window)

    p = sub.add_parser("status", parents=[common], help="输出本实例状态，不打印令牌")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("stop", parents=[common], help="认证后停止自己的实例")
    p.set_defaults(func=cmd_stop)

    p = sub.add_parser("restart", parents=[common], help="停止当前实例并重新启动开窗")
    p.set_defaults(func=cmd_restart)

    p = sub.add_parser("install-shortcuts", parents=[common], help="安装桌面与开始菜单快捷方式")
    p.add_argument("--launcher", required=True, help="稳定 WorkbenchLauncher.exe 路径")
    p.set_defaults(func=cmd_install_shortcuts)

    p = sub.add_parser("uninstall-shortcuts", parents=[common], help="仅撤销安装清单且目标匹配的快捷方式")
    p.set_defaults(func=cmd_uninstall_shortcuts)

    args = parser.parse_args(argv)
    if not getattr(args, "config", None):
        # 从配置示例推断：doctor 无 config 时先报错，引导显式传入
        parser.error("缺少 --config，请传入配置文件绝对路径")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
