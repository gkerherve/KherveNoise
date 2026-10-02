"""The open document: an ordered set of spectra, and its .knoise file.

A spectrum is a plain dict shaped like a KherveFitting core level, so the
importers, the denoiser and the KherveFitting-compatible Excel export all
speak the same language:

    {'Name': 'C1s', 'B.E.': [...], 'Raw Data': [...],
     'Corrected Data': [...], 'Transmission': [...],
     'ExperimentalInfo': {...},                    # optional
     'Denoise': {'source': 'C1s', 'params': {...}}  # on denoised copies}

The denoiser reads 'B.E.' (x) and 'Raw Data' (y), exactly as KherveFitting's
Spectral Denoising window does.  Qt-free.

Copyright (C) 2026 Gwilherm Kerherve
Licensed under the GNU General Public License v3.0 (see LICENSE).
"""

import copy
import json
import os
import re

from .engine import SUFFIX

FORMAT = "KherveNoise"
FORMAT_VERSION = 1
EXTENSION = ".knoise"

# ---------------------------------------------------------------------------
# Axis labels — KherveFitting's _TECHNIQUE_AXES, first match wins.
# ---------------------------------------------------------------------------
_TECHNIQUE_AXES = (
    (lambda n: n.startswith('EDX~Plot'), 'Energy (keV)', 'Counts'),
    (lambda n: n.startswith('TEM~Plot'), 'Distance (nm)', 'Intensity (a.u.)'),
    (lambda n: n.startswith('AFM~Profile'), 'Distance (nm)', 'Height (nm)'),
    (lambda n: n.startswith(('SEM', 'TEM~Count', 'TEM~Freq')),
     'Particle size (nm)', 'Count'),
    (lambda n: n.upper().startswith('FTIR'),
     'Wavenumber (cm$^{-1}$)', 'Transmittance (%)'),
    (lambda n: n.upper().startswith('EELS'),
     'Energy Loss (eV)', 'Intensity (a.u.)'),
    (lambda n: n.upper().startswith('EIS'), "Z' (Ω)", "-Z'' (Ω)"),
    (lambda n: n.upper().startswith('SQUID'), 'Temperature (K)', 'Moment (emu)'),
    (lambda n: n.upper().startswith('TGA'), 'Temperature (°C)', 'Mass (mg)'),
    (lambda n: n.upper().startswith('XRD'), '2θ (°)', 'Intensity (counts)'),
    (lambda n: n.startswith('XAS'), 'Photon Energy (eV)', 'Intensity (a.u.)'),
    (lambda n: n.upper().startswith('UVVIS'), 'Wavelength (nm)', 'Absorbance (a.u.)'),
    (lambda n: n.upper().startswith('ELLIPS'), 'Wavelength (nm)', '$\\Psi$ (°)'),
    (lambda n: n.upper().startswith('PL'), 'Wavelength (nm)', 'PL Intensity (a.u.)'),
    (lambda n: n.upper().startswith('MS'), 'm/z', 'Intensity (a.u.)'),
    (lambda n: n.upper().startswith('GC'), 'Retention time (min)', 'Signal (a.u.)'),
    (lambda n: n.upper().startswith('DIL'), 'Temperature (°C)', 'dL/L$_0$'),
    (lambda n: n.upper().startswith('BET'), 'Relative pressure (P/P$_0$)',
     'Quantity adsorbed (cm$^3$/g STP)'),
    (lambda n: n.startswith('RA') or 'RAMAN' in n.upper() or n.startswith('Ra_'),
     'Wavenumber (cm$^{-1}$)', 'Intensity (a.u.)'),
)

XPS_LABELS = ('Binding Energy (eV)', 'Intensity (CPS)')


def is_xps_like(name):
    """True when the spectrum really is on a binding-energy axis."""
    n = str(name or '')
    return not any(m(n) for m, _x, _y in _TECHNIQUE_AXES)


def axis_labels(name, spectrum=None):
    """(x label, y label) — a label stored on the spectrum wins."""
    n = str(name or '')
    sp = spectrum or {}
    for matches, x_label, y_label in _TECHNIQUE_AXES:
        if matches(n):
            return sp.get('X_Label') or x_label, sp.get('Y_Label') or y_label
    if sp.get('X_Label'):
        return sp['X_Label'], sp.get('Y_Label') or XPS_LABELS[1]
    return XPS_LABELS


def x_reversed(name, spectrum=None):
    """Axis direction, as the denoiser draws it: XPS (and FTIR) read high
    to low.  A spectrum may force it with 'X_Reversed'."""
    sp = spectrum or {}
    if 'X_Reversed' in sp:
        return bool(sp['X_Reversed'])
    return is_xps_like(name) or str(name).upper().startswith('FTIR')


