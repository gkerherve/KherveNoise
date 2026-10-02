"""Thermo / VG Scienta AVG text exports (.avg, VGD DataSpace as ASCII).

Reproduces KherveFitting's ``AVG_Import``: ``parse_avg_file``,
``calculate_avg_data``, ``extract_core_level_name`` and the metadata block
of ``_write_sheet``, with the sheet naming of ``open_avg_file``
(``Ti2p``, ``Ti2p1``, ``Ti2p2`` ... one per spectrum of the second axis).

Route reproduced: the **workbook route** (the only one AVG has).
``_write_sheet`` writes ``BE | Corrected Data | Raw Data | Transmission``
rounded with ``round(v, 2)``; ``_load_into_kherve`` reads it back with
``ConfigFile.add_core_level_Data`` (``.2f``) and ``Save.refresh_sheets``
then renames the sheets with its normaliser (``"XPS Survey"`` ->
``Survey``) and reloads columns A / B.  So every column here is kept to 2
decimals (``_r2``): ``'B.E.'`` = source energy - KE, ``'Raw Data'`` =
counts / (acquisition time x periods), ``'Corrected Data'`` = the raw
counts, ``'Transmission'`` = acquisition time x periods (1 and the raw
counts when either is missing).

Deviation: a spectrum index with no data block at all (KherveFitting
writes an all-zero sheet for it) is listed in ``dismissed`` instead.

Copyright (C) 2026 Gwilherm Kerherve
Licensed under the GNU General Public License v3.0 (see LICENSE).
"""

import os
import re

from . import Format
from .avantage import refresh_sheet_names
from ..document import make_spectrum
from ..importers import ImportResult, _r2


def extract_core_level_name(filename):
    """'Ti2p Snap.avg' -> 'Ti2p', 'O1s_Scan.avg' -> 'O1s'."""
    base_name = os.path.splitext(filename)[0]
    suffixes_to_remove = [
        '_Snap', '_snap', '_SNAP',
        ' Snap', ' snap', ' SNAP',
        '_Scan', '_scan', '_SCAN',
        ' Scan', ' scan', ' SCAN',
        '_Region', '_region', '_REGION',
        ' Region', ' region', ' REGION',
        '_core level', '_Core Level', '_Core level',
        ' core level', ' Core Level', ' Core level',
        '_spectrum', '_Spectrum', ' spectrum', ' Spectrum',
    ]
    result = base_name
    for suffix in suffixes_to_remove:
        if result.endswith(suffix):
            result = result[:-len(suffix)]
            break
    match = re.match(r'^([A-Z][a-z]?\d+[spdfgh]\d*)[\s_]', result + ' ')
    if match:
        result = match.group(1)
    return result.strip()


def _get_bstr(line):
    m = re.search(r"VT_BSTR\s*=\s*'([^']*)'", line)
    return m.group(1) if m else ''


def _get_r4(line):
    m = re.search(r'VT_R4\s*=\s*([\d.eE+\-]+)', line)
    return float(m.group(1)) if m else None


def _get_i4(line):
    m = re.search(r'VT_I4\s*=\s*(\d+)', line)
    return int(m.group(1)) if m else None


def _get_date(line):
    m = re.search(r'VT_DATE\s*=\s*(.+)', line)
    return m.group(1).strip() if m else ''


