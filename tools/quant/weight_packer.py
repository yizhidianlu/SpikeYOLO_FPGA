"""Contract 1 reference implementation: layer-dict -> .npz (+ .bin) packer/unpacker.

This module is intentionally framework-agnostic. It does NOT depend on PyTorch
or on `tools/fpga/numpy_reference.py`. A1's PTQ pipeline (run_ptq.py) and
A2's golden extractor (extract_golden.py) feed in already-quantized NumPy
dicts; this module is the single source of truth for the on-disk layout.

Layouts
-------
- ``standard``  weights stay as ``int8 [C_out, C_in/groups, K, K]`` (what
  ``tools/fpga/numpy_reference.conv2d_int`` expects). Use for PyTorch/NumPy
  verification round-trips.
- ``pe_tile``   weights are reshaped to
  ``int8 [Co_outer, Ci_outer, K, K, Co_tile, Ci_tile]`` (Co_tile=16, Ci_tile=8),
  padding the trailing channels with zeros when ``C_out`` / ``C_in`` are not a
  multiple of the tile. This is what the HLS PE array (B1) ingests.

Both layouts share an identical key schema in the .npz so contract tests can
verify they round-trip and dequantize to the same numbers.

CLI
---
    python tools/quant/weight_packer.py pack \
        --input  /tmp/quantized_dict.npz \
        --output models/tiny_fpga_int8.npz \
        --layout standard

    python tools/quant/weight_packer.py pack \
        --input  models/tiny_fpga_int8.npz \
        --output models/tiny_fpga_int8_tiled.npz \
        --layout pe_tile

    python tools/quant/weight_packer.py to-bin \
        --input  models/tiny_fpga_int8_tiled.npz \
        --output models/tiny_fpga_int8.bin

    python tools/quant/weight_packer.py validate \
        --input models/tiny_fpga_int8.npz
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np


CO_TILE = 16
CI_TILE = 8

KIND_TO_ENUM = {
    "conv2d_bn":     0,
    "ms_downsample": 1,
    "sep_conv":      2,
    "ms_standard":   3,
    "maxpool":       4,
    "sppf":          5,
    "detect":        6,
}
ENUM_TO_KIND = {v: k for k, v in KIND_TO_ENUM.items()}


@dataclass
class LayerEntry:
    """A single quantized Conv2d_bn layer."""

    idx: int
    kind: str                # one of KIND_TO_ENUM keys
    w:   np.ndarray          # int8 standard layout (C_out, C_in/groups, K, K)
    bias: np.ndarray         # int32 (C_out,)
    out_shift: np.ndarray    # int8 (C_out,)
    stride: int
    pad: int
    groups: int
    first_layer: bool
    k: int = 0               # kernel size (derived; populated in __post_init__)
    c_in: int = 0
    c_out: int = 0

    def __post_init__(self) -> None:
        if self.kind not in KIND_TO_ENUM:
            raise ValueError(f"unknown kind {self.kind!r}")
        if self.w.dtype != np.int8:
            raise TypeError(f"w must be int8, got {self.w.dtype}")
        if self.bias.dtype != np.int32:
            raise TypeError(f"bias must be int32, got {self.bias.dtype}")
        if self.out_shift.dtype != np.int8:
            raise TypeError(f"out_shift must be int8, got {self.out_shift.dtype}")
        c_out, c_in_g, k, k2 = self.w.shape
        if k != k2:
            raise ValueError(f"non-square kernel {k}x{k2}")
        if c_out != self.bias.shape[0] or c_out != self.out_shift.shape[0]:
            raise ValueError("C_out mismatch between w / bias / out_shift")
        self.k = k
        self.c_out = c_out
        self.c_in = c_in_g * self.groups


# -----------------------------------------------------------------------------
# PE-tile reshape
# -----------------------------------------------------------------------------

def to_pe_tile(w_std: np.ndarray, co_tile: int = CO_TILE,
               ci_tile: int = CI_TILE) -> np.ndarray:
    """Re-tile ``[C_out, C_in, K, K]`` -> ``[Co_outer, Ci_outer, K, K, Co_tile, Ci_tile]``.

    Pads trailing channels with zeros when not divisible. The inner-most two
    axes are ``(co_tile, ci_tile)`` so a single 128-byte BRAM read pulls
    ``Co_tile`` weights for ``Ci_tile`` input channels at one kernel position.
    """
    if w_std.dtype != np.int8:
        raise TypeError(f"expected int8, got {w_std.dtype}")
    c_out, c_in, kh, kw = w_std.shape
    co_outer = (c_out + co_tile - 1) // co_tile
    ci_outer = (c_in + ci_tile - 1) // ci_tile
    padded = np.zeros((co_outer * co_tile, ci_outer * ci_tile, kh, kw),
                      dtype=np.int8)
    padded[:c_out, :c_in] = w_std
    tiled = padded.reshape(co_outer, co_tile, ci_outer, ci_tile, kh, kw)
    return np.ascontiguousarray(tiled.transpose(0, 2, 4, 5, 1, 3))


def from_pe_tile(w_tile: np.ndarray, c_out: int, c_in: int) -> np.ndarray:
    """Inverse of ``to_pe_tile`` (drops the zero padding)."""
    co_outer, ci_outer, kh, kw, co_tile, ci_tile = w_tile.shape
    untiled = w_tile.transpose(0, 4, 1, 5, 2, 3)
    untiled = untiled.reshape(co_outer * co_tile, ci_outer * ci_tile, kh, kw)
    return np.ascontiguousarray(untiled[:c_out, :c_in])


# -----------------------------------------------------------------------------
# .npz writer / reader
# -----------------------------------------------------------------------------

def write_npz(layers: List[LayerEntry], out_path: Path,
              layout: str = "standard") -> None:
    """Serialize a layer list to a .npz with per-layer key prefixes ``L{NN}.``."""
    if layout not in ("standard", "pe_tile"):
        raise ValueError(layout)
    arrays: Dict[str, np.ndarray] = {}
    meta: List[Dict] = []
    for L in layers:
        p = f"L{L.idx:02d}."
        w_arr = L.w if layout == "standard" else to_pe_tile(L.w)
        arrays[p + "w"] = w_arr
        arrays[p + "bias"] = L.bias
        arrays[p + "out_shift"] = L.out_shift
        arrays[p + "scalar"] = np.array(
            [L.stride, L.pad, L.groups,
             1 if L.first_layer else 0,
             KIND_TO_ENUM[L.kind], L.k, L.c_in, L.c_out],
            dtype=np.int32,
        )
        meta.append({
            "idx": L.idx, "kind": L.kind, "stride": L.stride, "pad": L.pad,
            "groups": L.groups, "first_layer": L.first_layer,
            "k": L.k, "c_in": L.c_in, "c_out": L.c_out,
        })
    arrays["__layout__"] = np.array([layout.encode()], dtype="S16")
    arrays["__meta__"] = np.array([json.dumps(meta).encode()], dtype=object)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(out_path, **arrays)


def read_npz(path: Path) -> Tuple[List[LayerEntry], str]:
    """Inverse of ``write_npz``. Returns ``(layers, layout)``."""
    with np.load(path, allow_pickle=True) as data:
        layout = bytes(data["__layout__"][0]).decode().rstrip("\x00")
        meta_raw = data["__meta__"][0]
        meta = json.loads(bytes(meta_raw).decode() if isinstance(meta_raw, bytes) else meta_raw)
        layers: List[LayerEntry] = []
        for m in meta:
            p = f"L{m['idx']:02d}."
            w = data[p + "w"]
            if layout == "pe_tile":
                w = from_pe_tile(w, m["c_out"], m["c_in"] // m["groups"])
            layers.append(LayerEntry(
                idx=m["idx"], kind=m["kind"],
                w=w, bias=data[p + "bias"], out_shift=data[p + "out_shift"],
                stride=m["stride"], pad=m["pad"], groups=m["groups"],
                first_layer=m["first_layer"],
            ))
        return layers, layout


# -----------------------------------------------------------------------------
# Board-side .bin serializer  (LayerRecord schema from docs/CONTRACTS.md)
# -----------------------------------------------------------------------------

# struct LayerRecord {
#   uint8  idx, kind_enum, stride, pad, groups, first_layer;
#   uint16 k;        # NB: spec lists k as uint16; we keep 1 byte of pad for alignment
#   uint16 c_in;
#   uint16 c_out;
#   uint32 weight_bytes, bias_bytes, shift_bytes;
# } total = 24 bytes; 16-byte aligned via trailing pad
_LAYER_RECORD_FMT = "<6BHHHIII"           # 6*1 + 2 + 2 + 2 + 4 + 4 + 4 = 24 bytes
_LAYER_RECORD_SZ  = struct.calcsize(_LAYER_RECORD_FMT)
assert _LAYER_RECORD_SZ == 24


def _align16(n: int) -> int:
    return (n + 15) & ~15


def write_bin(layers: List[LayerEntry], out_path: Path,
              layout: str = "pe_tile") -> None:
    """Write the board-side binary blob. Weights are PE-tile ordered."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as f:
        for L in layers:
            w_bytes = (to_pe_tile(L.w) if layout == "pe_tile" else L.w).tobytes()
            bias_bytes = L.bias.tobytes()
            shift_bytes = L.out_shift.tobytes()
            f.write(struct.pack(
                _LAYER_RECORD_FMT,
                L.idx, KIND_TO_ENUM[L.kind], L.stride, L.pad,
                L.groups, 1 if L.first_layer else 0,
                L.k, L.c_in, L.c_out,
                len(w_bytes), len(bias_bytes), len(shift_bytes),
            ))
            f.write(w_bytes)
            f.write(bias_bytes)
            f.write(shift_bytes)
            # 16-byte align this record
            cur = f.tell()
            pad = _align16(cur) - cur
            if pad:
                f.write(b"\x00" * pad)


