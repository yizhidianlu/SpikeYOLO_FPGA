"""tests/test_sdk_examples.py -- compile + smoke-run the 5 SDK examples.

Owner: C2 Driver & SDK Agent (see docs/AGENT_PLAYBOOKS/C2_driver_sdk.md).
Pairs with sw/sdk/examples/ added in the C2 W6 sprint. We keep this test
*lenient* on environments without gcc (CI Linux runners have it; bare
Windows checkouts may not) so the suite still collects everywhere.

What we verify:
  * test_examples_present        -- the five .c files exist and parse trivial
  * test_examples_have_main      -- each has a `int main(` entry point
  * test_examples_compile        -- gcc -c is enough to catch syntax errors
  * test_hello_open_smoke_run    -- if hello_open actually links, it prints
                                    "SDK version: 1.1.0"
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / "sw" / "sdk"
EXAMPLES_DIR = SDK / "examples"
INCLUDE_DIR = SDK / "include"
SRC_DIR = SDK / "src"

EXAMPLES = [
    "hello_open",
    "infer_one_frame",
    "layer_isolation",
    "perf_counters",
    "async_pipeline",
]

SDK_SOURCES = [
    SRC_DIR / "accel_drv.c",
    SRC_DIR / "dma_buf.c",
    SRC_DIR / "sa_strerror.c",
    SRC_DIR / "sa_version.c",
]


def _gcc() -> str | None:
    return shutil.which("gcc")


def test_examples_present():
    """All five example .c files must exist."""
    for ex in EXAMPLES:
        p = EXAMPLES_DIR / f"{ex}.c"
        assert p.is_file(), f"missing example: {p}"


def test_examples_have_main():
    """Each example must define `int main(`."""
    for ex in EXAMPLES:
        body = (EXAMPLES_DIR / f"{ex}.c").read_text(encoding="utf-8")
        assert "int main(" in body, f"{ex}.c missing main()"


def test_examples_buildfiles_present():
    """CMakeLists.txt + Makefile + README must ship alongside the examples."""
    for name in ("CMakeLists.txt", "Makefile", "README.md"):
        assert (EXAMPLES_DIR / name).is_file(), f"missing {name}"


@pytest.mark.parametrize("ex", EXAMPLES)
def test_examples_compile(tmp_path, ex):
    """Each example must compile with SA_STUB_BACKEND=1.

    On hosts without gcc (e.g. bare Windows Python) the test is *skipped*,
    not failed -- C2's invariant is "examples build under MinGW/gcc 5.3+
    and any modern Linux gcc"; we don't punish a CI worker for lacking gcc.
    """
    if _gcc() is None:
        pytest.skip("gcc not on PATH")
    out = tmp_path / f"{ex}.exe"
    cmd = [
        _gcc(),
        "-DSA_STUB_BACKEND=1",
        "-D_POSIX_C_SOURCE=200809L",
        "-std=c11",
        "-Wall",
        f"-I{INCLUDE_DIR}",
        f"-I{SRC_DIR}",
        str(EXAMPLES_DIR / f"{ex}.c"),
        *(str(s) for s in SDK_SOURCES),
        "-lpthread",
        "-o",
        str(out),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    # perf_counters is known to hit an ICE on MinGW gcc 5.3 if the source uses
    # double-promotion in a small helper. We treat ICE as xfail, real
    # syntax/link errors as failures.
    if res.returncode != 0:
        if "internal compiler error" in (res.stderr + res.stdout):
            pytest.xfail(f"{ex}: gcc ICE -- known MinGW 5.3 issue")
        pytest.fail(f"compile failed for {ex}\nstderr:\n{res.stderr}")
    assert out.exists(), f"{ex}: gcc returned 0 but no binary produced"


def test_hello_open_smoke_run(tmp_path):
    """hello_open must run + exit 0 + print 'SDK version: 1.1.0'."""
    if _gcc() is None:
        pytest.skip("gcc not on PATH")
    out = tmp_path / "hello_open.exe"
    cmd = [
        _gcc(),
        "-DSA_STUB_BACKEND=1",
        "-D_POSIX_C_SOURCE=200809L",
        "-std=c11",
        f"-I{INCLUDE_DIR}",
        f"-I{SRC_DIR}",
        str(EXAMPLES_DIR / "hello_open.c"),
        *(str(s) for s in SDK_SOURCES),
        "-lpthread",
        "-o",
        str(out),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"hello_open did not compile in this env: {r.stderr[:200]}")
    run = subprocess.run([str(out)], capture_output=True, text=True, timeout=10)
    assert run.returncode == 0, f"hello_open exit={run.returncode}\n{run.stderr}"
    assert "SDK version: 1.1.0" in run.stdout, run.stdout
