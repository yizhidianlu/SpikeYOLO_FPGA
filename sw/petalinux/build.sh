#!/bin/bash
# sw/petalinux/build.sh — one-shot Petalinux 2023.2 image build for ZYBO Z7-20.
#
# Inputs:
#   ../../hw/vivado/out/system.xsa            (B2 hardware platform)
#   project-spec/                              (configs + recipes)
#
# Outputs:
#   spikeyolo_petalinux/images/linux/BOOT.BIN
#   spikeyolo_petalinux/images/linux/image.ub
#   spikeyolo_petalinux/images/linux/petalinux-sdimage.wic
#
# Usage:
#   source /opt/petalinux-v2023.2/settings.sh
#   ./build.sh             # full build
#   ./build.sh -fast       # skip image regeneration if recipes unchanged

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJ_DIR="${SCRIPT_DIR}/spikeyolo_petalinux"
XSA_PATH="${SCRIPT_DIR}/../../hw/vivado/out/system.xsa"
SPEC_DIR="${SCRIPT_DIR}/project-spec"

if [ ! -f "${XSA_PATH}" ]; then
    echo "[build.sh] ERROR: ${XSA_PATH} not found. Run hw/vivado/build_bitstream.tcl first." >&2
    exit 1
fi

# 1. Create the project on first run.
if [ ! -d "${PROJ_DIR}" ]; then
    cd "${SCRIPT_DIR}"
    petalinux-create -t project --template zynq -n "$(basename "${PROJ_DIR}")"
fi

# 2. Overlay our customisations into the freshly-generated project-spec/.
rsync -a --delete \
    --exclude .git \
    "${SPEC_DIR}/" "${PROJ_DIR}/project-spec/"

# 3. Pull in the latest .xsa.
cd "${PROJ_DIR}"
petalinux-config --get-hw-description="${XSA_PATH}" --silentconfig

# 4. Build rootfs + kernel + u-boot.
if [ "$1" != "-fast" ]; then
    petalinux-build
fi

# 5. Package BOOT.BIN + image.ub + SD card image.
petalinux-package boot --fsbl images/linux/zynq_fsbl.elf \
                       --u-boot --fpga "${XSA_PATH%.xsa}.bit" --force
petalinux-package wic --bootfiles "BOOT.BIN image.ub" \
                       --rootfs-file images/linux/rootfs.tar.gz --force

echo "============================================================"
echo " Done. SD image: ${PROJ_DIR}/images/linux/petalinux-sdimage.wic"
echo " Flash with:   sudo dd if=images/linux/petalinux-sdimage.wic of=/dev/sdX bs=4M conv=fsync status=progress"
echo "============================================================"
