"""Fold BatchNorm parameters into the preceding Conv weights.

For each output channel ``co`` we compute::

    sigma_co = sqrt(running_var_co + eps)
    scale_co = gamma_co / sigma_co
    fused_w_co  = conv_w_co * scale_co            # broadcasting over (C_in, K, K)
    fused_b_co  = (conv_b_co - running_mean_co) * scale_co + beta_co

This produces an equivalent Conv-only layer whose forward pass matches
``conv -> BN`` at inference time. Pure NumPy, suitable for unit testing and
for the M1 PTQ pipeline (run_ptq.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import numpy as np


@dataclass
class BnParams:
    running_mean: np.ndarray   # (C_out,) float
    running_var:  np.ndarray   # (C_out,) float
    gamma:        np.ndarray   # (C_out,) float
    beta:         np.ndarray   # (C_out,) float
    eps:          float = 1e-5

    def __post_init__(self) -> None:
        n = self.running_mean.shape[0]
        for arr in (self.running_var, self.gamma, self.beta):
            if arr.shape != (n,):
                raise ValueError("BN parameter shape mismatch")
        if self.eps <= 0:
            raise ValueError("eps must be positive")


def fold(conv_w: np.ndarray,
         conv_b: np.ndarray | None,
         bn: BnParams) -> Tuple[np.ndarray, np.ndarray]:
    """Fuse ``conv (w, b)`` and ``bn`` into one ``(w', b')``.

    Parameters
    ----------
    conv_w :  float (C_out, C_in/groups, K, K)
    conv_b :  float (C_out,) or None
    bn     :  BnParams over C_out channels

    Returns
    -------
    (fused_w, fused_b)  both float; caller decides dtype/quantization later.
    """
    if conv_w.ndim != 4:
        raise ValueError(f"conv_w must be 4-D, got {conv_w.shape}")
    c_out = conv_w.shape[0]
    if c_out != bn.running_mean.shape[0]:
        raise ValueError(
            f"channel mismatch: conv C_out={c_out}, bn={bn.running_mean.shape[0]}"
        )
    if conv_b is None:
        conv_b = np.zeros((c_out,), dtype=conv_w.dtype)
    elif conv_b.shape != (c_out,):
        raise ValueError(f"conv_b shape {conv_b.shape} != ({c_out},)")

    sigma = np.sqrt(bn.running_var.astype(np.float64) + bn.eps)
    scale = bn.gamma.astype(np.float64) / sigma                  # (C_out,)

    fused_w = conv_w.astype(np.float64) * scale.reshape(-1, 1, 1, 1)
    fused_b = (conv_b.astype(np.float64) - bn.running_mean.astype(np.float64)) * scale \
              + bn.beta.astype(np.float64)
    return fused_w.astype(conv_w.dtype), fused_b.astype(conv_w.dtype)


def quantize_per_channel_weight(w_fp: np.ndarray,
                                bits: int = 8) -> Tuple[np.ndarray, np.ndarray]:
    """Symmetric per-output-channel weight quantization.

    Returns
    -------
    (w_int, scale)  where ``w_int`` is int8 with the same shape as ``w_fp``
    and ``scale`` is float (C_out,) such that ``w_fp ≈ w_int * scale.reshape(-1, 1, 1, 1)``.
    """
    if bits != 8:
        raise NotImplementedError("only 8-bit symmetric supported in M1")
    if w_fp.ndim != 4:
        raise ValueError(f"weight must be 4-D, got {w_fp.shape}")
    qmax = 127
    per_channel_max = np.maximum(np.abs(w_fp).reshape(w_fp.shape[0], -1).max(axis=1),
                                 1e-12)
    scale = per_channel_max / qmax                                # (C_out,)
    w_q = np.round(w_fp / scale.reshape(-1, 1, 1, 1)).clip(-qmax, qmax).astype(np.int8)
    return w_q, scale.astype(np.float32)


def compute_out_shift(weight_scale: np.ndarray,
                      input_scale: float,
                      output_scale: float) -> np.ndarray:
    """Compute per-channel right-shift amount so that
    ``y_int = (acc_int + bias_int) >> out_shift`` approximates
    ``acc_int * (weight_scale * input_scale / output_scale)``.

    Returns int8 ``out_shift[C_out]``. Negative shifts (left-shift) are not
    supported by the HLS arithmetic; caller must guarantee
    ``output_scale >= max(weight_scale) * input_scale`` or accept saturation.
    """
    if output_scale <= 0 or input_scale <= 0:
        raise ValueError("scales must be positive")
    if np.any(weight_scale <= 0):
        raise ValueError("weight_scale must be positive per channel")
    effective = weight_scale.astype(np.float64) * input_scale / output_scale
    # shift = round(-log2(effective))   (so that 1 / 2^shift ≈ effective)
    shift = np.round(-np.log2(effective)).astype(np.int8)
    shift = np.clip(shift, 0, 31).astype(np.int8)
    return shift
