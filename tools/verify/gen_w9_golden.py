#!/usr/bin/env python3
"""tools/verify/gen_w9_golden.py — produce W9 smoke-test golden artifacts.

Pairs with sw/app/src/spike_accel_w9_smoke.c. Runs the host-side
`tools/fpga/numpy_reference.TinyFpgaNet` on the W9 PTQ INT8 weights
(`models/tiny_fpga_int8_real.npz`) with a deterministic input pattern
(default: byte-ramp), dumps the int8 output, and prints the 32-bit
FNV-1a hash that the board-side smoke binary will compare against.

Usage:
    python tools/verify/gen_w9_golden.py \\
        --weights models/tiny_fpga_int8_real.npz \\
        --input   ramp \\
        --output  golden/w9_smoke_feat_out.bin \\
        --hash-out golden/w9_smoke.hash

CI flow (board-nightly):
    1. PC: gen_w9_golden.py --hash-out golden.txt  → emits 8-hex hash
    2. scp `tiny_fpga_int8_real.bin` to /lib/firmware/ on board
    3. board: spike_accel_w9_smoke --golden-hash $(cat golden.txt)
    4. board exit 0 means byte-exact match host vs PL.

Owner: shared by A1 (numpy reference + INT8 weights) and C2 (SDK).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

# numpy_reference.TinyFpgaNet provides the bit-exact INT8 reference used by all
# HLS csim regressions (Contract 2). It accepts a single int8 [1,3,256,256]
# image and returns int8 [1,48,16,16] pre-NMS feature output.
from tools.fpga import numpy_reference  # type: ignore

INPUT_H = 256
INPUT_W = 256
INPUT_C = 3
INPUT_NBYTES = INPUT_H * INPUT_W * INPUT_C   # 196 608

OUTPUT_H = 16
OUTPUT_W = 16
OUTPUT_C = 48
OUTPUT_NBYTES = OUTPUT_H * OUTPUT_W * OUTPUT_C   # 12 288


def fnv1a32(buf: bytes) -> int:
    """32-bit FNV-1a, byte-for-byte equivalent to the C version in the smoke app."""
    h = 0x811C9DC5
    for b in buf:
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def build_input(pattern: str, path: str | None) -> np.ndarray:
    """Return INT8 [1,3,256,256] image matching one of the named patterns."""
    if pattern == "ramp":
        arr = np.arange(INPUT_NBYTES, dtype=np.uint8).astype(np.int8)
    elif pattern == "zero":
        arr = np.zeros(INPUT_NBYTES, dtype=np.int8)
    elif pattern == "one":
        arr = np.ones(INPUT_NBYTES, dtype=np.int8)
    elif pattern == "file":
        if not path:
            raise SystemExit("--input file requires --input-path PATH")
        raw = Path(path).read_bytes()
        if len(raw) != INPUT_NBYTES:
            raise SystemExit(
                f"input file {path} has {len(raw)} bytes, expected {INPUT_NBYTES}"
            )
        arr = np.frombuffer(raw, dtype=np.int8).copy()
    else:
        raise SystemExit(f"unknown --input pattern {pattern!r}")
    return arr.reshape(1, INPUT_C, INPUT_H, INPUT_W)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--weights", default="models/tiny_fpga_int8_real.npz",
        help="Path to NPZ weights (.bin's accompanying .npz)",
    )
    p.add_argument(
        "--input", choices=["ramp", "zero", "one", "file"], default="ramp",
        help="Input pattern (must match what the board-side smoke test feeds)",
    )
    p.add_argument("--input-path", default=None, help="Required if --input file")
    p.add_argument(
        "--output", default=None,
        help="Optional: dump int8 feat_out bytes to this path (mirrors the .bin format)",
    )
    p.add_argument(
        "--hash-out", default=None,
        help="Optional: write the 8-hex-digit FNV-1a32 hash to this path (no trailing nl)",
    )
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    weights_path = (REPO_ROOT / args.weights).resolve()
    if not weights_path.exists():
        raise SystemExit(f"weights not found: {weights_path}")

    img = build_input(args.input, args.input_path)
    if args.verbose:
        print(f"[golden] input pattern = {args.input}, dtype = {img.dtype}, "
              f"shape = {img.shape}", file=sys.stderr)
        in_hash = fnv1a32(img.tobytes())
        print(f"[golden] input fnv1a32  = 0x{in_hash:08x}", file=sys.stderr)

    if args.verbose:
        print(f"[golden] loading weights {weights_path}", file=sys.stderr)
    # PBT-fix: TinyFpgaNet has no classmethod load_npz; construct via load_weights.
    net = numpy_reference.TinyFpgaNet(
        weights=numpy_reference.load_weights(str(weights_path))
    )

    if args.verbose:
        print("[golden] running TinyFpgaNet forward (CPU, may take ~10-30s)…", file=sys.stderr)
    feat_out = net.forward(img)
    feat_out = np.asarray(feat_out, dtype=np.int8)

    if feat_out.size != OUTPUT_NBYTES:
        raise SystemExit(
            f"unexpected feat_out size {feat_out.size}, want {OUTPUT_NBYTES}"
        )

    out_bytes = feat_out.tobytes()
    h = fnv1a32(out_bytes)
    hex_h = f"{h:08x}"

    if args.output:
        out_path = (REPO_ROOT / args.output).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(out_bytes)
        if args.verbose:
            print(f"[golden] wrote {out_path} ({len(out_bytes)} bytes)", file=sys.stderr)

    if args.hash_out:
        hash_path = (REPO_ROOT / args.hash_out).resolve()
        hash_path.parent.mkdir(parents=True, exist_ok=True)
        hash_path.write_text(hex_h)
        if args.verbose:
            print(f"[golden] wrote {hash_path}", file=sys.stderr)

    print(hex_h)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
