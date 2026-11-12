"""Windows WebView2 desktop host."""
from .windows_identity import set_workbench_app_id

def prepare():
    set_workbench_app_id()
    import clr  # Select .NET Framework before pywebview's CoreCLR fallback.

def run(webview, window, lifecycle, record, icon):
    webview.start(gui='edgechromium', icon=icon,
                  storage_path=str(lifecycle.instance.state / 'webview'))
