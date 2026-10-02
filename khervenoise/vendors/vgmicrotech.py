"""VG-Microtech (.1) files — port of KherveFitting's VGMicrotech_Import.

Reproduces ``open_vg_microtech_file`` (File > Import > VG-Microtech >
"File (.1)", and drag and drop):

* line 2 is the header ``BE-start BE-end step ? dwell points pass-energy
  photon-energy``, line 3 the measurement type, then one intensity per
  line (non-numeric lines skipped, extra values beyond the point count
  dropped);
* the binding energy is ``numpy.linspace(BE start, BE end, points)``;
* the spectrum is named ``normalize_sheet_name(measurement type)``.

**Workbook route**: KherveFitting writes the sheet and reads it back with
``ConfigFile.add_core_level_Data``, so BE and counts are kept to 2
decimals (``_r2``); a file with fewer values than points is cut to the
values present (the sheet writer's ``zip``).  The "Experimental
description" sheet KherveFitting writes beside it is kept as the
spectrum's info.

Copyright (C) 2026 Gwilherm Kerherve
Licensed under the GNU General Public License v3.0 (see LICENSE).
"""

import os

import numpy as np

from ..document import make_spectrum
from ..importers import ImportResult, _r2, normalize_sheet_name
from . import Format


def read_vg_microtech(path):
    """One spectrum per .1 file, as KherveFitting's open_vg_microtech_file."""
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()

    header = lines[1].strip().split()
    be_start = float(header[0])
    be_end = float(header[1])
    energy_step = float(header[2])
    _unknown_param = float(header[3])
    dwell_time = float(header[4])
    num_points = int(header[5])
    pass_energy = float(header[6])
    photon_energy = abs(float(header[7]))  # absolute value for negative photon energies

    measurement_type = lines[2].strip()

    intensity_values = []
    for i in range(3, len(lines)):
        if lines[i].strip():
            try:
                intensity_values.append(float(lines[i].strip()))
            except ValueError:
                continue

    if len(intensity_values) > num_points:
        intensity_values = intensity_values[:num_points]

    be_values = np.linspace(be_start, be_end, num_points)
    sheet_name = normalize_sheet_name(measurement_type)

    result = ImportResult(source=path)
    pairs = list(zip(be_values, intensity_values))
    if not pairs:
        result.dismissed.append((sheet_name, "no data"))
        return result

    info = {
        "Sample ID": os.path.basename(path),
        "BE Start": str(be_start),
        "BE End": str(be_end),
        "Energy Step": str(energy_step),
        "Dwell Time": str(dwell_time),
        "Number of Points": str(num_points),
        "Pass Energy": str(pass_energy),
        "Photon Energy": str(photon_energy),
        "Technique": "XPS",
        "Species & Transition": measurement_type,
    }
    result.spectra.append(make_spectrum(sheet_name,
                                        [_r2(be) for be, _y in pairs],
                                        [_r2(y) for _be, y in pairs],
                                        info=info))
    return result


FORMATS = [
    Format(key="vgmicrotech", label="File (.1)", group="VG-Microtech",
           extensions=(".1",), reader=read_vg_microtech),
]
