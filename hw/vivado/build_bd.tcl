# hw/vivado/build_bd.tcl — Vivado 2024.1 Block Design for SpikeYOLO on ZYBO Z7-20.
#
# Usage:
#   source /opt/Xilinx/Vivado/2024.1/settings64.sh
#   vivado -mode batch -source build_bd.tcl
#
# Inputs:
#   ../hls/build/sa_tiny_fpga_top.xo    (B1 IP — VLNV xilinx.com:hls:sa_tiny_fpga_top:1.0)
#   constraints/zybo_z7_20.xdc          (B2 pin constraints)
#
# Outputs:
#   out/system.bd                       (saved BD)
#   out/system.xpr                      (Vivado project)
#   out/address_map.yaml                (Contract 4 — emitted post-implementation)
#
# Data-plane wiring (Option γ — M1 W6 unblocking):
#   M_AXI_GP0 (PS) -> ic_ctrl -> {spike_accel.s_axi_control,
#                                 axi_dma_feat.S_AXI_LITE}
#   spike_accel.{m_axi_gmem0..gmem4} -> ic_data_hp0 -> ps_0.S_AXI_HP0
#   axi_dma_feat.{M_AXI_MM2S,M_AXI_S2MM} -> ic_data_hp1 -> ps_0.S_AXI_HP1
#   ps_0.FCLK_CLK0 (100 MHz) -> spike_accel + DMA + ic_ctrl + ic_data_*
#   IRQs: spike_accel + dma_mm2s + dma_s2mm -> xlconcat -> ps_0.IRQ_F2P
#
# HDMI path (VDMA + rgb2dvi + v_axis_to_video_out + v_tc bridge) deferred to
# M4-W11 (C3 Application sprint). See URGENT_ASK_8 + REPLIES_FROM_MAIN 2026-05-12.
# FCLK_CLK1 (148.5 MHz) still emitted by PS but unused — harmless.

set PROJECT     spike_zybo
set OUT_DIR     [file normalize "[file dirname [info script]]/out"]
set HLS_DIR     [file normalize "[file dirname [info script]]/../hls/build"]
set CONSTR_DIR  [file normalize "[file dirname [info script]]/constraints"]
set IP_REPO_DIR [file normalize "[file dirname [info script]]/ip_repo"]
set DIGILENT_IP     [file normalize "${IP_REPO_DIR}/digilent/vivado-library"]
set DIGILENT_BOARDS [file normalize "${IP_REPO_DIR}/digilent/vivado-boards/new/board_files"]
set SPIKE_IP    [file normalize "${IP_REPO_DIR}/spike_accel"]
set PART        xc7z020clg400-1
set BOARD_PART  digilentinc.com:zybo-z7-20:part0:1.0

# Catch a missing IP early so the rest of the script doesn't pollute the log.
# B1's exported IP lives as sa_tiny_fpga_top.xo (see hw/hls/README.md).
if {![file exists "${HLS_DIR}/sa_tiny_fpga_top.xo"] &&
    ![file exists "${SPIKE_IP}/sa_tiny_fpga_top.xo"]} {
    puts "WARN: sa_tiny_fpga_top.xo not found under HLS build dir or spike_accel/."
    puts "      Generating BD with a placeholder IP. Re-run after .xo is built."
    set HAS_HLS_IP 0
} else {
    set HAS_HLS_IP 1
}

file mkdir $OUT_DIR
# Per Remote URGENT_ASK_7: Vivado 2024.1 ships without ZYBO board files.
# Point board.repoPaths at Digilent's vivado-boards submodule BEFORE
# create_project / set_property board_part (must be set as a global param
# so the project picks it up at creation time).
if {[file isdirectory $DIGILENT_BOARDS]} {
    set_param board.repoPaths [list $DIGILENT_BOARDS]
    puts "INFO: board.repoPaths = $DIGILENT_BOARDS"
} else {
    puts "ERROR: vivado-boards not found at $DIGILENT_BOARDS"
    puts "       Run hw/vivado/scripts/setup_ip_repo.sh first (it now fetches both"
    puts "       vivado-library and vivado-boards as submodules)."
    exit 1
}

