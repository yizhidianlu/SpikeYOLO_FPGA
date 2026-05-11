# hw/vivado/scripts/axi_protocol_check.tcl — Vivado AXI VIP smoke test.
#
# Open the project, attach AXI VIPs to the three protocol-relevant interfaces
# in the BD, run a short behavioral simulation, and fail if any AXI assertion
# trips. This is the M2 acceptance gate for Contract 3 (B1 -> B2 hand-off)
# and the M2-W2 gate for Contract 4 (B2 -> C2/C3 data path).
#
# VIPs attached:
#   1. spike_accel_0/s_axi_control  (AXI4-Lite master VIP)  — Contract 3
#   2. spike_accel_0/m_axi_gmem     (AXI4 monitor)          — Contract 3
#   3. axi_dma_feat/M_AXI_MM2S      (AXI4 monitor)          — Contract 4
#
# Output:
#   hw/vivado/out/axi_protocol_check.rpt — summary (PASS/FAIL + violation list)

set OUT_DIR [file normalize "[file dirname [info script]]/../out"]
set RPT     [file join $OUT_DIR axi_protocol_check.rpt]
file mkdir $OUT_DIR
set rfp [open $RPT w]
proc rpt {fp s} {puts $fp $s; puts $s}

rpt $rfp "[axi_protocol_check] opening project..."
open_project [file join $OUT_DIR spike_zybo.xpr]
open_bd_design [file join $OUT_DIR spike_zybo.gen sources_1 bd system system.bd]

if {[llength [get_bd_cells spike_accel_0]] == 0} {
    rpt $rfp "ERROR: spike_accel_0 not found — was build_bd.tcl run?"
    close $rfp
    exit 1
}

# 1. Master VIP on s_axi_control (drives register accesses).
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_vip:1.1 vip_ctrl
set_property -dict [list \
    CONFIG.INTERFACE_MODE {MASTER} \
    CONFIG.PROTOCOL       {AXI4LITE} \
] [get_bd_cells vip_ctrl]
connect_bd_intf_net [get_bd_intf_pins vip_ctrl/M_AXI] \
                    [get_bd_intf_pins spike_accel_0/s_axi_control]

# 2. Monitor VIP on spike_accel m_axi_gmem (Contract 3 AXI4-MM master).
if {[llength [get_bd_intf_pins spike_accel_0/m_axi_gmem]] > 0} {
    create_bd_cell -type ip -vlnv xilinx.com:ip:axi_vip:1.1 vip_gmem
    set_property -dict [list \
        CONFIG.INTERFACE_MODE {MONITOR} \
        CONFIG.PROTOCOL       {AXI4} \
    ] [get_bd_cells vip_gmem]
    connect_bd_intf_net [get_bd_intf_pins vip_gmem/M_AXI] \
                        [get_bd_intf_pins spike_accel_0/m_axi_gmem]
} else {
    rpt $rfp "WARN: spike_accel_0/m_axi_gmem absent — Contract 3 monitor skipped"
}

# 3. Monitor VIP on axi_dma_feat MM2S (Contract 4 data path).
if {[llength [get_bd_intf_pins axi_dma_feat/M_AXI_MM2S]] > 0} {
    create_bd_cell -type ip -vlnv xilinx.com:ip:axi_vip:1.1 vip_dma
    set_property -dict [list \
        CONFIG.INTERFACE_MODE {MONITOR} \
        CONFIG.PROTOCOL       {AXI4} \
    ] [get_bd_cells vip_dma]
    connect_bd_intf_net [get_bd_intf_pins vip_dma/M_AXI] \
                        [get_bd_intf_pins axi_dma_feat/M_AXI_MM2S]
} else {
    rpt $rfp "WARN: axi_dma_feat/M_AXI_MM2S absent — Contract 4 monitor skipped"
}

save_bd_design

# Bring in the testbench (drives vip_ctrl with smoke writes/reads).
catch {add_files -fileset sim_1 [file join $OUT_DIR ../scripts vip_axi_check_tb.sv]}

launch_simulation
run 10us

set fails [get_value -count [get_assertions -filter {STATUS == FAILED}]]
if {$fails > 0} {
    rpt $rfp "FAIL: $fails AXI protocol violations detected"
    foreach a [get_assertions -filter {STATUS == FAILED}] {
        rpt $rfp "  - [get_property NAME $a]"
    }
    close $rfp
    exit 1
}
rpt $rfp "[OK] AXI protocol check passed (vip_ctrl + vip_gmem + vip_dma)"
close $rfp
exit 0
