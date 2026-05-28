# probe_i2.tcl — ELF has bkpt at end; CPU auto-halts so JTAG mrd works.
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

# Accelerator inference is fast; bkpt should be hit within a few seconds
after 8000

puts "==state after con+wait==:"
state
catch { puts "PC = [rrd pc]" }

# If CPU is halted at bkpt, mrd works directly. If not, try stop.
puts "==Try mrd status block @ 0x10845400==:"
if {[catch {set rv [mrd 0x10845400 4]} _err]} {
    puts "mrd fail: $_err — attempting stop"
    catch {stop}
    catch { puts [mrd 0x10845400 4] }
} else {
    puts "mrd OK: $rv"
}

puts "==Dump 21504 bytes from OUTPUT_BUF for host reverify==:"
if {[catch {mrd -bin -file C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/runs/remote_machine/w9_pbt_feat_out.bin 0x10840000 [expr 21504 / 4]} _err]} {
    puts "dump fail: $_err"
} else {
    puts "dump OK — first 16 bytes:"
    catch { puts [mrd 0x10840000 4] }
}
exit 0
