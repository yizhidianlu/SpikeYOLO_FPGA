#!/usr/bin/env bash
# tools/ci/local_validate.sh
# ----------------------------------------------------------------------------
# Single-shot local self-check covering everything numpy_regress.yml +
# hls_smoke.yml exercise on GitHub Actions, minus the self-hosted runner
# bits. Run before pushing to fork/origin — a green local run predicts a
# green PR.
#
# Owner: D2 (CI/CD). Mirrors numpy_regress.yml step order.
#
# M1 W7: extended 6 → 9 steps to cover the A2/C2/D1 deliverables added
# late M1:
#   [7/9] A2 numpy_vs_hls --self-consistency (12 layer NumPy/NumPy)
#   [8/9] C2 SDK examples smoke (hello_open) — SKIP if not built
#   [9/9] D1 latency_breakdown simulate (headroom_pct > 0 gate)
# ----------------------------------------------------------------------------
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

echo "[1/9] CLI --help lint (lazy-import contract)"
python tools/quant/distill_from_teacher.py --help > /dev/null
python tools/verify/torch_vs_numpy.py        --help > /dev/null
python tools/verify/extract_golden.py        --help > /dev/null
python tools/verify/gen_coco_val100.py       --help > /dev/null

echo "[2/9] Regenerate golden tensors from A1 weights (Contract 2)"
python tools/verify/extract_golden.py \
    --npz models/tiny_fpga_int8.npz \
    --num-images 1 \
    --layers 0,1,2,3,4,5,6,7,8,9,10,11 \
    --output-dir tests/golden/

echo "[3/9] pytest test_bit_exact (A2 acceptance)"
pytest tests/test_bit_exact.py -v --tb=short

echo "[4/9] golden_index sanity (A2 contract-2 schema)"
python -c "import json,sys; \
idx=json.load(open('tests/golden/golden_index.json')); \
assert idx['layer_count']==12, f'layer_count={idx[\"layer_count\"]}!=12'; \
assert idx['weights_source']!='synthetic', 'still using synthetic weights'; \
print('OK', idx['weights_source'], idx.get('weights_sha256','')[:12])"

echo "[5/9] make host_csim_layer_00 (B1 contract-3)"
if ! command -v g++  > /dev/null 2>&1; then
    echo "  SKIP: g++ not in PATH (Windows dev box without MinGW is fine)"
elif ! command -v make > /dev/null 2>&1; then
    echo "  SKIP: make not in PATH (Windows dev box without GNU make is fine)"
elif [ ! -f hw/hls/Makefile ]; then
    echo "  SKIP: hw/hls/Makefile not present (B1 still W3-pending?)"
else
    make -C hw/hls host_csim_layer_00
fi

echo "[6/9] address-map + weight-pack (A2 contracts 1 & 4)"
pytest tests/test_address_map.py tests/test_weight_pack.py -v --tb=short

echo "[7/9] NumPy self-consistency 12/12 (A2 W5)"
SC_OUT="runs/local_validate_self_consistency.json"
mkdir -p runs
python tools/verify/numpy_vs_hls.py --self-consistency \
    --weights models/tiny_fpga_int8.npz \
    --golden-dir tests/golden/ \
    --out "$SC_OUT"
python -c "import json,sys; d=json.load(open('$SC_OUT')); \
s=d.get('summary',{}); \
assert s.get('fail',1)==0, f'self-consistency fails={s}'; \
print('  PASS', s.get('pass','?'), '/', s.get('total','?'))"

echo "[8/9] SDK examples smoke (C2 W6)"
if [ -x sw/sdk/examples/build/hello_open ]; then
    sw/sdk/examples/build/hello_open || echo "  hello_open exited non-zero (board absent OK in dev box)"
elif [ -x sw/sdk/examples/build/hello_open.exe ]; then
    sw/sdk/examples/build/hello_open.exe || echo "  hello_open exited non-zero (board absent OK in dev box)"
else
    echo "  SKIP: sw/sdk/examples/build/hello_open not built (cmake/make sw/sdk/examples)"
fi

echo "[9/9] latency_breakdown simulate (D1 W5)"
LB_OUT="runs/local_validate_latency_breakdown.json"
python tools/perf/latency_breakdown.py --mode simulate --out "$LB_OUT"
python -c "import json,sys; d=json.load(open('$LB_OUT')); \
h=d.get('headroom_pct'); \
assert h is not None and h > 0, f'headroom_pct={h} not >0 (latency exceeds 33 ms budget?)'; \
print('  PASS  headroom_pct=', h, 'fps_avg=', d.get('fps_avg'))"

echo "[ok] all 9 gates passed — safe to push to fork"
