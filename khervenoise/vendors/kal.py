"""Kratos (.kal) — port of KherveFitting's ``Kal_Import.parse_kal_file`` and
``Kal_Import.build_kal_core_levels`` (with ``Vamas_Import``'s
``extract_transmission_data``, ``parse_casa_info_lines`` and
``CASA_INFO_FIELDS``).  The Raman .txt helpers of that module are not
ported.

Route reproduced: the in-memory **.kfit** route (``build_kal_core_levels``
→ ``ConfigFile.build_core_level_Data``), so values are *not* rounded:

* 'B.E.'           = 1486.67 - KE, KE = linspace(start, start+(n-1)*step, n);
* 'Raw Data'       = ordinate values / transmission (the plotted trace);
* 'Corrected Data' = the ordinate values;
* 'Transmission'   = the block's transmission table interpolated at KE.

KherveFitting interpolates with ``scipy.interpolate.interp1d(kind='linear',
bounds_error=False, fill_value='extrapolate')`` (scipy 1.13.0 pinned).
SciPy is not a KherveNoise dependency, so :func:`_interp1d_linear` repeats
that code path (mergesort of the table, ``searchsorted`` clipped to
[1, n-1], ``slope * (x - x_lo) + y_lo``) — the same arithmetic, including
the linear extrapolation outside the table, which ``numpy.interp`` would
clamp instead.

Names are ``normalize_sheet_name(name.replace(' ', ''))`` made unique with
1, 2… as ``build_kal_core_levels`` does.

Copyright (C) 2026 Gwilherm Kerherve
Licensed under the GNU General Public License v3.0 (see LICENSE).
"""

import numpy as np

from ..document import make_spectrum
from ..importers import ImportResult, normalize_sheet_name
from . import Format


# ---------------------------------------------------------------------------
# Vamas_Import helpers used by the Kratos reader
# ---------------------------------------------------------------------------
CASA_INFO_FIELDS = [
    'Casa Sample Name', 'Stage Position', 'Angle', 'FoV Position', 'Lens Mode',
    'Neutraliser', 'Charge Balance', 'Filament Current', 'Filament Bias',
    'Magnet Lens Trim Coil', 'Aperture', 'Iris Position'
]


def parse_casa_info_lines(comment_text):
    """Kratos/Casa informational fields from a 'Casa Info Follows' block,
    keyed by CASA_INFO_FIELDS (missing fields -> '')."""
    result = {k: '' for k in CASA_INFO_FIELDS}
    if not comment_text or 'Casa Info Follows' not in comment_text:
        return result

    tail = comment_text.split('Casa Info Follows', 1)[1]
    candidate_lines = [ln.strip() for ln in tail.split('\n') if ln.strip()][:15]

    # Sample Name: first non-numeric, non-structured line.
    for ln in candidate_lines:
        try:
            float(ln)
            continue
        except ValueError:
            pass
        if ln.lower().startswith(('xps', 'aes', 'uhv')):
            break
        if ':' in ln or '(' in ln or '=' in ln or ln.startswith('FoV') \
                or ln.startswith('Aperture') or ln.startswith('Iris'):
            break
        result['Casa Sample Name'] = ln
        break

    for ln in candidate_lines:
        if ln.startswith('(') and 'Angle' in ln:
            paren_end = ln.find(')')
            if paren_end != -1:
                result['Stage Position'] = ln[:paren_end + 1]
            if 'Angle:' in ln:
                result['Angle'] = ln.split('Angle:', 1)[1].strip()
        elif ln.startswith('FoV Position'):
            result['FoV Position'] = ln.split('FoV Position', 1)[1].strip()
        elif ln.startswith('Lens Mode'):
            result['Lens Mode'] = ln.split(':', 1)[1].strip() if ':' in ln else ''
        elif ln.startswith('Neutraliser'):
            result['Neutraliser'] = ln.split(':', 1)[1].strip() if ':' in ln else ''
        elif ln.startswith('Charge Balance'):
            for part in ln.split(':'):
                if '=' not in part:
                    continue
                key, val = part.split('=', 1)
                key, val = key.strip(), val.strip()
                if key in result:
                    result[key] = val
        elif ln.startswith('Aperture Description'):
            result['Aperture'] = ln.split(':', 1)[1].strip() if ':' in ln else ''
        elif ln.startswith('Iris Position Description'):
            result['Iris Position'] = ln.split(':', 1)[1].strip().rstrip('.') if ':' in ln else ''

    return result


