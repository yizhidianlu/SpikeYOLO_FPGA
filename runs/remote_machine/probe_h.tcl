# probe_h.tcl — `mrd -memmap` via DAP MEM-AP, no CPU halt.
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
puts "PROBE_H halted cold, PC=[rrd pc]"

fpga -file $::W9_BIT
ps7_init
ps7_post_config

mwr -bin -file $::W9_WEIGHTS $::W9_WEIGHTS_ADDR [expr $::W9_WEIGHTS_BYTES / 4]
puts "PROBE_H: weights loaded; first 4 u32:"
mrd $::W9_WEIGHTS_ADDR 4

dow $::W9_ELF
puts "PROBE_H: elf loaded, PC=[rrd pc]"
con
after 3000

puts "==Now CPU is running; try mrd -memmap (DAP MEM-AP)=="
foreach addr {0x10845400 0x10845404 0x10845408 0x1084540C} {
    set rv "<fail>"
    catch { set rv [mrd -memmap $addr] } _err
    puts "memmap @ $addr: $rv  (err=$_err)"
}

puts "==Output buf first 16 bytes==:"
catch { puts [mrd -memmap 0x10840000 4] }

puts "==Dump full 21504-byte feat_out via -memmap=="
if {[catch {mrd -memmap -bin -file C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/runs/remote_machine/w9_pbt_feat_out.bin 0x10840000 [expr 21504 / 4]} _err]} {
    puts "memmap dump fail: $_err"
} else {
    puts "memmap dump OK"
}
exit 0
