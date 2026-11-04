"""业务层和 Windows 打开适配器共用的执行类型限制。"""

SCRIPT_EXTENSIONS = frozenset({
    '.exe', '.com', '.msi', '.msp', '.msix', '.appx', '.appinstaller', '.bat', '.cmd', '.ps1', '.psm1',
    '.vbs', '.vbe', '.js', '.jse', '.wsf', '.wsh', '.hta', '.lnk', '.url', '.sh',
    '.py', '.pyw', '.scr', '.cpl', '.reg', '.jar', '.application', '.gadget',
})
