"""Igor Pro exports (.itx, .dat) — port of KherveFitting's Igor_Import.

Reproduces ``import_igor_itx_file`` and ``import_igor_dat_file``:

* **ITX** — ``IGOR`` first line, ``WAVES 'name'`` / ``BEGIN`` / values /
  ``END`` blocks, the BE axis from the following ``X SetScale/P x start,step``
  (point index when absent); fitted waves (bck, fitresult, peak) skipped;
  waves taken in sorted name order and named from ``[All <core level>]
  <sample>`` or, failing that, a core level / VB / 'eV' found in the wave
  name.
* **DAT** — tab-separated, a header row of ``[All <core level>] <sample>``
  columns, the BE column found the way KherveFitting does (a column whose
  values are all above 500 is BE with the counts in the next column,
  otherwise the nearest empty-header column to the left, else column 0).

Both name each spectrum ``<core level><index>`` (C1s0, O1s1 …), reverse the
data to high -> low BE and multiply intensities by 10000 when their maximum
is below 100 (KherveFitting's guard against '.2f' precision loss).

**Workbook route**: KherveFitting writes ``f"{v:.2f}"`` strings to a sheet
and reads them back with ``ConfigFile.add_core_level_Data`` — reproduced by
``_r2`` on the very same values.

Copyright (C) 2026 Gwilherm Kerherve
Licensed under the GNU General Public License v3.0 (see LICENSE).
"""

import os
import re

import numpy as np

from ..document import make_spectrum
from ..importers import ImportResult, _r2
from . import Format

_SAMPLE_PATTERN = r'\[All (.*?)\] (\w+)'


def _spectrum(name, be_values, data_values, info):
    """Write f'{v:.2f}' cells (reversed, scaled), read them back."""
    max_val = np.max(data_values) if len(data_values) > 0 else 0
    scale_factor = 10000 if max_val < 100 else 1
    be_rev = list(be_values)[::-1]
    data_rev = list(data_values)[::-1]
    xs, ys = [], []
    for be, intensity in zip(be_rev, data_rev):
        xs.append(_r2(f"{be:.2f}"))
        ys.append(_r2(f"{(intensity * scale_factor):.2f}"))
    if scale_factor != 1:
        info = dict(info, **{'Intensity Scale': str(scale_factor)})
    return make_spectrum(name, xs, ys, info=info)


# ---------------------------------------------------------------------------
# ITX
# ---------------------------------------------------------------------------
def read_igor_itx(path):
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    if not lines or lines[0].strip() != 'IGOR':
        raise ValueError("Not a valid Igor ITX file")

    waves_data = {}
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if line.startswith('WAVES'):
            wave_name_match = re.search(r"WAVES[/\w]*\s+'([^']+)'", line)
            if not wave_name_match:
                i += 1
                continue

            wave_name = wave_name_match.group(1)

            if any(term in wave_name.lower() for term in ['bck', 'fitresult', 'peak']):
                i += 1
                continue

            i += 1
            while i < len(lines) and lines[i].strip() != 'BEGIN':
                i += 1

            if i >= len(lines):
                break

            i += 1
            data_values = []
            while i < len(lines) and lines[i].strip() != 'END':
                try:
                    value = float(lines[i].strip())
                    data_values.append(value)
                except ValueError:
                    pass
                i += 1

            if data_values:
                waves_data[wave_name] = np.array(data_values)

                i += 1
                if i < len(lines):
                    setscale_line = lines[i].strip()
                    if setscale_line.startswith('X SetScale'):
                        match = re.search(r'x\s+([\d.]+),([\d.]+)', setscale_line)
                        if match:
                            start_be = float(match.group(1))
                            step = float(match.group(2))
                            be_array = np.arange(start_be,
                                                 start_be + step * len(data_values),
                                                 step)[:len(data_values)]
                            waves_data[f'{wave_name}_BE'] = be_array

        i += 1

    if not waves_data:
        raise ValueError("No valid wave data found in file")

    samples_info = []
    for wave_name in sorted(waves_data.keys()):
        if '_BE' in wave_name:
            continue

        match = re.search(_SAMPLE_PATTERN, wave_name)
        if match:
            core_level_raw = match.group(1)
            sample_name = match.group(2)
            core_level = core_level_raw.replace(' ', '')
            samples_info.append({'sample_name': sample_name, 'core_level': core_level,
                                 'wave_name': wave_name})
        else:
            core_level_match = re.search(r'([A-Z][a-z]?\d[spdf])', wave_name)
            if core_level_match:
                core_level = core_level_match.group(1)
            elif '_V' in wave_name or 'VB' in wave_name.upper() or 'valence' in wave_name.lower():
                vb_range_match = re.search(r'_V\(([\d.]+)\s+to\s+([\d.]+)\)', wave_name)
                if vb_range_match:
                    core_level = f"VB_{vb_range_match.group(1)}to{vb_range_match.group(2)}"
                else:
                    core_level = 'VB'
            elif 'eV' in wave_name:
                ev_match = re.search(r'([\d.]+)\s*eV', wave_name)
                if ev_match:
                    core_level = f"{ev_match.group(1)}eV"
                else:
                    core_level = 'Spectrum'
            else:
                core_level = 'Unknown'

            sample_name = wave_name.strip("'").replace('.txt', '').replace('.itx', '')
            samples_info.append({'sample_name': sample_name, 'core_level': core_level,
                                 'wave_name': wave_name})

    if not samples_info:
        raise ValueError("No valid sample data found in file")

    result = ImportResult(source=path)
    for idx, sample_info in enumerate(samples_info):
        wave_name = sample_info['wave_name']
        sheet_name = f"{sample_info['core_level']}{idx}"
        be_key = f'{wave_name}_BE'
        if be_key in waves_data:
            be_values = waves_data[be_key]
        else:
            be_values = np.arange(len(waves_data[wave_name]))
        data_values = waves_data[wave_name]
        info = {'Sample ID': sample_info['sample_name'], 'Wave': wave_name,
                'Source File': os.path.basename(path)}
        result.spectra.append(_spectrum(sheet_name, be_values, data_values, info))
    return result


