"""PHI .spe / .pro, Kratos .kal and SDP .sdp readers (khervenoise.vendors).

The .spe / .pro / .kal / .sdp files are built here from the layouts
KherveFitting's parsers expect, so these tests always run.  Where the
KherveFitting sources are on this machine, its own importers are loaded
(``wx`` and ``libraries.*`` stubbed, helper functions ast-extracted) and run
on the same file: names, x, 'Raw Data' and the other columns must match.
Real SDP files are used when present; they are never copied into the repo.
"""

import ast
import glob
import os
import struct
import subprocess
import sys
import types

import numpy as np
import pytest

from khervenoise.vendors import formats_for
from khervenoise.vendors import kal, pro, sdp, spe

KF_ROOT = os.environ.get("KHERVEFITTING_SRC", "/Users/gkerherv/Documents/PycharmProjects/KherveFittingPro")
KF_LIB = os.path.join(KF_ROOT, "libraries")
KF_PY = os.path.join(KF_ROOT, ".venv", "bin", "python")
SDP_DIR = "/Users/gkerherv/Downloads/Oxides, Rare Earth"
SDP_FILES = sorted(glob.glob(os.path.join(SDP_DIR, "*.sdp"))
                   + glob.glob(os.path.join(SDP_DIR, "*.SDP")))
SDP_SAMPLE = os.path.join(SDP_DIR, "CeO2 powder 99.9%, Rare Metallics Co.sdp")

needs_kf = pytest.mark.skipif(not os.path.isdir(KF_LIB),
                              reason="KherveFitting sources not on this machine")


