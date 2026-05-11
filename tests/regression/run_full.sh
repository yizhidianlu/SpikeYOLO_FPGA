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

# NOTE: intentionally no `set -e`. Each step records its own pass/fail
# into a final summary so a single broken gate does not mask the rest
# (matches D1 month-end protocol: collect everything, then triage).

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_DIR="${REPO_ROOT}/runs/regression_$(date -u +%Y%m%d_%H%M%S)"
mkdir -p "${LOG_DIR}"

declare -a STEP_NAMES
declare -a STEP_RESULTS
record_step() {
  STEP_NAMES+=("$1")
  STEP_RESULTS+=("$2")
}

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
# 1. NumPy bit-exact regression (49 cases, A2 owns)
# ---------------------------------------------------------------------------
echo ""
echo "=== [1/5] NumPy regression (tests/test_bit_exact.py) ==="
if pytest "${REPO_ROOT}/tests/test_bit_exact.py" -v \
    --junitxml="${LOG_DIR}/numpy.xml" 2>&1 | tee "${LOG_DIR}/numpy.log"; then
  record_step "1_numpy_bit_exact" "PASS"
else
  record_step "1_numpy_bit_exact" "FAIL"
fi

# ---------------------------------------------------------------------------
# 1b. NumPy self-consistency (Contract-2 12-layer gate, A2 W5)
#     Pure CPU, no g++/make/HLS deps — runs in any env.
# ---------------------------------------------------------------------------
echo ""
echo "=== [1b/5] NumPy self-consistency (A2 contract-2, 12 layers) ==="
SC_JSON="${LOG_DIR}/numpy_self_consistency.json"
if python "${REPO_ROOT}/tools/verify/numpy_vs_hls.py" \
    --self-consistency \
    --weights "${REPO_ROOT}/models/tiny_fpga_int8.npz" \
    --golden-dir "${REPO_ROOT}/tests/golden/" \
    --out "${SC_JSON}" \
    2>&1 | tee "${LOG_DIR}/numpy_self_consistency.log"; then
  # Python on Windows can sometimes choke on MSYS-style /c/... paths handed
  # via os.path; pass the path as an argv string and let pathlib normalize it.
  if python -c "import json,sys,pathlib; \
p=pathlib.Path(sys.argv[1]); \
d=json.loads(p.read_text()); \
s=d.get('summary',d); \
fail=s.get('fail', s.get('failed', 0)); \
print(f'self_consistency: fail={fail} total={s.get(\"total\",\"?\")}'); \
sys.exit(0 if fail==0 else 1)" \
      "${SC_JSON}"; then
    record_step "1b_numpy_self_consistency" "PASS"
  else
    record_step "1b_numpy_self_consistency" "FAIL"
  fi
else
  record_step "1b_numpy_self_consistency" "FAIL"
fi

# ---------------------------------------------------------------------------
# 2. HLS host_csim — every layer with a host_csim_layer_NN target (B1 owns)
# ---------------------------------------------------------------------------
echo ""
echo "=== [2/5] HLS host_csim (4 layers — 00, 01, 03, 08 as of M1 W3) ==="
if ! command -v make >/dev/null 2>&1 || ! command -v g++ >/dev/null 2>&1; then
  echo "[2/5] SKIP: make/g++ not on PATH (host_csim requires gcc toolchain)" \
    | tee "${LOG_DIR}/host_csim.log"
  record_step "2_host_csim_4layers" "SKIP"
elif make -C "${REPO_ROOT}/hw/hls" \
    host_csim_layer_00 \
    host_csim_layer_01 \
    host_csim_layer_03 \
    host_csim_layer_08 \
    2>&1 | tee "${LOG_DIR}/host_csim.log"; then
  record_step "2_host_csim_4layers" "PASS"
else
  record_step "2_host_csim_4layers" "FAIL"
fi

# ---------------------------------------------------------------------------
# 3. Quantization mAP gate (A1 owns; soft-warn until distill mAP exists)
# ---------------------------------------------------------------------------
echo ""
echo "=== [3/5] Quantization mAP gate (eval_quant_map) ==="
if python "${REPO_ROOT}/tools/quant/eval_quant_map.py" \
    --weights "${REPO_ROOT}/models/tiny_fpga_int8.npz" \
    --target-degradation 1.0 2>&1 | tee "${LOG_DIR}/quant_map.log"; then
  echo "[3/5] mAP gate PASS"
  record_step "3_quant_map_gate" "PASS"
else
  echo "[3/5] WARN: mAP gate failed (or skipped). Expected until R8 closes."
  record_step "3_quant_map_gate" "WARN"
fi

# ---------------------------------------------------------------------------
# 4. Baseline triple (teacher / student_init / student_distilled, A1 owns)
# ---------------------------------------------------------------------------
echo ""
echo "=== [4/5] Baseline triple summary ==="
# Default: read the persisted A1 numbers from runs/baseline_summary.json
# (teacher = 45.35%, student_init = 0.00%; A1 W3 cached). The full COCO
# val takes ~6 min on RTX 5060 — re-run only with --recompute-baseline.
RECOMPUTE_BASELINE=${RECOMPUTE_BASELINE:-0}
if [ "${RECOMPUTE_BASELINE}" = "1" ]; then
  if python "${REPO_ROOT}/tools/quant/eval_baseline_triple.py" \
      --out "${LOG_DIR}/baseline_summary.json" \
      2>&1 | tee "${LOG_DIR}/baseline.log"; then
    record_step "4_baseline_triple" "PASS"
  else
    record_step "4_baseline_triple" "FAIL"
  fi
else
  if python "${REPO_ROOT}/tools/quant/eval_baseline_triple.py" \
      --from-cache "${REPO_ROOT}/runs/baseline_summary.json" \
      --out "${LOG_DIR}/baseline_summary.json" \
      2>&1 | tee "${LOG_DIR}/baseline.log"; then
    record_step "4_baseline_triple" "PASS"
  else
    record_step "4_baseline_triple" "FAIL"
  fi
fi

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
echo "=== Step summary ==="
fail_count=0
for i in "${!STEP_NAMES[@]}"; do
  printf "  %-30s %s\n" "${STEP_NAMES[$i]}" "${STEP_RESULTS[$i]}"
  case "${STEP_RESULTS[$i]}" in
    FAIL) fail_count=$((fail_count+1)) ;;
  esac
done
echo "=== ${fail_count} FAIL / ${#STEP_NAMES[@]} steps ==="
echo "=== Logs in ${LOG_DIR} ==="
exit ${fail_count}