def read_bin(path: Path) -> List[LayerEntry]:
    """Inverse of ``write_bin``. Drops PE-tile padding (back to standard layout)."""
    raw = path.read_bytes()
    pos = 0
    out: List[LayerEntry] = []
    while pos < len(raw):
        fields = struct.unpack(_LAYER_RECORD_FMT, raw[pos:pos + _LAYER_RECORD_SZ])
        (idx, kind_enum, stride, pad_v, groups, first_layer,
         k, c_in, c_out, w_bytes, bias_bytes, shift_bytes) = fields
        pos += _LAYER_RECORD_SZ
        w_buf = raw[pos:pos + w_bytes]; pos += w_bytes
        b_buf = raw[pos:pos + bias_bytes]; pos += bias_bytes
        s_buf = raw[pos:pos + shift_bytes]; pos += shift_bytes
        # Skip alignment padding
        pos = _align16(pos)
        # Reconstruct PE-tile array then untile back to standard
        co_outer = (c_out + CO_TILE - 1) // CO_TILE
        ci_outer = ((c_in // groups) + CI_TILE - 1) // CI_TILE
        w_tile = np.frombuffer(w_buf, dtype=np.int8).reshape(
            co_outer, ci_outer, k, k, CO_TILE, CI_TILE)
        w_std = from_pe_tile(w_tile, c_out, c_in // groups)
        out.append(LayerEntry(
            idx=idx, kind=ENUM_TO_KIND[kind_enum],
            w=w_std,
            bias=np.frombuffer(b_buf, dtype=np.int32).copy(),
            out_shift=np.frombuffer(s_buf, dtype=np.int8).copy(),
            stride=stride, pad=pad_v, groups=groups,
            first_layer=bool(first_layer),
        ))
    return out


# -----------------------------------------------------------------------------
# Validation
# -----------------------------------------------------------------------------

def validate(path: Path) -> List[str]:
    """Return a list of validation errors (empty == OK)."""
    errs: List[str] = []
    try:
        layers, layout = read_npz(path)
    except Exception as exc:
        return [f"failed to load {path}: {exc}"]
    if not layers:
        errs.append("npz has zero layers")
    seen_idx = set()
    for L in layers:
        if L.idx in seen_idx:
            errs.append(f"duplicate layer idx {L.idx}")
        seen_idx.add(L.idx)
        if L.kind not in KIND_TO_ENUM:
            errs.append(f"L{L.idx}: unknown kind {L.kind}")
        if L.w.shape[0] != L.c_out:
            errs.append(f"L{L.idx}: c_out mismatch")
        if L.w.shape[1] * L.groups != L.c_in:
            errs.append(f"L{L.idx}: c_in/groups mismatch")
    return errs


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def _cli_pack(args: argparse.Namespace) -> int:
    layers, src_layout = read_npz(Path(args.input))
    write_npz(layers, Path(args.output), layout=args.layout)
    print(f"[pack] {args.input} ({src_layout}) -> {args.output} ({args.layout})  "
          f"layers={len(layers)}")
    return 0


def _cli_to_bin(args: argparse.Namespace) -> int:
    layers, _ = read_npz(Path(args.input))
    write_bin(layers, Path(args.output), layout="pe_tile")
    print(f"[to-bin] {args.input} -> {args.output}  layers={len(layers)}  "
          f"size={Path(args.output).stat().st_size} bytes")
    return 0


def _cli_validate(args: argparse.Namespace) -> int:
    errs = validate(Path(args.input))
    if errs:
        print("FAIL", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print(f"OK  {args.input}")
    return 0


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Contract 1 weight packer")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_pack = sub.add_parser("pack")
    p_pack.add_argument("--input", required=True)
    p_pack.add_argument("--output", required=True)
    p_pack.add_argument("--layout", choices=["standard", "pe_tile"], default="standard")
    p_pack.set_defaults(func=_cli_pack)

    p_bin = sub.add_parser("to-bin")
    p_bin.add_argument("--input", required=True)
    p_bin.add_argument("--output", required=True)
    p_bin.set_defaults(func=_cli_to_bin)

    p_val = sub.add_parser("validate")
    p_val.add_argument("--input", required=True)
    p_val.set_defaults(func=_cli_validate)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
