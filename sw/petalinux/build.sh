#!/bin/bash
# sw/petalinux/build.sh — one-shot Petalinux 2024.1 image build for ZYBO Z7-20.
#
# Inputs:
#   ../../hw/vivado/out/system.xsa            (B2 hardware platform)
#   project-spec/                              (configs + recipes)
#   $PETALINUX_BSP                            (optional, ADR-0003 Option A path)
#
# Outputs:
#   spikeyolo_petalinux/images/linux/BOOT.BIN
#   spikeyolo_petalinux/images/linux/image.ub
#   spikeyolo_petalinux/images/linux/petalinux-sdimage.wic
#
# Usage:
#   source /opt/petalinux-v2024.1/settings.sh
#   ./build.sh                                 # full build (default)
#   ./build.sh --fast                          # skip image regeneration
#   ./build.sh --dry-run                       # print petalinux-* commands, do not invoke
#   ./build.sh --source /path/to/bsp.bsp       # use Digilent BSP (ADR-0003 Option A)
#
# Exit codes:
#   0   success
#   1   missing input (.xsa, BSP, or $PETALINUX env)
#   2   petalinux-* command failure

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJ_DIR="${SCRIPT_DIR}/spikeyolo_petalinux"
XSA_PATH="${SCRIPT_DIR}/../../hw/vivado/out/system.xsa"
SPEC_DIR="${SCRIPT_DIR}/project-spec"

DRY_RUN=0
FAST=0
BSP_PATH="${PETALINUX_BSP:-}"   # may be overridden by --source

# ---------------------------------------------------------------------------
# CLI parse
# ---------------------------------------------------------------------------
while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run)       DRY_RUN=1; shift ;;
        --fast|-fast)    FAST=1; shift ;;     # -fast kept for back-compat
        --source)        BSP_PATH="$2"; shift 2 ;;
        -h|--help)
            sed -n '2,20p' "$0"
            exit 0 ;;
        *)
            echo "[build.sh] ERROR: unknown flag '$1' (try --help)" >&2
            exit 1 ;;
    esac
done

# ---------------------------------------------------------------------------
# Helper: dry-runnable command runner
# ---------------------------------------------------------------------------
run() {
    if [ "${DRY_RUN}" = "1" ]; then
        echo "[dry-run] $*"
    else
        "$@"
    fi
}

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
if [ "${DRY_RUN}" = "0" ]; then
    if [ -z "${PETALINUX:-}" ]; then
        echo "[build.sh] ERROR: \$PETALINUX env not set." >&2
        echo "           run: source /opt/petalinux-v2024.1/settings.sh" >&2
        exit 1
    fi
    if ! command -v petalinux-create >/dev/null 2>&1; then
        echo "[build.sh] ERROR: petalinux-create not on PATH (sourced settings.sh?)" >&2
        exit 1
    fi
fi

if [ ! -f "${XSA_PATH}" ]; then
    if [ "${DRY_RUN}" = "1" ]; then
        echo "[dry-run] WARN: ${XSA_PATH} missing — will be required for real build."
    else
        echo "[build.sh] ERROR: ${XSA_PATH} not found." >&2
        echo "           run hw/vivado/build_bitstream.tcl first." >&2
        exit 1
    fi
fi

if [ -n "${BSP_PATH}" ] && [ ! -f "${BSP_PATH}" ]; then
    if [ "${DRY_RUN}" = "1" ]; then
        echo "[dry-run] WARN: BSP '${BSP_PATH}' missing — will be required for real build."
    else
        echo "[build.sh] ERROR: --source BSP '${BSP_PATH}' not found." >&2
        exit 1
    fi
fi

# ---------------------------------------------------------------------------
# 1. Create the project on first run.
# ---------------------------------------------------------------------------
if [ ! -d "${PROJ_DIR}" ]; then
    cd "${SCRIPT_DIR}"
    if [ -n "${BSP_PATH}" ]; then
        # ADR-0003 Option A: layer onto Digilent ZYBO Z7-20 BSP.
        run petalinux-create -t project --source "${BSP_PATH}" \
            --name "$(basename "${PROJ_DIR}")"
    else
        # Fallback: vanilla Zynq template (ADR-0003 Option B path).
        run petalinux-create -t project --template zynq \
            --name "$(basename "${PROJ_DIR}")"
    fi
