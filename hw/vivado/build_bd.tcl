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
# Data-plane wiring (M3 HDMI rebuild — URGENT_ASK_18):
#   M_AXI_GP0 (PS) -> ic_ctrl -> {spike_accel.s_axi_control,
#                                 axi_dma_feat.S_AXI_LITE,
#                                 vdma_disp.S_AXI_LITE,
#                                 v_tc_0.ctrl}
#   spike_accel.{m_axi_gmem0..gmem4} -> ic_data_hp0 -> ps_0.S_AXI_HP0
#   axi_dma_feat.{M_AXI_MM2S,M_AXI_S2MM} + vdma_disp.M_AXI_MM2S -> ic_data_hp1 -> ps_0.S_AXI_HP1
#   ps_0.FCLK_CLK0 (90 MHz) -> spike_accel + DMA + ic_ctrl + ic_data_*
#   ps_0.FCLK_CLK1 (148.5 MHz) -> vdma m_axis side + v_tc clk + vid_out + rgb2dvi PixelClk
#   IRQs: spike_accel + dma_mm2s + dma_s2mm + vdma_mm2s -> xlconcat -> ps_0.IRQ_F2P
#
# HDMI Section 10 uses an in-tree Verilog adapter (rtl/axis_to_video_bridge.v)
# in place of `xilinx.com:ip:v_axis_to_video_out:4.0`, which is missing from
# Vivado installs without the Video & Image Processing IP Suite (URGENT_ASK_18,
# 2026-05-13). The bridge is functionally equivalent for our 1080p60 use-case
# and removes the per-machine installer dependency.

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
# board_part version probe (M2-W2 quirk sync): older Digilent vivado-boards
# submodules ship :1.0, newer ones ship :1.2. Try the declared revision first,
# fall back to the other. Remote previously worked around this via string-map
# in run_step5_bd_patched.tcl; this in-tree probe makes the wrapper redundant.
if {[catch {set_property board_part $BOARD_PART [current_project]} _bp_err]} {
    set _alt_bp [regsub {part0:1\.[02]$} $BOARD_PART {part0:1.2}]
    if {$_alt_bp eq $BOARD_PART} { set _alt_bp [regsub {part0:1\.[02]$} $BOARD_PART {part0:1.0}] }
    puts "INFO: board_part $BOARD_PART not in catalog, trying $_alt_bp"
    set_property board_part $_alt_bp [current_project]
    set BOARD_PART $_alt_bp
}
unset -nocomplain _bp_err _alt_bp

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

# M3 HDMI: in-tree Verilog adapter that replaces v_axis_to_video_out:4.0
# (which is shipped only with the Video & Image Processing IP Suite).
# Adding it via add_files lets Section 10 instantiate it as a BD module
# reference (`create_bd_cell -type module -reference axis_to_video_bridge`).
set RTL_DIR [file normalize "[file dirname [info script]]/rtl"]
if {[file exists "${RTL_DIR}/axis_to_video_bridge.v"]} {
    add_files -norecurse [list "${RTL_DIR}/axis_to_video_bridge.v"]
    update_compile_order -fileset sources_1
} else {
    puts "WARN: ${RTL_DIR}/axis_to_video_bridge.v not found - HDMI Section 10 will fail"
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
# 4. HDMI TX path — M3 rebuild (was Option γ-removed at URGENT_ASK_8)
# ============================================================================
# Data flow: vdma_disp.M_AXIS_MM2S (AXI-Stream RGB pixels @ 148.5 MHz pixel
#            clock) -> vid_out.s_axis (axis-to-parallel video adapter) ->
#            rgb2dvi_0.vid_p* (parallel RGB) -> TMDS serializer -> 4 LVDS pairs.
# Side: v_tc_0 generates 1080p60 timing (HSync/VSync/active/blanking) consumed
#       by vid_out's vtiming_* discrete inputs.

create_bd_cell -type ip -vlnv xilinx.com:ip:axi_vdma:6.3 vdma_disp
set_property -dict [list \
    CONFIG.c_include_mm2s           {1} \
    CONFIG.c_include_s2mm           {0} \
    CONFIG.c_mm2s_genlock_mode      {0} \
    CONFIG.c_include_mm2s_dre       {1} \
    CONFIG.c_m_axi_mm2s_data_width  {64} \
    CONFIG.c_mm2s_max_burst_length  {256} \
] [get_bd_cells vdma_disp]

create_bd_cell -type ip -vlnv xilinx.com:ip:v_tc:6.2 v_tc_0
set_property -dict [list \
    CONFIG.HAS_AXI4_LITE {true} \
    CONFIG.GEN_F0_VSYNC_HSTART {1920} \
    CONFIG.GEN_F0_VSYNC_HEND   {1920} \
    CONFIG.GEN_F0_VFRAME_SIZE  {1125} \
    CONFIG.GEN_F0_VSYNC_VSTART {1083} \
    CONFIG.GEN_F0_VSYNC_VEND   {1088} \
    CONFIG.GEN_F1_VSYNC_HSTART {1920} \
    CONFIG.GEN_F1_VSYNC_HEND   {1920} \
    CONFIG.GEN_F1_VFRAME_SIZE  {1125} \
    CONFIG.GEN_F1_VSYNC_VSTART {1083} \
    CONFIG.GEN_F1_VSYNC_VEND   {1088} \
    CONFIG.GEN_HACTIVE_SIZE    {1920} \
    CONFIG.GEN_HFRAME_SIZE     {2200} \
    CONFIG.GEN_HSYNC_START     {2008} \
    CONFIG.GEN_HSYNC_END       {2052} \
    CONFIG.GEN_VACTIVE_SIZE    {1080} \
] [get_bd_cells v_tc_0]

# vid_out: in-tree Verilog `axis_to_video_bridge` instantiated as a BD
# module reference (replaces missing xilinx.com:ip:v_axis_to_video_out:4.0).
# Vivado infers AXI4-Stream slave interface from the s_axis_* port names.
create_bd_cell -type module -reference axis_to_video_bridge vid_out

create_bd_cell -type ip -vlnv digilentinc.com:ip:rgb2dvi:1.4 rgb2dvi_0
set_property -dict [list \
    CONFIG.kClkRange          {1} \
    CONFIG.kRstActiveHigh     {true} \
    CONFIG.kGenerateSerialClk {true} \
] [get_bd_cells rgb2dvi_0]

# ============================================================================
# 5. AXI Smartconnect — control plane + two HP data planes
# ============================================================================
# ic_ctrl masters: M00=spike_accel.s_axi_control, M01=axi_dma_feat.S_AXI_LITE,
# M02=vdma_disp.S_AXI_LITE, M03=v_tc_0.ctrl (M3 HDMI rebuild).
create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 ic_ctrl
set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI {4}] [get_bd_cells ic_ctrl]

