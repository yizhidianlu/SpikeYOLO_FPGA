"""Activation calibration helpers.

Two search strategies:

* ``mse_min_scale`` — sweep candidate clip thresholds and pick the one that
  minimizes round-trip mean-squared error on quantized samples. Slow but
  robust; used by default for tiny_fpga since the model only has a handful
  of activation tensors (T=1).

* ``percentile_scale`` — pick the N-th percentile of |x| as the clip. Fast
  and surprisingly close on most layers; useful as a sanity check / fallback.

Both return a single scalar scale (per-tensor) suitable for the I-LIF/MultiSpike4
activations that already live in the [0, MAX_SPIKE] range. For the (rare)
non-spike tensors A1 may keep a per-channel variant in a follow-up.
"""

from __future__ import annotations

from typing import Iterable, Tuple

import numpy as np


def _fake_quant(x: np.ndarray, scale: float, qmin: int, qmax: int) -> np.ndarray:
    """Symmetric fake-quant: round-to-nearest then dequant."""
    if scale <= 0:
        return np.zeros_like(x)
    q = np.round(x / scale).clip(qmin, qmax)
    return q * scale


def mse_min_scale(samples: Iterable[np.ndarray],
                  bits: int = 8,
                  num_steps: int = 80) -> Tuple[float, float]:
    """Sweep ``scale`` in a log-spaced grid and pick the MSE-minimizing one.

    Returns ``(best_scale, best_mse)``.
    """
    qmax = (1 << (bits - 1)) - 1
    qmin = -qmax
    # Stack samples (each is a flat array). Cap total elements at 1 M to stay fast.
    flat = np.concatenate([s.ravel() for s in samples])
    if flat.size > 1_000_000:
        rng = np.random.default_rng(0)
        idx = rng.choice(flat.size, 1_000_000, replace=False)
        flat = flat[idx]
    max_abs = float(np.max(np.abs(flat)))
    if max_abs <= 0:
        return 1.0, 0.0
    # Search 1% .. 200% of (max_abs / qmax)
    centre = max_abs / qmax
    candidates = np.geomspace(0.01 * centre, 2.0 * centre, num=num_steps)
    best_scale = float(candidates[-1])
    best_mse = float("inf")
    for s in candidates:
        recon = _fake_quant(flat, float(s), qmin, qmax)
        mse = float(np.mean((flat - recon) ** 2))
        if mse < best_mse:
            best_mse = mse
            best_scale = float(s)
    return best_scale, best_mse


def percentile_scale(samples: Iterable[np.ndarray],
                     pct: float = 99.99,
                     bits: int = 8) -> float:
    qmax = (1 << (bits - 1)) - 1
    flat = np.concatenate([np.abs(s).ravel() for s in samples])
    if flat.size == 0:
        return 1.0
    clip = float(np.percentile(flat, pct))
    if clip <= 0:
        return 1.0
    return clip / qmax


def multispike4_scale() -> Tuple[float, int]:
    """Activations after I-LIF are clamped to [0, MAX_SPIKE=4]. No search
    needed — the scale is fixed and the zero-point is zero (unsigned).

    Returns ``(scale, zero_point)``. Scale = 1.0 means the activation is
    already integer-valued and lives directly in the int8 range.
    """
    return 1.0, 0
