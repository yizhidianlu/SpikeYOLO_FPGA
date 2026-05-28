# probe_i.tcl — HW breakpoint at WFI. CPU auto-halts when reached.
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

# Set HW breakpoints at both WFI instructions (timeout and success paths)
puts "==Setting HW BP at WFI (success path 0x100e0c)==:"
catch { bpadd -addr 0x100e0c } _bp1
puts "bp1: $_bp1"
catch { bpadd -addr 0x100d84 } _bp2
puts "bp2 (timeout path): $_bp2"
catch { bplist }

con
# Wait long enough for accelerator to finish and CPU to hit WFI
after 10000

puts "==Check state after wait=="
state
puts "PC = [rrd pc]"

# CPU should be at BP. mrd should work now.
puts "==status block==:"
catch { puts [mrd 0x10845400 4] }

puts "==Dump 21504 bytes from OUTPUT_BUF==:"
if {[catch {mrd -bin -file C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/runs/remote_machine/w9_pbt_feat_out.bin 0x10840000 [expr 21504 / 4]} _err]} {
    puts "dump fail: $_err"
} else {
    puts "dump OK"
}
exit 0
