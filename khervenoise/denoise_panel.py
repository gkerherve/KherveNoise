"""The Spectral Denoising panel — KherveFitting's window, in Qt.

A replica of ``SpectralDenoisingWindow`` (KherveFitting
``libraries/ToolsMenu/FFT_Filter.py``): the "Analysis Controls" column on
the left (Data / Method / Create denoised sheet for / Result view / Result
display / About / References) and, on the right, the three-tier figure —
the transform or decomposition (top), a "what is kept" map (middle), and
Raw vs Denoised with a residual strip (bottom).  Same controls, same
defaults, same plots, same Auto rules; the maths lives in ``engine``.

Where KherveFitting writes a denoised copy into its workbook, KherveNoise
adds it to the open document as a new spectrum named ``<source>_<vmd|wav|
fft>`` — the source spectrum is never changed.

Copyright (C) 2026 Gwilherm Kerherve
Licensed under the GNU General Public License v3.0 (see LICENSE).
"""

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.colors import LinearSegmentedColormap, SymLogNorm
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.ticker import ScalarFormatter
from matplotlib.widgets import RectangleSelector
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox,
                               QDoubleSpinBox, QFrame, QGroupBox, QHBoxLayout,
                               QLabel, QListWidget, QListWidgetItem,
                               QMessageBox, QPushButton, QScrollArea, QSlider,
                               QSpinBox, QToolButton, QVBoxLayout, QWidget)

from . import GREEN_HEX
from . import engine
from .document import axis_labels, x_reversed
from .engine import METHODS

# KherveFitting brand green - RGB (79, 190, 159) = #4FBE9F
GREEN_RGB = (79 / 255, 190 / 255, 159 / 255)
# Complementary ("opposite") colour - a magenta/purple, deliberately NOT red.
OPP_RGB = (190 / 255, 79 / 255, 170 / 255)   # #BE4FAA
# Diverging colormap: magenta (-) -> white (0) -> green (+)
DIVERGING_CMAP = LinearSegmentedColormap.from_list(
    'kf_div', [OPP_RGB, (1.0, 1.0, 1.0), GREEN_RGB])

_GREEN_BTN = (f"QPushButton {{ background: {GREEN_HEX}; color: white; "
              "border: 1px solid #3a9c80; border-radius: 3px; padding: 3px 10px; }"
              "QPushButton:hover { background: #45ad90; }"
              "QPushButton:pressed { background: #3a9c80; }")


def _spin(lo, hi, value, width=70):
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setValue(value)
    s.setKeyboardTracking(False)      # wx.SpinCtrl fires on commit, not per key
    s.setFixedWidth(width)
    return s


def _dspin(lo, hi, value, step, digits=1, width=70):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setDecimals(digits)
    s.setValue(value)
    s.setKeyboardTracking(False)
    s.setFixedWidth(width)
    return s


def _row(*widgets, stretch=True):
    h = QHBoxLayout()
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(4)
    for w in widgets:
        if isinstance(w, str):
            h.addWidget(QLabel(w))
        else:
            h.addWidget(w)
    if stretch:
        h.addStretch(1)
    return h


