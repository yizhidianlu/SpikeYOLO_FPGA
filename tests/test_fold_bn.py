"""Unit tests for tools.quant.fold_bn and tools.quant.calibrate.

Verify that folding a Conv+BN pair is numerically equivalent to running the
two-stage forward, and that calibration scales fall in sensible ranges.
"""

from __future__ import annotations

import numpy as np
import pytest

from tools.quant.fold_bn import (
    BnParams, compute_out_shift, fold, quantize_per_channel_weight,
)
from tools.quant.calibrate import (
    mse_min_scale, multispike4_scale, percentile_scale,
)


# -----------------------------------------------------------------------------
# fold_bn
# -----------------------------------------------------------------------------

def _forward_conv_bn(x, conv_w, conv_b, bn):
    """Reference: conv (no padding/stride for simplicity) -> BN."""
    out = np.tensordot(x, conv_w, axes=([1, 2, 3], [1, 2, 3]))  # (N, C_out)
    if conv_b is not None:
        out = out + conv_b
    # BN: (out - mean) / sqrt(var+eps) * gamma + beta
    sigma = np.sqrt(bn.running_var + bn.eps)
    return (out - bn.running_mean) / sigma * bn.gamma + bn.beta


@pytest.mark.contract
def test_fold_bn_equivalence_1x1():
    rng = np.random.default_rng(0)
    C_in, C_out = 3, 4
    conv_w = rng.standard_normal((C_out, C_in, 1, 1)).astype(np.float64)
    conv_b = rng.standard_normal((C_out,)).astype(np.float64)
    bn = BnParams(
        running_mean=rng.standard_normal((C_out,)),
        running_var=np.abs(rng.standard_normal((C_out,))) + 0.1,
        gamma=rng.standard_normal((C_out,)),
        beta=rng.standard_normal((C_out,)),
        eps=1e-5,
    )
    # spatial dims = 1x1 to keep tensordot simple
    x = rng.standard_normal((2, C_in, 1, 1))

    ref_out = _forward_conv_bn(x, conv_w, conv_b, bn)

    fw, fb = fold(conv_w, conv_b, bn)
    fused = np.tensordot(x, fw, axes=([1, 2, 3], [1, 2, 3])) + fb
    np.testing.assert_allclose(fused, ref_out, rtol=1e-9, atol=1e-9)


@pytest.mark.contract
def test_fold_bn_zero_bias():
    """When conv_b is None we treat it as zero — verify same answer."""
    rng = np.random.default_rng(1)
    C_in, C_out = 2, 2
    conv_w = rng.standard_normal((C_out, C_in, 1, 1))
    bn = BnParams(
        running_mean=np.zeros(C_out), running_var=np.ones(C_out),
        gamma=np.ones(C_out), beta=np.zeros(C_out), eps=1e-5,
    )
    fw_none, fb_none = fold(conv_w, None, bn)
    fw_zero, fb_zero = fold(conv_w, np.zeros(C_out), bn)
    np.testing.assert_array_equal(fw_none, fw_zero)
    np.testing.assert_array_equal(fb_none, fb_zero)


@pytest.mark.contract
def test_fold_rejects_shape_mismatch():
    conv_w = np.zeros((4, 3, 1, 1))
    bn = BnParams(np.zeros(5), np.ones(5), np.ones(5), np.zeros(5))  # 5 != 4
    with pytest.raises(ValueError, match="channel mismatch"):
        fold(conv_w, None, bn)


@pytest.mark.contract
def test_quantize_per_channel_weight_recovers():
    rng = np.random.default_rng(2)
    w = rng.standard_normal((6, 3, 3, 3)).astype(np.float32)
    w_q, scale = quantize_per_channel_weight(w)
    assert w_q.dtype == np.int8
    assert scale.shape == (6,)
    recon = w_q.astype(np.float32) * scale.reshape(-1, 1, 1, 1)
    # max abs error <= half a quant step per channel
    per_ch_err = np.max(np.abs(w - recon).reshape(6, -1), axis=1)
    per_ch_step = scale
    assert (per_ch_err <= per_ch_step * 1.01).all(), (per_ch_err, per_ch_step)


@pytest.mark.contract
def test_compute_out_shift_increases_for_smaller_effective():
    """Smaller effective scale => more right-shift (larger shift value)."""
    weight_scale = np.array([0.01, 0.001, 0.0001], dtype=np.float32)
    shift = compute_out_shift(weight_scale, input_scale=1.0, output_scale=1.0)
    assert shift[0] < shift[1] < shift[2]
    assert shift.dtype == np.int8


# -----------------------------------------------------------------------------
# calibrate
# -----------------------------------------------------------------------------

@pytest.mark.contract
def test_mse_min_scale_picks_reasonable_value():
    rng = np.random.default_rng(0)
    # Activations drawn from a heavy-tailed distribution
    samples = [rng.standard_normal((1024,)) * 3.0 for _ in range(4)]
    scale, mse = mse_min_scale(samples)
    # Scale must be positive, less than max_abs / qmax * 2 ceiling
    max_abs = max(np.max(np.abs(s)) for s in samples)
    assert 0 < scale <= max_abs / 127 * 2.0
    assert mse >= 0


@pytest.mark.contract
def test_percentile_scale_smaller_than_max_for_outliers():
    rng = np.random.default_rng(0)
    samples = [rng.standard_normal((10_000,))]
    samples[0][0] = 100.0    # outlier
    scale_99 = percentile_scale(samples, pct=99.0)
    max_abs = float(np.max(np.abs(samples[0])))
    # 99th percentile should drop the outlier
    assert scale_99 * 127 < max_abs


@pytest.mark.contract
def test_multispike4_scale_constant():
    scale, zp = multispike4_scale()
    assert scale == 1.0
    assert zp == 0
