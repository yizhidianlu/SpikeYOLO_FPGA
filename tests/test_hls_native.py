"""HLS algorithm regression — DUT vs reference, native C++ build.

Runs the same testbench that Vitis HLS C-sim runs, but without needing a
Vitis license. Skipped automatically when no C++ compiler is found, so
this is a no-op on developer machines that lack g++/clang.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
HLS_DIR = REPO_ROOT / "hw" / "hls"


def _find_cxx() -> str | None:
    for c in ("g++", "clang++", "c++"):
        if shutil.which(c):
            return c
    return None


@pytest.mark.contract
def test_native_csim_passes():
    cxx = _find_cxx()
    if cxx is None:
        pytest.skip("no C++ compiler in PATH (g++/clang++/c++) — CI will run via vitis_hls")

    out_dir = HLS_DIR / "build"
    out_dir.mkdir(exist_ok=True)
    binary = out_dir / "tb_conv2d_int"
    if binary.exists():
        binary.unlink()
    # Compile testbench + DUT together
    cmd = [
        cxx, "-std=c++17", "-O2", "-Wall", "-Wno-unknown-pragmas",
        "-I", str(HLS_DIR / "include"),
        "-I", str(HLS_DIR / "sim"),
        str(HLS_DIR / "sim" / "tb_conv2d_int.cpp"),
        str(HLS_DIR / "src" / "conv2d_int.cpp"),
        "-o", str(binary),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        pytest.fail(f"native compile failed:\n{r.stderr}")

    # Execute
    r = subprocess.run([str(binary)], capture_output=True, text=True, timeout=300)
    if r.returncode != 0 or "CSIM PASS" not in r.stdout:
        pytest.fail(
            f"native csim FAILED\n"
            f"--- stdout ---\n{r.stdout}\n"
            f"--- stderr ---\n{r.stderr}\n"
        )
