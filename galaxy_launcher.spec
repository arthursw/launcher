# -*- mode: python ; coding: utf-8 -*-
import platform

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('galaxy/galaxy.yml', 'galaxy'),
        ('galaxy/icon_128x128.png', 'resources/'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='galaxy',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[
        'galaxy/galaxy.icns'
        if platform.system() == 'Darwin'
        else 'galaxy/icon_128x128.png'
    ],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='galaxy',
)
if platform.system() == 'Darwin':
    app = BUNDLE(
        coll,
        name='Galaxy.app',
        icon='galaxy/galaxy.icns',
        bundle_identifier=None,
    )
