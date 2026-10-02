"""Spectral denoising maths — Qt-free, shared by the window, batch and MCP.

A faithful port of KherveFitting's Spectral Denoising window
(``libraries/ToolsMenu/FFT_Filter.py``): every function here reproduces
the corresponding method of ``SpectralDenoisingWindow`` number for number.
Three training-free, single-spectrum methods:

  * FFT filter - transform to the Fourier (reciprocal) domain, multiply the
                 coefficients by a flat-topped half-Gaussian low-pass filter,
                 transform back. Cut-off + slope controls.
  * Wavelet    - wavelet-shrinkage (PyWavelets): decompose, threshold the
                 detail coefficients, reconstruct. Good at preserving sharp
                 peaks. Wavelet / level / mode / threshold-scale controls.
  * VMD        - Variational Mode Decomposition (pure numpy): decompose the
                 signal into K band-limited modes and keep the low-frequency
                 ones. Number-of-modes / bandwidth / kept-modes controls.

Every method works on the spectrum minus the straight line joining its two
end points (the "baseline"), then adds that line back.

Copyright (C) 2026 Gwilherm Kerherve
Licensed under the GNU General Public License v3.0 (see LICENSE).
"""

import numpy as np

METHODS = ["VMD", "Wavelet", "FFT filter"]
SUFFIX = {"FFT filter": "fft", "Wavelet": "wav", "VMD": "vmd"}
WAVELETS = ["db4", "db8", "sym4", "sym8", "coif5"]
WAVELET_MODES = ["soft", "hard"]

#: Defaults of the window's controls, as KherveFitting ships them.
DEFAULTS = {
    "FFT filter": {"cutoff": 1, "slope": 3.0},
    "Wavelet": {"wavelet": "sym8", "level": 3, "mode": "soft", "k": 1.0},
    "VMD": {"K": 6, "alpha": 2000.0, "keep": 3},
}


