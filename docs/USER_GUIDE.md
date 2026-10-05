# KherveNoise — User Guide

KherveNoise removes noise from a spectrum **without any training data**,
one spectrum at a time, and shows you exactly what each method keeps and
what it throws away. It is the *Spectral Denoising* tool of KherveFitting
released as a program of its own: same methods, same controls, same plots,
the same numbers.

## Getting started

1. **Bring in data.** Use *File ▸ Open…*, one of the *File ▸ Import*
   entries, the toolbar icons, or simply **drag files onto the window**.
2. **Pick a spectrum** in the *Data* box (*Select core level*).
3. **Pick a method** — VMD, Wavelet or FFT filter. KherveNoise applies
   its **Auto** parameters straight away.
4. **Judge the result** in the bottom panel: Raw (black) against Denoised
   (green), with the residual (magenta) above it.
5. **Create** the denoised spectra you want to keep, then **save** the
   project (.knoise) or **export** to KherveFitting / CSV.

The original data are never modified: every denoised result is a new
spectrum named after its source (`C1s_vmd`, `C1s_wav`, `C1s_fft`).

## Spectral Denoising

The window has the *Analysis Controls* column on the left and a figure of
three panels on the right.

### Analysis Controls

- **Data** — the spectrum on screen and its number of points (and, for the
  FFT filter, the number of Fourier coefficients).
- **Method** — the method, a one-line summary of its current settings,
  the method's parameters, and two buttons: **Apply** (recompute and
  redraw) and **Auto** (recommended parameters for this spectrum).
- **Create denoised sheet for** — tick the spectra to denoise in one go
  (*All* / *None* help). With **Auto parameters per spectrum** ticked,
  each spectrum is tuned on its own with the Auto rule; unticked, the
  current settings are used for every one. **Create** adds the results.
- **Result view** — *Zoom in (box)*: drag a rectangle on the bottom plot;
  *Zoom out*; *Y +* / *Y −* stretch or squeeze the intensity axis;
  *Reset* shows the whole spectrum again.
- **Result display** — show or hide Raw and Denoised, draw Raw as a line
  or as points, and set both line widths.
- **About / References** — the methods and their publications.

### The figure

| Panel | VMD | Wavelet | FFT filter |
|---|---|---|---|
| Top | Energy of each mode at its centre frequency — green kept, magenta dropped | RMS of the detail coefficients per level, with the threshold | ln\|Cn\| of the Fourier coefficients, the filter's transfer function and the noise level |
| Middle | The modes themselves, lowest frequency at the bottom | Scalogram of the detail coefficients | Contribution of every Fourier coefficient across the spectrum, with the cut-off |
| Bottom | Raw vs Denoised, residual strip above | same | same |

**A good result leaves a residual that looks like structureless noise.**
If you can see peaks in the residual, the filter is too strong.

### Variational Mode Decomposition (VMD)

The spectrum is split into **K** band-limited modes, each centred on its own
frequency; the **Keep modes** lowest-frequency ones are summed into the
denoised spectrum and the rest are dropped as noise. **Bandwidth** (α) sets
how narrow each mode is.

- More kept modes → more detail kept (and more noise).
- *Auto* finds the frequency where the spectrum's Fourier coefficients sink
  into the noise floor, sets K from it (10–20) and keeps every mode below it.

### Wavelet shrinkage

The spectrum is decomposed with a discrete wavelet transform (db4, db8,
sym4, sym8 or coif5) to **Level** scales; the detail coefficients below the
universal threshold σ√(2 ln N) × **Threshold x** are shrunk (*soft*) or set
to zero (*hard*), and the spectrum is rebuilt. It keeps sharp peaks well.

- Higher *Threshold x* → smoother.
- *Auto* uses level 4 (or the deepest the spectrum allows) and ×1.

### FFT filter

The spectrum is transformed to Fourier space and multiplied by a
flat-topped half-Gaussian: coefficients up to the **Cut-off n** pass
unchanged, higher ones roll off with the **Slope** (higher = sharper).

- *Auto* puts the cut-off where ln|Cn| stays at or below the noise floor.

Every method works on the spectrum minus the straight line joining its
first and last points, then adds that line back, so a sloping background
does not leak into the filtering.

## Files

### Importing

| Format | What is read |
|---|---|
| **Excel** (.xlsx, .xls) | One spectrum per sheet whose first row is a KherveFitting header pair (e.g. *Binding Energy* + *Raw Data*). Sheets named *Sheet1*, *Results Table* or *Experimental Description* are skipped. A workbook with no such sheet is read as the first two numeric columns of each sheet. |
| **VAMAS** (.vms) | One spectrum per block (blocks with 0 scans skipped). Kinetic energy is converted to binding energy with the block's photon energy; counts are divided by scans × dwell time and corrected by the transmission function, exactly as in KherveFitting. Names are normalised (C1s, Survey, VB, Auger lines such as *Ckll*). |
| **Data files** (.asc, .txt, .dat, .xy, .csv) | Two columns, x then intensity, separated by `;`, `,`, tabs or spaces. Lines starting with `#` and header lines are ignored. The spectrum is named after the file. |

