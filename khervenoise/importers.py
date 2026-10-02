"""File import — VAMAS, Excel and plain data files.  Qt-free.

Each reader reproduces what KherveFitting does with the same file, so a
spectrum lands here with the same x / y values it would have there:

* **VAMAS (.vms)** — ``Vamas_Import.open_vamas_file``: one spectrum per
  block, blocks with 0 scans skipped, KE converted to BE with the block's
  own photon energy, counts divided by scans x dwell time and by the
  transmission, Auger / valence-band / survey names normalised.  As in
  KherveFitting, the transmission-corrected trace is what the denoiser sees
  ('Raw Data'); the uncorrected counts are kept as 'Corrected Data'.
* **Excel (.xlsx / .xls)** — ``Open.open_xlsx_file`` +
  ``ConfigFile.add_core_level_Data``: one spectrum per sheet whose row-1
  headers are a KherveFitting pair (Binding Energy + Raw Data, Wavenumber +
  Intensity …), generic ``Sheet1`` names and the "Results Table" /
  "Experimental Description" sheets dismissed, values kept to 2 decimals.
  A workbook with no KherveFitting sheet at all falls back to "first two
  numeric columns of every sheet" (KherveFitting asks interactively there).
* **Instrument formats** — Avantage, VGD, AVG, Kratos, PHI, Scienta, MRS,
  VG-Microtech, Igor, Diamond and SDP live in ``khervenoise.vendors``; an
  instrument format that recognises a file is tried first.
* **Data files (.asc, .txt, .dat, .xy, .csv)** —
  ``XPS_ASC_CSV_Import``: two numeric columns separated by ';', ',' or
  whitespace, '#' comments skipped, one spectrum named after the file.

Every reader returns ``ImportResult(spectra, dismissed, source)``.

Copyright (C) 2026 Gwilherm Kerherve
Licensed under the GNU General Public License v3.0 (see LICENSE).
"""

import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field

from .document import make_spectrum

#: KherveFitting reads every Excel / ASC / CSV value back with '.2f'
#: rounding (add_core_level_Data). Kept so a spectrum denoises to the very
#: same numbers in both programs.
ROUND_LIKE_KHERVEFITTING = True

#: KherveFitting's defaults for the KE -> BE conversion.
WORK_FUNCTION = 0.0

EXCEL_EXT = ('.xlsx', '.xlsm', '.xls')
VAMAS_EXT = ('.vms', '.npl')
DATA_EXT = ('.asc', '.txt', '.dat', '.xy', '.csv', '.tsv')
ALL_EXT = EXCEL_EXT + VAMAS_EXT + DATA_EXT

FILTER_EXCEL = "Excel files (*.xlsx *.xlsm *.xls)"
FILTER_VAMAS = "VAMAS files (*.vms *.npl)"
FILTER_DATA = "Data files (*.asc *.txt *.dat *.xy *.csv *.tsv)"


@dataclass
class ImportResult:
    spectra: list = field(default_factory=list)
    dismissed: list = field(default_factory=list)      # (name, reason)
    source: str = ""


def _r2(v):
    return float(f"{float(v):.2f}") if ROUND_LIKE_KHERVEFITTING else float(v)


# ---------------------------------------------------------------------------
# Sheet-name normalisation (KherveFitting Open.py / Vamas_Import.py)
# ---------------------------------------------------------------------------
_SPIN_ORBIT_DIGITS = {'p': '13', 'd': '35', 'f': '57'}


def phi_region_base(name):
    """'Fe2p3' -> 'Fe2p' (a 2p3/2 window, not sample row 3)."""
    m = re.match(r'^([A-Z][a-z]?\d[pdf])(\d)$', str(name).strip())
    if m and m.group(2) in _SPIN_ORBIT_DIGITS[m.group(1)[-1]]:
        return m.group(1)
    return name


