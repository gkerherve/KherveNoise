"""khervenoise.engine must reproduce KherveFitting's maths exactly.

tests/kf_reference.py is a verbatim copy of the original functions.
"""

import numpy as np
import pytest

from khervenoise import engine
from tests import kf_reference as ref

KF = ref.SpectralDenoisingWindow()


def _spectrum(n=301, seed=0, survey=False):
    rng = np.random.default_rng(seed)
    x = np.linspace(295, 280, n)
    y = 1000 + 30 * (x - 280)
    centres = [284.8, 286.3, 288.9] if not survey else np.linspace(282, 293, 9)
    for i, c in enumerate(centres):
        y += (5000 / (i + 1)) * np.exp(-0.5 * ((x - c) / 0.45) ** 2)
    return x, y + rng.normal(0, 60, n)


@pytest.mark.parametrize("n", [64, 201, 300, 513])
@pytest.mark.parametrize("K", [3, 6, 12])
def test_vmd_identical_to_original(n, K):
    _, y = _spectrum(n, seed=n + K)
    d = y - np.linspace(y[0], y[-1], n)
    u_ref, om_ref = ref.vmd(d, 2000.0, K)
    u, om = engine.vmd(d, 2000.0, K)
    np.testing.assert_array_equal(om, om_ref)
    np.testing.assert_array_equal(u, u_ref)


def test_vmd_short_run_identical():
    _, y = _spectrum(120, seed=4)
    for n_iter in (2, 3, 5):
        u_ref, om_ref = ref.vmd(y, 500.0, 4, n_iter=n_iter)
        u, om = engine.vmd(y, 500.0, 4, n_iter=n_iter)
        np.testing.assert_array_equal(u, u_ref)
        np.testing.assert_array_equal(om, om_ref)


@pytest.mark.parametrize("M", [3, 8, 40, 151])
def test_fft_recommended_and_filter(M):
    _, y = _spectrum(2 * M, seed=M)
    lnC = np.log(np.abs(np.fft.rfft(y - np.linspace(y[0], y[-1], len(y)))) + 1e-12)[:M]
    assert engine.fft_recommended(lnC, M) == KF._fft_recommended(lnC, M)
    for nc, slope in ((1, 3.0), (7, 0.5), (M // 2, 20.0)):
        np.testing.assert_array_equal(engine.fft_build_filter(M, nc, slope),
                                      KF._fft_build_filter(M, nc, slope))


PARAMS = [
    {'method': 'FFT filter', 'cutoff': 12, 'slope': 3.0},
    {'method': 'FFT filter', 'cutoff': 1, 'slope': 0.5},
    {'method': 'Wavelet', 'wavelet': 'sym8', 'level': 3, 'mode': 'soft', 'k': 1.0},
    {'method': 'Wavelet', 'wavelet': 'db4', 'level': 12, 'mode': 'hard', 'k': 2.5},
    {'method': 'Wavelet', 'wavelet': 'coif5', 'level': 2, 'mode': 'soft', 'k': 0.3},
    {'method': 'VMD', 'K': 6, 'alpha': 2000.0, 'keep': 3},
    {'method': 'VMD', 'K': 10, 'alpha': 500.0, 'keep': 1},
]


@pytest.mark.parametrize("params", PARAMS)
@pytest.mark.parametrize("n", [200, 301])
def test_denoise_identical(params, n):
    x, y = _spectrum(n, seed=n)
    np.testing.assert_array_equal(engine.denoise(x, y, params),
                                  KF._denoise(x, y, params))


@pytest.mark.parametrize("survey", [False, True])
def test_vmd_auto_identical(survey):
    _, y = _spectrum(400, seed=9, survey=survey)
    d = y - np.linspace(y[0], y[-1], len(y))
    assert engine.vmd_auto_K_keep(d, 2000.0) == \
        ref.SpectralDenoisingWindow._vmd_auto_K_keep(d, 2000.0)


def test_auto_params_shapes():
    x, y = _spectrum(300)
    for m in engine.METHODS:
        p = engine.auto_params(x, y, m)
        assert p['method'] == m
        out = engine.denoise(x, y, p)
        assert out.shape == y.shape
        assert np.std(y - out) < np.std(y - np.mean(y))


def test_full_params_rejects_unknown_method():
    with pytest.raises(ValueError):
        engine.full_params("Median")
    p = engine.full_params("VMD", K="8", keep=2)
    assert p == {'K': 8, 'alpha': 2000.0, 'keep': 2, 'method': 'VMD'}
