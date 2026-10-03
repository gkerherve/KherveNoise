"""What KherveNoise.spec (Windows) and KherveNoiseMAC.spec (macOS) share.

Both specs import this, so the module list, the data files and the
excludes cannot drift apart between the two platforms.

Copyright (C) 2026 Gwilherm Kerherve
Licensed under the GNU General Public License v3.0 (see LICENSE).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_NAME = "KherveNoise"
ENTRY = str(ROOT / "KherveNoise.py")
VERSION_FILE = ROOT / "khervenoise" / "VERSION"

#: Other Qt bindings / toolkits and heavy dev-only packages. KherveNoise is
#: PySide6-only; two Qt bindings in one bundle break at start-up.
EXCLUDES = [
    "PyQt5", "PyQt6", "PySide2", "tkinter", "_tkinter",
    "scipy", "IPython", "jedi", "notebook", "jupyter_client",
    "pytest", "_pytest", "setuptools", "pip",
    # PySide6 add-ons the app never touches (keep the bundle small)
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
    "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia",
    "PySide6.QtBluetooth", "PySide6.QtPositioning", "PySide6.QtSql",
]


def stamp_version():
    """Write khervenoise/VERSION from git (a frozen build has no .git) and
    return (full, short): '0.1.N+sha' and '0.1.N'."""
    sys.path.insert(0, str(ROOT))
    from khervenoise._version import git_version
    full = git_version(ROOT)
    VERSION_FILE.write_text(full, encoding="ascii")
    return full, full.split("+")[0]


def icons():
    """(ico, icns) under build/, rendered from the app's own mark."""
    ico = ROOT / "build" / f"{APP_NAME}.ico"
    icns = ROOT / "build" / f"{APP_NAME}.icns"
    if not (ico.is_file() and icns.is_file()):
        sys.path.insert(0, str(ROOT / "packaging"))
        from make_icons import build_icons
        build_icons(ROOT / "build")
    return str(ico), str(icns)


def analysis_inputs():
    """(datas, binaries, hiddenimports) for Analysis()."""
    from PyInstaller.utils.hooks import collect_data_files, collect_submodules

    datas = [
        # help.py reads <bundle>/docs/USER_GUIDE.md
        (str(ROOT / "docs" / "USER_GUIDE.md"), "docs"),
        (str(ROOT / "LICENSE"), "."),
        (str(VERSION_FILE), "khervenoise"),
    ]
    binaries = []
    # The vendor readers, the MCP stack, the updater and every dialog are
    # imported lazily (importlib / inside functions), so static analysis
    # alone would leave them out.
    hiddenimports = collect_submodules("khervenoise") + [
        "PySide6.QtNetwork",                    # MCP bridge (QTcpServer)
        "matplotlib.backends.backend_qtagg",
        "matplotlib.backends.backend_svg",      # Save Figure as SVG
        "matplotlib.backends.backend_pdf",      # ... and PDF
        "pywt", "pywt._extensions._cwt",
        "vamas", "olefile",
        "openpyxl", "openpyxl.cell._writer", "xlrd",
        "pandas", "numpy",
    ]
    datas += collect_data_files("vamas")
    # h5py is optional (Diamond NeXus, Scienta HDF5): bundle it when present.
    try:
        import h5py  # noqa: F401
        hiddenimports += collect_submodules("h5py")
    except ImportError:
        print("KherveNoise spec: h5py not installed - building without NeXus / HDF5 import")
    return datas, binaries, hiddenimports
