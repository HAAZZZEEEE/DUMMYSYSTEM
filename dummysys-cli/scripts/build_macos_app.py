"""Freeze the installed Workbench into a relocatable macOS .app; retain build evidence."""
import argparse
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New build directory outside the repository')
    parser.add_argument('--config', type=Path, required=True, help='Installed Workbench config')
    parser.add_argument('--install-to', type=Path, help='New destination ending in .app')
    args = parser.parse_args(argv)
    if sys.platform != 'darwin':
        parser.error('This builder requires macOS')
    for path in (args.output, args.config, args.install_to):
        if path is not None and not path.is_absolute():
            parser.error('All paths must be absolute')
    if args.output.exists() or args.output.resolve().is_relative_to(Path(__file__).resolve().parents[2]):
        parser.error('Use a new output directory outside the repository')
    if not args.config.is_file():
        parser.error('Workbench config does not exist')
    if args.install_to and (args.install_to.exists() or args.install_to.suffix != '.app'):
        parser.error('Install destination must be a new .app path')
    import workbench
    from workbench.config import load_config
    from workbench.dmy import resolve_command
    _, source = resolve_command(load_config(args.config)['workspace_root'])
    if source != 'registered':
        parser.error('Install the workspace first; the .app requires its registered CLI environment')
    args.output.mkdir(parents=True)
    entry = args.output / 'desktop_entry.py'
    entry.write_text('from workbench.launcher import main\nraise SystemExit(main())\n', encoding='utf-8')
    iconset = args.output / 'DUMMYSYS.iconset'
    iconset.mkdir()
    svg = Path(workbench.__file__).parent / 'static/icons/app-icon.svg'
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            target = iconset / f'icon_{size}x{size}{"@2x" if scale == 2 else ""}.png'
            subprocess.run(['/usr/bin/sips', '-s', 'format', 'png', '-z', str(size*scale),
                            str(size*scale), str(svg), '--out', str(target)], check=True,
                           stdout=subprocess.DEVNULL)
    icon = args.output / 'DUMMYSYS.icns'
    subprocess.run(['/usr/bin/iconutil', '-c', 'icns', str(iconset), '-o', str(icon)], check=True)
    command = [sys.executable, '-I', '-m', 'PyInstaller', '--noconfirm', '--windowed', '--name', 'DUMMYSYS',
               '--icon', str(icon), '--osx-bundle-identifier', 'org.dummysys.workbench', '--distpath', str(args.output / 'dist'),
               '--workpath', str(args.output / 'build'), '--specpath', str(args.output),
               '--collect-all', 'workbench', '--collect-all', 'dummysys_core', '--collect-all', 'dummysys_cli',
               '--collect-data', 'webview',
               '--hidden-import', 'webview.platforms.cocoa', '--hidden-import', 'Foundation',
               '--hidden-import', 'AppKit', '--hidden-import', 'WebKit', str(entry)]
    with (args.output / 'build.log').open('wb') as log:
        subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT, cwd=args.output)
    bundle = args.output / 'dist/DUMMYSYS.app'
    webview_js = bundle / 'Contents/Frameworks/webview/js'
    if not any(webview_js.rglob('*.js')):
        raise RuntimeError('The app bundle is missing pywebview JavaScript assets')
    (bundle / 'Contents/Resources/workbench-config.json').write_text(
        json.dumps({'config': str(args.config)}, ensure_ascii=False), encoding='utf-8')
    info_path = bundle / 'Contents/Info.plist'
    info = plistlib.loads(info_path.read_bytes())
    info.update(CFBundleDisplayName='DUMMYSYS', NSHighResolutionCapable=True)
    info_path.write_bytes(plistlib.dumps(info))
    subprocess.run(['/usr/bin/codesign', '--force', '--deep', '--sign', '-', str(bundle)], check=True,
                   stdout=subprocess.DEVNULL)
    target = bundle
    if args.install_to:
        args.install_to.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(bundle, args.install_to, symlinks=True)
        target = args.install_to
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(target)], check=True)
    receipt = {'ok': True, 'app': str(target), 'config': str(args.config), 'python': sys.executable,
               'source': workbench.__file__, 'signing': 'local-ad-hoc', 'log': str(args.output / 'build.log')}
    (args.output / 'receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
