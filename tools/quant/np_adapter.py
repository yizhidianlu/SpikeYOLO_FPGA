"""Bridge between Contract 1 ``LayerEntry`` lists and the nested ``weights``
dict expected by ``tools.fpga.numpy_reference.TinyFpgaNet``.

Schema is authored from the *real* PyTorch ``snn_yolov8_tiny_fpga.yaml`` model
walk (see ``tools/quant/probe_schema.py``):

* 37 ``nn.Conv2d`` instances total
* yaml nodes 4 (acb2) and 6 (acb3) are **single blocks** (ultralytics' parser
  does not stack them despite ``n=2`` in the yaml)
* ``SepConv.pwconv3`` is a ``SepRepConv`` that holds **two** nested Conv2d
  layers (``body.1.0`` 1×1 and ``body.1.1`` 3×3 depth-wise), so each SepConv
  contributes 4 convs (pwconv1, dwconv2, pwconv3.inner0, pwconv3.inner1)
* yaml node 10 (SpikeDetect head) has 7 convs: 3 in cv2 + 3 in cv3 + 1 dfl

Concrete idx → (yaml_node, key_path) map below.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np

from tools.fpga.numpy_reference import ConvBnParams
from tools.quant.weight_packer import LayerEntry


# ---------------------------------------------------------------------------
# Per-position layout — 37 entries matching the PyTorch model walk.
# ---------------------------------------------------------------------------

# acb 6-conv pattern: (sep.{pwconv1,dwconv2,pwconv3_inner0,pwconv3_inner1},
#                      conv1, conv2)
def _acb_entries(yaml_node: int) -> List[Tuple[int, Tuple]]:
    # The PyTorch SepConv has 4 nn.Conv2d: pwconv1, dwconv2, then SepRepConv
    # contains two more (an inner 1×1 and an inner depth-wise 3×3). We map
    # those latter two to numpy_reference's pwconv3 / dwconv4 keys — same
    # cardinality even if the inner structure differs.
    return [
        (yaml_node, ("sep", "pwconv1")),
        (yaml_node, ("sep", "dwconv2")),
        (yaml_node, ("sep", "pwconv3")),     # ↔ SepRepConv body.1.0 (1×1)
        (yaml_node, ("sep", "dwconv4")),     # ↔ SepRepConv body.1.1 (3×3 dw)
        (yaml_node, ("conv1",)),
        (yaml_node, ("conv2",)),
    ]


_SCHEMA: List[Tuple[int, Tuple]] = (
    [(1, ("encode_conv",))]                            # 00 stem
    + _acb_entries(2)                                  # 01-06 acb1
    + [(3, ("encode_conv",))]                          # 07 ds1
    + _acb_entries(4)                                  # 08-13 acb2 (single block)
    + [(5, ("encode_conv",))]                          # 14 ds2
    + _acb_entries(6)                                  # 15-20 acb3 (single block)
    + [(7, ("cv1",)), (7, ("cv2",))]                   # 21-22 sppf cv1, cv2
    + [(8, ("conv",))]                                 # 23 head_reduce
    + _acb_entries(9)                                  # 24-29 head_refine
    + [
        (10, ("cv2", 0, 0)),                           # 30 detect cv2[0].0
        (10, ("cv2", 0, 1)),                           # 31 detect cv2[0].1
        (10, ("cv2", 0, 2)),                           # 32 detect cv2[0].2
        (10, ("cv3", 0, 0)),                           # 33 detect cv3[0].0
        (10, ("cv3", 0, 1)),                           # 34 detect cv3[0].1
        (10, ("cv3", 0, 2)),                           # 35 detect cv3[0].2
        (10, ("dfl",)),                                # 36 detect dfl
    ]
)
assert len(_SCHEMA) == 37, f"schema length {len(_SCHEMA)} != 37"


# yaml nodes 4 and 6 are *lists of one block* so numpy_reference.TinyFpgaNet's
# `for sub in self.weights[N]` keeps working. We wrap their dicts in [..].
_LIST_NODES = {4, 6}


def schema_size() -> int:
    """Number of Conv2d entries in tiny_fpga (== 37)."""
    return len(_SCHEMA)


# ---------------------------------------------------------------------------
# LayerEntry -> ConvBnParams
# ---------------------------------------------------------------------------

def _layer_to_conv_bn(L: LayerEntry) -> ConvBnParams:
    return ConvBnParams(
        w=L.w.astype(np.int8),
        bias=L.bias.astype(np.int32),
        out_shift=L.out_shift.astype(np.int16),
        stride=L.stride, pad=L.pad,
        groups=L.groups, first_layer=L.first_layer,
    )


# ---------------------------------------------------------------------------
# Inject a single value into the nested dict (with optional list expansion)
# ---------------------------------------------------------------------------

def _ensure_list_for(root: Dict, yaml_node: int) -> Dict:
    """If ``yaml_node`` lives inside a list-style node (acb2/acb3), make sure
    the list exists and return its single element to be filled.
    """
    if yaml_node in _LIST_NODES:
        lst = root.setdefault(yaml_node, [{}])
        if not isinstance(lst, list):
            lst = root[yaml_node] = [lst]
        if not lst:
            lst.append({})
        return lst[0]
    return root.setdefault(yaml_node, {})


def _set_nested(node, key_path: Tuple, value) -> None:
    """Walk ``key_path`` and assign ``value`` at the leaf. Handles dict + list.

    Implementation note: at each non-leaf step we look ahead one key to decide
    whether the next container should be a dict (next key is str) or a list
    (next key is int). This handles arbitrary nesting like ``("cv2", 0, 0)``.
    """
    for i, key in enumerate(key_path):
        is_last = (i == len(key_path) - 1)
        next_is_int = (not is_last) and isinstance(key_path[i + 1], int)
        empty_next = [] if next_is_int else {}

        if isinstance(key, int):
            if not isinstance(node, list):
                raise TypeError(f"expected list at key {key!r}, got {type(node).__name__}")
            while len(node) <= key:
                node.append({})
            if is_last:
                node[key] = value
                return
            # Allocate the correctly-typed container at this slot if missing.
            if not isinstance(node[key], type(empty_next)):
                node[key] = empty_next
            node = node[key]
        else:
            if is_last:
                node[key] = value
                return
            if key not in node or not isinstance(node[key], type(empty_next)):
                node[key] = empty_next
            node = node[key]


def to_numpy_reference(layers: List[LayerEntry]) -> Dict[int, object]:
    """Convert a flat LayerEntry list to the nested weight dict expected
    by ``numpy_reference.TinyFpgaNet``. Requires exactly ``schema_size()``
    layers; raises ``ValueError`` otherwise.

    Because numpy_reference.TinyFpgaNet historically expects
    ``weights[4]`` / ``weights[6]`` to be a list of *two* sub-blocks (the
    yaml hints ``n=2``), and the real PyTorch model collapses them to one,
    we duplicate slot 0 into slot 1 so the legacy forward path keeps
    iterating twice. M3 work re-aligns numpy_reference with the PyTorch
    single-block layout.
    """
    import copy

    if len(layers) != len(_SCHEMA):
        raise ValueError(
            f"to_numpy_reference: expected {len(_SCHEMA)} LayerEntry "
            f"(one per Conv2d_bn in tiny_fpga), got {len(layers)}"
        )
    out: Dict[int, object] = {}
    for L, (yaml_node, key_path) in zip(layers, _SCHEMA):
        node = _ensure_list_for(out, yaml_node)
        _set_nested(node, key_path, _layer_to_conv_bn(L))

    for yn in _LIST_NODES:
        lst = out.get(yn)
        if isinstance(lst, list) and len(lst) == 1:
            lst.append(copy.deepcopy(lst[0]))
    return out
