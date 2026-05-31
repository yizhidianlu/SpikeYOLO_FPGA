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
# Data-plane wiring (locked W5):
#   M_AXI_GP0 (PS) -> ic_ctrl -> {spike_accel.s_axi_control,
#                                 axi_dma_feat.S_AXI_LITE,
#                                 vdma_disp.S_AXI_LITE}
#   spike_accel.{m_axi_gmem0..gmem4} -> ic_data_hp0 -> ps_0.S_AXI_HP0
#   axi_dma_feat.{M_AXI_MM2S,M_AXI_S2MM} -> ic_data_hp1 -> ps_0.S_AXI_HP1
#   vdma_disp.M_AXI_MM2S -> ic_data_hp1
#   vdma_disp.M_AXIS_MM2S -> rgb2dvi.s_axis_video (148.5 MHz pixel clock = FCLK_CLK1)
#   ps_0.FCLK_CLK0 (100 MHz) -> spike_accel + DMA + ic_ctrl + ic_data_*
#   ps_0.FCLK_CLK1 (148.5 MHz) -> rgb2dvi.PixelClk + vdma_disp m_axis side
#   IRQs: spike_accel + dma + vdma -> xlconcat -> ps_0.IRQ_F2P

set PROJECT     spike_zybo
set OUT_DIR     [file normalize "[file dirname [info script]]/out"]
set HLS_DIR     [file normalize "[file dirname [info script]]/../hls/build"]
set CONSTR_DIR  [file normalize "[file dirname [info script]]/constraints"]
set IP_REPO_DIR [file normalize "[file dirname [info script]]/ip_repo"]
set DIGILENT_IP [file normalize "${IP_REPO_DIR}/digilent/vivado-library"]
set SPIKE_IP    [file normalize "${IP_REPO_DIR}/spike_accel"]
set PART        xc7z020clg400-1
# :1.2 is the only Z7-20 board-file version Digilent ships now (:1.0 dropped
# upstream → set_property board_part fails → apply_board_preset no-ops →
# all PS/DDR config lost). Cloud Claude URGENT_ASK_15 c0d3fc2, 2026-05-29.
# The :1.2 preset's DDR config (MT41K256M16 RE-125) == Digilent golden
# byte-for-byte and is CORRECT; §1b applies NO DDR override (see there).
set BOARD_PART  digilentinc.com:zybo-z7-20:part0:1.2

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

# HDMI video-out (rgb2dvi) gate. The rgb2dvi v1.4 IP takes a parallel `vid_io`
# RGB input, NOT AXI-Stream — so vdma_disp.M_AXIS_MM2S can't connect to it
# directly; it needs a v_axi4s_vid_out (+ v_tc) converter in between, which
# isn't wired yet (Cloud Claude URGENT_ASK_18 5b81062, 2026-05-29 — the
# original line-249 connect to a non-existent rgb2dvi/s_axis_video pin never
# csynth'd on 2024.1). Until the converter chain is added (Phase B), gate the
# whole HDMI block off so Phase A (DDR-fix validation: boot→UART) can build.
# Override to 1 on the command line once the converter is in:
#   vivado -mode batch -source build_bd.tcl -tclargs HAS_HDMI=1
set HAS_HDMI 0
foreach a $argv { if {$a eq "HAS_HDMI=1"} { set HAS_HDMI 1 } }

file mkdir $OUT_DIR
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
    CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {100} \
    CONFIG.PCW_FPGA1_PERIPHERAL_FREQMHZ {148.5} \
] [get_bd_cells ps_0]

