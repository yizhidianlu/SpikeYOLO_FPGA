# probe_h4.tcl — try -address-space PA with running CPU
source C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/sw/baremetal/spike_accel_w9_smoke/xsdb_setup.tcl
set ::W9_ELF [file normalize "C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/vitis_workspace/spike_accel_w9_smoke/Debug/spike_accel_w9_smoke.elf"]
set ::W9_PS7_INIT [file normalize "C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/vitis_workspace/spike_zybo_baremetal_plat/hw/ps7_init.tcl"]
source $::W9_PS7_INIT

connect
targets -set -filter {name =~ "*Cortex-A9 MPCore #0*"}
catch {rst -dap}
after 200
catch {rst -srst}
after 500
catch {targets -set -filter {name =~ "*Cortex-A9 MPCore #0*"}}
stop
fpga -file $::W9_BIT
ps7_init
ps7_post_config
mwr -bin -file $::W9_WEIGHTS $::W9_WEIGHTS_ADDR [expr $::W9_WEIGHTS_BYTES / 4]
dow $::W9_ELF
con
after 3000

puts "==Try mrd -address-space PA with running CPU=="
set rv "<fail>"
if {[catch {set rv [mrd -address-space PA 0x10845400 4]} _err]} {
    puts "PA fail: $_err"
} else {
    puts "PA OK: $rv"
}

# Maybe PSU APU target has separate address spaces?
puts "==targets list==:"
targets
puts "==target -info on current=="
catch { target }

# Try direct DAP MEM-AP via raw address (Cortex-A9 typically AP1)
puts "==Try mrd with -force --? not valid here. Use just mrd -force=="
catch {puts [mrd -force 0x10845400 4]}

# Dump via PA
puts "==Dump via PA==:"
if {[catch {mrd -address-space PA -bin -file C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/runs/remote_machine/w9_pbt_feat_out.bin 0x10840000 [expr 21504 / 4]} _err]} {
    puts "PA dump fail: $_err"
} else {
    puts "PA dump OK"
}
exit 0
