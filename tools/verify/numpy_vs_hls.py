"""Bit-exact comparator: NumPy golden ↔ HLS C-sim output.

This is the workhorse for B1's CI gate. Three operating modes:

* **Single-layer file mode** (``--golden a.npz --hls-output b.bin``).
  The HLS testbench writes its layer outputs as raw little-endian binary
  blobs (so it can run without a NumPy runtime); this script loads the
  matching golden tensor and asserts every INT element matches. Supports:
  - ``.bin``  raw byte stream, dtype + shape provided via ``--dtype`` /
              ``--shape`` flags (or sniffed from the golden tensor).
  - ``.npy``  standard NumPy format.

* **Auto host_csim driver mode** (``--all-layers``). B1's actual
  ``hw/hls/Makefile`` ships ``host_csim_layer_{00,01,03,08,11}`` plus
  ``host_csim_top`` targets that do the DUT vs GOLDEN compare *inside* the
  testbench (no .bin written to disk). This mode invokes those make
  targets, parses each binary's stdout for the ``[layer_NN] DUT vs GOLDEN
  ...`` lines and the ``CSIM PASS / FAIL_GOLDEN`` sentinel, and aggregates
  everything into ``runs/numpy_vs_hls_diff.json``. Mismatch indices
  reported by the testbench (``[layer_NN][DUT vs GOLD] idx=N dut=X gold=Y
  diff=Z``) are captured up to the first 5. Layers without a wired-up
  host_csim_layer_NN target are gracefully marked ``skip_no_hls_bin`` (not
  fail) so the gate stays green while B1 builds out the missing targets.

* **NumPy self-consistency mode** (``--self-consistency``). Re-runs the
  per-layer ``tools/fpga/numpy_reference`` primitive on the stored
  ``input`` of each layer .npz and asserts byte-identical match against
  the stored ``output``. This is contract-2 self-consistency
  (NumPy ↔ NumPy stability under the v1.0.2 weights), and is the W5
  fallback path for layers 02/04/05/06/07/09/10 that don't yet have an
  individual host_csim_layer_NN target on the HLS side.
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
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# host_csim_layer_NN targets B1 has wired in hw/hls/Makefile (W5 status).
# Update this list as B1 turns on more layers. Layers that appear in the
# golden index but not here are gracefully marked ``skip_no_hls_bin`` in the
# --all-layers report rather than failing.
_HOST_CSIM_LAYERS: List[Tuple[int, str]] = [
    (0,  "stem"),
    (1,  "acb1"),
    (3,  "acb2a"),    # sep_conv smoke driven by gen_sep_conv_smoke
    (8,  "sppf"),
    (11, "detect"),   # W4: TB_DETECT_HEAD added by B1
]

# Optional top-level testbench (full tiny_fpga forward DUT vs GOLDEN).
_HOST_CSIM_TOP = ("top", "host_csim_top")

# Golden index layers we expect to see. Used to mark missing host_csim_layer_NN
# targets as ``skip_no_hls_bin`` (informational, not a CI fail) in the
# --all-layers report.
_ALL_GOLDEN_LAYERS: List[Tuple[int, str]] = [
    (0,  "stem"),
    (1,  "acb1"),
    (2,  "ds1"),
    (3,  "acb2a"),
    (4,  "acb2b"),
    (5,  "ds2"),
    (6,  "acb3a"),
    (7,  "acb3b"),
    (8,  "sppf"),
    (9,  "head_reduce"),
    (10, "head_refine"),
    (11, "detect"),
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
    p.add_argument("--self-consistency", action="store_true",
                   help="re-run numpy_reference primitive per layer on the "
                        "stored input and assert byte-identical match against "
                        "the stored output (contract-2 NumPy/NumPy stability). "
                        "No HLS / make involvement.")
    p.add_argument("--weights", type=Path,
                   default=_REPO_ROOT / "models" / "tiny_fpga_int8.npz",
                   help="A1 PTQ .npz (default: models/tiny_fpga_int8.npz). "
                        "Used by --self-consistency.")
    p.add_argument("--golden-dir", type=Path,
                   default=_REPO_ROOT / "tests" / "golden",
                   help="directory holding golden_index.json and layer_*.npz. "
                        "Used by --self-consistency.")
    p.add_argument("--out", type=Path, default=None,
                   help="alias for --report; preferred for --self-consistency")
    # --- W6 board-regression mode (skeleton; populated when board runs land) ---
    p.add_argument("--board-regression", action="store_true",
                   help="(M4 W4) compare a board-produced predictions JSON "
                        "against tests/golden/coco_val100.json. Requires "
                        "--board-out (the board JSON) and uses --iou-threshold "
                        "/ --pass-rate to grade matches per image.")
    p.add_argument("--board-out", type=Path, default=None,
                   help="path to board-produced predictions JSON "
                        "(same Contract 6 schema as coco_val100.json)")
    p.add_argument("--iou-threshold", type=float, default=0.99,
                   help="(--board-regression) minimum IoU for a det to count "
                        "as a match against the golden bbox")
    p.add_argument("--pass-rate", type=float, default=0.95,
                   help="(--board-regression) fraction of images that must "
                        "match (>= iou_threshold) for the gate to pass")
    args = p.parse_args(argv)

    if args.board_regression:
        return _board_regression_mode(args)
    if args.self_consistency:
        return _self_consistency_mode(args)
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


def _scan_makefile_targets(makefile_path: Path) -> set:
    """Return the set of target names declared at line-start in the Makefile.

    Used by --all-layers to gracefully skip host_csim_layer_NN entries that
    don't exist yet, rather than calling ``make`` and getting a ``no rule``
    error. We deliberately use a cheap line-prefix sniff (no full Makefile
    parse) — only target-definition lines are recognised.
    """
    targets: set = set()
    if not makefile_path.exists():
        return targets
    try:
        for raw in makefile_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.rstrip()
            if not line or line[0] in " \t#":
                continue
            # crude target match: 'name: ...' or 'name :'
            head = line.split(":", 1)[0].strip()
            if not head:
                continue
            # ignore variable assignments and special directives
            if "=" in head or head.startswith(".") and head not in (".PHONY",):
                continue
            # target names may carry no spaces
            if " " in head or "\t" in head:
                continue
            targets.add(head)
    except OSError:
        pass
    return targets


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


def run_numpy_self_consistency_layer(
    layer_idx: int,
    layer_name: str,
    numpy_weights,
    golden_dir: Path,
) -> Dict:
    """Re-run the numpy_reference primitive for one layer and compare to its
    stored golden output. Pure NumPy. Returns a JSON-serialisable dict:

      {pass: bool, shape: [...], mismatch_count: int,
       first_mismatches: [{index, golden, numpy_out, diff}, ...]}

    Mirrors the layer→primitive mapping in tests/test_bit_exact.py.
    Raises FileNotFoundError if the layer .npz is missing.
    """
    from tools.fpga.numpy_reference import (
        ms_downsampling, ms_standard_conv, ms_all_conv_block, spike_sppf,
    )

    npz_path = golden_dir / f"layer_{layer_idx:02d}_{layer_name}.npz"
    if not npz_path.exists():
        raise FileNotFoundError(npz_path)
    with np.load(npz_path, allow_pickle=False) as d:
        x_in = d["input"]
        expected = d["output"]

    if layer_name == "stem":
        y = ms_downsampling(x_in, numpy_weights[1]["encode_conv"])
    elif layer_name == "acb1":
        w = numpy_weights[2]
        y = ms_all_conv_block(x_in, w["sep"], w["conv1"], w["conv2"])
    elif layer_name == "ds1":
        y = ms_downsampling(x_in, numpy_weights[3]["encode_conv"])
    elif layer_name == "acb2a":
        w = numpy_weights[4][0]
        y = ms_all_conv_block(x_in, w["sep"], w["conv1"], w["conv2"])
    elif layer_name == "acb2b":
        w = numpy_weights[4][1]
        y = ms_all_conv_block(x_in, w["sep"], w["conv1"], w["conv2"])
    elif layer_name == "ds2":
        y = ms_downsampling(x_in, numpy_weights[5]["encode_conv"])
    elif layer_name == "acb3a":
        w = numpy_weights[6][0]
        y = ms_all_conv_block(x_in, w["sep"], w["conv1"], w["conv2"])
    elif layer_name == "acb3b":
        w = numpy_weights[6][1]
        y = ms_all_conv_block(x_in, w["sep"], w["conv1"], w["conv2"])
    elif layer_name == "sppf":
        y = spike_sppf(x_in,
                       numpy_weights[7]["cv1"],
                       numpy_weights[7]["cv2"], k=5)
    elif layer_name == "head_reduce":
        y = ms_standard_conv(x_in, numpy_weights[8]["conv"])
    elif layer_name == "head_refine":
        w = numpy_weights[9]
        y = ms_all_conv_block(x_in, w["sep"], w["conv1"], w["conv2"])
    elif layer_name == "detect":
        # Detect head decode is on the PS — golden is just an INT8 cast.
        y = x_in.astype(np.int8)
    else:
        raise ValueError(f"unknown layer: {layer_name}")

    if y.shape != expected.shape:
        return {
            "pass": False,
            "shape": list(y.shape),
            "expected_shape": list(expected.shape),
            "mismatch_count": -1,
            "reason": "shape mismatch",
            "first_mismatches": [],
        }

    diff_mask = (y != expected)
    n_mis = int(diff_mask.sum())
    examples: List[Dict] = []
    if n_mis > 0:
        idxs = np.argwhere(diff_mask)[:5]
        for ix in idxs:
            tup = tuple(int(v) for v in ix)
            examples.append({
                "index": list(tup),
                "golden": int(expected[tup]),
                "numpy_out": int(y[tup]),
                "diff": int(y[tup]) - int(expected[tup]),
            })

    return {
        "pass": n_mis == 0,
        "shape": list(y.shape),
        "mismatch_count": n_mis,
        "first_mismatches": examples,
    }


def _load_numpy_weights(weights_npz: Path):
    """Helper: load A1 .npz + autocorrect pads + map to numpy_reference dicts.

    Returns ``(numpy_weights, sha256_hex)``. Raises if weights missing or schema
    mismatched.
    """
    import hashlib
    from tools.quant.weight_packer import read_npz
    from tools.quant.np_adapter import to_numpy_reference, schema_size
    from tools.verify.extract_golden import _autocorrect_layer_pads

    if not weights_npz.exists():
        raise FileNotFoundError(weights_npz)
    layers, _ = read_npz(weights_npz)
    _autocorrect_layer_pads(layers, verbose=False)
    if len(layers) != schema_size():
        raise ValueError(
            f"weights schema mismatch: got {len(layers)}, "
            f"expected {schema_size()}"
        )
    weights = to_numpy_reference(layers)
    sha = hashlib.sha256(weights_npz.read_bytes()).hexdigest()
    return weights, sha


def _board_regression_mode(args: argparse.Namespace) -> int:
    """(W6 skeleton, full implementation lands in M4 W4)

    Compare a board-produced predictions JSON against the golden
    ``tests/golden/coco_val100.json``. Both files share the Contract 6
    schema; per image we IoU-match each board det against the closest golden
    det, count the image as ``pass`` iff every golden det has a board match
    with ``IoU >= --iou-threshold``, and finally gate on
    ``image_pass_rate >= --pass-rate``.

    The C3 / D1 wiring story (M4 W4):
      1. board produces ``runs/board_coco_val100.json`` via ``coco_val_on_board.py``
         on the FPGA UIO backend
      2. host runs ``python tools/verify/numpy_vs_hls.py --board-regression
         --golden tests/golden/coco_val100.json
         --board-out runs/board_coco_val100.json``
      3. CI gate fails if the per-image pass rate drops below 0.95

    This W6 commit only ships the CLI surface + JSON-loading skeleton so
    every downstream agent can plumb their callers against the final flag
    names. The IoU-match scoring loop is intentionally NotImplemented until
    real board outputs land — falling through to it raises a
    ``NotImplementedError`` with a pointer to this docstring, which is the
    correct behaviour for an absent dependency.
    """
    golden_path = args.golden
    board_path = args.board_out
    if golden_path is None:
        print("[--board-regression] --golden is required "
              "(usually tests/golden/coco_val100.json)", file=sys.stderr)
        return 2
    if board_path is None:
        print("[--board-regression] --board-out is required "
              "(path to board-produced predictions JSON)", file=sys.stderr)
        return 2
    if not Path(golden_path).exists():
        print(f"[--board-regression] golden file missing: {golden_path}",
              file=sys.stderr)
        return 2
    if not Path(board_path).exists():
        # M4 W4 hasn't happened yet — emit a stub report so C3/D1 can wire
        # the call without crashing CI.
        print(f"[--board-regression] board file missing: {board_path} "
              f"(M4 W4 has not produced board output yet; emitting stub report)",
              file=sys.stderr)
        stub = {
            "gate_passed": False,
            "reason": "board_out missing — M4 W4 has not landed",
            "golden_path": str(golden_path),
            "board_path": str(board_path),
            "iou_threshold": args.iou_threshold,
            "pass_rate_threshold": args.pass_rate,
            "image_pass_rate": None,
            "images_total": 0,
            "images_passed": 0,
            "per_image": {},
            "status": "PENDING_BOARD_RUN",
        }
        out_path = args.report or args.out or (
            _REPO_ROOT / "runs" / "numpy_vs_hls_board_regression.json"
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(stub, indent=2))
        print(f"[--board-regression] wrote stub report -> {out_path}")
        return 0  # not a CI fail — just pending; D1 promotes to fail in M4 W4

    # Both files exist — schema-load them and defer the matcher to M4 W4.
    golden = json.loads(Path(golden_path).read_text(encoding="utf-8"))
    board = json.loads(Path(board_path).read_text(encoding="utf-8"))
    if golden.get("schema_version") != "1.0":
        print(f"[--board-regression] golden schema_version != 1.0: "
              f"{golden.get('schema_version')}", file=sys.stderr)
        return 2
    if board.get("schema_version") != "1.0":
        print(f"[--board-regression] board schema_version != 1.0: "
              f"{board.get('schema_version')}", file=sys.stderr)
        return 2
    # Weights-sha guard: board must have run the same .npz as golden.
    if golden.get("weights_sha256") != board.get("weights_sha256"):
        print(f"[--board-regression] sha256 mismatch — golden "
              f"{(golden.get('weights_sha256') or '')[:16]}... vs board "
              f"{(board.get('weights_sha256') or '')[:16]}...",
              file=sys.stderr)
        return 2

    raise NotImplementedError(
        "Per-image IoU matching loop lands in M4 W4 once board outputs "
        "are available. See _board_regression_mode docstring."
    )


def _self_consistency_mode(args: argparse.Namespace) -> int:
    """Re-run numpy_reference per-layer against tests/golden/layer_*.npz.

    Schema of the emitted JSON:

      {
        "weights_sha256": "...",
        "weights_path": "models/...",
        "golden_dir": "tests/golden",
        "tested_at": ISO-UTC,
        "layers": {
          "00_stem":   {"pass": true, "shape": [...], "mismatch_count": 0, ...},
          ...
          "11_detect": {"pass": ..., ...}
        },
        "summary": {"total": 12, "pass": 12, "fail": 0}
      }
    """
    from datetime import datetime, timezone

    weights_npz = args.weights
    golden_dir = args.golden_dir
    out_path = args.out or args.report or (
        _REPO_ROOT / "runs" / "numpy_self_consistency_full.json"
    )

    try:
        numpy_weights, sha = _load_numpy_weights(weights_npz)
    except FileNotFoundError as exc:
        print(f"[self-consistency] missing weights: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"[self-consistency] failed to load weights: {exc}", file=sys.stderr)
        return 2

    layers_report: Dict[str, Dict] = {}
    n_pass = 0
    n_fail = 0
    for layer_idx, layer_name in _ALL_GOLDEN_LAYERS:
        tag = f"{layer_idx:02d}_{layer_name}"
        try:
            res = run_numpy_self_consistency_layer(
                layer_idx, layer_name, numpy_weights, golden_dir,
            )
        except FileNotFoundError as exc:
            res = {"pass": False, "reason": f"missing golden npz: {exc}",
                   "mismatch_count": -1, "first_mismatches": []}
        layers_report[tag] = res
        flag = "PASS" if res.get("pass") else "FAIL"
        if res.get("pass"):
            n_pass += 1
        else:
            n_fail += 1
        print(f"[self-consistency] {tag:<22} {flag}  "
              f"mismatches={res.get('mismatch_count', '?')}")

    payload = {
        "weights_sha256": sha,
        "weights_path": str(weights_npz),
        "golden_dir": str(golden_dir),
        "tested_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S%z"),
        "layers": layers_report,
        "summary": {
            "total": len(_ALL_GOLDEN_LAYERS),
            "pass": n_pass,
            "fail": n_fail,
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2))
    print(f"[self-consistency] wrote {out_path} "
          f"({n_pass}/{len(_ALL_GOLDEN_LAYERS)} pass)")
    return 0 if n_fail == 0 else 1


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

        # Sniff the Makefile once so we know which host_csim_layer_NN /
        # host_csim_top targets are actually wired up. Layers in the golden
        # index without a target get marked ``skip_no_hls_bin`` (informational,
        # not a CI fail), keeping the gate green while B1 builds out missing
        # targets.
        wired_targets = _scan_makefile_targets(hw_hls / "Makefile")
        wired_layer_indices = {idx for idx, _ in _HOST_CSIM_LAYERS}

        for layer_idx, name in _ALL_GOLDEN_LAYERS:
            tag = f"layer_{layer_idx:02d}_{name}"
            target = f"host_csim_layer_{layer_idx:02d}"
            if layer_idx not in wired_layer_indices or target not in wired_targets:
                summary[tag] = {
                    "ok": True,  # informational skip, not a failure
                    "sentinel": "SKIP_NO_HLS_BIN",
                    "n_elements": 0,
                    "n_mismatches": 0,
                    "first_mismatches": [],
                    "layer_idx": layer_idx,
                    "layer_name": name,
                    "make_target": target,
                    "make_rc": None,
                    "skipped": True,
                    "skip_reason": "no host_csim_layer_NN target wired in Makefile",
                }
                print(f"[{tag}] SKIP  (no make target {target})")
                continue
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

        # Top-level testbench (full tiny_fpga forward), optional.
        if _HOST_CSIM_TOP[1] in wired_targets:
            top_tag = "top_tiny_fpga"
            target = _HOST_CSIM_TOP[1]
            print(f"[{top_tag}] -> make {target}")
            rc, out, err = _run_make_target(target, hw_hls)
            parsed = _parse_csim_output(out, err)
            parsed["layer_idx"] = -1
            parsed["layer_name"] = "top"
            parsed["make_target"] = target
            parsed["make_rc"] = rc
            if parsed["sentinel"] == "PASS":
                parsed["ok"] = True
            elif parsed["sentinel"] in ("FAIL", "FAIL_GOLDEN"):
                parsed["ok"] = False
            else:
                parsed["ok"] = (rc == 0)
            if not parsed["ok"]:
                all_ok = False
            flag = "PASS" if parsed["ok"] else "FAIL"
            print(f"[{top_tag}] {flag}  rc={rc}  sentinel={parsed['sentinel']}  "
                  f"elems={parsed['n_elements']}  "
                  f"mismatches={parsed['n_mismatches']}")
            summary[top_tag] = parsed

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
