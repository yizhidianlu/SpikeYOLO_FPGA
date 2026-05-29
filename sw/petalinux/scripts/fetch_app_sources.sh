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

# Device-tree: pull in the C2-generated UIO overlay so the C1 system-user.dtsi
# can /include/ "uio_config.dts" at dtc preprocessing time.  Source lives in
# sw/driver/ (Contract 4 ownership); copied into the device-tree recipe's
# files/ subdir where the bbappend's FILESEXTRAPATHS picks it up
# (Cloud Claude URGENT_ASK_9 376e2c5, 2026-05-28).
DT_RECIPE="${ROOT}/sw/petalinux/project-spec/meta-user/recipes-bsp/device-tree/files"
mkdir -p "${DT_RECIPE}"
if [ -f "${ROOT}/sw/driver/uio_config.dts" ]; then
    cp "${ROOT}/sw/driver/uio_config.dts" "${DT_RECIPE}/uio_config.dts"
    echo "[fetch_app_sources] DT overlay: sw/driver/uio_config.dts -> ${DT_RECIPE}/uio_config.dts"
else
    echo "[fetch_app_sources] WARN: sw/driver/uio_config.dts missing — system-user.dtsi /include/ will fail at dtc" >&2
fi

# FPGA bitstream: the exported XSA has no embedded .bit, so petalinux's
# FPGA_MANAGER flow can't auto-extract one.  Stage the standalone Git-LFS
# bitstream into the fpga-firmware recipe's files/; that recipe converts it
# to system.bit.bin and ships it to /lib/firmware + programs PL at boot
# (Cloud Claude uart_diag 869000a Bug A/B, 2026-05-29).
FPGA_RECIPE="${ROOT}/sw/petalinux/project-spec/meta-user/recipes-bsp/fpga-firmware/files"
mkdir -p "${FPGA_RECIPE}"
if [ -f "${ROOT}/hw/vivado/out/system.bit" ] \
        && [ "$(stat -c%s "${ROOT}/hw/vivado/out/system.bit" 2>/dev/null || echo 0)" -gt 100000 ]; then
    cp "${ROOT}/hw/vivado/out/system.bit" "${FPGA_RECIPE}/system.bit"
    echo "[fetch_app_sources] bitstream: hw/vivado/out/system.bit -> ${FPGA_RECIPE}/system.bit"
else
    echo "[fetch_app_sources] WARN: hw/vivado/out/system.bit missing or is an LFS pointer (run 'git lfs pull') — PL will not be programmed at boot" >&2
fi

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