def parse_avg_file(file_path):
    """KherveFitting's ``parse_avg_file``, verbatim."""
    with open(file_path, 'r', encoding='latin-1') as fh:
        lines = fh.readlines()

    metadata = {
        'title': '', 'subject': '', 'author': '', 'created': '', 'saved': '',
        'instrument': '', 'source_energy': 1486.68, 'pass_energy': None,
        'work_function': None, 'acq_time': None, 'periods': None,
        'txf_coeffs': [], 'lens_mode': '',
    }
    energy_axis = {'ke_start': None, 'ke_step': None, 'num_points': None}
    second_axis = None
    spectra = []
    current_spectrum = []
    in_data_block = False
    num_spectra_expected = 1
    txf_coeff_list = []

    for line in lines:
        line_s = line.rstrip()

        if 'DS_EXT_SUPROPID_TITLE' in line_s:
            metadata['title'] = _get_bstr(line_s)
        elif 'DS_EXT_SUPROPID_SUBJECT' in line_s:
            metadata['subject'] = _get_bstr(line_s)
        elif 'DS_EXT_SUPROPID_AUTHOR' in line_s:
            metadata['author'] = _get_bstr(line_s)
        elif 'DS_EXT_SUPROPID_CREATED' in line_s:
            metadata['created'] = _get_date(line_s)
        elif 'DS_EXT_SUPROPID_SAVED' in line_s:
            metadata['saved'] = _get_date(line_s)
        elif 'DS_GEPROPID_INSTRUMENT' in line_s:
            metadata['instrument'] = _get_bstr(line_s)
        elif 'DS_SOPROPID_ENERGY' in line_s:
            v = _get_r4(line_s)
            if v is not None:
                metadata['source_energy'] = v
        elif 'DS_ANPROPID_PASS' in line_s:
            v = _get_r4(line_s)
            if v is not None:
                metadata['pass_energy'] = v
        elif 'DS_ANPROPID_WORK_FTN' in line_s:
            v = _get_r4(line_s)
            if v is not None:
                metadata['work_function'] = v
        elif 'DS_ACPROPID_ACQ_TIME' in line_s:
            v = _get_r4(line_s)
            if v is not None:
                metadata['acq_time'] = v
        elif 'DS_ACPROPID_PERIODS' in line_s:
            v = _get_i4(line_s)
            if v is not None:
                metadata['periods'] = v
        elif 'DS_ANPROPID_LENS_MODE_NAME' in line_s:
            metadata['lens_mode'] = _get_bstr(line_s)
        elif 'DS_ANPROPID_TXFN_COEFF[' in line_s:
            v = _get_r4(line_s)
            if v is not None:
                txf_coeff_list.append(v)

        elif line_s.strip().startswith('$DATAAXES='):
            pass
        elif line_s.strip().startswith('$SPACEAXES='):
            pass

        # N=   start,  width,  numPoints,  axisType,  linear,  symbol,  unit,  label
        elif re.match(r'\s+\d+=\s+[\d.\-]+,', line_s):
            m = re.match(
                r'\s+(\d+)=\s+([\d.\-]+),\s+([\d.\-]+),\s+(\d+),\s+'
                r'(\w+),\s+\w+,\s+\'([^\']*)\',\s+\'([^\']*)\',\s+\'([^\']*)\'',
                line_s)
            if m:
                ax_start = float(m.group(2))
                ax_width = float(m.group(3))
                ax_num = int(m.group(4))
                ax_type = m.group(5)
                ax_unit = m.group(7)
                ax_label = m.group(8)
                if ax_type == 'ENERGY':
                    energy_axis['ke_start'] = ax_start
                    energy_axis['ke_step'] = ax_width
                    energy_axis['num_points'] = ax_num
                else:
                    num_spectra_expected = ax_num
                    second_axis = {'label': ax_label, 'unit': ax_unit,
                                   'axis_type': ax_type, 'values': []}

        elif line_s.startswith('$AXISVALUE=') and second_axis is not None:
            vm = re.search(r'VALUE=([\d.\-]+)', line_s)
            sm = re.search(r'SPACEAXIS=(\d+)', line_s)
            if vm and sm and int(sm.group(1)) == 1:
                second_axis['values'].append(float(vm.group(1)))

        elif line_s.startswith('$DATA='):
            if current_spectrum:
                spectra.append(current_spectrum)
            current_spectrum = []
            in_data_block = True

        elif in_data_block and line_s.startswith('LIST@'):
            parts = line_s.split('=', 1)
            if len(parts) == 2:
                for v in re.findall(r'[\d.\-+eE]+', parts[1]):
                    try:
                        current_spectrum.append(float(v))
                    except ValueError:
                        pass

    if current_spectrum:
        spectra.append(current_spectrum)

    metadata['txf_coeffs'] = txf_coeff_list
    if second_axis is None:
        num_spectra_expected = max(1, len(spectra))

    return {
        'metadata': metadata,
        'energy_axis': energy_axis,
        'second_axis': second_axis,
        'spectra': spectra,
        'num_spectra': len(spectra) if spectra else num_spectra_expected,
    }


def calculate_avg_data(parsed, spectrum_index=0):
    """KherveFitting's ``calculate_avg_data``: BE axis and counts/(time x periods)."""
    ea = parsed['energy_axis']
    meta = parsed['metadata']
    ke_start = ea['ke_start']
    ke_step = ea['ke_step']
    num_points = ea['num_points']
    source_energy = meta['source_energy']

    raw_intensities = (parsed['spectra'][spectrum_index]
                       if spectrum_index < len(parsed['spectra']) else [])
    raw_intensities = list(raw_intensities[:num_points])
    while len(raw_intensities) < num_points:
        raw_intensities.append(0.0)

    ke_values = [ke_start + i * ke_step for i in range(num_points)]
    be_values = [source_energy - ke for ke in ke_values]
    be_start = be_values[0]
    be_end = be_values[-1]
    be_step = (be_end - be_start) / (num_points - 1) if num_points > 1 else 0.0

    acq_time = meta.get('acq_time')
    periods = meta.get('periods')
    if acq_time and periods and acq_time > 0 and periods > 0:
        factor = acq_time * periods
        corrected_data = [v / factor for v in raw_intensities]
        transmission_values = [factor] * num_points
        txf_valid = True
    else:
        corrected_data = list(raw_intensities)
        transmission_values = [1.0] * num_points
        txf_valid = False

    return {
        'be_values': be_values, 'ke_values': ke_values,
        'raw_intensities': raw_intensities, 'corrected_data': corrected_data,
        'transmission_values': transmission_values,
        'be_start': be_start, 'be_end': be_end, 'be_step': be_step,
        'txf_valid': txf_valid,
    }