class DenoisePanel(QWidget):
    """Analysis controls + figure.  ``document`` is set by the window."""

    #: names of the spectra a Create just added
    spectra_created = Signal(list)
    #: the selected spectrum changed (name)
    spectrum_selected = Signal(str)
    help_requested = Signal(str)
    references_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.document = None
        #: ``change_hook(label, func)`` runs *func* as one undoable change;
        #: the main window installs its own.  Default: just run it.
        self.change_hook = lambda label, func: func()

        # --- shared state ---
        self.method = "VMD"
        self.x = None
        self.y = None
        self.baseline = None
        self.N = 0
        self.y_filtered = None
        self.current_sheet = None
        self.x_label, self.y_label = 'X', 'Y'
        self.x_reversed = False

        # FFT cache
        self.coeffs = None
        self.M = 0
        self.n_axis = None
        self.lnC = None
        self.contrib = None
        self.contrib_vmax = 1.0
        self.noise_floor = None
        self.noise_thr = None

        # VMD cache (so the kept-modes control does not re-run VMD)
        self._vmd_cache = {'key': None, 'modes': None, 'omega': None}

        # zoom state
        self.result_ylim = None
        self.result_xlim = None
        self.box_zoom_on = False
        self.rect_selector = None
        self._quiet = False

        main = QHBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        self._create_control_panel(main)
        self._create_plots_panel(main)
        self._show_param_panel()
        self._draw_empty()

    # ==================================================================
    # Control panel
    # ==================================================================
    def _create_control_panel(self, main):
        cp = QWidget()
        cp.setObjectName("analysisControls")
        s = QVBoxLayout(cp)
        s.setContentsMargins(6, 6, 6, 6)
        s.setSpacing(6)

        title = QLabel("Analysis Controls")
        f = title.font(); f.setBold(True); f.setPointSize(f.pointSize() + 2)
        title.setFont(f)
        help_btn = QToolButton()
        help_btn.setText("?")
        help_btn.setToolTip("Spectral Denoising in the User Guide (F1)")
        help_btn.setAutoRaise(True)
        help_btn.clicked.connect(lambda: self.help_requested.emit('denoise'))
        title_row = QHBoxLayout()
        title_row.addWidget(title, 1)
        title_row.addWidget(help_btn)
        s.addLayout(title_row)

        # --- Data ---
        box = QGroupBox("Data")
        bs = QVBoxLayout(box)
        bs.addWidget(QLabel("Select core level:"))
        self.data_combo = QComboBox()
        self.data_combo.currentTextChanged.connect(self.on_data_selected)
        bs.addWidget(self.data_combo)
        self.points_text = QLabel("Points: -")
        bs.addWidget(self.points_text)
        s.addWidget(box)

        # --- Method ---
        mbox = QGroupBox("Method")
        ms = QVBoxLayout(mbox)
        self.method_choice = QComboBox()
        self.method_choice.addItems(METHODS)
        self.method_choice.setCurrentIndex(0)
        self.method_choice.currentTextChanged.connect(self.on_method_changed)
        ms.addWidget(self.method_choice)
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: rgb(90, 90, 90);")
        ms.addWidget(self.status_label)

        self._build_fft_params()
        self._build_wav_params()
        self._build_vmd_params()
        for panel in (self.fft_panel, self.wav_panel, self.vmd_panel):
            ms.addWidget(panel)

        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setStyleSheet(_GREEN_BTN)
        self.apply_btn.clicked.connect(lambda: self.update_all_plots())
        self.auto_btn = QPushButton("Auto")
        self.auto_btn.clicked.connect(self.on_auto)
        abtn = QHBoxLayout()
        abtn.addWidget(self.apply_btn, 1)
        abtn.addWidget(self.auto_btn, 1)
        ms.addLayout(abtn)
        s.addWidget(mbox)

        # --- Create for (batch) ---
        cbox = QGroupBox("Create denoised sheet for")
        cs = QVBoxLayout(cbox)
        self.batch_list = QListWidget()
        self.batch_list.setFixedHeight(100)
        cs.addWidget(self.batch_list)
        ball = QPushButton("All"); ball.setFixedWidth(52)
        ball.clicked.connect(lambda: self._batch_check_all(True))
        bnone = QPushButton("None"); bnone.setFixedWidth(52)
        bnone.clicked.connect(lambda: self._batch_check_all(False))
        cs.addLayout(_row(ball, bnone))
        self.auto_params_cb = QCheckBox("Auto parameters per spectrum")
        self.auto_params_cb.setChecked(True)
        cs.addWidget(self.auto_params_cb)
        self.create_btn = QPushButton("Create")
        self.create_btn.clicked.connect(self.on_create)
        cs.addWidget(self.create_btn)
        s.addWidget(cbox)

        # --- Result view (zoom) ---
        zbox = QGroupBox("Result view")
        zs = QVBoxLayout(zbox)
        self.box_zoom_btn = QPushButton("Zoom in (box)")
        self.box_zoom_btn.setFixedSize(115, 30)
        self.box_zoom_btn.clicked.connect(self.on_box_zoom_toggle)
        zo = QPushButton("Zoom out"); zo.setFixedSize(85, 30)
        zo.clicked.connect(lambda: self.on_zoom_out())
        zs.addLayout(_row(self.box_zoom_btn, zo))
        z2 = []
        for lbl, fac in (("Y +", 0.8), ("Y -", 1.25)):
            b = QPushButton(lbl); b.setFixedSize(45, 30)
            b.clicked.connect(lambda _=False, fc=fac: self.on_zoom_y(fc))
            z2.append(b)
        rst = QPushButton("Reset"); rst.setFixedSize(70, 30)
        rst.clicked.connect(lambda: self.on_zoom_reset())
        zs.addLayout(_row(*z2, rst))
        s.addWidget(zbox)

        # --- Result display (style of the bottom plot) ---
        dbox = QGroupBox("Result display")
        ds = QVBoxLayout(dbox)
        self.show_raw_cb = QCheckBox("Raw"); self.show_raw_cb.setChecked(True)
        self.show_raw_cb.toggled.connect(self.on_result_style)
        self.show_den_cb = QCheckBox("Denoised"); self.show_den_cb.setChecked(True)
        self.show_den_cb.toggled.connect(self.on_result_style)
        r1 = _row(self.show_raw_cb, self.show_den_cb)
        r1.setSpacing(14)
        ds.addLayout(r1)
        self.raw_style = QComboBox(); self.raw_style.addItems(["Line", "Scatter"])
        self.raw_style.currentIndexChanged.connect(self.on_result_style)
        ds.addLayout(_row("Raw as", self.raw_style))
        self.raw_w = _dspin(0.2, 6.0, 1.2, 0.2, width=60)
        self.raw_w.valueChanged.connect(self.on_result_style)
        self.den_w = _dspin(0.2, 6.0, 2.2, 0.2, width=60)
        self.den_w.valueChanged.connect(self.on_result_style)
        ds.addLayout(_row("Raw w", self.raw_w, "Denoised w", self.den_w))
        s.addWidget(dbox)

        about_btn = QPushButton("About / References")
        about_btn.clicked.connect(self.references_requested.emit)
        s.addWidget(about_btn)
        s.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(cp)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.StyledPanel)
        cp.setMinimumWidth(265)
        scroll.setMinimumWidth(285)
        self.cp = cp
        main.addWidget(scroll, 0)

    # ---- parameter sub-panels -----------------------------------------
    def _build_fft_params(self):
        self.fft_panel = QWidget()
        s = QVBoxLayout(self.fft_panel)
        s.setContentsMargins(0, 0, 0, 0)
        self.n_spin = _spin(1, 100, 1)
        self.n_spin.valueChanged.connect(self.on_n_spin)
        s.addLayout(_row("Cut-off n =", self.n_spin))
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(1, 100)
        self.slider.setValue(1)
        self.slider.valueChanged.connect(self.on_slider)
        s.addWidget(self.slider)
        self.slope_ctrl = _dspin(0.5, 20.0, 3.0, 0.5)
        self.slope_ctrl.valueChanged.connect(lambda _v: self._live_update())
        s.addLayout(_row("Slope", self.slope_ctrl, " (higher=sharper)"))

    def _build_wav_params(self):
        self.wav_panel = QWidget()
        s = QVBoxLayout(self.wav_panel)
        s.setContentsMargins(0, 0, 0, 0)
        self.wav_choice = QComboBox()
        self.wav_choice.addItems(engine.WAVELETS)
        self.wav_choice.setCurrentText("sym8")
        self.wav_choice.currentTextChanged.connect(lambda _t: self._live_update())
        s.addLayout(_row("Wavelet", self.wav_choice))
        self.wav_level = _spin(1, 12, 3, width=60)
        self.wav_level.valueChanged.connect(lambda _v: self._live_update())
        self.wav_mode = QComboBox()
        self.wav_mode.addItems(engine.WAVELET_MODES)
        self.wav_mode.currentTextChanged.connect(lambda _t: self._live_update())
        s.addLayout(_row("Level", self.wav_level, "Mode", self.wav_mode))
        self.wav_k = _dspin(0.1, 5.0, 1.0, 0.1)
        self.wav_k.valueChanged.connect(lambda _v: self._live_update())
        s.addLayout(_row("Threshold x", self.wav_k, " (higher=more smoothing)"))

    def _build_vmd_params(self):
        self.vmd_panel = QWidget()
        s = QVBoxLayout(self.vmd_panel)
        s.setContentsMargins(0, 0, 0, 0)
        self.vmd_K = _spin(2, 40, 6, width=60)
        self.vmd_K.valueChanged.connect(self.on_vmd_struct_changed)
        self.vmd_alpha = _spin(100, 50000, 2000, width=75)
        self.vmd_alpha.valueChanged.connect(self.on_vmd_struct_changed)
        s.addLayout(_row("Modes K", self.vmd_K, "Bandwidth", self.vmd_alpha))
        self.vmd_keep = _spin(1, 40, 3, width=60)
        self.vmd_keep.valueChanged.connect(lambda _v: self._live_update())
        s.addLayout(_row("Keep modes", self.vmd_keep, " lowest-frequency"))

    def _show_param_panel(self):
        self.fft_panel.setVisible(self.method == "FFT filter")
        self.wav_panel.setVisible(self.method == "Wavelet")
        self.vmd_panel.setVisible(self.method == "VMD")

    # ==================================================================
    # Plots panel
    # ==================================================================
    def _create_plots_panel(self, main):
        pp = QFrame()
        pp.setFrameShape(QFrame.StyledPanel)
        ps = QVBoxLayout(pp)
        ps.setContentsMargins(0, 0, 0, 0)
        self.fig = Figure(figsize=(8, 7))
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setFocusPolicy(Qt.ClickFocus)

        outer = self.fig.add_gridspec(3, 1, height_ratios=[3, 3, 3.4], hspace=0.28)
        self.ax_top = self.fig.add_subplot(outer[0])
        self.ax_tf = self.ax_top.twinx()
        self.ax_mid = self.fig.add_subplot(outer[1])
        inner = outer[2].subgridspec(2, 1, height_ratios=[0.5, 3], hspace=0.05)
        self.ax_result = self.fig.add_subplot(inner[1])
        self.ax_resid = self.fig.add_subplot(inner[0], sharex=self.ax_result)
        self.fig.subplots_adjust(top=0.975, bottom=0.055, left=0.10, right=0.90)

        self.rect_selector = RectangleSelector(
            self.ax_result, self._on_box_select, useblit=True, button=[1],
            minspanx=1e-9, minspany=1e-9, spancoords='data', interactive=False)
        self.rect_selector.set_active(False)

        ps.addWidget(self.canvas, 1)
        main.addWidget(pp, 1)

    @staticmethod
    def _style_axes(ax, lw=1.3):
        for sp in ax.spines.values():
            sp.set_linewidth(lw)
        ax.tick_params(width=lw)

    def _draw_empty(self):
        for ax in (self.ax_top, self.ax_mid, self.ax_resid, self.ax_result):
            ax.clear()
            self._style_axes(ax)
        self.ax_tf.clear()
        self.ax_tf.set_visible(False)
        self.ax_result.text(0.5, 0.5, "Open, import or drop a spectrum file\n"
                            "(Excel, VAMAS, ASC / TXT / DAT / CSV)",
                            ha='center', va='center', color='#888',
                            transform=self.ax_result.transAxes)
        self.canvas.draw_idle()

    # ==================================================================
    # Data list / selection
    # ==================================================================
    def set_document(self, document):
        self.document = document
        self.populate_data_list()

    def populate_data_list(self, select=None):
        """Refill the core-level combo and the batch list; keeps the ticks."""
        names = self.document.usable_names() if self.document else []
        prev = set(self.checked_names())
        current = select or self.data_combo.currentText()

        self._quiet = True
        self.data_combo.clear()
        self.data_combo.addItems(names)
        self.batch_list.clear()
        self._quiet = False
        if not names:
            self._reset_data()
            return
        if current not in names:
            current = names[0]
        to_check = (prev & set(names)) or {current}
        for nm in names:
            item = QListWidgetItem(nm)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if nm in to_check else Qt.Unchecked)
            self.batch_list.addItem(item)
        self._quiet = True
        self.data_combo.setCurrentText(current)
        self._quiet = False
        if current != self.current_sheet or self.x is None:
            self.load_selected_data()

    def _reset_data(self):
        self.x = self.y = self.y_filtered = None
        self.current_sheet = None
        self.N = self.M = 0
        self._update_points_label()
        self.status_label.setText("")
        self._draw_empty()

    def checked_names(self):
        return [self.batch_list.item(i).text() for i in range(self.batch_list.count())
                if self.batch_list.item(i).checkState() == Qt.Checked]

    def set_checked(self, names):
        names = set(names)
        for i in range(self.batch_list.count()):
            it = self.batch_list.item(i)
            it.setCheckState(Qt.Checked if it.text() in names else Qt.Unchecked)

    def select_spectrum(self, name):
        if name and self.data_combo.findText(name) >= 0:
            self.data_combo.setCurrentText(name)
            return True
        return False

    def on_data_selected(self, _text=None):
        if not self._quiet:
            self.load_selected_data()

    def load_selected_data(self):
        nm = self.data_combo.currentText()
        if not nm or self.document is None or self.document.get(nm) is None:
            return
        cl = self.document.get(nm)
        try:
            self.x = np.array(cl['B.E.'], dtype=float)
            self.y = np.array(cl['Raw Data'], dtype=float)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"Could not read data: {e}")
            return
        self.current_sheet = nm
        # Axis conventions follow the spectrum's technique — an EELS spectrum
        # runs low->high in energy loss, XPS high->low in binding energy.
        self.x_label, self.y_label = axis_labels(nm, cl)
        self.x_reversed = x_reversed(nm, cl)
        self.N = len(self.y)
        self.baseline = np.linspace(self.y[0], self.y[-1], self.N)
        self._vmd_cache = {'key': None, 'modes': None, 'omega': None}

        # FFT transform (also drives the FFT cut-off range)
        self.coeffs = np.fft.rfft(self.y - self.baseline)
        self.M = len(self.coeffs)
        self.n_axis = np.arange(self.M)
        self.lnC = engine.ln_coeffs(self.coeffs)
        self.contrib, self.contrib_vmax = engine.fft_contributions(self.coeffs, self.N)

        self._update_points_label()
        self._quiet = True
        self.n_spin.setRange(1, max(1, self.M - 1))
        self.slider.setRange(1, max(1, self.M - 1))
        self.wav_level.setRange(1, self._wav_max_level())
        self._quiet = False

        self.result_ylim = None
        self.result_xlim = None
        self.spectrum_selected.emit(nm)
        self.on_auto()        # sensible defaults for the active method, then plot

    # ==================================================================
    # Method switching / auto
    # ==================================================================
    def _apply_xdir(self, ax):
        """Set the x limits in the technique's reading direction."""
        if self.x_reversed:
            ax.set_xlim(self.x.max(), self.x.min())
        else:
            ax.set_xlim(self.x.min(), self.x.max())

    def _update_points_label(self):
        if self.x is None:
            self.points_text.setText("Points: -")
        elif self.method == "FFT filter":
            self.points_text.setText(f"Points: {self.N}   (FFT coeffs: {self.M})")
        else:
            self.points_text.setText(f"Points: {self.N}")

    def on_method_changed(self, text=None):
        if self._quiet:
            return
        self.method = self.method_choice.currentText()
        self._show_param_panel()
        self._update_points_label()
        if self.x is not None:
            self.on_auto()

    def set_method(self, method):
        if method not in METHODS:
            raise ValueError(f"Unknown method {method!r}; choose one of {METHODS}")
        if self.method_choice.currentText() == method:
            return
        self.method_choice.setCurrentText(method)

    def on_auto(self, *_):
        """Set recommended parameters for the active method, then redraw."""
        if self.x is None:
            return
        self._busy(True)
        try:
            self._quiet = True
            if self.method == "FFT filter":
                cutoff, floor, thr = engine.fft_recommended(self.lnC, self.M)
                self.noise_floor, self.noise_thr = floor, thr
                self._set_cutoff(cutoff)
            elif self.method == "Wavelet":
                self.wav_level.setValue(min(self._wav_max_level(), 4))
                self.wav_k.setValue(1.0)
            elif self.method == "VMD":
                K, keep = engine.vmd_auto_K_keep(self.y - self.baseline,
                                                 float(self.vmd_alpha.value()))
                self.vmd_K.setValue(K)
                self.vmd_keep.setRange(1, K)
                self.vmd_keep.setValue(min(keep, K))
        finally:
            self._quiet = False
            self._busy(False)
        self.update_all_plots()

    # ---- FFT cut-off plumbing ----
    def _set_cutoff(self, n_c):
        n_c = int(max(1, min(n_c, self.M - 1)))
        self.n_spin.setValue(n_c)
        self.slider.setValue(n_c)

    def on_n_spin(self, value):
        if self._quiet:
            return
        self._quiet = True
        self.slider.setValue(value)
        self._quiet = False
        self.update_all_plots()

    def on_slider(self, value):
        if self._quiet:
            return
        self._quiet = True
        self.n_spin.setValue(value)
        self._quiet = False
        self.update_all_plots()

    def on_vmd_struct_changed(self, *_):
        # K or bandwidth changed -> VMD must be recomputed; clamp keep range
        if self._quiet:
            return
        self.vmd_keep.setRange(1, self.vmd_K.value())
        self.update_all_plots()

    def _live_update(self):
        if not self._quiet:
            self.update_all_plots()

    def _batch_check_all(self, state):
        for i in range(self.batch_list.count()):
            self.batch_list.item(i).setCheckState(Qt.Checked if state else Qt.Unchecked)

    def _wav_max_level(self):
        return engine.wav_max_level(self.N, self.wav_choice.currentText() or 'sym8')

    # ==================================================================
    # Parameters
    # ==================================================================
    def active_params(self):
        p = {'method': self.method}
        if self.method == "FFT filter":
            p.update(cutoff=int(self.n_spin.value()), slope=float(self.slope_ctrl.value()))
        elif self.method == "Wavelet":
            p.update(wavelet=self.wav_choice.currentText(), level=self.wav_level.value(),
                     mode=self.wav_mode.currentText(), k=float(self.wav_k.value()))
        elif self.method == "VMD":
            p.update(K=self.vmd_K.value(), alpha=float(self.vmd_alpha.value()),
                     keep=self.vmd_keep.value())
        return p

    def _held_controls(self):
        """The controls Auto leaves alone (slope, wavelet / mode, bandwidth)."""
        return {'slope': float(self.slope_ctrl.value()),
                'wavelet': self.wav_choice.currentText(),
                'mode': self.wav_mode.currentText(),
                'alpha': float(self.vmd_alpha.value())}

    def auto_params_for(self, x, y):
        return engine.auto_params(x, y, self.method, self._held_controls())

    def set_params(self, params, redraw=True):
        """Put *params* in the controls (method included) and redraw."""
        method = params.get('method', self.method)
        self._quiet = True
        try:
            if method != self.method:
                self.method_choice.setCurrentText(method)
                self.method = method
                self._show_param_panel()
                self._update_points_label()
            if method == "FFT filter":
                if 'cutoff' in params:
                    self._set_cutoff(int(params['cutoff']))
                if 'slope' in params:
                    self.slope_ctrl.setValue(float(params['slope']))
            elif method == "Wavelet":
                if 'wavelet' in params:
                    if params['wavelet'] not in engine.WAVELETS:
                        raise ValueError(f"wavelet must be one of {engine.WAVELETS}")
                    self.wav_choice.setCurrentText(params['wavelet'])
                if 'level' in params:
                    self.wav_level.setValue(int(params['level']))
                if 'mode' in params:
                    if params['mode'] not in engine.WAVELET_MODES:
                        raise ValueError("mode must be 'soft' or 'hard'")
                    self.wav_mode.setCurrentText(params['mode'])
                if 'k' in params:
                    self.wav_k.setValue(float(params['k']))
            elif method == "VMD":
                if 'K' in params:
                    self.vmd_K.setValue(int(params['K']))
                if 'alpha' in params:
                    self.vmd_alpha.setValue(int(round(float(params['alpha']))))
                self.vmd_keep.setRange(1, self.vmd_K.value())
                if 'keep' in params:
                    self.vmd_keep.setValue(int(params['keep']))
        finally:
            self._quiet = False
        if redraw:
            self.update_all_plots()

    def _get_vmd_modes(self):
        """Run VMD (cached by sheet/K/alpha). Returns (modes [K x N], omega [K])."""
        K = self.vmd_K.value()
        alpha = float(self.vmd_alpha.value())
        key = (self.current_sheet, K, alpha, self.N)
        if self._vmd_cache['key'] == key and self._vmd_cache['modes'] is not None:
            return self._vmd_cache['modes'], self._vmd_cache['omega']
        modes, omega = engine.vmd_modes(self.y - self.baseline, alpha, K, self.N)
        self._vmd_cache = {'key': key, 'modes': modes, 'omega': omega}
        return modes, omega

    # ==================================================================
    # Plotting
    # ==================================================================
    def _busy(self, on):
        if on:
            QApplication.setOverrideCursor(Qt.WaitCursor)
        else:
            QApplication.restoreOverrideCursor()

    def update_all_plots(self, show_errors=True):
        """Recompute the denoised curve for the controls and redraw.
        Returns an error string ('' on success)."""
        if self.x is None:
            return "No spectrum loaded."
        params = self.active_params()
        self._busy(True)
        try:
            if self.method == "FFT filter":
                self.y_filtered = engine.denoise(self.x, self.y, params)
                self._plot_fft(params)
            elif self.method == "Wavelet":
                self.y_filtered, aux = self._wav_preview(params)
                self._plot_wav(params, aux)
            elif self.method == "VMD":
                self.y_filtered, aux = self._vmd_preview(params)
                self._plot_vmd(params, aux)
        except ImportError:
            msg = ("PyWavelets is required for the Wavelet method.\n"
                   "Install it with:  pip install PyWavelets")
            if show_errors:
                QMessageBox.critical(self, "Missing dependency", msg)
            return msg
        except Exception as e:  # noqa: BLE001
            if show_errors:
                QMessageBox.critical(self, "Error", f"Denoising failed: {e}")
            import traceback
            traceback.print_exc()
            return f"Denoising failed: {e}"
        finally:
            self._busy(False)
        self._plot_result()
        self.canvas.draw()
        return ""

    # ---- FFT plots ----
    def _plot_fft(self, params):
        n_c = params['cutoff']
        H = engine.fft_build_filter(self.M, n_c, params['slope'])
        self.ax_tf.set_visible(True)
        self.ax_top.clear(); self.ax_tf.clear()
        ln, = self.ax_top.plot(self.n_axis, self.lnC, color='black', linewidth=1.4, label='ln|Cn|')
        self.ax_top.axvline(n_c, color='gray', linestyle=':', linewidth=1.2)
        tf, = self.ax_tf.plot(self.n_axis, H, color=GREEN_RGB, linewidth=2.2, label='Filter')
        self.ax_tf.set_ylim(0, 1.05)
        handles = [ln, tf]
        if self.noise_thr is not None:
            tl = self.ax_top.axhline(self.noise_thr, color=OPP_RGB, linewidth=1.6,
                                     linestyle='--', label='Noise level')
            handles.append(tl)
        self.ax_top.set_xlabel('Fourier Coefficients (n)'); self.ax_top.set_ylabel('ln(Cn)')
        self.ax_tf.set_ylabel('Transfer Function')
        self.ax_tf.yaxis.set_label_position('right'); self.ax_tf.yaxis.tick_right()
        self.ax_top.set_xlim(0, self.M - 1)
        self.ax_top.legend(handles=handles, loc='upper right', fontsize=7, ncol=3)
        self._style_axes(self.ax_top); self._style_axes(self.ax_tf)
        self.status_label.setText(f"FFT  cut-off n={n_c}, slope {params['slope']:g}")

        # middle: per-coefficient contribution map (magnitude, multi-hue scale)
        self.ax_mid.clear()
        mag = np.abs(self.contrib)
        norm = SymLogNorm(linthresh=self.contrib_vmax * 1e-2, vmin=0.0,
                          vmax=self.contrib_vmax, base=10)
        self.ax_mid.imshow(mag, aspect='auto', origin='lower', cmap='viridis',
                           norm=norm, extent=[self.x[0], self.x[-1], 0, self.M - 1],
                           interpolation='nearest')
        self.ax_mid.axhline(n_c, color='white', linestyle=':', linewidth=1.2)
        self._apply_xdir(self.ax_mid); self.ax_mid.set_ylim(0, self.M - 1)
        self.ax_mid.set_ylabel('Fourier Coefficients (n)')
        self.ax_mid.set_xlabel(self.x_label)
        self._style_axes(self.ax_mid)

    # ---- Wavelet ----
    def _wav_preview(self, params):
        d = self.y - self.baseline
        rec, aux = engine.wav_decompose(d, params['wavelet'], params['level'],
                                        params['mode'], params['k'])
        return rec + self.baseline, aux

    def _plot_wav(self, params, aux):
        self.ax_tf.set_visible(False); self.ax_tf.clear()
        self.ax_top.clear()
        cof, thr, lvl = aux['cof'], aux['thr'], aux['lvl']
        details = cof[1:]
        lvl_idx = list(range(lvl, 0, -1))          # finest(1) .. coarsest(lvl)
        rms = [np.sqrt(np.mean(c ** 2)) for c in details]
        xs = lvl_idx
        self.ax_top.bar(xs, rms, color=GREEN_RGB, width=0.6, label='detail RMS')
        self.ax_top.axhline(thr, color=OPP_RGB, linewidth=1.6, linestyle='--', label='threshold')
        self.ax_top.set_xlabel('Detail level (1 = finest / highest freq)')
        self.ax_top.set_ylabel('coeff RMS')
        self.ax_top.set_xticks(sorted(set(xs)))
        self.ax_top.set_xlim(0.5, lvl + 0.5)
        self.ax_top.legend(loc='upper right', fontsize=7)
        self._style_axes(self.ax_top)
        self.status_label.setText(f"Wavelet {params['wavelet']} L{lvl} {params['mode']} x{params['k']:g}")

        # middle: scalogram of the detail coefficients
        self.ax_mid.clear()
        rows = []
        for c in cof[1:]:                          # detail coeffs, coarsest..finest
            up = np.repeat(c, int(np.ceil(self.N / len(c))))[:self.N]
            rows.append(up)
        rows = rows[::-1]                           # finest at top
        img = np.array(rows) if rows else np.zeros((1, self.N))
        vmax = np.max(np.abs(img)) or 1.0
        norm = SymLogNorm(linthresh=vmax * 1e-2, vmin=-vmax, vmax=vmax, base=10)
        self.ax_mid.imshow(img, aspect='auto', origin='upper', cmap=DIVERGING_CMAP, norm=norm,
                           extent=[self.x[0], self.x[-1], 0.5, len(rows) + 0.5],
                           interpolation='nearest')
        self._apply_xdir(self.ax_mid)
        self.ax_mid.set_ylabel('Detail level (1=finest, top)')
        self.ax_mid.set_xlabel(self.x_label)
        self._style_axes(self.ax_mid)

    # ---- VMD ----
    def _vmd_preview(self, params):
        modes, omega = self._get_vmd_modes()
        order = np.argsort(omega)
        keep = order[:max(1, min(params['keep'], len(order)))]
        y_filt = modes[keep].sum(axis=0) + self.baseline
        aux = {'modes': modes, 'omega': omega, 'keep': set(keep.tolist()), 'order': order}
        return y_filt, aux

    def _plot_vmd(self, params, aux):
        self.ax_tf.set_visible(False); self.ax_tf.clear()
        self.ax_top.clear()
        modes, omega, keep = aux['modes'], aux['omega'], aux['keep']
        energy = np.sum(modes ** 2, axis=1)
        for i in range(len(omega)):
            col = GREEN_RGB if i in keep else OPP_RGB
            self.ax_top.vlines(omega[i], 1.0, max(energy[i], 1.0), color=col, linewidth=2)
            self.ax_top.plot(omega[i], max(energy[i], 1.0), 'o', color=col, markersize=5)
        self.ax_top.set_yscale('log')
        self.ax_top.set_xlim(-0.02, 0.52)
        self.ax_top.set_xlabel('Mode centre frequency (cycles/point)')
        self.ax_top.set_ylabel('Mode energy')
        self.ax_top.legend(handles=[Line2D([0], [0], color=GREEN_RGB, marker='o', label='kept'),
                                    Line2D([0], [0], color=OPP_RGB, marker='o', label='dropped')],
                           loc='upper right', fontsize=7)
        self._style_axes(self.ax_top)
        self.status_label.setText(f"VMD K={params['K']} keep {params['keep']} (alpha {params['alpha']:g})")

        # middle: the modes stacked, low-freq at bottom, kept=green / dropped=magenta
        self.ax_mid.clear()
        order = aux['order']
        for row, mi in enumerate(order):
            m = modes[mi]
            amax = np.max(np.abs(m)) or 1.0
            col = GREEN_RGB if mi in keep else OPP_RGB
            self.ax_mid.plot(self.x, 0.42 * m / amax + (row + 1), color=col, linewidth=1.0)
        self._apply_xdir(self.ax_mid)
        self.ax_mid.set_ylim(0.4, len(order) + 0.6)
        self.ax_mid.set_yticks(range(1, len(order) + 1))
        self.ax_mid.set_ylabel('VMD modes (low->high freq)')
        self.ax_mid.set_xlabel(self.x_label)
        self._style_axes(self.ax_mid)

    # ---- shared result plot ----
    def _plot_result(self):
        resid = self.y - self.y_filtered
        self.ax_resid.clear()
        self.ax_resid.plot(self.x, resid, color=OPP_RGB, linewidth=1.1)
        self.ax_resid.axhline(0, color='gray', linewidth=0.7)
        self.ax_resid.set_ylabel('Resid.', fontsize=7)
        self.ax_resid.tick_params(labelsize=6)
        for lab in self.ax_resid.get_xticklabels():
            lab.set_visible(False)

        self.ax_result.clear()
        shown = False
        if self.show_raw_cb.isChecked():
            if self.raw_style.currentText() == "Scatter":
                self.ax_result.plot(self.x, self.y, linestyle='none', marker='o',
                                    markersize=max(2.0, self.raw_w.value() * 2.2),
                                    color='black', label='Raw')
            else:
                self.ax_result.plot(self.x, self.y, color='black',
                                    linewidth=self.raw_w.value(), label='Raw')
            shown = True
        if self.show_den_cb.isChecked():
            self.ax_result.plot(self.x, self.y_filtered, color=GREEN_RGB,
                                linewidth=self.den_w.value(), label='Denoised')
            shown = True
        self._apply_xdir(self.ax_result)
        self.ax_result.set_xlabel(self.x_label)
        self.ax_result.set_ylabel(self.y_label)
        if shown:
            self.ax_result.legend(loc='best', fontsize=7)
        fm = ScalarFormatter(useMathText=True); fm.set_scientific(True); fm.set_powerlimits((-2, 3))
        self.ax_result.yaxis.set_major_formatter(fm)
        if self.result_xlim is not None:
            self.ax_result.set_xlim(self.result_xlim)
        if self.result_ylim is not None:
            self.ax_result.set_ylim(self.result_ylim)
        self._style_axes(self.ax_resid); self._style_axes(self.ax_result)

    # ==================================================================
    # Zoom
    # ==================================================================
    def on_result_style(self, *_):
        """Redraw only the result plot (style change, no recompute)."""
        if self.y_filtered is not None:
            self._plot_result()
            self.canvas.draw()

    def on_zoom_y(self, factor):
        if self.y_filtered is None:
            return
        lo, hi = self.ax_result.get_ylim()
        mid = 0.5 * (lo + hi); half = 0.5 * (hi - lo) * factor
        self.result_ylim = (mid - half, mid + half)
        self.ax_result.set_ylim(self.result_ylim); self.canvas.draw()

    def on_zoom_reset(self):
        self.result_ylim = None; self.result_xlim = None
        self.update_all_plots()

    def on_box_zoom_toggle(self, *_):
        if self.rect_selector is None:
            return
        self.box_zoom_on = not self.box_zoom_on
        self.rect_selector.set_active(self.box_zoom_on)
        self._set_box_btn(self.box_zoom_on)

    def _set_box_btn(self, active):
        if active:
            self.box_zoom_btn.setText("Drag a box…")
            self.box_zoom_btn.setStyleSheet(_GREEN_BTN)
        else:
            self.box_zoom_btn.setText("Zoom in (box)")
            self.box_zoom_btn.setStyleSheet("")

    def _on_box_select(self, eclick, erelease):
        x0, x1 = eclick.xdata, erelease.xdata
        y0, y1 = eclick.ydata, erelease.ydata
        if None in (x0, x1, y0, y1) or x0 == x1 or y0 == y1:
            return
        if self.x_reversed:
            self.result_xlim = (max(x0, x1), min(x0, x1))
        else:
            self.result_xlim = (min(x0, x1), max(x0, x1))
        self.result_ylim = (min(y0, y1), max(y0, y1))
        self.ax_result.set_xlim(self.result_xlim); self.ax_result.set_ylim(self.result_ylim)
        self.box_zoom_on = False; self.rect_selector.set_active(False); self._set_box_btn(False)
        self.canvas.draw_idle()

    def on_zoom_out(self):
        if self.y_filtered is None:
            return
        xhi, xlo = self.ax_result.get_xlim(); ylo, yhi = self.ax_result.get_ylim()
        xc, xh = 0.5 * (xhi + xlo), 0.5 * (xhi - xlo) * 1.6
        yc, yh = 0.5 * (yhi + ylo), 0.5 * (yhi - ylo) * 1.6
        self.result_xlim = (xc + xh, xc - xh); self.result_ylim = (yc - yh, yc + yh)
        self.ax_result.set_xlim(self.result_xlim); self.ax_result.set_ylim(self.result_ylim)
        self.canvas.draw()

    # ==================================================================
    # Create denoised spectra
    # ==================================================================
    def create_spectra(self, targets=None, auto=None, params=None):
        """Denoise *targets* into new spectra.  No dialogs (MCP uses this).

        *targets* defaults to the ticked list, then the selected spectrum;
        *auto* to the "Auto parameters per spectrum" box; *params* to the
        controls.  Returns (created names, errors)."""
        if self.document is None:
            return [], ["No document."]
        if targets is None:
            targets = self.checked_names() or ([self.current_sheet] if self.current_sheet else [])
        if not targets:
            return [], ["No core level selected."]
        auto = self.auto_params_cb.isChecked() if auto is None else bool(auto)
        cur_params = dict(params) if params else self.active_params()
        method = cur_params.get('method', self.method)
        created, errors = [], []

        def run():
            for name in targets:
                cl = self.document.get(name)
                if cl is None or 'B.E.' not in cl or 'Raw Data' not in cl:
                    errors.append(f"{name}: no such spectrum")
                    continue
                x = np.array(cl['B.E.'], dtype=float)
                y = np.array(cl['Raw Data'], dtype=float)
                try:
                    p = (engine.auto_params(x, y, method, self._held_controls())
                         if auto else cur_params)
                    yf = np.asarray(engine.denoise(x, y, p), dtype=float)
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{name}: {e}")
                    continue
                if len(yf) < len(x):
                    yf = np.append(yf, [yf[-1]] * (len(x) - len(yf)))
                yf = yf[:len(x)].tolist()
                new_name = self.document.next_sheet_name(name, method)
                new_cl = {'Name': new_name, 'B.E.': x.tolist(), 'Raw Data': yf,
                          'Corrected Data': yf, 'Transmission': [1.0] * len(x),
                          'Denoise': {'source': name,
                                      'params': {k: (float(v) if isinstance(v, (np.floating,)) else v)
                                                 for k, v in p.items()}}}
                for key in ('X_Label', 'Y_Label', 'X_Reversed', 'Technique',
                            'ExperimentalInfo'):
                    if key in cl:
                        new_cl[key] = cl[key]
                self.document.add(new_cl, replace=True)
                created.append(new_name)

        self._busy(True)
        try:
            self.change_hook(f"Create denoised ({method})", run)
        finally:
            self._busy(False)
        if created:
            self.populate_data_list()
            self.spectra_created.emit(created)
        return created, errors

    def on_create(self, *_):
        if self.x is None:
            QMessageBox.warning(self, "No Data", "Select a core level first.")
            return
        created, errors = self.create_spectra()
        if not created:
            QMessageBox.warning(self, "Spectral Denoising",
                                "Nothing was created." + ("\n\n" + "\n".join(errors) if errors else ""))
            return
        msg = (f"Created {len(created)} denoised sheet(s) with method '{self.method}':\n"
               + "\n".join(created) + "\n\nThe active core level is unchanged.")
        if errors:
            msg += "\n\nSkipped:\n" + "\n".join(errors)
        QMessageBox.information(self, "Denoised Sheets Created", msg)
