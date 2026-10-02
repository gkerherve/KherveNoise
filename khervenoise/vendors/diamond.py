"""Diamond Light Source — ports of KherveFitting's Diamond_NXS_Import and
Diamond_B07_DAT_Import.

* **NeXus (.nxs, I09 / B07 / I10)** — ``detect``, ``read_xps``, ``read_xas``,
  ``_core_level_name``, ``guess_edge`` (verbatim) and the naming of
  ``import_nxs_files`` for one file: one spectrum per analyser region (XPS;
  slices summed, kinetic regions converted to BE), or TEY/I0, raw TEY, other
  channels and I0 (XAS, named ``XAS~<edge>~``, ``XAS~<edge>-TEY~`` …, on a
  photon-energy axis).  A core level met twice gets 1, 2 … appended.
  Interactive choice: XPS intensity in counts per second (counts / (step time
  x iterations)), KherveFitting's default.
* **B07 XPS (.dat)** — ``is_b07_xps_dat``, ``parse_name``, ``read_dat``,
  ``_core_level_name`` and ``plan_rows`` (verbatim), as
  ``import_b07_dat_files`` does for one file.  Interactive choice: "Average
  per scan" (intensity / number of scans), KherveFitting's default.

Both reproduce the **in-memory route** (``ConfigFile.build_core_level_Data``,
which the .kfit project uses): values are not rounded, non-finite points are
dropped (NeXus), and the Experimental Description KherveFitting builds is
kept as the spectrum's info.

h5py is needed for .nxs only and is imported lazily.

Copyright (C) 2026 Gwilherm Kerherve
Licensed under the GNU General Public License v3.0 (see LICENSE).
"""

import os
import re

import numpy as np

from ..document import make_spectrum
from ..importers import ImportResult, normalize_sheet_name, phi_region_base
from . import Format

XAS_X_LABEL = 'Photon Energy (eV)'

# Groups under /entry that are never spectra
_SKIP_GROUPS = {'instrument', 'before_scan', 'user01', 'analyser', 'sample',
                'diamond_scan', 'notes', 'ew4000', 'keys', 'monitor'}
_XPS_PAIRS = (('energies', 'spectrum_data'), ('binding_energy', 'spectrum'),
              ('energies', 'spectrum'))
_I0_NAMES = ('jI0', 'I0', 'i0', 'iI0', 'mirror_current', 'm4c1')
_TEY_NAMES = ('sdc', 'tey', 'TEY', 'drain_current')
_XAS_ENERGY_NAMES = ('jenergy', 'energy', 'pgmenergy', 'ienergy', 'dcmenergy')

# Absorption edges (eV) for naming an XAS sheet from its energy range
_EDGES = [
    ('C-K', 284), ('N-K', 400), ('Ti-L', 456), ('O-K', 531), ('V-L', 513),
    ('Cr-L', 575), ('Mn-L', 640), ('F-K', 685), ('Fe-L', 707), ('Co-L', 778),
    ('Ni-L', 853), ('Cu-L', 933), ('Zn-L', 1022), ('Na-K', 1071),
    ('Mg-K', 1303), ('Al-K', 1560), ('Si-K', 1839), ('P-K', 2146),
    ('S-K', 2472), ('Cl-K', 2822), ('K-K', 3608), ('Ca-K', 4038),
    ('Ce-M', 884), ('La-M', 836), ('Ba-M', 781), ('Sr-L', 1940),
]


# ---------------------------------------------------------------------------
# NeXus helpers (verbatim)
# ---------------------------------------------------------------------------
def _txt(value):
    if isinstance(value, bytes):
        return value.decode('utf-8', 'replace').strip()
    if isinstance(value, np.ndarray):
        flat = value.reshape(-1)
        return _txt(flat[0]) if flat.size else ''
    return str(value).strip()


def _scalar(h5, path):
    try:
        arr = np.asarray(h5[path][()]).reshape(-1)
        return float(arr[0]) if arr.size else None
    except (KeyError, TypeError, ValueError):
        return None


