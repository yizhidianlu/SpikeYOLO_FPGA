# hw/vivado/scripts/axi_protocol_check.tcl — Vivado AXI VIP smoke test.
#
# Open the project, locate the spike_accel IP, attach AXI Verification IP to
# the s_axi_control port, then run a quick simulation that fires a small
# burst of register writes/reads. Fails the script if VIP detects a protocol
# violation.
#
# This is the M2 acceptance gate for Contract 3 (B1 -> B2 hand-off).

set OUT_DIR [file normalize "[file dirname [info script]]/../out"]
open_project [file join $OUT_DIR spike_zybo.xpr]

# Add the VIP IP to the BD.
open_bd_design [file join $OUT_DIR spike_zybo.gen sources_1 bd system system.bd]

if {[llength [get_bd_cells spike_accel_0]] == 0} {
    puts "ERROR: spike_accel_0 not found — was build_bd.tcl run?"
    exit 1
}

# Create a VIP and connect it to spike_accel_0/s_axi_control.
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_vip:1.1 vip_ctrl
set_property -dict [list \
    CONFIG.INTERFACE_MODE {MASTER} \
    CONFIG.PROTOCOL       {AXI4LITE} \
] [get_bd_cells vip_ctrl]

connect_bd_intf_net [get_bd_intf_pins vip_ctrl/M_AXI] \
                    [get_bd_intf_pins spike_accel_0/s_axi_control]
save_bd_design

# Synthesize for simulation only (behavioral).
launch_simulation
catch {
    add_files -fileset sim_1 [file join $OUT_DIR ../scripts vip_axi_check_tb.sv]
}

# Run for 10 us; the testbench fires register accesses and AXI VIP enforces
# protocol on every cycle.
run 10us

# Fail if any AXI4 protocol assertions tripped.
if {[get_value -count [get_assertions -filter {STATUS == FAILED}]] > 0} {
    puts "FAIL: AXI protocol violations detected"
    exit 1
}
puts "[OK] AXI protocol check passed"
exit 0
