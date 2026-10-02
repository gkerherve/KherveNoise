"""Scienta Omicron (SES) exports — ports of KherveFitting's Scienta_Import.

Reproduces ``parse_scienta_file``, ``parse_region``, ``clean_region_name``,
``is_auger_line`` and ``parse_h5_scienta_file`` verbatim, then the
spectrum KherveFitting ends up with:

* **Plot file (.txt)** — ``import_scienta_file`` -> ``finalize_scienta_import``
  -> ``write_sheet_data`` -> ``ConfigFile.add_core_level_Data``.  This is the
  *workbook route*: BE / intensity written with ``round(v, 2)`` and read
  back with ``'.2f'`` (``_r2``), sheet named ``clean_region_name(region)``
  made unique with 1, 2, …, the Experimental Description block of
  ``write_sheet_data`` kept as the spectrum's info.
* **Map file (.txt)** and **HDF5 map (.h5)** — ``import_scienta_map`` /
  ``import_h5_scienta_file`` open ``ScientaMapPreviewWindow``, whose default
  action is "SUM && Import" (``on_sum_sweeps``): every sweep kept, averaged
  (sum / number of sweeps), region names taken from the proposed
  ``clean_region_name`` field, "Save Maps" unticked (its default), then the
  same ``finalize_scienta_import`` workbook route.  The 2D maps themselves
  (``XPS~Map`` sheets) are not imported — the denoiser only uses 1D
  spectra — so only the summed spectrum is.  Binning ("Bin && Import") is
  an interactive alternative and is not reproduced.

Every Scienta spectrum is on KherveFitting's binding-energy axis (the
importer never converts the SES energy scale), so no ``x_label`` is set.

Copyright (C) 2026 Gwilherm Kerherve
Licensed under the GNU General Public License v3.0 (see LICENSE).
"""

import math
import os
import re

import numpy as np

from ..document import make_spectrum
from ..importers import ImportResult, _r2
from . import Format


# ---------------------------------------------------------------------------
# Names (verbatim from KherveFitting)
# ---------------------------------------------------------------------------
def clean_region_name(region_name):
    """(clean_name, is_special) for a Scienta region name."""
    suffixes_to_remove = [
        '_fast2', '_fast', '_slow', '_quick', '_scan', '_Scan', '_SCAN',
        ' fast2', ' fast', ' slow', ' quick', ' scan', ' Scan', ' SCAN',
        '_region', '_Region', '_REGION', ' region', ' Region', ' REGION',
        '_spectrum', '_Spectrum', ' spectrum', ' Spectrum'
    ]

    name = region_name.strip()
    for suffix in suffixes_to_remove:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
            break

    name = name.strip()
    lower_name = name.lower()

    if any(x in lower_name for x in ['survey', 'wide scan', 'wide']):
        if 'survey' in lower_name:
            return 'Survey', True
        else:
            return 'Wide', True

    if any(x in lower_name for x in ['valence band', 'valence_band', 'valenceband', 'valence']):
        return 'VB', True

    if 'fermi' in lower_name:
        return 'Fermi', True

    auger_patterns = [
        r'([A-Z][a-z]?)\s*(KLL\d*)',
        r'([A-Z][a-z]?)\s*(LMM\d*)',
        r'([A-Z][a-z]?)\s*(MNN\d*)',
        r'([A-Z][a-z]?)\s*(MVV\d*)',
        r'([A-Z][a-z]?)\s*(MNV\d*)',
        r'([A-Z][a-z]?)\s*(NOO\d*)',
        r'([A-Z][a-z]?)\s*(KL\d+)',
        r'([A-Z][a-z]?)\s*(LM\d+)',
        r'([A-Z][a-z]?)\s*(MN\d+)',
    ]

    for pattern in auger_patterns:
        match = re.match(pattern, name, re.IGNORECASE)
        if match:
            element = match.group(1)
            auger_type = match.group(2).upper()
            return f"{element}{auger_type}", True

    core_level_patterns = [
        r'^([A-Z][a-z]?)\s+(\d+[spdfgh])(\d*)$',
        r'^([A-Z][a-z]?)_(\d+[spdfgh])(\d*)$',
        r'^([A-Z][a-z]?)\s+(\d+[spdfgh])\s+(\d+)$',
        r'^([A-Z][a-z]?)_(\d+[spdfgh])_(\d+)$',
    ]

    for pattern in core_level_patterns:
        match = re.match(pattern, name)
        if match:
            element = match.group(1)
            orbital = match.group(2)
            return f"{element}{orbital}", False

    standard_pattern = r'^([A-Z][a-z]?\d+[spdfgh])(\d*)$'
    match = re.match(standard_pattern, name)
    if match:
        core_level = match.group(1)
        return core_level, False

    base_match = re.match(r'^(.+?)(\d*)$', name)
    if base_match and base_match.group(1):
        return base_match.group(1).strip(), False

    return name, False


