"""PHI depth profiles (.pro) — port of KherveFitting's ``PRO_Import``:
``_parse_pro_header``, ``_extract_regions``, ``phi_transmission``,
``_find_data_offset``, ``_read_blocks``, ``open_pro_file`` and
``build_pro_core_levels``.

Route reproduced: the in-memory **.kfit** route (``build_pro_core_levels``
→ ``ConfigFile.build_core_level_Data``), so values are *not* rounded.  One
spectrum per region x depth cycle, in storage order (region-major,
cycle-minor):

* 'B.E.'           = ``np.linspace(be_start, be_end, npts)``;
* 'Raw Data'       = counts / PHI transmission (the plotted trace), where
  counts = stored c/s x the region's collection time;
* 'Corrected Data' = those counts;
* 'Transmission'   = ``phi_transmission(source - BE, pass energy, a, b)``.

Names are ``normalize_sheet_name(phi_region_base(region))`` made unique
with 1, 2… (C1s, C1s1, C1s2 for three cycles), as ``open_pro_file`` does.

Copyright (C) 2026 Gwilherm Kerherve
Licensed under the GNU General Public License v3.0 (see LICENSE).
"""

import os
import re
import struct

import numpy as np

from ..document import make_spectrum
from ..importers import ImportResult, normalize_sheet_name, phi_region_base
from . import Format


# ---------------------------------------------------------------------------
# Header parsing
# ---------------------------------------------------------------------------
def _parse_pro_header(content):
    """Return (header_lines, header_dict) parsed from the SOFH...EOFH block."""
    hm = re.search(rb'SOFH(.*?)EOFH', content, re.DOTALL)
    if not hm:
        raise ValueError("Not a valid PHI file: missing SOFH...EOFH header")
    text = hm.group(1).decode('latin-1', errors='ignore')
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    hdr = {}
    for ln in lines:
        if ':' in ln:
            key, val = ln.split(':', 1)
            # Keep the first occurrence of repeated keys (e.g. SpectralRegDef)
            hdr.setdefault(key.strip(), val.strip())
    return lines, hdr


def _extract_regions(header_lines):
    """Active depth-profile regions from the plain ``SpectralRegDef:`` lines.

    Field layout (whitespace separated):
        SpectralRegDef: <n> <?> <name> <Z> <npts> <step> <be_start> <be_end>
                        <inner_lo> <inner_hi> <coll_time> <pass_energy> <mode>
    """
    regions = []
    for ln in header_lines:
        if not ln.startswith('SpectralRegDef:'):
            continue
        # Exclude the *Full / *Def2 / *Background / *Hero / *IR sibling keys
        key = ln.split(':', 1)[0]
        if key != 'SpectralRegDef':
            continue
        p = ln.split()
        if len(p) < 13:
            continue
        try:
            regions.append({
                'name': p[3],
                'atomic_number': int(p[4]) if p[4].lstrip('-').isdigit() else 0,
                'npts': int(p[5]),
                'step': float(p[6]),
                'be_start': float(p[7]),
                'be_end': float(p[8]),
                'coll_time': float(p[11]),
                'pass_energy': float(p[12]),
            })
        except (ValueError, IndexError):
            continue
    return regions


def phi_transmission(ke, pass_energy, a, b):
    """PHI analyser transmission (MultiPak's law):

        T = PE * ( a^2 / (a^2 + (KE/PE)^2) )^b

    with a, b from the header's IntensityCalCoeff and PE the pass energy;
    ``a * KE^-b`` when no pass energy is known.
    """
    ke = np.maximum(np.asarray(ke, dtype=float), 1.0)
    try:
        pe = float(pass_energy)
    except (TypeError, ValueError):
        pe = 0.0
    if not pe > 0:
        return a * np.power(ke, -b)
    r = ke / pe
    return pe * np.power(a * a / (a * a + r * r), b)


def _hval(hdr, key, default=None):
    return hdr.get(key, default)


