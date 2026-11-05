# -*- mode: python ; coding: utf-8 -*-
# Slim build of Font Studio: bundles only the Qt pieces the app actually uses
# (QtCore / QtGui / QtWidgets + the Windows platform, style and .ico plugins).
# Build:  pyinstaller --noconfirm --clean packaging/fontstudio.spec
import os
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.win32 import versioninfo

# PyInstaller refuses to UPX DLLs built with Control Flow Guard (all Qt DLLs).
# UPX (with --strip-loadconf) packs them fine; this only drops the CFG hardening
# flag, it does not change behaviour. Qt *plugins* stay uncompressed (Qt must read
# their metadata), see upx_exclude / PyInstaller's own plugin check.
versioninfo.pefile_check_control_flow_guard = lambda *_a, **_k: False

from PyInstaller.utils import misc as _misc
_is_plugin = _misc.is_file_qt_plugin
# Qt6Core.dll embeds the plugin-metadata marker string, so PyInstaller wrongly
# treats it as a plugin; real plugins (plugins/...) are still left alone.
_misc.is_file_qt_plugin = lambda f: False if os.path.basename(f).lower() == 'qt6core.dll' else _is_plugin(f)

import subprocess as _sp
import PyInstaller.building.utils as _bu
_run = _sp.run
def _run_upx_force(cmd, *args, **kwargs):
    # UPX itself also refuses CFG files unless --force is given.
    if isinstance(cmd, list) and cmd and os.path.basename(str(cmd[0])).lower().startswith('upx') and '-V' not in cmd:
        cmd = [cmd[0], '--force', *cmd[1:]]
    return _run(cmd, *args, **kwargs)
_bu.subprocess = type('subprocess_shim', (), {**{k: getattr(_sp, k) for k in dir(_sp) if not k.startswith('__')}, 'run': staticmethod(_run_upx_force)})

ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))

# fontTools loads table modules dynamically (ttLib.tables._n_a_m_e, ...)
hidden = collect_submodules('fontTools.ttLib') + collect_submodules('fontTools.cffLib') + collect_submodules('fontTools.misc')

# Python / Qt modules the app never touches
excludes = [
    'tkinter', '_tkinter', 'unittest', 'pydoc', 'doctest', 'pdb', 'xmlrpc',
    'http.server', 'lib2to3', 'distutils', 'setuptools', 'pip', 'test',
    'numpy', 'matplotlib', 'PIL', 'scipy', 'pandas',
    'ssl', '_ssl', '_hashlib',
]
excludes += ['PySide6.' + m for m in (
    'QtNetwork', 'QtQml', 'QtQuick', 'QtQuickWidgets', 'QtSvg', 'QtSvgWidgets',
    'QtPdf', 'QtPdfWidgets', 'QtWebEngineCore', 'QtWebEngineWidgets', 'QtSql',
    'QtOpenGL', 'QtOpenGLWidgets', 'QtMultimedia', 'QtDBus', 'QtXml', 'QtTest',
    'QtPrintSupport', 'QtConcurrent', 'QtUiTools', 'QtDesigner', 'QtHelp',
    'QtStateMachine', 'QtCharts', 'QtDataVisualization', 'Qt3DCore',
)]

a = Analysis(
    [os.path.join(ROOT, 'font_studio.py')],
    pathex=[ROOT],
    datas=[(os.path.join(ROOT, 'assets', 'fontstudio.ico'), 'assets')],
    hiddenimports=hidden,
    excludes=excludes,
    noarchive=False,
    optimize=1,
)

# Keep only the Qt plugins needed for this widgets app on Windows.
KEEP_PLUGINS = {
    'platforms/qwindows.dll',             # Windows platform integration
    'styles/qmodernwindowsstyle.dll',     # native Windows 10/11 look
    'imageformats/qico.dll',              # window/taskbar icon (.ico)
}
DROP_DLLS = {
    'opengl32sw.dll', 'd3dcompiler_47.dll',      # software OpenGL fallback, unused
    'qt6network.dll', 'qt6svg.dll', 'qt6pdf.dll', # pulled in by hooks, not linked by Core/Gui/Widgets
    'qt6opengl.dll', 'qt6qml.dll', 'qt6quick.dll',
    'libcrypto-3.dll', 'libssl-3.dll',            # OpenSSL: app makes no network/TLS calls
    '_ssl.pyd', '_hashlib.pyd',                   # hashlib.sha256 falls back to the built-in _sha2
}

def keep(entry):
    dest = entry[0].replace(os.sep, '/')
    low = dest.lower()
    name = low.rsplit('/', 1)[-1]
    if name in DROP_DLLS:
        return False
    if name == 'ucrtbase.dll' or name.startswith('api-ms-win-'):
        return False                      # Universal CRT ships with Windows 10/11 (Qt 6's minimum)
    if '/translations/' in low or low.endswith('.qm'):
        return False                      # app never installs a QTranslator
    if '/plugins/' in low:
        rel = low.split('/plugins/', 1)[1]
        return rel in KEEP_PLUGINS
    return True

a.binaries = [b for b in a.binaries if keep(b)]
a.datas = [d for d in a.datas if keep(d)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='FontStudio',
    debug=False,
    strip=False,
    upx=True,
    upx_exclude=['api-ms-win-*.dll', 'ucrtbase.dll', 'msvcp140*.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'python3.dll', 'qwindows.dll'],
    runtime_tmpdir=None,
    console=False,
    icon=os.path.join(ROOT, 'assets', 'fontstudio.ico'),
)