def _string(h5, path):
    try:
        return _txt(h5[path][()])
    except (KeyError, TypeError, ValueError):
        return ''


def _entry(h5):
    keys = list(h5.keys())
    for name in ('entry1', 'entry'):
        if name in keys:
            return name
    if not keys:
        raise ValueError("The NeXus file has no entry.")
    return keys[0]


def beamline_of(h5, entry):
    return (_string(h5, f'{entry}/instrument/beamline')
            or _string(h5, f'{entry}/instrument/name')).upper()


def _xps_regions(h5, entry):
    import h5py
    head = h5[entry]
    regions = []
    for name in head:
        if name in _SKIP_GROUPS or not isinstance(head[name], h5py.Group):
            continue
        group = head[name]
        for x_name, y_name in _XPS_PAIRS:
            if x_name in group and y_name in group:
                regions.append((name, x_name, y_name))
                break
    return regions


def _xas_channels(h5, entry):
    """{channel name: (energy array, data array)} of a jenergy-type scan."""
    import h5py
    found = {}
    for base in (entry, f'{entry}/instrument'):
        if base not in h5:
            continue
        for name, group in h5[base].items():
            if not isinstance(group, h5py.Group) or name in found or 'data' not in group:
                continue
            energy = None
            for e_name in _XAS_ENERGY_NAMES:
                if e_name in group:
                    energy = np.asarray(group[e_name][()], dtype=float).reshape(-1)
                    break
            if energy is None and f'{entry}/instrument/jenergy/value' in h5:
                energy = np.asarray(h5[f'{entry}/instrument/jenergy/value'][()],
                                    dtype=float).reshape(-1)
            data = np.asarray(group['data'][()])
            if energy is None or data.dtype.kind not in 'fiu':
                continue
            data = data.astype(float).reshape(-1)
            if data.size > 3 and energy.size == data.size:
                found[name] = (energy, data)
    return found


def detect(file_path):
    """'XPS', 'XAS' or None for a Diamond NeXus file."""
    try:
        import h5py
        with h5py.File(file_path, 'r') as h5:
            entry = _entry(h5)
            if _xps_regions(h5, entry):
                return 'XPS'
            channels = _xas_channels(h5, entry)
            if any(n in channels for n in _TEY_NAMES) or len(channels) >= 2:
                return 'XAS'
    except Exception:
        return None
    return None


def _core_level_name(region):
    """'O1s_2keV' -> 'O1s'; anything without an orbital keeps its name."""
    m = re.search(r'([A-Z][a-z]?\d[spdf]\d?)', region)
    return normalize_sheet_name(phi_region_base(m.group(1))) if m else region


