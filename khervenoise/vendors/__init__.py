"""Instrument (vendor) file formats — ports of KherveFitting's importers.

Each module in this package is Qt-free and declares the formats it reads
in a module-level ``FORMATS`` list of :class:`Format`.  A reader takes a
path and returns an :class:`khervenoise.importers.ImportResult` whose
spectra hold the same ``'B.E.'`` / ``'Raw Data'`` values KherveFitting's
importer puts in ``Data['Core levels']`` for the same file.

``importers.read_any`` and the File ▸ Import ▸ Instrument menu are built
from :func:`all_formats`, so a new format is one ``Format`` entry here.

Copyright (C) 2026 Gwilherm Kerherve
Licensed under the GNU General Public License v3.0 (see LICENSE).
"""

import importlib
from dataclasses import dataclass, field
from typing import Callable, Optional, Tuple

#: Modules holding a FORMATS list, in menu order.
MODULES = (
    "avantage", "vgd", "avg",            # Thermo Scientific
    "kal",                               # Kratos
    "spe", "pro",                        # PHI (Physical Electronics)
    "scienta",                           # Scienta Omicron
    "mrs", "vgmicrotech", "igor",        # MRS, VG-Microtech, Igor Pro
    "diamond",                           # Diamond Light Source
    "sdp",                               # XPS International (SDP)
)


@dataclass
class Format:
    key: str                         # short id, e.g. "vgd"
    label: str                       # menu text, e.g. "VGD file (.vgd)"
    group: str                       # menu group, e.g. "Thermo"
    extensions: Tuple[str, ...]      # lower-case, with the dot
    reader: Callable                 # reader(path) -> ImportResult
    #: Optional content test for extensions shared with other formats
    #: (.xlsx, .dat, .txt, .h5): sniff(path) -> bool.
    sniff: Optional[Callable] = None
    #: Shown once before importing (e.g. third-party format notices).
    notice: str = ""
    #: Lower runs first when several formats claim the same extension.
    priority: int = 50
    extra: dict = field(default_factory=dict)

    @property
    def file_filter(self):
        pats = " ".join(f"*{e}" for e in self.extensions)
        return f"{self.label.split(' (')[0]} ({pats})"


_CACHE = None


def all_formats():
    """Every registered Format (modules that fail to import are skipped)."""
    global _CACHE
    if _CACHE is None:
        found = []
        for name in MODULES:
            try:
                mod = importlib.import_module(f"{__name__}.{name}")
            except Exception:  # noqa: BLE001 — a missing optional library
                continue
            found.extend(getattr(mod, "FORMATS", []))
        _CACHE = found
    return list(_CACHE)


def formats_for(path):
    """Formats that can read *path*: extension match, then sniff, by priority."""
    low = str(path).lower()
    out = []
    for fmt in all_formats():
        if not low.endswith(fmt.extensions):
            continue
        if fmt.sniff is not None:
            try:
                if not fmt.sniff(path):
                    continue
            except Exception:  # noqa: BLE001
                continue
        out.append(fmt)
    return sorted(out, key=lambda f: f.priority)


def groups():
    """{group: [Format, …]} in registration order."""
    out = {}
    for fmt in all_formats():
        out.setdefault(fmt.group, []).append(fmt)
    return out


def extensions():
    exts = []
    for fmt in all_formats():
        for e in fmt.extensions:
            if e not in exts:
                exts.append(e)
    return tuple(exts)