def extract_transmission_data(block):
    """(ke_trans, trans_values) arrays of a .kal block, or (None, None)."""
    if 'Transmission Function Object (ke,t)' in block:
        trans_section = block.split('Transmission Function Object (ke,t)')[1].split('Dataset filename')[0]

        ke_line = trans_section.split('Transmission Function Kinetic Energy =')[1].split('\n')[0]
        ke_str = ke_line.strip().strip('{}').strip()
        ke_trans = np.array([float(x.strip()) for x in ke_str.split(',')])

        val_line = trans_section.split('Transmission Function Value          =')[1].split('\n')[0]
        val_str = val_line.strip().strip('{}').strip()
        trans_values = np.array([float(x.strip()) for x in val_str.split(',')])

        return ke_trans, trans_values
    return None, None


def _interp1d_linear(x, y, x_new):
    """scipy 1.13 ``interp1d(x, y, kind='linear', bounds_error=False,
    fill_value='extrapolate')(x_new)`` for 1-D float data."""
    x = np.array(x, dtype=float)
    y = np.array(y, dtype=float)
    ind = np.argsort(x, kind="mergesort")
    x = x[ind]
    y = y[ind]
    x_new = np.asarray(x_new, dtype=float)
    x_new_indices = np.searchsorted(x, x_new)
    x_new_indices = x_new_indices.clip(1, len(x) - 1).astype(int)
    lo = x_new_indices - 1
    hi = x_new_indices
    x_lo = x[lo]
    x_hi = x[hi]
    y_lo = y[lo]
    y_hi = y[hi]
    slope = (y_hi - y_lo) / (x_hi - x_lo)
    return slope * (x_new - x_lo) + y_lo


# ---------------------------------------------------------------------------
# Kal_Import
# ---------------------------------------------------------------------------
KAL_FIELDS = [
    'Sample ID', 'Date', 'Time', 'Technique', 'Species & Transition',
    'Number of scans', 'Source Label', 'Source Energy', 'Source width X',
    'Source width Y', 'Pass Energy', 'Work Function', 'Analyzer Mode',
    'Sputtering Energy', 'Sputter Time', 'Sample Tilt',
    'Take-off Polar Angle', 'Take-off Azimuth',
    'Target Bias', 'Analysis Width X', 'Analysis Width Y', 'X Label',
    'X Units', 'X Start', 'X Step', 'Num Y Values', 'Num Scans',
    'Collection Time', 'Time Correction', 'Y Unit', '# Comment Lines',
    'Block Comment'
] + list(CASA_INFO_FIELDS)


