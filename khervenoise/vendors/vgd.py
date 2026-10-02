"""Thermo Avantage / VG Scienta VGD binary files (.vgd, OLE2 compound file).

Reproduces KherveFitting's ``VGD_Import``: ``parse_vgd_file``,
``calculate_vgd_data``, ``extract_core_level_name``,
``vgd_spectrum_metadata``, ``build_vgd_average_metadata``,
``vgd_map_pixel_data``, ``_unique_name`` and the in-memory builders
``build_vgd_core_levels`` / ``build_vgd_spectrum_core_level`` /
``build_vgd_xy_map_core_levels`` (as called by ``import_vgd_file``).

Route reproduced: the **in-memory .kfit route** (``build_core_level_Data``),
so nothing is rounded: ``'B.E.'`` = source energy - KE, ``'Raw Data'`` =
counts / (periods x dwell time), ``'Corrected Data'`` = the raw counts,
``'Transmission'`` = periods x dwell time (1 and the raw counts when either
is unknown).  Names are KherveFitting's ``extract_core_level_name`` of the
file name (``"O1s Scan.VGD"`` -> ``O1s``, ``"XPS Survey.VGD"`` ->
``XPS Survey`` — the .kfit route does not run refresh_sheets' renaming),
made unique with 1, 2 ... for multi-spectrum files.

XY area scans: KherveFitting builds a ``<core>~Map`` (one Y column per
pixel, an image — not denoisable; listed in ``dismissed``) and a plain
``<core>`` spectrum, the average of all pixels, which is imported.

Needs ``olefile``.

Copyright (C) 2026 Gwilherm Kerherve
Licensed under the GNU General Public License v3.0 (see LICENSE).
"""

import os
import re
import struct

from . import Format
from ..document import make_spectrum
from ..importers import ImportResult


