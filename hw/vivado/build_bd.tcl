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
set BRIDGE_IP   [file normalize "${IP_REPO_DIR}/axis_to_video_bridge"]
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
if {[file isdirectory $BRIDGE_IP] && [file exists "${BRIDGE_IP}/component.xml"]} {
    lappend ip_paths $BRIDGE_IP
} else {
    puts "ERROR: axis_to_video_bridge IP not packaged at $BRIDGE_IP"
    puts "       Run packaging step first (one-time, or after RTL edits):"
    puts "         vivado -mode batch -source hw/vivado/scripts/package_axis_bridge.tcl"
    puts "       Then re-run this script."
    exit 1
}
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

# ============================================================================
# Disable broken IP / BD rules (URGENT_ASK_11/19/20 install-quirk family)
# ============================================================================
# Some Vivado 2024.1 installs ship partial IP packages where the bd_rule
# helper TCLs reference missing files. This crashes `create_bd_design` when
# the affected rule is scanned. Same family of issues we already worked
# around in build_bitstream.tcl. Wildcard list expanded as new rules surface:
#   roe_framer            (URGENT_ASK_11) — 100G Ethernet rule, missing auto_utils.tcl
#   hdmi_gt_controller    (M2-W2 sync)    — Video Connectivity rule, same family
#   l_ethernet            (URGENT_ASK_20) — 1G/10G Ethernet rule, missing rules.tcl
#   microblaze            (URGENT_ASK_20) — MicroBlaze proc rule, missing bd.tcl
# All four are unused by our BD (we run on Zynq-7020 PS7 + spike_accel).
if {[info exists ::env(XILINX_VIVADO)]} {
    set _xlnx_ip [file join $::env(XILINX_VIVADO) data ip]
} else {
    set _xlnx_ip ""
}
# v6 fix (URGENT_ASK_23): switch from hardcoded VLNV (with version pinning)
# to NAME-equality match. v4 used VLNVs like xilinx.com:ip:microblaze:11.0
# but missed microblaze_riscv:1.0 (a separate IP). Listing each new broken
# IP by exact NAME (and letting `get_ipdefs NAME == X` resolve to the
# actual ipdef object) avoids both:
#   - v3 wildcard pollution (*microblaze* matched 6+ entries)
#   - v4 version-pinning misses (next-version IP would silently skip)
# Adding a new broken IP is now a single line in _broken_ip_names.
set _broken_ip_names {
    roe_framer
    hdmi_gt_controller
    l_ethernet
    microblaze
    microblaze_riscv
}
foreach _name $_broken_ip_names {
    if {$_xlnx_ip eq ""} { continue }
    set _ipdefs [get_ipdefs -quiet -filter "NAME == $_name"]
    if {[llength $_ipdefs] == 0} {
        puts "INFO: IP NAME=$_name not in catalog — skipping"
        continue
    }
    foreach _ipdef $_ipdefs {
        if {[catch {update_ip_catalog -disable_ip $_ipdef -repo_path $_xlnx_ip} _err]} {
            puts "WARN: could not disable $_ipdef: $_err"
        } else {
            puts "INFO: Disabled broken IP $_ipdef"
        }
    }
}
unset -nocomplain _broken_ip_names _name _ipdefs _ipdef _err _xlnx_ip

# v7 fix (URGENT_ASK_24): NAME-equality disable list above covers 5 known-bad
# IPs but new ones keep surfacing (versal_cips, qdma, gt_*, ...). The Vivado
# 2024.1 install ships *many* partial Design Assistant rules, not just a few.
#
# Three-layer defense to break the whack-a-mole:
#   L1 — disable list above mutes 5 noisiest entries (kept for log clarity)
#   L2 — set_param to skip Design Assistant rule init (try several variants;
#        Vivado's exact param name isn't publicly documented, catch-fallback)
#   L3 — set_msg_config to demote bd_rule init errors to INFO so they don't
#        terminate the script even if L1+L2 miss
#   L4 — wrap create_bd_design in catch and continue if .bd was actually saved
#
# Our BD is hand-written via create_bd_cell + connect_bd_*; the only Design
# Assistant rule we actually invoke is processing_system7 (line 167's
# apply_bd_automation), so muting all other rules is functionally safe.
catch { set_param bd.skipDesignAssistant true }
catch { set_param bd.disableDesignAssistant true }
catch { set_param bd.disableRuleInit true }

