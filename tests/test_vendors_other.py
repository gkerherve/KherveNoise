"""Scienta, MRS, VG-Microtech, Igor and Diamond importers.

No sample files exist for these formats, so each test writes a small
synthetic file shaped exactly as KherveFitting's parser expects, reads it
with khervenoise.vendors and — when the KherveFittingPro sources are on this
machine — runs KherveFitting's own import pipeline on the same file (its
functions ast-extracted from the source, wx / libraries.* stubbed, the real
ConfigFile.add_core_level_Data / build_core_level_Data used) and asserts the
very same spectra come out.
"""

import ast
import json
import os
import re
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from khervenoise import vendors
from khervenoise.vendors import diamond, igor, mrs, scienta, vgmicrotech

KF = Path(os.environ.get("KHERVEFITTING_SRC", "/Users/gkerherv/Documents/PycharmProjects/KherveFittingPro") + "/libraries")
HAVE_KF = (KF / "FileMenu" / "Scienta_Import.py").exists()
needs_kf = pytest.mark.skipif(not HAVE_KF, reason="KherveFittingPro sources not found")

RNG = np.random.default_rng(7)


# ---------------------------------------------------------------------------
# KherveFitting reference harness (test-only)
# ---------------------------------------------------------------------------
def _fake_wx():
    wx = MagicMock(name="wx")
    wx.ID_OK, wx.ID_CANCEL, wx.ID_YES = 5100, 5101, 5103
    dlg = wx.SingleChoiceDialog.return_value
    dlg.ShowModal.return_value = wx.ID_OK
    dlg.GetSelection.return_value = 0              # KherveFitting's default choice
    return wx


def _extract(relpath, ns, funcs=(), methods=(), assigns=True):
    """Exec selected top-level functions / class methods (and plain
    assignments) of a KherveFitting source file into ``ns``."""
    path = KF / relpath
    tree = ast.parse(path.read_text(encoding="utf-8"))
    body = []
    for node in tree.body:
        if assigns and isinstance(node, ast.Assign):
            body.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in funcs:
            body.append(node)
        elif isinstance(node, ast.ClassDef):
            body += [m for m in node.body if isinstance(m, ast.FunctionDef)
                     and (node.name, m.name) in methods]
    exec(compile(ast.Module(body=body, type_ignores=[]), str(path), "exec"), ns)
    return ns


def _window():
    w = MagicMock(name="window")
    w.GetPosition.return_value = types.SimpleNamespace(x=0, y=0)
    w.GetSize.return_value = types.SimpleNamespace(width=800, height=600)
    w.results_grid.GetNumberRows.return_value = 0
    w.Data = {'Core levels': {}}
    return w


@pytest.fixture
def kf(monkeypatch):
    """Fake wx + libraries.* modules wired to KherveFitting's real readers."""
    if not HAVE_KF:
        pytest.skip("KherveFittingPro sources not found")
    import openpyxl
    import openpyxl.utils  # noqa: F401
    import pandas as pd

    wx = _fake_wx()
    base = {'np': np, 're': re, 'os': os, 'json': json, 'openpyxl': openpyxl, 'wx': wx}
    cfg = _extract("ConfigFile.py", dict(base),
                   funcs=("add_core_level_Data", "build_core_level_Data"), assigns=False)
    opn = _extract("FileMenu/Open.py", dict(base),
                   funcs=("normalize_sheet_name", "phi_region_base"))

    def open_xlsx_file(window, path):
        """open_xlsx_file's data path: every sheet but the special ones
        through add_core_level_Data."""
        window.Data = {'Core levels': {}}
        for name in pd.ExcelFile(path).sheet_names:
            if name.lower() in ("results table", "experimental description"):
                continue
            cfg['add_core_level_Data'](window.Data, window, path, name)

    captured = {}

    def finish_import(window, core_levels, sample_names, first, console):
        captured['core_levels'] = core_levels
        return first

    mods = {
        'wx': wx,
        'libraries': types.ModuleType('libraries'),
        'libraries.FileMenu': types.ModuleType('libraries.FileMenu'),
        'libraries.FileMenu.Open': types.SimpleNamespace(
            normalize_sheet_name=opn['normalize_sheet_name'],
            phi_region_base=opn['phi_region_base'],
            open_xlsx_file=open_xlsx_file, update_recent_files=lambda *a, **k: None),
        'libraries.ConfigFile': types.SimpleNamespace(
            add_core_level_Data=cfg['add_core_level_Data'],
            build_core_level_Data=cfg['build_core_level_Data'],
            Init_Measurement_Data=lambda window: {'Core levels': {}}),
        'libraries.FileMenu.Save': types.SimpleNamespace(
            update_undo_redo_state=lambda *a: None, save_state=lambda *a: None,
            convert_to_serializable_and_round=lambda d: {},
            refresh_sheets=lambda *a, **k: None),
        'libraries.Sheet_Operations': types.SimpleNamespace(on_sheet_selected=lambda *a: None),
        'libraries.FileMenu.ProcessingConsole': types.SimpleNamespace(ProcessingConsole=MagicMock()),
        'libraries.FileMenu.Diamond_NXS_Import': types.SimpleNamespace(finish_import=finish_import),
    }
    for name, mod in mods.items():
        monkeypatch.setitem(sys.modules, name, mod)
    return types.SimpleNamespace(wx=wx, base=base, cfg=cfg, captured=captured,
                                 open_xlsx_file=open_xlsx_file)


