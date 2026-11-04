"""PyInstaller 入口：窗口化运行 workbench.launcher（无控制台）。

打包命令见 README 批次 D；构建产物 WorkbenchLauncher.exe 是快捷方式与
launch() 子进程分支（frozen）指向的稳定 GUI 入口。
"""
from __future__ import annotations

import sys

from workbench.launcher import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
