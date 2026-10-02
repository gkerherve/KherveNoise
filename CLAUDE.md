# KherveNoise — notes for Claude

KherveNoise is a PySide6 desktop app in the Kherve family (KherveFitting,
KhervePlot, KherveSlide, KherveTeX, KherveMol, KherveCAD, KherveSheet,
KhervePaint…). It is **a replica of KherveFitting's Spectral Denoising
window** (`KherveFittingPro/libraries/ToolsMenu/FFT_Filter.py`) as a
program of its own: same controls, same defaults, same plots, same Auto
rules, same numbers — plus the application around it (files, undo, MCP,
updates, help).

## Source of truth

KherveFitting's `SpectralDenoisingWindow` is the reference. When it
changes, port the change here and keep the two in step:

- maths → `engine.py` (Qt-free). `tests/kf_reference.py` is a **verbatim**
  copy of the original functions; `tests/test_engine.py` asserts the
  results are bit-for-bit equal. Re-extract it rather than editing it.
- controls and plots → `denoise_panel.py`, method by method
  (`_plot_fft` / `_plot_wav` / `_plot_vmd` / `_plot_result`).
- instrument files → `vendors/*.py` (one module per KherveFitting
  `*_Import.py`); `tests/test_vendors_*.py` load KherveFitting's own
  importers from `KHERVEFITTING_SRC` (wx stubbed) and compare every value.
- file reading → `importers.py` mirrors `Vamas_Import.open_vamas_file`,
  `Open.open_xlsx_file` + `ConfigFile.add_core_level_Data` and
  `XPS_ASC_CSV_Import` (including the `.2f` rounding of Excel / ASC / CSV
  values — `ROUND_LIKE_KHERVEFITTING`).

Known quirks kept on purpose because KherveFitting has them: VMD returns
the iterate *before* the last one (vmdpy behaviour); in the wavelet
scalogram the finest level is drawn at the top, as its axis title says,
but the tick numbers run 1..L from the bottom, so that top row carries
the number L rather than 1. Fix them in KherveFitting first if they are to change.

## Build / run

- Python 3.12 / 3.13, **PySide6-Essentials** (never PyQt5/6, never the full
  PySide6 wheel), matplotlib, numpy, PyWavelets, pandas, openpyxl, xlrd,
  vamas, olefile (VGD); h5py optional (NeXus, Scienta HDF5) and imported
  lazily. A per-project `.venv` (as for the sibling apps).
- Run: `python KherveNoise.py` or `python -m khervenoise`;
  `--mcp-server` forks the stdio MCP server before any Qt.
- Crash log: `%TEMP%/khervenoise_crash.log` (faulthandler).
- **Version** is derived in `_version.py` from `git rev-list --count HEAD`
  + short sha → `KherveNoise v0.1.N+sha`. Never edit a version by hand.

## File size policy

Every module in `khervenoise/` should stay near **1000 lines**; split by
domain before passing that.

## Layout

