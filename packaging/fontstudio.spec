# -*- mode: python ; coding: utf-8 -*-
"""Lean one-file Windows build for Font Studio.

Keep only the Qt modules and plugins used by the application.  The spec is
intentionally separate from font_studio.py so packaging changes do not alter
application behavior.
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

a = Analysis(
    ["font_studio.py"],
    pathex=[],
    binaries=[],
    datas=[("assets/fontstudio.ico", "assets")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "unittest",
        "pydoc",
        "ssl",
        "_ssl",
        "_hashlib",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DRender",
        "PySide6.Qt3DInput",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.QtNetwork",
        "PySide6.QtOpenGL",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuickWidgets",
        "PySide6.QtRemoteObjects",
        "PySide6.QtScxml",
        "PySide6.QtSensors",
        "PySide6.QtSerialPort",
        "PySide6.QtSql",
        "PySide6.QtSvg",
        "PySide6.QtTest",
        "PySide6.QtWebChannel",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebSockets",
        "PySide6.QtXml",
    ],
    noarchive=False,
)

# PySide6 hooks may collect optional Qt DLLs and plugin families.  Retain the
# three plugins needed for a native Windows widget window and ICO decoding.
required_qt_plugins = (
    "platforms/qwindows.dll",
    "styles/qmodernwindowsstyle.dll",
    "imageformats/qico.dll",
)
unneeded_dlls = {
    "opengl32sw.dll",
    "d3dcompiler_47.dll",
    "qt6network.dll",
    "qt6svg.dll",
    "libcrypto-3.dll",
    "libssl-3.dll",
    "_ssl.pyd",
    "_hashlib.pyd",
    "ucrtbase.dll",
}
filtered_binaries = []
for entry in a.binaries:
    destination = entry[0].replace("\\", "/").lower()
    basename = Path(destination).name.lower()
    if basename in unneeded_dlls or basename.startswith("api-ms-win-"):
        continue
    if "/qt/plugins/" in destination or "/plugins/" in destination:
        if not any(destination.endswith(plugin) for plugin in required_qt_plugins):
            continue
    filtered_binaries.append(entry)
a.binaries = filtered_binaries

# Qt translation catalogs are not loaded by this application.
a.datas = [
    entry for entry in a.datas
    if not entry[0].lower().endswith(".qm")
]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="FontStudio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=["assets/fontstudio.ico"],
)