def _spectra(core_levels):
    return {n: (list(cl['B.E.']), list(cl['Raw Data'])) for n, cl in core_levels.items()
            if 'B.E.' in cl and cl['B.E.']}


def _ours(result):
    return {sp['Name']: (sp['B.E.'], sp['Raw Data']) for sp in result.spectra}


def _assert_same(kf_levels, result, info=True):
    ref = _spectra(kf_levels)
    got = _ours(result)
    assert list(got) == list(ref)
    for name in ref:
        assert got[name][0] == ref[name][0], name          # exact, not approx
        assert got[name][1] == ref[name][1], name
    if info:
        for sp in result.spectra:
            assert sp.get('ExperimentalInfo', {}) == kf_levels[sp['Name']].get('ExperimentalInfo', {})


def _keys(path):
    return [f.key for f in vendors.formats_for(str(path))]


# ---------------------------------------------------------------------------
# Synthetic files
# ---------------------------------------------------------------------------
def _ses_region(n, name, be, data_cols, sweeps=None):
    lines = [f"[Region {n}]", f"Region Name={name}",
             "Dimension 1 name=Binding Energy [eV]", f"Dimension 1 size={len(be)}",
             "Dimension 1 scale=" + " ".join(f"{v:.3f}" for v in be)]
    if sweeps:
        lines += ["Dimension 2 name=Sweep", f"Dimension 2 size={sweeps}",
                  "Dimension 2 scale=" + " ".join(str(i + 1) for i in range(sweeps))]
    lines += ["", f"[Info {n}]", f"Region Name={name}", "Sample=Pt foil",
              "Spectrum Name=run1", "Instrument=R4000", "Lens Mode=Transmission",
              "Pass Energy=20", "Energy Scale=Binding", "Excitation Energy=1486.6",
              "Acquisition Mode=Swept", "Energy Step=0.1", "Step Time=100",
              "Date=2026-01-02", "Time=10:00:00", "", f"[Data {n}]"]
    for i, v in enumerate(be):
        lines.append(f"  {v:.3f}  " + "  ".join(f"{c[i]:.4f}" for c in data_cols))
    return lines + [""]


def write_ses(path, regions):
    lines = ["[Info]", f"Number of Regions={len(regions)}", "Version=1.3.1", ""]
    for n, reg in enumerate(regions, start=1):
        lines += _ses_region(n, *reg)
    path.write_text("\n".join(lines))
    return path


def _be(hi, n=25, step=0.1):
    return hi - step * np.arange(n)


def _counts(n=25, scale=1000.0):
    return scale * (1 + RNG.random(n)) + RNG.random(n) / 3


@pytest.fixture
def ses_plot(tmp_path):
    be = _be(290.0)
    return write_ses(tmp_path / "plot.txt", [
        ("C1s_fast", be, [_counts()]),
        ("C 1s 2", be, [_counts()]),           # same core level -> C1s1
        ("O1s", _be(535.0, 30), [_counts(30)]),
        ("Survey scan", _be(1000.0, 40, 1.0), [_counts(40, 5e4)]),
    ])


