"""KherveNoise main window: menus, toolbars, files, undo, MCP.

The central widget is the Spectral Denoising panel (``denoise_panel``);
everything here is the application around it — opening / importing /
saving / exporting, the recent-files list, undo, drag and drop, New
Instance, the updater and the Claude (MCP) connection.

Copyright (C) 2026 Gwilherm Kerherve
Licensed under the GNU General Public License v3.0 (see LICENSE).
"""

import os
import subprocess
import sys

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QKeySequence, QUndoCommand, QUndoStack
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog,
                               QInputDialog, QLabel, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox,
                               QPushButton, QHBoxLayout, QTextBrowser,
                               QToolBar, QVBoxLayout)

from . import APP_NAME, ORG_NAME, __version__
from . import icons, importers, tooltips
from .denoise_panel import DenoisePanel
from .document import EXTENSION, Document, natural_sort_key

MAX_RECENT = 10
KEY_RECENT = "recent_files"
KEY_DIR = "last_dir"


class _SnapshotCommand(QUndoCommand):
    """One undoable change: the spectra before and after it."""

    def __init__(self, window, label, before, after):
        super().__init__(label)
        self._w, self._before, self._after = window, before, after
        self._first = True

    def redo(self):
        if self._first:            # already applied when pushed
            self._first = False
            return
        self._w._restore(self._after)

    def undo(self):
        self._w._restore(self._before)


