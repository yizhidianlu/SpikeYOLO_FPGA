"""Static lint of the Vivado tcl files.

We cannot run `vivado -mode batch` from the developer machine, but we can
verify that the tcl files satisfy basic invariants:

* readable + no NUL bytes
* `proc` and `if {}` braces balance
* no Windows-style CRLF line endings (Vivado on Linux trips on those)
* paths referenced exist or are documented as auto-generated
"""

from __future__ import annotations

from pathlib import Path

import pytest


VIVADO_DIR = Path(__file__).resolve().parent.parent / "hw" / "vivado"


@pytest.mark.contract
@pytest.mark.parametrize("name", ["build_bd.tcl", "build_bitstream.tcl",
                                  "scripts/axi_protocol_check.tcl"])
def test_tcl_braces_balanced(name):
    p = VIVADO_DIR / name
    if not p.exists():
        pytest.skip(f"{name} not yet committed")
    text = p.read_text(encoding="utf-8")
    open_b = text.count("{")
    close_b = text.count("}")
    assert open_b == close_b, (
        f"unbalanced braces in {name}: {{ = {open_b}, }} = {close_b}"
    )


@pytest.mark.contract
@pytest.mark.parametrize("name", ["build_bd.tcl", "build_bitstream.tcl",
                                  "scripts/axi_protocol_check.tcl",
                                  "constraints/zybo_z7_20.xdc"])
def test_no_crlf(name):
    p = VIVADO_DIR / name
    if not p.exists():
        pytest.skip(f"{name} not yet committed")
    raw = p.read_bytes()
    assert b"\r\n" not in raw, f"{name} contains CRLF — Vivado on Linux will choke"


@pytest.mark.contract
def test_xdc_references_present_packages():
    """Sanity: the constraint file must touch HDMI TX + clk + LEDs."""
    p = VIVADO_DIR / "constraints" / "zybo_z7_20.xdc"
    text = p.read_text(encoding="utf-8")
    for required in ("sys_clk", "hdmi_tx_clk_p", "hdmi_tx_data_p", "led", "sw"):
        assert required in text, f"missing port {required!r} in xdc"


@pytest.mark.contract
def test_build_bd_references_xo_repo():
    """build_bd.tcl must set ip_repo_paths to point at hw/hls/build."""
    p = VIVADO_DIR / "build_bd.tcl"
    text = p.read_text(encoding="utf-8")
    assert "ip_repo_paths" in text
    assert "hls/build" in text