def is_auger_line(name):
    """Check if a region name is an Auger line."""
    lower_name = name.lower()

    if any(lower_name.endswith(x) for x in ['kll', 'mnn', 'mvv', 'mnv', 'lmm', 'noo']):
        return True

    auger_patterns = [
        r'kll\d*', r'kl\d+', r'lmm\d*', r'lm\d+',
        r'mnn\d*', r'mn\d+', r'mvv\d*', r'mv\d+',
        r'mnv\d*', r'noo\d*', r'no\d+'
    ]

    for pattern in auger_patterns:
        if re.search(pattern, lower_name):
            return True

    return False


# ---------------------------------------------------------------------------
# .txt parsing (verbatim)
# ---------------------------------------------------------------------------
def parse_scienta_file(file_path):
    """Parse a Scienta .txt file: all regions with their data and metadata."""
    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()

    lines = content.split('\n')

    result = {
        'num_regions': 0,
        'version': '',
        'regions': [],
        'file_path': file_path,
        'is_map': False
    }

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line == '[Info]':
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('['):
                info_line = lines[i].strip()
                if info_line.startswith('Number of Regions='):
                    result['num_regions'] = int(info_line.split('=')[1])
                elif info_line.startswith('Version='):
                    result['version'] = info_line.split('=')[1]
                i += 1
            break
        i += 1

    for region_num in range(1, result['num_regions'] + 1):
        region_data = parse_region(lines, region_num)
        if region_data:
            result['regions'].append(region_data)
            if region_data.get('sweeps', 1) > 1 and region_data.get('data_2d') is not None:
                result['is_map'] = True

    return result


def parse_region(lines, region_num):
    """Parse a single region from the file."""
    region = {
        'name': '',
        'be_values': None,
        'sweeps': 1,
        'sweep_scale': None,
        'data_2d': None,
        'intensities': None,
        'metadata': {}
    }

    region_header = f'[Region {region_num}]'
    info_header = f'[Info {region_num}]'
    data_header = f'[Data {region_num}]'

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if line == region_header:
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('['):
                region_line = lines[i].strip()
                if region_line.startswith('Region Name='):
                    region['name'] = region_line.split('=')[1]
                elif region_line.startswith('Dimension 1 size='):
                    region['dim1_size'] = int(region_line.split('=')[1])
                elif region_line.startswith('Dimension 1 scale='):
                    scale_str = region_line.split('=')[1]
                    region['be_values'] = np.array([float(x) for x in scale_str.split()])
                elif region_line.startswith('Dimension 2 size='):
                    region['sweeps'] = int(region_line.split('=')[1])
                elif region_line.startswith('Dimension 2 scale='):
                    scale_str = region_line.split('=')[1]
                    region['sweep_scale'] = np.array([int(x) for x in scale_str.split()])
                i += 1

        elif line == info_header:
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('['):
                info_line = lines[i].strip()
                if '=' in info_line:
                    key, value = info_line.split('=', 1)
                    region['metadata'][key] = value
                i += 1

        elif line == data_header:
            i += 1
            data_rows = []
            while i < len(lines) and not lines[i].strip().startswith('[') and lines[i].strip():
                data_line = lines[i].strip()
                if data_line:
                    values = [float(x) for x in data_line.split()]
                    data_rows.append(values)
                i += 1

            if data_rows:
                data_array = np.array(data_rows)
                if data_array.shape[1] == 2:
                    region['be_values'] = data_array[:, 0]
                    region['intensities'] = data_array[:, 1]
                    region['sweeps'] = 1
                else:
                    if region['be_values'] is None:
                        region['be_values'] = data_array[:, 0]
                    region['data_2d'] = data_array[:, 1:].T
        else:
            i += 1

    return region if (region['data_2d'] is not None or region['intensities'] is not None) else None