| **Instrument files** | Read with KherveFitting's own importers (see below). |

*Open* replaces the current spectra; *Import* adds to them;
*Import ▸ All Files in a Folder* imports every supported file of a folder.

#### Instrument files

*File ▸ Import ▸ Instrument* lists them per vendor, as KherveFitting's
*Import ▸ XPS* menu does. Opening or dropping the file works too.

| Vendor | Files |
|---|---|
| **Thermo Scientific** | Avantage exports (.xlsx / .xls with a *Titles* sheet), VGD (.vgd), AVG (.avg) |
| **Kratos** | .kal |
| **PHI (Physical Electronics)** | MultiPak spectra (.spe), depth profiles (.pro — one spectrum per region and cycle) |
| **Scienta Omicron** | SES plot files (.txt); map files (.txt) and HDF5 maps (.h5), imported as the summed spectrum KherveFitting makes from them |
| **MRS** | .mrs |
| **VG-Microtech** | .1 |
| **Igor Pro** | .itx, .dat |
| **Diamond Light Source** | NeXus (.nxs, I09 / B07 / I10) and B07 XPS .dat exports |
| **XPS International** | SDP files (.sdp) — a third-party format: you are asked to confirm first |

Images and 2D maps themselves (PHI SXI images, the pixels of a Thermo XY
area scan or of a Scienta map) are not imported — there is no single
spectrum in them to denoise. Where KherveFitting makes a spectrum from a
map (the all-pixel average of a VGD area scan, the summed sweeps of a
Scienta map), that spectrum is imported.

Diamond NeXus files and Scienta HDF5 maps need the optional *h5py*
package (in `requirements.txt`).

KherveNoise is not limited to XPS: any x / y data can be denoised. Only an
XPS spectrum gets the *Binding Energy (eV)* / *Intensity (CPS)* axes read
high to low — one from an instrument file or VAMAS binding-energy block, a
file whose x column is headed *Binding Energy* / *BE*, or a core-level name
(C1s, O 1s, Ti2p, Survey, VB…). Names starting with *FTIR*, *Raman*, *EELS*,
*XAS*, *XRD*… get their technique's label and direction. Anything else gets
its file's column headers as axis labels (plain *X* / *Y* when there are
none), read low to high. **Spectrum ▸ Axes…** changes any of this.

### Saving and exporting

- **Save** (.knoise) keeps every spectrum, including the denoised copies with
  the method and parameters that made them.
- **Export ▸ To KherveFitting** writes a workbook in KherveFitting's own
  layout (one sheet per spectrum: *BE · Corrected Data · Raw Data ·
  Transmission*), ready for peak fitting. Acquisition details and the
  denoising parameters go into the *Experimental Description* block.
- **Export ▸ As CSV / Text** writes x, intensity column pairs.
- **Export ▸ Figure** saves the three panels as PNG (300 dpi), SVG or PDF.

## Spectrum menu

- **Axes…** sets the x and y labels, the x direction and whether the
  spectrum is XPS (binding energy). Undoable.
- **Rename** (F2), **Delete** and **Spectrum Information** (acquisition
  details, and for a denoised copy its source and parameters).
- *Edit ▸ Undo / Redo* reverts any import, create, rename or delete.

## File menu, instances and updates

- **New Instance of KherveNoise** opens a second, independent window.
- **About KherveNoise** — the author and the Kherve family of tools.
- **Exit** asks about unsaved work first.
- **Help ▸ Check for Updates…** brings a source checkout up to date from
  GitHub (only when it can do so safely), and **Update Automatically**
  does so in the background.

## Connecting Claude (MCP)

*AI ▸ Connect to Claude (MCP)…* lets Claude Desktop, Claude Code, Cursor,
Zed and other MCP assistants work with the spectra open in KherveNoise.

1. Tick **Let assistants connect to KherveNoise**.
2. Choose what the assistant may do: *Read only*, *Edit* (recommended) or
   *Full* (also opens, imports, saves and exports files of its choosing).
3. Select your assistant in the list and press **Connect** — KherveNoise
   writes the entry into that application's settings for you.
4. Restart the assistant, then ask, for example: *"In KherveNoise, import
   my VAMAS file, denoise every core level with VMD and show me the
   result for C1s."*

The assistant can list and read spectra, import files, preview any method
and its residual, set the controls, create denoised copies, rename and
delete spectra, export, and look at the figure. Each change is one
Ctrl+Z step.

## Toolbar reference

Hover over any toolbar icon for the same explanation.

<!-- toolbar-reference -->

## References

Help ▸ *Methods & References* lists the publications behind each method —
Cooley & Tukey (FFT), Mallat and Donoho & Johnstone (wavelet shrinkage),
Dragomiretskiy & Zosso (VMD) — and the libraries KherveNoise is built on.
Please cite the method you use.
