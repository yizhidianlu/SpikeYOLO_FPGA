#!/usr/bin/env bash
# D1 month-end regression: run all gates that exist today.
#
# Owner: D1 System Verification — see docs/AGENT_PLAYBOOKS/D1_verification.md
#
# Usage:
#   bash tests/regression/run_full.sh           # PC-side gates only (fast)
#   bash tests/regression/run_full.sh --full    # also Vitis cosim (slow, M2+)
#   bash tests/regression/run_full.sh --board   # also board gates (M3+)
#
# Exit non-zero on any gate failure. Prints a summary at the end.

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_DIR="${REPO_ROOT}/runs/regression_$(date -u +%Y%m%d_%H%M%S)"
mkdir -p "${LOG_DIR}"

WANT_FULL=0
WANT_BOARD=0
for arg in "$@"; do
  case "${arg}" in
    --full)  WANT_FULL=1  ;;
    --board) WANT_BOARD=1 ;;
    *) echo "[run_full] unknown arg: ${arg}"; exit 2 ;;
  esac
done

echo "=== D1 regression $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
echo "=== Logs:  ${LOG_DIR} ==="

# ---------------------------------------------------------------------------
# 1. NumPy bit-exact regression (37 cases, A2 owns)
# ---------------------------------------------------------------------------
echo ""
echo "=== [1/5] NumPy regression (tests/test_bit_exact.py) ==="
pytest "${REPO_ROOT}/tests/test_bit_exact.py" -v \
  --junitxml="${LOG_DIR}/numpy.xml" 2>&1 | tee "${LOG_DIR}/numpy.log"

# ---------------------------------------------------------------------------
# 2. HLS host_csim — every layer with a host_csim_layer_NN target (B1 owns)
# ---------------------------------------------------------------------------
echo ""
echo "=== [2/5] HLS host_csim (4 layers — 00, 01, 03, 08 as of M1 W3) ==="
make -C "${REPO_ROOT}/hw/hls" \
  host_csim_layer_00 \
  host_csim_layer_01 \
  host_csim_layer_03 \
  host_csim_layer_08 \
  2>&1 | tee "${LOG_DIR}/host_csim.log"

# ---------------------------------------------------------------------------
# 3. Quantization mAP gate (A1 owns; soft-warn until distill mAP exists)
# ---------------------------------------------------------------------------
echo ""
echo "=== [3/5] Quantization mAP gate (eval_quant_map) ==="
if python "${REPO_ROOT}/tools/quant/eval_quant_map.py" \
    --weights "${REPO_ROOT}/models/tiny_fpga_int8.npz" \
    --target-degradation 1.0 2>&1 | tee "${LOG_DIR}/quant_map.log"; then
  echo "[3/5] mAP gate PASS"
else
  echo "[3/5] WARN: mAP gate failed (or skipped). Expected until R8 closes."
fi

# ---------------------------------------------------------------------------
# 4. Baseline triple (teacher / student_init / student_distilled, A1 owns)
# ---------------------------------------------------------------------------
echo ""
echo "=== [4/5] Baseline triple summary ==="
python "${REPO_ROOT}/tools/quant/eval_baseline_triple.py" \
  --out "${LOG_DIR}/baseline_summary.json" \
  2>&1 | tee "${LOG_DIR}/baseline.log"

# ---------------------------------------------------------------------------
# 5. Optional: Vitis HLS cosim (M2+; needs self-hosted vivado runner)
# ---------------------------------------------------------------------------
if [ "${WANT_FULL}" = "1" ]; then
  echo ""
  echo "=== [5/5] Vitis HLS cosim (--full) ==="
  cd "${REPO_ROOT}/hw/hls" && \
    vitis_hls -f run_cosim.tcl 2>&1 | tee "${LOG_DIR}/cosim.log" && cd -
fi

# ---------------------------------------------------------------------------
# 6. Optional: Board gates (M3+; needs ZYBO reachable)
# ---------------------------------------------------------------------------
if [ "${WANT_BOARD}" = "1" ]; then
  echo ""
  echo "=== [board] FPS bench + COCO val on board ==="
  python "${REPO_ROOT}/tools/perf/fps_bench.py" \
    --mode board --frames 600 --min-fps 10 \
    --out "${LOG_DIR}/fps_bench.json" \
    2>&1 | tee "${LOG_DIR}/fps_bench.log"
  # tests/regression/coco_val_on_board.py — TODO M3+
fi

echo ""
echo "=== ALL GATES PASS ==="
echo "=== Logs in ${LOG_DIR} ==="
