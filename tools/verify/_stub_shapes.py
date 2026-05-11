"""Backward-compat helper: emit zero-filled layer .npz placeholders.

Kept for the very first B1 wiring iteration (M1W1). Real goldens live in
``tools.verify.extract_golden.trace_forward``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import numpy as np


_SHAPES = {
    "stem":        ((1, 3, 256, 256),  np.int8,  (1, 24, 64, 64),  np.int32),
    "acb1":        ((1, 24, 64, 64),   np.int32, (1, 24, 64, 64),  np.int32),
    "ds1":         ((1, 24, 64, 64),   np.int32, (1, 48, 32, 32),  np.int32),
    "acb2a":       ((1, 48, 32, 32),   np.int32, (1, 48, 32, 32),  np.int32),
    "acb2b":       ((1, 48, 32, 32),   np.int32, (1, 48, 32, 32),  np.int32),
    "ds2":         ((1, 48, 32, 32),   np.int32, (1, 96, 16, 16),  np.int32),
    "acb3a":       ((1, 96, 16, 16),   np.int32, (1, 96, 16, 16),  np.int32),
    "acb3b":       ((1, 96, 16, 16),   np.int32, (1, 96, 16, 16),  np.int32),
    "sppf":        ((1, 96, 16, 16),   np.int32, (1, 96, 16, 16),  np.int32),
    "head_reduce": ((1, 96, 16, 16),   np.int32, (1, 48, 16, 16),  np.int32),
    "head_refine": ((1, 48, 16, 16),   np.int32, (1, 48, 16, 16),  np.int32),
    "detect":      ((1, 48, 16, 16),   np.int32, (1, 48, 16, 16),  np.int8),
}


def emit_stub_layers(out_dir: Path,
                     layer_names: List[str],
                     kinds_per_layer: List[str]) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    out: Dict[str, Path] = {}
    for idx, (name, kind) in enumerate(zip(layer_names, kinds_per_layer)):
        ishape, idtype, oshape, odtype = _SHAPES[name]
        rng = np.random.default_rng(idx * 7919 + 1)
        in_arr = rng.integers(-32, 32, size=ishape, dtype=np.int32).astype(idtype)
        out_arr = rng.integers(-64, 64, size=oshape, dtype=np.int32).astype(odtype)
        path = out_dir / f"layer_{idx:02d}_{name}.npz"
        np.savez(path, input=in_arr, output=out_arr,
                 input_shape=np.array(ishape, dtype=np.int32),
                 output_shape=np.array(oshape, dtype=np.int32),
                 params_hash=np.array([b"STUB"], dtype="S64"),
                 kind=np.array([kind.encode()], dtype="S32"))
        out[name] = path
    return out