# ic_data_hp0 aggregates the 5 spike_accel gmem* masters into S_AXI_HP0.
create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 ic_data_hp0
set_property -dict [list CONFIG.NUM_SI {5} CONFIG.NUM_MI {1}] [get_bd_cells ic_data_hp0]

# ic_data_hp1 aggregates AXI-DMA (MM2S+S2MM) + VDMA MM2S into S_AXI_HP1.
create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 ic_data_hp1
set_property -dict [list CONFIG.NUM_SI {3} CONFIG.NUM_MI {1}] [get_bd_cells ic_data_hp1]

# ============================================================================
# 6. IRQ concatenation -> PS IRQ_F2P
# ============================================================================
# In0=spike_accel.interrupt, In1=dma_mm2s, In2=dma_s2mm, In3=vdma_mm2s (M3).
create_bd_cell -type ip -vlnv xilinx.com:ip:xlconcat:2.1 irq_concat
set_property -dict [list CONFIG.NUM_PORTS {4}] [get_bd_cells irq_concat]

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
connect_bd_intf_net -intf_net ctrl_to_vdma \
    [get_bd_intf_pins ic_ctrl/M02_AXI] \
    [get_bd_intf_pins vdma_disp/S_AXI_LITE]
connect_bd_intf_net -intf_net ctrl_to_v_tc \
    [get_bd_intf_pins ic_ctrl/M03_AXI] \
    [get_bd_intf_pins v_tc_0/ctrl]

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
connect_bd_intf_net -intf_net vdma_mm2s_to_hp1 \
    [get_bd_intf_pins vdma_disp/M_AXI_MM2S] \
    [get_bd_intf_pins ic_data_hp1/S02_AXI]
connect_bd_intf_net -intf_net ic_data_hp1_to_ps \
    [get_bd_intf_pins ic_data_hp1/M00_AXI] \
    [get_bd_intf_pins ps_0/S_AXI_HP1]

# ============================================================================
# 10. HDMI video stream (M3 rebuild — uses in-tree axis_to_video_bridge)
# ============================================================================
# vdma -> vid_out: AXI-Stream RGB at 148.5 MHz pixel clock. The s_axis_*
# port group on axis_to_video_bridge is auto-inferred as Xilinx AXI4-Stream
# slave interface, so connect_bd_intf_net works straight to vdma.M_AXIS_MM2S.
connect_bd_intf_net -intf_net vdma_axis_to_vid_out \
    [get_bd_intf_pins vdma_disp/M_AXIS_MM2S] \
    [get_bd_intf_pins vid_out/s_axis]

# v_tc.vtiming_out interface -> vid_out discrete vtiming_* pins. Vivado
# expands v_tc's vtiming_out video_timing interface into individual sub-pins
# named `vtiming_out_<signal>` accessible via get_bd_pins.
foreach {sig vidpin} {
    active_video  vtiming_active_video
    hsync         vtiming_hsync
    vsync         vtiming_vsync
    hblank        vtiming_hblank
    vblank        vtiming_vblank
} {
    catch {connect_bd_net \
        [get_bd_pins v_tc_0/vtiming_out_$sig] \
        [get_bd_pins vid_out/$vidpin]}
}

