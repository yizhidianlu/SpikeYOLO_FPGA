# probe_uart.tcl — UART1 hardware-level probe per Main 2026-05-26T14:25.
# Halt CPU BEFORE downloading any ELF so JTAG mrd is free.

source C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/sw/baremetal/spike_accel_w9_smoke/xsdb_setup.tcl
set ::W9_PS7_INIT [file normalize "C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/vitis_workspace/spike_zybo_baremetal_plat/export/spike_zybo_baremetal_plat/hw/ps7_init.tcl"]
source $::W9_PS7_INIT

connect
targets -set -filter {name =~ "*Cortex-A9 MPCore #0*"}
rst -system
after 200
fpga -file $::W9_BIT
ps7_init
ps7_post_config

stop
puts "INFO: CPU halted, PC = [rrd pc]"

foreach {name addr} {
    UART_CLK_CTRL  0xF8000154
    APER_CLK_CTRL  0xF800014C
    MIO_PIN_48     0xF8000730
    MIO_PIN_49     0xF8000734
    UART1_CR       0xE0001000
    UART1_BAUDGEN  0xE0001018
    UART1_SR       0xE000102C
} {
    set val "<read-fail>"
    catch { set val [mrd -force $addr] }
    puts "PROBE $name @ $addr  =>  $val"
}
exit 0