# ---------------------------------------------------------------------------
# Synthetic files
# ---------------------------------------------------------------------------
def _c1s_counts(n):
    return [1000.0 + 37.0 * k + (400.0 if k == n // 2 else 0.0) for k in range(n)]


def make_spe(path, dtype="f"):
    """VersaProbe (float32, dtype 'f') or X-tool (float64, 'd') layout:
    header, a 16-byte directory, then the regions' counts back to back."""
    header = "\n".join([
        "SOFH",
        "FileDate: 2024 05 06",
        "InstrumentModel: PHI VersaProbe III",
        "XraySource: Al mono 1486.6",
        "IntensityCalCoeff: 29.443 0.222",
        "PassEnergy: 55.0 eV",
        "AnalyserWorkFcn: 4.3 eV",
        "XrayBeamDiameter: 100.0 um",
        "Comments: synthetic file",
        "SpectralRegDefFull: 1 1 C1s 6 21 -0.1000 290.0 288.0 290.0 288.0 0.2 55.0 FAT",
        "SpectralRegDef: 1 1 C1s 6 21 -0.1000 290.0000 288.0000 290.0 288.0 0.2000 55.0000 FAT",
        "SpectralRegDef: 2 1 Fe2p3 26 15 -0.2000 712.0000 709.2000 712.0 709.2 0.2000 23.5000 FAT",
        "SpectralRegDef: 3 1 O1s 8 12 -0.1000 533.0000 531.9000 533.0 531.9 0.2000 55.0000 FAT",
        "SpectralRegDef2: 1 1 C1s 6 21 -0.1 290.0 288.0",
        "EOFH",
    ]).encode("ascii")
    c1s = _c1s_counts(21)
    fe = [2000.0 + 113.0 * k for k in range(15)]
    o1s = [-5.0] * 12                                 # invalid -> skipped
    body = b"\x00" * 16 + struct.pack(f"<{21 + 15 + 12}{dtype}", *(c1s + fe + o1s))
    with open(path, "wb") as fh:
        fh.write(header[:-4] + b"EOFH" + body)
    return c1s, fe


def make_pro(path):
    """DEPTHPRO layout: header, 64-byte directory, float32 c/s region-major /
    cycle-minor, the two per-cycle tables and a short trailer."""
    header = "\r\n".join([
        "SOFH",
        "FileType: DEPTHPRO",
        "InstrumentModel: PHI VersaProbe III",
        "Operator: KN",
        "FileDate: 2024 05 06",
        "XraySource: Al 1486.6 25.0 W",
        "IntensityCalCoeff: 29.443 0.222",
        "AnalyserWorkFcn: 4.3 eV",
        "AnalyserMode: FAT",
        "SputterEnergy: 2.0 kV",
        "XrayBeamDiameter: 100.0 um",
        "NoDPDataCyc: 3",
        "SpatialAreaDesc: 1 Synthetic sample",
        "SpectralRegDef: 1 1 C1s 6 11 -0.2000 290.0000 288.0000 290.0 288.0 0.1000 55.0000 FAT",
        "SpectralRegDefFull: 1 1 C1s 6 11 -0.2000 290.0 288.0 290.0 288.0 0.1 55.0 FAT",
        "SpectralRegDef: 2 1 Fe2p3 26 9 -0.5000 712.0000 708.0000 712.0 708.0 0.2000 26.0000 FAT",
        "EOFH",
    ]).encode("latin-1")
    blocks = []
    for c in range(3):
        blocks.append([1500.5 + 10.0 * k + 100.0 * c for k in range(11)])
    for c in range(3):
        blocks.append([800.25 + 7.0 * k + 50.0 * c for k in range(9)])
    flat = [v for b in blocks for v in b]
    body = (b"\r\n" + b"\x00" * 62 + struct.pack(f"<{len(flat)}f", *flat)
            + b"\x00" * (8 * 2 * 3) + b"\x00" * 100)
    with open(path, "wb") as fh:
        fh.write(header + body)
    return blocks


KAL_TEXT = """Kratos Analytical export
Dataset filename = sample.kal
Object name = Sample Position/1
Stage Position Name = Pos A
Stage X Rotation = 45
Ordinate values = {1}
Dataset filename = sample.kal
Object name = C 1s/2
Date Acquired = 2024-05-06 10:11:12
Chemical symbol or formula = C
Transition or charge state = 1s
# Sweeps completed = 5
Pass energy = 20
Abscissa label = Kinetic Energy
Abscissa units = eV
Spectrum scan start = 1191.67 eV
Spectrum scan step size = 0.1 eV
Dwell time = 0.1 seconds
Ordinate values = {CS1}
Transmission Function Object (ke,t)
Transmission Function Kinetic Energy = {1000.0, 1150.0, 1192.0, 1300.0}
Transmission Function Value          = {10.0, 11.5, 12.25, 13.1}
Casa Info Follows
Synthetic sample
(1.0, 2.0) Angle: 0
Lens Mode: Hybrid
Dataset filename = sample.kal
Object name = C 1s/3
Chemical symbol or formula = C
Transition or charge state = 1s
Spectrum scan start = 1180.0 eV
Spectrum scan step size = 0.25 eV
Ordinate values = {CS2}
Transmission Function Object (ke,t)
Transmission Function Kinetic Energy = {1185.0, 1150.0, 1170.0}
Transmission Function Value          = {12.0, 11.0, 11.7}
Dataset filename = sample.kal
Object name = O 1s/4
Spectrum scan start = 950.0 eV
Spectrum scan step size = 0.1 eV
Ordinate values = {5, 6, 7, 8}
"""


def make_kal(path):
    cs1 = [100.0 + 3.5 * k for k in range(15)]
    cs2 = [250.0 - 2.25 * k for k in range(30)]   # KE 1180..1187.25: extrapolated
    text = (KAL_TEXT.replace("CS1", ", ".join(str(v) for v in cs1))
            .replace("CS2", ", ".join(str(v) for v in cs2)))
    with open(path, "w") as fh:
        fh.write(text)
    return cs1, cs2


def _sdp_block(desc, be_start, step, n, ys, source=1486.68, pe=50.0, count=None):
    strings = [b"C:\\data\\run.vms", desc.encode(), b"", b"Mon Jan 01 1990", b"VAMAS/ISO"]
    out = b"Binding Energy" + b"\x00" * (112 - 14)
    for s in strings:
        out += struct.pack("<H", len(s) + 1) + s + b"\x00"
    out += struct.pack("<5d", be_start, step, be_start + (n - 1) * step, min(ys, default=0.0),
                       max(ys, default=0.0))
    out += b"\x00\x00"
    out += struct.pack("<6d", source, 0.0, 4.5, pe, 3.0, 0.0)
    out += struct.pack("<II", 1, n if count is None else count)
    out += struct.pack(f"<{len(ys)}d", *ys)
    return out


def make_sdp(path):
    c1s = [1000.0 + 37.123 * k + 0.005 for k in range(101)]
    o1s = [5000.0 - 12.345 * k for k in range(71)]
    surv = [20000.0 + 3.333 * k for k in range(111)]
    data = b"XI SDP BINARY FILE" + struct.pack("<HH", 1, 5) + b"\x00" * 10
    data += _sdp_block("C1s Scan", 295.0, -0.1, 101, c1s)
    data += _sdp_block("", 535.0, -0.1, 71, o1s)                 # named from BE
    data += _sdp_block("C 1s", 295.0, -0.1, 101, c1s)            # duplicate -> C1s1
    data += _sdp_block("Survey", 1100.0, -10.0, 111, surv)
    data += _sdp_block("empty", 100.0, -1.0, 0, [], count=0)     # skipped
    with open(path, "wb") as fh:
        fh.write(data)
    return c1s, o1s, surv


# ---------------------------------------------------------------------------
# KherveFitting's own importers, wx / libraries.* stubbed
# ---------------------------------------------------------------------------
def _extract(path, names, ns):
    """Exec the top-level functions / assignments called *names* of *path*."""
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), path)
    body = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            body.append(node)
        elif isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id in names for t in node.targets):
            body.append(node)
    exec(compile(ast.Module(body=body, type_ignores=[]), path, "exec"), ns)
    return ns