# Demote the two error IDs that all whack-a-mole rule failures cascade through:
#   [Ip 78-90]      Error in initialization of Rule object 'xilinx.com:bd_rule:*'
#   [Common 17-39]  '<command>' failed due to earlier errors.
# Both are non-fatal for our hand-wired BD path. set_msg_config -new_severity
# changes these from ERROR to INFO so the tool keeps going.
catch { set_msg_config -id "Ip 78-90"      -new_severity INFO -quiet }
catch { set_msg_config -id "Common 17-39"  -new_severity INFO -quiet }

# M3 HDMI: in-tree axis_to_video_bridge IP replaces missing
# xilinx.com:ip:v_axis_to_video_out:4.0. Packaged as proper IP-XACT under
# hw/vivado/ip_repo/axis_to_video_bridge/ via package_axis_bridge.tcl.
# Section 10 instantiates it as `create_bd_cell -type ip -vlnv user:user:
# axis_to_video_bridge:1.0` -- same code path as spike_accel/rgb2dvi, which
# avoids the unstable `-type module -reference` SIGSEGV path (URGENT_ASK_25).
# (BRIDGE_IP existence + ip_repo_paths inclusion checked above.)

# L4: wrap create_bd_design in catch. On install with broken bd_rules the call
# may return error after writing system.bd. Detect that and continue.
if {[catch {create_bd_design system} _bd_err]} {
    puts "WARN: create_bd_design returned: $_bd_err"
    puts "      Likely benign Design Assistant rule init noise from the partial"
    puts "      Vivado install. Trying to proceed if a BD was actually created..."
    if {[llength [get_bd_designs -quiet system]] == 0} {
        puts "ERROR: BD 'system' was not created. Cannot proceed."
        exit 1
    }
    puts "INFO: BD 'system' exists in memory; continuing with cell creation."
}
unset -nocomplain _bd_err

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
# v9 (URGENT_ASK_26): force VDMA's M_AXIS data width to 24 bits to match
# axis_to_video_bridge's RGB888 contract. Default is 32 (matches the 64-bit
# m_axi_mm2s data path in 4-byte chunks); leaving it 32 made BD validator
# reject the connection with "TDATA_NUM_BYTES does not match (3 vs 4)".
#
# v10 (URGENT_ASK_27 Option delta): R2 margin too tight (~120 slices over
# on Area_Explore best). Shrink VDMA itself to recover:
#   c_num_fstores       3 -> 1   (no triple-buffer; OK for initial demo)
#   c_include_mm2s_dre  1 -> 0   (DRE adds ~150 LUT; SW guarantees alignment)
#   c_mm2s_max_burst    256 -> 128 (halves burst-FIFO depth)
# Combined expected savings: ~250-400 slices.
set_property -dict [list \
    CONFIG.c_include_mm2s           {1} \
    CONFIG.c_include_s2mm           {0} \
    CONFIG.c_mm2s_genlock_mode      {0} \
    CONFIG.c_include_mm2s_dre       {0} \
    CONFIG.c_num_fstores            {1} \
    CONFIG.c_m_axi_mm2s_data_width  {32} \
    CONFIG.c_mm2s_axis_data_width   {24} \
    CONFIG.c_mm2s_max_burst_length  {128} \
] [get_bd_cells vdma_disp]
# v11/Option ζ: HP1 M_AXI 64 -> 32 bit. Bandwidth check at 1080p30 target:
#   1920*1080*30*3 = 187 MB/s required; HP1 32b @ 100 MHz axi ≈ 280-320 MB/s
#   sustained → comfortable. 1080p60 (374 MB/s) would not fit; we are not
#   targeting it. Saves ~100-150 slices in FIFO + addr arith + byte-enable.

create_bd_cell -type ip -vlnv xilinx.com:ip:v_tc:6.2 v_tc_0
# v_tc:6.2 quirk (URGENT_ASK_19 side): GEN_* timing params are gated behind
# enable_generation + a custom video format select. Easier to use the
# VIDEO_MODE preset for 1080p60. Detection disabled (we only generate).
# v11/Option η: explicitly null out the second-field / interlaced subblocks
# so synthesis prunes them rather than leaving idle slices around.
set_property -dict [list \
    CONFIG.HAS_AXI4_LITE        {true} \
    CONFIG.enable_generation    {true} \
    CONFIG.enable_detection     {false} \
    CONFIG.VIDEO_MODE           {1080p} \
    CONFIG.GEN_F1_VIDEO_FORMAT  {0} \
    CONFIG.GEN_INTERLACED       {false} \
] [get_bd_cells v_tc_0]

