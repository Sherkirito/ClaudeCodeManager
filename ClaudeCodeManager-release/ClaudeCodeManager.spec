# -*- mode: python ; coding: utf-8 -*-

import os
import sys

build_console = os.environ.get('CCM_BUILD_CONSOLE') == '1'
runtime_bin = os.path.join(sys.prefix, 'Library', 'bin')
runtime_dlls = [
    'libssl-3-x64.dll',
    'libcrypto-3-x64.dll',
    'ffi.dll',
    'sqlite3.dll',
    'libmpdec-4.dll',
    'liblzma.dll',
    'libbz2.dll',
    'libexpat.dll',
]

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[
        (os.path.join(runtime_bin, dll_name), '.')
        for dll_name in runtime_dlls
        if os.path.exists(os.path.join(runtime_bin, dll_name))
    ],
    datas=[
        ('static', 'static'),
        ('assets\\app-icon.ico', 'assets'),
    ],
    hiddenimports=[
        'webview.platforms.winforms',
        'webview.platforms.edgechromium',
        'clr_loader',
        'pythonnet',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        '_tkinter',
        'cryptography',
        'numpy',
        'PIL',
        'psutil',
        'tornado',
        'yaml',
        'webview.platforms.android',
        'webview.platforms.cef',
        'webview.platforms.cocoa',
        'webview.platforms.gtk',
        'webview.platforms.qt',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ClaudeCodeManager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=build_console,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets\\app-icon.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ClaudeCodeManager',
)
