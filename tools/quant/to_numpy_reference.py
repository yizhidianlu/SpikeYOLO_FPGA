"""Bridge weight_packer .npz -> TinyFpgaNet weights dict.

weight_packer writes a flat ``L00..LNN`` schema (with ``__layout__`` and
``__meta__`` arrays carrying stride/pad/groups/kind), while
``tools.fpga.numpy_reference.TinyFpgaNet`` expects a nested dict keyed by
YAML layer index (1..9) with sub-paths like ``weights[2]['sep']['pwconv1']``
and ``weights[4]`` as a list of AllConvBlock dicts.

This module hardcodes the PTQ-enumeration -> YAML-path mapping for the
tiny_fpga YAML scale ``[0.25, 0.1875, 256]`` (depth-scaled to 1 for every
MS_AllConvBlock; 30 quantized convs feed forward_backbone + forward_head;
the trailing SpikeDetect head convs in the .npz are not consumed by
TinyFpgaNet.forward and are silently dropped).

Usage:
    from tools.quant.to_numpy_reference import load_for_tinyfpga
    weights = load_for_tinyfpga("models/tiny_fpga_int8_pbt.npz")
    net = TinyFpgaNet(weights=weights)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Sequence, Union

import numpy as np

from tools.fpga.numpy_reference import ConvBnParams
from tools.quant.weight_packer import LayerEntry, read_npz


# PTQ-enumerated index -> (yaml_layer_idx, nested_path).
# A leading int in the path means weights[yaml_idx] is a list and the int
# selects the list element (depth-1 for all AllConvBlocks at this scale).
PTQ_TO_PATH: Sequence[tuple[int, tuple[Union[int, str], ...]]] = (
    (1, ("encode_conv",)),                  # L00 stem MS_DownSampling first_layer
    (2, ("sep", "pwconv1")),                # L01
    (2, ("sep", "dwconv2")),                # L02
    (2, ("sep", "pwconv3")),                # L03
    (2, ("sep", "dwconv4")),                # L04
    (2, ("conv1",)),                        # L05
    (2, ("conv2",)),                        # L06
    (3, ("encode_conv",)),                  # L07 MS_DownSampling s=2
    (4, (0, "sep", "pwconv1")),             # L08  block 0
    (4, (0, "sep", "dwconv2")),             # L09
    (4, (0, "sep", "pwconv3")),             # L10
    (4, (0, "sep", "dwconv4")),             # L11
    (4, (0, "conv1")),                      # L12
    (4, (0, "conv2")),                      # L13
    (5, ("encode_conv",)),                  # L14 MS_DownSampling s=2
    (6, (0, "sep", "pwconv1")),             # L15
    (6, (0, "sep", "dwconv2")),             # L16
    (6, (0, "sep", "pwconv3")),             # L17
    (6, (0, "sep", "dwconv4")),             # L18
    (6, (0, "conv1")),                      # L19
    (6, (0, "conv2")),                      # L20
    (7, ("cv1",)),                          # L21 SpikeSPPF
    (7, ("cv2",)),                          # L22
    (8, ("conv",)),                         # L23 MS_StandardConv
    (9, ("sep", "pwconv1")),                # L24
    (9, ("sep", "dwconv2")),                # L25
    (9, ("sep", "pwconv3")),                # L26
    (9, ("sep", "dwconv4")),                # L27
    (9, ("conv1",)),                        # L28
    (9, ("conv2",)),                        # L29
    # L30..L36 = SpikeDetect head; ignored.
)


def _layer_entry_to_convbn(le: LayerEntry) -> ConvBnParams:
    return ConvBnParams(
        w=le.w.astype(np.int8, copy=False),
        bias=le.bias.astype(np.int32, copy=False),
        out_shift=le.out_shift.astype(np.int16, copy=False),
        stride=int(le.stride),
        pad=int(le.pad),
        groups=int(le.groups),
        first_layer=bool(le.first_layer),
    )


def _insert_nested(weights: Dict[int, Any],
                   yaml_idx: int,
                   path: tuple,
                   value: ConvBnParams) -> None:
    if not path:
        weights[yaml_idx] = value
        return

    if isinstance(path[0], int):
        list_idx = path[0]
        rest = path[1:]
        lst = weights.setdefault(yaml_idx, [])
        if not isinstance(lst, list):
            raise TypeError(f"weights[{yaml_idx}] expected list, got {type(lst).__name__}")
        while len(lst) <= list_idx:
            lst.append({})
        node = lst[list_idx]
    else:
        node = weights.setdefault(yaml_idx, {})
        rest = path

    for i, key in enumerate(rest):
        last = (i == len(rest) - 1)
        if last:
            node[key] = value
        else:
            node = node.setdefault(key, {})


def load_for_tinyfpga(npz_path: str | Path) -> Dict[int, Any]:
    """Load a weight_packer .npz and build a TinyFpgaNet-compatible nested dict."""
    npz_path = Path(npz_path)
    layers, _ = read_npz(npz_path)
    needed = len(PTQ_TO_PATH)
    if len(layers) < needed:
        raise ValueError(
            f"{npz_path}: bridge expects >= {needed} layers, got {len(layers)}"
        )
    weights: Dict[int, Any] = {}
    for ptq_idx, (yaml_idx, path) in enumerate(PTQ_TO_PATH):
        _insert_nested(weights, yaml_idx, path, _layer_entry_to_convbn(layers[ptq_idx]))
    return weights


__all__ = ["load_for_tinyfpga", "PTQ_TO_PATH"]
