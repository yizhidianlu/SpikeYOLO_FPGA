#!/usr/bin/env python3
"""
tools/ci/run_host_csim.py — cross-platform launcher for HLS host_csim binaries.

The Makefile in hw/hls calls this so the same recipe works on POSIX shells and
Windows cmd / PowerShell. We set SA_GOLDEN_DIR / SA_WEIGHT_DIR (and any extra
NAME=VAL passed via --env) before invoking the testbench from a chosen cwd.

The binary's stdout / stderr are streamed verbatim. Exit code is forwarded.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", required=True,
                    help="absolute path to the testbench executable")
    ap.add_argument("--cwd", required=True,
                    help="working directory to chdir into before running")
    ap.add_argument("--golden-dir", required=True,
                    help="value for SA_GOLDEN_DIR (relative to cwd)")
    ap.add_argument("--weight-dir", required=True,
                    help="value for SA_WEIGHT_DIR (relative to cwd)")
    ap.add_argument("--env", action="append", default=[],
                    metavar="NAME=VAL",
                    help="extra env var to inject (repeatable)")
    args = ap.parse_args()

    env = os.environ.copy()
    env["SA_GOLDEN_DIR"] = args.golden_dir
    env["SA_WEIGHT_DIR"] = args.weight_dir
    for kv in args.env:
        if "=" not in kv:
            print(f"[run_host_csim] bad --env '{kv}' (expected NAME=VAL)",
                  file=sys.stderr)
            return 2
        k, v = kv.split("=", 1)
        env[k] = v

    bin_path = args.binary
    if not os.path.isfile(bin_path):
        # On Windows mingw32-make leaves off the .exe suffix in the rule
        # variable, but the linker still produces foo.exe. Try that fallback.
        if os.path.isfile(bin_path + ".exe"):
            bin_path = bin_path + ".exe"
        else:
            print(f"[run_host_csim] binary not found: {args.binary}",
                  file=sys.stderr)
            return 2

    rc = subprocess.run(
        [bin_path],
        cwd=args.cwd,
        env=env,
    ).returncode
    return rc


if __name__ == "__main__":
    sys.exit(main())
