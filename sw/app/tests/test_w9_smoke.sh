#!/bin/bash
# sw/app/tests/test_w9_smoke.sh — board-side gate for the W9 PTQ INT8 firmware.
#
# Pre-conditions (set up by D1 board_nightly workflow or manual bring-up):
#   1. ZYBO Z7-20 booted with the M2-W1 bitstream loaded
#      ($(fpgautil -b /lib/firmware/system.bit) or u-boot autoload)
#   2. /lib/firmware/tiny_fpga_int8.bin present (W9 PTQ output)
#   3. golden hash sourced from $W9_GOLDEN_HASH env var or
#      ${REPO_ROOT}/tests/golden/w9_smoke.hash (8 hex digits, no 0x, lowercase)
#   4. /opt/spike_accel_w9_smoke installed
#
# Exit:
#   0   smoke passed
#   non-zero   first failing step; check stderr above
#
# Usage on board:
#     /opt/run_on_board.sh --w9-smoke
# or directly:
#     W9_GOLDEN_HASH=$(cat /lib/firmware/w9_smoke.hash) \
#         /opt/spike_accel_w9_smoke --golden-hash "$W9_GOLDEN_HASH"

set -euo pipefail

BIN=${SA_W9_SMOKE_BIN:-/opt/spike_accel_w9_smoke}
WEIGHTS=${SA_W9_WEIGHTS:-/lib/firmware/tiny_fpga_int8.bin}
OUTPUT=${SA_W9_OUTPUT:-/tmp/feat_out_int8.bin}
HASH=${W9_GOLDEN_HASH:-}

if [[ -z "$HASH" && -f /lib/firmware/w9_smoke.hash ]]; then
    HASH=$(cat /lib/firmware/w9_smoke.hash)
fi

if [[ ! -x "$BIN" ]]; then
    echo "[w9-smoke-test] binary not found at $BIN" >&2
    exit 2
fi
if [[ ! -f "$WEIGHTS" ]]; then
    echo "[w9-smoke-test] weights not found at $WEIGHTS" >&2
    exit 2
fi

ARGS=(--weights "$WEIGHTS" --output "$OUTPUT" --repeat 3)
if [[ -n "$HASH" ]]; then
    ARGS+=(--golden-hash "$HASH")
    echo "[w9-smoke-test] golden hash = $HASH"
else
    echo "[w9-smoke-test] no golden hash (baseline-only run)"
fi

echo "[w9-smoke-test] $BIN ${ARGS[*]}"
"$BIN" "${ARGS[@]}"
echo "[w9-smoke-test] PASS"
