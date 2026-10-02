"""SDP / XPS International (.sdp) — port of KherveFitting's ``SDP_Import``:
``parse_sdp_file``, ``identify_core_level_from_be``,
``identify_core_level_from_description``,
``_extract_core_level_from_filename``, ``extract_sample_name``,
``_unique_sheet_name`` and ``_write_sheet``, as driven by
``import_sdp_file``.

Route reproduced: the **workbook** route — the only one SDP has.
``_write_sheet`` writes ``round(be, 2) | round(intensity, 2)`` and the
Experimental Description block at column 50, and
``ConfigFile.add_core_level_Data`` reads it back with ``.2f`` rounding, so:

* 'B.E.'           = _r2(round(be_start + i * be_step, 2));
* 'Raw Data'       = _r2(round(intensity, 2));
* 'Corrected Data' = 'Raw Data' (no column C);
* 'Transmission'   = 1.0 (no column D).

Names are the identified core level made unique with 1, 2…
(``_unique_sheet_name``); ``refresh_sheets``' later normalisation never
changes such a name (they carry no space or scan suffix).  KherveFitting
warns before importing (see ``Format.notice``).

Copyright (C) 2026 Gwilherm Kerherve
Licensed under the GNU General Public License v3.0 (see LICENSE).
"""

import os
import re
import struct

from ..document import make_spectrum
from ..importers import ImportResult, _r2
from . import Format

MAGIC = b'XI SDP BINARY FILE'
MAGIC_LEN = 18

# Marker used to locate the start of each spectrum block
BE_MARKER = b'Binding Energy'

# Fixed offset from a "Binding Energy" marker to the first metadata string.
BE_TO_META_STRINGS = 112

# Length-prefixed metadata strings before the parameter block:
#   0: file path,  1: description,  2: acquisition params,
#   3: date,  4: format string (e.g. "VAMAS/ISO", "XI ASCII")
NUM_META_STRINGS = 5

# Field offsets within the parameter block (starts right after the 5th string)
OFF_BE_START = 0
OFF_BE_STEP = 8
OFF_BE_END = 16
OFF_Y_MIN = 24
OFF_Y_MAX = 32
OFF_SOURCE_E = 42      # 2-byte gap at +40
OFF_WORK_FN = 58
OFF_PASS_E = 66
OFF_SWEEPS = 74
OFF_FLAG = 90
OFF_DATA_COUNT = 94
OFF_DATA_START = 98

NOTICE = (
    "This file is the property of Spectral Data Processor (SDP).\n"
    "You should use the SDP software to view/edit this file.\n\n"
    "I can attempt to import it, but I cannot promise that the data is correct.\n\n"
    "Do you want to proceed with the import?"
)


# ---------------------------------------------------------------------------
# Core-level identification
# ---------------------------------------------------------------------------
_CORE_LEVELS = [
    (14, "Hf4f"), (18, "Ga3d"), (22, "Ta4f"), (26, "Ge3d"), (31, "W4f"),
    (40, "Re4f"), (42, "As3d"), (49, "Mg2p"), (51, "Os4f"), (55, "Se3d"),
    (61, "Ir4f"), (69, "Br3d"), (71, "Pt4f"), (74, "Al2p"), (84, "Au4f"),
    (99, "Si2p"), (111, "Rb3d"), (118, "Tl4f"), (130, "P2p"), (134, "Sr3d"),
    (139, "Pb4f"), (142, "Gd4d"), (151, "Si2s"), (157, "Y3d"), (162, "S2p"),
    (170, "Bi4f"), (182, "Zr3d"), (189, "B1s"), (199, "Cl2p"), (207, "Nb3d"),
    (228, "Mo3d"), (232, "S2s"), (242, "Ar2p"), (280, "C1s"), (285, "C1s"),
    (293, "K2p"), (307, "Rh3d"), (334, "Pd3d"), (347, "Ca2p"), (368, "Ag3d"),
    (382, "U4f"), (399, "N1s"), (405, "Cd3d"), (412, "Sc2p"), (444, "In3d"),
    (459, "Ti2p"), (487, "Sn3d"), (517, "V2p"), (529, "O1s"), (532, "O1s"),
    (573, "Te3d"), (577, "Cr2p"), (619, "I3d"), (641, "Mn2p"), (686, "F1s"),
    (711, "Fe2p"), (726, "Cs3d"), (780, "Co2p"), (796, "Ba3d"), (836, "La3d"),
    (855, "Ni2p"), (883, "Ce3d"), (929, "Pr3d"), (933, "Cu2p"), (980, "Nd3d"),
    (1004, "Pm3d"), (1022, "Zn2p"), (1072, "Na1s"), (1083, "Sm3d"),
    (1117, "Ga2p"), (1126, "Eu3d"), (1186, "Gd3d"), (1220, "Tb3d"),
    (1296, "Dy3d"), (1351, "Ho3d"), (1409, "Er3d"), (1468, "Tm3d"),
]


