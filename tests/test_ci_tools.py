"""Unit tests for tools/ci/{check_timing, check_utilization, dispatch_risk_issue}.

Pure parsers — feed synthetic report text, assert exit codes + JSON output.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tools.ci import check_timing, check_utilization, dispatch_risk_issue


# ---------------------------------------------------------------------------
# check_timing
# ---------------------------------------------------------------------------

VIVADO_TIMING_OK = """\
+----------------------+-------+
| Worst Negative Slack (WNS) |  0.423 ns |
| Total Negative Slack (TNS) |  0.000 ns |
+----------------------+-------+
"""

VIVADO_TIMING_FAIL = """\
| Worst Negative Slack (WNS)    |  -1.275 ns |
| Total Negative Slack (TNS)    | -25.30  ns |
"""

HLS_TIMING_OK = """\
+ Timing (ns):
    | Clock |  Target | Estimated | Uncertainty |
    | ap_clk|   10.00 |     8.42  |    1.25     |
"""


def test_check_timing_vivado_ok(tmp_path):
    p = tmp_path / "timing.rpt"
    p.write_text(VIVADO_TIMING_OK)
    rc = check_timing.main([str(p), "--wns-min", "0.0"])
    assert rc == 0


def test_check_timing_vivado_fail(tmp_path):
    p = tmp_path / "timing.rpt"
    p.write_text(VIVADO_TIMING_FAIL)
    rc = check_timing.main([str(p), "--wns-min", "0.0"])
    assert rc == 1


def test_check_timing_hls_ok(tmp_path):
    p = tmp_path / "synth.rpt"
    p.write_text(HLS_TIMING_OK)
    # HLS: Target=10.0, Estimated=8.42 -> WNS = 10.0 - 8.42 = 1.58
    rc = check_timing.main([str(p), "--wns-min", "0.0"])
    assert rc == 0


def test_check_timing_unparseable(tmp_path):
    p = tmp_path / "nope.rpt"
    p.write_text("nothing useful here\n")
    rc = check_timing.main([str(p)])
    assert rc == 2


# ---------------------------------------------------------------------------
# check_utilization
# ---------------------------------------------------------------------------

UTIL_REPORT = """\
| Resource    | Used | Available | Used % |
| ----------- | ---- | --------- | ------ |
| Slice LUTs                   |  21800 |     0 |        0 |     53200 | 40.98 |
| DSP                          |    128 |     0 |        0 |       220 | 58.18 |
| Block RAM Tile               |     62 |     0 |        0 |       140 | 44.28 |
"""

UTIL_REPORT_OVER = """\
| DSP                          |    210 |     0 |        0 |       220 | 95.45 |
| Slice LUTs                   |  21800 |     0 |        0 |     53200 | 40.98 |
| Block RAM Tile               |     62 |     0 |        0 |       140 | 44.28 |
"""


def test_check_util_within_budget(tmp_path, capsys):
    p = tmp_path / "util.rpt"
    p.write_text(UTIL_REPORT)
    rc = check_utilization.main([str(p)])
    assert rc == 0


def test_check_util_over_budget(tmp_path):
    p = tmp_path / "util.rpt"
    p.write_text(UTIL_REPORT_OVER)
    rc = check_utilization.main([str(p)])
    assert rc == 1


def test_check_util_json(tmp_path, capsys):
    p = tmp_path / "util.rpt"
    p.write_text(UTIL_REPORT)
    check_utilization.main([str(p), "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert "dsp" in payload["bins"]
    assert payload["bins"]["dsp"]["pct"] == pytest.approx(58.18, rel=1e-3)


# ---------------------------------------------------------------------------
# dispatch_risk_issue
# ---------------------------------------------------------------------------

def test_dispatch_classifies_r1_timing(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "timing.rpt").write_text(VIVADO_TIMING_FAIL)
    out = tmp_path / "classified.json"
    rc = dispatch_risk_issue.main([
        "--workflow-run-id", "1234",
        "--workflow-name", "HLS Smoke",
        "--logs-dir", str(logs),
        "--dry-run-output", str(out),
    ])
    assert rc == 0
    classified = json.loads(out.read_text(encoding="utf-8"))["classified"]
    assert classified["id"] == "R1"


def test_dispatch_classifies_r4_quant(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "eval.log").write_text(
        "eval_quant_map: mAP delta 2.18 (threshold 1.0) -- FAIL\n"
    )
    out = tmp_path / "c.json"
    rc = dispatch_risk_issue.main([
        "--workflow-run-id", "999",
        "--workflow-name", "NumPy Bit-Exact Regression",
        "--logs-dir", str(logs),
        "--dry-run-output", str(out),
    ])
    assert rc == 0
    classified = json.loads(out.read_text(encoding="utf-8"))["classified"]
    assert classified["id"] == "R4"


def test_dispatch_falls_back_to_default(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "weird.log").write_text("something nobody pattern-matches\n")
    out = tmp_path / "c.json"
    rc = dispatch_risk_issue.main([
        "--workflow-run-id", "5",
        "--workflow-name", "Custom",
        "--logs-dir", str(logs),
        "--dry-run-output", str(out),
    ])
    assert rc == 0
    classified = json.loads(out.read_text(encoding="utf-8"))["classified"]
    assert classified["id"] == "default"