# ----------------------------------------------------------------------
# Variational Mode Decomposition (Dragomiretskiy & Zosso, 2014) - pure numpy.
# ----------------------------------------------------------------------
def vmd(signal, alpha, K, tau=0.0, DC=0, init=1, tol=1e-7, n_iter=500):
    """Decompose 'signal' into K band-limited modes.
    Returns (modes [K x L], omega [K] final centre frequencies).

    Same arithmetic as KherveFitting's (vmdpy-style) loop, which stores all
    ``n_iter`` iterations and finally reads row ``n - 1`` — the iterate
    *before* the last one.  Only those two rows are ever read back, so only
    two are kept here: identical numbers, a few MB instead of ~350 MB for a
    survey at K = 20 (tests/test_engine.py checks it against the literal
    version)."""
    f = np.asarray(signal, dtype=float)
    if len(f) % 2:
        f = f[:-1]
    half = len(f) // 2
    fMirr = np.concatenate([np.flip(f[:half]), f, np.flip(f[half:])])
    T = len(fMirr)
    t = np.arange(1, T + 1) / T
    freqs = t - 0.5 - 1.0 / T

    Alpha = alpha * np.ones(K)
    f_hat = np.fft.fftshift(np.fft.fft(fMirr))
    f_hat_plus = np.copy(f_hat)
    f_hat_plus[:T // 2] = 0

    u_cur = np.zeros((T, K), dtype=complex)        # u_hat_plus[n]
    om_cur = np.zeros(K)                           # omega[n]
    for i in range(K):
        om_cur[i] = (0.5 / K) * i
    if DC:
        om_cur[0] = 0
    lam_cur = np.zeros(T, dtype=complex)           # lambda_hat[n]
    u_prev, om_prev = u_cur, om_cur                # row n - 1

    uDiff = tol + np.spacing(1)
    n = 0
    sum_uk = 0
    pos = slice(T // 2, T)
    while uDiff > tol and n < n_iter - 1:
        u_new = np.zeros((T, K), dtype=complex)
        om_new = np.zeros(K)
        k = 0
        sum_uk = u_cur[:, K - 1] + sum_uk - u_cur[:, 0]
        u_new[:, k] = (f_hat_plus - sum_uk - lam_cur / 2) / \
                      (1 + Alpha[k] * (freqs - om_cur[k]) ** 2)
        if not DC:
            om_new[k] = np.dot(freqs[pos], abs(u_new[pos, k]) ** 2) / \
                        np.sum(abs(u_new[pos, k]) ** 2)
        for k in range(1, K):
            sum_uk = u_new[:, k - 1] + sum_uk - u_cur[:, k]
            u_new[:, k] = (f_hat_plus - sum_uk - lam_cur / 2) / \
                          (1 + Alpha[k] * (freqs - om_cur[k]) ** 2)
            om_new[k] = np.dot(freqs[pos], abs(u_new[pos, k]) ** 2) / \
                        np.sum(abs(u_new[pos, k]) ** 2)
        lam_new = lam_cur + tau * (np.sum(u_new, axis=1) - f_hat_plus)
        n += 1
        uDiff = np.spacing(1)
        for i in range(K):
            diff = u_new[:, i] - u_cur[:, i]
            uDiff = uDiff + (1.0 / T) * np.dot(diff, np.conj(diff))
        uDiff = np.abs(uDiff)
        u_prev, om_prev = u_cur, om_cur
        u_cur, om_cur, lam_cur = u_new, om_new, lam_new

    om = om_prev
    idxs = np.flip(np.arange(1, T // 2 + 1))
    u_hat = np.zeros((T, K), dtype=complex)
    u_hat[T // 2:T, :] = u_prev[pos, :]
    u_hat[idxs, :] = np.conj(u_prev[pos, :])
    u_hat[0, :] = np.conj(u_hat[-1, :])
    u = np.zeros((K, len(t)))
    for k in range(K):
        u[k, :] = np.real(np.fft.ifft(np.fft.ifftshift(u_hat[:, k])))
    u = u[:, T // 4:3 * T // 4]            # undo the mirror padding
    return u, om


# ----------------------------------------------------------------------
# Shared helpers
# ----------------------------------------------------------------------
def baseline(y):
    """The straight line joining the first and last points."""
    y = np.asarray(y, dtype=float)
    return np.linspace(y[0], y[-1], len(y))


def ln_coeffs(coeffs):
    return np.log(np.abs(coeffs) + 1e-12)


def fft_build_filter(M, n_c, slope):
    """Flat-topped half-Gaussian low-pass transfer function (length M)."""
    n = np.arange(M)
    sigma = max(1.5, n_c / slope)
    H = np.ones(M)
    m = n > n_c
    H[m] = np.exp(-0.5 * ((n[m] - n_c) / sigma) ** 2)
    return H


def fft_recommended(lnC, M):
    """Noise-floor crossing cut-off. Returns (cutoff, floor, threshold)."""
    if M < 8:
        return 1, (float(np.median(lnC)) if M else 0.0), 0.0
    start = max(2, int(0.6 * M))
    tail = lnC[start:]
    floor = float(np.median(tail))
    mad = float(np.median(np.abs(tail - floor)))
    scale = 1.4826 * mad if mad > 0 else (float(np.std(tail)) or 1.0)
    thr = floor + 1.0 * scale
    sm = np.convolve(lnC, np.ones(3) / 3, mode='same')
    n_min = max(2, int(0.02 * M))
    run = max(3, int(0.05 * M))
    cutoff = None
    for i in range(n_min, M - run):
        if np.all(sm[i:i + run] <= thr):
            cutoff = i
            break
    if cutoff is None:
        cutoff = max(n_min, M - run - 1)
    return int(cutoff), floor, thr


def fft_contributions(coeffs, N):
    """Per-coefficient contribution of each Fourier term to the spectrum.
    Returns (contrib [M x N], vmax) — the window's middle FFT map."""
    M = len(coeffs)
    contrib = np.zeros((M, N))
    for k in range(M):
        v = np.zeros(M, dtype=complex)
        v[k] = coeffs[k]
        contrib[k] = np.fft.irfft(v, n=N)
    amp = np.abs(contrib[1:]) if M > 1 else np.abs(contrib)
    vmax = float(np.max(amp)) if amp.size and np.max(amp) > 0 else 1.0
    return contrib, vmax


def wav_max_level(N, wavelet='sym8'):
    try:
        import pywt
        return max(1, min(12, pywt.dwt_max_level(N, pywt.Wavelet(wavelet).dec_len)))
    except Exception:
        return 6


def wav_decompose(d, wavelet, level, mode, k):
    """Wavelet shrinkage of *d*. Returns (filtered d, aux) where aux holds
    the coefficients, thresholded coefficients, threshold and used level."""
    import pywt
    N = len(d)
    lvl = max(1, min(level, pywt.dwt_max_level(N, pywt.Wavelet(wavelet).dec_len)))
    cof = pywt.wavedec(d, wavelet, level=lvl)
    sigma = np.median(np.abs(cof[-1])) / 0.6745
    thr = sigma * np.sqrt(2 * np.log(max(N, 2))) * k
    new = [cof[0]] + [pywt.threshold(c, thr, mode=mode) for c in cof[1:]]
    rec = pywt.waverec(new, wavelet)[:N]
    return rec, {'cof': cof, 'new': new, 'thr': thr, 'lvl': lvl}


def vmd_auto_K_keep(d, alpha):
    """Pick the number of modes K and the kept count using the SAME signal/noise
    boundary as the FFT method: the frequency f_c at which ln|C_n| drops into the
    noise floor. The signal occupies frequencies below f_c (this holds for narrow
    core levels AND for surveys whose sharp lines reach high frequencies), so:
      - K scales with f_c (complex/wide spectra need more modes);
      - keep = the number of VMD modes whose centre frequency is below f_c.
    Returns (K, keep)."""
    N = len(d)
    coeffs = np.fft.rfft(d)
    lnC = ln_coeffs(coeffs)
    nc, _, _ = fft_recommended(lnC, len(coeffs))
    fc = nc / float(N)                                  # cycles per point (0..0.5)
    K = int(np.clip(round(fc * 30) + 8, 10, 20))
    _, omega = vmd(d, alpha, K)
    keep = int(np.clip(np.sum(np.sort(omega) <= fc), 1, K))
    return K, keep


def vmd_modes(d, alpha, K, N=None):
    """Run VMD and pad/truncate the modes to N columns."""
    N = len(d) if N is None else N
    modes, omega = vmd(d, alpha, K)
    if modes.shape[1] < N:
        modes = np.pad(modes, ((0, 0), (0, N - modes.shape[1])), mode='edge')
    elif modes.shape[1] > N:
        modes = modes[:, :N]
    return modes, omega


# ----------------------------------------------------------------------
# Public entry points
# ----------------------------------------------------------------------
def denoise(x, y, params):
    """Compute the denoised spectrum for arbitrary (x, y) with explicit params.
    Returns y_filtered (np.array)."""
    y = np.asarray(y, dtype=float)
    N = len(y)
    base = np.linspace(y[0], y[-1], N)
    d = y - base
    method = params['method']
    if method == "FFT filter":
        coeffs = np.fft.rfft(d)
        H = fft_build_filter(len(coeffs), params['cutoff'], params['slope'])
        return np.fft.irfft(coeffs * H, n=N) + base
    if method == "Wavelet":
        rec, _ = wav_decompose(d, params['wavelet'], params['level'],
                               params['mode'], params['k'])
        return rec + base
    if method == "VMD":
        modes, omega = vmd(d, params['alpha'], params['K'])
        if modes.shape[1] < N:
            modes = np.pad(modes, ((0, 0), (0, N - modes.shape[1])), mode='edge')
        order = np.argsort(omega)
        keep = order[:max(1, min(params['keep'], len(order)))]
        return modes[keep].sum(axis=0) + base
    return y.copy()


def auto_params(x, y, method, current=None):
    """Recommended params for arbitrary (x, y).

    *current* carries the controls the window keeps as they are when it
    auto-tunes: the FFT slope, the wavelet / mode, and the VMD bandwidth
    — exactly as KherveFitting's ``_auto_params``."""
    cur = dict(DEFAULTS.get(method, {}))
    cur.update(current or {})
    y = np.asarray(y, dtype=float)
    N = len(y)
    d = y - np.linspace(y[0], y[-1], N)
    if method == "FFT filter":
        coeffs = np.fft.rfft(d)
        cutoff, _, _ = fft_recommended(ln_coeffs(coeffs), len(coeffs))
        return {'method': method, 'cutoff': cutoff, 'slope': float(cur['slope'])}
    if method == "Wavelet":
        import pywt
        lvl = min(4, pywt.dwt_max_level(N, pywt.Wavelet(cur['wavelet']).dec_len))
        return {'method': method, 'wavelet': cur['wavelet'],
                'level': max(1, lvl), 'mode': cur['mode'], 'k': 1.0}
    if method == "VMD":
        alpha = float(cur['alpha'])
        K, keep = vmd_auto_K_keep(d, alpha)
        return {'method': method, 'K': K, 'alpha': alpha, 'keep': keep}
    return {'method': method}


def full_params(method, /, **values):
    """A complete parameter dict for *method*: the defaults overlaid with
    *values* (unknown keys are ignored)."""
    if method not in METHODS:
        raise ValueError(f"Unknown method {method!r}; choose one of {METHODS}")
    p = dict(DEFAULTS[method])
    for k in p:
        if k in values and values[k] is not None:
            p[k] = type(p[k])(values[k])
    p['method'] = method
    return p


def noise_estimate(y, y_filtered):
    """RMS of the residual and an SNR in dB (signal = denoised span)."""
    y = np.asarray(y, dtype=float)
    yf = np.asarray(y_filtered, dtype=float)
    r = y - yf
    rms = float(np.sqrt(np.mean(r ** 2))) if r.size else 0.0
    span = float(np.max(yf) - np.min(yf)) if yf.size else 0.0
    snr = float(20 * np.log10(span / rms)) if rms > 0 and span > 0 else float('inf')
    return {'residual_rms': rms, 'snr_db': snr}
