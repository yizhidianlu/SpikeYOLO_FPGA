# w9_jtag_harvest.tcl — UART-bypass W9 smoke harvest.
# Loads bitstream + ps7_init + weights + JTAG-only ELF, runs 5s, halts,
# reads 4-word status block + 21504-byte output blob via JTAG mrd.

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

# Halt before loading weights / elf so JTAG operations are deterministic.
stop
puts "HARVEST: CPU halted (pre-load), PC = [rrd pc]"

mwr -bin -file $::W9_WEIGHTS $::W9_WEIGHTS_ADDR [expr $::W9_WEIGHTS_BYTES / 4]
puts "HARVEST: weights loaded; first 4 u32:"
mrd $::W9_WEIGHTS_ADDR 4

dow $::W9_ELF
puts "HARVEST: elf loaded, PC = [rrd pc]"

# Run for 5 seconds (accelerator typically completes well within 1s @ 90MHz).
con
after 5000

# CPU should be in WFI now; halt should succeed.
if {[catch {stop} _err]} {
    puts "HARVEST WARN: stop failed: $_err — try again"
    after 1000
    catch {stop}
}
puts "HARVEST: CPU halted (post-run), PC = [rrd pc]"

# Read the 4-word status block at OUTPUT_BUF_PHYS + 0x5400 = 0x10845400.
puts "HARVEST: status block @ 0x10845400 (4 u32):"
mrd 0x10845400 4

# Dump 21504-byte feat_out blob from OUTPUT_BUF_PHYS = 0x10840000.
mrd -bin -file C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/runs/remote_machine/w9_pbt_feat_out.bin 0x10840000 [expr 21504 / 4]
puts "HARVEST: dumped 21504 bytes from 0x10840000 -> runs/remote_machine/w9_pbt_feat_out.bin"

# First 16 bytes of output for log-level sanity.
puts "HARVEST: first 16 output bytes:"
mrd 0x10840000 4

exit 0