def normalize_sheet_name(name):
    """Normalize a core level name to KherveFitting's standard format."""
    new_name = name
    lower_name = name.lower()
    if 'survey' in lower_name:
        new_name = 'Survey'
    elif 'wide' in lower_name:
        new_name = 'Wide'
    elif 'su1s' in lower_name or '_su' in lower_name or name.lower().endswith('_su'):
        new_name = 'Survey'
    elif any(term in lower_name for term in ['valence', 'valence band', 'valence scan',
                                             'vb scan', 'vb', 'valence band scan']):
        new_name = 'VB'
    elif any(term in lower_name for term in ['fermi', 'fermi scan']):
        new_name = 'Fermi'
    else:
        match = re.search(r'([A-Z][a-z]?)\s+(\d+[spdf])', name)
        if match:
            element, orbital = match.groups()
            new_name = f"{element}{orbital}"
        match = re.search(r'([A-Z][a-z]?\d+[spdf])', new_name)
        if match and len(new_name) > len(match.group(1)):
            new_name = match.group(1)
    suffix_match = re.search(r'(\d+)$', name)
    if suffix_match and not re.search(r'\d+$', new_name):
        new_name = f"{new_name}{suffix_match.group(1)}"
    return new_name


def normalize_auger_and_valence_names(sheet_name):
    """'Fe LM2' -> 'Felmm', 'C KL1' -> 'Ckll', 'V.B.' -> 'VB'."""
    if re.match(r'^V\.?B\.?\s*$', sheet_name.strip(), re.IGNORECASE):
        return "VB"
    match = re.match(r'^([A-Z][a-z]?)\s+([A-Z]+\d*)$', sheet_name.strip())
    if match:
        element, auger_part = match.group(1), match.group(2)
        letters = re.sub(r'\d+', '', auger_part).lower()
        if len(letters) >= 2:
            letters += letters[-1]
        return f"{element}{letters}"
    return sheet_name


# ---------------------------------------------------------------------------
# VAMAS
# ---------------------------------------------------------------------------
VAMAS_EXP_LABELS = [
    "Sample ID", "Date", "Time", "Technique", "Species & Transition", "Number of scans",
    "Source Label", "Source Energy", "Source width X", "Source width Y", "Pass Energy",
    "Work Function", "Analyzer Mode", "Sputtering Energy", "Take-off Polar Angle",
    "Take-off Azimuth", "Target Bias", "Analysis Width X", "Analysis Width Y", "X Label",
    "X Units", "X Start", "X Step", "Num Y Values", "Num Scans", "Collection Time",
    "Time Correction", "Y Unit", "Block Comment",
]


