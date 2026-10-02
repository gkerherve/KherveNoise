"""The words behind every toolbar icon.

One entry per icon, keyed "<toolbar>|<label>" where the label is the
action's text. Each value is (title, what it does, [how-to steps], tip).
tooltips.py turns them into the hover tooltip, the status-bar line and the
Toolbar reference chapter of the User Guide.

Keep the text free of angle brackets and ampersands: it is used both as
HTML (tooltips) and as Markdown (the guide).

Copyright (C) 2026 Gwilherm Kerherve
Licensed under the GNU General Public License v3.0 (see LICENSE).
"""

TIPS = {
    # ---------------------------------------------------------------- File
    "File|New Instance": (
        "New Instance of KherveNoise",
        "Starts a second, independent KherveNoise window — its own "
        "spectra, its own settings — so two data sets can be denoised side "
        "by side.",
        ["Click the icon: a fresh KherveNoise window opens.",
         "Open or import a file in it; this window is not affected.",
         "Close either window on its own when you are done."],
        "Each instance asks about its own unsaved work when it closes."),
    "File|Open": (
        "Open a file",
        "Opens a KherveNoise project (.knoise) — every spectrum, denoised "
        "copies included, with the settings that made them — or reads any "
        "supported data file (Excel, VAMAS, ASC / TXT / DAT / CSV) in "
        "place of the current work.",
        ["Click the icon and choose the file.",
         "If the current spectra are unsaved you are asked first.",
         "The first spectrum is selected and denoised with Auto settings."],
        "Recent files are under File, Open Recent. You can also drag a file "
        "onto the window."),
    "File|Import Excel": (
        "Import an Excel workbook",
        "Reads a KherveFitting-style workbook (.xlsx / .xls): one spectrum "
        "per sheet whose first row is a header pair such as Binding Energy "
        "+ Raw Data. Sheets named Sheet1, Results Table or Experimental "
        "Description are skipped, as in KherveFitting.",
        ["Click the icon and pick the workbook.",
         "The spectra are ADDED to those already open (a name that exists "
         "gets a number).",
         "A short report lists any sheet that was left out and why."],
        "A workbook with no KherveFitting sheet at all is read as the first "
        "two numeric columns of every sheet."),
    "File|Import Data File": (
        "Import a data file (ASC, TXT, DAT, XY, CSV)",
        "Reads a two-column text file — x then intensity — separated by "
        "semicolons, commas, tabs or spaces. Lines starting with # and any "
        "non-numeric line (a header) are ignored. The spectrum is named "
        "after the file.",
        ["Click the icon and select one or several files (Ctrl or Shift "
         "click to pick many).",
         "Each file becomes one spectrum, added to the open ones.",
         "Rename a spectrum with Spectrum, Rename (F2)."],
        "Only the first two columns are read, exactly as KherveFitting does. "
        "Name the file after the core level (C1s.txt) to get the XPS "
        "binding-energy axis."),
    "File|Import VAMAS": (
        "Import a VAMAS file (.vms)",
        "Reads an ISO 14976 VAMAS file from CasaXPS, Kratos, Thermo, PHI "
        "and others: one spectrum per block, kinetic energy converted to "
        "binding energy with the block's photon energy, counts divided by "
        "scans times dwell time and corrected by the transmission function.",
        ["Click the icon and choose the .vms file.",
         "Each block becomes a spectrum named after its core level (C1s, "
         "O1s, Survey, VB, Auger lines such as Ckll).",
         "Blocks recorded with 0 scans are skipped."],
        "The block's acquisition details are kept and written to the "
        "Experimental Description block when you export to KherveFitting."),
    "File|Import Instrument File": (
        "Import an instrument file",
        "Reads the native or exported files of XPS instruments, as "
        "KherveFitting does: Thermo Avantage (.xlsx, .xls), VGD and AVG; "
        "Kratos .kal; PHI .spe spectra and .pro depth profiles; Scienta "
        "Omicron .txt; MRS; VG-Microtech .1; Igor .itx and .dat; Diamond "
        "Light Source NeXus and B07 .dat; SDP files from XPS International.",
        ["Click the icon and pick one or several files — the file type list "
         "narrows the choice to one instrument if you like.",
         "Every region, block or cycle becomes a spectrum named after its "
         "core level, added to those already open.",
         "A report lists anything left out, such as images or maps, which "
         "cannot be denoised."],
        "The same readers run when you Open or drop a file, so this icon is "
        "only a shortcut. File, Import, Instrument lists them per vendor."),
    "File|Import Folder": (
        "Import every file in a folder",
        "Imports all the supported files of one folder in a single step — "
        "a series of samples or a whole measurement session — each spectrum "
        "added to the open ones.",
        ["Click the icon and choose the folder.",
         "Every file KherveNoise can read is imported, in natural name order "
         "(sample2 before sample10).",
         "Ctrl+Z removes the whole import in one go."],
        "Spectra with the same name get a number (C1s, C1s1, C1s2…)."),
    "File|Save": (
        "Save the project",
        "Writes every spectrum — originals and denoised copies with the "
        "method and parameters that produced them — to one .knoise "
        "project file.",
        ["Click the icon. The first time you are asked for a file name.",
         "After that it saves silently to the same file.",
         "Use File, Save As to keep a second copy."],
        "Ctrl+S. The title bar shows a star while there are unsaved changes."),
    "File|Export to KherveFitting": (
        "Export to KherveFitting (.xlsx)",
        "Writes the spectra to an Excel workbook in KherveFitting's own "
        "layout — one sheet per spectrum with BE, Corrected Data, Raw Data "
        "and Transmission columns — ready to open in KherveFitting for peak "
        "fitting.",
        ["Click the icon and choose which spectra to write (all, or only "
         "the denoised copies).",
         "Pick a file name.",
         "Open the workbook in KherveFitting with File, Open."],
        "Denoised sheets record their source spectrum and parameters in the "
        "Experimental Description block."),
    "File|Export CSV": (
        "Export as CSV / text",
        "Writes the selected spectra side by side as x, intensity column "
        "pairs — comma-separated for .csv, tab-separated for .txt — for "
        "Origin, Excel, KhervePlot or any other program.",
        ["Click the icon and choose which spectra to write.",
         "Pick a .csv or .txt file name.",
         "Each spectrum adds two columns with its name in the header."],
        None),
    "File|Save Figure": (
        "Save the figure",
        "Saves the three-panel figure exactly as shown — transform, kept "
        "map and Raw vs Denoised with residual — as PNG, SVG or PDF.",
        ["Set up the view you want (method, zoom, Raw as scatter…).",
         "Click the icon and choose the file type by its extension.",
         "PNG is written at 300 dpi."],
        "SVG and PDF stay sharp at any size, which suits papers and slides."),
    # ------------------------------------------------------------- Denoise
    "Denoise|Apply": (
        "Apply",
        "Recomputes the denoised spectrum with the parameters now in the "
        "Method box and redraws all three panels. Changing a parameter "
        "already does this — Apply is for redrawing on demand.",
        ["Select the core level in the Data box.",
         "Choose a method (VMD, Wavelet or FFT filter) and set its "
         "parameters.",
         "Click Apply and compare Raw against Denoised; the residual strip "
         "should look like structureless noise."],
        "If peaks show up in the residual, the filter is too strong: keep "
        "more modes, lower the wavelet threshold or raise the FFT cut-off."),
    "Denoise|Auto": (
        "Auto parameters",
        "Sets recommended parameters for the active method from the "
        "spectrum itself. FFT: the cut-off where ln|Cn| sinks into the "
        "noise floor. Wavelet: level 4 (or the deepest possible) with "
        "threshold x1. VMD: the number of modes and how many to keep from "
        "the same signal / noise boundary.",
        ["Select the core level and the method.",
         "Click Auto: the controls are filled in and the plots redrawn.",
         "Fine-tune from there if needed."],
        "Auto runs by itself whenever you pick another spectrum or method."),
    "Denoise|Create": (
        "Create denoised spectra",
        "Writes the denoised version of every ticked spectrum to a NEW "
        "spectrum named after its source plus _vmd, _wav or _fft. The "
        "original data are never changed.",
        ["Tick the spectra in the Create denoised sheet for list (All / "
         "None help).",
         "Leave Auto parameters per spectrum ticked to tune each one on its "
         "own, or untick it to use the current settings for all.",
         "Click Create; the new spectra appear in the lists."],
        "Undo (Ctrl+Z) removes a whole Create in one step."),
    "Denoise|Delete Spectrum": (
        "Delete the selected spectrum",
        "Removes the spectrum shown in the Data box from the project — "
        "typically a denoised copy you no longer want.",
        ["Select the spectrum in the Data box.",
         "Click the icon and confirm.",
         "Ctrl+Z brings it back."],
        None),
    # ---------------------------------------------------------------- View
    "View|Zoom Box": (
        "Zoom in (box)",
        "Zooms the Raw vs Denoised panel onto a rectangle you drag, to "
        "inspect a shoulder or the noise on a background.",
        ["Click the icon (the Zoom in button turns green).",
         "Drag a box over the bottom plot.",
         "The view zooms to it; the box mode switches itself off."],
        "The zoom is kept while you change parameters, so you can watch one "
        "feature as you tune."),
    "View|Zoom Out": (
        "Zoom out",
        "Widens the Raw vs Denoised view by 60 percent in both directions "
        "around its centre.",
        ["Click the icon once or several times."],
        None),
    "View|Y Zoom In": (
        "Y zoom in",
        "Stretches the intensity axis of the Raw vs Denoised panel by 20 "
        "percent around its centre — handy to see small residual features.",
        ["Click the icon; repeat for more."],
        None),
    "View|Y Zoom Out": (
        "Y zoom out",
        "Compresses the intensity axis of the Raw vs Denoised panel by 25 "
        "percent around its centre.",
        ["Click the icon; repeat for more."],
        None),
    "View|Reset View": (
        "Reset the view",
        "Returns the Raw vs Denoised panel to the full spectrum and redraws "
        "every panel.",
        ["Click the icon."],
        None),
    # ---------------------------------------------------------------- Help
    "Help|Connect to Claude": (
        "Connect to Claude (MCP)",
        "Lets Claude Desktop, Claude Code, Cursor and other MCP assistants "
        "drive this window: list and read spectra, import files, denoise "
        "with any method, create denoised copies, export, and look at the "
        "figure.",
        ["Click the icon and tick Let assistants connect.",
         "Pick your assistant in the list and press Connect — KherveNoise "
         "writes the entry into its settings for you.",
         "Restart the assistant, then ask, for example, denoise C1s with "
         "VMD in KherveNoise."],
        "Every change an assistant makes is one Ctrl+Z step. The access "
        "level (read, edit, full) is yours to choose."),
    "Help|User Guide": (
        "User Guide",
        "Opens the in-app guide: the three methods, what each panel of the "
        "figure shows, importing, exporting to KherveFitting, and this "
        "toolbar reference.",
        ["Click the icon (or press F1).",
         "Pick a chapter on the left, or type in Find."],
        None),
    "Help|References": (
        "Methods and References",
        "The denoising methods with their primary publications and DOIs — "
        "the FFT low-pass filter, wavelet shrinkage and Variational Mode "
        "Decomposition — and the libraries KherveNoise is built on.",
        ["Click the icon; links open in your browser."],
        "Cite the method you used in your paper."),
    "Help|About": (
        "About KherveNoise",
        "Who wrote KherveNoise, the Kherve family of tools, the version "
        "you are running and the licence.",
        ["Click the icon."],
        None),
}
