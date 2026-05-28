#!/bin/bash
# sw/petalinux/scripts/fetch_app_sources.sh — copy SDK + app + weights
# into the spike-accel-app recipe's files/ before petalinux-build.
#
# This is the bridge between the in-repo C2/C3 source tree and Yocto's
# fetcher, kept as a separate script so the Petalinux project can be cleaned
# without losing user customisations.

set -eo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
RECIPE="${ROOT}/sw/petalinux/project-spec/meta-user/recipes-apps/spike-accel-app/files"

mkdir -p "${RECIPE}/sdk"   "${RECIPE}/app"   "${RECIPE}/firmware"
rsync -a --delete "${ROOT}/sw/sdk/"  "${RECIPE}/sdk/"
rsync -a --delete "${ROOT}/sw/app/"  "${RECIPE}/app/"

# Pick the source INT8 weight set baked into the image.
#   SA_WEIGHTS_BIN env: override source filename (under models/).
#   Default: PBT (person/bus/train) ep20 — Path B demo-grade model.
# The board-side filename stays tiny_fpga_int8.bin so the SDK / driver
# / device tree don't need to know which variant is loaded.
WEIGHTS_SRC="${SA_WEIGHTS_BIN:-tiny_fpga_int8_pbt.bin}"
if [ -f "${ROOT}/models/${WEIGHTS_SRC}" ]; then
    cp "${ROOT}/models/${WEIGHTS_SRC}" "${RECIPE}/firmware/tiny_fpga_int8.bin"
    echo "[fetch_app_sources] weights: models/${WEIGHTS_SRC} -> firmware/tiny_fpga_int8.bin"
elif [ -f "${ROOT}/models/tiny_fpga_int8.bin" ]; then
    cp "${ROOT}/models/tiny_fpga_int8.bin" "${RECIPE}/firmware/tiny_fpga_int8.bin"
    echo "[fetch_app_sources] weights: fallback legacy tiny_fpga_int8.bin (NOT demo-grade)" >&2
else
    echo "[fetch_app_sources] WARN: no weight .bin found in models/ — image will boot but inference returns SA_ERR_WEIGHT_LOAD" >&2
fi

cp "${ROOT}/sw/app/scripts/run_on_board.sh" "${RECIPE}/"
# CMakeLists at the top level wires sdk+app into a single project.
cat >"${RECIPE}/CMakeLists.txt" <<'EOF'
cmake_minimum_required(VERSION 3.18)
project(spike_accel_app_bundle LANGUAGES C CXX)
add_subdirectory(sdk)
add_subdirectory(app)
EOF
echo "[fetch_app_sources] OK — sources copied to ${RECIPE}"