class SpectraPicker(QDialog):
    """Tick the spectra an export should write."""

    def __init__(self, document, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(360, 420)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Spectra to write:"))
        self.list = QListWidget()
        for name in document.names():
            it = QListWidgetItem(name)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            it.setData(Qt.UserRole, bool(document.get(name).get('Denoise')))
            self.list.addItem(it)
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        for label, pick in (("All", lambda d: True), ("None", lambda d: False),
                            ("Denoised only", lambda d: d)):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, f=pick: self._check(f))
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _check(self, pick):
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setCheckState(Qt.Checked if pick(it.data(Qt.UserRole)) else Qt.Unchecked)

    def names(self):
        return [self.list.item(i).text() for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.Checked]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings(ORG_NAME, APP_NAME)
        self.document = Document()
        self.undo_stack = QUndoStack(self)
        self.undo_stack.cleanChanged.connect(self._on_clean_changed)
        self._help = None
        self.bridge = None

        self.panel = DenoisePanel(self)
        self.panel.change_hook = self.change
        self.panel.help_requested.connect(self.show_help)
        self.panel.references_requested.connect(self.show_references)
        self.panel.spectra_created.connect(self._on_created)
        self.panel.spectrum_selected.connect(lambda _n: self._update_title())
        self.setCentralWidget(self.panel)
        self.panel.set_document(self.document)

        from .updater import Updater
        self.updater = Updater(self)

        self._build_actions()
        self._build_menus()
        self._build_toolbars()
        tooltips.apply_to_toolbars(self)
        self.setAcceptDrops(True)
        self.resize(1200, 900)
        self._update_title()
        self.statusBar().showMessage(
            "Open, import or drop an Excel, VAMAS or data file to begin.")

    # ==================================================================
    # Actions, menus, toolbars
    # ==================================================================
    def _act(self, text, slot, icon=None, shortcut=None, tip=None):
        a = QAction(text, self)
        if icon is not None:
            a.setIcon(icon)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if tip:
            a.setStatusTip(tip)
        a.triggered.connect(lambda _checked=False: slot())
        return a

    def _build_actions(self):
        p = self.panel
        A = self._act
        self.a_new_instance = A("New Instance", self.new_instance, icons.new_instance(),
                                "Ctrl+Shift+N")
        self.a_open = A("Open", self.open_dialog, icons.open_file(), QKeySequence.Open)
        self.a_import_excel = A("Import Excel", self.import_excel_dialog, icons.import_excel())
        self.a_import_data = A("Import Data File", self.import_data_dialog, icons.import_data())
        self.a_import_vamas = A("Import VAMAS", self.import_vamas_dialog, icons.import_vamas())
        self.a_import_instrument = A("Import Instrument File", self.import_instrument_dialog,
                                     icons.import_instrument())
        self.a_import_folder = A("Import Folder", self.import_folder_dialog,
                                 icons.import_folder())
        self.a_save = A("Save", self.save, icons.save(), QKeySequence.Save)
        self.a_save_as = A("Save As…", self.save_as, None, QKeySequence.SaveAs)
        self.a_export_kf = A("Export to KherveFitting", self.export_khervefitting_dialog,
                             icons.export_kfit())
        self.a_export_csv = A("Export CSV", self.export_csv_dialog, icons.export_csv())
        self.a_save_fig = A("Save Figure", self.save_figure_dialog, icons.save_figure())
        self.a_about = A("About", self.show_about, icons.about())
        self.a_exit = A("Exit", self.close, icons.exit_app(), QKeySequence.Quit)

        self.a_apply = A("Apply", lambda: p.update_all_plots(), icons.apply_denoise(), "F5")
        self.a_auto = A("Auto", p.on_auto, icons.auto_params(), "Ctrl+Shift+A")
        self.a_create = A("Create", p.on_create, icons.create_spectra(), "Ctrl+Return")
        self.a_delete = A("Delete Spectrum", self.delete_current, icons.delete_spectrum())
        self.a_rename = A("Rename Spectrum…", self.rename_current, None, "F2")
        self.a_info = A("Spectrum Information…", self.show_spectrum_info)

        self.a_zoom_box = A("Zoom Box", p.on_box_zoom_toggle, icons.zoom_box())
        self.a_zoom_out = A("Zoom Out", p.on_zoom_out, icons.zoom_out())
        self.a_y_in = A("Y Zoom In", lambda: p.on_zoom_y(0.8), icons.y_zoom("+"))
        self.a_y_out = A("Y Zoom Out", lambda: p.on_zoom_y(1.25), icons.y_zoom("-"))
        self.a_reset = A("Reset View", p.on_zoom_reset, icons.zoom_reset())

        self.a_mcp = A("Connect to Claude", self.show_mcp_dialog, icons.mcp())
        self.a_guide = A("User Guide", self.show_help, icons.user_guide(), "F1")
        self.a_refs = A("References", self.show_references, icons.references())

        self.a_undo = self.undo_stack.createUndoAction(self, "&Undo")
        self.a_undo.setShortcut(QKeySequence.Undo)
        self.a_redo = self.undo_stack.createRedoAction(self, "&Redo")
        self.a_redo.setShortcut(QKeySequence.Redo)

    def _build_menus(self):
        m = self.menuBar()
        f = m.addMenu("&File")
        f.addAction(self._clone(self.a_new_instance, f"New &Instance of {APP_NAME}"))
        f.addSeparator()
        f.addAction(self._clone(self.a_open, "&Open…"))
        self.recent_menu = f.addMenu("Open &Recent")
        self.recent_menu.aboutToShow.connect(self._populate_recent)
        imp = f.addMenu("&Import")
        imp.addAction(self._clone(self.a_import_excel, "&Excel File (.xlsx, .xls)…"))
        imp.addAction(self._clone(self.a_import_data, "&Data File (.asc, .txt, .dat, .xy, .csv)…"))
        imp.addAction(self._clone(self.a_import_vamas, "&VAMAS File (.vms)…"))
        imp.addSeparator()
        inst = imp.addMenu(icons.import_instrument(), "&Instrument")
        inst.addAction(self._clone(self.a_import_instrument, "Any Instrument File…"))
        inst.addSeparator()
        self._build_instrument_menu(inst)
        imp.addSeparator()
        imp.addAction(self._clone(self.a_import_folder, "All Files in a &Folder…"))
        f.addSeparator()
        f.addAction(self._clone(self.a_save, "&Save"))
        f.addAction(self.a_save_as)
        exp = f.addMenu("&Export")
        exp.addAction(self._clone(self.a_export_kf, "To &KherveFitting (.xlsx)…"))
        exp.addAction(self._clone(self.a_export_csv, "As &CSV / Text…"))
        exp.addAction(self._clone(self.a_save_fig, "&Figure (PNG, SVG, PDF)…"))
        f.addSeparator()
        f.addAction(self._clone(self.a_about, f"&About {APP_NAME}"))
        f.addSeparator()
        f.addAction(self._clone(self.a_exit, "E&xit"))

        e = m.addMenu("&Edit")
        e.addAction(self.a_undo)
        e.addAction(self.a_redo)

        s = m.addMenu("&Spectrum")
        s.addAction(self.a_rename)
        s.addAction(self._clone(self.a_delete, "&Delete Spectrum"))
        s.addAction(self.a_info)

        d = m.addMenu("&Denoise")
        d.addAction(self._clone(self.a_apply, "&Apply"))
        d.addAction(self._clone(self.a_auto, "A&uto Parameters"))
        d.addAction(self._clone(self.a_create, "&Create Denoised Spectra"))
        d.addSeparator()
        meth = d.addMenu("&Method")
        for name in ("VMD", "Wavelet", "FFT filter"):
            meth.addAction(name, lambda n=name: self.panel.set_method(n))

        v = m.addMenu("&View")
        for a in (self.a_zoom_box, self.a_zoom_out, self.a_y_in, self.a_y_out, self.a_reset):
            v.addAction(a)

        ai = m.addMenu("&AI")
        ai.addAction(self._clone(self.a_mcp, "Connect to &Claude (MCP)…"))

        h = m.addMenu("&Help")
        h.addAction(self._clone(self.a_guide, "&User Guide"))
        h.addAction(self._clone(self.a_refs, "&Methods && References…"))
        h.addSeparator()
        self.updater.add_menu_actions(h)
        h.addSeparator()
        h.addAction(self._clone(self.a_about, f"&About {APP_NAME}"))

    def _build_instrument_menu(self, menu):
        """One submenu per vendor (Thermo, Kratos, PHI…), one entry per
        format — KherveFitting's Import ▸ XPS layout."""
        from . import vendors
        for group, formats in vendors.groups().items():
            sub = menu.addMenu(group)
            for fmt in formats:
                sub.addAction(f"{fmt.label}…",
                              lambda f=fmt: self._import_dialog(
                                  f"Import {f.group} — {f.label}", f.file_filter))

    def _clone(self, action, text):
        """A menu entry that shares a toolbar action's slot, icon and
        shortcut but carries its own (longer) wording."""
        a = QAction(action.icon(), text, self)
        a.setShortcut(action.shortcut())
        a.setStatusTip(action.statusTip())
        a.triggered.connect(action.trigger)
        action.setShortcut(QKeySequence())        # menu owns the shortcut
        return a

    def _build_toolbars(self):
        def bar(title, actions):
            tb = QToolBar(title, self)
            tb.setObjectName(f"toolbar_{title}")
            tb.setMovable(True)
            for a in actions:
                tb.addAction(a)
            self.addToolBar(Qt.TopToolBarArea, tb)
            return tb
        bar("File", [self.a_new_instance, self.a_open, self.a_import_excel,
                     self.a_import_data, self.a_import_vamas, self.a_import_instrument,
                     self.a_import_folder, self.a_save,
                     self.a_export_kf, self.a_export_csv, self.a_save_fig])
        bar("Denoise", [self.a_apply, self.a_auto, self.a_create, self.a_delete])
        bar("View", [self.a_zoom_box, self.a_zoom_out, self.a_y_in, self.a_y_out,
                     self.a_reset])
        bar("Help", [self.a_mcp, self.a_guide, self.a_refs, self.a_about])

    # ==================================================================
    # Undo
    # ==================================================================
    def change(self, label, func):
        """Run *func* (which mutates the document) as one undo step."""
        before = self.document.snapshot()
        func()
        after = self.document.snapshot()
        if after != before:
            self.undo_stack.push(_SnapshotCommand(self, label, before, after))
        self._update_title()

    def _restore(self, snap):
        current = self.panel.current_sheet
        self.document.restore(snap)
        self.panel.populate_data_list(select=current)
        self._update_title()

    def _on_created(self, names):
        self.statusBar().showMessage(f"Created {', '.join(names)}", 8000)

    # ==================================================================
    # Title / dirty state
    # ==================================================================
    def _on_clean_changed(self, clean):
        # Undoing back to the saved state makes the file clean again.
        if clean and self.document.path:
            self.document.dirty = False
        try:
            self._update_title()
        except RuntimeError:        # the stack outlives the window at exit
            pass

    def _update_title(self):
        name = os.path.basename(self.document.path or self.document.source or "") or "Untitled"
        star = "*" if self.document.dirty and not self.document.is_empty() else ""
        self.setWindowTitle(f"{APP_NAME} v{__version__} — {name}{star}")

    def maybe_save(self, title="Unsaved changes"):
        """Ask about unsaved spectra. False means: stop, the user cancelled."""
        if not self.document.dirty or self.document.is_empty():
            return True
        ans = QMessageBox.question(
            self, title, "The spectra have unsaved changes. Save them first?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if ans == QMessageBox.Cancel:
            return False
        if ans == QMessageBox.Save:
            return self.save()
        return True

    def closeEvent(self, event):
        if not self.maybe_save("Exit"):
            event.ignore()
            return
        if self.bridge is not None:
            self.bridge.stop()
        event.accept()

    # ==================================================================
    # New instance
    # ==================================================================
    def new_instance(self):
        try:
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            script = os.path.join(root, "KherveNoise.py")
            if getattr(sys, "frozen", False):
                args = [sys.executable]
            elif os.path.exists(script):
                args = [sys.executable, script]
            else:
                args = [sys.executable, "-m", "khervenoise"]
            subprocess.Popen(args, cwd=root, close_fds=True)
            self.statusBar().showMessage(f"Started a new instance of {APP_NAME}.", 5000)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "New Instance", str(e))

    # ==================================================================
    # Files: open / import
    # ==================================================================
    def _last_dir(self):
        return str(self.settings.value(KEY_DIR, os.path.expanduser("~")))

    def _remember_dir(self, path):
        self.settings.setValue(KEY_DIR, os.path.dirname(os.path.abspath(path)))

    def open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open", self._last_dir(),
            f"{importers.filter_all()};;KherveNoise project (*{EXTENSION});;"
            f"{importers.FILTER_EXCEL};;{importers.FILTER_VAMAS};;"
            f"{importers.FILTER_DATA};;{importers.filter_instruments()};;All files (*)")
        if path:
            self.open_path(path)

    def open_path(self, path, interactive=True):
        """Replace the current work by *path* (a .knoise project or any
        importable file). Returns the spectrum names now open."""
        if interactive and not self.maybe_save("Open"):
            return []
        if interactive and not self._accept_notices([path]):
            return []
        try:
            if path.lower().endswith(EXTENSION):
                doc = Document.load(path)
                dismissed = []
            else:
                res = importers.read_any(path)
                doc = Document()
                for sp in res.spectra:
                    doc.add(sp)
                doc.source = path
                doc.dirty = bool(res.spectra)
                dismissed = res.dismissed
        except Exception as exc:  # noqa: BLE001
            if interactive:
                QMessageBox.critical(self, "Open", f"Could not open {os.path.basename(path)}:\n{exc}")
                return []
            raise
        if doc.is_empty():
            msg = "No spectra were found in this file." + self._dismissed_text(dismissed)
            if interactive:
                QMessageBox.warning(self, "Open", msg)
                return []
            raise ValueError(msg)
        self.document = doc
        self.undo_stack.clear()
        self.panel.set_document(doc)
        self._add_recent(path)
        self._remember_dir(path)
        self._update_title()
        self.statusBar().showMessage(f"Opened {os.path.basename(path)} — "
                                     f"{len(doc)} spectra.", 8000)
        if interactive and dismissed:
            QMessageBox.information(self, "Sheets dismissed",
                                    "The file was opened, but some parts were left out:"
                                    + self._dismissed_text(dismissed))
        return doc.names()

    def open_or_import(self, path):
        """A file handed over by the OS (command line, Finder): a project or
        the first file opens; later files are added to it."""
        if path.lower().endswith(EXTENSION) or self.document.is_empty():
            return self.open_path(path)
        return self.import_paths([path])[0]

    @staticmethod
    def _dismissed_text(dismissed):
        if not dismissed:
            return ""
        return "\n\n" + "\n".join(f"  - {n} : {r}" for n, r in dismissed)

    def _accept_notices(self, paths):
        """Show each third-party format notice once (KherveFitting does so
        for SDP files); drop the files the user declines."""
        kept, answers = [], {}
        for path in paths:
            notice = importers.notice_for(path)
            if notice and notice not in answers:
                answers[notice] = QMessageBox.question(
                    self, "Third-party format", notice + "\n\nDo you want to proceed?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes
            if not notice or answers[notice]:
                kept.append(path)
        return kept

    def import_paths(self, paths, interactive=True):
        """ADD the spectra of *paths* to the document (one undo step).
        Returns (names added, dismissed)."""
        if interactive:
            paths = self._accept_notices(paths)
            if not paths:
                return [], []
        results, dismissed, failures = [], [], []
        for path in paths:
            try:
                res = importers.read_any(path)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{os.path.basename(path)}: {exc}")
                continue
            results.append(res)
            dismissed += res.dismissed
        added = []

        def run():
            for res in results:
                for sp in res.spectra:
                    added.append(self.document.add(sp))
            if self.document.source is None and results:
                self.document.source = results[0].source

        if any(r.spectra for r in results):
            label = f"Import {os.path.basename(paths[0])}" + ("…" if len(paths) > 1 else "")
            self.change(label, run)
            self.panel.populate_data_list(select=added[0] if added else None)
            for p in paths:
                self._add_recent(p)
            self._remember_dir(paths[0])
            self.statusBar().showMessage(f"Imported {len(added)} spectra: "
                                         f"{', '.join(added[:8])}" +
                                         ("…" if len(added) > 8 else ""), 8000)
        if interactive:
            if failures or not added:
                QMessageBox.warning(self, "Import",
                                    ("\n".join(failures) or "No spectra were found.")
                                    + self._dismissed_text(dismissed))
            elif dismissed:
                QMessageBox.information(self, "Import",
                                        f"Imported {len(added)} spectra; left out:"
                                        + self._dismissed_text(dismissed))
        elif failures and not added:
            raise ValueError("; ".join(failures))
        return added, dismissed

    def _import_dialog(self, title, flt, multi=True):
        if multi:
            paths, _ = QFileDialog.getOpenFileNames(self, title, self._last_dir(),
                                                    f"{flt};;All files (*)")
        else:
            path, _ = QFileDialog.getOpenFileName(self, title, self._last_dir(),
                                                  f"{flt};;All files (*)")
            paths = [path] if path else []
        if paths:
            self.import_paths(paths)

    def import_excel_dialog(self):
        self._import_dialog("Import Excel file", importers.FILTER_EXCEL)

    def import_data_dialog(self):
        self._import_dialog("Import data file(s)", importers.FILTER_DATA)

    def import_vamas_dialog(self):
        self._import_dialog("Import VAMAS file", importers.FILTER_VAMAS)

    def import_instrument_dialog(self):
        from . import vendors
        filters = [importers.filter_instruments()] + [
            f"{f.group} — {f.file_filter}" for f in vendors.all_formats()]
        self._import_dialog("Import instrument file(s)", ";;".join(filters))

    def import_folder_dialog(self):
        folder = QFileDialog.getExistingDirectory(self, "Import all files in a folder",
                                                  self._last_dir())
        if not folder:
            return
        paths = sorted((os.path.join(folder, n) for n in os.listdir(folder)
                        if not n.startswith(".") and importers.kind_of(n)),
                       key=lambda p: natural_sort_key(os.path.basename(p)))
        if not paths:
            QMessageBox.information(self, "Import Folder",
                                    "No supported files in this folder.")
            return
        self.import_paths(paths)

    # ---- drag and drop ----
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        projects = [p for p in paths if p.lower().endswith(EXTENSION)]
        others = [p for p in paths if importers.kind_of(p)]
        if projects:
            self.open_path(projects[0])
        elif others:
            if self.document.is_empty():
                self.open_path(others[0])
                others = others[1:]
            if others:
                self.import_paths(others)
        else:
            QMessageBox.warning(self, "Drop", "Only .knoise, Excel, VAMAS, instrument "
                                "and data files (.asc, .txt, .dat, .xy, .csv) can be "
                                "dropped.")

    # ---- recent files ----
    def recent_files(self):
        value = self.settings.value(KEY_RECENT, []) or []
        if isinstance(value, str):
            value = [value]
        return [p for p in value if os.path.exists(p)]

    def _add_recent(self, path):
        path = os.path.abspath(path)
        items = [p for p in self.recent_files() if p != path]
        self.settings.setValue(KEY_RECENT, [path] + items[:MAX_RECENT - 1])

    def _populate_recent(self):
        self.recent_menu.clear()
        files = self.recent_files()
        if not files:
            a = self.recent_menu.addAction("(none)")
            a.setEnabled(False)
            return
        for path in files:
            self.recent_menu.addAction(os.path.basename(path),
                                       lambda p=path: self.open_path(p)).setStatusTip(path)
        self.recent_menu.addSeparator()
        self.recent_menu.addAction("Clear List",
                                   lambda: self.settings.setValue(KEY_RECENT, []))

    # ==================================================================
    # Files: save / export
    # ==================================================================
    def save(self):
        if not self.document.path:
            return self.save_as()
        return self.save_to(self.document.path)

    def save_as(self):
        start = self.document.path or os.path.join(
            self._last_dir(),
            os.path.splitext(os.path.basename(self.document.source or "Untitled"))[0] + EXTENSION)
        path, _ = QFileDialog.getSaveFileName(self, "Save project", start,
                                              f"KherveNoise project (*{EXTENSION})")
        if not path:
            return False
        if not path.lower().endswith(EXTENSION):
            path += EXTENSION
        return self.save_to(path)

    def save_to(self, path):
        try:
            self.document.save(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Save", f"Could not save {path}:\n{exc}")
            return False
        self.undo_stack.setClean()
        self._add_recent(path)
        self._remember_dir(path)
        self._update_title()
        self.statusBar().showMessage(f"Saved {path}", 6000)
        return True

    def _pick_spectra(self, title):
        if self.document.is_empty():
            QMessageBox.information(self, title, "There are no spectra to export.")
            return None
        dlg = SpectraPicker(self.document, title, self)
        if dlg.exec() != QDialog.Accepted or not dlg.names():
            return None
        return [self.document.get(n) for n in dlg.names()]

    def _export_start(self, ext):
        base = os.path.splitext(os.path.basename(
            self.document.path or self.document.source or "Spectra"))[0]
        return os.path.join(self._last_dir(), f"{base}_denoised{ext}")

    def export_khervefitting_dialog(self):
        spectra = self._pick_spectra("Export to KherveFitting")
        if not spectra:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export to KherveFitting",
                                              self._export_start(".xlsx"),
                                              "Excel workbook (*.xlsx)")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        from .exporters import write_khervefitting_xlsx
        try:
            sheets = write_khervefitting_xlsx(path, spectra)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Export", f"Could not write {path}:\n{exc}")
            return
        self._remember_dir(path)
        self.statusBar().showMessage(f"Wrote {len(sheets)} sheet(s) to {path}", 8000)

    def export_csv_dialog(self):
        spectra = self._pick_spectra("Export CSV / Text")
        if not spectra:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV / Text",
                                              self._export_start(".csv"),
                                              "CSV (*.csv);;Tab-separated text (*.txt)")
        if not path:
            return
        from .exporters import write_text
        try:
            write_text(path, spectra)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Export", f"Could not write {path}:\n{exc}")
            return
        self._remember_dir(path)
        self.statusBar().showMessage(f"Wrote {path}", 8000)

    def save_figure_dialog(self):
        if self.panel.x is None:
            QMessageBox.information(self, "Save Figure", "Nothing on screen yet.")
            return
        start = os.path.join(self._last_dir(), f"{self.panel.current_sheet}_denoise.png")
        path, _ = QFileDialog.getSaveFileName(self, "Save Figure", start,
                                              "PNG (*.png);;SVG (*.svg);;PDF (*.pdf)")
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ".png"
        try:
            self.panel.fig.savefig(path, dpi=300)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Save Figure", str(exc))
            return
        self._remember_dir(path)
        self.statusBar().showMessage(f"Saved {path}", 6000)

    # ==================================================================
    # Spectrum menu
    # ==================================================================
    def delete_spectrum(self, name, confirm=True):
        if self.document.get(name) is None:
            return False
        if confirm and QMessageBox.question(
                self, "Delete Spectrum", f"Delete '{name}'?\n(Ctrl+Z brings it back.)",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return False
        self.change(f"Delete {name}", lambda: self.document.remove(name))
        self.panel.populate_data_list()
        return True

    def delete_current(self):
        if self.panel.current_sheet:
            self.delete_spectrum(self.panel.current_sheet)

    def rename_spectrum(self, old, new):
        new = str(new).strip()
        if not new or (new != old and self.document.get(new) is not None):
            return False
        ok = []
        self.change(f"Rename {old}", lambda: ok.append(self.document.rename(old, new)))
        self.panel.populate_data_list(select=new)
        return bool(ok and ok[0])

    def rename_current(self):
        old = self.panel.current_sheet
        if not old:
            return
        new, ok = QInputDialog.getText(self, "Rename Spectrum", "New name:", text=old)
        if ok and new.strip() and new.strip() != old:
            if not self.rename_spectrum(old, new):
                QMessageBox.warning(self, "Rename Spectrum", f"'{new}' is already taken.")

    def show_spectrum_info(self):
        name = self.panel.current_sheet
        sp = self.document.get(name) if name else None
        if sp is None:
            return
        rows = [("Name", name), ("Points", len(sp['B.E.'])),
                ("x range", f"{min(sp['B.E.']):g} – {max(sp['B.E.']):g}")]
        if sp.get('Denoise'):
            rows.append(("Denoised from", sp['Denoise'].get('source')))
            rows += [(f"  {k}", v) for k, v in sp['Denoise'].get('params', {}).items()]
        rows += list((sp.get('ExperimentalInfo') or {}).items())
        html = "<table cellpadding='3'>" + "".join(
            f"<tr><td><b>{k}</b></td><td>{v}</td></tr>" for k, v in rows) + "</table>"
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Spectrum Information — {name}")
        dlg.resize(520, 520)
        lay = QVBoxLayout(dlg)
        view = QTextBrowser()
        view.setHtml(html)
        lay.addWidget(view)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        dlg.exec()

    # ==================================================================
    # Help / about / MCP
    # ==================================================================
    def show_help(self, section=None):
        from .help import HelpDialog
        if self._help is None:
            self._help = HelpDialog(self)
        self._help.show()
        self._help.raise_()
        self._help.activateWindow()
        if section:
            self._help.jump_to("Spectral Denoising" if section == "denoise" else section)

    def show_references(self):
        from .references import ReferencesDialog
        ReferencesDialog(self).exec()

    def show_about(self):
        from .about import AboutDialog
        AboutDialog(self).exec()

    def _ensure_bridge(self):
        if self.bridge is None:
            from .mcp_bridge import ACCESS_LEVELS, DEFAULT_ACCESS, McpBridge
            self.bridge = McpBridge(self)
            level = str(self.settings.value("mcp/access", DEFAULT_ACCESS))
            self.bridge.set_access(level if level in ACCESS_LEVELS else DEFAULT_ACCESS)
        return self.bridge

    def start_mcp_if_enabled(self):
        # KHERVENOISE_MCP=read|edit|full starts the bridge at that level
        # without touching the saved preferences (smoke tests of a build).
        forced = os.environ.get("KHERVENOISE_MCP", "")
        if forced:
            self._ensure_bridge().set_access(forced)
            self.bridge.start()
        elif str(self.settings.value("mcp/enabled", False)).lower() in ("true", "1"):
            self._ensure_bridge().start()

    def show_mcp_dialog(self):
        from .mcp_dialog import McpServerDialog
        dlg = McpServerDialog(self._ensure_bridge(), self)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.exec()
