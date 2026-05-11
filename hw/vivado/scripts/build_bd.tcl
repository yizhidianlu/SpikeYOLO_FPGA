# hw/vivado/scripts/build_bd.tcl
#
# Vivado 2023.2 batch entry point — wraps the canonical BD builder that lives
# at hw/vivado/build_bd.tcl. The top-level script holds the actual create_bd_*
# calls; this thin wrapper exists so callers can stay inside scripts/ alongside
# synth_impl.tcl and axi_protocol_check.tcl without duplicating logic.
#
# Usage:
#   source /opt/Xilinx/Vivado/2023.2/settings64.sh
#   vivado -mode batch -source hw/vivado/scripts/build_bd.tcl
#
# The wrapped script:
#   - creates project spike_zybo (xc7z020clg400-1, board zybo-z7-20)
#   - instantiates ps_0, spike_accel_0 (B1 IP, placeholder if .xo missing),
#     axi_dma_feat, vdma_disp, rgb2dvi_0, ic_ctrl, ic_data
#   - applies AXI4 auto-connect for control plane
#   - assigns spike_accel base to 0x43C00000 (pinned to address_map.yaml)
#   - saves system.bd, makes wrapper, reads constraints/zybo_z7_20.xdc
#
# TODO M2-W1: tighten data-plane wiring (HP0/HP1 split, VDMA -> rgb2dvi
#             AXI4-Stream, IRQ concat to ps_0/IRQ_F2P).
# TODO M2-W1: replace the rgb2dvi catch with a hard requirement once the
#             Digilent IP repo is checked in under hw/vivado/ip_repo/.

set SCRIPT_DIR [file normalize [file dirname [info script]]]
set TOP_BD     [file normalize [file join $SCRIPT_DIR .. build_bd.tcl]]

if {![file exists $TOP_BD]} {
    puts "FATAL: top-level build_bd.tcl not found at $TOP_BD"
    exit 1
}

puts "============================================================"
puts "[scripts/build_bd.tcl] sourcing $TOP_BD"
puts "============================================================"
source $TOP_BD