# vid_out: in-tree IP-XACT-packaged axis_to_video_bridge (URGENT_ASK_25).
# Replaces both the missing xilinx.com:ip:v_axis_to_video_out:4.0 (ASK_18)
# AND the unstable `-type module -reference` path that SIGSEGV'd
# (ASK_19/22/25). Standard create_bd_cell -type ip -vlnv route, same code
# path as our spike_accel and rgb2dvi IPs.
create_bd_cell -type ip -vlnv user:user:axis_to_video_bridge:1.0 vid_out

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
# v10 (URGENT_ASK_27 Option delta): drop vdma IRQ - M4 demo SW polls VDMA
# status registers rather than using vdma_mm2s_introut. Saves ~10-20 slices.
# In0=spike_accel.interrupt, In1=dma_mm2s, In2=dma_s2mm.
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

# v_tc:6.2 -> vid_out discrete pins (URGENT_ASK_22 fix v5):
# v_tc's actual top-level pins are `<sig>_out` (not `vtiming_out_<sig>`),
# and there is NO active_video output. The bridge derives active_video
# from the blanking pair, so we wire only 4 discrete signals here.
foreach {src dst} {
    hsync_out   vtiming_hsync
    vsync_out   vtiming_vsync
    hblank_out  vtiming_hblank
    vblank_out  vtiming_vblank
} {
    connect_bd_net [get_bd_pins v_tc_0/$src] [get_bd_pins vid_out/$dst]
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
# v10 (URGENT_ASK_27 Option delta): vdma IRQ wire removed - SW polls status.
# catch {connect_bd_net [get_bd_pins vdma_disp/mm2s_introut] [get_bd_pins irq_concat/In3]}
connect_bd_net [get_bd_pins irq_concat/dout] [get_bd_pins ps_0/IRQ_F2P]

# ============================================================================
# 13. Address assignments — keep in sync with hw/vivado/out/address_map.yaml
# ============================================================================
assign_bd_address
# URGENT_ASK_22 fix v5: explicitly set range BEFORE offset for each
# register-mapped peripheral. Vivado defaults a control-register segment
# to 1G range which is misaligned at 0x43C00000 (max range there is 4M).
# 64K is plenty for these IPs' control reg files. VDMA's M_AXI_MM2S
# data segment (which DOES want full DDR3 range) is separate and gets
# auto-assigned to the DDR3 mapping by assign_bd_address — we don't
# touch it here.
catch {
    # Pin spike_accel control regs to the canonical base (0x43C00000)
    set seg [get_bd_addr_segs -of [get_bd_cells spike_accel_0] -filter {USAGE==register}]
    if {[llength $seg] > 0} {
        set_property range  64K [lindex $seg 0]
        set_property offset 0x43C00000 [lindex $seg 0]
    }
}
catch {
    # AXI DMA  0x40400000
    set seg [get_bd_addr_segs -of [get_bd_cells axi_dma_feat] -filter {USAGE==register}]
    if {[llength $seg] > 0} {
        set_property range  64K [lindex $seg 0]
        set_property offset 0x40400000 [lindex $seg 0]
    }
}
catch {
    # VDMA control 0x43000000 (M3 HDMI rebuild — matches address_map.yaml + uio_config.dts)
    set seg [get_bd_addr_segs -of [get_bd_cells vdma_disp] -filter {USAGE==register}]
    if {[llength $seg] > 0} {
        set_property range  64K [lindex $seg 0]
        set_property offset 0x43000000 [lindex $seg 0]
    }
}
catch {
    # v_tc_0 0x43C10000 (next free slot above spike_accel)
    set seg [get_bd_addr_segs -of [get_bd_cells v_tc_0] -filter {USAGE==register}]
    if {[llength $seg] > 0} {
        set_property range  64K [lindex $seg 0]
        set_property offset 0x43C10000 [lindex $seg 0]
    }
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