# ---------------------------------------------------------------------------
# DAT
# ---------------------------------------------------------------------------
def read_igor_dat(path):
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    if not lines:
        raise ValueError("File is empty")

    header = lines[0].strip().split('\t')
    samples_info = []
    seen_samples = set()

    all_data = {}
    for line in lines[1:]:
        if not line.strip():
            continue
        values = line.strip().split('\t')
        try:
            for col_idx in range(len(values)):
                if col_idx not in all_data:
                    all_data[col_idx] = []
                val = float(values[col_idx]) if col_idx < len(values) and values[col_idx] else 0.0
                all_data[col_idx].append(val)
        except (ValueError, IndexError):
            continue

    for i, h in enumerate(header):
        if not h.strip():
            continue

        match = re.search(_SAMPLE_PATTERN, h)
        if match:
            core_level_raw = match.group(1)
            sample_name = match.group(2)
            core_level = core_level_raw.replace(' ', '')

            if sample_name not in seen_samples:
                if 'bck' not in h.lower() and 'fitresult' not in h.lower() and 'peak' not in h.lower():
                    col_values = all_data.get(i, [])

                    if col_values and min(col_values) > 500:
                        be_col = i
                        data_col = i + 1
                        if data_col >= len(header) or data_col not in all_data:
                            continue
                    else:
                        data_col = i
                        be_col = None
                        for j in range(i - 1, -1, -1):
                            if not header[j].strip():
                                be_col = j
                                break
                        if be_col is None:
                            be_col = 0

                    samples_info.append({'sample_name': sample_name, 'core_level': core_level,
                                         'data_col': data_col, 'be_col': be_col})
                    seen_samples.add(sample_name)

    if not samples_info:
        raise ValueError("No valid sample data found in file")
    if not all_data:
        raise ValueError("No valid data found in file")

    result = ImportResult(source=path)
    for idx, sample_info in enumerate(samples_info):
        sheet_name = f"{sample_info['core_level']}{idx}"
        be_col = sample_info['be_col']
        data_col = sample_info['data_col']
        if be_col not in all_data or data_col not in all_data:
            # KherveFitting leaves this sheet with its headers only.
            result.dismissed.append((sheet_name, "no data column"))
            continue
        info = {'Sample ID': sample_info['sample_name'],
                'Source File': os.path.basename(path)}
        result.spectra.append(_spectrum(sheet_name, all_data[be_col], all_data[data_col], info))
    return result


def sniff_igor_dat(path):
    """What import_igor_dat_file needs: a tab-separated first line with an
    '[All <core level>] <sample>' column."""
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        first = f.readline()
    return any(re.search(_SAMPLE_PATTERN, h) for h in first.strip().split('\t'))


FORMATS = [
    Format(key="igor_itx", label="ITX file (.itx)", group="Igor",
           extensions=(".itx",), reader=read_igor_itx),
    Format(key="igor_dat", label="Data file (.dat)", group="Igor",
           extensions=(".dat",), reader=read_igor_dat, sniff=sniff_igor_dat, priority=10),
]