def _module(name, **attrs):
    mod = types.ModuleType(name)
    mod.__path__ = []
    mod.__dict__.update(attrs)
    return mod


def _fail(*args, **kwargs):
    raise AssertionError(f"KherveFitting reported an error: {args}")


@pytest.fixture
def kf(monkeypatch):
    """Namespace of KherveFitting's SPE/PRO/Kal/SDP import modules."""
    if not os.path.isdir(KF_LIB):
        pytest.skip("KherveFitting sources not on this machine")
    import re
    import pandas as pd

    wx = _module("wx", OK=1, ICON_ERROR=2, MessageBox=_fail)
    wx.__getattr__ = lambda name: 0
    open_ns = _extract(os.path.join(KF_LIB, "FileMenu", "Open.py"),
                       {"_SPIN_ORBIT_DIGITS", "phi_region_base", "normalize_sheet_name"},
                       {"re": re})
    cfg_ns = _extract(os.path.join(KF_LIB, "ConfigFile.py"),
                      {"build_core_level_Data", "add_core_level_Data"}, {"os": os})
    vam_ns = _extract(os.path.join(KF_LIB, "FileMenu", "Vamas_Import.py"),
                      {"CASA_INFO_FIELDS", "parse_casa_info_lines",
                       "extract_transmission_data"}, {"np": np, "re": re})

    class Console:
        def __init__(self, *a, **k):
            pass

        def update(self, *a, **k):
            pass

        def is_cancelled(self):
            return False

        def finish(self, *a, **k):
            pass

    mods = {
        "wx": wx,
        "libraries": _module("libraries"),
        "libraries.FileMenu": _module("libraries.FileMenu"),
        "libraries.FileMenu.Open": _module("libraries.FileMenu.Open", **open_ns),
        "libraries.ConfigFile": _module("libraries.ConfigFile", **cfg_ns,
                                        Init_Measurement_Data=lambda window: {}),
        "libraries.FileMenu.Vamas_Import": _module("libraries.FileMenu.Vamas_Import",
                                                   **vam_ns),
        "libraries.FileMenu.ProcessingConsole": _module(
            "libraries.FileMenu.ProcessingConsole", ProcessingConsole=Console),
        "libraries.FileMenu.KFitting_IO": _module(
            "libraries.FileMenu.KFitting_IO", KFITTING_EXT=".kfit",
            prompt_project_format=lambda window, n=0: "kfitting",
            write_kfitting=lambda window, path: None,
            open_kfitting_file=lambda window, path: None),
    }
    for name, mod in mods.items():
        monkeypatch.setitem(sys.modules, name, mod)

    loaded = {}
    wanted = ["PRO_Import", "SPE_Import", "SDP_Import"]
    try:
        import scipy  # noqa: F401  (Kal_Import imports scipy.interpolate)
        wanted.append("Kal_Import")
    except ImportError:
        pass
    for name in wanted:
        path = os.path.join(KF_LIB, "FileMenu", f"{name}.py")
        full = f"libraries.FileMenu.{name}"
        mod = _module(full, __file__=path)
        monkeypatch.setitem(sys.modules, full, mod)
        with open(path, encoding="utf-8") as fh:
            exec(compile(fh.read(), path, "exec"), mod.__dict__)
        loaded[name] = mod
    return types.SimpleNamespace(pd=pd, **loaded, **cfg_ns)