def read_vamas(path, work_function=WORK_FUNCTION):
    """Spectra of a VAMAS file, processed as KherveFitting does."""
    from vamas import Vamas
    if not os.path.exists(path):
        raise FileNotFoundError(f"The file {path} does not exist.")
    temp_dir = None
    read_path = path
    # The parser only accepts a lowercase ".vms" extension.
    if not read_path.endswith('.vms'):
        temp_dir = tempfile.mkdtemp(prefix='knoise_vamas_')
        read_path = os.path.join(temp_dir, os.path.splitext(os.path.basename(path))[0] + '.vms')
        shutil.copy2(path, read_path)
    try:
        vamas_data = Vamas(read_path)
    finally:
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)

    result = ImportResult(source=path)
    taken = set()
    for i, block in enumerate(vamas_data.blocks, start=1):
        if block.num_scans_to_compile_block == 0:
            result.dismissed.append((block.species_label, "0 scans"))
            continue
        if block.species_label.lower() == "wide" or \
                block.transition_or_charge_state_label.lower() == "none":
            raw_name = block.species_label
        else:
            raw_name = f"{block.species_label}{block.transition_or_charge_state_label}"
        raw_name = normalize_auger_and_valence_names(raw_name.replace("/", "_"))
        name = normalize_sheet_name(phi_region_base(raw_name))
        if name in taken:
            count = 1
            while f"{name}{count}" in taken:
                count += 1
            name = f"{name}{count}"
        taken.add(name)

        num_points = block.num_y_values
        x_values = [block.x_start + j * block.x_step for j in range(num_points)]
        y_values = block.corresponding_variables[0].y_values
        y_unit = block.corresponding_variables[0].unit
        num_scans = block.num_scans_to_compile_block
        try:
            collection_time = getattr(block, 'signal_collection_time', None)
            if collection_time is None:
                collection_time = getattr(block, 'dwell_time', None)
            if collection_time is None:
                collection_time = 1.0
        except (AttributeError, TypeError):
            collection_time = 1.0
        if y_unit != "c/s" and collection_time > 0:
            y_values = [y / (num_scans * collection_time) for y in y_values]
        elif y_unit != "c/s":
            y_values = [y / num_scans for y in y_values]

        if block.x_label.lower() in ["kinetic energy", "ke"]:
            photon_energy = block.analysis_source_characteristic_energy
            x_values = [photon_energy - x - work_function for x in x_values]
            x_label = "Binding Energy"
        else:
            x_label = block.x_label

        if len(block.corresponding_variables) > 1:
            raw_t = block.corresponding_variables[1].y_values
            if collection_time > 0:
                transmission = [t / (num_scans * collection_time) for t in raw_t]
            else:
                transmission = [t / num_scans for t in raw_t]
        else:
            if collection_time > 0:
                transmission = [1.0 / (num_scans * collection_time)] * len(y_values)
            else:
                transmission = [1.0 / num_scans] * len(y_values)

        n = min(len(x_values), len(y_values))
        x_values, y_values = x_values[:n], y_values[:n]
        trans = [transmission[j] if j < len(transmission) else 1.0 for j in range(n)]
        if collection_time > 0:
            corrected = [(y / abs(t)) / (num_scans * collection_time)
                         for y, t in zip(y_values, trans)]
        else:
            corrected = [(y / abs(t)) / num_scans for y, t in zip(y_values, trans)]

        info = dict(zip(VAMAS_EXP_LABELS, [
            block.sample_identifier,
            f"{block.year}/{block.month}/{block.day}",
            f"{block.hour}:{block.minute}:{block.second}",
            block.technique,
            f"{block.species_label} {block.transition_or_charge_state_label}",
            num_scans, block.analysis_source_label,
            block.analysis_source_characteristic_energy,
            block.analysis_source_beam_width_x, block.analysis_source_beam_width_y,
            block.analyzer_pass_energy_or_retard_ratio_or_mass_res,
            block.analyzer_work_function_or_acceptance_energy, block.analyzer_mode,
            getattr(block, 'sputtering_source_energy', 'N/A'),
            block.analyzer_axis_take_off_polar_angle,
            block.analyzer_axis_take_off_azimuth, block.target_bias,
            block.analysis_width_x, block.analysis_width_y, block.x_label,
            block.x_units, block.x_start, block.x_step, block.num_y_values,
            num_scans, block.signal_collection_time, block.signal_time_correction,
            y_unit, block.block_comment]))
        info['Block'] = f"Block {i}"
        label = None if x_label.lower().startswith('binding') else f"{x_label} ({block.x_units})"
        sp = make_spectrum(name, x_values, corrected, raw=y_values,
                           transmission=trans, info=info, x_label=label)
        result.spectra.append(sp)
    return result


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------
_SPECIAL_SHEETS = ("results table", "experimental description")


def _header_kind(col1, col2):
    """Does a row-1 header pair look like a KherveFitting sheet?"""
    c1, c2 = str(col1).strip().upper(), str(col2).strip().upper()
    xps = (('BE' in c1 or 'B.E.' in c1 or 'BINDING' in c1)
           and ('RAW DATA' in c2 or 'CORRECTED DATA' in c2 or 'INTENSITY' in c2))
    raman = ('WAVENUMBER' in c1 or 'CM-1' in c1) and ('RAW DATA' in c2 or 'INTENSITY' in c2)
    xas = ('ENERGY' in c1 or 'PHOTON ENERGY' in c1) and ('INTENSITY' in c2 or 'RAW DATA' in c2)
    eels = 'ENERGY' in c1 and ('EV' in c1 or 'LOSS' in c1) and 'INTENSITY' in c2
    return xps or raman or xas or eels


def _sheet_spectrum(df, name):
    """add_core_level_Data's standard path: A=x, B=Raw Data, C=Corrected
    Data, D=Transmission, header row skipped, '.2f' kept."""
    import pandas as pd
    xs, ys, cs, ts = [], [], [], []
    for index, row in df.iterrows():
        if index == 0:
            continue
        be_val, raw_val = row.iloc[0], row.iloc[1]
        if pd.isna(be_val) or pd.isna(raw_val):
            continue
        try:
            x, y = float(be_val), float(raw_val)
            c = float(row.iloc[2]) if len(row) > 2 and not pd.isna(row.iloc[2]) else y
            t = float(row.iloc[3]) if len(row) > 3 and not pd.isna(row.iloc[3]) else 1.0
        except (ValueError, TypeError):
            continue
        xs.append(x); ys.append(y); cs.append(c); ts.append(t)
    header = str(df.iloc[0, 0]).strip() if len(df) else ''
    label = None
    if header and not re.search(r'binding|\bbe\b|b\.e\.', header, re.I) \
            and header.lower() not in ('nan',):
        label = header
    return make_spectrum(name, [_r2(v) for v in xs], [_r2(v) for v in ys],
                         raw=[_r2(v) for v in cs], transmission=[_r2(v) for v in ts],
                         x_label=label)