def natural_sort_key(name):
    parts = re.split(r'(\d+)', str(name))
    return [int(p) if p.isdigit() else p.lower() for p in parts]


def make_spectrum(name, x, y, raw=None, transmission=None, info=None,
                  x_label=None, y_label=None):
    """A spectrum dict, every column cut to the shortest (as KherveFitting's
    build_core_level_Data does)."""
    x = [float(v) for v in x]
    y = [float(v) for v in y]
    raw = [float(v) for v in raw] if raw is not None else list(y)
    trans = ([float(v) for v in transmission] if transmission is not None
             else [1.0] * len(y))
    n = min(len(x), len(y), len(raw), len(trans))
    sp = {'Name': name, 'B.E.': x[:n], 'Raw Data': y[:n],
          'Corrected Data': raw[:n], 'Transmission': trans[:n]}
    if info:
        sp['ExperimentalInfo'] = {str(k): ('' if v is None else str(v).strip())
                                  for k, v in info.items()}
    if x_label:
        sp['X_Label'] = str(x_label)
    if y_label:
        sp['Y_Label'] = str(y_label)
    return sp


class Document:
    """Ordered spectra + the file they came from.  Qt-free."""

    def __init__(self):
        self.spectra = {}          # name -> spectrum dict, insertion order
        self.path = None           # .knoise path once saved/opened
        self.source = None         # file the data were imported from
        self.dirty = False

    # ── access ───────────────────────────────────────────────────────
    def names(self, sort=False):
        names = list(self.spectra)
        return sorted(names, key=natural_sort_key) if sort else names

    def usable_names(self):
        """Spectra the denoiser can work on — KherveFitting's filter."""
        return sorted((nm for nm, cl in self.spectra.items()
                       if 'B.E.' in cl and 'Raw Data' in cl
                       and len(cl['Raw Data']) >= 4
                       and 'zzProfile' not in nm and not nm.startswith('zzBook')),
                      key=natural_sort_key)

    def get(self, name):
        return self.spectra.get(name)

    def __len__(self):
        return len(self.spectra)

    def is_empty(self):
        return not self.spectra

    # ── mutation ─────────────────────────────────────────────────────
    def unique_name(self, base):
        if base not in self.spectra:
            return base
        for i in range(1, 10000):
            cand = f"{base}{i}"
            if cand not in self.spectra:
                return cand
        return f"{base}{len(self.spectra)}"

    def next_sheet_name(self, source, method):
        """KherveFitting's naming: '<source>_<fft|wav|vmd>[n]'."""
        base = f"{source}_{SUFFIX.get(method, 'dn')}"
        return self.unique_name(base)

    def add(self, spectrum, replace=False):
        """Add a spectrum; returns the name it was stored under."""
        name = str(spectrum.get('Name') or 'Spectrum')
        if not replace:
            name = self.unique_name(name)
        spectrum['Name'] = name
        self.spectra[name] = spectrum
        self.dirty = True
        return name

    def remove(self, name):
        if self.spectra.pop(name, None) is not None:
            self.dirty = True
            return True
        return False

    def rename(self, old, new):
        new = str(new).strip()
        if not new or old not in self.spectra or (new != old and new in self.spectra):
            return False
        items = [(new if k == old else k, v) for k, v in self.spectra.items()]
        self.spectra = dict(items)
        self.spectra[new]['Name'] = new
        self.dirty = True
        return True

    def clear(self):
        self.spectra = {}
        self.path = None
        self.source = None
        self.dirty = False

    # ── snapshots (undo) ─────────────────────────────────────────────
    def snapshot(self):
        return copy.deepcopy(self.spectra)

    def restore(self, snap):
        self.spectra = copy.deepcopy(snap)
        self.dirty = True

    # ── .knoise file ─────────────────────────────────────────────────
    def to_dict(self):
        return {'format': FORMAT, 'version': FORMAT_VERSION,
                'source': self.source, 'spectra': list(self.spectra.values())}

    def save(self, path):
        data = self.to_dict()
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1)
        os.replace(tmp, path)
        self.path = path
        self.dirty = False

    @classmethod
    def load(cls, path):
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or data.get('format') != FORMAT:
            raise ValueError(f"{os.path.basename(path)} is not a KherveNoise file.")
        doc = cls()
        for sp in data.get('spectra', []):
            if isinstance(sp, dict) and 'B.E.' in sp and 'Raw Data' in sp:
                doc.spectra[str(sp.get('Name'))] = sp
        doc.source = data.get('source')
        doc.path = path
        doc.dirty = False
        return doc