# vid_out -> rgb2dvi: parallel RGB data + sync signals (discrete pins).
connect_bd_net [get_bd_pins vid_out/vid_data]          [get_bd_pins rgb2dvi_0/vid_pData]
connect_bd_net [get_bd_pins vid_out/vid_active_video]  [get_bd_pins rgb2dvi_0/vid_pVDE]
connect_bd_net [get_bd_pins vid_out/vid_hsync]         [get_bd_pins rgb2dvi_0/vid_pHSync]
connect_bd_net [get_bd_pins vid_out/vid_vsync]         [get_bd_pins rgb2dvi_0/vid_pVSync]

# HDMI TMDS BD ports — names match constraints/zybo_z7_20.xdc:
#   hdmi_tx_clk_p/n  (1 pair),  hdmi_tx_data_p/n  ([2:0], 3 pairs)
create_bd_port -dir O                hdmi_tx_clk_p
create_bd_port -dir O                hdmi_tx_clk_n
create_bd_port -dir O -from 2 -to 0  hdmi_tx_data_p
create_bd_port -dir O -from 2 -to 0  hdmi_tx_data_n
connect_bd_net [get_bd_ports hdmi_tx_clk_p]   [get_bd_pins rgb2dvi_0/TMDS_Clk_p]
connect_bd_net [get_bd_ports hdmi_tx_clk_n]   [get_bd_pins rgb2dvi_0/TMDS_Clk_n]
connect_bd_net [get_bd_ports hdmi_tx_data_p]  [get_bd_pins rgb2dvi_0/TMDS_Data_p]
connect_bd_net [get_bd_ports hdmi_tx_data_n]  [get_bd_pins rgb2dvi_0/TMDS_Data_n]

# rgb2dvi pixel-clock + reset (148.5 MHz on FCLK_CLK1).
connect_bd_net [get_bd_pins ps_0/FCLK_CLK1]            [get_bd_pins rgb2dvi_0/PixelClk]
connect_bd_net [get_bd_pins rst_clk1/peripheral_reset] [get_bd_pins rgb2dvi_0/aRst]

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
    vdma_disp/s_axi_lite_aclk
    vdma_disp/m_axi_mm2s_aclk
    v_tc_0/s_axi_aclk
} {
    catch {connect_bd_net [get_bd_pins ps_0/FCLK_CLK0] [get_bd_pins $pin]}
}
# Resets to the same domain
foreach pin {
    ic_ctrl/aresetn
    ic_data_hp0/aresetn
    ic_data_hp1/aresetn
    axi_dma_feat/axi_resetn
    vdma_disp/axi_resetn
    v_tc_0/s_axi_aresetn
} {
    catch {connect_bd_net [get_bd_pins rst_clk0/peripheral_aresetn] [get_bd_pins $pin]}
}
if {$HAS_HLS_IP} {
    catch {connect_bd_net [get_bd_pins ps_0/FCLK_CLK0] [get_bd_pins spike_accel_0/ap_clk]}
    catch {connect_bd_net [get_bd_pins rst_clk0/peripheral_aresetn] [get_bd_pins spike_accel_0/ap_rst_n]}
}

# Pixel-clock domain (148.5 MHz on FCLK_CLK1) — vdma m_axis side + v_tc clk +
# axis_to_video_bridge (single-clock module, drives s_axis_aclk on the same
# pixel clock so no CDC FIFO is needed).
catch {connect_bd_net [get_bd_pins ps_0/FCLK_CLK1] [get_bd_pins vdma_disp/m_axis_mm2s_aclk]}
catch {connect_bd_net [get_bd_pins ps_0/FCLK_CLK1] [get_bd_pins v_tc_0/clk]}
catch {connect_bd_net [get_bd_pins ps_0/FCLK_CLK1] [get_bd_pins vid_out/s_axis_aclk]}
catch {connect_bd_net [get_bd_pins rst_clk1/peripheral_aresetn] [get_bd_pins v_tc_0/resetn]}
catch {connect_bd_net [get_bd_pins rst_clk1/peripheral_aresetn] [get_bd_pins vid_out/s_axis_aresetn]}

# ============================================================================
# 12. IRQ wiring
# ============================================================================
if {$HAS_HLS_IP} {
    catch {connect_bd_net [get_bd_pins spike_accel_0/interrupt] [get_bd_pins irq_concat/In0]}
}
catch {connect_bd_net [get_bd_pins axi_dma_feat/mm2s_introut] [get_bd_pins irq_concat/In1]}
catch {connect_bd_net [get_bd_pins axi_dma_feat/s2mm_introut] [get_bd_pins irq_concat/In2]}
catch {connect_bd_net [get_bd_pins vdma_disp/mm2s_introut]    [get_bd_pins irq_concat/In3]}
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
catch {
    # VDMA  0x43000000  (M3 HDMI rebuild — matches address_map.yaml + uio_config.dts)
    set seg [get_bd_addr_segs -of [get_bd_cells vdma_disp] -filter {USAGE==register}]
    if {[llength $seg] > 0} { set_property offset 0x43000000 [lindex $seg 0] }
}
catch {
    # v_tc_0 0x43C10000  (next free slot above spike_accel)
    set seg [get_bd_addr_segs -of [get_bd_cells v_tc_0] -filter {USAGE==register}]
    if {[llength $seg] > 0} { set_property offset 0x43C10000 [lindex $seg 0] }
}

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
