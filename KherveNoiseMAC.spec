# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for KherveNoise on macOS.
#
#   .venv/bin/pip install pyinstaller
#   .venv/bin/pyinstaller KherveNoiseMAC.spec --noconfirm
#     -> dist/KherveNoise.app
#
# Builds for the Mac it runs on (Apple Silicon or Intel). PyInstaller signs
# the bundle ad hoc, which Apple Silicon needs to run it at all; it is not
# notarised, so on another Mac the first launch is right-click > Open.
#
# Finder opens .knoise projects and the spectrum files below with
# KherveNoise (app.py handles the QFileOpenEvent macOS sends).
#
# The Windows build is KherveNoise.spec; both share packaging/spec_common.py.
#
# Copyright (C) 2026 Gwilherm Kerherve. GPL-3.0.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(SPECPATH) / "packaging"))
import spec_common as common  # noqa: E402

FULL_VERSION, SHORT_VERSION = common.stamp_version()
_ICO, ICNS = common.icons()
datas, binaries, hiddenimports = common.analysis_inputs()
print(f"Building {common.APP_NAME} v{FULL_VERSION} for macOS")

a = Analysis(
    [common.ENTRY],
    pathex=[str(common.ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=common.EXCLUDES,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="KherveNoise",
    icon=ICNS,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,       # files arrive as QFileOpenEvent instead
    target_arch=None,           # the build Mac's own architecture
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="KherveNoise",
)

app = BUNDLE(
    coll,
    name="KherveNoise.app",
    icon=ICNS,
    bundle_identifier="com.kerherve.khervenoise",
    # CFBundleShortVersionString must be dot-separated digits: no '+sha'.
    version=SHORT_VERSION,
    info_plist={
        "CFBundleName": "KherveNoise",
        "CFBundleDisplayName": "KherveNoise",
        "CFBundleShortVersionString": SHORT_VERSION,
        "CFBundleVersion": SHORT_VERSION,
        "CFBundleGetInfoString": f"KherveNoise {FULL_VERSION}",
        "LSMinimumSystemVersion": "11.0",
        "LSApplicationCategoryType": "public.app-category.education",
        "NSHighResolutionCapable": True,          # sharp text on Retina
        "NSRequiresAquaSystemAppearance": False,
        "NSHumanReadableCopyright":
            "Copyright (C) 2026 Gwilherm Kerherve. GPL-3.0.",
        "UTExportedTypeDeclarations": [{
            "UTTypeIdentifier": "com.kerherve.khervenoise.project",
            "UTTypeDescription": "KherveNoise project",
            "UTTypeConformsTo": ["public.json", "public.data"],
            "UTTypeTagSpecification": {"public.filename-extension": ["knoise"]},
        }],
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": "KherveNoise project",
                "CFBundleTypeRole": "Editor",
                "LSHandlerRank": "Owner",
                "LSItemContentTypes": ["com.kerherve.khervenoise.project"],
                "CFBundleTypeExtensions": ["knoise"],
            },
            {
                # Opened, not owned: these files belong to the instruments
                # (and to KherveFitting), so KherveNoise only offers itself.
                "CFBundleTypeName": "Spectrum file",
                "CFBundleTypeRole": "Viewer",
                "LSHandlerRank": "Alternate",
                "CFBundleTypeExtensions": [
                    "vms", "npl", "vgd", "avg", "kal", "spe", "pro", "mrs",
                    "itx", "nxs", "sdp", "asc", "xy",
                ],
            },
        ],
    },
)