# ---------------------------------------------------------------------------
# Binary data location + decode
# ---------------------------------------------------------------------------
def _find_data_offset(binary, regions, cycles):
    """Byte offset (within the post-EOFH section) of the first spectrum float."""
    total = cycles * sum(r['npts'] for r in regions)
    tot_bytes = total * 4
    # Two float32 tables of one value per region per cycle follow the
    # spectra, on top of a short record trailer.
    max_trailer = 512 + 8 * len(regions) * cycles
    n0 = regions[0]['npts']
    limit = len(binary) - tot_bytes
    if limit < 0:
        raise ValueError("PHI .pro binary section too small for declared regions/cycles")

    for off in range(0, limit + 1, 2):
        ok = True
        # First region must be a clean, strong positive signal (rejects the
        # zero-padding that precedes the data)
        for k in range(n0):
            v = struct.unpack_from('<f', binary, off + 4 * k)[0]
            if not (1.0 < v < 1e7):
                ok = False
                break
        if not ok:
            continue
        # Remaining points must be finite and non-negative
        for k in range(n0, total):
            v = struct.unpack_from('<f', binary, off + 4 * k)[0]
            if not (0.0 <= v < 1e7):
                ok = False
                break
        if ok and 0 <= len(binary) - (off + tot_bytes) <= max_trailer:
            return off
    raise ValueError("Could not locate spectral data in PHI .pro file")


def _read_blocks(binary, start, regions, cycles):
    """Return list of (region, cycle, c/s values) in storage order."""
    off = start
    blocks = []
    for r in regions:
        for c in range(cycles):
            vals = list(struct.unpack_from('<%df' % r['npts'], binary, off))
            off += r['npts'] * 4
            blocks.append((r, c, vals))
    return blocks