def identify_core_level_from_be(be_start, be_end):
    """'Survey' for > 200 eV wide scans, 'VB' for 0-20 eV, else the closest
    primary core level within 30 eV ('Unknown' otherwise)."""
    center = (be_start + be_end) / 2.0
    width = abs(be_start - be_end)

    if width > 200:
        return "Survey"
    if center <= 20 and width < 60:
        return "VB"

    best_name = "Unknown"
    best_dist = 999.0
    for be, name in _CORE_LEVELS:
        dist = abs(center - be)
        if dist < best_dist and dist < 30:
            best_dist = dist
            best_name = name
    return best_name


def identify_core_level_from_description(desc):
    """'C1s Scan' -> 'C1s', 'O 1s' -> 'O1s', 'Survey' -> 'Survey', 'VB scan' -> 'VB'."""
    if not desc:
        return None

    match = re.match(r'^([A-Z][a-z]?\s*\d+[spdfgh]\d*)', desc)
    if match:
        return match.group(1).replace(' ', '')

    low = desc.lower().strip()
    if low.startswith(('survey', 'wide')):
        return 'Survey'
    if low.startswith(('vb', 'valence')):
        return 'VB'

    return None


def _extract_core_level_from_filename(filename):
    """'O1s.sdp' -> 'O1s', 'C1s_Scan.sdp' -> 'C1s', 'Survey.sdp' -> 'Survey'."""
    if not filename:
        return None

    base = os.path.splitext(os.path.basename(filename))[0]

    for suffix in ['_Scan', '_scan', '_SCAN', ' Scan', ' scan',
                   '_Region', '_region', ' Region', ' region',
                   '_spe', '_SPE', '_txt', '_TXT', '_vgd', '_VGD',
                   '_vms', '_VMS', '_iso', '_ISO', '_mrs', '_MRS']:
        if base.endswith(suffix):
            base = base[:-len(suffix)]
            break

    match = re.match(r'^([A-Z][a-z]?\s*\d+[spdfgh]\d*)', base)
    if match:
        return match.group(1).replace(' ', '')

    low = base.lower().strip()
    if low.startswith(('survey', 'wide')):
        return 'Survey'
    if low.startswith(('vb', 'valence')):
        return 'VB'

    return None


def extract_sample_name(filename):
    """Sample name from the SDP filename, source-format suffix removed."""
    base_name = os.path.splitext(filename)[0]

    suffixes_to_remove = [
        '_spe', '_SPE', '_txt', '_TXT', '_vgd', '_VGD',
        '_vms', '_VMS', '_iso', '_ISO', '_mrs', '_MRS',
    ]
    result = base_name
    for suffix in suffixes_to_remove:
        if result.endswith(suffix):
            result = result[:-len(suffix)]
            break

    return result.strip()


