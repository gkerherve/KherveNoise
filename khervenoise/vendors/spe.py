"""PHI MultiPak spectra (.spe) — port of KherveFitting's
``SPE_Import.open_spe_file`` + ``SPE_Import.build_spe_core_levels``
(with ``PRO_Import.phi_transmission`` and ``Open.phi_region_base``).

Route reproduced: the in-memory **.kfit** route (``build_spe_core_levels``
→ ``ConfigFile.build_core_level_Data``), so values are *not* rounded:

* 'B.E.'           = ``np.linspace(start, end, npts)`` of the region;
* 'Raw Data'       = counts / PHI transmission (the plotted trace);
* 'Corrected Data' = the same trace (an SPE sheet has no raw column);
* 'Transmission'   = 1.0.

The header / offset-detection / decoding logic is copied from
``open_spe_file`` (VersaProbe float32, X-tool float64, Quantum 2000 float64
at the end of the file).  Regions with fewer than 50 % valid points are
dismissed, as KherveFitting skips them.  Sheet names are
``phi_region_base(name)[:31]``; a repeated name gets 1, 2… appended, as the
.xlsx route's ``openpyxl`` ``create_sheet`` does (the .kfit dict would
silently keep only the last one).

Copyright (C) 2026 Gwilherm Kerherve
Licensed under the GNU General Public License v3.0 (see LICENSE).
"""

import os
import re
import struct

import numpy as np

from ..document import make_spectrum
from ..importers import ImportResult, phi_region_base
from . import Format
from .pro import phi_transmission


# ---------------------------------------------------------------------------
# Offset detection (open_spe_file's nested helpers, verbatim)
# ---------------------------------------------------------------------------
def try_find_offset_standard(binary_data, first_region, dtype, bytes_per_val):
    """Try to find data offset for standard formats (VersaProbe, X-tool)."""
    fmt = '<f' if dtype == 'float32' else '<d'
    num_points = first_region['num_points']

    first_region_size = num_points * bytes_per_val
    max_offset = len(binary_data) - first_region_size
    if max_offset < 0:
        return None
    max_offset = min(2000, max_offset)

    for offset in range(0, max_offset + 1, 2):
        try:
            values = []
            valid = True
            for i in range(min(20, num_points)):
                byte_pos = offset + i * bytes_per_val
                if byte_pos + bytes_per_val > len(binary_data):
                    valid = False
                    break
                val = struct.unpack(fmt, binary_data[byte_pos:byte_pos + bytes_per_val])[0]
                if not (1 < val < 1e8):
                    valid = False
                    break
                values.append(val)

            if valid and len(values) >= 10 and max(values) - min(values) > 1:
                # Verify all points in first region
                all_valid = True
                for i in range(num_points):
                    byte_pos = offset + i * bytes_per_val
                    if byte_pos + bytes_per_val > len(binary_data):
                        all_valid = False
                        break
                    val = struct.unpack(fmt, binary_data[byte_pos:byte_pos + bytes_per_val])[0]
                    if not (0 <= val < 1e8):
                        all_valid = False
                        break

                if all_valid:
                    return offset
        except Exception:  # noqa: BLE001 — KherveFitting: bare except
            pass

    return None


def try_quantum2000_format(binary_data, first_region, total_points):
    """Try Quantum 2000 format: float64 data at END of binary section."""
    expected_size = total_points * 8
    if expected_size > len(binary_data):
        return None

    offset = len(binary_data) - expected_size
    num_points = first_region['num_points']

    try:
        values = []
        valid = True
        for i in range(min(20, num_points)):
            byte_pos = offset + i * 8
            val = struct.unpack('<d', binary_data[byte_pos:byte_pos + 8])[0]
            if not (0 < val < 1e8):
                valid = False
                break
            values.append(val)

        if valid and len(values) >= 10 and max(values) - min(values) > 1:
            return offset
    except Exception:  # noqa: BLE001
        pass

    return None


