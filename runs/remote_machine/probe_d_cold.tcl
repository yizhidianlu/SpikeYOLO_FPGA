# probe_d_cold.tcl — cold bitstream load, halt CPU immediately. NO ps7_init,
# NO ELF download, NO con. Pure JTAG halt sanity check.
connect
targets -set -filter {name =~ "*Cortex-A9 MPCore #0*"}
puts "==state pre-fpga=="
state
puts "==fpga -file=="
fpga -file C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/hw/vivado/out/system.bit
puts "==state post-fpga=="
state
puts "==attempt halt=="
if {[catch {stop} _err]} {
    puts "STOP FAIL: $_err"
} else {
    puts "STOP OK"
}
puts "PC = [rrd pc]"
puts "CPSR = [rrd cpsr]"
exit 0