create_project -force $PROJECT $OUT_DIR -part $PART
set_property board_part $BOARD_PART [current_project]

# Compose the ip_repo search path: HLS build dir (B1 dev workflow), the
# checked-in spike_accel drop point (post B1 hand-off), and Digilent's
# vivado-library (rgb2dvi etc., fetched by hw/vivado/scripts/setup_ip_repo.sh).
set ip_paths [list]
if {$HAS_HLS_IP}                  { lappend ip_paths $HLS_DIR }
if {[file isdirectory $SPIKE_IP]} { lappend ip_paths $SPIKE_IP }
if {[file isdirectory $DIGILENT_IP]} {
    lappend ip_paths $DIGILENT_IP
} else {
    puts "WARN: Digilent vivado-library not found at $DIGILENT_IP"
    puts "      run hw/vivado/scripts/setup_ip_repo.sh before re-trying."
}
if {[llength $ip_paths] > 0} {
    set_property ip_repo_paths $ip_paths [current_project]
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
    CONFIG.PCW_USE_M_AXI_GP0           {1} \
    CONFIG.PCW_USE_S_AXI_HP0           {1} \
    CONFIG.PCW_USE_S_AXI_HP1           {1} \
    CONFIG.PCW_USE_FABRIC_INTERRUPT    {1} \
    CONFIG.PCW_IRQ_F2P_INTR            {1} \
    CONFIG.PCW_EN_CLK1_PORT            {1} \
    CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {90} \
    CONFIG.PCW_FPGA1_PERIPHERAL_FREQMHZ {148.5} \
] [get_bd_cells ps_0]

# M2-W2 Path B (URGENT_ASK_17 fallback): FCLK_CLK0 100 -> 90 MHz to close
# timing on the spike_accel critical paths. v7 bitstream + Perf_Explore
# strategy closed -27% of WNS (-0.764 -> -0.557 ns), but the remaining
# 0.557 ns slack would need many more retiming passes with diminishing
# returns. A one-shot 10 % clock reduction grants +1.111 ns of period
# slack and closes timing cleanly. Throughput hit ~10 %, comfortably
# inside the 30 FPS / 33 ms M3 budget per REPLIES_FROM_MAIN 2026-05-13T18:20.
# FCLK_CLK1 (148.5 MHz pixel clock) stays unchanged - it feeds the HDMI
# path (M3 deferred), no impact on the spike_accel data path.

# ============================================================================
# 2. Accelerator IP (B1 HLS output)
# ============================================================================
if {$HAS_HLS_IP} {
    create_bd_cell -type ip -vlnv xilinx.com:hls:sa_tiny_fpga_top:1.0 spike_accel_0
} else {
    # Placeholder concat block keeps the BD structurally valid for M2 dry-run.
    create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 spike_accel_0
}

# ============================================================================
# 3. AXI DMA (feature/weight streaming)
# ============================================================================
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_dma:7.1 axi_dma_feat
set_property -dict [list \
    CONFIG.c_include_sg             {0} \
    CONFIG.c_sg_length_width        {26} \
    CONFIG.c_m_axi_mm2s_data_width  {64} \
    CONFIG.c_m_axi_s2mm_data_width  {64} \
] [get_bd_cells axi_dma_feat]

# ============================================================================
# 4. HDMI TX path — REMOVED in Option γ (URGENT_ASK_8)
# ============================================================================
# Original W5 plan: VDMA(MM2S) -> rgb2dvi -> HDMI TMDS. Blocker: rgb2dvi has
# only parallel RGB inputs (vid_pData/VDE/HSync/VSync), no AXI-Stream slave.
# Proper fix needs v_axis_to_video_out + v_tc bridge IPs. To keep M1 W6
# bitstream on schedule and validate spike_accel, all HDMI/VDMA cells +
# wiring are removed. HDMI display rebuilds in M4-W11 (C3 Application).
# spike_accel still has full HP0 DMA via axi_dma_feat — inference path intact.