# ---------------------------------------------------------------------------
# Decoding (open_spe_file up to the records list)
# ---------------------------------------------------------------------------
def decode_spe(file_path):
    """Return (records, skipped) exactly as ``open_spe_file`` builds them.

    records: [{'sheet_name', 'energy', 'corrected', 'exp'}]
    skipped: [(sheet_name, reason)] for regions with < 50 % valid points.
    """
    with open(file_path, 'rb') as f:
        content = f.read()

    # Extract header
    header_match = re.search(rb'SOFH(.*?)EOFH', content, re.DOTALL)
    if not header_match:
        raise ValueError("Cannot find header section (SOFH...EOFH)")

    header_text = header_match.group(1).decode('utf-8', errors='ignore')
    header_lines = [line.strip() for line in header_text.strip().split('\n')]

    # Extract intensity calibration coefficients
    a, b = 31.826, 0.229  # Default values
    for line in header_lines:
        if 'IntensityCalCoeff:' in line:
            try:
                _, coeffs = line.split(':', 1)
                parts = coeffs.strip().split()
                if len(parts) >= 2:
                    a = float(parts[0])
                    b = float(parts[1])
            except Exception:  # noqa: BLE001
                pass
            break

    # Extract source energy
    source_energy = 1486.6  # Default Al K-alpha
    for line in header_lines:
        if 'XraySource:' in line:
            if 'Al' in line:
                source_energy = 1486.6
            elif 'Mg' in line:
                source_energy = 1253.6
            # Try to extract exact value if present
            try:
                parts = line.split()
                for part in parts:
                    try:
                        val = float(part)
                        if 1200 < val < 1600:
                            source_energy = val
                            break
                    except Exception:  # noqa: BLE001
                        pass
            except Exception:  # noqa: BLE001
                pass
            break

    # Get instrument model
    instrument_model = "Unknown"
    for line in header_lines:
        if 'InstrumentModel:' in line:
            instrument_model = line.split(':', 1)[1].strip()
            break

    # Find active regions - use SpectralRegDef: (not Full or 2:)
    regions = []
    for line in header_lines:
        if line.startswith('SpectralRegDef:') and 'Full' not in line and '2:' not in line:
            parts = line.split()
            if len(parts) >= 9:
                region = {
                    'number': int(parts[1]),
                    'name': parts[3],
                    'atomic_number': int(parts[4]) if parts[4].lstrip('-').isdigit() else 0,
                    'num_points': int(parts[5]),
                    'step': float(parts[6]),
                    'start_energy': float(parts[7]),
                    'end_energy': float(parts[8]),
                    # field 12 of SpectralRegDef: pass energy (eV)
                    'pass_energy': float(parts[12]) if len(parts) > 12 and
                    parts[12].replace('.', '', 1).isdigit() else None,
                }

                # Normalize region name
                if region['name'] == 'Su1s':
                    region['name'] = 'Survey'

                regions.append(region)

    if not regions:
        raise ValueError("No spectral regions found in file")

    # Extract metadata for experimental description
    metadata = {
        'Sample ID': os.path.basename(file_path),
        'Date': '1970/1/1',
        'Time': '0:0:0',
        'Technique': 'XPS',
        'Instrument': instrument_model,
        'Species & Transition': '',
        'Number of scans': '1',
        'Source Label': 'Al' if source_energy > 1400 else 'Mg',
        'Source Energy': str(source_energy),
        'Source width X': '100',
        'Source width Y': '100',
        'Pass Energy': '224',
        'Work Function': '4.339',
        'Analyzer Mode': 'FAT',
        'Sputtering Energy': 'N/A',
        'Take-off Polar Angle': '1E+37',
        'Take-off Azimuth': '1E+37',
        'Target Bias': '1E+37',
        'Analysis Width X': '1E+37',
        'Analysis Width Y': '1E+37',
        'X Label': 'Kinetic Energy',
        'X Units': 'eV',
        'X Start': '',
        'X Step': '',
        'Num Y Values': '',
        'Num Scans': '1',
        'Collection Time': '0.16',
        'Time Correction': '1E+37',
        'Y Unit': 'd',
        '# Comment Lines': '0',
        'Block Comment': ''
    }

    # Update metadata from header
    for line in header_lines:
        if 'FileDateTime:' in line:
            parts = line.split(':', 1)[1].strip().split()
            if len(parts) >= 2:
                metadata['Date'] = parts[0]
                metadata['Time'] = parts[1]
        elif 'FileDate:' in line:
            metadata['Date'] = line.split(':', 1)[1].strip().replace(' ', '/')
        elif 'PassEnergy:' in line:
            try:
                metadata['Pass Energy'] = line.split(':', 1)[1].strip().split()[0]
            except Exception:  # noqa: BLE001
                pass
        elif 'AnalyserWorkFcn:' in line or 'WorkFunction:' in line:
            try:
                metadata['Work Function'] = line.split(':', 1)[1].strip().split()[0]
            except Exception:  # noqa: BLE001
                pass
        elif 'AnalyserMode:' in line:
            metadata['Analyzer Mode'] = line.split(':', 1)[1].strip()
        elif 'XrayBeamDiameter:' in line:
            try:
                size = line.split(':', 1)[1].strip().split()[0]
                metadata['Source width X'] = size
                metadata['Source width Y'] = size
            except Exception:  # noqa: BLE001
                pass
        elif 'Comments:' in line:
            metadata['Block Comment'] = line.split(':', 1)[1].strip()
            metadata['# Comment Lines'] = '1'

    # Get binary data section
    data_start = content.find(b'EOFH') + 4
    binary_data = content[data_start:]

    # Calculate total points
    total_points = sum(r['num_points'] for r in regions)

    # Try different formats
    data_type = None
    bytes_per_val = None
    first_offset = None

    # Method 1: Try float32 (VersaProbe format)
    offset = try_find_offset_standard(binary_data, regions[0], 'float32', 4)
    if offset is not None:
        data_type = 'float32'
        bytes_per_val = 4
        first_offset = offset

    # Method 2: Try float64 standard (X-tool format)
    if first_offset is None:
        offset = try_find_offset_standard(binary_data, regions[0], 'float64', 8)
        if offset is not None:
            data_type = 'float64'
            bytes_per_val = 8
            first_offset = offset

    # Method 3: Try Quantum 2000 format (float64 at end)
    if first_offset is None:
        offset = try_quantum2000_format(binary_data, regions[0], total_points)
        if offset is not None:
            data_type = 'float64'
            bytes_per_val = 8
            first_offset = offset

    if first_offset is None:
        raise ValueError("Could not detect data format or find valid data offset")

    # Calculate offsets for all regions (contiguous data)
    region_offsets = []
    current_offset = first_offset
    for region in regions:
        region_offsets.append(current_offset)
        current_offset += region['num_points'] * bytes_per_val

    fmt = '<f' if data_type == 'float32' else '<d'
    records = []
    skipped = []

    # Process each region
    for i, region in enumerate(regions):
        # 'Fe2p3' is PHI's 2p3/2 window, not Fe2p on sample row 3
        sheet_name = phi_region_base(region['name'])
        num_points = region['num_points']
        offset = region_offsets[i]

        # Read intensity values
        intensity_values = []
        valid_count = 0
        for j in range(num_points):
            data_offset = offset + (j * bytes_per_val)
            if data_offset + bytes_per_val <= len(binary_data):
                try:
                    val = struct.unpack(fmt, binary_data[data_offset:data_offset + bytes_per_val])[0]
                    if 0 <= val < 1e8:
                        intensity_values.append(val)
                        valid_count += 1
                    else:
                        intensity_values.append(0.0)
                except Exception:  # noqa: BLE001
                    intensity_values.append(0.0)
            else:
                intensity_values.append(0.0)

        # Skip regions with mostly invalid data (< 50% valid)
        if valid_count < num_points * 0.5:
            skipped.append((sheet_name, f"only {valid_count}/{num_points} valid points"))
            continue

        # Make sure we have the expected number of points
        if len(intensity_values) < num_points:
            intensity_values.extend([0.0] * (num_points - len(intensity_values)))

        # Create sheet (max 31 chars for sheet name)
        sheet_name = sheet_name[:31]

        # Update region-specific metadata
        region_metadata = metadata.copy()
        region_metadata['Species & Transition'] = region['name']
        region_metadata['X Start'] = f"{region['start_energy']:.2f}"
        region_metadata['X Step'] = f"{region['step']:.4f}"
        region_metadata['Num Y Values'] = str(num_points)

        # Calculate energy values and transmission
        energy_values = np.linspace(region['start_energy'], region['end_energy'], num_points)
        ke_values = source_energy - energy_values
        # Protect against negative or zero KE values
        ke_values = np.maximum(ke_values, 1.0)
        transmission = phi_transmission(
            ke_values, region.get('pass_energy') or metadata.get('Pass Energy'), a, b)
        corrected_intensity = np.array(intensity_values) / transmission

        records.append({
            'sheet_name': sheet_name,
            'energy': energy_values,
            'corrected': corrected_intensity,
            'exp': region_metadata,
        })

    return records, skipped


def read_spe(path):
    """Spectra of a PHI .spe file, as KherveFitting's .kfit import builds them."""
    records, skipped = decode_spe(path)
    if not records:
        raise ValueError("No valid data regions found in file")
    result = ImportResult(source=path)
    result.dismissed.extend(skipped)
    taken = set()
    for rec in records:
        base = rec['sheet_name']
        name = base
        count = 1
        while name in taken:
            name = f"{base}{count}"
            count += 1
        taken.add(name)
        # build_core_level_Data(be_values=energy, plot_values=corrected):
        # raw_values defaults to the plotted trace, transmission to 1.0.
        result.spectra.append(make_spectrum(name, rec['energy'], rec['corrected'],
                                            info=rec['exp']))
    return result


FORMATS = [
    Format(key="spe", label="Data file (.spe)", group="PHI",
           extensions=(".spe",), reader=read_spe),
]
