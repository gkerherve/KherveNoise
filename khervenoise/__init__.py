"""KherveNoise — spectral denoising (FFT / Wavelet / VMD) for spectroscopy.

A standalone copy of KherveFitting's Spectral Denoising window.

Copyright (C) 2026 Gwilherm Kerherve
Licensed under the GNU General Public License v3.0 (see LICENSE).
"""

import os

# matplotlib picks a Qt binding on its own; without this it may take
# PyQt5 when that is installed too, and two bindings in one process crash.
os.environ["QT_API"] = "pyside6"

APP_NAME = "KherveNoise"
ORG_NAME = "Kherve"
REPO = "gkerherve/KherveNoise"

#: KherveFitting brand green - RGB (79, 190, 159) = #4FBE9F
GREEN_HEX = "#4FBE9F"
#: Its complementary magenta, used for residuals / dropped components.
OPP_HEX = "#BE4FAA"

from ._version import get_version  # noqa: E402

__version__ = get_version()