def _window():
    return types.SimpleNamespace(show_popup_message2=_fail)


def kf_spe(kf, path):
    w = _window()
    assert kf.SPE_Import.open_spe_file(w, path) is True
    return w.Data["Core levels"]


def kf_pro(kf, path):
    w = _window()
    assert kf.PRO_Import.open_pro_file(w, path) is True
    return w.Data["Core levels"]


def kf_kal(kf, path):
    if not hasattr(kf, "Kal_Import"):
        pytest.skip("scipy is needed to run KherveFitting's Kal_Import")
    w = _window()
    kf.Kal_Import.open_kal_file(w, path)
    return w.Data["Core levels"]


def kf_sdp(kf, path, tmp_path):
    """import_sdp_file without wx: sheets written, workbook read back."""
    import openpyxl
    m = kf.SDP_Import
    parsed = m.parse_sdp_file(path)
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    names = []
    for i, spec in enumerate(parsed["spectra"]):
        name = m._unique_sheet_name(spec["core_level"], names)
        names.append(name)
        m._write_sheet(wb.create_sheet(name), spec, parsed["metadata"], i,
                       len(parsed["spectra"]))
    xlsx = str(tmp_path / "kf_sdp.xlsx")
    wb.save(xlsx)
    data = {"Core levels": {}}
    for name in names:
        kf.add_core_level_Data(data, None, xlsx, name)
    return data["Core levels"]


COLUMNS = ("B.E.", "Raw Data", "Corrected Data", "Transmission")


def assert_same(result, kf_levels, rtol=None, inexact=()):
    assert [s["Name"] for s in result.spectra] == list(kf_levels)
    for sp in result.spectra:
        ref = kf_levels[sp["Name"]]
        for col in COLUMNS:
            if rtol is not None and col in inexact:
                np.testing.assert_allclose(sp[col], ref[col], rtol=rtol)
            else:
                assert sp[col] == [float(v) for v in ref[col]], (sp["Name"], col)
        assert sp.get("ExperimentalInfo", {}) == ref.get("ExperimentalInfo", {})


# ---------------------------------------------------------------------------
# PHI .spe
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("dtype", ["f", "d"])
def test_spe_synthetic(tmp_path, dtype):
    p = str(tmp_path / f"synthetic_{dtype}.spe")
    c1s, fe = make_spe(p, dtype)
    assert formats_for(p)[0].key == "spe"
    res = spe.read_spe(p)
    assert [s["Name"] for s in res.spectra] == ["C1s", "Fe2p"]
    assert res.dismissed == [("O1s", "only 0/12 valid points")]
    sp = res.spectra[0]
    assert sp["B.E."] == list(np.linspace(290.0, 288.0, 21))
    ke = np.maximum(1486.6 - np.linspace(290.0, 288.0, 21), 1.0)
    t = 55.0 * np.power(29.443 ** 2 / (29.443 ** 2 + (ke / 55.0) ** 2), 0.222)
    assert sp["Raw Data"] == list(np.array(c1s) / t)
    assert sp["Corrected Data"] == sp["Raw Data"]
    assert sp["Transmission"] == [1.0] * 21
    assert sp["ExperimentalInfo"]["Species & Transition"] == "C1s"
    assert sp["ExperimentalInfo"]["Date"] == "2024/05/06"
    assert sp["ExperimentalInfo"]["Pass Energy"] == "55.0"
    assert "X_Label" not in sp
    assert res.spectra[1]["ExperimentalInfo"]["Species & Transition"] == "Fe2p3"


@needs_kf
@pytest.mark.parametrize("dtype", ["f", "d"])
def test_spe_matches_khervefitting(kf, tmp_path, dtype):
    p = str(tmp_path / f"synthetic_{dtype}.spe")
    make_spe(p, dtype)
    assert_same(spe.read_spe(p), kf_spe(kf, p))


def test_spe_duplicate_regions_unique(tmp_path):
    p = str(tmp_path / "dup.spe")
    make_spe(p)
    with open(p, "rb") as fh:
        raw = fh.read().replace(b"Fe2p3 26", b"C1s   6 ")
    with open(p, "wb") as fh:
        fh.write(raw)
    assert [s["Name"] for s in spe.read_spe(p).spectra] == ["C1s", "C1s1"]