# ---------------------------------------------------------------------------
# open_pro_file (records part)
# ---------------------------------------------------------------------------
def decode_pro(file_path):
    """Return (records, sample_name) exactly as ``open_pro_file`` builds them.

    records: [{'sheet_name', 'be', 'corrected', 'raw_counts',
               'transmission', 'exp'}]
    """
    with open(file_path, 'rb') as f:
        content = f.read()

    header_lines, hdr = _parse_pro_header(content)

    regions = _extract_regions(header_lines)
    if not regions:
        raise ValueError("No active spectral regions (SpectralRegDef) found")

    # Number of depth-profile data cycles (default 1 for a plain acquisition)
    try:
        cycles = int(float(_hval(hdr, 'NoDPDataCyc', '1')))
    except (ValueError, TypeError):
        cycles = 1
    cycles = max(cycles, 1)

    # Source energy + intensity-calibration (transmission) coefficients
    source_energy = 1486.6
    xr = _hval(hdr, 'XraySource', '')
    if xr:
        for tok in xr.split():
            try:
                val = float(tok)
                if 100 < val < 6000:
                    source_energy = val
                    break
            except ValueError:
                pass
    source_label = 'Al' if source_energy > 1400 else 'Mg'

    cal_a, cal_b = 78.797, 0.629  # VersaProbe III defaults
    cal = _hval(hdr, 'IntensityCalCoeff', '')
    if cal:
        try:
            parts = cal.split()
            cal_a, cal_b = float(parts[0]), float(parts[1])
        except (ValueError, IndexError):
            pass

    work_fn = '4.397'
    wf = _hval(hdr, 'AnalyserWorkFcn', '')
    if wf:
        work_fn = wf.split()[0]

    instrument = _hval(hdr, 'InstrumentModel', 'PHI')
    operator = _hval(hdr, 'Operator', '')
    analyzer_mode = _hval(hdr, 'AnalyserMode', 'FAT')
    sputter_energy = _hval(hdr, 'SputterEnergy', 'N/A')
    date_raw = _hval(hdr, 'FileDate', '')
    date_str = date_raw.replace(' ', '/') if date_raw else ''
    # Sample name: the spatial-area description if present, else file name
    sample_name = None
    for ln in header_lines:
        if ln.startswith('SpatialAreaDesc:'):
            parts = ln.split(':', 1)[1].strip().split(None, 1)
            if len(parts) == 2:
                sample_name = parts[1].strip()
            break
    if not sample_name:
        sample_name = os.path.splitext(os.path.basename(file_path))[0]

    # ---- Locate + decode binary spectra ---------------------------------
    binary = content[content.find(b'EOFH') + 4:]
    start = _find_data_offset(binary, regions, cycles)
    blocks = _read_blocks(binary, start, regions, cycles)

    records = []
    sheet_names = []
    for region, cycle, cs_values in blocks:
        # 'Fe2p3' is PHI's 2p3/2 window, not Fe2p on sample row 3
        base = normalize_sheet_name(phi_region_base(region['name']))
        sheet_name = base
        count = 1
        while sheet_name in sheet_names:
            sheet_name = f"{base}{count}"
            count += 1
        sheet_names.append(sheet_name)

        npts = region['npts']
        be = np.linspace(region['be_start'], region['be_end'], npts)
        # counts = (counts / second) x collection_time
        raw_counts = np.array(cs_values, dtype=float) * region['coll_time']

        # Analyser transmission, PHI's law (see phi_transmission)
        transmission = phi_transmission(source_energy - be, region['pass_energy'],
                                        cal_a, cal_b)
        corrected = raw_counts / transmission

        exp = {
            'Sample ID': sample_name,
            'Date': date_str,
            'Time': '0:0:0',
            'Technique': 'XPS',
            'Species & Transition': region['name'],
            'Number of scans': '1',
            'Source Label': source_label,
            'Source Energy': f"{source_energy:.1f}",
            'Source width X': _hval(hdr, 'XrayBeamDiameter', '220').split()[0],
            'Source width Y': _hval(hdr, 'XrayBeamDiameter', '220').split()[0],
            'Pass Energy': f"{region['pass_energy']:.0f}",
            'Work Function': work_fn,
            'Analyzer Mode': analyzer_mode,
            'Sputtering Energy': sputter_energy,
            'Sputter Time': str(cycle),
            'Sample Tilt': '',
            'Take-off Polar Angle': '1E+37',
            'Take-off Azimuth': '1E+37',
            'Target Bias': '1E+37',
            'Analysis Width X': '1E+37',
            'Analysis Width Y': '1E+37',
            'X Label': 'Binding Energy',
            'X Units': 'eV',
            'X Start': f"{region['be_start']:.2f}",
            'X Step': f"{region['step']:.4f}",
            'Num Y Values': str(npts),
            'Num Scans': '1',
            'Collection Time': f"{region['coll_time']:.3f}",
            'Time Correction': '1E+37',
            'Y Unit': 'd',
            '# Comment Lines': '1',
            'Block Comment': f"PHI .pro depth profile - {region['name']} cycle {cycle}",
            'Depth Cycle': str(cycle),
            'Instrument': instrument,
            'Operator': operator,
        }
        records.append({
            'sheet_name': sheet_name,
            'be': be,
            'corrected': corrected,
            'raw_counts': raw_counts,
            'transmission': transmission,
            'exp': exp,
        })

    if not records:
        raise ValueError("No spectra were imported")
    return records, sample_name


def read_pro(path):
    """Spectra of a PHI .pro depth profile, as KherveFitting's .kfit import
    builds them (build_pro_core_levels)."""
    records, _sample = decode_pro(path)
    result = ImportResult(source=path)
    for rec in records:
        result.spectra.append(make_spectrum(
            rec['sheet_name'], rec['be'], rec['corrected'],
            raw=rec['raw_counts'], transmission=rec['transmission'],
            info=rec['exp']))
    return result


FORMATS = [
    Format(key="pro", label="Depth profile (.pro)", group="PHI",
           extensions=(".pro",), reader=read_pro),
]
