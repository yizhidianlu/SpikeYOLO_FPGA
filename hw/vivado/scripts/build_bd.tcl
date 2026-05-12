# hw/vivado/scripts/build_bd.tcl
#
# Vivado 2024.1 batch entry point — wraps the canonical BD builder that lives
# at hw/vivado/build_bd.tcl. The top-level script holds the actual create_bd_*
# calls; this thin wrapper exists so callers can stay inside scripts/ alongside
# synth_impl.tcl and axi_protocol_check.tcl without duplicating logic.
#
# Usage:
#   source /opt/Xilinx/Vivado/2024.1/settings64.sh
#   vivado -mode batch -source hw/vivado/scripts/build_bd.tcl
#
# The wrapped script:
#   - creates project spike_zybo (xc7z020clg400-1, board zybo-z7-20)
#   - instantiates ps_0, spike_accel_0 (B1 IP, placeholder if .xo missing),
#     axi_dma_feat, vdma_disp, rgb2dvi_0, ic_ctrl, ic_data_hp0, ic_data_hp1,
#     irq_concat, rst_clk0, rst_clk1
#   - wires control plane (M_AXI_GP0 -> ic_ctrl -> 3 AXI-Lite slaves)
#   - wires data plane:
#       - spike_accel gmem0..gmem4 -> ic_data_hp0 -> S_AXI_HP0
#       - axi_dma_feat mm2s+s2mm + vdma_disp mm2s -> ic_data_hp1 -> S_AXI_HP1
#   - wires VDMA M_AXIS_MM2S -> rgb2dvi.s_axis_video (pixel clock = FCLK_CLK1)
#   - concatenates IRQ from accel + DMA + VDMA into PS IRQ_F2P
#   - distributes FCLK_CLK0 (100 MHz) to data/control plane,
#                  FCLK_CLK1 (148.5 MHz) to HDMI pixel domain
#   - pins canonical addresses (0x43C0_0000 spike_accel,
#                               0x4040_0000 dma, 0x4300_0000 vdma)
#   - saves system.bd, makes wrapper, reads constraints/zybo_z7_20.xdc
#
# rgb2dvi VLNV `digilentinc.com:ip:rgb2dvi:1.4` is now a hard requirement —
# run `bash hw/vivado/scripts/setup_ip_repo.sh` before sourcing this script.

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
