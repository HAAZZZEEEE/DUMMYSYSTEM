"""业务层和平台打开适配器共用的执行类型限制。"""

SCRIPT_EXTENSIONS = frozenset({
    '.exe', '.com', '.msi', '.msp', '.msix', '.appx', '.appinstaller', '.bat', '.cmd', '.ps1', '.psm1',
    '.vbs', '.vbe', '.js', '.jse', '.wsf', '.wsh', '.hta', '.lnk', '.url', '.sh',
    '.command', '.scpt', '.applescript', '.workflow', '.app',
    '.py', '.pyw', '.scr', '.cpl', '.reg', '.jar', '.application', '.gadget',
})