- `KherveNoise.py` — entry script.
- `khervenoise/`
  - `__init__.py`   — `APP_NAME`, `ORG_NAME`, `REPO`, brand colours
                      (KherveFitting green `#4FBE9F`, opposite `#BE4FAA`),
                      pins `QT_API=pyside6`.
  - `app.py`        — `main()`: crash log, Fusion + light palette/QSS,
                      `--mcp-server`, files on the command line, updater.
  - `engine.py`     — Qt-free maths: `vmd` (memory-light, identical
                      arithmetic), `fft_build_filter`, `fft_recommended`,
                      `fft_contributions`, `wav_decompose`, `vmd_auto_K_keep`,
                      `denoise`, `auto_params`, `full_params`, `noise_estimate`.
  - `document.py`   — `Document` (ordered spectra, `.knoise` JSON,
                      snapshots for undo), `make_spectrum`, the technique axis
                      table (`axis_labels`, `x_reversed`, `is_xps_like`).
                      A spectrum is a KherveFitting core-level dict:
                      `'B.E.'` (x) and `'Raw Data'` (y) are what is denoised.
  - `importers.py`  — Qt-free readers returning `ImportResult`.
  - `exporters.py`  — KherveFitting-layout `.xlsx` and CSV / text.
  - `vendors/`      — instrument formats, one Qt-free module per format
                      family, each a port of a KherveFitting
                      `libraries/FileMenu/*_Import.py`: `avantage`, `vgd`,
                      `avg` (Thermo), `kal` (Kratos), `spe`, `pro` (PHI),
                      `scienta`, `mrs`, `vgmicrotech`, `igor`, `diamond`,
                      `sdp`. Each declares `FORMATS = [Format(...)]`
                      (extensions, reader, optional `sniff` + `priority` for
                      shared extensions such as .xlsx / .txt / .dat / .h5,
                      optional third-party `notice`). `importers.read_any`
                      tries a claiming vendor format first; the File ▸
                      Import ▸ Instrument menu is built from
                      `vendors.groups()`. Each module's docstring says which
                      KherveFitting route it reproduces — the in-memory
                      .kfit route (no rounding) when KherveFitting has one,
                      otherwise the workbook route (`.2f`).
  - `denoise_panel.py` — the replica window as a `QWidget` (control column
                      in a scroll area + matplotlib figure). `create_spectra`
                      is the dialog-free Create (MCP uses it); `change_hook`
                      makes it one undo step.
  - `mainwindow.py` — menus, four toolbars (File / Denoise / View / Help),
                      open / import / save / export, recent files, drag and
                      drop, New Instance, Spectrum menu, undo
                      (`change(label, func)` → `_SnapshotCommand`), help,
                      About, MCP wiring.
  - `icons.py`      — every icon drawn with QPainter (no image files), and
                      the app mark.
  - `tooltips.py` / `tooltip_texts.py` — long how-to tooltip + status line of
                      every toolbar icon, keyed `"<toolbar>|<action text>"`,
                      also rendered into the guide's Toolbar reference.
  - `help.py`       — User Guide dialog over `docs/USER_GUIDE.md`
                      (`<!-- toolbar-reference -->` is filled from the tips).
  - `about.py`      — About (author, khervetools.com family, versions, GPL).
  - `references.py` — the Methods & References dialog (KherveFitting's text).
  - `updater.py`    — Help ▸ Check for Updates / Update Automatically
                      (ported from KhervePlot: fetch + clean fast-forward,
                      GitHub release fallback). `KHERVENOISE_NO_UPDATE=1`
                      or the offscreen platform disables it.
  - `mcp_server.py` (Qt-free stdio JSON-RPC), `mcp_bridge.py` (loopback
                      `QTcpServer` + token + access levels), `mcp_schema.py`
                      (tool table + `check_args`), `mcp_tools.py` (executor),
                      `mcp_hosts.py` (writes Claude Desktop / Claude Code /
                      Cursor… configs), `mcp_dialog.py` (AI ▸ Connect to
                      Claude). `KHERVENOISE_STATE_DIR` overrides the endpoint
                      folder (tests).
- `docs/USER_GUIDE.md`, `docs/screenshot.png`.
- `tests/` — pytest, offscreen (`conftest.py` isolates QSettings and the MCP
  state dir). Run `.venv/bin/python -m pytest tests -q`.

## Rules

- **Toolbar icons need a written tip.** A new toolbar action needs a
  `tooltip_texts.TIPS` entry; `tests/test_window.py` fails on a missing or
  orphaned one. No angle brackets or ampersands in the text.
- **Everything that changes the spectra is undoable**: go through
  `MainWindow.change(label, func)` (the panel's `change_hook`).
- **MCP**: a new tool = a `mcp_schema.TOOLS` entry + `_t_<name>` in
  `mcp_tools.py` + a line in `mcp_server._INSTRUCTIONS`; classify it in
  `mcp_bridge` (`_READ_ONLY_TOOLS`, `_FILE_TOOLS`). Tools must never open a
  modal dialog — use the `interactive=False` paths.
- **Persistence**: anything stored on a spectrum must round-trip through
  `.knoise` (`document.py`); bump `FORMAT_VERSION` and keep old files loading.
- Keep the guide (`docs/USER_GUIDE.md`) in step with features.

## Commit / push policy

**Every change lands as a commit on the `dev` branch and is pushed
immediately.** `main` is the stable line and only moves when the user asks
for a merge. No `Co-Authored-By:` trailer (authorship stays with the user).
Subjects under 70 chars, prefixed `feat:` `fix:` `refactor:` `style:`
`docs:` `perf:` or `test:`; the body explains *why*. Run the tests first;
`git add` explicit paths, never `-A`.

## Licensing

GPL-3.0. New source files carry the short notice:
"Copyright (C) 2026 Gwilherm Kerherve / Licensed under the GNU General
Public License v3.0 (see LICENSE)."
