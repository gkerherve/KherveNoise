"""The MCP tool table — what an assistant may call, and how.  Qt-free.

A tool's ``description`` is prompt text sent to the model verbatim: say
what it does and when to prefer it over its neighbours.  A new tool = a
``TOOLS`` entry + a ``_t_<name>`` method in ``mcp_tools.py`` (+ a line in
``mcp_server._INSTRUCTIONS``); ``tests/test_mcp.py`` enforces the pairing.

Copyright (C) 2026 Gwilherm Kerherve
Licensed under the GNU General Public License v3.0 (see LICENSE).
"""

from .engine import METHODS, WAVELET_MODES, WAVELETS

_PARAMS = {
    "type": "object",
    "description": (
        "Method parameters. VMD: K (2-40 modes), alpha (bandwidth "
        "100-50000), keep (1-K lowest-frequency modes kept). Wavelet: "
        f"wavelet ({', '.join(WAVELETS)}), level (1-12), mode "
        f"({'|'.join(WAVELET_MODES)}), k (0.1-5 threshold scale). "
        "FFT filter: cutoff (coefficient n, >=1), slope (0.5-20). "
        "Missing keys take the method's defaults."),
    "properties": {
        "K": {"type": "integer", "minimum": 2, "maximum": 40},
        "alpha": {"type": "number", "minimum": 100, "maximum": 50000},
        "keep": {"type": "integer", "minimum": 1, "maximum": 40},
        "wavelet": {"type": "string", "enum": WAVELETS},
        "level": {"type": "integer", "minimum": 1, "maximum": 12},
        "mode": {"type": "string", "enum": WAVELET_MODES},
        "k": {"type": "number", "minimum": 0.1, "maximum": 5},
        "cutoff": {"type": "integer", "minimum": 1},
        "slope": {"type": "number", "minimum": 0.5, "maximum": 20},
    },
}
_METHOD = {"type": "string", "enum": METHODS,
           "description": "Denoising method; default: the one in the controls."}
_NAME = {"type": "string", "description": "Spectrum name, as get_project_info lists it."}
_NAMES = {"type": "array", "items": {"type": "string"},
          "description": "Spectrum names; omit for every spectrum."}


def _tool(name, description, props=None, required=None):
    return {"name": name, "description": description,
            "input_schema": {"type": "object", "properties": props or {},
                             "required": required or []}}


