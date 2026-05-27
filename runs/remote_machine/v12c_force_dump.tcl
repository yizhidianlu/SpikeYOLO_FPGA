# v12c_force_dump.tcl — read DDR status + output BEFORE attempting any halt.
# JTAG can read PS DDR via the PSU DDR controller even if CPU is in WFI.
source C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/sw/baremetal/spike_accel_w9_smoke/xsdb_setup.tcl
set ::W9_ELF [file normalize "C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/vitis_workspace/spike_accel_w9_smoke/Debug/spike_accel_w9_smoke.elf"]
set ::W9_PS7_INIT [file normalize "C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/vitis_workspace/spike_zybo_baremetal_plat/hw/ps7_init.tcl"]
source $::W9_PS7_INIT

connect
targets -set -filter {name =~ "*Cortex-A9 MPCore #0*"}
rst -system
after 200
fpga -file $::W9_BIT
ps7_init
ps7_post_config

stop
mwr -bin -file $::W9_WEIGHTS $::W9_WEIGHTS_ADDR [expr $::W9_WEIGHTS_BYTES / 4]
dow $::W9_ELF
puts "PC pre-con: [rrd pc]"
con
after 8000

# Try `-force` read while CPU running
puts "==Status block @ 0x10845400 (CPU running):"
foreach addr {0x10845400 0x10845404 0x10845408 0x1084540C} {
    if {[catch {set v [mrd -force $addr]} _err]} {
        puts "$addr: <read-fail> $_err"
    } else {
        puts "$addr: $v"
    }
}

puts "==Output buf first 16 bytes @ 0x10840000 (CPU running):"
catch { puts [mrd -force 0x10840000 4] }

# Save 21504-byte feat blob via mrd -force
if {[catch {mrd -force -bin -file C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/runs/remote_machine/w9_pbt_feat_out.bin 0x10840000 [expr 21504 / 4]} _err]} {
    puts "feat_out dump fail (CPU still running): $_err"
    # Try halt + retry
    catch { stop }
    after 500
    catch { mrd -bin -file C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/runs/remote_machine/w9_pbt_feat_out.bin 0x10840000 [expr 21504 / 4] }
}
puts "PC final: [rrd pc]"
exit 0
