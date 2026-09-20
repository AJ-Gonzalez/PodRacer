# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['src/podracer/main.py'],
    pathex=['src', 'packages/podracer_db/src'],
    binaries=[],
    datas=[('src/podracer/fonts', 'podracer/fonts'), ('src/podracer/assets', 'podracer/assets')],
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
    name='PodRacer',
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
    icon=['src/podracer/assets/podracer_icon.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PodRacer',
)
app = BUNDLE(
    coll,
    name='PodRacer.app',
    icon='src/podracer/assets/podracer_icon.icns',
    bundle_identifier='io.github.ajgonzalez.PodRacer',
)
