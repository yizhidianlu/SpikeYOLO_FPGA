"""Bit-exact comparator: NumPy golden ↔ HLS C-sim output.

This is the workhorse for B1's CI gate. The HLS testbench writes its layer
outputs as raw little-endian binary blobs (so it can run without a NumPy
runtime); this script loads the matching golden tensor and asserts every
INT element matches.

Supports two HLS output formats:

* ``.bin``  raw byte stream, dtype + shape provided via ``--dtype`` /
            ``--shape`` flags (or sniffed from the golden tensor).
* ``.npy``  standard NumPy format (used when the HLS testbench is
            compiled natively and can ``np.save`` via cnpy or similar).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np


_DTYPE_MAP = {
    "int8":  np.int8,
    "uint8": np.uint8,
    "int16": np.int16,
    "int32": np.int32,
    "int64": np.int64,
    "float32": np.float32,
    "float64": np.float64,
}


def load_golden(path: Path, key: str = "output") -> np.ndarray:
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix == ".npz":
        with np.load(path) as data:
            if key not in data.files:
                raise KeyError(
                    f"key {key!r} not in {path.name}. "
                    f"available: {data.files}"
                )
            return data[key]
    if path.suffix == ".npy":
        return np.load(path)
    raise ValueError(f"unsupported golden format: {path.suffix}")


def load_hls_output(path: Path,
                    dtype: Optional[np.dtype],
                    shape: Optional[Tuple[int, ...]]) -> np.ndarray:
    if path.suffix == ".npy":
        return np.load(path)
    if path.suffix in (".bin", ".raw", ""):
        if dtype is None or shape is None:
            raise ValueError(
                "Need --dtype and --shape when loading raw .bin HLS output"
            )
        data = np.frombuffer(path.read_bytes(), dtype=dtype)
        return data.reshape(shape)
    raise ValueError(f"unsupported HLS output format: {path.suffix}")


def compare(golden: np.ndarray, hls: np.ndarray, max_mismatches: int = 10) -> Dict:
    """Element-wise INT compare. Returns a dict suitable for JSON dump."""
    if golden.shape != hls.shape:
        return {"ok": False, "reason": "shape mismatch",
                "golden_shape": list(golden.shape), "hls_shape": list(hls.shape)}
    if golden.dtype != hls.dtype:
        # Allow promotion in one direction: golden int32 vs hls int32 is fine;
        # mismatched ints we still report.
        if not (np.issubdtype(golden.dtype, np.integer)
                and np.issubdtype(hls.dtype, np.integer)):
            return {"ok": False, "reason": "dtype mismatch",
                    "golden_dtype": str(golden.dtype),
                    "hls_dtype": str(hls.dtype)}
        # cast both to int64 for comparison
        g = golden.astype(np.int64)
        h = hls.astype(np.int64)
    else:
        g, h = golden, hls

    diff_mask = g != h
    n_mismatches = int(diff_mask.sum())
    if n_mismatches == 0:
        return {"ok": True, "n_elements": int(g.size), "max_abs_diff": 0}

    # collect the first N mismatch indices for debugging
    idx = np.argwhere(diff_mask)[:max_mismatches]
    examples = [
        {"index": idx_i.tolist(),
         "golden": int(g[tuple(idx_i)]),
         "hls":    int(h[tuple(idx_i)]),
         "diff":   int(h[tuple(idx_i)]) - int(g[tuple(idx_i)])}
        for idx_i in idx
    ]
    max_abs = int(np.max(np.abs(g - h)))
    return {
        "ok": False,
        "n_elements": int(g.size),
        "n_mismatches": n_mismatches,
        "mismatch_pct": 100.0 * n_mismatches / g.size,
        "max_abs_diff": max_abs,
        "first_mismatches": examples,
    }


def main(argv: list | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--golden", required=True, type=Path,
                   help="NumPy golden tensor (.npz or .npy)")
    p.add_argument("--hls-output", required=True, type=Path,
                   help="HLS C-sim output (.bin / .raw / .npy)")
    p.add_argument("--key", default="output", help="key inside golden .npz")
    p.add_argument("--dtype", default=None, help="dtype for raw .bin (e.g. int32)")
    p.add_argument("--shape", default=None,
                   help="shape for raw .bin as comma-separated ints, e.g. 1,24,64,64")
    p.add_argument("--report", type=Path, default=None,
                   help="write JSON diff report here")
    p.add_argument("--all-layers", action="store_true",
                   help="treat --golden as a directory of layer_*.npz")
    args = p.parse_args(argv)

    if args.all_layers:
        return _all_layers_mode(args)

    golden = load_golden(args.golden, key=args.key)
    if args.dtype:
        dt = _DTYPE_MAP[args.dtype]
    elif args.hls_output.suffix in (".bin", ".raw"):
        dt = golden.dtype
    else:
        dt = None
    if args.shape:
        shape = tuple(int(x) for x in args.shape.split(","))
    elif args.hls_output.suffix in (".bin", ".raw"):
        shape = tuple(golden.shape)
    else:
        shape = None

    hls = load_hls_output(args.hls_output, dt, shape)
    result = compare(golden, hls)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


def _all_layers_mode(args: argparse.Namespace) -> int:
    """Iterate every layer_*.npz under args.golden and look for the matching
    HLS output in args.hls_output (treated as a directory)."""
    golden_dir = args.golden
    hls_dir = args.hls_output
    if not golden_dir.is_dir() or not hls_dir.is_dir():
        print("--all-layers requires both --golden and --hls-output be directories",
              file=sys.stderr)
        return 2
    all_ok = True
    summary = {}
    for npz in sorted(golden_dir.glob("layer_*.npz")):
        stem = npz.stem  # layer_00_stem
        hls_candidate = next(iter(hls_dir.glob(f"{stem}*.bin")
                                  or hls_dir.glob(f"{stem}*.npy")), None)
        if hls_candidate is None:
            print(f"[{stem}] no HLS output found in {hls_dir}", file=sys.stderr)
            summary[stem] = {"ok": False, "reason": "missing hls output"}
            all_ok = False
            continue
        golden = load_golden(npz)
        hls = load_hls_output(
            hls_candidate,
            dtype=golden.dtype if hls_candidate.suffix in (".bin", ".raw") else None,
            shape=tuple(golden.shape) if hls_candidate.suffix in (".bin", ".raw") else None,
        )
        result = compare(golden, hls)
        summary[stem] = result
        flag = "OK " if result["ok"] else "FAIL"
        n_total = result.get("n_elements", 0)
        n_bad = result.get("n_mismatches", 0)
        print(f"[{stem}] {flag}  total={n_total}  mismatches={n_bad}")
        if not result["ok"]:
            all_ok = False

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(summary, indent=2))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