def extract_core_level_name(filename):
    """'O1s_Scan.VGD' -> 'O1s', 'Ni2p core level.VGD' -> 'Ni2p'."""
    base_name = os.path.splitext(filename)[0]
    suffixes_to_remove = [
        '_Scan', '_scan', '_SCAN',
        ' Scan', ' scan', ' SCAN',
        '_Region', '_region', '_REGION',
        ' Region', ' region', ' REGION',
        '_core level', '_Core Level', '_Core level',
        ' core level', ' Core Level', ' Core level',
        '_spectrum', '_Spectrum', ' spectrum', ' Spectrum'
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


def parse_vgd_file(file_path):
    """KherveFitting's ``parse_vgd_file``, verbatim (byte offsets included)."""
    try:
        import olefile
    except ImportError as exc:  # pragma: no cover
        raise ImportError("The 'olefile' package is required to read VGD files "
                          "(pip install olefile).") from exc

    ole = olefile.OleFileIO(file_path)
    try:
        metadata = ole.get_metadata()
        title = metadata.title.split('\x00')[0] if metadata.title else "Unknown"
        subject = metadata.subject.split('\x00')[0] if metadata.subject else ""
        author = metadata.author.split('\x00')[0] if metadata.author else ""
        create_time = str(metadata.create_time) if metadata.create_time else ""
        saved_time = str(metadata.last_saved_time) if metadata.last_saved_time else ""

        vgdata = ole.openstream('VGData').read()
        total_points = len(vgdata) // 8

        # VGDataAxes: off 4 = ndims, off 12 = dim1-1 (KE points),
        # off 28 = dim2-1 (spectra or X pixels), off 44 = dim3-1 (Y pixels)
        data_axes = ole.openstream('VGDataAxes').read()

        num_spectra = 1
        points_per_spectrum = total_points
        is_area_scan = False
        n_x = n_y = None
        n_ke = None

        if len(data_axes) >= 8:
            ndims = struct.unpack('<i', data_axes[4:8])[0]
            if ndims == 3 and len(data_axes) >= 56:
                n_ke = struct.unpack('<i', data_axes[12:16])[0] + 1
                n_x = struct.unpack('<i', data_axes[28:32])[0] + 1
                n_y = struct.unpack('<i', data_axes[44:48])[0] + 1
                if n_ke * n_x * n_y == total_points:
                    is_area_scan = True
                    points_per_spectrum = n_ke
                    num_spectra = n_x * n_y
            elif ndims <= 2 and len(data_axes) >= 32:
                dim1 = struct.unpack('<i', data_axes[12:16])[0] + 1
                dim2 = struct.unpack('<i', data_axes[28:32])[0] + 1
                if dim1 * dim2 == total_points and dim2 > 1:
                    num_spectra = dim2
                    points_per_spectrum = dim1

        all_intensities = []
        for i in range(total_points):
            all_intensities.append(struct.unpack('<d', vgdata[i * 8:i * 8 + 8])[0])

        if is_area_scan:
            import numpy as _np
            arr = _np.array(all_intensities).reshape(n_y, n_x, n_ke)
            intensities = [arr[y, x, :].tolist() for y in range(n_y) for x in range(n_x)]
        elif num_spectra > 1:
            intensities = []
            for s in range(num_spectra):
                start_idx = s * points_per_spectrum
                intensities.append(all_intensities[start_idx:start_idx + points_per_spectrum])
        else:
            intensities = all_intensities

        space_axes = ole.openstream('VGSpaceAxes').read()
        ke_start = struct.unpack('<d', space_axes[30:38])[0] if len(space_axes) >= 46 else None
        ke_step = struct.unpack('<d', space_axes[38:46])[0] if len(space_axes) >= 46 else None

        x_start = x_step = y_start = y_step = None
        if is_area_scan and len(space_axes) >= 132:
            x_start = struct.unpack('<d', space_axes[73:81])[0]
            x_step = struct.unpack('<d', space_axes[81:89])[0]
            y_start = struct.unpack('<d', space_axes[116:124])[0]
            y_step = struct.unpack('<d', space_axes[124:132])[0]

        prop_stream_name = '\x05Q5nw4m3lIjudbfwyAayojlptCa'
        prop_data = ole.openstream(prop_stream_name).read()
    finally:
        ole.close()

    source_energy = None
    for i in range(0, len(prop_data) - 4, 4):
        val = struct.unpack('<f', prop_data[i:i + 4])[0]
        if 1480 < val < 1490:
            source_energy = val
            break
    if source_energy is None:
        source_energy = 1486.68

    pass_energy = None
    pe_offset = None
    for i in range(0, len(prop_data) - 4, 4):
        val = struct.unpack('<f', prop_data[i:i + 4])[0]
        if val in [10.0, 20.0, 35.0, 50.0, 100.0, 160.0, 200.0]:
            pass_energy = val
            pe_offset = i
            break

    dwell_time = None
    if pe_offset is not None and pe_offset + 12 <= len(prop_data):
        dwell_time = struct.unpack('<f', prop_data[pe_offset + 8:pe_offset + 12])[0]
        if not (0.001 < dwell_time < 10.0):
            dwell_time = None

    periods = None
    if pe_offset is not None and pe_offset >= 32:
        periods = struct.unpack('<i', prop_data[pe_offset - 32:pe_offset - 28])[0]
        if not (1 <= periods <= 1000):
            periods = None

    work_fn = None
    if pe_offset is not None and pe_offset + 20 <= len(prop_data):
        work_fn = struct.unpack('<f', prop_data[pe_offset + 16:pe_offset + 20])[0]
        if not (3.0 < work_fn < 6.0):
            work_fn = None

    txf_coeffs = []
    for start in range(3100, min(3800, len(prop_data) - 32), 4):
        val = struct.unpack('<f', prop_data[start:start + 4])[0]
        if 4.0 < val < 4.5:
            vals = []
            valid = True
            for j in range(4):
                off = start + j * 8
                if off + 4 <= len(prop_data):
                    vals.append(struct.unpack('<f', prop_data[off:off + 4])[0])
                else:
                    valid = False
                    break
            if valid and len(vals) == 4 and 0.5 < vals[1] < 1.0:
                txf_coeffs = vals
                break

    return {
        'intensities': intensities,
        'ke_start': ke_start,
        'ke_step': ke_step,
        'num_points': points_per_spectrum,
        'total_points': total_points,
        'num_spectra': num_spectra,
        'is_area_scan': is_area_scan,
        'n_x': n_x,
        'n_y': n_y,
        'x_start': x_start,
        'x_step': x_step,
        'y_start': y_start,
        'y_step': y_step,
        'source_energy': source_energy,
        'txf_coeffs': txf_coeffs,
        'pass_energy': pass_energy,
        'work_fn': work_fn,
        'dwell_time': dwell_time,
        'periods': periods,
        'metadata': {
            'title': title,
            'subject': subject,
            'author': author,
            'create_time': create_time,
            'saved_time': saved_time,
        },
    }


def calculate_vgd_data(parsed_data, spectrum_index=0):
    """KherveFitting's ``calculate_vgd_data``: BE axis and counts/(periods x dwell)."""
    num_spectra = parsed_data.get('num_spectra', 1)
    if num_spectra > 1:
        intensities = parsed_data['intensities'][spectrum_index]
    else:
        intensities = parsed_data['intensities']

    ke_start = parsed_data['ke_start']
    ke_step = parsed_data['ke_step']
    num_points = parsed_data['num_points']
    source_energy = parsed_data['source_energy']

    ke_values = [ke_start + i * ke_step for i in range(num_points)]
    be_values = [source_energy - ke for ke in ke_values]
    be_start = be_values[0]
    be_end = be_values[-1]
    be_step = (be_end - be_start) / (num_points - 1) if num_points > 1 else 0

    dwell_time = parsed_data.get('dwell_time')
    periods = parsed_data.get('periods')
    txf_valid = True
    if dwell_time and periods and dwell_time > 0 and periods > 0:
        correction_factor = periods * dwell_time
        corrected_data = [intensity / correction_factor for intensity in intensities]
        transmission_values = [correction_factor] * num_points
    else:
        corrected_data = list(intensities)
        transmission_values = [1.0] * num_points
        txf_valid = False

    return {
        'be_values': be_values,
        'ke_values': ke_values,
        'transmission_values': transmission_values,
        'corrected_data': corrected_data,
        'intensities': list(intensities),
        'be_start': be_start,
        'be_end': be_end,
        'be_step': be_step,
        'txf_valid': txf_valid,
    }


def _source_label(source_energy):
    return ("Al K-alpha Monochromated" if abs(source_energy - 1486.68) < 0.1
            else f"X-ray {source_energy:.2f} eV")


def vgd_spectrum_metadata(parsed_data, calc_data, core_level, base_name,
                          spectrum_idx, num_spectra, is_area_scan):
    """Experimental-description block for one VGD spectrum."""
    meta = parsed_data['metadata']
    source_energy = parsed_data['source_energy']
    created = meta['create_time'].split() if meta['create_time'] else []
    saved = meta['saved_time'].split() if meta['saved_time'] else []
    return {
        'Sample ID': meta['subject'] if meta['subject'] else base_name,
        'Title': meta['title'],
        'Author': meta['author'],
        'Date Created': created[0] if created else '',
        'Time Created': created[1] if len(created) > 1 else '',
        'Date Saved': saved[0] if saved else '',
        'Time Saved': saved[1] if len(saved) > 1 else '',
        'Technique': 'XPS',
        'Species & Transition': core_level,
        'Spectrum Index': str(spectrum_idx),
        'Total Spectra': str(num_spectra),
        'Area Scan': 'Yes' if is_area_scan else 'No',
        'Source Label': _source_label(source_energy),
        'Source Energy': f"{source_energy:.2f}",
        'Pass Energy': f"{parsed_data['pass_energy']:.2f}" if parsed_data['pass_energy'] else 'Unknown',
        'Work Function': f"{parsed_data['work_fn']:.2f}" if parsed_data['work_fn'] else 'Unknown',
        'Dwell Time': f"{parsed_data['dwell_time']:.4f}" if parsed_data['dwell_time'] else 'Unknown',
        'Periods': str(parsed_data['periods']) if parsed_data['periods'] else 'Unknown',
        'Number of Points': str(parsed_data['num_points']),
        'BE Start': f"{calc_data['be_start']:.2f}",
        'BE End': f"{calc_data['be_end']:.2f}",
        'BE Step': f"{abs(calc_data['be_step']):.4f}",
        'KE Start': f"{parsed_data['ke_start']:.2f}" if parsed_data['ke_start'] else 'Unknown',
        'KE Step': f"{parsed_data['ke_step']:.4f}" if parsed_data['ke_step'] else 'Unknown',
        'TXF Applied': 'Yes' if calc_data['txf_valid'] else 'No',
        'TXF Coefficients': (', '.join([f"{c:.6f}" for c in parsed_data['txf_coeffs']])
                             if parsed_data['txf_coeffs'] else 'N/A'),
    }


def build_vgd_average_metadata(parsed_data, first_calc, core_level, base_name,
                               map_sheet_name, n_pixels):
    """Experimental block of the pixel-average spectrum next to a map."""
    meta = parsed_data['metadata']
    source_energy = parsed_data['source_energy']
    return {
        'Sample ID': meta['subject'] if meta['subject'] else base_name,
        'Title': meta['title'],
        'Author': meta['author'],
        'Technique': 'XPS',
        'Core Level': core_level,
        'Source Label': _source_label(source_energy),
        'Source Energy': f"{source_energy:.2f}",
        'Pass Energy': f"{parsed_data['pass_energy']:.2f}" if parsed_data['pass_energy'] else 'Unknown',
        'Number of Points': str(parsed_data['num_points']),
        'BE Start': f"{first_calc['be_start']:.2f}",
        'BE End': f"{first_calc['be_end']:.2f}",
        'Source Map': map_sheet_name,
        'Description': f"Average of all {n_pixels} pixels of {map_sheet_name}",
    }


def vgd_map_pixel_data(parsed_data):
    """(first calc, [n_pixels, n_ke] corrected intensities) of an area scan."""
    import numpy as np
    first = calculate_vgd_data(parsed_data, 0)
    arr = np.asarray(parsed_data['intensities'], dtype=np.float64)
    dwell = parsed_data.get('dwell_time')
    periods = parsed_data.get('periods')
    if dwell and periods and dwell > 0 and periods > 0:
        arr = arr / (periods * dwell)
    return first, arr


def _unique_name(base, taken):
    """'C1s' -> 'C1s', 'C1s1', 'C1s2', ... skipping names already in use."""
    if base not in taken:
        return base
    counter = 1
    while f"{base}{counter}" in taken:
        counter += 1
    return f"{base}{counter}"


def vgd_core_levels(parsed_data, core_level, base_name, existing_names=()):
    """``build_vgd_core_levels`` minus the map: ([spectrum, ...], [(name, reason)])."""
    num_spectra = parsed_data.get('num_spectra', 1)
    is_area_scan = parsed_data.get('is_area_scan', False)
    spectra, dismissed = [], []

    if is_area_scan:
        n_x, n_y = parsed_data['n_x'], parsed_data['n_y']
        n_pixels = n_x * n_y
        first, pixels = vgd_map_pixel_data(parsed_data)
        n = min(len(first['be_values']), pixels.shape[1])
        pixels = pixels[:, :n]
        be_values = [float(v) for v in first['be_values'][:n]]
        map_name = _unique_name(f"{core_level}~Map", existing_names)
        avg_name = _unique_name(core_level, set(existing_names) | {map_name})
        dismissed.append((map_name, f"XY area map ({n_x} x {n_y} pixels) — an image, "
                                    f"not a spectrum; its pixel average is '{avg_name}'"))
        spectra.append(make_spectrum(
            avg_name, be_values, pixels.mean(axis=0),
            info=build_vgd_average_metadata(parsed_data, first, core_level, base_name,
                                            map_name, n_pixels)))
        return spectra, dismissed

    taken = set(existing_names)
    for spectrum_idx in range(num_spectra):
        sheet_name = _unique_name(core_level, taken)
        taken.add(sheet_name)
        calc = calculate_vgd_data(parsed_data, spectrum_idx)
        spectra.append(make_spectrum(
            sheet_name, calc['be_values'], calc['corrected_data'],
            raw=calc['intensities'], transmission=calc['transmission_values'],
            info=vgd_spectrum_metadata(parsed_data, calc, core_level, base_name,
                                       spectrum_idx, num_spectra, is_area_scan)))
    return spectra, dismissed


def read_vgd(path):
    """Spectra of a VGD file, as KherveFitting's .kfit import builds them."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"The file {path} does not exist.")
    parsed = parse_vgd_file(path)
    filename = os.path.basename(path)
    base_name = os.path.splitext(filename)[0]
    meta = parsed['metadata']
    core_level = extract_core_level_name(filename)
    if parsed.get('is_area_scan') and (not core_level) and meta['title'] \
            and meta['title'] != "Unknown":
        core_level = meta['title'].replace(' ', '_')
    spectra, dismissed = vgd_core_levels(parsed, core_level, base_name, [])
    return ImportResult(spectra=spectra, dismissed=dismissed, source=path)


FORMATS = [
    Format(key="vgd", label="VGD file (.vgd)", group="Thermo",
           extensions=('.vgd',), reader=read_vgd, priority=50),
]