def _experimental_info(path, sheet_name):
    """The 'Experimental Description' block KherveFitting writes at column
    40-60 of a sheet (VAMAS-built workbooks)."""
    if not path.lower().endswith(('.xlsx', '.xlsm')):
        return {}
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=False, data_only=True)
    except Exception:
        return {}
    info = {}
    try:
        if sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            exp_col = None
            for col in range(40, min(61, ws.max_column + 1)):
                v = ws.cell(row=1, column=col).value
                if v and "Experimental Description" in str(v):
                    exp_col = col
                    break
            if exp_col:
                for r in range(2, ws.max_row + 1):
                    p = ws.cell(row=r, column=exp_col).value
                    if p is not None and str(p).strip():
                        v = ws.cell(row=r, column=exp_col + 1).value
                        info[str(p).strip()] = '' if v is None else str(v).strip()
    finally:
        wb.close()
    return info


def _numeric_pairs(df):
    """First two mostly-numeric columns of a header-less sheet, for the
    generic fallback."""
    import pandas as pd
    num = df.apply(pd.to_numeric, errors='coerce')
    cols = [c for c in num.columns if num[c].notna().sum() >= 4]
    if len(cols) < 2:
        return None
    sub = num[[cols[0], cols[1]]].dropna()
    return sub.iloc[:, 0].tolist(), sub.iloc[:, 1].tolist()


def read_excel(path):
    import pandas as pd
    result = ImportResult(source=path)
    excel = pd.ExcelFile(path)
    names = [n for n in excel.sheet_names if n.lower() not in _SPECIAL_SHEETS]
    frames = {}
    for name in names:
        try:
            frames[name] = pd.read_excel(excel, sheet_name=name, header=None)
        except Exception as exc:  # noqa: BLE001
            result.dismissed.append((name, f"unreadable ({exc})"))

    for name, df in frames.items():
        if re.match(r'^Sheet\d+$', name, re.IGNORECASE):
            continue                              # judged below
        if df.shape[0] == 0 or df.shape[1] < 2:
            result.dismissed.append((name, "fewer than 2 columns or no data"))
            continue
        if not (_header_kind(df.iloc[0, 0], df.iloc[0, 1])
                or not _xps_named(name)):
            result.dismissed.append((name, "unrecognised column headers (Col1='"
                                     f"{str(df.iloc[0, 0]).strip()}', Col2='"
                                     f"{str(df.iloc[0, 1]).strip()}')"))
            continue
        sp = _sheet_spectrum(df, name)
        if len(sp['B.E.']) < 2:
            result.dismissed.append((name, "no numeric data"))
            continue
        info = _experimental_info(path, name)
        if info:
            sp['ExperimentalInfo'] = info
        result.spectra.append(sp)

    generic = [n for n in frames if re.match(r'^Sheet\d+$', n, re.IGNORECASE)]
    if result.spectra:
        for n in generic:
            result.dismissed.append((n, "default Excel name (e.g. Sheet1)"))
        return result

    # No KherveFitting sheet at all: first two numeric columns per sheet.
    result.dismissed = []
    base = os.path.splitext(os.path.basename(path))[0]
    for name, df in frames.items():
        pair = _numeric_pairs(df)
        if pair is None:
            result.dismissed.append((name, "no two numeric columns"))
            continue
        label = name if not re.match(r'^(Sheet|Feuil|Tabelle|Hoja)\d*$', name, re.IGNORECASE) else \
            (base if len(frames) == 1 else f"{base}_{name}")
        result.spectra.append(make_spectrum(label, [_r2(v) for v in pair[0]],
                                            [_r2(v) for v in pair[1]]))
    return result


