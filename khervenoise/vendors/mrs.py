"""MRS (.mrs) data files — port of KherveFitting's MRS_Import.

Reproduces ``get_core_level_from_filename`` and ``import_mrs_file`` (File >
Import > MRS > "Data file (.mrs)"; the drag-and-drop ``open_mrs_file`` reads
the same section and gives the same numbers).  One spectrum per file:

* the data section is found with the same three regular expressions
  (``data=Data Array``, then ``data=Auto Survey``, then any), the counts are
  the all-digit lines between the ``!`` markers, and the binding energy runs
  from ``up_be`` down to ``lo_be`` in equal steps;
* the spectrum is named by ``get_core_level_from_filename`` (``xxx_C.mrs``
  -> ``C1s``, ``xxx_SU.mrs`` -> ``Survey`` …) with ``import_mrs_file``'s
  extra ``_c1s`` / ``_su`` rule.

**Workbook route**: KherveFitting writes BE (unrounded) and counts to a
sheet and reads it back with ``ConfigFile.add_core_level_Data``, so both are
kept to 2 decimals (``_r2``).  The "Experimental description" sheet
KherveFitting writes beside it (file, energy range, points, description) is
kept as the spectrum's info.  ``extract_acquisition_parameters`` (an
Avantage-sheet helper that lives in the same KherveFitting module) is not
part of the MRS route and is not ported.

Copyright (C) 2026 Gwilherm Kerherve
Licensed under the GNU General Public License v3.0 (see LICENSE).
"""

import os
import re

from ..document import make_spectrum
from ..importers import ImportResult, _r2
from . import Format


_CORE_LEVEL_MAP = {
    'C': 'C1s',
    'N': 'N1s',
    'O': 'O1s',
    'F': 'F1s',
    'S': 'S2p',
    'CL': 'Cl2p',
    'BR': 'Br3d',
    'I': 'I3d',
    'SI': 'Si2p',
    'P': 'P2p',
    'B': 'B1s',
    'LI': 'Li1s',
    'NA': 'Na1s',
    'K': 'K2p',
    'CA': 'Ca2p',
    'MG': 'Mg2p',
    'AL': 'Al2p',
    'TI': 'Ti2p',
    'V': 'V2p',
    'CR': 'Cr2p',
    'MN': 'Mn2p',
    'FE': 'Fe2p',
    'CO': 'Co2p',
    'NI': 'Ni2p',
    'CU': 'Cu2p',
    'ZN': 'Zn2p',
    'GA': 'Ga3d',
    'GE': 'Ge3d',
    'AS': 'As3d',
    'SE': 'Se3d',
    'RB': 'Rb3d',
    'SR': 'Sr3d',
    'Y': 'Y3d',
    'ZR': 'Zr3d',
    'NB': 'Nb3d',
    'MO': 'Mo3d',
    'RU': 'Ru3d',
    'RH': 'Rh3d',
    'PD': 'Pd3d',
    'AG': 'Ag3d',
    'CD': 'Cd3d',
    'IN': 'In3d',
    'SN': 'Sn3d',
    'SB': 'Sb3d',
    'TE': 'Te3d',
    'CS': 'Cs3d',
    'BA': 'Ba3d',
    'LA': 'La3d',
    'CE': 'Ce3d',
    'HF': 'Hf4f',
    'TA': 'Ta4f',
    'W': 'W4f',
    'RE': 'Re4f',
    'OS': 'Os4f',
    'IR': 'Ir4f',
    'PT': 'Pt4f',
    'AU': 'Au4f',
    'HG': 'Hg4f',
    'PB': 'Pb4f',
    'BI': 'Bi4f',
    'TH': 'Th4f',
    'U': 'U4f',
    'SU': 'Survey',
    'VB': 'VB'  # Valence Band
}


def get_core_level_from_filename(filename):
    """xxx_C.MRS -> C1s, xxx_CL.MRS -> Cl2p, xxx_SU.MRS -> Survey …"""
    core_level_map = _CORE_LEVEL_MAP
    base_name = os.path.basename(filename)
    match = re.search(r'_([A-Z]+)\.mrs$', base_name.upper())

    if match:
        suffix = match.group(1)
        return core_level_map.get(suffix, suffix)
    base_name_without_ext = os.path.splitext(base_name)[0]
    for key, value in core_level_map.items():
        if key in base_name_without_ext.upper():
            return value

    return base_name_without_ext


def _sheet_name(file_path):
    """import_mrs_file's sheet name."""
    sheet_name = get_core_level_from_filename(file_path)
    if "_" in sheet_name:
        core_level = sheet_name.split("_")[1]
        if core_level.lower() in ["c1s", "o1s", "n1s", "s2p", "su", "vb"]:
            if core_level.lower() == "su":
                sheet_name = "Survey"
            else:
                sheet_name = core_level.upper()
    return sheet_name


def read_mrs(path):
    """One spectrum per .mrs file, as KherveFitting's import_mrs_file."""
    with open(path, 'r', errors='ignore') as f:
        content = f.read()

    result = ImportResult(source=path)
    desc_match = re.search(r'desc=(.*?)[\r\n]', content)
    sheet_name = _sheet_name(path)

    data_section_match = re.search(
        r'array_size=(\d+).*?data=Data Array.*?lo_be=([0-9.-]+).*?up_be=([0-9.-]+).*?!(.*?)!',
        content, re.DOTALL)
    if not data_section_match:
        data_section_match = re.search(
            r'array_size=(\d+).*?data=Auto Survey.*?lo_be=([0-9.-]+).*?up_be=([0-9.-]+).*?!(.*?)!',
            content, re.DOTALL)
    if not data_section_match:
        data_section_match = re.search(
            r'array_size=(\d+).*?lo_be=([0-9.-]+).*?up_be=([0-9.-]+).*?!(.*?)!',
            content, re.DOTALL)

    if not data_section_match:
        result.dismissed.append((sheet_name, "Could not locate data section in MRS file."))
        return result

    be_start = float(data_section_match.group(2))
    be_end = float(data_section_match.group(3))
    data_text = data_section_match.group(4).strip()

    data_values = []
    for line in data_text.split('\n'):
        line = line.strip()
        if line and line.isdigit():
            data_values.append(int(line))

    if not data_values:
        result.dismissed.append((sheet_name, "No valid data found in the MRS file."))
        return result

    num_points = len(data_values)
    step_size = (be_end - be_start) / (num_points - 1) if num_points > 1 else 0
    be_values = [be_end - i * step_size for i in range(num_points)]

    info = {
        "File": os.path.basename(path),
        "Energy Range": f"{be_start} - {be_end} eV",
        "Number of Points": str(num_points),
    }
    if desc_match:
        info["Description"] = desc_match.group(1).strip()

    result.spectra.append(make_spectrum(sheet_name,
                                        [_r2(v) for v in be_values],
                                        [_r2(v) for v in data_values],
                                        info=info))
    return result


FORMATS = [
    Format(key="mrs", label="Data file (.mrs)", group="MRS",
           extensions=(".mrs",), reader=read_mrs),
]