@pytest.fixture
def ses_map(tmp_path):
    be = _be(80.0, 20)
    return write_ses(tmp_path / "map.txt", [
        ("Pt4f_slow", be, [_counts(20) for _ in range(3)], 3),
        ("Valence Band", _be(10.0, 20), [_counts(20) for _ in range(4)], 4),
    ])


def write_scienta_h5(path):
    h5py = pytest.importorskip("h5py")
    ke = 1486.6 - 290.0 + 0.05 * np.arange(30)          # ascending KE -> BE flipped
    data = RNG.random((5, 30)) * 100 + 50
    with h5py.File(path, "w") as f:
        sd = f.create_group("acquisition/spectrum_definition")
        for k, v in dict(acquisition_mode="Image", energy_mode="Kinetic",
                         lens_mode_name="HighMag", element_set_name="C 1s").items():
            sd[k] = v
        sd["pass_energy"], sd["dwell_time"], sd["acquisition_time"] = 50.0, 0.1, 12.0
        sl = f.create_group("acquisition/spectrum_log")
        sl["start_time"], sl["stop_time"] = "2026-03-04T10:11:12", "2026-03-04T10:20:00"
        f["acquisition/spectrum/name"] = "map1"
        f["instrument/analyser/excitation_source/energy"] = 1486.6
        f["instrument/analyser/work_function"] = 4.5
        f["instrument/analyser/model"] = "DA30"
        g = f.create_group("acquisition/spectrum/data")
        g["data"], g["x_axis"] = data, ke
        g["y_axis"] = np.linspace(-1, 1, 5)
        g["y_axis"].attrs["label"], g["y_axis"].attrs["units"] = "Y", "mm"
        r = f.create_group("acquisition/spectrum/data_reduced_1d")
        r["data"], r["x_axis"] = data.sum(axis=0), ke
    return path


MRS_TEXT = """header
desc=Sputtered sample
oper=GK
time_stamp=2026-01-01 10:00
scan_total=5
array_size=11
data=Data Array
lo_be=280.0
up_be=290.7
!
{values}
!
"""


def write_mrs(path):
    vals = "\n".join(str(int(v)) for v in _counts(11))
    path.write_text(MRS_TEXT.format(values=vals))
    return path


def write_vg(path, n=21, extra=0):
    vals = "\n".join(f"{v:.3f}" for v in _counts(n + extra))
    path.write_text(f"VG file\n290.0 280.0 0.5 0 0.1 {n} 20 -1486.6\nC 1s\n{vals}\n")
    return path


def write_itx(path):
    small = RNG.random(15) * 2                           # max < 100 -> x10000
    big = _counts(12)
    lines = ["IGOR",
             "WAVES/D '[All C 1s] S1'", "BEGIN", *[f" {v:.6f}" for v in small], "END",
             "X SetScale/P x 280.05,0.1,\"\", '[All C 1s] S1'",
             "WAVES/D '[All C 1s] S1 bck'", "BEGIN", " 1", " 2", "END",
             "WAVES/D 'O1s_sample.txt'", "BEGIN", *[f" {v:.4f}" for v in big], "END",
             "X SetScale/P x 528.1,0.25,\"\", 'O1s_sample.txt'",
             "WAVES/D 'noaxis'", "BEGIN", *[f" {v:.4f}" for v in big[:6]], "END", ""]
    path.write_text("\n".join(lines))
    return path


def write_igor_dat(path):
    n = 12
    cu_be = 930.0 + 0.5 * np.arange(n)
    o_be = 528.0 + 0.25 * np.arange(n)
    rows = ["[All Cu 2p] S1\t\t[All Cu 2p] S1 bck\t\t[All O 1s] S2"]
    for i in range(n):
        rows.append(f"{cu_be[i]:.2f}\t{_counts(1)[0]:.3f}\t1.0\t{o_be[i]:.3f}\t{RNG.random() * 3:.5f}")
    path.write_text("\n".join(rows) + "\n")
    return path


def write_b07(path, scans=3):
    n = 20
    be = 280.0 + 0.1 * np.arange(n)                        # ascending, sorted on read
    spec = [_counts(n) for _ in range(scans)]
    head = "\t".join(["binding_energy", "intensity"] + [f"spectrum_{i + 1}" for i in range(scans)])
    rows = [head] + ["\t".join(f"{v:.4f}" for v in [be[i], sum(s[i] for s in spec)] +
                               [s[i] for s in spec]) for i in range(n)]
    path.write_text("\n".join(rows) + "\n")
    return path