TOOLS = [
    _tool("get_project_info",
          "List every spectrum (name, points, x range, axis label, and for a "
          "denoised copy its source and parameters), which spectrum is on "
          "screen, the method and parameters in the controls, the file and "
          "whether there are unsaved changes. Call this FIRST."),
    _tool("list_methods",
          "The three denoising methods, every parameter with its range and "
          "default, and how the Auto rule picks them."),
    _tool("get_spectrum",
          "Read a spectrum's data: x and y arrays (decimated to at most "
          "max_points), its experimental info, and for a denoised copy the "
          "source and parameters.",
          {"name": _NAME,
           "max_points": {"type": "integer", "minimum": 10, "default": 2000}},
          ["name"]),
    _tool("import_file",
          "Import a file and ADD its spectra: Excel in KherveFitting layout "
          "(.xlsx/.xls), VAMAS (.vms), a two-column data file "
          "(.asc/.txt/.dat/.xy/.csv), or an instrument file — Thermo "
          "Avantage (.xlsx/.xls) / VGD / AVG, Kratos .kal, PHI .spe / .pro, "
          "Scienta .txt, MRS, VG-Microtech .1, Igor .itx / .dat, Diamond "
          ".nxs / B07 .dat, SDP. Returns the names created and anything "
          "left out with the reason.",
          {"path": {"type": "string", "description": "Absolute file path."}},
          ["path"]),
    _tool("open_project",
          "Open a .knoise project (or any importable file) in place of the "
          "current work. Refuses to drop unsaved changes unless "
          "discard_unsaved_changes is true — offer to save first.",
          {"path": {"type": "string"},
           "discard_unsaved_changes": {"type": "boolean", "default": False}},
          ["path"]),
    _tool("save_project",
          "Save every spectrum to the .knoise project file. Without path it "
          "saves over the open project (like Ctrl+S); a path saves there.",
          {"path": {"type": "string"}}),
    _tool("select_spectrum",
          "Show a spectrum in the window (the Data box). Auto parameters are "
          "applied for the current method, as when the user picks it.",
          {"name": _NAME}, ["name"]),
    _tool("auto_params",
          "Recommended parameters for a spectrum and method — the Auto "
          "button's rule (FFT noise-floor crossing; wavelet level 4, k 1; "
          "VMD K and keep from the same signal/noise boundary). Reads only.",
          {"name": _NAME, "method": _METHOD}, ["name"]),
    _tool("denoise_preview",
          "Denoise one spectrum WITHOUT creating anything and report the "
          "residual RMS, SNR and the parameters used. auto=true uses the "
          "Auto rule. apply_to_view=true also shows it in the window "
          "(selects the spectrum, sets method and parameters, redraws). "
          "include_data returns the denoised y too.",
          {"name": _NAME, "method": _METHOD, "params": _PARAMS,
           "auto": {"type": "boolean", "default": False},
           "apply_to_view": {"type": "boolean", "default": False},
           "include_data": {"type": "boolean", "default": False},
           "max_points": {"type": "integer", "minimum": 10, "default": 2000}},
          ["name"]),
    _tool("set_params",
          "Put a method and parameters into the window's controls and redraw "
          "the spectrum on screen — what the user sees and what Create uses "
          "when auto is off.",
          {"method": _METHOD, "params": _PARAMS}),
    _tool("create_denoised",
          "Create denoised copies: one new spectrum per source, named "
          "'<name>_vmd' / '_wav' / '_fft' (numbered if taken). Originals "
          "never change. auto=true (default) tunes each spectrum with the "
          "Auto rule; auto=false uses params (or the controls). One undo "
          "step.",
          {"names": _NAMES, "method": _METHOD, "params": _PARAMS,
           "auto": {"type": "boolean", "default": True}}),
    _tool("rename_spectrum", "Rename a spectrum.",
          {"name": _NAME, "new_name": {"type": "string"}}, ["name", "new_name"]),
    _tool("set_axes",
          "Set a spectrum's axes: x_label / y_label (empty string = back "
          "to the default), reversed (x drawn high to low) and xps (true = "
          "XPS binding-energy spectrum; false = any other data). Data that "
          "is not XPS should not carry binding-energy / CPS labels. One "
          "undo step.",
          {"name": _NAME, "x_label": {"type": "string"},
           "y_label": {"type": "string"}, "reversed": {"type": "boolean"},
           "xps": {"type": "boolean"}}, ["name"]),
    _tool("delete_spectrum", "Remove a spectrum (undoable).",
          {"name": _NAME}, ["name"]),
    _tool("export_khervefitting",
          "Write spectra to an Excel workbook in KherveFitting's layout "
          "(one sheet each: BE | Corrected Data | Raw Data | Transmission), "
          "ready for peak fitting in KherveFitting.",
          {"path": {"type": "string"}, "names": _NAMES}, ["path"]),
    _tool("export_csv",
          "Write spectra as x, intensity column pairs (.csv comma, other "
          "extensions tab-separated).",
          {"path": {"type": "string"}, "names": _NAMES}, ["path"]),
    _tool("render_figure",
          "PNG of the window's figure: the transform or decomposition (top), "
          "what is kept (middle), Raw vs Denoised with the residual strip "
          "(bottom). Look at it after anything non-trivial.",
          {"dpi": {"type": "integer", "minimum": 50, "maximum": 300,
                   "default": 100}}),
]

#: Tools offered only at the Full access level (none run code here).
FULL_ACCESS_TOOLS = frozenset()

TOOL_NAMES = [t["name"] for t in TOOLS]
_BY_NAME = {t["name"]: t for t in TOOLS}

_TYPES = {"string": str, "integer": int, "number": (int, float),
          "boolean": bool, "array": list, "object": dict}


def check_args(name, args):
    """Validate *args* against the tool's schema; returns an error string
    or '' when they are fine."""
    tool = _BY_NAME.get(name)
    if tool is None:
        return f"Unknown tool {name!r}."
    if not isinstance(args, dict):
        return "Arguments must be an object."
    schema = tool["input_schema"]
    for req in schema.get("required", []):
        if req not in args or args[req] in (None, ""):
            return f"{name}: missing required argument {req!r}."
    props = schema.get("properties", {})
    for key, value in args.items():
        spec = props.get(key)
        if spec is None:
            return f"{name}: unknown argument {key!r}."
        want = _TYPES.get(spec.get("type"))
        if want is not None and value is not None:
            if spec.get("type") in ("integer", "number") and isinstance(value, bool):
                return f"{name}: {key} must be a {spec['type']}."
            if not isinstance(value, want):
                return f"{name}: {key} must be a {spec['type']}."
        if "enum" in spec and value not in spec["enum"]:
            return f"{name}: {key} must be one of {spec['enum']}."
    return ""
