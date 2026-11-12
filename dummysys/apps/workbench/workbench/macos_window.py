"""Cocoa host: closing hides, Dock reopens, Quit stops this workspace service."""
import threading
from .identity import identity_matches
from .macos_identity import process_identity, current_user_sid
from .macos_control import PipeControl


def native_ready(record):
    try:
        return (record.get('user_sid') == current_user_sid()
                and identity_matches(process_identity(record.get('pid')), record))
    except (OSError, ValueError, RuntimeError):
        return False


def activate(config, record):
    if not native_ready(record):
        return False
    # The private window channel uses the same peer/instance checks as the service.
    response = PipeControl(config['task_root'], purpose='window').request(
        PipeControl.REQUEST_TOKEN, expected_instance_id=record['instance_id'], expected_process=record)
    return response.get('token') == 'activated'


def prepare():
    from Foundation import NSProcessInfo
    NSProcessInfo.processInfo().setProcessName_('DUMMYSYS')


def run(webview, window, lifecycle, record, icon):
    import AppKit
    from PyObjCTools import AppHelper
    quitting = threading.Event()
    stopped = threading.Event()
    channel = PipeControl(lifecycle.config['task_root'], purpose='window')

    def reopen():
        window.restore()
        window.show()
        return 'activated'

    def close_window():
        if quitting.is_set():
            return True
        window.hide()
        return False

    def quit_app():
        if quitting.is_set():
            return
        quitting.set()
        def stop():
            try:
                result = lifecycle.stop(wait_stopped=15)
            except (OSError, RuntimeError):
                result = {}
            if (result.get('stopped') or result.get('stale_record_cleared')
                    or result.get('reason') == '没有运行中的工作台实例'):
                window.destroy()
            else:
                quitting.clear()
                AppHelper.callAfter(AppKit.NSBeep)
        threading.Thread(target=stop, daemon=True).start()

    class WorkbenchDelegate(AppKit.NSObject):
        def applicationShouldTerminate_(self, app):
            quit_app()
            return AppKit.NSTerminateCancel

        def applicationShouldHandleReopen_hasVisibleWindows_(self, app, visible):
            reopen()
            return True

        def applicationSupportsSecureRestorableState_(self, app):
            return True

    delegate = WorkbenchDelegate.alloc().init()

    def configure():
        AppKit.NSApplication.sharedApplication().setDelegate_(delegate)
        if icon:
            image = AppKit.NSImage.alloc().initWithContentsOfFile_(icon)
            if image:
                AppKit.NSApplication.sharedApplication().setApplicationIconImage_(image)

    def shown():
        AppHelper.callAfter(configure)

    def monitor():
        # A CLI stop/restart must close the old window too.
        while not stopped.wait(0.5):
            healthy = lifecycle.instance.is_healthy()
            if not healthy or healthy['instance_id'] != record['instance_id']:
                quitting.set()
                window.destroy()
                return

    window.events.closing += close_window
    window.events.shown += shown
    channel.start_server(reopen, record['instance_id'])
    watcher = threading.Thread(target=monitor, daemon=True)
    watcher.start()
    try:
        webview.start(gui='cocoa', storage_path=str(lifecycle.instance.state / 'webview'))
    finally:
        stopped.set()
        channel.stop_server()
        watcher.join(timeout=2)