def read_xps(file_path, cps=True):
    import h5py
    records = []
    with h5py.File(file_path, 'r') as h5:
        entry = _entry(h5)
        beamline = beamline_of(h5, entry)
        sample = _string(h5, f'{entry}/sample/name')
        for region, x_name, y_name in _xps_regions(h5, entry):
            g = h5[f'{entry}/{region}']
            ins = f'{entry}/instrument/{region}'
            x = np.asarray(g[x_name][()], dtype=float).reshape(-1)
            y = np.asarray(g[y_name][()], dtype=float)
            if y.ndim > 1:                          # slices / angles: sum them
                y = y.reshape(-1, y.shape[-1]).sum(axis=0)
            n = min(x.size, y.size)
            x, y = x[:n], y[:n]

            hv = (_scalar(h5, f'{entry}/{region}/excitation_energy')
                  or _scalar(h5, f'{ins}/excitation_energy')
                  or _scalar(h5, f'{ins}/photon_energy'))
            mode = _string(h5, f'{ins}/energy_mode') or 'Binding'
            if mode.lower().startswith('kin') and hv:
                x = hv - x                           # KE -> BE
            step = (_scalar(h5, f'{ins}/step_time') or _scalar(h5, f'{ins}/count_time'))
            iters = _scalar(h5, f'{ins}/number_of_iterations') or 1.0
            scale = 1.0
            if cps and step:
                scale = 1.0 / (step * iters)
            y = y * scale

            exp = {
                'Sample ID': sample if sample and sample != 'Not set' else
                os.path.splitext(os.path.basename(file_path))[0],
                'Technique': 'XPS',
                'Instrument': f"Diamond {beamline}".strip(),
                'Region Name': region,
                'Species & Transition': region,
                'Source Label': 'Synchrotron',
                'Source Energy': f"{hv:.2f}" if hv else '',
                'Excitation Energy': f"{hv:.2f}" if hv else '',
                'Pass Energy': _txt(h5[f'{ins}/pass_energy'][()]) if f'{ins}/pass_energy' in h5 else '',
                'Lens Mode': _string(h5, f'{ins}/lens_mode'),
                'Acquisition Mode': _string(h5, f'{ins}/acquisition_mode'),
                'Energy Mode': mode,
                'Step Time': f"{step:g}" if step else '',
                'Number of scans': f"{iters:g}",
                'Intensity': ('counts per second (counts / (step time x iterations))'
                              if scale != 1.0 else 'raw counts'),
                'Date': _string(h5, f'{entry}/diamond_scan/start_time')[:10],
                'Experiment': _string(h5, f'{entry}/experiment_identifier'),
                'Scan': _string(h5, f'{entry}/diamond_scan/entry_identifier'),
                'Source File': os.path.basename(file_path),
            }
            records.append({'name': _core_level_name(region), 'x': x, 'y': y, 'exp': exp})
    return records


def guess_edge(energy):
    """Absorption edge label for an XAS energy range ('O-K'), or ''."""
    lo, hi = float(np.nanmin(energy)), float(np.nanmax(energy))
    inside = [(abs(e - (lo + 0.2 * (hi - lo))), name) for name, e in _EDGES if lo - 5 <= e <= hi]
    return min(inside)[1] if inside else ''


def read_xas(file_path):
    import h5py
    with h5py.File(file_path, 'r') as h5:
        entry = _entry(h5)
        beamline = beamline_of(h5, entry)
        channels = _xas_channels(h5, entry)
        base_exp = {
            'Sample ID': os.path.splitext(os.path.basename(file_path))[0],
            'Technique': 'XAS',
            'Instrument': f"Diamond {beamline}".strip(),
            'Polarisation': _string(h5, f'{entry}/instrument/polarisation/value'),
            'Date': _string(h5, f'{entry}/diamond_scan/start_time')[:10],
            'Experiment': _string(h5, f'{entry}/experiment_identifier'),
            'Scan': _string(h5, f'{entry}/diamond_scan/entry_identifier'),
            'Scan Command': _string(h5, f'{entry}/diamond_scan/scan_command'),
            'Source File': os.path.basename(file_path),
        }
    i0_name = next((n for n in _I0_NAMES if n in channels), None)
    tey_name = next((n for n in _TEY_NAMES if n in channels), None)
    if not channels:
        return [], ''
    energy = channels[tey_name or next(iter(channels))][0]
    if np.nanmax(energy) < 20:                     # keV -> eV
        energy = energy * 1000.0
    edge = guess_edge(energy)
    order = np.argsort(energy)
    energy = energy[order]
    i0 = channels[i0_name][1][order] if i0_name else None

    def norm(sig):
        with np.errstate(divide='ignore', invalid='ignore'):
            return np.where(i0 != 0, sig / i0, np.nan)

    records = []
    label = edge or 'XAS'
    for name, (_e, data) in channels.items():
        if name == i0_name:
            continue
        data = data[order]
        tag = 'TEY' if name == tey_name else name
        if i0 is not None:
            records.append({'name': f"XAS~{label}~" if name == tey_name else f"XAS~{label}-{tag}-norm~",
                            'x': energy, 'y': norm(data),
                            'exp': dict(base_exp, **{'Signal': f'{tag} / I0 ({name} / {i0_name})',
                                                     'Species & Transition': label})})
        records.append({'name': f"XAS~{label}-{tag}~", 'x': energy, 'y': data,
                        'exp': dict(base_exp, **{'Signal': f'{tag} raw ({name})',
                                                 'Species & Transition': label})})
    if i0 is not None:
        records.append({'name': f"XAS~{label}-I0~", 'x': energy, 'y': i0,
                        'exp': dict(base_exp, **{'Signal': f'I0 ({i0_name})',
                                                 'Species & Transition': label})})
    return records, edge


