#!/usr/bin/env bash
# tools/ci/run_coco100_when_available.sh
#
# Auto-detect datasets/coco/val2017/. If present, generate the full 100-image
# Contract 6 baseline (tests/golden/coco_val100.json). If absent, leave the
# committed 5-image smoke (tests/golden/coco_val100_smoke.json) untouched and
# exit 0 with an INFO message — D1's monthly mAP report can then decide
# whether to escalate.
#
# Usage:
#   bash tools/ci/run_coco100_when_available.sh                  # default 100
#   bash tools/ci/run_coco100_when_available.sh --num 50         # override
#   COCO_VAL_DIR=/data/coco/val2017 bash ...                     # alt path
#
# Owner: A2  (do not move without updating Playbook A2_bit_exact_reference.md)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

VAL_DIR="${COCO_VAL_DIR:-datasets/coco/val2017}"
WEIGHTS="${COCO_WEIGHTS:-models/tiny_fpga_int8.npz}"
OUT="${COCO_OUT:-tests/golden/coco_val100.json}"
NUM="${COCO_NUM:-100}"
PER_CLASS_MIN="${COCO_PER_CLASS_MIN:-1}"

# Allow CLI overrides (forwarded verbatim so callers can still tweak --num etc.)
EXTRA_ARGS=("$@")

if [[ ! -d "$VAL_DIR" ]]; then
    echo "[coco100] $VAL_DIR not present — keeping smoke fixture"
    echo "[coco100] (D1: this is non-fatal; rerun once COCO val2017 is staged)"
    if [[ ! -f tests/golden/coco_val100_smoke.json ]]; then
        echo "[coco100] WARN: no smoke fixture either — generating one now"
        python tools/verify/gen_coco_val100.py \
            --num 5 \
            --weights "$WEIGHTS" \
            --output tests/golden/coco_val100_smoke.json \
            --per-class-min 1
    fi
    exit 0
fi

if [[ ! -f "$WEIGHTS" ]]; then
    echo "[coco100] ERROR: weights $WEIGHTS missing — cannot run real coco100"
    exit 2
fi

echo "[coco100] running real $NUM-image generator -> $OUT"
python tools/verify/gen_coco_val100.py \
    --val-dir "$VAL_DIR" \
    --weights "$WEIGHTS" \
    --num "$NUM" \
    --per-class-min "$PER_CLASS_MIN" \
    --output "$OUT" \
    "${EXTRA_ARGS[@]}"
echo "[coco100] OK -> $OUT"
