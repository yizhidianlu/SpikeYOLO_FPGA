#!/usr/bin/env python3
"""
tools/ci/explode_npz.py — explode .npz archives into raw .npy files.

The HLS host_csim flow reads golden tensors from C++. To keep that reader
small (~200 lines) and zero-dependency we side-step the zip container in
.npz files by extracting each member as a standalone .npy. The C++ side
(`hw/hls/sim/npz_reader.cpp`) only needs to parse the .npy header.

Usage
-----
    # Explode a single archive into <out_dir>/<member>.npy
    python tools/ci/explode_npz.py tests/golden/layer_00_stem.npz \\
        --out-dir tests/golden/exploded/layer_00_stem

    # Bulk-explode every layer_*.npz under tests/golden into
    # tests/golden/exploded/<stem>/<member>.npy
    python tools/ci/explode_npz.py --all
"""
from __future__ import annotations

import argparse
import os
import sys
from glob import glob

import numpy as np


def explode(npz_path: str, out_dir: str) -> list[str]:
    """Extract every member of `npz_path` as a .npy file under `out_dir`.

    Returns the list of created .npy paths (sorted).
    """
    os.makedirs(out_dir, exist_ok=True)
    written: list[str] = []
    # allow_pickle=True only because the upstream A1 .npz contains a small
    # `scalar` object array of fold_bn metadata. We never serialise pickled
    # objects on the way out: the C++ reader rejects anything but i1 / i4.
    with np.load(npz_path, allow_pickle=True) as nz:
        for name in nz.files:
            arr = nz[name]
            # Skip object dtypes — the C++ reader only handles INT8 / INT32.
            if arr.dtype == object:
                print(f"[explode_npz] skip {name} (dtype=object)")
                continue
            out = os.path.join(out_dir, name + ".npy")
            np.save(out, arr, allow_pickle=False)
            written.append(out)
    return sorted(written)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("npz", nargs="?", help="path to a single .npz to explode")
    ap.add_argument("--out-dir", help="output directory for the .npy members")
    ap.add_argument(
        "--all",
        action="store_true",
        help="explode every tests/golden/layer_*.npz into "
             "tests/golden/exploded/<stem>/",
    )
    ap.add_argument(
        "--root",
        default=".",
        help="project root (defaults to cwd) — used by --all to locate golden",
    )
    args = ap.parse_args()

    if args.all:
        pattern = os.path.join(args.root, "tests", "golden", "layer_*.npz")
        archives = sorted(glob(pattern))
        if not archives:
            print(f"[explode_npz] no archives matched {pattern}", file=sys.stderr)
            return 1
        for npz in archives:
            stem = os.path.splitext(os.path.basename(npz))[0]
            out_dir = os.path.join(
                args.root, "tests", "golden", "exploded", stem
            )
            written = explode(npz, out_dir)
            print(f"[explode_npz] {npz} -> {len(written)} files in {out_dir}")
        return 0

    if not args.npz:
        ap.error("either --all or a positional .npz path is required")
    out_dir = args.out_dir or os.path.join(
        os.path.dirname(args.npz),
        "exploded",
        os.path.splitext(os.path.basename(args.npz))[0],
    )
    written = explode(args.npz, out_dir)
    print(f"[explode_npz] {args.npz} -> {len(written)} files in {out_dir}")
    for p in written:
        print(f"  {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
