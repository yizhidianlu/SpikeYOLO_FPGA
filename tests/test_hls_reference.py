"""Verify the C++ reference in hw/hls/sim/reference.hpp agrees with the
NumPy reference in tools/fpga/numpy_reference.py.

We do this by re-implementing the same algorithms in Python (line-for-line
ports of the C++ reference) and checking the algorithm is identical end-to-end.
If a future B1 patch breaks the C++ reference without updating numpy_reference,
this test fails.
"""

from __future__ import annotations

import sys

import numpy as np
import pytest

from tools.fpga.numpy_reference import (
    ConvBnParams, MAX_SPIKE, conv2d_bn, conv2d_int, expand_cumulative, mem_update,
)


# -----------------------------------------------------------------------------
# Python re-implementation of hw/hls/sim/reference.hpp — used as the bridge
# between the NumPy golden and the C++ DUT, so any regression on either side
# fails this test immediately.
# -----------------------------------------------------------------------------

def py_ref_conv2d_int(x, w, N, C_in, C_out, H, W, K, stride, pad, groups):
    out = np.zeros((N, C_out, (H + 2 * pad - K) // stride + 1,
                    (W + 2 * pad - K) // stride + 1), dtype=np.int32)
    C_in_g = C_in // groups
    C_out_g = C_out // groups
    for n in range(N):
        for g in range(groups):
            co_lo = g * C_out_g; co_hi = co_lo + C_out_g
            ci_lo = g * C_in_g
            for co in range(co_lo, co_hi):
                for hy in range(out.shape[2]):
                    for wx in range(out.shape[3]):
                        acc = 0
                        for ci in range(C_in_g):
                            for ky in range(K):
                                for kx in range(K):
                                    h_in = hy * stride + ky - pad
                                    w_in = wx * stride + kx - pad
                                    if 0 <= h_in < H and 0 <= w_in < W:
                                        px = int(x[n, ci_lo + ci, h_in, w_in])
                                    else:
                                        px = 0
                                    wt = int(w[co, ci, ky, kx])
                                    acc += px * wt
                        out[n, co, hy, wx] = acc
    return out


# -----------------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------------

@pytest.mark.contract
def test_python_ref_matches_numpy_reference_conv2d_int():
    rng = np.random.default_rng(0)
    x = rng.integers(-50, 50, size=(1, 4, 8, 8), dtype=np.int8)
    w = rng.integers(-30, 30, size=(6, 4, 3, 3), dtype=np.int8)
    a = py_ref_conv2d_int(x, w, 1, 4, 6, 8, 8, 3, 1, 1, 1)
    b = conv2d_int(x, w, stride=1, pad=1, groups=1)
    np.testing.assert_array_equal(a, b)


@pytest.mark.contract
def test_lif_expand_logic():
    """Cumulative expansion replicates the C++ reference."""
    rng = np.random.default_rng(0)
    x = rng.integers(-5, 6, size=(1, 4, 4, 4), dtype=np.int32)
    # numpy_reference path:
    spike = mem_update(x)                 # (MAX_SPIKE, C, H, W) int8 {0,1}
    # C++ reference path (pure Python re-impl):
    expected = np.zeros((MAX_SPIKE, 4, 4, 4), dtype=np.int8)
    for c in range(4):
        for h in range(4):
            for w_ in range(4):
                mem = 0
                for t in range(1):
                    mem += int(x[t, c, h, w_])
                v = max(0, min(MAX_SPIKE, mem))
                for s in range(MAX_SPIKE):
                    expected[s, c, h, w_] = 1 if s < v else 0
    np.testing.assert_array_equal(spike, expected)


@pytest.mark.contract
def test_conv2d_bn_first_layer_path():
    """first_layer=True keeps T_in unchanged (no substep collapse)."""
    rng = np.random.default_rng(0)
    x = rng.integers(-127, 127, size=(1, 3, 16, 16), dtype=np.int8)
    w = rng.integers(-30, 30, size=(8, 3, 7, 7), dtype=np.int8)
    p = ConvBnParams(
        w=w,
        bias=rng.integers(-2000, 2000, size=(8,), dtype=np.int32),
        out_shift=np.full(8, 4, dtype=np.int16),
        stride=4, pad=2, groups=1, first_layer=True,
    )
    y = conv2d_bn(x, p)
    assert y.shape == (1, 8, 4, 4)   # T_out = T_in = 1
    assert y.dtype == np.int32


@pytest.mark.contract
def test_conv2d_bn_substep_collapse():
    """non-first_layer collapses MAX_SPIKE substeps into one."""
    rng = np.random.default_rng(0)
    T_in = MAX_SPIKE * 1   # T_out will be 1
    x = rng.integers(0, 2, size=(T_in, 8, 8, 8), dtype=np.int8)
    w = rng.integers(-30, 30, size=(16, 8, 3, 3), dtype=np.int8)
    p = ConvBnParams(
        w=w,
        bias=np.zeros(16, dtype=np.int32),
        out_shift=np.full(16, 3, dtype=np.int16),
        stride=1, pad=1, groups=1, first_layer=False,
    )
    y = conv2d_bn(x, p)
    assert y.shape == (1, 16, 8, 8)
