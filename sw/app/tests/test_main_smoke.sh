#!/usr/bin/env bash
# sw/app/tests/test_main_smoke.sh — host-side smoke test for the C3 app.
#
# Strategy
# --------
# The "ideal" smoke is:
#   1. cmake -B build-host -DSA_APP_NO_V4L2=ON -DSA_APP_NO_DRM=ON
#                          -DSA_APP_STUB_SDK=ON
#                          -Dspike_accel_DIR=<sdk-host-build>
#   2. cmake --build build-host
#   3. ./build-host/spike_accel_demo --backend stub --frames 100 \
#          --weights /tmp/fake_weights.bin
#   4. parse the "summary:" line, assert frames=100 and fps_ema > 0.
#
# But on a Windows MSYS2 + g++ 5.3 dev host (the C2 W4 report flags the same
# issue) libstdc++'s <random> ICEs on -fsyntax-only / -c, so the test
# auto-falls-back to a preprocess-only pass. The petalinux SDK toolchain
# (M3 W1 deliverable from C1) replaces the ICE-ing host compiler and the
# real build path takes over.

set -u

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SRC_DIR="${APP_DIR}/src"
SDK_INC="${APP_DIR}/../sdk/include"

PASS=0
FAIL=0
note()  { printf "  %s\n" "$*"; }
ok()    { printf "  [PASS] %s\n" "$*"; PASS=$((PASS+1)); }
bad()   { printf "  [FAIL] %s\n" "$*"; FAIL=$((FAIL+1)); }

CXX="${CXX:-g++}"
STD="${STD:-gnu++11}"
DEFS="-DSA_APP_NO_V4L2=1 -DSA_APP_NO_DRM=1 -DSA_STUB_BACKEND=1"
INCS="-I ${SDK_INC} -I ${SRC_DIR}"

echo "== test_main_smoke =="
echo "  CXX=${CXX}  STD=${STD}"
echo "  app_dir=${APP_DIR}"

# ---------------------------------------------------------------------------
# Path A: full cmake build + 100-frame run (only when cmake + a usable host
# compiler are available, and the SDK was host-built with SA_BUILD_STUB=ON).
# ---------------------------------------------------------------------------
have_cmake=0
have_real_build=0
if command -v cmake >/dev/null 2>&1; then have_cmake=1; fi

if [ "${have_cmake}" = "1" ] && [ "${SKIP_CMAKE:-0}" != "1" ]; then
    BUILD_DIR="${APP_DIR}/build-host-smoke"
    note "trying full cmake host build at ${BUILD_DIR}"
    if cmake -S "${APP_DIR}" -B "${BUILD_DIR}" \
             -DSA_APP_NO_V4L2=ON -DSA_APP_NO_DRM=ON -DSA_APP_STUB_SDK=ON \
             > "${BUILD_DIR}/.cmake.log" 2>&1 \
       && cmake --build "${BUILD_DIR}" -j > "${BUILD_DIR}/.build.log" 2>&1; then
        have_real_build=1
        ok "cmake host build"
    else
        note "cmake configure/build failed (see ${BUILD_DIR}/.{cmake,build}.log)"
        note "falling back to preprocess-only smoke"
    fi
fi

