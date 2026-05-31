# [DEBUG BRING-UP ONLY] skip FSBL DDRInitCheck self-test.
#
# UNSAFE FOR PRODUCTION — applies to all PV variants of fsbl-firmware.
#
# Context: Zynq-7000 FSBL DDR self-test trips on ZYBO Z7-20 byte lane 3
# (mixed-pattern read collapses to 0xFF), hangs at FsblHookFallback PC=0x578
# before u-boot. All prior JTAG DDR readbacks were through that halted
# controller (training never completed). This patch skips the in-FSBL test
# so we reach a TRAINED, quiescent controller for the decisive bench tests.
#
# Remove this bbappend (or SRC_URI line) once root cause is fixed.
#
# Cloud Claude, 2026-05-31 — per Main 80e7b1d reframe + ddr_debug_reports.md
# Option B.

FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI += "file://skip-ddr-init-check.patch"
