"""Bit-exact comparator: NumPy golden ↔ HLS C-sim output.

This is the workhorse for B1's CI gate. Two operating modes:

* **Single-layer file mode** (``--golden a.npz --hls-output b.bin``).
  The HLS testbench writes its layer outputs as raw little-endian binary
  blobs (so it can run without a NumPy runtime); this script loads the
  matching golden tensor and asserts every INT element matches. Supports:
  - ``.bin``  raw byte stream, dtype + shape provided via ``--dtype`` /
              ``--shape`` flags (or sniffed from the golden tensor).
  - ``.npy``  standard NumPy format.

* **Auto host_csim driver mode** (``--all-layers``). B1's actual
  ``hw/hls/Makefile`` ships ``host_csim_layer_{00,01,03,08}`` targets that
  do the DUT vs GOLDEN compare *inside* the testbench (no .bin written to
  disk). This mode invokes those make targets, parses each binary's stdout
  for the ``[layer_NN] DUT vs GOLDEN ...`` lines and the
  ``CSIM PASS / FAIL_GOLDEN`` sentinel, and aggregates everything into
  ``runs/numpy_vs_hls_diff.json``. Mismatch indices reported by the
  testbench (``[layer_NN][DUT vs GOLD] idx=N dut=X gold=Y diff=Z``) are
  captured up to the first 5.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np


_REPO_ROOT = Path(__file__).resolve().parents[2]


# host_csim_layer_NN targets B1 has wired in hw/hls/Makefile (W3 status).
# Update this list as B1 turns on more layers.
_HOST_CSIM_LAYERS: List[Tuple[int, str]] = [
    (0,  "stem"),
    (1,  "acb1"),
    (3,  "acb2a"),    # sep_conv smoke driven by gen_sep_conv_smoke
    (8,  "sppf"),
]


# Regex to pull "idx=N dut=X gold=Y diff=Z" from testbench stderr.
# B1 testbenches use either ``[layer_NN]`` (ms_downsampling, ms_all_conv_block,
# spike_sppf) or a kernel-name prefix like ``[sep_conv]``, so we accept any
# bracketed prefix.
_MISMATCH_RE = re.compile(
    r"\[\w+\]\[DUT vs GOLD\]\s+idx=(\d+)\s+dut=(-?\d+)\s+gold=(-?\d+)\s+diff=(-?\d+)"
)
# Regex to pull DUT-vs-REF mismatch nature for context.
_DUT_REF_RE = re.compile(r"\[\w+\] DUT vs REF FAILED:\s+(\d+)\s+mismatches")
_DUT_GOLD_FAIL_RE = re.compile(
    r"\[\w+\] DUT vs GOLDEN FAILED:\s+(\d+)\s+/\s+(\d+)"
)
_DUT_REF_OK_RE = re.compile(r"\[\w+\] DUT vs REF OK\s+\((\d+)\s+elems\)")


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
    p.add_argument("--golden", type=Path, default=None,
                   help="NumPy golden tensor (.npz or .npy). Required unless --all-layers.")
    p.add_argument("--hls-output", type=Path, default=None,
                   help="HLS C-sim output (.bin / .raw / .npy). Required unless --all-layers.")
    p.add_argument("--key", default="output", help="key inside golden .npz")
    p.add_argument("--dtype", default=None, help="dtype for raw .bin (e.g. int32)")
    p.add_argument("--shape", default=None,
                   help="shape for raw .bin as comma-separated ints, e.g. 1,24,64,64")
    p.add_argument("--report", type=Path, default=None,
                   help="write JSON diff report here")
    p.add_argument("--all-layers", action="store_true",
                   help="drive hw/hls/Makefile host_csim_layer_NN targets for "
                        "all wired-up layers, parse stdout for PASS/FAIL")
    args = p.parse_args(argv)

    if args.all_layers:
        return _all_layers_mode(args)
    if args.golden is None or args.hls_output is None:
        p.error("--golden and --hls-output are required unless --all-layers is set")

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


def _parse_csim_output(stdout: str, stderr: str) -> Dict:
    """Parse a B1 host_csim binary's combined stdout/stderr.

    Returns a dict with at least:
      - ok:             bool   (True iff CSIM PASS line is present)
      - sentinel:       str    (PASS / FAIL_GOLDEN / FAIL / UNKNOWN)
      - n_elements:     int    (from "DUT vs REF OK (N elems)" if seen)
      - n_mismatches:   int    (from "DUT vs GOLDEN FAILED: N / M" if seen)
      - first_mismatches: list of {index, golden, hls, diff} (up to 5)
    """
    combined = stdout + "\n" + stderr
    sentinel = "UNKNOWN"
    if "CSIM PASS" in stdout or "CSIM PASS" in stderr:
        sentinel = "PASS"
    elif "CSIM FAIL_GOLDEN" in combined:
        sentinel = "FAIL_GOLDEN"
    elif "CSIM FAIL" in combined:
        sentinel = "FAIL"

    n_elements = 0
    m = _DUT_REF_OK_RE.search(combined)
    if m:
        n_elements = int(m.group(1))

    n_mismatches = 0
    m = _DUT_GOLD_FAIL_RE.search(combined)
    if m:
        n_mismatches = int(m.group(1))
        if n_elements == 0:
            n_elements = int(m.group(2))

    examples: List[Dict] = []
    for hit in _MISMATCH_RE.finditer(combined):
        examples.append({
            "index": [int(hit.group(1))],
            "golden": int(hit.group(3)),
            "hls":    int(hit.group(2)),
            "diff":   int(hit.group(4)),
        })
        if len(examples) >= 5:
            break

    return {
        "ok": sentinel == "PASS",
        "sentinel": sentinel,
        "n_elements": n_elements,
        "n_mismatches": n_mismatches,
        "first_mismatches": examples,
    }


def _run_make_target(target: str, hw_hls_dir: Path) -> Tuple[int, str, str]:
    """Invoke ``make <target>`` inside hw/hls/. Returns (rc, stdout, stderr).

    On Windows, GNU make typically ships as ``mingw32-make.exe`` from
    msys2/conda. We probe both the bare name and the ``.exe`` suffix because
    Python's subprocess on Windows does not always honour PATHEXT (it does
    via shutil.which, so we route through that explicitly).
    """
    import shutil
    candidates = ["mingw32-make", "make", "mingw32-make.exe", "make.exe"]
    resolved = None
    for tool in candidates:
        path = shutil.which(tool)
        if path is not None:
            resolved = path
            break
    if resolved is None:
        return 127, "", f"no make tool found on PATH (tried: {', '.join(candidates)})"
    # If caller hasn't already set PYTHON, leave the env alone so the
    # Makefile's default `PYTHON ?= python` resolves via PATH. We used to
    # inject PYTHON=sys.executable, but on Windows that path contains
    # backslashes which mingw32-make hands to /usr/bin/sh which then strips
    # them ("D:\Application\..." -> "D:Application..."). The python on PATH
    # is always the same conda env in practice, and forward-slashing the
    # path breaks DOS-style shells. Easiest: don't override.
    env = dict(os.environ)
    if "PYTHON" not in env:
        # Best-effort: only set when sys.executable contains no backslash
        # (i.e. POSIX) — otherwise rely on `python` being on PATH.
        if "\\" not in sys.executable:
            env["PYTHON"] = sys.executable
    try:
        proc = subprocess.run(
            [resolved, target],
            cwd=str(hw_hls_dir),
            capture_output=True,
            text=True,
            env=env,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except OSError as exc:
        return 127, "", f"failed to invoke {resolved}: {exc}"


def _all_layers_mode(args: argparse.Namespace) -> int:
    """Drive B1's host_csim_layer_NN make targets and aggregate results.

    For each layer in ``_HOST_CSIM_LAYERS`` we invoke the corresponding
    ``host_csim_layer_NN`` target (which already does DUT vs GOLDEN compare
    against ``tests/golden/exploded/layer_NN_*/output.npy``), parse the
    binary's stdout/stderr for the CSIM sentinel + mismatch details, and
    emit one consolidated record per layer to
    ``runs/numpy_vs_hls_diff.json`` (or ``--report`` override).

    Backwards compatible: if ``--hls-output`` is a directory of pre-written
    .bin files, we fall back to the file-based comparator path used by
    earlier sprints.
    """
    summary: Dict[str, Dict] = {}
    all_ok = True

    # Backwards-compat: directory-of-bins mode (legacy, kept for whoever wires
    # vitis_hls cosim later — Vitis can dump tensors to .bin via the testbench).
    if args.hls_output is not None and Path(args.hls_output).is_dir():
        hls_dir = Path(args.hls_output)
        golden_dir = Path(args.golden) if args.golden is not None else (
            _REPO_ROOT / "tests" / "golden")
        for npz in sorted(golden_dir.glob("layer_*.npz")):
            stem = npz.stem
            cands = list(hls_dir.glob(f"{stem}*.bin")) + list(hls_dir.glob(f"{stem}*.npy"))
            if not cands:
                summary[stem] = {"ok": False, "reason": "missing hls output"}
                all_ok = False
                continue
            hls_candidate = cands[0]
            golden = load_golden(npz)
            hls = load_hls_output(
                hls_candidate,
                dtype=golden.dtype if hls_candidate.suffix in (".bin", ".raw") else None,
                shape=tuple(golden.shape) if hls_candidate.suffix in (".bin", ".raw") else None,
            )
            result = compare(golden, hls)
            summary[stem] = result
            if not result["ok"]:
                all_ok = False
            flag = "OK " if result["ok"] else "FAIL"
            print(f"[{stem}] {flag}  total={result.get('n_elements',0)}  "
                  f"mismatches={result.get('n_mismatches',0)}")
    else:
        # Default: drive the make targets B1 ships in hw/hls/Makefile.
        hw_hls = _REPO_ROOT / "hw" / "hls"
        if not (hw_hls / "Makefile").exists():
            print(f"[--all-layers] no Makefile at {hw_hls}/Makefile",
                  file=sys.stderr)
            return 2
        for layer_idx, name in _HOST_CSIM_LAYERS:
            tag = f"layer_{layer_idx:02d}_{name}"
            target = f"host_csim_layer_{layer_idx:02d}"
            print(f"[{tag}] -> make {target}")
            rc, out, err = _run_make_target(target, hw_hls)
            parsed = _parse_csim_output(out, err)
            parsed["layer_idx"] = layer_idx
            parsed["layer_name"] = name
            parsed["make_target"] = target
            parsed["make_rc"] = rc
            # Make may exit non-zero even on PASS if a sub-rule prints to
            # stderr; trust the sentinel first, fall back to rc.
            if parsed["sentinel"] == "PASS":
                parsed["ok"] = True
            elif parsed["sentinel"] in ("FAIL", "FAIL_GOLDEN"):
                parsed["ok"] = False
            else:
                parsed["ok"] = (rc == 0)
            if not parsed["ok"]:
                all_ok = False
            flag = "PASS" if parsed["ok"] else "FAIL"
            print(f"[{tag}] {flag}  rc={rc}  sentinel={parsed['sentinel']}  "
                  f"elems={parsed['n_elements']}  "
                  f"mismatches={parsed['n_mismatches']}")
            summary[tag] = parsed

    out_path = args.report or (_REPO_ROOT / "runs" / "numpy_vs_hls_diff.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "all_ok": all_ok,
        "n_layers": len(summary),
        "layers": summary,
    }, indent=2))
    print(f"[numpy_vs_hls] wrote diff report -> {out_path}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