def _row_name(base, row):
    """Sheet name for Sample Manager row ``row`` (0 = the bare name)."""
    return base if row == 0 else f"{base}{row}"


def read_nxs(path):
    """import_nxs_files for one file, counts per second (the default)."""
    kind = detect(path)
    if kind is None:
        raise ValueError("Not a Diamond XPS/XAS NeXus file (no analyser region "
                         "and no jenergy/TEY scan found).")
    if kind == 'XPS':
        records = read_xps(path, cps=True)
    else:
        records, _edge = read_xas(path)

    paths_count, row = 1, 0
    core_levels = {}
    seen = {}
    for rec in records:
        base = rec['name']
        k = seen.get(base, 0)
        seen[base] = k + 1
        name = _row_name(base, row + k * paths_count) if k else _row_name(base, row)
        y = np.asarray(rec['y'], dtype=float)
        ok = np.isfinite(y)
        x_label = XAS_X_LABEL if kind == 'XAS' else None
        core_levels[name] = make_spectrum(name, np.asarray(rec['x'])[ok], y[ok],
                                          info=rec['exp'], x_label=x_label)
    result = ImportResult(source=path, spectra=list(core_levels.values()))
    if not result.spectra:
        raise ValueError("No spectra found in the selected file(s).")
    return result


def sniff_nxs(path):
    return detect(path) is not None


# ---------------------------------------------------------------------------
# B07 XPS .dat (verbatim)
# ---------------------------------------------------------------------------
HEADER_X = 'binding_energy'
HEADER_Y = 'intensity'


def is_b07_xps_dat(path):
    """A B07 XPS text export: a .dat whose first line is the binding_energy /
    intensity header."""
    if not path.lower().endswith('.dat'):
        return False
    try:
        with open(path, 'r', errors='replace') as fh:
            head = fh.readline().strip().lower().split('\t')
    except OSError:
        return False
    return len(head) >= 2 and head[0] == HEADER_X and head[1] == HEADER_Y


def parse_name(path):
    """File-name fields: scan, region, temperature, condition, pass energy,
    photon energy, and the condition tags as written."""
    stem = os.path.splitext(os.path.basename(path))[0]
    tok = stem.split('_')
    scan_nums = re.findall(r'\d+', tok[0]) if tok else []
    scan = int(scan_nums[-1]) if scan_nums else None
    region = tok[1] if len(tok) > 1 else stem
    rest = [t for t in tok[2:] if t.upper() != 'XPS']
    pe = next((float(m.group(1)) for t in rest
               for m in [re.fullmatch(r'PE(\d+(?:\.\d+)?)', t, re.I)] if m), None)
    nums = [int(t) for t in rest if t.isdigit()]
    temp = nums[0] if nums else None
    hv = nums[-1] if len(nums) >= 2 else None        # a lone number is the temperature
    cond = next((t.upper() for t in rest if re.fullmatch(r'[Dd]\d+', t)), '')
    tags = [t for t in rest if not re.fullmatch(r'PE\d+(?:\.\d+)?', t, re.I)
            and not re.fullmatch(r'\d+min', t, re.I) and t != str(hv)]
    extra = [t for t in rest if not t.isdigit() and not re.fullmatch(r'[Dd]\d+', t)
             and not re.fullmatch(r'PE\d+(?:\.\d+)?', t, re.I) and not re.fullmatch(r'\d+min', t, re.I)]
    label = ' '.join(t for t in ([str(temp)] if temp is not None else []) + ([cond] if cond else []) + extra) or stem
    return {'scan': scan, 'region': region, 'temp': temp, 'cond': cond, 'pe': pe,
            'hv': hv, 'tags': '_'.join(tags), 'label': label, 'stem': stem}


