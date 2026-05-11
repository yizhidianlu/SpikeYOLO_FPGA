"""Parse a Vivado / Vitis HLS utilization report and gate against the
Z-7020 resource budget (Contract 3 resource_budget block).

Budget defaults (override via --budget=path/to/yaml):
    dsp_pct:   70
    lut_pct:   60
    bram_pct:  75
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List


_DEFAULT_BUDGET = {"dsp_pct": 70.0, "lut_pct": 60.0, "bram_pct": 75.0}

# Vivado report_utilization rows look like:
#   | DSP                          |    128 |     0 |        0 |       220 | 58.18 |
#   | Slice LUTs                   |  21800 |     0 |        0 |     53200 | 40.98 |
#   | Block RAM Tile               |     62 |     0 |        0 |       140 | 44.28 |
_ROW_PAT = re.compile(
    r"\|\s*(?P<resource>[\w \-]+?)\s*\|"
    r"\s*(?P<used>\d+)\s*\|"
    r"\s*\d+\s*\|"           # available
    r"\s*\d+\s*\|"           # function-bias
    r"\s*(?P<total>\d+)\s*\|"
    r"\s*(?P<pct>\d+\.\d+)\s*\|"
)

# Resource names we care about (case-insensitive prefix match)
_RESOURCE_BINS = {
    "dsp":  ["DSP"],
    "lut":  ["Slice LUTs", "CLB LUTs", "LUT as Logic"],
    "bram": ["Block RAM Tile", "BRAM Tile", "Block RAM"],
}


def _load_budget(path: Path | None) -> Dict[str, float]:
    if path is None:
        return dict(_DEFAULT_BUDGET)
    import yaml
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    out = dict(_DEFAULT_BUDGET)
    out.update({k: float(v) for k, v in (data or {}).items()})
    return out


def parse(report_path: Path) -> Dict[str, Dict]:
    """Return ``{bin: {used, total, pct}}`` for DSP / LUT / BRAM."""
    text = report_path.read_text(encoding="utf-8", errors="replace")
    bins: Dict[str, Dict] = {}
    for m in _ROW_PAT.finditer(text):
        name = m.group("resource").strip()
        used = int(m.group("used"))
        total = int(m.group("total"))
        pct = float(m.group("pct"))
        for bin_key, prefixes in _RESOURCE_BINS.items():
            if any(name.lower().startswith(p.lower()) for p in prefixes):
                # Keep the highest pct seen (e.g. multiple LUT subtypes)
                if bin_key not in bins or bins[bin_key]["pct"] < pct:
                    bins[bin_key] = {"used": used, "total": total, "pct": pct,
                                     "source_row": name}
    return bins


def main(argv: list | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("report", help="Vivado utilization.rpt or HLS synth report")
    p.add_argument("--budget", type=Path, default=None,
                   help="YAML overriding default {dsp,lut,bram}_pct budgets")
    p.add_argument("--strict", action="store_true",
                   help="fail if any required resource bin is missing from the report")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    budget = _load_budget(args.budget)
    bins = parse(Path(args.report))

    rc = 0
    missing: List[str] = []
    over: List[str] = []
    for bin_key, budget_pct in (("dsp", budget["dsp_pct"]),
                                ("lut", budget["lut_pct"]),
                                ("bram", budget["bram_pct"])):
        if bin_key not in bins:
            missing.append(bin_key)
            continue
        if bins[bin_key]["pct"] > budget_pct:
            over.append(bin_key)

    if args.json:
        print(json.dumps({"bins": bins, "budget": budget,
                          "missing": missing, "over": over}, indent=2))
    else:
        for k, v in bins.items():
            print(f"  {k.upper():4s}  {v['used']:6d} / {v['total']:6d}  "
                  f"= {v['pct']:5.2f}%  (budget {budget[k + '_pct']:.0f}%)")
        if missing:
            print(f"[check_util] missing rows in report: {missing}", file=sys.stderr)
            if args.strict:
                rc = 2
        if over:
            print(f"[check_util] FAIL — over budget: {over}", file=sys.stderr)
            rc = 1
        if rc == 0:
            print("[check_util] OK  all resources within budget")
    return rc


if __name__ == "__main__":
    sys.exit(main())