# ---------------------------------------------------------------------------
# HDF5 parsing (verbatim; h5py imported lazily)
# ---------------------------------------------------------------------------
def parse_h5_scienta_file(file_path):
    """Parse a Scienta Omicron HDF5 (.h5) map file (see KherveFitting)."""
    try:
        import h5py
    except ImportError as exc:
        raise ImportError("h5py is required to import HDF5 files.\n"
                          "Install it with:  pip install h5py") from exc

    with h5py.File(file_path, 'r') as f:

        def _str(ds):
            v = ds[()]
            if isinstance(v, bytes):
                return v.decode('utf-8', errors='replace')
            return str(v)

        def _float(ds):
            return float(ds[()])

        sd = f['acquisition/spectrum_definition']
        acq_mode = _str(sd['acquisition_mode'])
        energy_mode = _str(sd['energy_mode'])
        lens_mode = _str(sd['lens_mode_name'])
        pass_energy = _float(sd['pass_energy'])
        dwell_time = _float(sd['dwell_time'])
        acq_time = _float(sd['acquisition_time'])
        element_set = _str(sd['element_set_name'])

        sl = f['acquisition/spectrum_log']
        start_time = _str(sl['start_time'])
        stop_time = _str(sl['stop_time'])

        sp = f['acquisition/spectrum']
        name = _str(sp['name'])

        src = f['instrument/analyser/excitation_source']
        source_energy = _float(src['energy'])

        analyser = f['instrument/analyser']
        work_function = _float(analyser['work_function'])
        instrument_model = _str(analyser['model'])

        data_grp = f['acquisition/spectrum/data']
        data_2d_raw = data_grp['data'][()]
        x_axis_raw = data_grp['x_axis'][()]
        y_axis = data_grp['y_axis'][()]
        y_label = data_grp['y_axis'].attrs.get('label', b'Y').decode() \
            if isinstance(data_grp['y_axis'].attrs.get('label', b'Y'), bytes) \
            else str(data_grp['y_axis'].attrs.get('label', 'Y'))
        y_unit = data_grp['y_axis'].attrs.get('units', b'').decode() \
            if isinstance(data_grp['y_axis'].attrs.get('units', b''), bytes) \
            else str(data_grp['y_axis'].attrs.get('units', ''))

        red_grp = f['acquisition/spectrum/data_reduced_1d']
        data_1d_raw = red_grp['data'][()]

    ke_values = np.array(x_axis_raw, dtype=float)
    be_values = source_energy - ke_values

    if be_values[0] < be_values[-1]:
        be_values = be_values[::-1]
        ke_values = ke_values[::-1]
        data_2d_raw = data_2d_raw[:, ::-1]
        data_1d_raw = data_1d_raw[::-1]

    return {
        'file_path': file_path,
        'name': name,
        'element_set': element_set,
        'source_energy': round(source_energy, 4),
        'pass_energy': round(pass_energy, 2),
        'work_function': round(work_function, 4),
        'lens_mode': lens_mode,
        'acq_mode': acq_mode,
        'energy_mode': energy_mode,
        'dwell_time': dwell_time,
        'acq_time': acq_time,
        'start_time': start_time,
        'stop_time': stop_time,
        'instrument_model': instrument_model,
        'be_values': be_values,
        'ke_values': ke_values,
        'y_axis': y_axis,
        'y_label': y_label,
        'y_unit': y_unit,
        'data_2d': np.array(data_2d_raw, dtype=float),
        'data_1d': np.array(data_1d_raw, dtype=float),
        'is_map': True,
    }


def _h5_parsed_data(file_path):
    """import_h5_scienta_file: the one-region 'parsed_data' it hands the
    preview window."""
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    h5data = parse_h5_scienta_file(file_path)
    n_y = h5data['data_2d'].shape[0]

    core_level, _ = clean_region_name(h5data['element_set'])
    if not core_level:
        core_level = base_name

    source_label = (
        'He I (UPS)' if abs(h5data['source_energy'] - 21.218) < 0.05 else
        'He II (UPS)' if abs(h5data['source_energy'] - 40.814) < 0.05 else
        'Al K-alpha' if abs(h5data['source_energy'] - 1486.68) < 0.1 else
        'Mg K-alpha' if abs(h5data['source_energy'] - 1253.6) < 0.1 else
        f"Photon {h5data['source_energy']:.3f} eV"
    )
    metadata = {
        'Sample': h5data['element_set'],
        'Spectrum Name': h5data['name'],
        'Instrument': h5data['instrument_model'],
        'Location': '',
        'User': '',
        'Date': h5data['start_time'][:10] if h5data['start_time'] else '',
        'Time': h5data['start_time'][11:] if len(h5data['start_time']) > 10 else '',
        'Technique': 'UPS' if h5data['source_energy'] < 100 else 'XPS',
        'Excitation Energy': f"{h5data['source_energy']:.3f}",
        'Source Label': source_label,
        'Pass Energy': f"{h5data['pass_energy']:.2f}",
        'Work Function': f"{h5data['work_function']:.4f}",
        'Lens Mode': h5data['lens_mode'],
        'Acquisition Mode': h5data['acq_mode'],
        'Energy Mode': h5data['energy_mode'],
        'Energy Scale': 'Binding',
        'Energy Step': f"{abs(float(h5data['be_values'][1]) - float(h5data['be_values'][0])):.4f}",
        'Step Time': f"{h5data['dwell_time']:.4f}",
        'Start Time': h5data['start_time'],
        'Stop Time': h5data['stop_time'],
        'Y Axis Label': h5data['y_label'],
        'Y Axis Unit': h5data['y_unit'],
        'Y Axis Start': f"{h5data['y_axis'][0]:.4f}",
        'Y Axis End': f"{h5data['y_axis'][-1]:.4f}",
        'Y Axis Points': str(n_y),
    }
    region = {
        'name': core_level,
        'be_values': h5data['be_values'],
        'sweeps': n_y,
        'sweep_scale': np.arange(n_y),
        'data_2d': h5data['data_2d'],
        'intensities': None,
        'metadata': metadata,
        'dropped_sweeps': [],
    }
    return {'num_regions': 1, 'version': 'HDF5', 'regions': [region],
            'file_path': file_path, 'is_map': True}


