"""快捷方式安装与撤销。

桌面与开始菜单 .lnk 指向稳定 WorkbenchLauncher.exe，传配置绝对路径，使用统一
AppUserModelID。安装清单记录创建位置与目标；撤销仅移除清单记录且目标仍匹配的
快捷方式。通过 Windows Shell COM 创建 .lnk，避免手工写二进制格式。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .windows import OpenFailed

APPUSERMODEL_ID = "dummysys.workbench"
MANIFEST_NAME = "install-manifest.json"
SHORTCUT_NAME = "DUMMYSYS 工作台.lnk"


def _desktop_dir() -> Path:
    import ctypes
    from ctypes import wintypes
    buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
    # CSIDL_DESKTOPDIRECTORY=0x10；用 Known Folder 探测，避免假定未重定向
    try:
        ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf)
        return Path(buf.value)
    except Exception:
        return Path(os.path.join(os.path.expanduser("~"), "Desktop"))


def _start_menu_dir() -> Path:
    import ctypes
    from ctypes import wintypes
    buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
    try:
        # CSIDL_PROGRAMS=0x02：当前用户 Start Menu\Programs，无需管理员权限。
        # CSIDL_STARTMENU(0x16) 是 All Users 目录，普通进程写入会拒绝访问。
        ctypes.windll.shell32.SHGetFolderPathW(None, 0x02, None, 0, buf)
        return Path(buf.value)
    except Exception:
        return Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs"


def _create_shortcut(lnk_path: Path, target: str, arguments: str) -> None:
    import win32com.client
    shell = win32com.client.Dispatch("WScript.Shell")
    lnk = shell.CreateShortCut(str(lnk_path))
    lnk.TargetPath = target
    lnk.Arguments = arguments
    lnk.WorkingDirectory = str(Path(target).parent)
    lnk.IconLocation = f"{target},0"
    lnk.Description = "DUMMYSYS 工作台"
    lnk.save()


def install_shortcuts(instance, launcher_exe: str, opener=None) -> dict:
    launcher = Path(launcher_exe)
    if not launcher.is_file():
        raise OpenFailed(f"启动器不存在：{launcher}")
    install_dir = instance.install_path
    install_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = install_dir / MANIFEST_NAME
    manifest = {}
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {}

    config_args = f'--config "{instance.config["config_path"]}"'
    entries = []
    for kind, folder in (("desktop", _desktop_dir()), ("start_menu", _start_menu_dir())):
        target_dir = folder
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        lnk_path = target_dir / SHORTCUT_NAME
        try:
            _create_shortcut(lnk_path, str(launcher), config_args)
        except Exception as error:
            entries.append({"kind": kind, "path": str(lnk_path), "created": False, "error": str(error)})
            continue
        entries.append({"kind": kind, "path": str(lnk_path), "created": True, "error": None})
        manifest[str(lnk_path)] = {"kind": kind, "target": str(launcher), "arguments": config_args,
                                   "app_user_model_id": APPUSERMODEL_ID}

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"entries": entries, "manifest": str(manifest_path)}


def uninstall_shortcuts(instance) -> dict:
    install_dir = instance.install_path
    manifest_path = install_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        return {"entries": [], "reason": "没有安装清单，无需撤销"}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"entries": [], "reason": "安装清单损坏，跳过撤销"}
    removed = []
    kept = {}
    for path, info in manifest.items():
        lnk = Path(path)
        if not lnk.is_file():
            kept[path] = info
            continue
        # 目标匹配才撤销，避免删除用户其他入口
        try:
            import win32com.client
            shell = win32com.client.Dispatch("WScript.Shell")
            target = shell.CreateShortCut(str(lnk)).TargetPath
        except Exception:
            target = None
        if target and Path(target).resolve() == Path(info.get("target", "")).resolve():
            try:
                lnk.unlink()
                removed.append({"path": path, "removed": True})
            except OSError as error:
                kept[path] = info
                removed.append({"path": path, "removed": False, "error": str(error)})
        else:
            kept[path] = info
            removed.append({"path": path, "removed": False, "reason": "目标不匹配，保留"})
    if kept:
        manifest_path.write_text(json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        try:
            manifest_path.unlink()
        except OSError:
            pass
    return {"entries": removed}
