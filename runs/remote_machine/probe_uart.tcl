# probe_uart.tcl — after w9_smoke_run, attempt to read UART1 status reg
# and OUTPUT_BUF_PHYS via xsdb without halting (mrd should work read-only
# even on running CPU in some Vitis builds).
source C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/sw/baremetal/spike_accel_w9_smoke/xsdb_setup.tcl
set ::W9_ELF [file normalize "C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/vitis_workspace/spike_accel_w9_smoke/Debug/spike_accel_w9_smoke.elf"]
set ::W9_PS7_INIT [file normalize "C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/vitis_workspace/spike_zybo_baremetal_plat/export/spike_zybo_baremetal_plat/hw/ps7_init.tcl"]
source $::W9_PS7_INIT

connect
targets -set -filter {name =~ "*Cortex-A9 MPCore #0*"}
rst -system
after 200
fpga -file $::W9_BIT
ps7_init
ps7_post_config

# Halt BEFORE downloading the ELF (so we can stop later)
stop
puts "INFO: CPU halted, PC = [rrd pc]"

mwr -bin -file $::W9_WEIGHTS $::W9_WEIGHTS_ADDR [expr $::W9_WEIGHTS_BYTES / 4]
puts "INFO: weights written, first 4 u32:"
mrd $::W9_WEIGHTS_ADDR 4

# Probe UART1 control register before downloading ELF (should be valid)
puts "INFO: UART_1 control reg (0xE0001000) BEFORE elf:"
mrd 0xE0001000 4

dow $::W9_ELF
puts "INFO: elf loaded, PC = [rrd pc]"
con
after 5000
# Try halt
puts "INFO: attempting halt…"
if {[catch {stop} _err]} {
    puts "WARN: stop failed: $_err"
    puts "INFO: trying mrd anyway"
}
puts "INFO: post-run UART_1 status:"
catch { puts "[mrd 0xE000102C 1]" }
puts "INFO: post-run OUTPUT_BUF_PHYS (0x10840000) first 16 bytes:"
catch { puts "[mrd 0x10840000 4]" }
puts "INFO: SA_REG_BASE (0x43C00000) first 8 regs:"
catch { puts "[mrd 0x43C00000 8]" }
puts "INFO: PC after run:"
catch { puts "[rrd pc]" }
exit 0