# ---------------------------------------------------------------------------
# The import pipeline
# ---------------------------------------------------------------------------
def _plot_import_data(parsed):
    """import_scienta_file: single-sweep regions passed straight through."""
    regions = []
    for region in parsed['regions']:
        regions.append({
            'name': region['name'],
            'be_values': region['be_values'],
            'intensities': region['intensities'],
            'metadata': region['metadata'],
            'num_sweeps_summed': 1,
            'total_sweeps': 1,
            'dropped_sweeps': [],
            'data_2d': None,
        })
    return {'file_path': parsed['file_path'], 'regions': regions,
            'bin_mode': False, 'save_maps': False}


def _summed_import_data(parsed):
    """ScientaMapPreviewWindow.on_sum_sweeps with its defaults: the proposed
    names, no sweep dropped, 'Save Maps' unticked."""
    regions = [r.copy() for r in parsed['regions']]
    for i, region in enumerate(regions):
        if parsed['regions'][i].get('data_2d') is not None:
            region['data_2d'] = np.copy(parsed['regions'][i]['data_2d'])
        region['dropped_sweeps'] = []
        # init_ui's name field, applied by on_sum_sweeps
        proposed, _ = clean_region_name(region['name'])
        if not proposed:
            proposed = region['name']
        new_name = proposed.strip()
        if new_name:
            region['name'] = new_name

    out = []
    for region in regions:
        if region.get('data_2d') is None:
            out.append({
                'name': region['name'],
                'be_values': region['be_values'],
                'intensities': region['intensities'],
                'metadata': region['metadata'],
                'num_sweeps_summed': 1,
                'total_sweeps': 1,
                'dropped_sweeps': [],
                'data_2d': None,
            })
            continue
        dropped = set(region.get('dropped_sweeps', []))
        valid_indices = [i for i in range(region['sweeps']) if i not in dropped]
        if not valid_indices:
            raise ValueError(f"Region '{region['name']}' has all sweeps dropped!")
        valid_data = region['data_2d'][valid_indices, :]
        summed_intensities = np.sum(valid_data, axis=0) / len(valid_indices)
        out.append({
            'name': region['name'],
            'be_values': region['be_values'],
            'intensities': summed_intensities,
            'metadata': region['metadata'],
            'num_sweeps_summed': len(valid_indices),
            'total_sweeps': region['sweeps'],
            'dropped_sweeps': list(dropped),
            'data_2d': region['data_2d'],
        })
    return {'file_path': parsed['file_path'], 'regions': out,
            'bin_mode': False, 'save_maps': False}