def read_dat(path, average=False):
    """(BE descending, intensity, number of scans)."""
    data = np.genfromtxt(path, delimiter='\t', names=True, dtype=float, encoding='utf-8')
    names = [n.lower() for n in data.dtype.names]
    x = np.asarray(data[data.dtype.names[names.index(HEADER_X)]], dtype=float)
    y = np.asarray(data[data.dtype.names[names.index(HEADER_Y)]], dtype=float)
    n_scans = sum(1 for n in names if n.startswith('spectrum'))
    if average and n_scans:
        y = y / n_scans
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    order = np.argsort(x)[::-1]                        # descending BE
    return x[order], y[order], n_scans


def _b07_core_level_name(region):
    """Diamond_B07_DAT_Import._core_level_name."""
    if region.lower().startswith('survey'):
        return 'Survey'
    m = re.search(r'([A-Z][a-z]?\d[spdf]\d?)', region)
    return normalize_sheet_name(phi_region_base(m.group(1))) if m else region


def _row_label(meta):
    return f"{meta['label']} - {meta['hv']} eV" if meta['hv'] else meta['label']


def plan_rows(metas):
    """Row index for every file: one row per (condition, photon energy), in
    scan order; a core level already in that row starts another row for the
    same condition and energy. Returns (row per file, label per row)."""
    rows = []                                         # [key, label, set of core levels]
    assign = []
    for meta in metas:
        key = (meta['temp'], meta['cond'], meta['hv']) if meta['hv'] or meta['cond'] else meta['stem']
        name = _b07_core_level_name(meta['region'])
        target = next((i for i, r in enumerate(rows) if r[0] == key and name not in r[2]), None)
        if target is None:
            repeat = sum(1 for r in rows if r[0] == key)
            label = _row_label(meta) + (f" ({repeat + 1})" if repeat else "")
            rows.append([key, label, set()])
            target = len(rows) - 1
        rows[target][2].add(name)
        assign.append(target)
    return assign, [r[1] for r in rows]


def read_b07_dat(path, average=True):
    """import_b07_dat_files for one file, average per scan (the default)."""
    if not is_b07_xps_dat(path):
        raise ValueError("Not a Diamond B07 XPS .dat file (first line must be "
                         "'binding_energy<TAB>intensity...').")
    metas = [parse_name(path)]
    rows, labels = plan_rows(metas)
    meta, row = metas[0], rows[0]
    x, y, n_scans = read_dat(path, average=average)
    base = _b07_core_level_name(meta['region'])
    name = base if row == 0 else f"{base}{row}"
    hv = meta['hv']
    exp = {
        'Sample ID': labels[row],
        'Technique': 'XPS',
        'Instrument': 'Diamond B07',
        'Region Name': meta['region'],
        'Species & Transition': meta['region'],
        'Source Label': 'Synchrotron',
        'Source Energy': f"{hv:.2f}" if hv else '',
        'Excitation Energy': f"{hv:.2f}" if hv else '',
        'Pass Energy': f"{meta['pe']:g}" if meta['pe'] is not None else '',
        'Number of scans': str(n_scans),
        'Intensity': ('average per scan (intensity / number of scans)' if average
                      else 'sum of the scans (file intensity column)'),
        'Scan': str(meta['scan'] or ''),
        'Condition': meta['tags'],
        'Source File': os.path.basename(path),
    }
    result = ImportResult(source=path)
    result.spectra.append(make_spectrum(name, x, y, info=exp))
    return result


FORMATS = [
    Format(key="diamond_nxs", label="NeXus (I09 / B07 / I10) (.nxs)",
           group="Diamond Light Source", extensions=(".nxs",), reader=read_nxs,
           sniff=sniff_nxs, priority=10),
    Format(key="diamond_b07", label="B07 XPS (.dat)", group="Diamond Light Source",
           extensions=(".dat",), reader=read_b07_dat, sniff=is_b07_xps_dat, priority=10),
]