# ============================================================================
# 5. AXI Smartconnect — control plane + two HP data planes
# ============================================================================
create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 ic_ctrl
set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI {2}] [get_bd_cells ic_ctrl]

# ic_data_hp0 aggregates the 5 spike_accel gmem* masters into S_AXI_HP0.
create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 ic_data_hp0
set_property -dict [list CONFIG.NUM_SI {5} CONFIG.NUM_MI {1}] [get_bd_cells ic_data_hp0]

# ic_data_hp1 aggregates AXI-DMA (MM2S+S2MM) into S_AXI_HP1.
create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 ic_data_hp1
set_property -dict [list CONFIG.NUM_SI {2} CONFIG.NUM_MI {1}] [get_bd_cells ic_data_hp1]

# ============================================================================
# 6. IRQ concatenation -> PS IRQ_F2P
# ============================================================================
create_bd_cell -type ip -vlnv xilinx.com:ip:xlconcat:2.1 irq_concat
set_property -dict [list CONFIG.NUM_PORTS {3}] [get_bd_cells irq_concat]

# ============================================================================
# 7. Resets — system processor reset for each clock domain
# ============================================================================
create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 rst_clk0
create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 rst_clk1

connect_bd_net [get_bd_pins ps_0/FCLK_CLK0]        [get_bd_pins rst_clk0/slowest_sync_clk]
connect_bd_net [get_bd_pins ps_0/FCLK_RESET0_N]    [get_bd_pins rst_clk0/ext_reset_in]
connect_bd_net [get_bd_pins ps_0/FCLK_CLK1]        [get_bd_pins rst_clk1/slowest_sync_clk]
connect_bd_net [get_bd_pins ps_0/FCLK_RESET0_N]    [get_bd_pins rst_clk1/ext_reset_in]

# ============================================================================
# 8. Control-plane wiring (PS M_AXI_GP0 -> AXI-Lite of each peripheral)
# ============================================================================
connect_bd_intf_net -intf_net ps_to_ic_ctrl \
    [get_bd_intf_pins ps_0/M_AXI_GP0] \
    [get_bd_intf_pins ic_ctrl/S00_AXI]

if {$HAS_HLS_IP} {
    connect_bd_intf_net -intf_net ctrl_to_spike \
        [get_bd_intf_pins ic_ctrl/M00_AXI] \
        [get_bd_intf_pins spike_accel_0/s_axi_control]
}
connect_bd_intf_net -intf_net ctrl_to_dma \
    [get_bd_intf_pins ic_ctrl/M01_AXI] \
    [get_bd_intf_pins axi_dma_feat/S_AXI_LITE]
# ctrl_to_vdma removed (VDMA dropped in Option γ — see Section 4)

# ============================================================================
# 9. Data-plane wiring (spike_accel m_axi_gmem* -> HP0; DMA + VDMA -> HP1)
# ============================================================================
if {$HAS_HLS_IP} {
    # 5 master ports gmem0..gmem4 mapped onto S00..S04 of ic_data_hp0.
    for {set i 0} {$i < 5} {incr i} {
        set s [format "S%02d_AXI" $i]
        connect_bd_intf_net -intf_net "spike_to_hp0_$i" \
            [get_bd_intf_pins spike_accel_0/m_axi_gmem$i] \
            [get_bd_intf_pins ic_data_hp0/$s]
    }
}
connect_bd_intf_net -intf_net ic_data_hp0_to_ps \
    [get_bd_intf_pins ic_data_hp0/M00_AXI] \
    [get_bd_intf_pins ps_0/S_AXI_HP0]

connect_bd_intf_net -intf_net dma_mm2s_to_hp1 \
    [get_bd_intf_pins axi_dma_feat/M_AXI_MM2S] \
    [get_bd_intf_pins ic_data_hp1/S00_AXI]
connect_bd_intf_net -intf_net dma_s2mm_to_hp1 \
    [get_bd_intf_pins axi_dma_feat/M_AXI_S2MM] \
    [get_bd_intf_pins ic_data_hp1/S01_AXI]
