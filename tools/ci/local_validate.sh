#!/usr/bin/env bash
# tools/ci/local_validate.sh
# ----------------------------------------------------------------------------
# Single-shot local self-check covering everything numpy_regress.yml +
# hls_smoke.yml exercise on GitHub Actions, minus the self-hosted runner
# bits. Run before pushing to fork/origin.
#
# Owner: D2 (CI/CD). Mirrors numpy_regress.yml step order so a green
# local run predicts a green PR.
# ----------------------------------------------------------------------------
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

echo "[1/6] CLI --help lint (lazy-import contract)"
python tools/quant/distill_from_teacher.py --help > /dev/null
python tools/verify/torch_vs_numpy.py        --help > /dev/null
python tools/verify/extract_golden.py        --help > /dev/null
python tools/verify/gen_coco_val100.py       --help > /dev/null

echo "[2/6] Regenerate golden tensors from A1 weights (Contract 2)"
python tools/verify/extract_golden.py \
    --npz models/tiny_fpga_int8.npz \
    --num-images 1 \
    --layers 0,1,2,3,4,5,6,7,8,9,10,11 \
    --output-dir tests/golden/

echo "[3/6] pytest test_bit_exact (A2 acceptance, 37 cases)"
pytest tests/test_bit_exact.py -v --tb=short

echo "[4/6] golden_index sanity (A2 contract-2 schema)"
python -c "import json,sys; \
idx=json.load(open('tests/golden/golden_index.json')); \
assert idx['layer_count']==12, f'layer_count={idx[\"layer_count\"]}!=12'; \
assert idx['weights_source']!='synthetic', 'still using synthetic weights'; \
print('OK', idx['weights_source'], idx.get('weights_sha256','')[:12])"

echo "[5/6] make host_csim_layer_00 (B1 contract-3)"
if ! command -v g++  > /dev/null 2>&1; then
    echo "SKIP: g++ not in PATH (Windows dev box without MinGW is fine)"
elif ! command -v make > /dev/null 2>&1; then
    echo "SKIP: make not in PATH (Windows dev box without GNU make is fine)"
elif [ ! -f hw/hls/Makefile ]; then
    echo "SKIP: hw/hls/Makefile not present (B1 still W3-pending?)"
else
    make -C hw/hls host_csim_layer_00
fi

echo "[6/6] all gates passed — safe to push to fork"
