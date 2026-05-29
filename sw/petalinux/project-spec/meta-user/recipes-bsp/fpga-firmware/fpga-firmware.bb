# fpga-firmware.bb — ship the v12c PL bitstream into the rootfs as a
# raw FPGA-manager binary (.bit.bin) and program it at boot.
#
# Why this recipe exists (Cloud Claude uart_diag 869000a, 2026-05-29):
#   The exported XSA (hw/vivado/out/system.xsa) does NOT embed the
#   bitstream, so petalinux's CONFIG_SUBSYSTEM_FPGA_MANAGER flow had
#   nothing to extract — BOOT.BIN ended up without a bitstream (Bug A)
#   and /lib/firmware shipped only the SNN weights, no system.bit.bin
#   (Bug B). Without the PL programmed, spike_accel UIO + AXI DMA + HDMI
#   drivers never probe and the demo can't run.
#
#   We have the standalone bitstream at hw/vivado/out/system.bit (Git LFS,
#   2.52 MB). fetch_app_sources.sh stages it into this recipe's files/;
#   here we convert .bit -> .bit.bin via bootgen (correct byte order for
#   the Zynq-7000 zynq-fpga manager) and install it to /lib/firmware.
#
#   NOTE: this recipe does NOT also put the bitstream into BOOT.BIN — that
#   would double-program the PL (FSBL + Linux). The fpga_manager path
#   (this recipe + load-fpga.service) is the single source of PL config.

SUMMARY = "SpikeYOLO v12c PL bitstream + boot-time FPGA-manager load"
DESCRIPTION = "Converts system.bit to system.bit.bin and programs the PL \
at boot via fpgautil, so spike_accel / AXI-DMA / HDMI drivers can probe."
LICENSE = "CLOSED"

SRC_URI = "file://system.bit \
           file://load-fpga.service"

S = "${WORKDIR}"

# bootgen does the .bit -> .bit.bin conversion at build time.
DEPENDS = "bootgen-native"

# Pulls in fpgautil at runtime (provided by fpga-manager-script in
# meta-xilinx when CONFIG_SUBSYSTEM_FPGA_MANAGER=y).
RDEPENDS:${PN} = "fpga-manager-script"

inherit systemd

SYSTEMD_SERVICE:${PN} = "load-fpga.service"
SYSTEMD_AUTO_ENABLE = "enable"

# Zynq-7000 full bitstream — architecture is fixed.
COMPATIBLE_MACHINE = ".*"

do_compile() {
    # Avoid a <<EOF heredoc here — bitbake's .bb parser scans for the
    # function's closing brace and mis-tokenises the `}` inside the bif
    # body, throwing "ParseError: unparsed line 'EOF'" (Cloud Claude
    # URGENT_ASK_13 f19a840, 2026-05-29). printf keeps it on safe lines.
    printf 'all:\n{\n    [bitstream] %s/system.bit\n}\n' "${WORKDIR}" \
        > ${WORKDIR}/bitstream.bif
    # -process_bitstream bin emits ${WORKDIR}/system.bit.bin in the byte
    # order the zynq-fpga manager expects (no .bit header, bit-swapped).
    cd ${WORKDIR}
    bootgen -arch zynq -image bitstream.bif -process_bitstream bin -w
}

do_install() {
    install -d ${D}${nonarch_base_libdir}/firmware
    install -m 0644 ${WORKDIR}/system.bit.bin \
        ${D}${nonarch_base_libdir}/firmware/system.bit.bin

    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${WORKDIR}/load-fpga.service \
        ${D}${systemd_system_unitdir}/load-fpga.service
}

FILES:${PN} = "${nonarch_base_libdir}/firmware/system.bit.bin \
               ${systemd_system_unitdir}/load-fpga.service"