def write_nxs_xps(path):
    h5py = pytest.importorskip("h5py")
    with h5py.File(path, "w") as f:
        e = f.create_group("entry")
        e["instrument/beamline"] = "b07"
        e["sample/name"] = "Not set"
        e["diamond_scan/start_time"] = "2026-05-06T07:08:09"
        e["experiment_identifier"] = "si12345-1"

        def region(name, x, y, mode="Binding", hv=1000.0, step=0.2, iters=3, xn="energies",
                   yn="spectrum_data"):
            g = e.create_group(name)
            g[xn], g[yn], g["excitation_energy"] = x, y, hv
            ins = e.create_group(f"instrument/{name}")
            ins["energy_mode"], ins["lens_mode"] = mode, "Angular56"
            ins["pass_energy"], ins["step_time"], ins["number_of_iterations"] = 50, step, iters

        region("O1s_2keV", _be(535.0, 30), RNG.random((4, 30)) * 1e3)
        region("O1s_hv", _be(534.0, 25), RNG.random(25) * 1e3, hv=2000.0)
        y = RNG.random(20) * 1e3
        y[3] = np.nan                                       # dropped, as KherveFitting does
        region("C1s", 1000.0 - _be(290.0, 20), y, mode="Kinetic",
               xn="binding_energy", yn="spectrum")
    return path


def write_nxs_xas(path):
    h5py = pytest.importorskip("h5py")
    energy = np.linspace(545.0, 525.0, 40)                  # descending, sorted on read
    with h5py.File(path, "w") as f:
        e = f.create_group("entry")
        e["instrument/name"] = "i09"
        i0 = RNG.random(40) + 0.5
        i0[5] = 0.0                                         # -> NaN in TEY/I0, dropped
        for name, data in (("jI0", i0), ("sdc", RNG.random(40) * 10), ("fluo", RNG.random(40))):
            g = e.create_group(name)
            g["jenergy"], g["data"] = energy, data
    return path


# ---------------------------------------------------------------------------
# Scienta
# ---------------------------------------------------------------------------
def test_scienta_plot(ses_plot):
    assert _keys(ses_plot)[0] == "scienta_txt"
    res = scienta.read_scienta_txt(str(ses_plot))
    assert [s['Name'] for s in res.spectra] == ["C1s", "C1s1", "O1s", "Survey"]
    sp = res.spectra[0]
    assert sp['B.E.'][0] == 290.0 and len(sp['B.E.']) == 25
    assert all(v == round(v, 2) for v in sp['Raw Data'])
    assert sp['ExperimentalInfo']['Pass Energy'] == "20"
    assert sp['ExperimentalInfo']['Region Name'] == "C1s_fast"
    assert 'X_Label' not in sp


def test_scienta_map_is_summed(ses_map):
    assert _keys(ses_map)[0] == "scienta_map"
    res = scienta.read_scienta_txt(str(ses_map))
    assert [s['Name'] for s in res.spectra] == ["Pt4f", "VB"]
    parsed = scienta.parse_scienta_file(str(ses_map))
    mean = parsed['regions'][0]['data_2d'].mean(axis=0)
    assert res.spectra[0]['Raw Data'] == [float(f"{v:.2f}") for v in mean]
    assert res.spectra[0]['ExperimentalInfo']['Sweeps Summed'] == "3"


@needs_kf
def test_scienta_plot_matches_khervefitting(kf, ses_plot):
    ns = _extract("FileMenu/Scienta_Import.py", dict(kf.base, HAS_H5PY=False),
                  funcs=("clean_region_name", "parse_scienta_file", "parse_region",
                         "import_scienta_file", "finalize_scienta_import", "write_sheet_data"))
    kf.wx.FileDialog.return_value.__enter__.return_value.GetPath.return_value = str(ses_plot)
    w = _window()
    ns['import_scienta_file'](w)
    _assert_same(w.Data['Core levels'], scienta.read_scienta_txt(str(ses_plot)))


