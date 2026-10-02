"""Run the MCP tools against the live KherveNoise window.

Each ``_t_<name>`` handles one entry of ``mcp_schema.TOOLS``.  They run on
the GUI thread (the bridge calls them from its socket handler) and must
never open a modal dialog — a QMessageBox nobody asked for would freeze the
app, so they use the window's dialog-free entry points.

Copyright (C) 2026 Gwilherm Kerherve
Licensed under the GNU General Public License v3.0 (see LICENSE).
"""

import base64
import io
import os

import numpy as np

from . import __version__, engine
from .document import axis_labels
from .mcp_schema import check_args


def _decimate(values, max_points):
    values = list(values)
    if len(values) <= max_points:
        return values
    idx = np.linspace(0, len(values) - 1, max_points).round().astype(int)
    return [values[i] for i in idx]


def _clean(obj):
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, float) and not np.isfinite(obj):
        return None if np.isnan(obj) else ("inf" if obj > 0 else "-inf")
    return obj


class McpToolExecutor:
    def __init__(self, window):
        self._w = window

    @property
    def doc(self):
        return self._w.document

    @property
    def panel(self):
        return self._w.panel

    def execute(self, name, args):
        args = args or {}
        err = check_args(name, args)
        if err:
            return {"error": err}
        handler = getattr(self, f"_t_{name}", None)
        if handler is None:
            return {"error": f"Tool {name!r} is not implemented."}
        try:
            return _clean(handler(**args))
        except _ToolError as exc:
            return {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"{type(exc).__name__}: {exc}"}

    # ── helpers ─────────────────────────────────────────────────
    def _spectrum(self, name):
        sp = self.doc.get(name)
        if sp is None:
            raise _ToolError(f"No spectrum named {name!r}. Known: "
                             f"{', '.join(self.doc.names()) or '(none)'}.")
        return sp

    def _params(self, method, params, x=None, y=None, auto=False):
        method = method or self.panel.method
        if method not in engine.METHODS:
            raise _ToolError(f"method must be one of {engine.METHODS}")
        if auto:
            return engine.auto_params(x, y, method, self.panel._held_controls())
        base = (self.panel.active_params() if method == self.panel.method
                else engine.full_params(method))
        base.update({k: v for k, v in (params or {}).items() if v is not None})
        base.pop('method', None)
        p = engine.full_params(method, **base)
        if method == "VMD" and p['keep'] > p['K']:
            raise _ToolError("keep cannot exceed K.")
        return p

    def _names(self, names):
        if not names:
            return self.doc.usable_names()
        missing = [n for n in names if self.doc.get(n) is None]
        if missing:
            raise _ToolError(f"Unknown spectra: {', '.join(missing)}")
        return list(names)

    # ── read ────────────────────────────────────────────────────
    def _t_get_project_info(self):
        rows = []
        for name, sp in self.doc.spectra.items():
            x = sp.get('B.E.') or []
            row = {"name": name, "points": len(x),
                   "x_min": min(x) if x else None, "x_max": max(x) if x else None,
                   "x_label": axis_labels(name, sp)[0]}
            if sp.get('Denoise'):
                row["denoised_from"] = sp['Denoise'].get('source')
                row["params"] = sp['Denoise'].get('params')
            rows.append(row)
        return {"app": "KherveNoise", "version": __version__,
                "file": self.doc.path, "imported_from": self.doc.source,
                "unsaved_changes": bool(self.doc.dirty),
                "on_screen": self.panel.current_sheet,
                "method": self.panel.method,
                "params": self.panel.active_params() if self.panel.x is not None else None,
                "ticked_for_create": self.panel.checked_names(),
                "spectra": rows}

    def _t_list_methods(self):
        return {"methods": {
            "VMD": {"what": "Variational Mode Decomposition: K band-limited modes, "
                            "the `keep` lowest-frequency ones summed.",
                    "params": {"K": "modes, 2-40 (default 6)",
                               "alpha": "bandwidth penalty, 100-50000 (default 2000)",
                               "keep": "lowest-frequency modes kept, 1-K (default 3)"},
                    "auto": "K = clip(round(30 f_c) + 8, 10, 20) and keep = modes "
                            "whose centre frequency is below f_c, where f_c is the "
                            "FFT noise-floor crossing."},
            "Wavelet": {"what": "Wavelet shrinkage (PyWavelets): universal threshold "
                                "sigma*sqrt(2 ln N) times k on the detail coefficients.",
                        "params": {"wavelet": f"{engine.WAVELETS} (default sym8)",
                                   "level": "1-12, capped by the signal length (default 3)",
                                   "mode": "soft|hard (default soft)",
                                   "k": "threshold scale 0.1-5 (default 1.0)"},
                        "auto": "level = min(4, max level), k = 1."},
            "FFT filter": {"what": "Fourier low-pass with a flat-topped half-Gaussian "
                                   "transfer function.",
                           "params": {"cutoff": "last fully kept coefficient n (>=1)",
                                      "slope": "0.5-20, higher = sharper (default 3)"},
                           "auto": "cut-off where the smoothed ln|Cn| stays at or below "
                                   "the noise floor + 1.4826 MAD."},
        }, "note": "Every method denoises the spectrum minus the straight line joining "
                   "its first and last points, then adds the line back."}

    def _t_get_spectrum(self, name, max_points=2000):
        sp = self._spectrum(name)
        out = {"name": name, "points": len(sp['B.E.']),
               "x_label": axis_labels(name, sp)[0],
               "x": _decimate(sp['B.E.'], max_points),
               "y": _decimate(sp['Raw Data'], max_points)}
        if sp.get('ExperimentalInfo'):
            out["experimental_info"] = sp['ExperimentalInfo']
        if sp.get('Denoise'):
            out["denoised_from"] = sp['Denoise'].get('source')
            out["params"] = sp['Denoise'].get('params')
        return out

    def _t_auto_params(self, name, method=None):
        sp = self._spectrum(name)
        method = method or self.panel.method
        return {"name": name, "params": self._params(
            method, None, np.asarray(sp['B.E.'], float),
            np.asarray(sp['Raw Data'], float), auto=True)}

    def _t_denoise_preview(self, name, method=None, params=None, auto=False,
                           apply_to_view=False, include_data=False, max_points=2000):
        sp = self._spectrum(name)
        x = np.asarray(sp['B.E.'], float)
        y = np.asarray(sp['Raw Data'], float)
        p = self._params(method, params, x, y, auto=auto)
        yf = engine.denoise(x, y, p)
        out = {"name": name, "params": p, **engine.noise_estimate(y, yf)}
        if apply_to_view:
            self.panel.select_spectrum(name)
            self.panel.set_params(p, redraw=False)
            err = self.panel.update_all_plots(show_errors=False)
            if err:
                out["view_error"] = err
            out["on_screen"] = True
        if include_data:
            out["x"] = _decimate(x.tolist(), max_points)
            out["y_denoised"] = _decimate(np.asarray(yf).tolist(), max_points)
        return out

    def _t_render_figure(self, dpi=100):
        if self.panel.x is None:
            raise _ToolError("Nothing on screen — import or select a spectrum first.")
        buf = io.BytesIO()
        self.panel.fig.savefig(buf, format="png", dpi=int(dpi))
        from .mcp_server import IMAGE_KEY
        return {IMAGE_KEY: base64.b64encode(buf.getvalue()).decode("ascii"),
                "spectrum": self.panel.current_sheet,
                "method": self.panel.method,
                "params": self.panel.active_params()}

    # ── change ──────────────────────────────────────────────────
    def _t_select_spectrum(self, name):
        self._spectrum(name)
        self.panel.select_spectrum(name)
        return {"on_screen": name, "method": self.panel.method,
                "params": self.panel.active_params()}

    def _t_set_params(self, method=None, params=None):
        if self.panel.x is None:
            raise _ToolError("No spectrum on screen.")
        p = self._params(method, params)
        self.panel.set_params(p, redraw=False)
        err = self.panel.update_all_plots(show_errors=False)
        if err:
            raise _ToolError(err)
        return {"on_screen": self.panel.current_sheet, "params": self.panel.active_params(),
                **engine.noise_estimate(self.panel.y, self.panel.y_filtered)}

    def _t_create_denoised(self, names=None, method=None, params=None, auto=True):
        targets = self._names(names)
        method = method or self.panel.method
        p = None if auto else self._params(method, params)
        if auto and method != self.panel.method:
            p = {'method': method}            # carries the method for auto mode
        created, errors = self.panel.create_spectra(targets, auto=auto, params=p)
        if not created:
            raise _ToolError("Nothing was created. " + "; ".join(errors))
        return {"created": created, "skipped": errors, "method": method, "auto": bool(auto)}

    def _t_rename_spectrum(self, name, new_name):
        self._spectrum(name)
        if not self._w.rename_spectrum(name, new_name):
            raise _ToolError(f"Cannot rename to {new_name!r} (empty or taken).")
        return {"renamed": name, "to": new_name}

    def _t_delete_spectrum(self, name):
        self._spectrum(name)
        self._w.delete_spectrum(name, confirm=False)
        return {"deleted": name, "remaining": self.doc.names()}

    # ── files ───────────────────────────────────────────────────
    def _t_import_file(self, path):
        path = os.path.abspath(os.path.expanduser(path))
        if not os.path.isfile(path):
            raise _ToolError(f"No such file: {path}")
        names, dismissed = self._w.import_paths([path], interactive=False)
        if not names:
            raise _ToolError("No spectra found. " +
                             "; ".join(f"{n}: {r}" for n, r in dismissed))
        out = {"imported": names,
               "dismissed": [{"name": n, "reason": r} for n, r in dismissed]}
        from .importers import notice_for
        if notice_for(path):
            out["notice"] = notice_for(path)
        return out

    def _t_open_project(self, path, discard_unsaved_changes=False):
        path = os.path.abspath(os.path.expanduser(path))
        if not os.path.isfile(path):
            raise _ToolError(f"No such file: {path}")
        if self.doc.dirty and not self.doc.is_empty() and not discard_unsaved_changes:
            raise _ToolError("The open spectra have unsaved changes. Save them "
                             "(save_project) or pass discard_unsaved_changes=true.")
        names = self._w.open_path(path, interactive=False)
        return {"opened": path, "spectra": names}

    def _t_save_project(self, path=None):
        path = path or self.doc.path
        if not path:
            raise _ToolError("The project has never been saved: give a path "
                             "ending in .knoise.")
        path = os.path.abspath(os.path.expanduser(path))
        if not path.lower().endswith(".knoise"):
            path += ".knoise"
        self._w.save_to(path)
        return {"saved": path, "spectra": len(self.doc)}

    def _t_export_khervefitting(self, path, names=None):
        from .exporters import write_khervefitting_xlsx
        path = os.path.abspath(os.path.expanduser(path))
        if not path.lower().endswith((".xlsx", ".xlsm")):
            path += ".xlsx"
        sheets = write_khervefitting_xlsx(path, [self.doc.get(n) for n in self._names(names)])
        return {"written": path, "sheets": sheets}

    def _t_export_csv(self, path, names=None):
        from .exporters import write_text
        path = os.path.abspath(os.path.expanduser(path))
        write_text(path, [self.doc.get(n) for n in self._names(names)])
        return {"written": path}


class _ToolError(Exception):
    """A tool refusal whose message goes back to the assistant as is."""
