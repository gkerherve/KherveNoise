"""Verbatim copy of KherveFitting's denoising maths (libraries/ToolsMenu/
FFT_Filter.py, KherveFittingPro), used only as the reference the tests
compare khervenoise.engine against. Do not edit; re-extract instead."""

import numpy as np

def vmd(signal, alpha, K, tau=0.0, DC=0, init=1, tol=1e-7, n_iter=500):
    """Decompose 'signal' into K band-limited modes.
    Returns (modes [K x L], omega [K] final centre frequencies)."""
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

    u_hat_plus = np.zeros((n_iter, len(freqs), K), dtype=complex)
    omega = np.zeros((n_iter, K))
    for i in range(K):
        omega[0, i] = (0.5 / K) * i
    if DC:
        omega[0, 0] = 0

    lambda_hat = np.zeros((n_iter, len(freqs)), dtype=complex)
    uDiff = tol + np.spacing(1)
    n = 0
    sum_uk = 0
    while uDiff > tol and n < n_iter - 1:
        k = 0
        sum_uk = u_hat_plus[n, :, K - 1] + sum_uk - u_hat_plus[n, :, 0]
        u_hat_plus[n + 1, :, k] = (f_hat_plus - sum_uk - lambda_hat[n, :] / 2) / \
                                  (1 + Alpha[k] * (freqs - omega[n, k]) ** 2)
        if not DC:
            omega[n + 1, k] = np.dot(freqs[T // 2:T], abs(u_hat_plus[n + 1, T // 2:T, k]) ** 2) / \
                              np.sum(abs(u_hat_plus[n + 1, T // 2:T, k]) ** 2)
        for k in range(1, K):
            sum_uk = u_hat_plus[n + 1, :, k - 1] + sum_uk - u_hat_plus[n, :, k]
            u_hat_plus[n + 1, :, k] = (f_hat_plus - sum_uk - lambda_hat[n, :] / 2) / \
                                      (1 + Alpha[k] * (freqs - omega[n, k]) ** 2)
            omega[n + 1, k] = np.dot(freqs[T // 2:T], abs(u_hat_plus[n + 1, T // 2:T, k]) ** 2) / \
                              np.sum(abs(u_hat_plus[n + 1, T // 2:T, k]) ** 2)
        lambda_hat[n + 1, :] = lambda_hat[n, :] + tau * (np.sum(u_hat_plus[n + 1, :, :], axis=1) - f_hat_plus)
        n += 1
        uDiff = np.spacing(1)
        for i in range(K):
            diff = u_hat_plus[n, :, i] - u_hat_plus[n - 1, :, i]
            uDiff = uDiff + (1.0 / T) * np.dot(diff, np.conj(diff))
        uDiff = np.abs(uDiff)

    n_used = min(n_iter, n)
    om = omega[n_used - 1, :]
    idxs = np.flip(np.arange(1, T // 2 + 1))
    u_hat = np.zeros((T, K), dtype=complex)
    u_hat[T // 2:T, :] = u_hat_plus[n_used - 1, T // 2:T, :]
    u_hat[idxs, :] = np.conj(u_hat_plus[n_used - 1, T // 2:T, :])
    u_hat[0, :] = np.conj(u_hat[-1, :])
    u = np.zeros((K, len(t)))
    for k in range(K):
        u[k, :] = np.real(np.fft.ifft(np.fft.ifftshift(u_hat[:, k])))
    u = u[:, T // 4:3 * T // 4]            # undo the mirror padding
    return u, om

class SpectralDenoisingWindow:
    @staticmethod
    def _fft_build_filter(M, n_c, slope):
        n = np.arange(M)
        sigma = max(1.5, n_c / slope)
        H = np.ones(M)
        m = n > n_c
        H[m] = np.exp(-0.5 * ((n[m] - n_c) / sigma) ** 2)
        return H

    @staticmethod
    def _fft_recommended(lnC, M):
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

    @staticmethod
    def _vmd_auto_K_keep(d, alpha):
        """Pick the number of modes K and the kept count using the SAME signal/noise
        boundary as the FFT method: the frequency f_c at which ln|C_n| drops into the
        noise floor. The signal occupies frequencies below f_c (this holds for narrow
        core levels AND for surveys whose sharp lines reach high frequencies), so:
          - K scales with f_c (complex/wide spectra need more modes);
          - keep = the number of VMD modes whose centre frequency is below f_c.
        This is robust where the earlier rules failed - the frequency gap breaks when
        signal modes cluster near 0, and a median-energy floor breaks for surveys where
        most modes are signal. Returns (K, keep)."""
        N = len(d)
        coeffs = np.fft.rfft(d)
        lnC = np.log(np.abs(coeffs) + 1e-12)
        nc, _, _ = SpectralDenoisingWindow._fft_recommended(lnC, len(coeffs))
        fc = nc / float(N)                                  # cycles per point (0..0.5)
        K = int(np.clip(round(fc * 30) + 8, 10, 20))
        _, omega = vmd(d, alpha, K)
        keep = int(np.clip(np.sum(np.sort(omega) <= fc), 1, K))
        return K, keep

    def _denoise(self, x, y, params):
        """Compute the denoised spectrum for arbitrary (x, y) with explicit params.
        Used by batch. Returns y_filtered (np.array)."""
        N = len(y)
        base = np.linspace(y[0], y[-1], N)
        d = y - base
        if params['method'] == "FFT filter":
            coeffs = np.fft.rfft(d)
            H = self._fft_build_filter(len(coeffs), params['cutoff'], params['slope'])
            return np.fft.irfft(coeffs * H, n=N) + base
        if params['method'] == "Wavelet":
            import pywt
            w, lvl, mode, k = params['wavelet'], params['level'], params['mode'], params['k']
            lvl = max(1, min(lvl, pywt.dwt_max_level(N, pywt.Wavelet(w).dec_len)))
            cof = pywt.wavedec(d, w, level=lvl)
            sigma = np.median(np.abs(cof[-1])) / 0.6745
            thr = sigma * np.sqrt(2 * np.log(max(N, 2))) * k
            new = [cof[0]] + [pywt.threshold(c, thr, mode=mode) for c in cof[1:]]
            return pywt.waverec(new, w)[:N] + base
        if params['method'] == "VMD":
            modes, omega = vmd(d, params['alpha'], params['K'])
            if modes.shape[1] < N:
                modes = np.pad(modes, ((0, 0), (0, N - modes.shape[1])), mode='edge')
            order = np.argsort(omega)
            keep = order[:max(1, min(params['keep'], len(order)))]
            return modes[keep].sum(axis=0) + base
        return y.copy()