fi

# ---------------------------------------------------------------------------
# 2. Overlay our customisations into the freshly-generated project-spec/.
#
# Two buckets — must NOT be merged:
#
#   meta-user/  — Main owns wholesale (recipes-apps, recipes-bsp,
#                 recipes-kernel, recipes-core). Safe to rsync --delete.
#
#   configs/config — Petalinux owns the base (~500 lines incl. essential
#                    CONFIG_SUBSYSTEM_ARCH_ARM=y, CONFIG_SYSTEM_ZYNQ=y, …).
#                    SPEC_DIR/configs/config is a ~21-line OVERRIDE subset
#                    that must be APPENDED to the base, not replace it.
#                    Bug history: doing `rsync -a --delete` here wiped the
#                    base and made petalinux-config --get-hw-description
#                    blow up with IsADirectoryError because ARCH was empty
#                    (Cloud Claude URGENT_ASK 1bf2f0f, 2026-05-28).
# ---------------------------------------------------------------------------
run rsync -a --delete \
    --exclude .git \
    "${SPEC_DIR}/meta-user/" "${PROJ_DIR}/project-spec/meta-user/"

if [ -f "${SPEC_DIR}/configs/config" ]; then
    CFG_DST="${PROJ_DIR}/project-spec/configs/config"
    MARKER="# === sw/petalinux/project-spec/configs/config overrides applied ==="
    if [ "${DRY_RUN}" = "1" ]; then
        echo "[dry-run] append ${SPEC_DIR}/configs/config to ${CFG_DST} (if marker absent)"
    elif [ -f "${CFG_DST}" ] && grep -qF "${MARKER}" "${CFG_DST}" 2>/dev/null; then
        echo "[build.sh] config overrides already applied — skipping append (rerun)"
    elif [ -f "${CFG_DST}" ]; then
        {
            echo ""
            echo "${MARKER}"
            cat "${SPEC_DIR}/configs/config"
        } >> "${CFG_DST}"
        echo "[build.sh] appended config overrides from ${SPEC_DIR}/configs/config"
    else
        echo "[build.sh] WARN: ${CFG_DST} not present yet — petalinux-create did not generate it?" >&2
    fi
fi

# ---------------------------------------------------------------------------
# 3. Pull in C2/C3 source via the sibling fetch script.
# ---------------------------------------------------------------------------
if [ -x "${SCRIPT_DIR}/scripts/fetch_app_sources.sh" ]; then
    run bash "${SCRIPT_DIR}/scripts/fetch_app_sources.sh"
fi

# ---------------------------------------------------------------------------
# 4. Pull in the latest .xsa.
# ---------------------------------------------------------------------------
cd "${PROJ_DIR}"
run petalinux-config --get-hw-description="${XSA_PATH}" --silentconfig

# ---------------------------------------------------------------------------
# 5. Build rootfs + kernel + u-boot.
# ---------------------------------------------------------------------------
if [ "${FAST}" = "0" ]; then
    run petalinux-build
else
    echo "[build.sh] --fast: skipping petalinux-build"
fi

# ---------------------------------------------------------------------------
# 6. Package BOOT.BIN + image.ub + SD card image.
# ---------------------------------------------------------------------------
run petalinux-package boot --fsbl images/linux/zynq_fsbl.elf \
                           --u-boot --fpga "${XSA_PATH%.xsa}.bit" --force
run petalinux-package wic --bootfiles "BOOT.BIN image.ub" \
                          --rootfs-file images/linux/rootfs.tar.gz --force

echo "============================================================"
if [ "${DRY_RUN}" = "1" ]; then
    echo " Dry-run complete. No files written."
else
    echo " Done. SD image: ${PROJ_DIR}/images/linux/petalinux-sdimage.wic"
    echo " Flash with:   sudo dd if=images/linux/petalinux-sdimage.wic \\"
    echo "                       of=/dev/sdX bs=4M conv=fsync status=progress"
fi
echo "============================================================"
