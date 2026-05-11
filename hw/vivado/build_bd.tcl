# hw/vivado/build_bd.tcl — Vivado 2023.2 Block Design for SpikeYOLO on ZYBO Z7-20.
#
# Usage:
#   source /opt/Xilinx/Vivado/2023.2/settings64.sh
#   vivado -mode batch -source build_bd.tcl
#
# Inputs:
#   ../hls/build/tiny_fpga_top.xo     (B1 IP)
#   constraints/zybo_z7_20.xdc        (B2 pin constraints)
#
# Outputs:
#   out/system.bd       (saved BD)
#   out/system.xpr      (Vivado project)
#   out/address_map.yaml (Contract 4 — emitted post-implementation)

set PROJECT     spike_zybo
set OUT_DIR     [file normalize "[file dirname [info script]]/out"]
set HLS_DIR     [file normalize "[file dirname [info script]]/../hls/build"]
set CONSTR_DIR  [file normalize "[file dirname [info script]]/constraints"]
set PART        xc7z020clg400-1
set BOARD_PART  digilentinc.com:zybo-z7-20:part0:1.0

# Catch a missing IP early so the rest of the script doesn't pollute the log.
if {![file exists "${HLS_DIR}/tiny_fpga_top.xo"]} {
    puts "WARN: hw/hls/build/tiny_fpga_top.xo not found — generating BD with a"
    puts "      placeholder IP. Re-run after the HLS .xo is built."
    set HAS_HLS_IP 0
} else {
    set HAS_HLS_IP 1
}

file mkdir $OUT_DIR
create_project -force $PROJECT $OUT_DIR -part $PART
set_property board_part $BOARD_PART [current_project]

if {$HAS_HLS_IP} {
    set_property ip_repo_paths "${HLS_DIR}" [current_project]
    update_ip_catalog
}

create_bd_design system

# ============================================================================
# 1. Zynq PS
# ============================================================================
create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 ps_0
apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 \
    -config {make_external "FIXED_IO, DDR" apply_board_preset "1"} \
    [get_bd_cells ps_0]

set_property -dict [list \
    CONFIG.PCW_USE_M_AXI_GP0        {1} \
    CONFIG.PCW_USE_S_AXI_HP0        {1} \
    CONFIG.PCW_USE_S_AXI_HP1        {1} \
    CONFIG.PCW_USE_FABRIC_INTERRUPT {1} \
    CONFIG.PCW_IRQ_F2P_INTR         {1} \
    CONFIG.PCW_USB0_USB0_IO         {MIO 28 .. 39} \
] [get_bd_cells ps_0]

# ============================================================================
# 2. Clocks — pl_clk0 100 MHz (M4) or 150 MHz (M5)
# ============================================================================
set_property -dict [list CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {100}] [get_bd_cells ps_0]

# ============================================================================
# 3. Accelerator IP (B1 HLS output)
# ============================================================================
if {$HAS_HLS_IP} {
    create_bd_cell -type ip -vlnv xilinx.com:hls:tiny_fpga_top:1.0 spike_accel_0
} else {
    # Placeholder concat block keeps the BD structurally valid for M2 dry-run.
    create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 spike_accel_0
}

# ============================================================================
# 4. AXI DMA (feature/weight streaming)
# ============================================================================
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_dma:7.1 axi_dma_feat
set_property -dict [list \
    CONFIG.c_include_sg         {0} \
    CONFIG.c_sg_length_width    {26} \
    CONFIG.c_m_axi_mm2s_data_width {64} \
    CONFIG.c_m_axi_s2mm_data_width {64} \
] [get_bd_cells axi_dma_feat]

# ============================================================================
# 5. HDMI TX path
# ============================================================================
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_vdma:6.3 vdma_disp
set_property -dict [list \
    CONFIG.c_include_mm2s        {1} \
    CONFIG.c_include_s2mm        {0} \
    CONFIG.c_m_axi_mm2s_data_width {64} \
    CONFIG.c_mm2s_max_burst_length {256} \
    CONFIG.c_include_mm2s_dre    {0} \
] [get_bd_cells vdma_disp]

# Digilent's rgb2dvi IP (community-maintained for ZYBO HDMI out).
catch {create_bd_cell -type ip -vlnv digilentinc.com:ip:rgb2dvi:1.4 rgb2dvi_0}
if {[llength [get_bd_cells rgb2dvi_0]] == 0} {
    puts "WARN: rgb2dvi IP not in catalog — install the Digilent IP library or"
    puts "      drop it into hw/vivado/ip_repo/ before re-running."
}

# ============================================================================
# 6. AXI Smartconnect — control + data paths
# ============================================================================
create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 ic_ctrl
create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 ic_data
set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI {3}] [get_bd_cells ic_ctrl]
set_property -dict [list CONFIG.NUM_SI {3} CONFIG.NUM_MI {1}] [get_bd_cells ic_data]

# ============================================================================
# 7. Auto connect (control + data + clocks)
# ============================================================================
if {$HAS_HLS_IP} {
    apply_bd_automation -rule xilinx.com:bd_rule:axi4 \
        -config {Master "/ps_0/M_AXI_GP0" Slave "/spike_accel_0/s_axi_control" \
                 Clk_master "Auto" Clk_slave "Auto"} \
        [get_bd_intf_pins spike_accel_0/s_axi_control]
}
apply_bd_automation -rule xilinx.com:bd_rule:axi4 \
    -config {Master "/ps_0/M_AXI_GP0" Slave "/axi_dma_feat/S_AXI_LITE" \
             Clk_master "Auto" Clk_slave "Auto"} \
    [get_bd_intf_pins axi_dma_feat/S_AXI_LITE]
apply_bd_automation -rule xilinx.com:bd_rule:axi4 \
    -config {Master "/ps_0/M_AXI_GP0" Slave "/vdma_disp/S_AXI_LITE" \
             Clk_master "Auto" Clk_slave "Auto"} \
    [get_bd_intf_pins vdma_disp/S_AXI_LITE]

# ============================================================================
# 8. Address assignments — keep in sync with hw/vivado/out/address_map.yaml
# ============================================================================
assign_bd_address
catch {
    # Pin spike_accel control regs to the canonical base
    set seg [get_bd_addr_segs -of [get_bd_cells spike_accel_0]]
    if {[llength $seg] > 0} {
        set_property offset 0x43C00000 [lindex $seg 0]
    }
}

# ============================================================================
# 9. Save + wrapper
# ============================================================================
save_bd_design
write_bd_tcl -force [file join $OUT_DIR system_bd_dump.tcl]

make_wrapper -files [get_files system.bd] -top
add_files -norecurse [file join $OUT_DIR ${PROJECT}.gen sources_1 bd system hdl system_wrapper.v]
update_compile_order

read_xdc [file join $CONSTR_DIR zybo_z7_20.xdc]

puts "============================================================"
puts "build_bd.tcl OK — BD saved to ${OUT_DIR}/system.bd"
puts "Next: vivado -mode batch -source build_bitstream.tcl"
puts "============================================================"