# ============================================================================
# 1b. DDR lane-3 — NO OVERRIDE (reverted to golden 2026-05-31)
# ============================================================================
# Part/config are correct and EQUAL Digilent's golden preset byte-for-byte:
# MT41K256M16 RE-125 (K-die 1.35 V), board_part :1.2 (:1.0 dropped upstream,
# URGENT_ASK_15). There is no config delta to exploit — so we apply NO DDR
# override here and let the golden preset stand.
#
# Why all overrides were removed (two multi-agent debug workflows +
# first-hand ps7_init.c decode, 2026-05-31):
#
# 1. The board symptom is byte lane 3 reads UNIFORM patterns (0x00->0x00,
#    0xFF->0xFF) correctly but EVERY mixed pattern collapses to a FIXED 0xFF
#    (0xAA->0xFF, 0x12->0xFF). A read-eye/timing offset is data-DEPENDENT and
#    graceful — it cannot produce a fixed all-ones floor with intact uniform
#    words. The all-ones floor == the ODT-pulled-high idle bus (DDR3L idles
#    high) being latched => a read-GATE/postamble-window, DM/level, or PHYSICAL
#    DQ[31:24]/DQS3 defect — NOT a tunable read-eye tap.
#
# 2. We swept PCW_UIPARAM_DDR_DQS_TO_CLK_DELAY_3 three times
#    (-0.100 -> 0.000 -> -0.050); none fixed mixed patterns. First-hand
#    ps7_init.c shows the real per-lane values:
#       read-DQS DLL slave  0xF800612C/30/34/38 = 0x270/0x270/0x26C/0x288
#         (lane3 +9% outlier — but this is the SAME read-sample DOF the 3
#          sweeps already failed to fix, and is EXPECTED from the longest
#          trace BOARD_DELAY3=0.244)
#       fifo_we read-gate   0xF8006140/44/48/4C = 0x35/0x35/0x35/0x35 (UNIFORM)
#    (An earlier "fifo_we lane3=0x140" claim was a transcription error —
#     the gate is uniform; do not chase it.)
#
# 3. TRAIN_WRITE_LEVEL/READ_GATE/DATA_EYE are ALL = 1, so ps7_init's per-lane
#    slave values are only SEEDS — the PHY re-runs hardware training every cold
#    boot and OVERWRITES them. Editing BOARD_DELAY3 (which only changes the
#    derived seed) is therefore a likely NO-OP at runtime. That's why none of
#    the seed edits stuck. (Commit 8d67dcf's BOARD_DELAY3=0.221 is reverted
#    here for exactly this reason.)
#
# DECISIVE NEXT STEP (not a BD rebuild): boot an FSBL-escape-hatch bring-up
# image (skip DDRInitCheck) to get the FIRST uncontaminated, fully-TRAINED DDR
# readback (all prior JTAG reads were through a FAILED-init halted controller),
# then run the 0x55-vs-0xAA byte-3 symmetry test + read POST-TRAIN slave regs.
# If 0x55 survives while its bit-inverse 0xAA collapses to 0xFF => non-symmetric
# 1-bias => PHYSICAL lane-3 fault (no tap/training/seed fix possible).
# See runs/cloud_machine/REPLIES_FROM_MAIN.md 2026-05-31.
#
# (intentionally no set_property DDR override — golden preset stands)

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
# 4. HDMI TX path
# ============================================================================
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_vdma:6.3 vdma_disp
set_property -dict [list \
    CONFIG.c_include_mm2s           {1} \
    CONFIG.c_include_s2mm           {0} \
    CONFIG.c_m_axi_mm2s_data_width  {64} \
    CONFIG.c_mm2s_max_burst_length  {256} \
    CONFIG.c_include_mm2s_dre       {0} \
] [get_bd_cells vdma_disp]

# Digilent's rgb2dvi IP (community-maintained for ZYBO HDMI out).
# Gated by HAS_HDMI — see the flag definition near the top. Needs a
# v_axi4s_vid_out converter (Phase B) before it can connect to VDMA's AXIS.
if {$HAS_HDMI} {
create_bd_cell -type ip -vlnv digilentinc.com:ip:rgb2dvi:1.4 rgb2dvi_0
set_property -dict [list \
    CONFIG.kClkRange    {1} \
    CONFIG.kGenerateSerialClk {true} \
    CONFIG.kRstActiveHigh     {true} \
] [get_bd_cells rgb2dvi_0]
}

# ============================================================================
# 5. AXI Smartconnect — control plane + two HP data planes
# ============================================================================
create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 ic_ctrl
set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI {3}] [get_bd_cells ic_ctrl]

# ic_data_hp0 aggregates the 5 spike_accel gmem* masters into S_AXI_HP0.
# HAS_HLS_IP gated: its 5 slaves are ALL spike_accel gmem* masters (also
# HAS_HLS_IP-gated below), so in the Phase-A placeholder build it would have
# 5 dangling AXI slaves → synth optimises the instance to a black box →
# opt_design DRC [INBB-3] fails (Cloud Claude URGENT_ASK_19 d607cba). Only
# create it when the spike_accel masters exist.
if {$HAS_HLS_IP} {
create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 ic_data_hp0
set_property -dict [list CONFIG.NUM_SI {5} CONFIG.NUM_MI {1}] [get_bd_cells ic_data_hp0]
}

# ic_data_hp1 aggregates AXI-DMA (MM2S+S2MM) and (when HAS_HDMI) VDMA MM2S
# into S_AXI_HP1. dma_feat is always 2 slaves (S00/S01); vdma_disp adds S02
# only with HDMI. NUM_SI tracks that so the smartconnect has no dangling
# slave (Cloud Claude URGENT_ASK_20 db78202).
set hp1_num_si [expr {$HAS_HDMI ? 3 : 2}]
create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 ic_data_hp1
set_property -dict [list CONFIG.NUM_SI $hp1_num_si CONFIG.NUM_MI {1}] [get_bd_cells ic_data_hp1]