def avg_sheet_metadata(core_level, calc_data, parsed, spectrum_index, base_name):
    """The 'Experimental Description' block ``_write_sheet`` writes."""
    meta = parsed['metadata']
    ea = parsed['energy_axis']
    source_energy = meta['source_energy']
    source_label = ("Al K-alpha Monochromated" if abs(source_energy - 1486.68) < 0.1
                    else f"X-ray {source_energy:.2f} eV")
    second_axis = parsed.get('second_axis')
    second_axis_label = ''
    second_axis_value = ''
    if second_axis and spectrum_index < len(second_axis['values']):
        second_axis_label = f"{second_axis['label']} ({second_axis['unit']})"
        second_axis_value = f"{second_axis['values'][spectrum_index]:.4f}"

    exp_metadata = {
        'Sample ID': meta['subject'] if meta['subject'] else base_name,
        'Title': meta['title'],
        'Author': meta['author'],
        'Date Created': meta['created'].split()[0] if meta['created'] else '',
        'Time Created': (meta['created'].split()[1]
                         if meta['created'] and len(meta['created'].split()) > 1 else ''),
        'Date Saved': meta['saved'].split()[0] if meta['saved'] else '',
        'Time Saved': (meta['saved'].split()[1]
                       if meta['saved'] and len(meta['saved'].split()) > 1 else ''),
        'Instrument': meta['instrument'],
        'Lens Mode': meta['lens_mode'],
        'Technique': 'XPS',
        'Species & Transition': core_level,
        'Spectrum Index': str(spectrum_index),
        'Total Spectra': str(parsed['num_spectra']),
        'Source Label': source_label,
        'Source Energy': f"{source_energy:.2f}",
        'Pass Energy': (f"{meta['pass_energy']:.2f}"
                        if meta['pass_energy'] is not None else 'Unknown'),
        'Work Function': (f"{meta['work_function']:.2f}"
                          if meta['work_function'] is not None else 'Unknown'),
        'Acq Time (s)': (f"{meta['acq_time']:.4f}"
                         if meta['acq_time'] is not None else 'Unknown'),
        'Periods': str(meta['periods']) if meta['periods'] is not None else 'Unknown',
        'Number of Points': str(ea['num_points']),
        'BE Start': f"{calc_data['be_start']:.2f}",
        'BE End': f"{calc_data['be_end']:.2f}",
        'BE Step': f"{abs(calc_data['be_step']):.4f}",
        'KE Start': f"{ea['ke_start']:.2f}" if ea['ke_start'] is not None else 'Unknown',
        'KE Step': f"{ea['ke_step']:.4f}" if ea['ke_step'] is not None else 'Unknown',
        'TXF Applied': 'Yes' if calc_data['txf_valid'] else 'No',
        'TXF Coefficients': (', '.join([f"{c:.6f}" for c in meta['txf_coeffs']])
                             if meta['txf_coeffs'] else 'N/A'),
    }
    if second_axis_label:
        exp_metadata[second_axis_label] = second_axis_value
    return exp_metadata


def read_avg(path):
    """Spectra of an AVG file, as KherveFitting ends up with them."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"The file {path} does not exist.")
    filename = os.path.basename(path)
    base_name = os.path.splitext(filename)[0]
    core_level = extract_core_level_name(filename)
    parsed = parse_avg_file(path)
    ea = parsed['energy_axis']
    if ea['ke_start'] is None or ea['ke_step'] is None or not ea['num_points']:
        raise ValueError(f"{filename}: no energy axis ($SPACEAXES ENERGY line) found.")

    num_spectra = parsed['num_spectra']
    names = [core_level if idx == 0 else f"{core_level}{idx}" for idx in range(num_spectra)]
    finals = refresh_sheet_names(names)

    result = ImportResult(source=path)
    for idx, name in enumerate(finals):
        if idx >= len(parsed['spectra']):
            result.dismissed.append((name, "no data block in the file"))
            continue
        calc = calculate_avg_data(parsed, idx)
        info = avg_sheet_metadata(core_level, calc, parsed, idx, base_name)
        result.spectra.append(make_spectrum(
            name,
            [_r2(v) for v in calc['be_values']],
            [_r2(v) for v in calc['corrected_data']],
            raw=[_r2(v) for v in calc['raw_intensities']],
            transmission=[_r2(v) for v in calc['transmission_values']],
            info=info))
    return result


FORMATS = [
    Format(key="avg", label="AVG file (.avg)", group="Thermo",
           extensions=('.avg',), reader=read_avg, priority=50),
]
