"""
NumPy bit-exact reference for SpikeYOLO tiny_fpga.

This is the golden reference the HLS C-sim must match exactly.
Algorithms mirror ultralytics/nn/modules/yolo_spikformer_bin.py but drop
PyTorch entirely so each primitive can be ported to HLS C++ line-for-line.

Tensor conventions
------------------
- Spiking tensors carry an explicit time-step axis `T` as the leading dim:
    x.shape == (T, C, H, W)            (single batch assumed; B=1)
- Binary spike tensors hold values in {0, 1} stored as int8.
- Membrane / accumulator tensors are int32.
- Weights are int8, biases int32, per-output-channel scale is int32 (shift form).

Quantization scheme
-------------------
Post-PTQ we represent every Conv2d_bn as  (w_i8, b_i32, out_shift, out_zp=0).
Forward:
    acc_i32 = conv_int(spike_i8, w_i8)             # signed int32 accumulator
    acc_i32 = sum over 4 binary-spike substeps     # happens inside Conv2d_bn
    y_i32   = (acc_i32 + b_i32) >> out_shift       # fused BN scale, per-channel
    y_i8    = clamp(y_i32, -128, 127)              # stored int8 membrane
The LIF that follows clamps y_i8 to [0, 4] then re-expands to 4 binary spikes.

Public surface
--------------
- mem_update / expand_cumulative        -- spiking neuron
- conv2d_int                            -- int8 x int8 -> int32 conv
- conv2d_bn                             -- fused post-PTQ Conv2d_bn
- ms_downsampling / ms_standard_conv    -- block-level primitives
- sep_conv / ms_all_conv_block          -- composite blocks used in tiny_fpga
- spike_sppf                            -- cascaded 5x5 max-pool branch
- TinyFpgaNet                           -- full forward for the tiny_fpga YAML

All functions are side-effect free and accept explicit weight dicts, so they
can be unit-tested against PyTorch intermediate tensors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np


# -----------------------------------------------------------------------------
# Spiking primitives
# -----------------------------------------------------------------------------

MAX_SPIKE = 4  # MultiSpike4: membrane clamped to [0, 4] -> expands to 4 bits


def expand_cumulative(spike: np.ndarray, max_value: int = MAX_SPIKE) -> np.ndarray:
    """Convert an integer spike tensor in [0, max_value] to a binary spike train.

    Input:
        spike : int8 [T, C, H, W]  with values in {0,..,max_value}
    Output:
        binary: int8 [T * max_value, C, H, W]  values in {0, 1}

    For a voxel with value v, the first v substeps are 1, the rest are 0.
    Matches `expand_tensor_cumulative` in yolo_spikformer_bin.py:43.
    """
    assert spike.dtype == np.int8
    T, C, H, W = spike.shape
    steps = np.arange(max_value, dtype=np.int8).reshape(max_value, 1, 1, 1, 1)
    expanded = spike[np.newaxis, ...]                     # (1, T, C, H, W)
    binary = (steps < expanded).astype(np.int8)           # (max_value, T, C, H, W)
    binary = np.transpose(binary, (1, 0, 2, 3, 4))        # (T, max_value, C, H, W)
    return binary.reshape(T * max_value, C, H, W)


def mem_update(x: np.ndarray) -> np.ndarray:
    """I-LIF neuron (binary-inference form).

    Input:
        x : int32 [T, C, H, W]  accumulated integer feature map
    Output:
        binary : int8 [T * MAX_SPIKE, C, H, W]  values in {0, 1}

    Steps (mirrors `mem_update.forward` in yolo_spikformer_bin.py:33):
        1. Sum over the T axis to collapse to a single membrane potential frame.
        2. Clamp to [0, MAX_SPIKE] and cast to int8 (quantization: MultiSpike4).
        3. Expand the integer count into MAX_SPIKE binary spikes.
    """
    assert x.dtype == np.int32
    mem = x.sum(axis=0, keepdims=True)                    # (1, C, H, W) int32
    spike = np.clip(mem, 0, MAX_SPIKE).astype(np.int8)    # (1, C, H, W) int8
    return expand_cumulative(spike)                       # (MAX_SPIKE, C, H, W) int8


# -----------------------------------------------------------------------------
# Int convolution primitive
# -----------------------------------------------------------------------------

def _pad2d(x: np.ndarray, pad: int) -> np.ndarray:
    """Zero-pad on (H, W). x shape: (N, C, H, W)."""
    if pad == 0:
        return x
    return np.pad(x, ((0, 0), (0, 0), (pad, pad), (pad, pad)))


def conv2d_int(x: np.ndarray, w: np.ndarray, stride: int, pad: int,
               groups: int = 1) -> np.ndarray:
    """int8 feature-map x int8 weight -> int32 accumulator.

    Input shapes:
        x : int8 [N, C_in, H, W]
        w : int8 [C_out, C_in/groups, K, K]
    Output:
        y : int32 [N, C_out, H_out, W_out]

    Plain im2col implementation; speed is irrelevant -- this is the golden
    reference. Groups supports depth-wise conv (groups == C_in == C_out).
    """
    assert x.dtype == np.int8 and w.dtype == np.int8
    N, C_in, H, W = x.shape
    C_out, C_in_g, K, K2 = w.shape
    assert K == K2, "only square kernels"
    assert C_in_g == C_in // groups
    assert C_out % groups == 0

    xp = _pad2d(x.astype(np.int32), pad)                  # promote once
    H_out = (H + 2 * pad - K) // stride + 1
    W_out = (W + 2 * pad - K) // stride + 1
    y = np.zeros((N, C_out, H_out, W_out), dtype=np.int32)

    wg = C_out // groups
    for g in range(groups):
        c_in_lo = g * C_in_g
        c_in_hi = c_in_lo + C_in_g
        c_out_lo = g * wg
        c_out_hi = c_out_lo + wg
        w_g = w[c_out_lo:c_out_hi].astype(np.int32)       # (wg, C_in_g, K, K)
        for ky in range(K):
            for kx in range(K):
                # slice contribution from kernel position (ky, kx)
                xs = xp[:, c_in_lo:c_in_hi,
                        ky:ky + H_out * stride:stride,
                        kx:kx + W_out * stride:stride]     # (N, C_in_g, H_out, W_out)
                # einsum: (N, c_in, H, W) x (wg, c_in, 1, 1) -> (N, wg, H, W)
                y[:, c_out_lo:c_out_hi] += np.einsum(
                    'ncij,mc->nmij', xs, w_g[:, :, ky, kx]
                )
    return y


# -----------------------------------------------------------------------------
# Fused Conv2d_bn (BN pre-folded into int weight scale + bias)
# -----------------------------------------------------------------------------

@dataclass
class ConvBnParams:
    """Post-PTQ fused parameters for a single Conv2d_bn.

    w          : int8 [C_out, C_in/groups, K, K]
    bias       : int32 [C_out]   -- folded (BN bias + weight*input_zero_point drift)
    out_shift  : int  [C_out]    -- right-shift amount per channel (BN scale)
    stride, pad, groups, kernel : layout info
    first_layer: True for the stem (no sum-over-4 before BN)
    """
    w: np.ndarray
    bias: np.ndarray
    out_shift: np.ndarray
    stride: int
    pad: int
    groups: int = 1
    first_layer: bool = False

    def __post_init__(self):
        assert self.w.dtype == np.int8, f"weight dtype {self.w.dtype}"
        assert self.bias.dtype == np.int32, f"bias dtype {self.bias.dtype}"
        assert self.out_shift.dtype in (np.int8, np.int16, np.int32)
        assert self.w.shape[0] == self.bias.shape[0] == self.out_shift.shape[0]


def conv2d_bn(x: np.ndarray, p: ConvBnParams) -> np.ndarray:
    """Run a fused Conv2d_bn.  Returns int32 pre-LIF feature map [T, C, H, W].

    Semantics (mirrors Conv2d_bn.forward in yolo_spikformer_bin.py:166):
        x [T_spike, C, H, W] int8  (binary spikes; or uint8-cast input for stem)
        -> conv (N = T_spike as batch)
        -> if not first_layer: reshape to [MAX_SPIKE, T_out, C, H, W] and sum dim=0
                            (collapses the 4 binary substeps emitted by the
                             upstream LIF back into one integer frame)
        -> add bias
        -> arithmetic right-shift by out_shift (per-channel BN scale)
        -> return int32 (caller clips in mem_update)
    """
    assert x.dtype == np.int8, f"conv input must be int8, got {x.dtype}"
    T_in = x.shape[0]

    y = conv2d_int(x, p.w, p.stride, p.pad, p.groups)     # (T_in, C, H, W) int32

    if not p.first_layer:
        assert T_in % MAX_SPIKE == 0, f"T_in={T_in} must be multiple of {MAX_SPIKE}"
        T_out = T_in // MAX_SPIKE
        y = y.reshape(MAX_SPIKE, T_out, *y.shape[1:]).sum(axis=0)
    # else: T_in == 1 (raw image), no collapse.

    # Fused BN: y = (y + bias) >> shift, per output channel.
    b = p.bias.reshape(1, -1, 1, 1)
    s = p.out_shift.astype(np.int32).reshape(1, -1, 1, 1)
    # Use floor-shift (arithmetic shift right) to match HLS semantics.
    y = (y + b) >> s
    return y.astype(np.int32)


# -----------------------------------------------------------------------------
# Block-level primitives (pure fns, take weight dicts)
# -----------------------------------------------------------------------------

def ms_downsampling(x: np.ndarray, cbn: ConvBnParams) -> np.ndarray:
    """MS_DownSampling.  Input may be raw uint8 image (first layer) or spikes.

    - first_layer=True:   x is int8 [1, 3, H, W]  (raw normalized image)
    - first_layer=False:  x is int32 [T, C, H, W]  from previous layer -> LIF first.
    Returns int32 [T, C, H, W] pre-LIF output.
    """
    if cbn.first_layer:
        assert x.dtype == np.int8
        return conv2d_bn(x, cbn)
    assert x.dtype == np.int32
    spk = mem_update(x)                                   # -> int8 [T*4, C, H, W]
    return conv2d_bn(spk, cbn)


def ms_standard_conv(x: np.ndarray, cbn: ConvBnParams) -> np.ndarray:
    """MS_StandardConv.  Always non-first-layer."""
    assert x.dtype == np.int32
    spk = mem_update(x)
    return conv2d_bn(spk, cbn)


def sep_conv(x: np.ndarray, params: Dict[str, ConvBnParams]) -> np.ndarray:
    """SepConv (PW expansion -> DW -> PW reduction -> DW group=C).

    params keys: 'pwconv1', 'dwconv2', 'pwconv3', 'dwconv4'
    """
    x = ms_standard_conv(x, params['pwconv1'])
    x = ms_standard_conv(x, params['dwconv2'])
    x = ms_standard_conv(x, params['pwconv3'])
    x = ms_standard_conv(x, params['dwconv4'])
    return x


def ms_all_conv_block(x: np.ndarray,
                      sep_params: Dict[str, ConvBnParams],
                      conv1: ConvBnParams,
                      conv2: ConvBnParams) -> np.ndarray:
    """MS_AllConvBlock = shortcut(SepConv) + shortcut(conv1 -> conv2).

    Mirrors yolo_spikformer_bin.py:468.
    """
    x = sep_conv(x, sep_params) + x                       # residual 1
    x_feat = x
    x = ms_standard_conv(x, conv1)
    x = ms_standard_conv(x, conv2)
    return x + x_feat                                     # residual 2


def maxpool2d_spike(x: np.ndarray, k: int) -> np.ndarray:
    """MaxPool on a binary spike tensor (k x k, stride 1, same padding).

    For binary {0,1} input this is a 25-bit OR reduction -- no DSP on FPGA.
    Input/Output: int8 [T, C, H, W].
    """
    assert x.dtype == np.int8
    pad = k // 2
    xp = _pad2d(x, pad)
    T, C, H, W = x.shape
    out = np.zeros_like(x)
    for dy in range(k):
        for dx in range(k):
            out = np.maximum(out, xp[:, :, dy:dy + H, dx:dx + W])
    return out


def spike_sppf(x: np.ndarray,
               cv1: ConvBnParams,
               cv2: ConvBnParams,
               k: int = 5) -> np.ndarray:
    """SpikeSPPF: cv1 -> 3x cascaded MaxPool -> concat(C-dim) -> cv2.

    Mirrors yolo_spikformer_bin.py:574 but on int tensors.  For the tiny_fpga
    variant the plan keeps a *single* 5x5 stage; set k accordingly.
    """
    x = ms_standard_conv(x, cv1)                          # int32 pre-LIF
    # Pool branches operate on the spike of x; emulate the PyTorch path:
    spk = mem_update(x)                                   # int8 [T*4, C, H, W]
    y1 = maxpool2d_spike(spk, k)
    y2 = maxpool2d_spike(y1, k)
    y3 = maxpool2d_spike(y2, k)
    concat = np.concatenate([spk, y1, y2, y3], axis=1)    # channel-cat on binary
    # Collapse 4 binary substeps back to int32 frame for cv2.
    T4, C, H, W = concat.shape
    assert T4 % MAX_SPIKE == 0
    T = T4 // MAX_SPIKE
    concat_i32 = (concat.reshape(MAX_SPIKE, T, C, H, W)
                  .sum(axis=0).astype(np.int32))
    return ms_standard_conv(concat_i32, cv2)


# -----------------------------------------------------------------------------
# Full network for the tiny_fpga YAML
# -----------------------------------------------------------------------------

@dataclass
class TinyFpgaNet:
    """Runs the full snn_yolov8_tiny_fpga model on int tensors.

    Weights are expected in a dict keyed by layer index (matching the YAML):
        weights[1]  = {'encode_conv': ConvBnParams}          # stem
        weights[2]  = {'sep': {...}, 'conv1': ..., 'conv2': ..., '...'}  # AllConvBlock
        ...
    Use `tools/fpga/fold_bn.py::export_layer_params` to populate.
    """
    weights: Dict[int, Dict]
    nc: int = 80

    def forward_backbone(self, img_i8: np.ndarray) -> np.ndarray:
        """Run layers 0..7 of the tiny_fpga YAML. Returns int32 backbone feature."""
        # Layer 0: MS_GetT -> just add a T=1 axis; dtype stays int8 for stem.
        x = img_i8[np.newaxis, ...]                       # (1, 3, H, W) int8

        # Layer 1: MS_DownSampling, first_layer=True  (stem 7x7 s=4)
        x = ms_downsampling(x, self.weights[1]['encode_conv'])    # int32 [1, C, H/4, W/4]

        # Layer 2: MS_AllConvBlock depth=1
        x = ms_all_conv_block(x,
                              self.weights[2]['sep'],
                              self.weights[2]['conv1'],
                              self.weights[2]['conv2'])

        # Layer 3: MS_DownSampling stride 2
        x = ms_downsampling(x, self.weights[3]['encode_conv'])

        # Layer 4: MS_AllConvBlock depth=2
        for sub in self.weights[4]:
            x = ms_all_conv_block(x, sub['sep'], sub['conv1'], sub['conv2'])

        # Layer 5: MS_DownSampling stride 2
        x = ms_downsampling(x, self.weights[5]['encode_conv'])

        # Layer 6: MS_AllConvBlock depth=2
        for sub in self.weights[6]:
            x = ms_all_conv_block(x, sub['sep'], sub['conv1'], sub['conv2'])

        # Layer 7: SpikeSPPF  (single k=5 stage; cascade still runs inside helper)
        x = spike_sppf(x, self.weights[7]['cv1'], self.weights[7]['cv2'], k=5)
        return x

    def forward_head(self, x: np.ndarray) -> np.ndarray:
        """Run layers 8..9.  Final SpikeDetect runs on PS, not here."""
        x = ms_standard_conv(x, self.weights[8]['conv'])          # reduce
        x = ms_all_conv_block(x,
                              self.weights[9]['sep'],
                              self.weights[9]['conv1'],
                              self.weights[9]['conv2'])
        return x                                                  # int32 pre-LIF

    def forward(self, img_i8: np.ndarray) -> np.ndarray:
        return self.forward_head(self.forward_backbone(img_i8))


# -----------------------------------------------------------------------------
# Utility: load packed weights
# -----------------------------------------------------------------------------

def load_weights(path: str) -> Dict[int, Dict]:
    """Load weights.npz produced by tools/fpga/fold_bn.py.

    Expected keys follow the pattern:
        'L{idx}.{sub}.{field}'    e.g. 'L1.encode_conv.w', 'L1.encode_conv.bias'
                                       'L2.sep.pwconv1.w', ...
    Returns the nested dict consumed by TinyFpgaNet.
    """
    raw = dict(np.load(path, allow_pickle=True))
    out: Dict[int, Dict] = {}
    for key, arr in raw.items():
        # Skip metadata keys emitted by weight_packer (e.g. __layout__).
        if key.startswith('__'):
            continue
        # Format: "L<idx>.<path>.<field>"
        head, _, field = key.rpartition('.')
        assert head.startswith('L'), f"bad key: {key}"
        idx_str, _, sub = head.partition('.')
        idx = int(idx_str[1:])
        node = out.setdefault(idx, {})
        for part in sub.split('.'):
            if part:
                node = node.setdefault(part, {})
        node[field] = arr

    # Convert terminal {w, bias, out_shift, stride, pad, groups, first_layer} dicts
    # into ConvBnParams.
    def _finalize(d):
        if isinstance(d, dict) and 'w' in d and 'bias' in d:
            return ConvBnParams(
                w=d['w'].astype(np.int8),
                bias=d['bias'].astype(np.int32),
                out_shift=d['out_shift'].astype(np.int16),
                stride=int(d['stride']),
                pad=int(d['pad']),
                groups=int(d.get('groups', 1)),
                first_layer=bool(d.get('first_layer', 0)),
            )
        if isinstance(d, dict):
            return {k: _finalize(v) for k, v in d.items()}
        return d

    return _finalize(out)


if __name__ == '__main__':
    # Quick self-check: exercise the spiking primitives with known patterns.
    mem = np.array([[[[0, 1, 2], [3, 4, 5]]]], dtype=np.int32)  # (1, 1, 2, 3)
    mem_T = mem.reshape(1, 1, 2, 3)                             # T=1
    spk = mem_update(mem_T)
    print("mem in :", mem_T.squeeze())
    print("spikes :", spk.squeeze())   # expect 4 binary substeps, column 4->[1,1,1,1], col 5 also
    print("sanity : sum over substeps matches clamp(mem,0,4):",
          (spk.sum(0) == np.clip(mem_T[0], 0, MAX_SPIKE)).all())