def _xps_named(name):
    from .document import is_xps_like
    return is_xps_like(name)


# ---------------------------------------------------------------------------
# Data files (ASC / TXT / DAT / XY / CSV)
# ---------------------------------------------------------------------------
def _base_name(path):
    # KherveFitting: os.path.basename(file_path).split('.')[0]
    return os.path.basename(path).split('.')[0] or "Spectrum"


def read_asc(path):
    """XPS_ASC_CSV_Import.import_xps_asc_file_direct."""
    data = []
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            if line.strip() and not line.startswith('#'):
                if ';' in line:
                    parts = line.strip().split(';')
                elif ',' in line:
                    parts = line.strip().split(',')
                else:
                    parts = line.strip().split()
                if len(parts) >= 2:
                    try:
                        data.append([float(parts[0]), float(parts[1])])
                    except ValueError:
                        continue
    result = ImportResult(source=path)
    if not data:
        result.dismissed.append((_base_name(path), "No valid data found in the file."))
        return result
    xs = [float(f"{x:.2f}") for x, _y in data]
    ys = [float(f"{y:.2f}") for _x, y in data]
    result.spectra.append(make_spectrum(_base_name(path), xs, ys))
    return result


def read_csv(path):
    """XPS_ASC_CSV_Import.import_xps_csv_file (first two columns)."""
    import pandas as pd
    try:
        df = pd.read_csv(path, delimiter=',', header=None)
    except Exception:  # noqa: BLE001
        df = pd.DataFrame()
    if df.shape[1] < 2:
        for sep in [';', '\t', r'\s+']:
            try:
                test = pd.read_csv(path, sep=sep, header=None, engine='python')
            except Exception:  # noqa: BLE001
                continue
            if test.shape[1] >= 2:
                df = test
                break
    result = ImportResult(source=path)
    if df.shape[1] < 2:
        result.dismissed.append((_base_name(path),
                                 "CSV file must contain at least two columns "
                                 "(BE and Intensity)."))
        return result
    num = df.iloc[:, :2].apply(pd.to_numeric, errors='coerce').dropna()
    if len(num) == 0:
        result.dismissed.append((_base_name(path), "No valid data found in the file."))
        return result
    result.spectra.append(make_spectrum(_base_name(path),
                                        [_r2(v) for v in num.iloc[:, 0]],
                                        [_r2(v) for v in num.iloc[:, 1]]))
    return result


def read_data_file(path):
    if path.lower().endswith(('.csv', '.tsv')):
        res = read_csv(path)
        if res.spectra:
            return res
    return read_asc(path)


# ---------------------------------------------------------------------------
def vendor_formats(path):
    """Instrument formats (``khervenoise.vendors``) that claim *path*."""
    from . import vendors
    return vendors.formats_for(path)


def kind_of(path):
    low = str(path).lower()
    if vendor_formats(path):
        return "vendor"
    if low.endswith(EXCEL_EXT):
        return "excel"
    if low.endswith(VAMAS_EXT):
        return "vamas"
    if low.endswith(DATA_EXT):
        return "data"
    return None


def read_any(path):
    """Dispatch on the extension (and content, for shared extensions such
    as .xlsx / .txt / .dat), as KherveFitting's drop handler does: an
    instrument format that recognises the file wins, then Excel, VAMAS and
    plain data files."""
    fmts = vendor_formats(path)
    if fmts:
        return fmts[0].reader(path)
    kind = kind_of(path)
    if kind == "excel":
        return read_excel(path)
    if kind == "vamas":
        return read_vamas(path)
    if kind == "data":
        return read_data_file(path)
    raise ValueError(f"Unsupported file type: {os.path.basename(path)}")


def notice_for(path):
    """A third-party notice to show before importing *path* ('' if none)."""
    fmts = vendor_formats(path)
    return fmts[0].notice if fmts else ""


def all_extensions():
    from . import vendors
    exts = list(ALL_EXT)
    for e in vendors.extensions():
        if e not in exts:
            exts.append(e)
    return exts


def filter_all():
    pats = " ".join(f"*{e}" for e in (".knoise",) + tuple(all_extensions()))
    return f"All supported ({pats})"


def filter_instruments():
    from . import vendors
    pats = " ".join(f"*{e}" for e in vendors.extensions())
    return f"Instrument files ({pats})"