def _kf_preview_class(ns):
    """ScientaMapPreviewWindow without the GUI: __init__'s copies, the
    proposed names of init_ui, then its default button, on_sum_sweeps."""
    class Preview:
        def __init__(self, parent, parsed_data, callback_on_import):
            self.parsed_data, self.callback_on_import = parsed_data, callback_on_import
            self.regions = [r.copy() for r in parsed_data['regions']]
            for i, region in enumerate(self.regions):
                if parsed_data['regions'][i].get('data_2d') is not None:
                    region['data_2d'] = np.copy(parsed_data['regions'][i]['data_2d'])
                region['dropped_sweeps'] = []
            self.name_fields = []
            for region in self.regions:
                proposed, _ = ns['clean_region_name'](region['name'])
                tf = MagicMock()
                tf.GetValue.return_value = proposed or region['name']
                self.name_fields.append(tf)
            self.save_maps_checkbox = MagicMock()
            self.save_maps_checkbox.GetValue.return_value = False
            self.Close = lambda: None
            ns['on_sum_sweeps'](self, None)
    return Preview


@needs_kf
def test_scienta_map_matches_khervefitting(kf, ses_map):
    ns = _extract("FileMenu/Scienta_Import.py", dict(kf.base, HAS_H5PY=False),
                  funcs=("clean_region_name", "parse_scienta_file", "parse_region",
                         "import_scienta_map", "finalize_scienta_import", "write_sheet_data"),
                  methods=(("ScientaMapPreviewWindow", "on_sum_sweeps"),))
    ns['ScientaMapPreviewWindow'] = _kf_preview_class(ns)
    kf.wx.FileDialog.return_value.__enter__.return_value.GetPath.return_value = str(ses_map)
    w = _window()
    ns['import_scienta_map'](w)
    _assert_same(w.Data['Core levels'], scienta.read_scienta_txt(str(ses_map)))


@needs_kf
def test_scienta_h5_matches_khervefitting(kf, tmp_path):
    h5py = pytest.importorskip("h5py")
    path = write_scienta_h5(tmp_path / "map.h5")
    assert "scienta_h5" in _keys(path)
    ns = _extract("FileMenu/Scienta_Import.py", dict(kf.base, HAS_H5PY=True, h5py=h5py),
                  funcs=("clean_region_name", "parse_h5_scienta_file", "import_h5_scienta_file",
                         "finalize_scienta_import", "write_sheet_data"),
                  methods=(("ScientaMapPreviewWindow", "on_sum_sweeps"),))
    ns['ScientaMapPreviewWindow'] = _kf_preview_class(ns)
    w = _window()
    ns['import_h5_scienta_file'](w, str(path))
    res = scienta.read_scienta_h5(str(path))
    assert [s['Name'] for s in res.spectra] == ["C1s"]
    assert res.spectra[0]['B.E.'][0] > res.spectra[0]['B.E.'][-1]
    _assert_same(w.Data['Core levels'], res)


# ---------------------------------------------------------------------------
# MRS
# ---------------------------------------------------------------------------
def test_mrs(tmp_path):
    path = write_mrs(tmp_path / "sample_C.mrs")
    assert _keys(path) == ["mrs"]
    res = mrs.read_mrs(str(path))
    sp = res.spectra[0]
    assert sp['Name'] == "C1s" and len(sp['B.E.']) == 11
    assert sp['B.E.'][0] == 290.7 and sp['B.E.'][-1] == 280.0


@needs_kf
def test_mrs_matches_khervefitting(kf, tmp_path):
    path = write_mrs(tmp_path / "sample_C.mrs")
    ns = _extract("FileMenu/MRS_Import.py", dict(kf.base),
                  funcs=("get_core_level_from_filename", "import_mrs_file", "open_mrs_file"))
    for name in ("x_SU.MRS", "x_CL.mrs", "abc_Fe.mrs", "zz.mrs", "a_1.mrs", "VB.mrs"):
        assert mrs.get_core_level_from_filename(name) == ns['get_core_level_from_filename'](name)
    ours = mrs.read_mrs(str(path))
    # Menu route
    kf.wx.FileDialog.return_value.__enter__.return_value.GetPath.return_value = str(path)
    w = _window()
    ns['import_mrs_file'](w)
    _assert_same(w.Data['Core levels'], ours, info=False)
    # Drag-and-drop route: same numbers
    w = _window()
    assert ns['open_mrs_file'](w, str(path))
    _assert_same(w.Data['Core levels'], ours, info=False)


