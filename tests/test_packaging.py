"""The PyInstaller packaging helpers: icons, version stamping, specs."""

import ast
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packaging"))


def test_icons_are_well_formed(qapp, tmp_path):
    import make_icons
    ico, icns = make_icons.build_icons(tmp_path)
    data = open(ico, "rb").read()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind, count) == (0, 1, len(make_icons.ICO_SIZES))
    for i in range(count):
        size, offset = struct.unpack("<II", data[6 + 16 * i + 8: 6 + 16 * i + 16])
        assert data[offset:offset + 8] == b"\x89PNG\r\n\x1a\n"
    data = open(icns, "rb").read()
    assert data[:4] == b"icns" and struct.unpack(">I", data[4:8])[0] == len(data)


def test_git_version_shape():
    from khervenoise._version import git_version
    v = git_version(ROOT)
    assert v.startswith("0.1.")


def test_specs_parse_and_share_one_helper():
    for name in ("KherveNoise.spec", "KherveNoiseMAC.spec"):
        src = open(os.path.join(ROOT, name), encoding="utf-8").read()
        ast.parse(src)
        assert "import spec_common as common" in src
        assert "common.analysis_inputs()" in src
    assert "BUNDLE(" in open(os.path.join(ROOT, "KherveNoiseMAC.spec")).read()


def test_every_vendor_module_is_bundled():
    """The vendor modules are imported by name at run time; the specs bundle
    them through collect_submodules('khervenoise')."""
    import spec_common
    src = open(spec_common.__file__).read()
    assert 'collect_submodules("khervenoise")' in src


def test_installer_scripts_parse():
    for name in ("build_installer.py", "build_macos.py", "smoke_test.py"):
        ast.parse(open(os.path.join(ROOT, "packaging", name), encoding="utf-8").read())


def test_installer_and_specs_agree_on_names():
    """The Inno script, both build scripts and the specs all name the same
    executable, and the stable file names are the ones the website links to."""
    iss = open(os.path.join(ROOT, "packaging", "KherveNoise.iss"), encoding="utf-8").read()
    assert '#define AppExe "KherveNoise.exe"' in iss
    assert "OutputBaseFilename={#AppName}-Setup-{#APP_VERSION}" in iss
    win = open(os.path.join(ROOT, "KherveNoise.spec"), encoding="utf-8").read()
    assert 'name="KherveNoise"' in win
    inst = open(os.path.join(ROOT, "packaging", "build_installer.py"), encoding="utf-8").read()
    assert 'f"{_APP}-Setup.exe"' in inst and "-portable.zip" in inst
    mac = open(os.path.join(ROOT, "packaging", "build_macos.py"), encoding="utf-8").read()
    assert 'f"{_APP}-macOS-{arch}.dmg"' in mac
    assert os.path.isfile(os.path.join(ROOT, "packaging", "macos", "entitlements.plist"))


def test_workflows_build_but_never_release():
    """CI builds and uploads artifacts only: a release is a deliberate act."""
    for name, trigger in (("windows-build.yml", '"v*"'), ("macos-build.yml", '"macos-v*"')):
        src = open(os.path.join(ROOT, ".github", "workflows", name), encoding="utf-8").read()
        assert trigger in src
        assert "actions/upload-artifact" in src and "smoke_test.py" in src
        assert "gh release" not in src.replace("`gh release create", "")
