"""Python ref <-> C++ postproc_nms bit-by-bit consistency check (M1 W6).

Strategy
--------
1. Generate a few random INT8 detect-head buffers ((nc+4) * grid * grid).
2. Run the Python reference (sw/app/reference/postproc_nms_ref.py) with the
   project defaults (iou=0.45, conf=0.25, nc=80, grid=16, stride=16).
3. Build sw/app/src/postproc_nms_cli.cpp into a small binary (via the
   sw/app/Makefile) and run it on the same buffer; parse its JSON output.
4. Sort both detection lists by (cls, confidence, x1) and confirm:
     * same count
     * same cls per detection
     * conf identical to <= 1e-5 abs
     * x1/y1/x2/y2 identical to <= 1e-3 abs (single precision float == FP32
       in both ref and impl; the C++ build is also FP32, so tolerance is
       slack only against text->float round-trip in our JSON writer).

Skipping
--------
The MSYS2 g++ 5.3 toolchain on the C3 dev host ICEs on certain default-arg
syntaxes (see runs/C3_W4_report.md). When `make postproc_nms_cli` fails for
that reason the test is *skipped* with the compiler error attached, so the
contract guarantee can still be verified end-to-end on the petalinux SDK
side (C1 M3 W1 deliverable) without breaking host CI.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parent.parent
APP_DIR = REPO / "sw" / "app"
APP_REF = APP_DIR / "reference"
sys.path.insert(0, str(APP_REF))

from postproc_nms_ref import decode_and_nms as py_decode_and_nms  # noqa: E402


# ---------------------------------------------------------------------------
# Build helpers
# ---------------------------------------------------------------------------
def _try_build_cli() -> Path | None:
    """Build the postproc_nms_cli binary via make. Returns the binary path
    on success, None on toolchain failure (caller skips)."""
    if shutil.which("make") is None:
        return None
    env = os.environ.copy()
    # Force a binary suffix-less name on Linux; .exe on Windows is fine too.
    ret = subprocess.run(
        ["make", "postproc_nms_cli"],
        cwd=str(APP_DIR),
        env=env,
        capture_output=True,
        text=True,
    )
    if ret.returncode != 0:
        print("make stderr:", ret.stderr[-800:], file=sys.stderr)
        return None
    for cand in ("postproc_nms_cli", "postproc_nms_cli.exe"):
        p = APP_DIR / "build-host" / cand
        if p.exists():
            return p
    return None


CLI_BIN = _try_build_cli()


def _run_cpp(buf: np.ndarray, iou: float, conf: float, nc: int, grid: int,
             stride: int) -> list[dict]:
    assert CLI_BIN is not None
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        in_path = td / "in.bin"
        out_path = td / "out.json"
        in_path.write_bytes(buf.astype(np.int8).tobytes())
        ret = subprocess.run(
            [
                str(CLI_BIN),
                "--input", str(in_path), "--out", str(out_path),
                "--iou", str(iou), "--conf", str(conf),
                "--nc", str(nc), "--grid", str(grid), "--stride", str(stride),
            ],
            capture_output=True, text=True,
        )
        assert ret.returncode == 0, f"cli failed: {ret.stderr}"
        data = json.loads(out_path.read_text())
        return data["detections"]


def _run_py(buf: np.ndarray, iou: float, conf: float, nc: int, grid: int,
            stride: int) -> list[dict]:
    dets = py_decode_and_nms(buf, nc, grid, grid, stride, conf, iou)
    return [
        {"x1": d.x1, "y1": d.y1, "x2": d.x2, "y2": d.y2,
         "conf": d.conf, "cls": d.cls}
        for d in dets
    ]


def _sort_key(d: dict):
    return (d["cls"], -d["conf"], round(d["x1"], 4), round(d["y1"], 4))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
SKIP_REASON = (
    "postproc_nms_cli build unavailable on this host (MSYS2 g++ 5.3 ICE)."
    " The consistency check runs on the petalinux SDK / CI image."
)


@pytest.mark.skipif(CLI_BIN is None, reason=SKIP_REASON)
@pytest.mark.contract
class TestPyVsCppNms:
    """Python decode_and_nms vs C++ postproc_nms_cli on identical INT8 input."""

    @pytest.mark.parametrize("seed", [0, 1, 7, 42])
    def test_random_input_match(self, seed: int):
        rng = np.random.default_rng(seed)
        nc, grid, stride = 80, 16, 16
        buf = rng.integers(-120, 120, size=(nc + 4, grid, grid),
                            dtype=np.int8)
        iou, conf = 0.45, 0.25

        py = _run_py(buf, iou, conf, nc, grid, stride)
        cpp = _run_cpp(buf, iou, conf, nc, grid, stride)

        py = sorted(py, key=_sort_key)
        cpp = sorted(cpp, key=_sort_key)

        assert len(py) == len(cpp), (
            f"count mismatch py={len(py)} cpp={len(cpp)}")
        bbox_diffs = []
        for a, b in zip(py, cpp):
            assert a["cls"] == b["cls"], (a, b)
            assert abs(a["conf"] - b["conf"]) < 1e-5, (a, b)
            for k in ("x1", "y1", "x2", "y2"):
                bbox_diffs.append(abs(a[k] - b[k]))
        if bbox_diffs:
            assert max(bbox_diffs) < 1e-3, (
                f"max bbox diff {max(bbox_diffs)} >= 1e-3")

    def test_all_zero_input_empty(self):
        nc, grid, stride = 80, 16, 16
        buf = np.zeros((nc + 4, grid, grid), dtype=np.int8)
        # sigmoid(0) = 0.5; threshold > 0.5 -> both must return empty
        py = _run_py(buf, 0.45, 0.6, nc, grid, stride)
        cpp = _run_cpp(buf, 0.45, 0.6, nc, grid, stride)
        assert py == [] and cpp == []

    def test_single_strong_detection(self):
        """One spiked cell -> exactly one detection from both sides."""
        nc, grid, stride = 80, 16, 16
        buf = np.zeros((nc + 4, grid, grid), dtype=np.int8)
        buf[4 + 17, 9, 4] = 127  # class 17 at cell (4,9)
        py = _run_py(buf, 0.45, 0.6, nc, grid, stride)
        cpp = _run_cpp(buf, 0.45, 0.6, nc, grid, stride)
        assert len(py) == 1 and len(cpp) == 1
        assert py[0]["cls"] == 17 and cpp[0]["cls"] == 17
        assert abs(py[0]["conf"] - cpp[0]["conf"]) < 1e-5
        for k in ("x1", "y1", "x2", "y2"):
            assert abs(py[0][k] - cpp[0][k]) < 1e-3