# ---------------------------------------------------------------------------
# VG-Microtech
# ---------------------------------------------------------------------------
def test_vg_microtech(tmp_path):
    path = write_vg(tmp_path / "scan.1", extra=3)
    assert _keys(path) == ["vgmicrotech"]
    sp = vgmicrotech.read_vg_microtech(str(path)).spectra[0]
    assert sp['Name'] == "C1s" and len(sp['B.E.']) == 21
    assert sp['B.E.'][0] == 290.0 and sp['B.E.'][-1] == 280.0
    assert sp['ExperimentalInfo']['Photon Energy'] == "1486.6"


@needs_kf
@pytest.mark.parametrize("extra", [0, 3, -4])
def test_vg_microtech_matches_khervefitting(kf, tmp_path, extra):
    path = write_vg(tmp_path / "scan.1", extra=extra)
    ns = _extract("FileMenu/VGMicrotech_Import.py", dict(kf.base),
                  funcs=("open_vg_microtech_file",))
    w = _window()
    assert ns['open_vg_microtech_file'](w, str(path))
    _assert_same(w.Data['Core levels'], vgmicrotech.read_vg_microtech(str(path)), info=False)


# ---------------------------------------------------------------------------
# Igor
# ---------------------------------------------------------------------------
def _kf_igor(kf):
    ns = _extract("FileMenu/Igor_Import.py", dict(kf.base),
                  funcs=("import_igor_itx_file", "import_igor_dat_file"))

    def _open_imported_excel_file(window, excel_path, samples_info):
        import pandas as pd
        window.Data = {'Core levels': {}}
        for name in pd.ExcelFile(excel_path).sheet_names:
            kf.cfg['add_core_level_Data'](window.Data, window, excel_path, name)
    ns['_open_imported_excel_file'] = _open_imported_excel_file
    return ns


def test_igor_itx(tmp_path):
    path = write_itx(tmp_path / "data.itx")
    assert _keys(path) == ["igor_itx"]
    res = igor.read_igor_itx(str(path))
    assert [s['Name'] for s in res.spectra] == ["O1s0", "C1s1", "Unknown2"]
    c1s = res.spectra[1]
    assert c1s['B.E.'][0] > c1s['B.E.'][-1]
    assert max(c1s['Raw Data']) > 100                       # scaled x10000


@needs_kf
def test_igor_itx_matches_khervefitting(kf, tmp_path):
    path = write_itx(tmp_path / "data.itx")
    w = _window()
    _kf_igor(kf)['import_igor_itx_file'](w, str(path))
    _assert_same(w.Data['Core levels'], igor.read_igor_itx(str(path)), info=False)


def test_igor_dat(tmp_path):
    path = write_igor_dat(tmp_path / "igor.dat")
    assert _keys(path)[0] == "igor_dat"
    res = igor.read_igor_dat(str(path))
    assert [s['Name'] for s in res.spectra] == ["Cu2p0", "O1s1"]
    assert res.spectra[0]['B.E.'][0] == 935.5


@needs_kf
def test_igor_dat_matches_khervefitting(kf, tmp_path):
    path = write_igor_dat(tmp_path / "igor.dat")
    w = _window()
    _kf_igor(kf)['import_igor_dat_file'](w, str(path))
    _assert_same(w.Data['Core levels'], igor.read_igor_dat(str(path)), info=False)


# ---------------------------------------------------------------------------
# Diamond
# ---------------------------------------------------------------------------
B07_NAME = "b07-1-120131_C1s_250_D2_PE20_495_XPS.dat"


def test_b07_dat(tmp_path):
    path = write_b07(tmp_path / B07_NAME)
    assert _keys(path)[0] == "diamond_b07"
    sp = diamond.read_b07_dat(str(path)).spectra[0]
    assert sp['Name'] == "C1s"
    assert sp['B.E.'][0] > sp['B.E.'][-1]
    info = sp['ExperimentalInfo']
    assert info['Sample ID'] == "250 D2 - 495 eV"
    assert info['Pass Energy'] == "20" and info['Number of scans'] == "3"