# ============================================================================
# 6. IRQ concatenation -> PS IRQ_F2P
# ============================================================================
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
    # M00 -> PS HP0: only when ic_data_hp0 exists (URGENT_ASK_19 d607cba).
    # PS_USE_S_AXI_HP0 stays 1; the HP0 slave just sits idle in Phase A.
    connect_bd_intf_net -intf_net ic_data_hp0_to_ps \
        [get_bd_intf_pins ic_data_hp0/M00_AXI] \
        [get_bd_intf_pins ps_0/S_AXI_HP0]
}

connect_bd_intf_net -intf_net dma_mm2s_to_hp1 \
    [get_bd_intf_pins axi_dma_feat/M_AXI_MM2S] \
    [get_bd_intf_pins ic_data_hp1/S00_AXI]
connect_bd_intf_net -intf_net dma_s2mm_to_hp1 \
    [get_bd_intf_pins axi_dma_feat/M_AXI_S2MM] \
    [get_bd_intf_pins ic_data_hp1/S01_AXI]
# vdma_disp memory-read master → S02 only when HDMI present (URGENT_ASK_20).
if {$HAS_HDMI} {
    connect_bd_intf_net -intf_net vdma_mm2s_to_hp1 \
        [get_bd_intf_pins vdma_disp/M_AXI_MM2S] \
        [get_bd_intf_pins ic_data_hp1/S02_AXI]
}
connect_bd_intf_net -intf_net ic_data_hp1_to_ps \
    [get_bd_intf_pins ic_data_hp1/M00_AXI] \
    [get_bd_intf_pins ps_0/S_AXI_HP1]

# ============================================================================
# 10. HDMI video stream: VDMA M_AXIS_MM2S -> rgb2dvi  (HAS_HDMI gated)
# ============================================================================
# NOTE: rgb2dvi takes parallel vid_io, not AXIS. This direct connect to a
# non-existent rgb2dvi/s_axis_video pin is a Phase-B placeholder — the real
# wiring needs v_axi4s_vid_out (AXIS->vid_io) + v_tc between VDMA and rgb2dvi
# (Cloud Claude URGENT_ASK_18 5b81062). Gated off for Phase A.
if {$HAS_HDMI} {
connect_bd_intf_net -intf_net vdma_to_rgb2dvi \
    [get_bd_intf_pins vdma_disp/M_AXIS_MM2S] \
    [get_bd_intf_pins rgb2dvi_0/s_axis_video]
# Pixel clock for rgb2dvi (148.5 MHz nominal for 1080p60).
connect_bd_net [get_bd_pins ps_0/FCLK_CLK1]     [get_bd_pins rgb2dvi_0/PixelClk]
connect_bd_net [get_bd_pins rst_clk1/peripheral_reset] [get_bd_pins rgb2dvi_0/aRst]

# Expose HDMI TMDS pins to top wrapper (constrained in zybo_z7_20.xdc).
create_bd_port -dir O -from 3 -to 0 hdmi_out_tmds_data_p
create_bd_port -dir O -from 3 -to 0 hdmi_out_tmds_data_n
create_bd_port -dir O hdmi_out_tmds_clk_p
create_bd_port -dir O hdmi_out_tmds_clk_n
connect_bd_net [get_bd_ports hdmi_out_tmds_data_p] [get_bd_pins rgb2dvi_0/TMDS_Data_p]
connect_bd_net [get_bd_ports hdmi_out_tmds_data_n] [get_bd_pins rgb2dvi_0/TMDS_Data_n]
connect_bd_net [get_bd_ports hdmi_out_tmds_clk_p]  [get_bd_pins rgb2dvi_0/TMDS_Clk_p]
connect_bd_net [get_bd_ports hdmi_out_tmds_clk_n]  [get_bd_pins rgb2dvi_0/TMDS_Clk_n]
}

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
} {
    catch {connect_bd_net [get_bd_pins rst_clk0/peripheral_aresetn] [get_bd_pins $pin]}
}
if {$HAS_HLS_IP} {
    catch {connect_bd_net [get_bd_pins ps_0/FCLK_CLK0] [get_bd_pins spike_accel_0/ap_clk]}
    catch {connect_bd_net [get_bd_pins rst_clk0/peripheral_aresetn] [get_bd_pins spike_accel_0/ap_rst_n]}
}
# VDMA m_axis side runs on the pixel clock.
catch {connect_bd_net [get_bd_pins ps_0/FCLK_CLK1] [get_bd_pins vdma_disp/m_axis_mm2s_aclk]}

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
    # VDMA     0x43000000
    set seg [get_bd_addr_segs -of [get_bd_cells vdma_disp] -filter {USAGE==register}]
    if {[llength $seg] > 0} { set_property offset 0x43000000 [lindex $seg 0] }
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
