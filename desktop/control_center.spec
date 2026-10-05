# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for SentinelOps Windows Control Center."""

import sys
from pathlib import Path

block_cipher = None

repo_root = Path(SPECPATH).parent.resolve()

a = Analysis(
    [str(repo_root / "desktop" / "main.py")],
    pathex=[str(repo_root)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
        "desktop.config",
        "desktop.api.client",
        "desktop.api.models",
        "desktop.state.app_state",
        "desktop.state.signals",
        "desktop.ui.main_window",
        "desktop.ui.styles",
        "desktop.workers.poller",
        "desktop.workers.task_runner",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "numpy",
        "scipy",
        "android",
        "tests",
        "runtime",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SentinelOpsControlCenter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # Keep console enabled for diagnostics and --help CLI output
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="SentinelOpsControlCenter",
)