@needs_kf
def test_b07_dat_matches_khervefitting(kf, tmp_path):
    path = write_b07(tmp_path / B07_NAME)
    ns = _extract("FileMenu/Diamond_B07_DAT_Import.py", dict(kf.base),
                  funcs=("_natural_key", "is_b07_xps_dat", "parse_name", "read_dat",
                         "_core_level_name", "_row_label", "plan_rows", "import_b07_dat_files"))
    assert ns['import_b07_dat_files'](_window(), [str(path)])
    _assert_same(kf.captured['core_levels'], diamond.read_b07_dat(str(path)))


def _kf_nxs(kf):
    finish = sys.modules['libraries.FileMenu.Diamond_NXS_Import'].finish_import
    return _extract("FileMenu/Diamond_NXS_Import.py", dict(kf.base, finish_import=finish),
                    funcs=("_txt", "_scalar", "_string", "_entry", "beamline_of",
                           "_xps_regions", "_xas_channels", "detect", "_core_level_name",
                           "read_xps", "guess_edge", "read_xas", "_row_name",
                           "import_nxs_files"))


def test_nxs_xps(tmp_path):
    path = write_nxs_xps(tmp_path / "i09-1234.nxs")
    assert _keys(path) == ["diamond_nxs"]
    res = diamond.read_nxs(str(path))
    # h5py lists groups alphabetically: C1s, O1s_2keV, O1s_hv
    assert [s['Name'] for s in res.spectra] == ["C1s", "O1s", "O1s1"]
    c1s = res.spectra[0]
    assert len(c1s['B.E.']) == 19                           # the NaN point dropped
    assert c1s['B.E.'][0] == pytest.approx(290.0)          # KE -> BE
    assert c1s['ExperimentalInfo']['Instrument'] == "Diamond B07"
    assert 'X_Label' not in c1s


@needs_kf
@pytest.mark.parametrize("writer", [write_nxs_xps, write_nxs_xas])
def test_nxs_matches_khervefitting(kf, tmp_path, writer):
    path = writer(tmp_path / "scan.nxs")
    assert _kf_nxs(kf)['import_nxs_files'](_window(), [str(path)])
    _assert_same(kf.captured['core_levels'], diamond.read_nxs(str(path)))


def test_nxs_xas(tmp_path):
    path = write_nxs_xas(tmp_path / "xas.nxs")
    res = diamond.read_nxs(str(path))
    names = [s['Name'] for s in res.spectra]
    assert names == ["XAS~O-K-fluo-norm~", "XAS~O-K-fluo~", "XAS~O-K~",
                     "XAS~O-K-TEY~", "XAS~O-K-I0~"]
    tey = res.spectra[2]
    assert len(tey['B.E.']) == 39 and tey['B.E.'][0] < tey['B.E.'][-1]
    assert tey['X_Label'] == "Photon Energy (eV)"


# ---------------------------------------------------------------------------
# Sniffs on shared extensions
# ---------------------------------------------------------------------------
MINE = {"scienta_txt", "scienta_map", "scienta_h5", "igor_dat", "diamond_b07"}


@pytest.mark.parametrize("name,text", [
    ("plain.txt", "290.0\t100\n289.9\t120\n289.8\t130\n"),
    ("plain.dat", "Binding Energy\tCounts\n290.0\t100\n289.9\t120\n"),
    ("plain2.dat", "290.0 100\n289.9 120\n"),
    ("info.txt", "[Info]\nsome notes\n"),
])
def test_plain_files_not_claimed(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text)
    assert not MINE & set(_keys(path))
    assert not scienta.sniff_plot(str(path)) and not scienta.sniff_map(str(path))
    if name.endswith(".dat"):
        assert not igor.sniff_igor_dat(str(path))
        assert not diamond.is_b07_xps_dat(str(path))


def test_shared_extensions_pick_right_format(tmp_path, ses_plot, ses_map):
    assert _keys(ses_plot)[0] == "scienta_txt" and "scienta_map" not in _keys(ses_plot)
    assert _keys(ses_map)[0] == "scienta_map" and "scienta_txt" not in _keys(ses_map)
    b07 = write_b07(tmp_path / B07_NAME)
    ig = write_igor_dat(tmp_path / "igor.dat")
    assert "igor_dat" not in _keys(b07)
    assert "diamond_b07" not in _keys(ig)
