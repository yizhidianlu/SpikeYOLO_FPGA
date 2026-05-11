"""Parse a Vivado / Vitis HLS timing_summary.rpt and gate on WNS.

Used by both ``hls_smoke.yml`` (HLS reports) and ``board_nightly.yml``
(Vivado implementation reports).

Recognized formats:
  - Vitis HLS ``synthesis report`` (key: "Estimated", "Target")
  - Vivado ``report_timing_summary -file`` ASCII output (key: "WNS")
  - JSON (key: "wns_ns")  — emitted by ``--json`` mode of this script in M5
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional


_WNS_PATTERNS = [
    # Vivado: "| Worst Negative Slack (WNS)    |  0.123  ns |"
    ("vivado_wns",
     re.compile(r"Worst\s+Negative\s+Slack\s*\(WNS\)\s*\|\s*(-?\d+\.\d+)")),
    # Some Vivado dumps use a less decorated header:
    ("vivado_short",
     re.compile(r"^\s*WNS\s*[:=]\s*(-?\d+\.\d+)", re.MULTILINE)),
    # Vitis HLS data row: "|ap_clk  | 10.00 ns | 8.420 ns | 1.25 ns |"
    # Capture both target (group 1) and estimated (group 2).
    ("hls_clock_row",
     re.compile(
         r"\|\s*[a-zA-Z_]\w*\s*\|"           # clock name cell
         r"\s*(\d+\.\d+)\s*(?:ns)?\s*\|"         # target
         r"\s*(\d+\.\d+)\s*(?:ns)?\s*\|"         # estimated
     )),
]


def parse(report_path: Path) -> dict:
    text = report_path.read_text(encoding="utf-8", errors="replace")

    # JSON short-circuit
    if report_path.suffix.lower() == ".json":
        return json.loads(text)

    wns_ns: Optional[float] = None
    for name, pat in _WNS_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        if name == "hls_clock_row":
            target = float(m.group(1))
            estimated = float(m.group(2))
            wns_ns = target - estimated
        else:
            wns_ns = float(m.group(1))
        break

    if wns_ns is None:
        return {"ok": False, "reason": "could not parse WNS from report",
                "path": str(report_path)}
    return {"ok": True, "wns_ns": wns_ns, "path": str(report_path)}


def main(argv: list | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("report", help="timing_summary.rpt or HLS synth report")
    p.add_argument("--wns-min", type=float, default=0.0,
                   help="fail if WNS < this value (ns). Default 0.0 = closure.")
    p.add_argument("--json", action="store_true",
                   help="emit parse result as JSON to stdout (for downstream tooling)")
    args = p.parse_args(argv)

    result = parse(Path(args.report))
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if not result["ok"]:
            print(f"[check_timing] FAIL  {result.get('reason')}  ({result['path']})",
                  file=sys.stderr)
        else:
            tag = "OK" if result["wns_ns"] >= args.wns_min else "FAIL"
            print(f"[check_timing] {tag}  WNS = {result['wns_ns']:+.3f} ns  "
                  f"(threshold ≥ {args.wns_min:+.3f})")

    if not result["ok"]:
        return 2
    if result["wns_ns"] < args.wns_min:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