# ---------------------------------------------------------------------------
# Binary parser
# ---------------------------------------------------------------------------
def parse_sdp_file(file_path):
    """{'spectra': [...], 'metadata': {...}} of an SDP binary file."""
    with open(file_path, 'rb') as f:
        data = f.read()

    file_size = len(data)

    if len(data) < MAGIC_LEN or data[:MAGIC_LEN] != MAGIC:
        raise ValueError("Not a valid SDP file: missing 'XI SDP BINARY FILE' header")

    version = struct.unpack('<H', data[18:20])[0]
    num_spectra_declared = struct.unpack('<H', data[20:22])[0]

    be_offsets = []
    pos = 0
    while True:
        pos = data.find(BE_MARKER, pos)
        if pos == -1:
            break
        be_offsets.append(pos)
        pos += 1

    if not be_offsets:
        raise ValueError("No spectrum data found in SDP file "
                         "(no 'Binding Energy' markers)")

    spectra = []

    for block_idx, be_off in enumerate(be_offsets):
        # ---- Walk through the 5 metadata strings ----------------------------
        meta_start = be_off + BE_TO_META_STRINGS
        if meta_start + 4 > file_size:
            continue

        off = meta_start
        meta_strings = []   # [path, description, acq_params, date, format]
        valid_meta = True
        for _ in range(NUM_META_STRINGS):
            if off + 2 > file_size:
                valid_meta = False
                break
            slen = struct.unpack('<H', data[off:off + 2])[0]
            if slen > 1000 or off + 2 + slen > file_size:
                valid_meta = False
                break
            raw = data[off + 2:off + 2 + slen]
            meta_strings.append(
                raw.split(b'\x00')[0].decode('ascii', errors='replace').strip())
            off += 2 + slen

        if not valid_meta or len(meta_strings) < NUM_META_STRINGS:
            continue

        # ---- Read parameter block -------------------------------------------
        params_base = off

        if params_base + OFF_DATA_START > file_size:
            continue

        try:
            be_start = struct.unpack('<d', data[params_base + OFF_BE_START:
                                                params_base + OFF_BE_START + 8])[0]
            be_step = struct.unpack('<d', data[params_base + OFF_BE_STEP:
                                               params_base + OFF_BE_STEP + 8])[0]
            be_end = struct.unpack('<d', data[params_base + OFF_BE_END:
                                              params_base + OFF_BE_END + 8])[0]
        except struct.error:
            continue

        if abs(be_start) > 5000 or abs(be_end) > 5000:
            continue
        if abs(be_step) > 100 or be_step == 0:
            continue

        try:
            y_min = struct.unpack('<d', data[params_base + OFF_Y_MIN:
                                             params_base + OFF_Y_MIN + 8])[0]
            y_max = struct.unpack('<d', data[params_base + OFF_Y_MAX:
                                             params_base + OFF_Y_MAX + 8])[0]
            source_energy = struct.unpack('<d', data[params_base + OFF_SOURCE_E:
                                                     params_base + OFF_SOURCE_E + 8])[0]
            work_fn = struct.unpack('<d', data[params_base + OFF_WORK_FN:
                                               params_base + OFF_WORK_FN + 8])[0]
            pass_energy = struct.unpack('<d', data[params_base + OFF_PASS_E:
                                                   params_base + OFF_PASS_E + 8])[0]
            sweeps = struct.unpack('<d', data[params_base + OFF_SWEEPS:
                                              params_base + OFF_SWEEPS + 8])[0]
        except struct.error:
            source_energy = 1486.68
            work_fn = pass_energy = sweeps = 0.0
            y_min = y_max = 0.0  # noqa: F841 — kept as in KherveFitting

        try:
            data_count = struct.unpack('<I', data[params_base + OFF_DATA_COUNT:
                                                  params_base + OFF_DATA_COUNT + 4])[0]
        except struct.error:
            continue

        data_start = params_base + OFF_DATA_START

        if data_count == 0 or data_count > 100000:
            continue
        if data_start + data_count * 8 > file_size:
            continue

        intensities = []
        for i in range(data_count):
            val = struct.unpack('<d', data[data_start + i * 8:
                                           data_start + i * 8 + 8])[0]
            intensities.append(val)

        if not intensities or all(v == 0 for v in intensities):
            continue

        # Verify data looks like real XPS counts (not garbage bytes)
        valid_count = sum(1 for v in intensities if abs(v) < 1e12 and v == v)
        if valid_count < len(intensities) * 0.9:
            continue

        be_values = [be_start + i * be_step for i in range(data_count)]

        file_path_str = meta_strings[0]
        description = meta_strings[1]
        acq_params = meta_strings[2]
        date_str = meta_strings[3]
        format_str = meta_strings[4]

        # Description, then the outer SDP filename, then the BE range.
        core_level = identify_core_level_from_description(description)
        if core_level is None:
            core_level = _extract_core_level_from_filename(file_path)
        if core_level is None:
            core_level = identify_core_level_from_be(be_start, be_values[-1])

        if not (100 < source_energy < 5000):
            source_energy = 1486.68

        spectra.append({
            'be_start': be_start,
            'be_step': be_step,
            'be_end': be_end,
            'be_values': be_values,
            'intensities': intensities,
            'num_points': data_count,
            'core_level': core_level,
            'file_path': file_path_str,
            'description': description,
            'acq_params': acq_params,
            'date': date_str,
            'format': format_str,
            'source_energy': source_energy,
            'pass_energy': pass_energy if 0 < pass_energy < 1000 else None,
            'work_function': work_fn if 2.0 < work_fn < 8.0 else None,
            'sweeps': int(sweeps) if 0 < sweeps < 10000 else None,
        })

    if not spectra:
        raise ValueError("No valid spectrum data found in SDP file")

    sample_name = extract_sample_name(os.path.basename(file_path))

    # The first description is the sample name only when meaningful
    first_desc = spectra[0].get('description', '')
    scan_label_pattern = re.compile(
        r'^[A-Z][a-z]?\d+[spdfgh]\d*\s+(Scan|Region|scan|region)', re.IGNORECASE)
    if first_desc:
        is_scan_label = bool(scan_label_pattern.match(first_desc))
        is_filename = any(c in first_desc for c in ['\\', '/']) or first_desc.endswith(('.txt', '.vms'))
        if not is_scan_label and not is_filename:
            sample_name = first_desc

    source_label = "Al K-alpha Monochromated" if abs(
        spectra[0]['source_energy'] - 1486.68) < 0.5 else (
        f"X-ray {spectra[0]['source_energy']:.2f} eV")

    return {
        'spectra': spectra,
        'metadata': {
            'file_path': file_path,
            'sample_name': sample_name,
            'version': version,
            'num_spectra_declared': num_spectra_declared,
            'num_spectra_actual': len(spectra),
            'source_energy': spectra[0].get('source_energy', 1486.68),
            'source_label': source_label,
            'source_file': spectra[0].get('file_path', ''),
        }
    }