# ---------------------------------------------------------------------------
# PHI .pro
# ---------------------------------------------------------------------------
def test_pro_synthetic(tmp_path):
    p = str(tmp_path / "profile.pro")
    blocks = make_pro(p)
    assert formats_for(p)[0].key == "pro"
    res = pro.read_pro(p)
    assert [s["Name"] for s in res.spectra] == ["C1s", "C1s1", "C1s2",
                                                 "Fe2p", "Fe2p1", "Fe2p2"]
    sp = res.spectra[1]                       # C1s, cycle 1
    be = np.linspace(290.0, 288.0, 11)
    counts = np.array(blocks[1], dtype=float) * 0.1
    t = pro.phi_transmission(1486.6 - be, 55.0, 29.443, 0.222)
    assert sp["B.E."] == list(be)
    assert sp["Corrected Data"] == list(counts)
    assert sp["Transmission"] == list(t)
    assert sp["Raw Data"] == list(counts / t)
    info = sp["ExperimentalInfo"]
    assert info["Depth Cycle"] == "1"
    assert info["Sample ID"] == "Synthetic sample"
    assert info["Species & Transition"] == "C1s"
    assert res.spectra[3]["ExperimentalInfo"]["Species & Transition"] == "Fe2p3"


@needs_kf
def test_pro_matches_khervefitting(kf, tmp_path):
    p = str(tmp_path / "profile.pro")
    make_pro(p)
    assert_same(pro.read_pro(p), kf_pro(kf, p))


# ---------------------------------------------------------------------------
# Kratos .kal
# ---------------------------------------------------------------------------
def test_kal_synthetic(tmp_path):
    p = str(tmp_path / "sample.kal")
    cs1, cs2 = make_kal(p)
    assert formats_for(p)[0].key == "kal"
    res = kal.read_kal(p)
    assert [s["Name"] for s in res.spectra] == ["C1s", "C1s1"]
    assert res.dismissed == [("O 1s", "no transmission function")]
    sp = res.spectra[0]
    ke = np.linspace(1191.67, 1191.67 + 14 * 0.1, 15)
    assert sp["B.E."] == list(1486.67 - ke)
    assert sp["Corrected Data"] == cs1
    # In-range points: plain linear interpolation of the table.
    t = np.interp(ke, [1000.0, 1150.0, 1192.0, 1300.0], [10.0, 11.5, 12.25, 13.1])
    np.testing.assert_allclose(sp["Transmission"], t, rtol=1e-13)
    np.testing.assert_allclose(sp["Raw Data"], np.array(cs1) / t, rtol=1e-13)
    info = sp["ExperimentalInfo"]
    assert info["Sample ID"] == "Pos A"
    assert info["Sample Tilt"] == "45"
    assert info["Species & Transition"] == "C 1s"
    assert info["Casa Sample Name"] == "Synthetic sample"
    assert info["Stage Position"] == "(1.0, 2.0)"
    assert info["Lens Mode"] == "Hybrid"
    # Outside the table the transmission is extrapolated, not clamped.
    t2 = res.spectra[1]["Transmission"]
    assert t2[-1] > 12.0
    assert t2[-1] == pytest.approx(11.7 + (12.0 - 11.7) / 15.0 * (1187.25 - 1170.0))


def test_kal_interp_matches_scipy():
    scipy_interp = pytest.importorskip("scipy.interpolate")
    rng = np.random.default_rng(0)
    for _ in range(200):
        n = int(rng.integers(2, 30))
        x, y = rng.uniform(0, 1500, n), rng.uniform(0.1, 100, n)
        xn = np.linspace(-50, 1600, 97)
        ref = scipy_interp.interp1d(x, y, kind="linear", bounds_error=False,
                                    fill_value="extrapolate")(xn)
        np.testing.assert_allclose(kal._interp1d_linear(x, y, xn), ref, rtol=1e-9)


