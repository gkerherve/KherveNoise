"""The main window and the denoising panel, offscreen."""

import numpy as np

from khervenoise import engine, tooltips
from khervenoise.tooltip_texts import TIPS


def test_every_toolbar_icon_has_a_written_tip(window):
    described = {k for group in tooltips.described_actions(window).values()
                 for k, _a in group}
    missing = described - set(TIPS)
    orphans = set(TIPS) - described
    assert not missing, f"toolbar icons without a TIPS entry: {missing}"
    assert not orphans, f"TIPS entries for no icon: {orphans}"
    for key in described:
        title, what, steps, _tip = TIPS[key]
        assert len(what) > 40 and steps, key


def test_file_menu_has_the_family_entries(window):
    texts = [a.text().replace("&", "") for a in window.menuBar().actions()[0].menu().actions()]
    for wanted in ("New Instance of KherveNoise", "Open…", "Import", "Save", "Export",
                   "About KherveNoise", "Exit"):
        assert any(t.startswith(wanted) for t in texts), wanted


def test_open_denoise_create_undo(window, vamas_path):
    assert window.open_path(vamas_path, interactive=False) == ["Pt4f"]
    p = window.panel
    assert p.current_sheet == "Pt4f" and p.y_filtered is not None
    for method in engine.METHODS:
        p.set_method(method)
        assert p.active_params()['method'] == method
        # The panel shows exactly what the engine computes.
        np.testing.assert_array_equal(p.y_filtered, engine.denoise(p.x, p.y, p.active_params()))
    created, errors = p.create_spectra(["Pt4f"], auto=False)
    assert created == ["Pt4f_fft"] and not errors
    assert window.document.get("Pt4f_fft")['Denoise']['source'] == "Pt4f"
    window.undo_stack.undo()
    assert window.document.get("Pt4f_fft") is None
    window.undo_stack.redo()
    assert window.document.get("Pt4f_fft") is not None


def test_auto_matches_khervefitting_rule(window, vamas_path):
    window.open_path(vamas_path, interactive=False)
    p = window.panel
    p.set_method("FFT filter")
    cutoff, _f, _t = engine.fft_recommended(p.lnC, p.M)
    assert p.active_params()['cutoff'] == cutoff


def test_save_and_reopen(window, vamas_path, tmp_path):
    window.open_path(vamas_path, interactive=False)
    window.panel.create_spectra(["Pt4f"])
    path = str(tmp_path / "t.knoise")
    assert window.save_to(path)
    assert not window.document.dirty
    assert window.open_path(path, interactive=False) == ["Pt4f", "Pt4f_vmd"]


def test_rename_and_delete(window, vamas_path):
    window.open_path(vamas_path, interactive=False)
    assert window.rename_spectrum("Pt4f", "Platinum")
    assert window.document.names() == ["Platinum"]
    window.delete_spectrum("Platinum", confirm=False)
    assert window.document.is_empty()
    window.undo_stack.undo()
    assert window.document.names() == ["Platinum"]


def test_set_axes_is_undoable(window, vamas_path):
    window.open_path(vamas_path, interactive=False)
    assert window.panel.x_label == "Binding Energy (eV)" and window.panel.x_reversed
    assert window.set_axes("Pt4f", "Time (s)", "Signal", False, False)
    assert window.panel.x_label == "Time (s)" and not window.panel.x_reversed
    window.undo_stack.undo()
    assert window.panel.x_label == "Binding Energy (eV)" and window.panel.x_reversed