def parse_kal_file(file_path, dismissed=None):
    """One dict per spectrum: 'sample_id', 'name', 'id', 'metadata' and
    'data' (a dict of BE / Corrected Data / Raw Data / Transmission arrays —
    a DataFrame in KherveFitting).  Spectra KherveFitting drops silently
    (no transmission function) are appended to *dismissed* when given."""
    with open(file_path, 'r') as f:
        content = f.read()

    blocks = content.split('Dataset filename')
    spectra = []  # list of dicts, preserves duplicates across sample positions
    PHOTON_ENERGY = 1486.67

    # Kratos only records these once per sample position, not per region.
    current_sample_id = "Unknown"
    current_sample_tilt = ''

    for block in blocks:
        for line in block.split('\n'):
            if 'Stage Position Name' in line:
                current_sample_id = line.split('=')[1].strip()
            elif 'Stage X Rotation' in line:
                current_sample_tilt = line.split('=')[1].strip()

        if 'Ordinate values' not in block or 'Object name' not in block:
            continue

        object_name_line = next((line for line in block.split('\n') if 'Object name' in line), None)
        if not object_name_line:
            continue

        name_parts = object_name_line.split('=')[1].strip().split('/')
        name = name_parts[0].strip()
        spectrum_id = name_parts[1].strip() if len(name_parts) > 1 else ""

        # Skip non-spectrum blocks
        if 'Sample Position' in name or 'Counter' in name:
            continue

        metadata = {
            'Sample ID': current_sample_id,
            'Date': '',
            'Time': '',
            'Technique': 'XPS',
            'Species & Transition': '',
            'Number of scans': '',
            'Source Label': 'Al mono',
            'Source Energy': '1486.6',
            'Source width X': '1E+37',
            'Source width Y': '1E+37',
            'Pass Energy': '',
            'Work Function': '1E+37',
            'Analyzer Mode': 'FAT',
            'Sputtering Energy': 'N/A',
            'Sputter Time': '',
            'Sample Tilt': current_sample_tilt,
            'Take-off Polar Angle': '1E+37',
            'Take-off Azimuth': '1E+37',
            'Target Bias': '1E+37',
            'Analysis Width X': '1E+37',
            'Analysis Width Y': '1E+37',
            'X Label': '',
            'X Units': '',
            'X Start': '',
            'X Step': '',
            'Num Y Values': '',
            'Num Scans': '',
            'Collection Time': '',
            'Time Correction': '1E+37',
            'Y Unit': 'd',
            '# Comment Lines': '0',
            'Block Comment': ''
        }

        for line in block.split('\n'):
            line = line.strip()

            if 'Date Acquired' in line:
                parts = line.split('=')[1].strip().split()
                if len(parts) >= 2:
                    metadata['Date'] = parts[0]
                    metadata['Time'] = parts[1]
            elif 'Chemical symbol or formula' in line:
                metadata['species'] = line.split('=')[1].strip()
            elif 'Transition or charge state' in line:
                metadata['transition'] = line.split('=')[1].strip()
            elif '# Sweeps completed' in line:
                num_scans = line.split('=')[1].strip()
                metadata['Number of scans'] = num_scans
                metadata['Num Scans'] = num_scans
            elif 'Pass energy' in line:
                metadata['Pass Energy'] = line.split('=')[1].strip()
            elif 'Abscissa label' in line:
                metadata['X Label'] = line.split('=')[1].strip()
            elif 'Abscissa units' in line:
                metadata['X Units'] = line.split('=')[1].strip()
            elif 'Spectrum scan start' in line:
                metadata['X Start'] = line.split('=')[1].split('eV')[0].strip()
            elif 'Spectrum scan step size' in line:
                metadata['X Step'] = line.split('=')[1].split('eV')[0].strip()
            elif 'Dwell time' in line:
                metadata['Collection Time'] = line.split('=')[1].replace('seconds', '').strip()

        if 'species' in metadata and 'transition' in metadata:
            metadata['Species & Transition'] = f"{metadata['species']} {metadata['transition']}"
            metadata.pop('species')
            metadata.pop('transition')

        if 'Ordinate values' in block:
            try:
                values_str = block.split('Ordinate values')[1].split('=')[1].split('}')[0].strip().strip('{').strip()
                values = values_str.split(',')
                metadata['Num Y Values'] = str(len(values))
            except Exception:  # noqa: BLE001
                pass

        comment_lines = []
        in_comment = False
        for line in block.split('\n'):
            if 'Casa Info Follows' in line:
                in_comment = True
                comment_lines.append(line.strip())
            elif in_comment and line.strip():
                comment_lines.append(line.strip())

        if comment_lines:
            metadata['# Comment Lines'] = str(len(comment_lines))
            metadata['Block Comment'] = '"' + '\n'.join(comment_lines) + '"'

        casa_info = parse_casa_info_lines('\n'.join(comment_lines))
        for k, v in casa_info.items():
            metadata[k] = v

        ke_trans, trans_values = extract_transmission_data(block)
        if ke_trans is not None and trans_values is not None:
            start_ke = float(metadata['X Start'])
            step = float(metadata['X Step'])
            raw_str = block.split('Ordinate values')[1].split('=')[1].split('}')[0].strip().strip('{').strip()
            raw_data = np.array([float(x.strip()) for x in raw_str.split(',')])

            num_points = len(raw_data)
            ke_values = np.linspace(start_ke, start_ke + (num_points - 1) * step, num_points)
            be_values = PHOTON_ENERGY - ke_values

            transmission = _interp1d_linear(ke_trans, trans_values, ke_values)
            corrected_data = raw_data / transmission

            spectra.append({
                'sample_id': current_sample_id,
                'name': name,
                'data': {
                    'BE': be_values,
                    'Corrected Data': corrected_data,
                    'Raw Data': raw_data,
                    'Transmission': transmission,
                },
                'metadata': metadata,
                'id': spectrum_id,
            })
        elif dismissed is not None:
            dismissed.append((name, "no transmission function"))

    return spectra


def read_kal(path):
    """Spectra of a Kratos .kal file, as build_kal_core_levels builds them."""
    result = ImportResult(source=path)
    spectra = parse_kal_file(path, result.dismissed)
    if not spectra:
        raise ValueError("No spectra found in this Kratos file.")
    taken = set()
    for info in spectra:
        base = normalize_sheet_name(info['name'].replace(' ', ''))
        sheet_name = base
        if sheet_name in taken:
            count = 1
            while f"{base}{count}" in taken:
                count += 1
            sheet_name = f"{base}{count}"
        taken.add(sheet_name)

        df = info['data']
        metadata = info['metadata']
        result.spectra.append(make_spectrum(
            sheet_name, df['BE'], df['Corrected Data'],
            raw=df['Raw Data'], transmission=df['Transmission'],
            info={f: metadata.get(f, '') for f in KAL_FIELDS}))
    return result


FORMATS = [
    Format(key="kal", label="Data file (.kal)", group="Kratos",
           extensions=(".kal",), reader=read_kal),
]