@pytest.mark.skipif(not os.path.exists(KF_PY), reason="KherveFitting venv not found")
def test_kal_interp_bit_exact_with_khervefitting_scipy():
    """KherveFitting pins scipy 1.13: same arithmetic, bit for bit."""
    code = (
        "import numpy as np, scipy, sys\n"
        "from scipy.interpolate import interp1d\n"
        "rng = np.random.default_rng(3); out = []\n"
        "for _ in range(50):\n"
        "    n = int(rng.integers(2, 30)); x = rng.uniform(0, 1500, n)\n"
        "    y = rng.uniform(0.1, 100, n); xn = np.linspace(-50, 1600, 97)\n"
        "    out.append((x.tolist(), y.tolist(), interp1d(x, y, kind='linear', "
        "bounds_error=False, fill_value='extrapolate')(xn).tolist()))\n"
        "print(repr((scipy.__version__, out)))\n")
    try:
        proc = subprocess.run([KF_PY, "-c", code], capture_output=True, text=True,
                              timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        pytest.skip(f"KherveFitting venv unusable: {exc}")
    if proc.returncode != 0:
        pytest.skip("KherveFitting venv has no scipy")
    version, cases = eval(proc.stdout)            # noqa: S307 — our own output
    if not version.startswith("1.13"):
        pytest.skip(f"KherveFitting venv has scipy {version}")
    xn = np.linspace(-50, 1600, 97)
    for x, y, ref in cases:
        assert kal._interp1d_linear(x, y, xn).tolist() == ref


@needs_kf
def test_kal_matches_khervefitting(kf, tmp_path):
    p = str(tmp_path / "sample.kal")
    make_kal(p)
    # scipy >= 1.14 rewrote interp1d's linear formula (last-ulp differences);
    # bit-exactness with KherveFitting's scipy 1.13 is checked above.
    assert_same(kal.read_kal(p), kf_kal(kf, p), rtol=1e-12,
                inexact=("Raw Data", "Transmission"))


# ---------------------------------------------------------------------------
# SDP
# ---------------------------------------------------------------------------
def test_sdp_synthetic(tmp_path):
    p = str(tmp_path / "sample.sdp")
    c1s, o1s, surv = make_sdp(p)
    fmt = formats_for(p)[0]
    assert fmt.key == "sdp"
    assert fmt.notice.startswith("This file is the property of Spectral Data Processor")
    res = sdp.read_sdp(p)
    assert [s["Name"] for s in res.spectra] == ["C1s", "O1s", "C1s1", "Survey"]
    sp = res.spectra[0]
    assert sp["B.E."] == [float(f"{round(295.0 - 0.1 * i, 2):.2f}") for i in range(101)]
    assert sp["Raw Data"] == [float(f"{round(v, 2):.2f}") for v in c1s]
    assert sp["Corrected Data"] == sp["Raw Data"]
    assert sp["Transmission"] == [1.0] * 101
    info = sp["ExperimentalInfo"]
    assert info["Sample ID"] == "sample"
    assert info["Species & Transition"] == "C1s"
    assert info["Pass Energy"] == "50.00"
    assert info["Total Spectra"] == "4"
    assert res.spectra[2]["Raw Data"] == sp["Raw Data"]


@needs_kf
def test_sdp_matches_khervefitting(kf, tmp_path):
    p = str(tmp_path / "sample.sdp")
    make_sdp(p)
    assert_same(sdp.read_sdp(p), kf_sdp(kf, p, tmp_path))


@pytest.mark.skipif(not os.path.exists(SDP_SAMPLE), reason="SDP sample not on this machine")
def test_sdp_real_file():
    assert formats_for(SDP_SAMPLE)[0].key == "sdp"
    res = sdp.read_sdp(SDP_SAMPLE)
    names = [s["Name"] for s in res.spectra]
    # Named as KherveFitting names them: from the BE range when the
    # description carries no core level (the Ce 3d window centre is nearer
    # Pr3d's 929 eV than Ce3d's 883 eV in identify_core_level_from_be).
    assert names == ["Survey", "VB", "Pr3d", "Si2p", "C1s", "O1s", "La3d", "Survey1"]
    assert all(len(s["B.E."]) == len(s["Raw Data"]) > 100 for s in res.spectra)


@needs_kf
@pytest.mark.skipif(not SDP_FILES, reason="SDP samples not on this machine")
@pytest.mark.parametrize("path", SDP_FILES, ids=os.path.basename)
def test_sdp_real_files_match_khervefitting(kf, tmp_path, path):
    assert formats_for(path)[0].key == "sdp"
    assert_same(sdp.read_sdp(path), kf_sdp(kf, path, tmp_path))