# ---------------------------------------------------------------------------
# Sheet layout (_write_sheet) read back as add_core_level_Data does
# ---------------------------------------------------------------------------
def _unique_sheet_name(core_level, sheet_names):
    """Return a unique sheet name: C1s, C1s1, C1s2, ..."""
    if core_level not in sheet_names:
        return core_level
    counter = 1
    while f"{core_level}{counter}" in sheet_names:
        counter += 1
    return f"{core_level}{counter}"


def _sheet_metadata(spec, meta, spec_idx, total_spectra):
    """The Experimental Description block ``_write_sheet`` writes."""
    source_energy = spec.get('source_energy', 1486.68)
    source_label = meta.get('source_label', '')
    return {
        'Sample ID': meta['sample_name'],
        'Source File': os.path.basename(meta.get('source_file', '')),
        'Original Path': spec.get('file_path', ''),
        'Description': spec.get('description', ''),
        'Date': spec.get('date', ''),
        'Technique': 'XPS',
        'Species & Transition': spec['core_level'],
        'Spectrum Index': str(spec_idx),
        'Total Spectra': str(total_spectra),
        'Source Label': source_label,
        'Source Energy': f"{source_energy:.2f}",
        'Pass Energy': (f"{spec['pass_energy']:.2f}"
                        if spec.get('pass_energy') else 'Unknown'),
        'Work Function': (f"{spec['work_function']:.2f}"
                          if spec.get('work_function') else 'Unknown'),
        'Sweeps': str(spec['sweeps']) if spec.get('sweeps') else 'Unknown',
        'Number of Points': str(spec['num_points']),
        'BE Start': f"{spec['be_start']:.2f}",
        'BE End': f"{spec['be_end']:.2f}",
        'BE Step': f"{abs(spec['be_step']):.4f}",
        'SDP Version': str(meta.get('version', '')),
    }


def read_sdp(path):
    """Spectra of an SDP file, as KherveFitting's workbook import leaves them."""
    parsed = parse_sdp_file(path)
    meta = parsed['metadata']
    spectra = parsed['spectra']
    result = ImportResult(source=path)
    sheet_names = []
    for spec_idx, spec in enumerate(spectra):
        sheet_name = _unique_sheet_name(spec['core_level'], sheet_names)
        sheet_names.append(sheet_name)
        # zip() in _write_sheet; round(v, 2) written, '.2f' read back;
        # add_core_level_Data skips rows whose value is NaN.
        pairs = [(be, y) for be, y in zip(spec['be_values'], spec['intensities'])
                 if be == be and y == y]
        xs = [_r2(round(be, 2)) for be, _y in pairs]
        ys = [_r2(round(y, 2)) for _be, y in pairs]
        result.spectra.append(make_spectrum(
            sheet_name, xs, ys,
            info=_sheet_metadata(spec, meta, spec_idx, len(spectra))))
    return result


FORMATS = [
    Format(key="sdp", label="SDP file (.sdp)", group="XPS International (SDP)",
           extensions=(".sdp",), reader=read_sdp, notice=NOTICE),
]