def _sheet_info(region, sheet_name):
    """write_sheet_data's Experimental Description block."""
    be_values = region['be_values']
    metadata = region['metadata']
    exp_metadata = {
        'Sample ID': metadata.get('Sample', ''),
        'Spectrum Name': metadata.get('Spectrum Name', ''),
        'Region Name': region['name'],
        'Instrument': metadata.get('Instrument', ''),
        'Location': metadata.get('Location', ''),
        'User': metadata.get('User', ''),
        'Date': metadata.get('Date', ''),
        'Time': metadata.get('Time', ''),
        'Technique': 'XPS',
        'Species & Transition': sheet_name,
        'Excitation Energy': metadata.get('Excitation Energy', ''),
        'Pass Energy': metadata.get('Pass Energy', ''),
        'Energy Scale': metadata.get('Energy Scale', ''),
        'Lens Mode': metadata.get('Lens Mode', ''),
        'Acquisition Mode': metadata.get('Acquisition Mode', ''),
        'Energy Step': metadata.get('Energy Step', ''),
        'Step Time': metadata.get('Step Time', ''),
        'Number of Points': str(len(be_values)),
        'BE Start': f"{be_values[0]:.2f}",
        'BE End': f"{be_values[-1]:.2f}",
    }
    if 'total_sweeps' in region:
        exp_metadata['Total Sweeps in File'] = str(region.get('total_sweeps', 1))
    if 'num_sweeps_summed' in region:
        exp_metadata['Sweeps Summed'] = str(region.get('num_sweeps_summed', 1))
    if 'dropped_sweeps' in region and region['dropped_sweeps']:
        exp_metadata['Dropped Sweeps'] = ', '.join(map(str, region['dropped_sweeps']))
    return {k: str(v) for k, v in exp_metadata.items()}


def _finalize(import_data):
    """finalize_scienta_import (summed, no maps) + add_core_level_Data."""
    result = ImportResult(source=import_data['file_path'])
    sheet_names = []
    for region in import_data['regions']:
        sheet_base, _is_special = clean_region_name(region['name'])
        sheet_name = sheet_base
        counter = 1
        while sheet_name in sheet_names:
            sheet_name = f"{sheet_base}{counter}"
            counter += 1
        sheet_names.append(sheet_name)

        # write_sheet_data: round(v, 2) into the workbook, zip() to the
        # shorter column; add_core_level_Data: NaN rows skipped, '.2f'.
        xs, ys = [], []
        for be, intensity in zip(region['be_values'], region['intensities']):
            be, intensity = float(be), float(intensity)
            if math.isnan(be) or math.isnan(intensity):
                continue
            xs.append(_r2(be))
            ys.append(_r2(intensity))
        if not xs:
            result.dismissed.append((sheet_name, "no data"))
            continue
        result.spectra.append(make_spectrum(sheet_name, xs, ys,
                                            info=_sheet_info(region, sheet_name)))
    return result


def read_scienta_txt(path):
    """A Scienta SES .txt export: plot file as is, map file summed."""
    parsed = parse_scienta_file(path)
    if not parsed['regions']:
        raise ValueError(f"No Scienta region found in {os.path.basename(path)}.")
    if parsed['is_map']:
        return _finalize(_summed_import_data(parsed))
    return _finalize(_plot_import_data(parsed))


def read_scienta_h5(path):
    """A Scienta HDF5 map, summed over its Y positions."""
    return _finalize(_summed_import_data(_h5_parsed_data(path)))


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------
def _head(path, size=65536):
    with open(path, 'r', encoding='utf-8', errors='replace') as fh:
        return fh.read(size)


def _is_ses(text):
    """What parse_scienta_file keys on: an [Info] block giving the number of
    regions, then [Region 1] with its Dimension 1 axis."""
    lines = [ln.strip() for ln in text.split('\n')]
    return ('[Info]' in lines and any(ln.startswith('Number of Regions=') for ln in lines)
            and '[Region 1]' in lines
            and any(ln.startswith('Dimension 1 ') for ln in lines))


def _head_is_map(text):
    return any(int(m.group(1)) > 1
               for m in re.finditer(r'^\s*Dimension 2 size=(\d+)', text, re.M))


def sniff_plot(path):
    text = _head(path)
    return _is_ses(text) and not _head_is_map(text)


def sniff_map(path):
    text = _head(path)
    return _is_ses(text) and _head_is_map(text)


def sniff_h5(path):
    try:
        import h5py
    except ImportError:
        return False
    with h5py.File(path, 'r') as f:
        return ('acquisition/spectrum_definition' in f
                and 'acquisition/spectrum/data' in f
                and 'instrument/analyser' in f)


FORMATS = [
    Format(key="scienta_txt", label="Plot file (.txt)", group="Scienta Omicron",
           extensions=(".txt",), reader=read_scienta_txt, sniff=sniff_plot, priority=10),
    Format(key="scienta_map", label="Map file, summed (.txt)", group="Scienta Omicron",
           extensions=(".txt",), reader=read_scienta_txt, sniff=sniff_map, priority=10),
    Format(key="scienta_h5", label="HDF5 map, summed (.h5)", group="Scienta Omicron",
           extensions=(".h5", ".hdf5"), reader=read_scienta_h5, sniff=sniff_h5, priority=10),
]