# vdma_mm2s_to_hp1 removed (VDMA dropped in Option γ — see Section 4)
connect_bd_intf_net -intf_net ic_data_hp1_to_ps \
    [get_bd_intf_pins ic_data_hp1/M00_AXI] \
    [get_bd_intf_pins ps_0/S_AXI_HP1]

# ============================================================================
# 10. HDMI video stream — REMOVED in Option γ (URGENT_ASK_8)
# ============================================================================
# rgb2dvi has no s_axis_video pin (only parallel RGB inputs). Restoring this
# section requires inserting v_axis_to_video_out:4.0 + v_tc:6.2 bridge IPs
# between vdma_disp.M_AXIS_MM2S and rgb2dvi_0's vid_pData/VDE/HSync/VSync.
# Deferred to M4-W11 (C3 Application). For M2 bitstream, no HDMI output.
# zybo_z7_20.xdc HDMI pin constraints will WARN unused-port — non-fatal.

# ============================================================================
# 11. Clock distribution (100 MHz to data/control plane, 148.5 MHz already wired)
# ============================================================================
# pl_clk0 -> PS GP0 + HP0 + HP1 + smartconnects + accel + DMA + VDMA AXI-Lite
foreach pin {
    ps_0/M_AXI_GP0_ACLK
    ps_0/S_AXI_HP0_ACLK
    ps_0/S_AXI_HP1_ACLK
    ic_ctrl/aclk
    ic_data_hp0/aclk
    ic_data_hp1/aclk
    axi_dma_feat/s_axi_lite_aclk
    axi_dma_feat/m_axi_mm2s_aclk
    axi_dma_feat/m_axi_s2mm_aclk
} {
    catch {connect_bd_net [get_bd_pins ps_0/FCLK_CLK0] [get_bd_pins $pin]}
}
# Resets to the same domain
foreach pin {
    ic_ctrl/aresetn
    ic_data_hp0/aresetn
    ic_data_hp1/aresetn
    axi_dma_feat/axi_resetn
} {
    catch {connect_bd_net [get_bd_pins rst_clk0/peripheral_aresetn] [get_bd_pins $pin]}
}
if {$HAS_HLS_IP} {
    catch {connect_bd_net [get_bd_pins ps_0/FCLK_CLK0] [get_bd_pins spike_accel_0/ap_clk]}
    catch {connect_bd_net [get_bd_pins rst_clk0/peripheral_aresetn] [get_bd_pins spike_accel_0/ap_rst_n]}
}
# VDMA m_axis pixel-clock wiring removed (Option γ — see Section 4)

# ============================================================================
# 12. IRQ wiring
# ============================================================================
if {$HAS_HLS_IP} {
    catch {connect_bd_net [get_bd_pins spike_accel_0/interrupt] [get_bd_pins irq_concat/In0]}
}
catch {connect_bd_net [get_bd_pins axi_dma_feat/mm2s_introut] [get_bd_pins irq_concat/In1]}
catch {connect_bd_net [get_bd_pins axi_dma_feat/s2mm_introut] [get_bd_pins irq_concat/In2]}
# vdma_disp irq removed (Option γ — see Section 4)
connect_bd_net [get_bd_pins irq_concat/dout] [get_bd_pins ps_0/IRQ_F2P]

# ============================================================================
# 13. Address assignments — keep in sync with hw/vivado/out/address_map.yaml
# ============================================================================
assign_bd_address
catch {
    # Pin spike_accel control regs to the canonical base (0x43C00000)
    set seg [get_bd_addr_segs -of [get_bd_cells spike_accel_0]]
    if {[llength $seg] > 0} {
        set_property offset 0x43C00000 [lindex $seg 0]
    }
}
catch {
    # AXI DMA  0x40400000
    set seg [get_bd_addr_segs -of [get_bd_cells axi_dma_feat] -filter {USAGE==register}]
    if {[llength $seg] > 0} { set_property offset 0x40400000 [lindex $seg 0] }
}
# VDMA 0x43000000 address-assign removed (Option γ — see Section 4)

# ============================================================================
# 14. Save + wrapper
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
