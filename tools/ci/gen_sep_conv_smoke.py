#!/usr/bin/env python3
"""
tools/ci/gen_sep_conv_smoke.py — generate a self-contained smoke fixture for
the standalone sep_conv testbench.

Background: tests/golden/layer_03_acb2a.npz holds the FULL acb2a block output
(post residual + conv1 + conv2 + residual). We want a per-stage golden that
isolates just sep_conv. Since A2 does not emit one as part of contract-2, we
synthesise it locally by re-running the NumPy reference with the same A1
weights and the same input tensor that A2 used for layer_03.

Output:
    hw/hls/sim/golden_local/sep_conv_smoke/input.npy
    hw/hls/sim/golden_local/sep_conv_smoke/output.npy
    hw/hls/sim/golden_local/sep_conv_smoke/meta.json

Reused weights: L08..L11 (acb2a sep_conv stage in tools/quant/np_adapter._SCHEMA).

Idempotent: running twice produces identical bytes.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np


def main() -> int:
    here = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(here))
    from tools.fpga.numpy_reference import sep_conv, ConvBnParams  # noqa: E402

    weights_npz = here / "models" / "tiny_fpga_int8.npz"
    input_npz   = here / "tests" / "golden" / "layer_03_acb2a.npz"
    out_dir     = here / "hw" / "hls" / "sim" / "golden_local" / "sep_conv_smoke"
    out_dir.mkdir(parents=True, exist_ok=True)

    nz = np.load(weights_npz, allow_pickle=True)
    meta_blob = json.loads(nz["__meta__"][0])

    def make(idx: int, pad_override=None) -> ConvBnParams:
        m = meta_blob[idx]
        return ConvBnParams(
            w=nz[f"L{idx:02d}.w"].astype(np.int8),
            bias=nz[f"L{idx:02d}.bias"].astype(np.int32),
            out_shift=nz[f"L{idx:02d}.out_shift"].astype(np.int8),
            stride=int(m["stride"]),
            pad=int(pad_override if pad_override is not None else m["pad"]),
            groups=int(m["groups"]),
            first_layer=bool(m["first_layer"]),
        )

    # acb2a sep_conv: pwconv1=L08, dwconv2=L09, pwconv3=L10, dwconv4=L11
    sep = {
        "pwconv1": make(8),
        "dwconv2": make(9),
        "pwconv3": make(10),
        "dwconv4": make(11),
    }

    # Apply pad-autocorrect to dwconv4 if A1 emitted pad=0 (legacy bug). A1 has
    # since fixed this so the autocorrect should be a no-op now, but the guard
    # keeps the script robust against future regressions.
    for k, p in sep.items():
        if p.w.shape[2] > 1 and p.stride == 1 and p.pad == 0:
            new_pad = p.w.shape[2] // 2
            print(f"[gen_sep_conv_smoke] auto-corrected {k} pad: 0 -> {new_pad}")
            p.pad = new_pad

    # Reuse layer_03_acb2a's input tensor (the model state at acb2a entry).
    g = np.load(input_npz, allow_pickle=True)
    x_in = np.array(g["input"], dtype=np.int32)  # (1, 48, 32, 32)

    y_out = sep_conv(x_in, sep)
    print(f"[gen_sep_conv_smoke] input  shape={x_in.shape} dtype={x_in.dtype}")
    print(f"[gen_sep_conv_smoke] output shape={y_out.shape} dtype={y_out.dtype}")

    np.save(out_dir / "input.npy",  x_in)
    np.save(out_dir / "output.npy", y_out)

    meta = {
        "kind": "sep_conv",
        "layer_source": "acb2a (yaml node 4, sub 0)",
        "weights": ["L08", "L09", "L10", "L11"],
        "input":  {"dtype": str(x_in.dtype),  "shape": list(x_in.shape)},
        "output": {"dtype": str(y_out.dtype), "shape": list(y_out.shape)},
        "geometry": {
            "T": 1, "C": 48, "C_exp": 96, "H": 32, "W": 32,
            "K_dw2": 7, "pad_dw2": 3, "K_dw4": 3, "pad_dw4": 1,
        },
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"[gen_sep_conv_smoke] wrote {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
