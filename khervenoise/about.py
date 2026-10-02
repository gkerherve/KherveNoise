"""File ▸ About KherveNoise: the app, its author and khervetools.com.

Laid out like KherveSlide's and KherveTeX's About — the app icon beside the
name and version, then the author, the Kherve tools family and what
KherveNoise is built with.

Copyright (C) 2026 Gwilherm Kerherve
Licensed under the GNU General Public License v3.0 (see LICENSE).
"""

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                               QTextBrowser, QVBoxLayout)

from . import APP_NAME, GREEN_HEX, REPO, __version__
from . import icons

KHERVETOOLS_URL = "https://khervetools.com"
GITHUB_URL = f"https://github.com/{REPO}"
KHERVEFITTING_PAPER = "https://doi.org/10.1002/sia.70032"

#: The family, as listed on khervetools.com.
KHERVE_TOOLS = (
    ("KherveFitting", "peak fitting for XPS spectra"),
    ("KherveNoise", "spectral denoising — FFT, wavelet and VMD"),
    ("KhervePlot", "Origin-style plotting and data analysis"),
    ("KherveTeX", "Word-like writing that produces LaTeX"),
    ("KherveSlide", "PowerPoint-like slides that produce beamer LaTeX"),
    ("KherveCAD", "easy CAD with OpenSCAD as the engine"),
    ("KherveMol", "molecules and crystals in 3D and 2D"),
    ("KherveSheet", "spreadsheets"),
    ("KherveBook", "notebooks"),
    ("KhervePDF", "reading and annotating PDFs"),
    ("KhervePaint", "drawing and scientific sketches"),
)


def _ver(mod: str) -> str:
    try:
        return str(__import__(mod).__version__)
    except Exception:  # noqa: BLE001
        return "—"


def about_html(version: str = __version__) -> str:
    from PySide6 import __version__ as pyside_version
    from PySide6.QtCore import qVersion
    tools = "".join(
        f"<li><b>{name}</b> — {what}</li>" for name, what in KHERVE_TOOLS)
    return (
        "<h3>About the author</h3>"
        "<p><b>Gwilherm Kerherv&eacute;</b> &nbsp;—&nbsp; Research "
        "Associate, Department of Materials, "
        "<a href='https://www.imperial.ac.uk/materials/'>Imperial College "
        "London</a>.</p>"
        "<p>Works on surface analysis and X-ray Photoelectron Spectroscopy "
        "(XPS), with a focus on materials for energy storage and "
        "catalysis, and writes free, open-source tools for scientists. "
        "He is the author of <b>KherveFitting</b>, the open-source XPS "
        "peak-fitting program "
        f"(<a href='{KHERVEFITTING_PAPER}'>Surf. Interface Anal., "
        "doi:10.1002/sia.70032</a>). KherveNoise is its Spectral Denoising "
        "tool released as a program of its own, so that any spectrum — "
        "XPS, Raman, FTIR, XAS, EELS… — can be cleaned up without opening "
        "a fitting project.</p>"
        "<p><a href='mailto:g.kerherve@imperial.ac.uk'>"
        "g.kerherve@imperial.ac.uk</a> &nbsp;·&nbsp; "
        "<a href='https://www.imperial.ac.uk/people/g.kerherve'>Imperial "
        "College profile</a> &nbsp;·&nbsp; "
        "<a href='https://www.linkedin.com/in/gwilherm-kerherve-3588b978/'>"
        "LinkedIn</a> &nbsp;·&nbsp; "
        "<a href='https://github.com/gkerherve'>github.com/gkerherve</a> "
        "&nbsp;·&nbsp; <a href='https://buymeacoffee.com/gkerherve'>Buy me "
        "a coffee</a></p>"
        "<hr>"
        f"<h3><a href='{KHERVETOOLS_URL}'>khervetools.com</a></h3>"
        "<p>The home of the <b>Kherve</b> family of free, open-source "
        "desktop apps for science, teaching and everyday work — "
        "downloads, user guides, news and workshops (free to attend). "
        "They share one look and feel, and many talk to an AI assistant "
        "(Claude) through MCP.</p>"
        f"<ul style='margin-top:2px'>{tools}</ul>"
        "<hr>"
        f"<h3>{APP_NAME}</h3>"
        "<p>Denoise a spectrum without training data, with three classical "
        "methods — Variational Mode Decomposition, wavelet shrinkage and an "
        "FFT low-pass filter — and see what each one keeps and removes. "
        "Imports Excel, VAMAS and plain data files; exports straight back "
        "to KherveFitting. Press <b>F1</b> for the User Guide.</p>"
        f"<p style='color:#666'>Version {version} &nbsp;·&nbsp; "
        f"<a href='{GITHUB_URL}'>source on GitHub</a></p>"
        "<p style='color:#666'><b>Built with</b> Python "
        f"{sys.version.split()[0]}, Qt {qVersion()}, PySide6 "
        f"{pyside_version}, NumPy {_ver('numpy')}, matplotlib "
        f"{_ver('matplotlib')}, PyWavelets {_ver('pywt')} and the "
        "<i>vamas</i> reader.</p>"
        "<p>Copyright &copy; 2026 Gwilherm Kerherv&eacute; — licensed "
        "under the <a href='https://www.gnu.org/licenses/gpl-3.0.html'>GNU "
        "GPL v3.0</a>.</p>")


class AboutDialog(QDialog):
    def __init__(self, parent=None, version: str = __version__):
        super().__init__(parent)
        self.setWindowTitle(f"About {APP_NAME}")
        self.resize(640, 700)
        lay = QVBoxLayout(self)
        head = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(icons.app_icon_pixmap(96))
        logo.setFixedSize(96, 96)
        head.addWidget(logo, 0, Qt.AlignTop)
        name = QLabel(
            "<h2 style='margin-bottom:0'>"
            "<span style='color:#2b2f36'>Kherve</span>"
            f"<span style='color:{GREEN_HEX}'>Noise</span></h2>"
            f"<p style='color:gray;margin-top:2px'>v{version}</p>"
            "<p>Spectral denoising — VMD, wavelet and FFT.<br>"
            f"Part of <a href='{KHERVETOOLS_URL}'>khervetools.com</a>.</p>")
        name.setOpenExternalLinks(True)
        head.addWidget(name, 1)
        lay.addLayout(head)
        self.text = QTextBrowser()
        self.text.setOpenExternalLinks(True)
        self.text.setHtml(about_html(version))
        lay.addWidget(self.text, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