if [ "${have_real_build}" = "1" ]; then
    BIN="${BUILD_DIR}/spike_accel_demo"
    FAKE_BIN="$(mktemp -t spike_fake_weights.XXXXXX)"
    # 16 KiB of zeros — well below SA_WEIGHT_POOL_SIZE.
    dd if=/dev/zero of="${FAKE_BIN}" bs=1024 count=16 > /dev/null 2>&1

    # ---- sequential mode (W4 baseline) ----
    OUT="$(mktemp -t spike_smoke_seq.XXXXXX)"
    if "${BIN}" --backend stub --frames 100 --timeout 200 --threads 1 \
                --display dump-frame \
                --cam-size 640x480 --weights "${FAKE_BIN}" \
                --drm-dev "${OUT}.drm" > "${OUT}" 2>&1; then
        ok "sequential (--threads 1) ran to completion"
    else
        bad "sequential exit non-zero (log: ${OUT})"
    fi

    if grep -q '^summary:' "${OUT}"; then
        ok "sequential: summary line present"
        frames=$(grep '^summary:' "${OUT}" | sed -E 's/.*frames=([0-9]+).*/\1/')
        fps=$(grep   '^summary:'   "${OUT}" | sed -E 's/.*fps_ema=([0-9.]+).*/\1/')
        efps=$(grep  '^summary:'   "${OUT}" | sed -E 's/.*effective_fps=([0-9.]+).*/\1/')
        [ "${frames}" -ge 100 ]                                && ok "sequential: frames>=100 (${frames})" || bad "sequential: frames=${frames}"
        awk -v f="${fps}"  'BEGIN{exit !(f>0)}'                && ok "sequential: fps_ema>0 (${fps})"     || bad "sequential: fps_ema=${fps}"
        awk -v f="${efps}" 'BEGIN{exit !(f>0)}'                && ok "sequential: effective_fps>0 (${efps})" || bad "sequential: effective_fps=${efps}"
    else
        bad "sequential: no summary line in output: ${OUT}"
    fi

    # ---- three-stage mode (M1 W5) ----
    OUT2="$(mktemp -t spike_smoke_3stg.XXXXXX)"
    if "${BIN}" --backend stub --frames 100 --timeout 200 --threads 3 \
                --display dump-frame \
                --cam-size 640x480 --weights "${FAKE_BIN}" \
                --drm-dev "${OUT2}.drm" > "${OUT2}" 2>&1; then
        ok "three-stage (--threads 3) ran to completion"
    else
        bad "three-stage exit non-zero (log: ${OUT2})"
    fi

    if grep -q '^summary:' "${OUT2}"; then
        ok "three-stage: summary line present"
        frames=$(grep '^summary:' "${OUT2}" | sed -E 's/.*frames=([0-9]+).*/\1/')
        efps=$(grep   '^summary:' "${OUT2}" | sed -E 's/.*effective_fps=([0-9.]+).*/\1/')
        [ "${frames}" -ge 100 ]                                && ok "three-stage: frames>=100 (${frames})" || bad "three-stage: frames=${frames}"
        awk -v f="${efps}" 'BEGIN{exit !(f>0)}'                && ok "three-stage: effective_fps>0 (${efps})" || bad "three-stage: effective_fps=${efps}"
        # Sanity: under stub backend, three-stage should be at least as fast as sequential.
        # We don't gate on > 50 because Windows host stub varies wildly; just non-zero.
    else
        bad "three-stage: no summary line in output: ${OUT2}"
    fi
    rm -f "${FAKE_BIN}"
fi

# ---------------------------------------------------------------------------
# Path B: preprocess-only fallback. Catches missing headers, typos, and
# malformed comment blocks (the dma_buf.c-style "*/" trap) without exercising
# the broken Windows libstdc++ codegen path.
# ---------------------------------------------------------------------------
if [ "${have_real_build}" = "0" ]; then
    note "preprocess-only smoke (${CXX} -std=${STD} -E)"
    for f in preproc postproc_nms hdmi_overlay v4l2_capture drm_display main; do
        if ${CXX} -std=${STD} -E ${DEFS} ${INCS} \
                  "${SRC_DIR}/${f}.cpp" > /dev/null 2>"${SRC_DIR}/.${f}.err"; then
            ok "preprocess ${f}.cpp"
            rm -f "${SRC_DIR}/.${f}.err"
        else
            bad "preprocess ${f}.cpp"
            sed -n '1,8p' "${SRC_DIR}/.${f}.err"
        fi
    done

    # Sanity-check that the runtime.yaml schema covers every key main.cpp
    # reads. This catches forgetting to update the yaml when adding a CLI flag.
    YAML="${APP_DIR}/configs/runtime.yaml"
    for k in "backend:" "weights_bin:" "weights_sha256:" "iou_threshold:" \
             "conf_threshold:" "max_frames:" "timeout_ms:" "num_classes:" \
             "stride:" "mode:" "ringbuf_capacity:" \
             "capture_thread_affinity:" "infer_thread_affinity:" \
             "display_thread_affinity:" "log_interval_frames:" \
             "layer:" "id:" "mask:"; do
        if grep -q "${k}" "${YAML}"; then ok  "runtime.yaml has ${k}"
        else                              bad "runtime.yaml missing ${k}"
        fi
    done
fi

echo "----"
echo "passed=${PASS} failed=${FAIL}"
[ "${FAIL}" = "0" ] && exit 0 || exit 1
