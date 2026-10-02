"""Spectral Denoising - Methods & References dialog.

The same text KherveFitting shows under its "About / References" button.

Copyright (C) 2026 Gwilherm Kerherve
Licensed under the GNU General Public License v3.0 (see LICENSE).
"""

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout

# Methods, acknowledgements and publication references.
ABOUT_HTML = """
<body bgcolor="#ffffff">
<h2>Spectral Denoising &mdash; methods &amp; references</h2>
<p>This tool denoises a single spectrum (no training data required) with a choice
of three classical, peer-reviewed signal-processing methods. It is an independent,
open-source implementation. Brief descriptions and primary references follow.</p>

<h3>1. FFT low-pass filter</h3>
<p>The spectrum is transformed to the Fourier (reciprocal) domain with the Fast
Fourier Transform; the coefficients are multiplied by a flat-topped half-Gaussian
low-pass transfer function and transformed back. The cut-off coefficient can be set
by hand or estimated from a noise-floor crossing of ln|C<sub>n</sub>|.</p>
<ul>
<li>Cooley, J.W. &amp; Tukey, J.W. <i>An algorithm for the machine calculation of complex
Fourier series.</i> Math. Comput. <b>19</b>, 297&ndash;301 (1965).
<a href="https://doi.org/10.1090/S0025-5718-1965-0178586-1">doi:10.1090/S0025-5718-1965-0178586-1</a></li>
<li>For a quantitative discussion of linear Fourier noise-reduction filters in
spectroscopy (theory and the optimality of the Gauss&ndash;Hermite filter): Aspnes, D.E.,
Le, L.V. &amp; Kim, Y.D. <i>Engineering the optimal filter: quantitative assessment of
linear noise-reducing filters in spectroscopy.</i> J. Appl. Phys. <b>139</b>, 114903 (2026).
<a href="https://doi.org/10.1063/5.0308052">doi:10.1063/5.0308052</a>
(this tool uses a plain flat-topped half-Gaussian, not a Gauss&ndash;Hermite filter).</li>
</ul>

<h3>2. Wavelet shrinkage</h3>
<p>A discrete wavelet transform decomposes the signal into approximation and detail
coefficients across scales; the detail coefficients are thresholded (soft/hard, with a
universal &sigma;&radic;(2&nbsp;ln&nbsp;N) threshold scaled by a user factor) and the signal is
reconstructed. Implemented with PyWavelets.</p>
<ul>
<li>Mallat, S.G. <i>A theory for multiresolution signal decomposition: the wavelet
representation.</i> IEEE Trans. Pattern Anal. Mach. Intell. <b>11</b>, 674&ndash;693 (1989).
<a href="https://doi.org/10.1109/34.192463">doi:10.1109/34.192463</a></li>
<li>Donoho, D.L. &amp; Johnstone, I.M. <i>Ideal spatial adaptation by wavelet shrinkage.</i>
Biometrika <b>81</b>, 425&ndash;455 (1994).
<a href="https://doi.org/10.1093/biomet/81.3.425">doi:10.1093/biomet/81.3.425</a></li>
<li>Donoho, D.L. <i>De-noising by soft-thresholding.</i> IEEE Trans. Inf. Theory
<b>41</b>, 613&ndash;627 (1995). <a href="https://doi.org/10.1109/18.382009">doi:10.1109/18.382009</a></li>
</ul>

<h3>3. Variational Mode Decomposition (VMD)</h3>
<p>VMD decomposes the signal into K band-limited modes by solving a constrained
variational problem; the low-frequency (signal) modes are summed and the
high-frequency (noise) modes discarded. Implemented in pure NumPy following the
original algorithm and the open-source <i>vmdpy</i> reference.</p>
<ul>
<li>Dragomiretskiy, K. &amp; Zosso, D. <i>Variational Mode Decomposition.</i> IEEE Trans.
Signal Process. <b>62</b>, 531&ndash;544 (2014).
<a href="https://doi.org/10.1109/TSP.2013.2288675">doi:10.1109/TSP.2013.2288675</a></li>
<li>Carvalho, V.R., Moraes, M.F.D., Braga, A.P. &amp; Mendes, E.M.A.M. <i>Evaluating
five different adaptive decomposition methods for EEG signal seizure detection and
classification</i> (vmdpy implementation). Biomed. Signal Process. Control <b>62</b>,
102073 (2020). <a href="https://doi.org/10.1016/j.bspc.2020.102073">doi:10.1016/j.bspc.2020.102073</a></li>
</ul>

<h3>Software libraries (with thanks)</h3>
<ul>
<li>NumPy &mdash; Harris, C.R. et al. <i>Array programming with NumPy.</i> Nature
<b>585</b>, 357&ndash;362 (2020). <a href="https://doi.org/10.1038/s41586-020-2649-2">doi:10.1038/s41586-020-2649-2</a></li>
<li>SciPy &mdash; Virtanen, P. et al. <i>SciPy 1.0: fundamental algorithms for scientific
computing in Python.</i> Nat. Methods <b>17</b>, 261&ndash;272 (2020).
<a href="https://doi.org/10.1038/s41592-019-0686-2">doi:10.1038/s41592-019-0686-2</a></li>
<li>Matplotlib &mdash; Hunter, J.D. <i>Matplotlib: a 2D graphics environment.</i> Comput.
Sci. Eng. <b>9</b>, 90&ndash;95 (2007). <a href="https://doi.org/10.1109/MCSE.2007.55">doi:10.1109/MCSE.2007.55</a></li>
<li>PyWavelets &mdash; Lee, G. et al. <i>PyWavelets: a Python package for wavelet analysis.</i>
J. Open Source Softw. <b>4</b>, 1237 (2019). <a href="https://doi.org/10.21105/joss.01237">doi:10.21105/joss.01237</a></li>
<li>Qt for Python (PySide6) &mdash; the Qt GUI toolkit, <a href="https://www.qt.io/qt-for-python">qt.io/qt-for-python</a>.</li>
</ul>
<p><font color="#777777">Denoising methods are long-published, public prior art; this is an
original implementation distributed with KherveFitting and KherveNoise.</font></p>
</body>
"""


class ReferencesDialog(QDialog):
    """Scrollable dialog listing the denoising methods, references and libraries."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Spectral Denoising - Methods & References")
        self.resize(660, 660)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        view = QTextBrowser()
        view.setOpenExternalLinks(True)
        view.setHtml(ABOUT_HTML)
        lay.addWidget(view, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
